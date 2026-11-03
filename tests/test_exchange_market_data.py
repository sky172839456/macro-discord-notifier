import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import exchange_market_data as exchange
import market_brief_data as source
import market_brief_v2 as brief
import summary_notifier as summary
import derivatives_notifier as derivatives
from datetime import timedelta


class ExchangeMarketTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, 0, tzinfo=timezone.utc)
        self.ts = int(self.now.timestamp()*1000)

    def bg(self, url):
        symbol = 'ETHUSDT' if 'ETHUSDT' in url else 'BTCUSDT'
        if '/spot/market/tickers' in url:
            data = [dict(symbol=symbol, lastPr='100', change24h='.01', high24h='110', low24h='90', quoteVolume='1000', ts=self.ts)]
        elif 'open-interest' in url:
            data = {'ts': self.ts, 'openInterestList': [{'symbol': symbol, 'size': '20'}]}
        elif '/mix/market/ticker' in url:
            data = [dict(symbol=symbol, markPrice='101', lastPr='100', change24h='.01', quoteVolume='1000', ts=self.ts)]
        elif 'current-fund-rate' in url:
            data = [dict(symbol=symbol, fundingRate='0', fundingRateInterval='8', nextUpdate=self.ts+8*3600000)]
        elif 'history-fund-rate' in url:
            data = [dict(symbol=symbol, fundingRate='0', fundingTime=self.ts-i*8*3600000) for i in range(22)]
        elif 'candles' in url:
            data = [[self.ts-i*exchange.DAY, '100', '110', '90', '105', '2', '200', '200'] for i in range(8)]
        else:
            raise AssertionError(url)
        return {'code': '00000', 'requestTime': self.ts, 'data': data}

    def bn(self, url):
        if 'premiumIndex' in url:
            return dict(symbol='BTCUSDT', markPrice='101', lastFundingRate='-.0001', nextFundingTime=self.ts+8*3600000, time=self.ts)
        if 'openInterest' in url:
            return dict(symbol='BTCUSDT', openInterest='20', time=self.ts)
        if 'fundingInfo' in url:
            return []
        if 'fundingRate' in url:
            return [dict(symbol='BTCUSDT', fundingTime=self.ts-i*8*3600000, fundingRate='0') for i in (1, 0)]
        return dict(symbol='BTCUSDT', lastPrice='100', priceChangePercent='1', highPrice='110', lowPrice='90',
                    quoteVolume='1000', closeTime=self.ts)

    def test_bg_decimal_change_and_usdt_base_coin_notional(self):
        spot = exchange.spot(self.bg, 'BTC', 'Bitget', self.now)
        row = exchange.contract(self.bg, 'BTC', 'Bitget', self.now)
        self.assertEqual(spot['change_24h'], 1)
        self.assertEqual(row['oi_usd'], 2020)
        self.assertEqual(row['oi_ccy'], 20)
        self.assertEqual(row['funding_rate'], 0)
        self.assertEqual(row['quote_currency'], 'USDT')
        self.assertEqual(row['funding_interval_hours'], 8)

    def test_binance_percent_not_multiplied_and_interval_observed(self):
        self.assertEqual(exchange.spot(self.bn, 'BTC', 'Binance', self.now)['change_24h'], 1)
        row = exchange.contract(self.bn, 'BTC', 'Binance', self.now)
        self.assertAlmostEqual(row['funding_rate'], -.01)
        self.assertTrue(row['interval_observed'])
        self.assertEqual(row['funding_interval_hours'], 8)

    def test_geoblock_uses_other_approved_venue_once(self):
        calls = []
        def fetch(venue):
            calls.append(venue)
            if venue == 'Bitget':
                raise HTTPError('https://api.bitget.com', 451, 'restricted', {}, None)
            return {'source': venue}
        row = exchange.prefer(fetch)
        self.assertEqual(calls, ['Bitget', 'Binance'])
        self.assertIn('451', row['fallback_reason'])

    def test_missing_nonfinite_bool_negative_size_stale_and_symbol_rejected(self):
        for value in ('', None, 'nan', 'inf', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exchange.number(value)
        for kind in ('size', 'timestamp', 'symbol'):
            def invalid(url):
                p = self.bg(url)
                if 'open-interest' in url:
                    if kind == 'size': p['data']['openInterestList'][0]['size'] = '-1'
                    if kind == 'symbol': p['data']['openInterestList'][0]['symbol'] = 'BTCUSD'
                    if kind == 'timestamp': p['data']['ts'] -= 3600000
                return p
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                exchange.contract(invalid, 'BTC', 'Bitget', self.now)

    def test_seven_closed_utc_days_excludes_open_candle(self):
        row = exchange.weekly_prices(self.bg, 'BTC', self.now)
        self.assertEqual(row['end_timestamp'], self.ts/1000)
        self.assertEqual(row['start_timestamp'], self.ts/1000-7*86400)
        self.assertAlmostEqual(row['change_7d'], 5)
        self.assertEqual(row['volume_7d'], 1400)

    def test_missing_or_conflicting_candle_rejected(self):
        for kind in ('missing', 'conflict'):
            def invalid(url):
                p = self.bg(url)
                if kind == 'missing': p['data'].pop()
                else: p['data'].append([self.ts-exchange.DAY, '100', '110', '90', '106', '2', '200', '200'])
                return p
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                exchange.daily_candles(invalid, 'BTC', 'Bitget', now=self.now)

    def test_weekly_settled_zero_is_real_and_duplicates_not_counted(self):
        current = exchange.contract(self.bg, 'BTC', 'Bitget', self.now)
        def duplicates(url):
            p = self.bg(url)
            p['data'].append(copy.deepcopy(p['data'][0]))
            return p
        row = exchange.settled_week(duplicates, 'BTC', current, self.now)
        self.assertEqual(row['samples'], 22)
        self.assertEqual(row['funding_avg_7d'], 0)

    def test_millisecond_settlement_offsets_are_not_missing_periods(self):
        current = exchange.contract(self.bg, 'BTC', 'Bitget', self.now)
        def jitter(url):
            p = self.bg(url)
            for i, row in enumerate(p['data']):
                row['fundingTime'] += i % 6
            return p
        row = exchange.settled_week(jitter, 'BTC', current, self.now)
        self.assertEqual(row['samples'], 22)
        self.assertEqual(row['funding_avg_7d'], 0)

    def test_weekly_missing_middle_or_edges_never_substituted_with_current_rate(self):
        current = exchange.contract(self.bg, 'BTC', 'Bitget', self.now)
        for kind in ('middle', 'edge'):
            def invalid(url):
                p = self.bg(url)
                if kind == 'middle': p['data'].pop(10)
                else: p['data'] = p['data'][:10]
                return p
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                exchange.settled_week(invalid, 'BTC', current, self.now)

    def test_old_okx_or_other_venue_history_not_compared(self):
        row = exchange.contract(self.bg, 'BTC', 'Bitget', self.now)
        for scope in ('OKX BTC-USDT-SWAP', 'Binance BTCUSDT USDT-PERP'):
            data = {'derivatives': {'BTC': copy.deepcopy(row)}}
            old = {'derivatives': {'BTC': {**row, 'scope': scope, 'oi_ccy': 10, 'timestamp': self.ts/1000-86400}}}
            brief.add_context(data, [old], self.now)
            self.assertNotIn('oi_change_1d', data['derivatives']['BTC'])

    def test_full_live_shape_fits_daily_weekly_limits_and_labels_actual_source(self):
        data = {'crypto': {}, 'derivatives': {}, 'weekly_derivatives': {}}
        for coin in ('BTC', 'ETH'):
            data['crypto'][coin] = exchange.spot(self.bg, coin, 'Bitget', self.now)
            data['derivatives'][coin] = exchange.contract(self.bg, coin, 'Bitget', self.now)
            data['weekly_derivatives'][coin] = exchange.settled_week(self.bg, coin, data['derivatives'][coin], self.now)
        for weekly in (False, True):
            text = brief.contract_lines(data, self.now, weekly)
            self.assertLessEqual(len(text), 1024)
            self.assertIn('Bitget USDT永續', text)
            self.assertNotIn('美元', text)
            self.assertNotIn('OKX', text)
        self.assertIn('100.00 USDT', brief.price_lines(data, None, self.now, False))

    def test_partial_exchange_failures_keep_daily_and_legacy_weekly_renderable(self):
        data = {'crypto': {'BTC': {'error': 'unavailable'}}, 'derivatives': {'BTC': {'error': 'unavailable'}},
                'weekly_crypto': {'BTC': {'error': 'unavailable'}}, 'weekly_derivatives': {'BTC': {'error': 'unavailable'}}}
        card = brief.build_card('daily', self.now, None, None, [], None, data)
        self.assertIn('部分資料暫缺', card['description'])
        with patch.dict('os.environ', {'SLIM_NOTIFICATIONS': '0'}):
            card = summary.build_embed('weekly', self.now, None, None, [], None, data)
        self.assertTrue(card['fields'])

    def test_dormant_monitor_does_not_alert_on_exchange_switch(self):
        oldtime = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        state = {'snapshots': {s: [{'time': oldtime, 'scope': 'OKX '+s, 'price': 1, 'open_interest_usd': 1}] for s in derivatives.SYMBOLS}}
        def fetch(symbol):
            return dict(symbol=symbol, scope='Bitget '+symbol+' USDT-PERP', price=100, open_interest_usd=1000, funding_rate=0)
        with patch.object(derivatives, 'load_state', return_value=state), patch.object(derivatives, 'save_state'), patch.object(derivatives, 'fetch_ticker', side_effect=fetch), patch.object(derivatives, 'send_discord') as send:
            derivatives.run_monitor('https://discord.invalid/never-send')
        send.assert_not_called()
        self.assertEqual(state['snapshots']['BTCUSDT'][-1]['scope'], 'Bitget BTCUSDT USDT-PERP')

    def test_one_coin_failure_and_stablecoin_failure_dont_drop_valid_prices(self):
        def fake(url):
            if 'BTCUSDT' in url or 'coingecko' in url:
                raise RuntimeError('unavailable')
            return self.bg(url)
        with patch.object(source, 'get_json', side_effect=fake), patch.object(exchange, 'clock_ms', return_value=self.ts):
            coins, stable = source.crypto_snapshot()
        self.assertEqual(coins['ETH']['price'], 100)
        self.assertIn('error', coins['BTC'])
        self.assertEqual(stable, {})


if __name__ == '__main__':
    unittest.main()
