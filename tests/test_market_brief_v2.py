import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import market_brief_data as source
import market_brief_v2 as brief
import summary_notifier as summary
import crypto_news_notifier as news


class MarketBriefV2Tests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 0, tzinfo=timezone.utc)
        self.ts = self.now.timestamp()
        self.data = {'errors': {}, 'crypto': {'BTC': {'price': 80000, 'change_24h': 1.2}, 'ETH': {'price': 2500, 'change_24h': -.8}},
                     'global': {'market_cap': 2e12, 'market_cap_change_24h': 1, 'volume_24h': 1e11, 'btc_dominance': 55, 'timestamp': self.ts},
                     'sentiment': {'value': 50, 'classification': 'Neutral', 'timestamp': self.ts, 'previous_value': 45, 'previous_timestamp': self.ts-86400},
                     'derivatives': {s: {'oi_usd': 1e9, 'oi_ccy': 100, 'funding_rate': .01, 'funding_time': int((self.ts+3600)*1000), 'timestamp': self.ts,
                                         'rate_timestamp': self.ts, 'scope': f'OKX {s}-USDT-SWAP'} for s in ('BTC', 'ETH')},
                     'etf': {'date': self.now-timedelta(days=1), 'net_flow_musd': 120},
                     'eth_etf': {'date': self.now-timedelta(days=1), 'net_flow_musd': -30}}

    def card(self, period='daily', data=None, events=None):
        return brief.build_card(period, self.now, None, None, events or [], None, self.data if data is None else data)

    def text(self, card):
        return '\n'.join(f['value'] for f in card['fields'])

    def test_daily_six_sections_show_normal_sentiment_and_attribution(self):
        card = self.card()
        self.assertEqual(len(card['fields']), 6)
        text = self.text(card)
        for expected in ('50/100', '中性', '+5.00分', 'Alternative.me', 'BTC市占', 'OKX BTC／ETH USDT永續', 'ETF', '市場觀察'):
            self.assertIn(expected, text)
        self.assertNotIn('Neutral', text)

    def test_missing_sections_still_visible_and_never_default_to_zero(self):
        text = self.text(self.card(data={}))
        self.assertIn('合約資料暫缺', text)
        self.assertIn('恐慌貪婪指數暫缺', text)
        self.assertNotIn('0.00%', text)
        self.assertNotIn('0/100', text)

    def test_global_outlier_volume_is_hidden_without_hiding_valid_market_cap(self):
        raw = {'data': {'total_market_cap': {'usd': 2e12}, 'total_volume': {'usd': 7e14},
                        'market_cap_percentage': {'btc': 55}, 'market_cap_change_percentage_24h_usd': 1, 'updated_at': self.ts}}
        with patch.object(source, 'get_json', return_value=raw):
            data = source.global_snapshot()
        self.assertIsNone(data['volume_24h'])
        text = brief.global_lines({'global': data}, self.now)
        self.assertIn('2.00兆美元', text)
        self.assertIn('來源數值未確認', text)

    def test_stale_prices_do_not_leak_into_market_observation(self):
        for row in self.data['crypto'].values():
            row.update(source='CoinGecko', updated_at=(self.now-timedelta(days=1)).isoformat())
        text = self.text(self.card())
        self.assertNotIn('$80,000', text)
        self.assertNotIn('漲跌方向分化', text)

    def test_stale_sentiment_and_contracts_not_presented_as_current(self):
        data = copy.deepcopy(self.data)
        data['sentiment']['timestamp'] -= 3*86400
        data['global']['timestamp'] -= 4*3600
        for r in data['derivatives'].values():
            r['timestamp'] -= 3600
        text = self.text(self.card(data=data))
        self.assertNotIn('50/100', text)
        self.assertNotIn('1.00兆', text)
        self.assertNotIn('未平倉名目額', text)

    def test_expired_funding_time_not_called_upcoming(self):
        self.data['derivatives']['BTC']['funding_time'] = int((self.ts-1)*1000)
        self.assertIn('本期費率／結算時間尚未確認', brief.contract_lines(self.data, self.now, False))

    def test_oi_uses_same_contract_coin_quantity_and_actual_baseline_time(self):
        old = copy.deepcopy(self.data)
        for r in old['derivatives'].values():
            r['timestamp'] -= 86400
            r['oi_usd'] /= 10  # USD valuation change must not be mistaken for position change.
            r['oi_ccy'] = 80
        brief.add_context(self.data, [brief.snapshot(old, self.now-timedelta(days=1))], self.now)
        self.assertEqual(self.data['derivatives']['BTC']['oi_change_1d'], 25)
        self.assertIn('+25.00%', brief.contract_lines(self.data, self.now, False))

    def test_oi_rejects_different_contract_or_wrong_interval(self):
        for hours, scope in ((48, 'OKX BTC-USDT-SWAP'), (24, 'OTHER BTC-USDT-SWAP')):
            data = copy.deepcopy(self.data)
            prior = {'derivatives': {'BTC': {'timestamp': self.ts-hours*3600, 'scope': scope, 'oi_ccy': 80}}}
            brief.add_context(data, [prior], self.now)
            self.assertNotIn('oi_change_1d', data['derivatives']['BTC'])

    def test_sentiment_comparison_requires_adjacent_day(self):
        self.data['sentiment']['previous_timestamp'] -= 86400
        self.assertIn('較前一日 暫缺', brief.sentiment_lines(self.data, self.now))

    def test_daily_collector_requests_two_days(self):
        with patch.object(source, 'get_json', return_value={'data': [{'value': '50', 'value_classification': 'Neutral', 'timestamp': self.ts}, {'value': '40', 'timestamp': self.ts-86400}]}) as get:
            row = source.fear_greed_snapshot()
        self.assertIn('limit=2', get.call_args.args[0])
        self.assertEqual(row['previous_value'], 40)

    def test_collectors_reject_blank_or_nonfinite_values(self):
        for value in (None, '', float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                source.finite_number(value)
        self.assertEqual(source.finite_number('0'), 0)

    def test_slim_collector_fetches_new_sources_without_liquidation_spam(self):
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}), patch.object(source, 'crypto_snapshot', return_value=({}, {})), \
             patch.object(source, 'global_snapshot', return_value={}) as glob, patch.object(source, 'derivatives_snapshot', return_value={}) as deriv, \
             patch.object(source, 'fear_greed_snapshot', return_value={}), patch.object(source, 'etf_flow_snapshot', return_value={}), \
             patch.object(source, 'liquidation_snapshot') as liq:
            source.collect_dashboard(self.now)
        glob.assert_called_once()
        deriv.assert_called_once()
        liq.assert_not_called()

    def test_weekly_funding_filters_to_seven_days_and_deduplicates(self):
        rows = [{'fundingTime': int((self.ts-i*8*3600)*1000), 'fundingRate': '.0001', 'realizedRate': '.0002'} for i in range(22)]
        rows += [rows[0], {'fundingTime': int((self.ts-9*86400)*1000), 'fundingRate': '1'}]
        with patch.object(source, 'derivatives_snapshot', return_value={'BTC': {}, 'ETH': {}}), patch.object(source, 'get_json', return_value={'code': '0', 'data': rows}):
            result = source.weekly_funding_snapshot(self.now)
        self.assertEqual(result['BTC']['samples'], 22)
        self.assertAlmostEqual(result['BTC']['funding_avg_7d'], .02)

    def test_weekly_funding_rejects_incomplete_window_and_internal_gaps(self):
        for missing in ('old', 'middle'):
            rows = [{'fundingTime': int((self.ts-i*8*3600)*1000), 'fundingRate': '.0001'} for i in range(22) if (i < 10 if missing == 'old' else i != 10)]
            with patch.object(source, 'derivatives_snapshot', return_value={'BTC': {}, 'ETH': {}}), patch.object(source, 'get_json', return_value={'code': '0', 'data': rows}):
                with self.assertRaises(RuntimeError):
                    source.weekly_funding_snapshot(self.now)

    def test_weekly_sentiment_rejects_missing_exact_seven_day_baseline(self):
        with patch.object(source, 'get_json', return_value={'data': [{'value': '50', 'value_classification': 'Neutral', 'timestamp': self.ts}, {'value': '40', 'timestamp': self.ts-6*86400}]}):
            with self.assertRaises(ValueError):
                source.weekly_sentiment_snapshot()

    def test_weekly_has_review_conclusion_and_future_focus(self):
        data = copy.deepcopy(self.data)
        data['weekly_crypto'] = {'BTC': {'price': 80000, 'change_7d': 3.2}, 'ETH': {'price': 2500, 'change_7d': 1.4}}
        data['weekly_sentiment'] = {**data['sentiment'], 'previous_timestamp': self.ts-7*86400}
        card = self.card('weekly', data)
        names = '\n'.join(f['name'] for f in card['fields'])
        for value in ('一週情緒', '上週關鍵事件', '一週統整與總結', '本週要注意什麼'):
            self.assertIn(value, names)
        self.assertIn('1.80個百分點', self.text(card))
        self.assertIn('歷史紀錄尚未涵蓋完整七日', self.text(card))
        self.assertNotIn('市場概況', names)

    def test_etf_different_dates_not_called_same_period(self):
        self.data['eth_etf']['date'] -= timedelta(days=1)
        self.assertFalse(any('同一統計期間' in row for row in brief.observations(self.data, False)))

    def test_many_events_and_long_names_fit_without_silent_omission(self):
        events = [{'time': self.now+timedelta(minutes=i+1), 'rule': {'key': 'cpi', 'name': '物價報告'+('測試'*100), 'source': 'https://example.com'}} for i in range(7)]
        card = self.card(events=events)
        self.assertTrue(all(len(f['value']) <= 1024 for f in card['fields']))
        self.assertIn('另有', self.text(card))
        self.assertIn('總經數據快訊', self.text(card))

    def item(self, id='1', days=1):
        return {'id': id, 'title': 'SEC approved Bitcoin ETF', 'title_zh': '監管機構批准比特幣ETF', 'summary': 'SEC approved Bitcoin ETF',
                'summary_zh_points': ['監管機構批准比特幣ETF。'], 'published': self.now-timedelta(days=days), 'source': '官方', 'official': True,
                'category': {'key': 'etf'}, 'url': 'https://example.com/news/'+id}

    def test_news_archive_has_original_link_and_filters_out_of_window(self):
        state = {}
        brief.remember_news(state, self.item(), self.now)
        brief.remember_news(state, self.item('future', -1), self.now)
        brief.remember_news(state, self.item('old', 9), self.now)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'news.json'
            path.write_text(json.dumps(state), encoding='utf-8')
            review = brief.news_review(path, self.now)
        self.assertEqual(len(review['items']), 1)
        self.assertFalse(review['complete_window'])
        self.assertIn('https://example.com/news/1', brief.review_lines({'news_review': review}))

    def test_weekly_review_does_not_promote_failed_chinese_translation(self):
        state = {}
        item = self.item()
        item['title_zh'] = '批准1000個比特幣ETF'
        brief.remember_news(state, item, self.now)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'news.json'
            path.write_text(json.dumps(state), encoding='utf-8')
            self.assertEqual(brief.news_review(path, self.now)['items'], [])

    def test_successful_immediate_news_is_archived_and_failed_send_is_not(self):
        for failure in (False, True):
            state = {'initialized': True, 'seen': {}, 'pending': [], 'translation_cache': {}}
            item = self.item()
            item['published'] = self.now
            item['title'] = 'SEC approves spot Bitcoin ETF'
            item['category'] = news.category_for(item['title'])
            with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'DISCORD_CRYPTO_NEWS_WEBHOOK_URL': 'https://discord.invalid'}), \
                 patch.object(news, 'load_state', return_value=state), patch.object(news, 'save_state'), \
                 patch.object(news, 'fetch_all', return_value=([item], [('test', 1, None)])), \
                 patch.object(news, 'add_translated_title', side_effect=lambda row, *_: dict(row)), \
                 patch.object(news, 'send_discord', side_effect=OSError('failed') if failure else None):
                if failure:
                    with self.assertRaises(OSError):
                        news.run(self.now)
                else:
                    news.run(self.now)
            self.assertEqual(len(state.get('weekly_journal', [])), 0 if failure else 1)

    def test_weekly_review_merges_identical_headlines_across_sources(self):
        state = {}
        for id in ('a', 'b'):
            brief.remember_news(state, self.item(id), self.now)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'news.json'
            path.write_text(json.dumps(state), encoding='utf-8')
            self.assertEqual(len(brief.news_review(path, self.now)['items']), 1)

    def test_long_review_links_fit_without_truncating_urls(self):
        items = [self.item(str(i)) for i in range(3)]
        for item in items:
            item['url'] += 'x'*400
        text = brief.review_lines({'items': items, 'news_review': {'items': items, 'complete_window': True}})
        self.assertLessEqual(len(text), 1024)
        self.assertIn(items[0]['url'], text)

    def test_summary_run_uses_new_fields_and_returns_successful_snapshot(self):
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}), patch.object(summary, 'collect_dashboard', return_value=self.data), \
             patch.object(summary, 'upcoming_events', return_value=([], None)), patch.object(summary, 'send') as send:
            result = summary.run('daily', self.now, dry_run=True)
        self.assertEqual(len(send.call_args.args[1]['fields']), 6)
        self.assertEqual(result['derivatives']['BTC']['oi_ccy'], 100)

    def test_final_delivery_preserves_query_time_and_category(self):
        from notification_format import apply_delivery_format
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            card = apply_delivery_format(self.card(), 'daily_market')
        self.assertTrue(card['title'].startswith('【每日行情】'))
        self.assertIn('查詢：10/14 08:00', card['footer']['text'])

    def test_scheduler_preserves_comparison_history_and_sends_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'
            path.write_text(json.dumps({'daily': '2026-10-13'}))
            with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}), patch.object(summary, 'SCHEDULE_STATE', path), \
                 patch.object(summary, 'run', return_value=brief.snapshot(self.data, self.now)) as run:
                self.assertEqual(summary.run_scheduled(self.now), ['daily'])
                self.assertEqual(summary.run_scheduled(self.now+timedelta(minutes=5)), [])
            state = json.loads(path.read_text())
            self.assertEqual(len(state['brief_history']), 1)
            self.assertEqual(run.call_count, 1)

    def test_failed_send_does_not_commit_comparison_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'
            original = {'daily': '2026-10-13', 'brief_history': []}
            path.write_text(json.dumps(original))
            with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}), patch.object(summary, 'SCHEDULE_STATE', path), patch.object(summary, 'run', side_effect=OSError('send failed')):
                with self.assertRaises(OSError):
                    summary.run_scheduled(self.now)
            self.assertEqual(json.loads(path.read_text()), original)


if __name__ == '__main__':
    unittest.main()
