"""Public market data: Bitget first, Binance fallback; no account API or state."""
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.error import HTTPError
import math

BG = 'https://api.bitget.com'
BN = 'https://api.binance.com'
BF = 'https://fapi.binance.com'
SOURCES = ('Bitget', 'Binance')
LINKS = {'Bitget': 'https://www.bitget.com', 'Binance': 'https://www.binance.com'}
DAY = 86400000


def number(value, positive=False):
    if value is None or value == '' or isinstance(value, bool):
        raise ValueError('missing market number')
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError('invalid market number')
    return result


def clock_ms(now=None):
    return int((now or datetime.now(timezone.utc)).timestamp() * 1000)


def fresh_ms(value, now=None):
    ts = number(value, True)
    if not -60000 <= clock_ms(now) - ts <= 1800000:
        raise ValueError('stale or future market timestamp')
    return ts


def reason(exc):
    if isinstance(exc, HTTPError):
        return f'HTTP {exc.code}'
    if isinstance(exc, ValueError):
        return f'ValueError: {str(exc)[:120]}'
    return type(exc).__name__


def checked(payload):
    if not isinstance(payload, dict) or payload.get('code') != '00000':
        raise ValueError('Bitget unsuccessful payload')
    return payload['data']


def match(rows, symbol):
    rows = [r for r in rows if r.get('symbol') == symbol]
    if len(rows) != 1:
        raise ValueError('missing or duplicate requested market symbol')
    return rows[0]


def prefer(fetch):
    failures = []
    for venue in SOURCES:
        try:
            row = fetch(venue)
            if failures:
                row['fallback_reason'] = '; '.join(failures)
            return row
        except Exception as exc:
            # No alternate domains, proxies or repeated requests on 403/451.
            failures.append(f'{venue} {reason(exc)}')
    raise RuntimeError('; '.join(failures))


def spot(get, coin, venue, now=None):
    symbol = coin + 'USDT'
    if venue == 'Bitget':
        row = match(checked(get(BG+'/api/v2/spot/market/tickers?'+urlencode({'symbol': symbol}))), symbol)
        price, change, ts = row['lastPr'], number(row['change24h'])*100, row['ts']
        high, low, volume = row['high24h'], row['low24h'], row['quoteVolume']
    elif venue == 'Binance':
        row = get(BN+'/api/v3/ticker/24hr?'+urlencode({'symbol': symbol}))
        if row.get('symbol') != symbol:
            raise ValueError('wrong Binance symbol')
        price, change, ts = row['lastPrice'], number(row['priceChangePercent']), row['closeTime']
        high, low, volume = row['highPrice'], row['lowPrice'], row['quoteVolume']
    else:
        raise ValueError('unsupported venue')
    result = dict(price=number(price, True), change_24h=change, change_7d=None,
                  high_24h=number(high, True), low_24h=number(low, True), volume_24h=number(volume),
                  updated_at=fresh_ms(ts, now)/1000, source=venue, source_url=LINKS[venue], quote_currency='USDT')
    if not result['low_24h'] <= result['price'] <= result['high_24h'] or result['volume_24h'] < 0 or change < -100:
        raise ValueError('inconsistent spot values')
    return result


def daily_candles(get, coin, venue, count=7, now=None):
    symbol = coin+'USDT'
    end = clock_ms(now)//DAY*DAY
    if venue == 'Bitget':
        rows = checked(get(BG+'/api/v2/spot/market/candles?'+urlencode(
            {'symbol': symbol, 'granularity': '1Dutc', 'limit': count+1})))
    elif venue == 'Binance':
        rows = get(BN+'/api/v3/klines?'+urlencode({'symbol': symbol, 'interval': '1d', 'limit': count+1}))
    else:
        raise ValueError('unsupported venue')
    candles = {}
    for row in rows:
        if len(row) < 8:
            raise ValueError('incomplete candle')
        ts = int(number(row[0], True))
        if ts % DAY or ts >= end:
            continue
        values = [number(v, True) for v in row[1:5]]
        volume = number(row[7])
        if not values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1] or volume < 0:
            raise ValueError('invalid candle OHLC or quote volume')
        parsed = [ts, *values, volume]
        if ts in candles and candles[ts] != parsed:
            raise ValueError('conflicting duplicate candle')
        candles[ts] = parsed
    times = [end-i*DAY for i in range(count, 0, -1)]
    if any(ts not in candles for ts in times):
        raise ValueError('missing current complete UTC daily candle')
    return {'candles': [candles[ts] for ts in times], 'source': venue, 'source_url': LINKS[venue], 'quote_currency': 'USDT'}


def weekly_prices(get, coin, now=None):
    result = prefer(lambda venue: daily_candles(get, coin, venue, now=now))
    rows = result.pop('candles')
    return {**result, 'price': rows[-1][4], 'change_7d': (rows[-1][4]/rows[0][1]-1)*100,
            'high_7d': max(r[2] for r in rows), 'low_7d': min(r[3] for r in rows),
            'volume_7d': sum(r[5] for r in rows), 'start_timestamp': rows[0][0]/1000,
            'end_timestamp': (rows[-1][0]+DAY)/1000}


def contract(get, coin, venue, now=None):
    symbol = coin+'USDT'
    if venue == 'Bitget':
        query = urlencode({'symbol': symbol, 'productType': 'USDT-FUTURES'})
        ticker = match(checked(get(BG+'/api/v2/mix/market/ticker?'+query)), symbol)
        oi = checked(get(BG+'/api/v2/mix/market/open-interest?'+query))
        rate_payload = get(BG+'/api/v2/mix/market/current-fund-rate?'+query)
        rate = match(checked(rate_payload), symbol)
        size = number(match(oi['openInterestList'], symbol)['size'])
        mark = number(ticker['markPrice'], True)
        ts, rt = fresh_ms(oi['ts'], now), fresh_ms(rate_payload['requestTime'], now)
        mark_ts = fresh_ms(ticker['ts'], now)
        funding, next_time = number(rate['fundingRate'])*100, number(rate['nextUpdate'], True)
        interval = number(rate['fundingRateInterval'], True)
        price, change, volume = number(ticker['lastPr'], True), number(ticker['change24h'])*100, number(ticker['quoteVolume'])
    elif venue == 'Binance':
        query = urlencode({'symbol': symbol})
        oi = get(BF+'/fapi/v1/openInterest?'+query)
        rate = get(BF+'/fapi/v1/premiumIndex?'+query)
        ticker = get(BF+'/fapi/v1/ticker/24hr?'+query)
        if any(r.get('symbol') != symbol for r in (oi, rate, ticker)):
            raise ValueError('wrong Binance perpetual symbol')
        size, mark = number(oi['openInterest']), number(rate['markPrice'], True)
        ts, rt = fresh_ms(oi['time'], now), fresh_ms(rate['time'], now)
        mark_ts = rt
        funding, next_time = number(rate['lastFundingRate'])*100, number(rate['nextFundingTime'], True)
        # No assumed eight-hour default. Prefer explicit adjustment info, otherwise
        # verify the last settled interval and label it as historical observation.
        info = get(BF+'/fapi/v1/fundingInfo')
        adjusted = [r for r in info if r.get('symbol') == symbol]
        interval = number(adjusted[0]['fundingIntervalHours'], True) if len(adjusted) == 1 else None
        if interval is None:
            recent = get(BF+'/fapi/v1/fundingRate?'+query+'&limit=2')
            if len(recent) != 2 or any(r.get('symbol') != symbol for r in recent):
                raise ValueError('funding interval unavailable')
            interval = (round(number(recent[1]['fundingTime'])/1000)-round(number(recent[0]['fundingTime'])/1000))/3600
        price, change, volume = number(ticker['lastPrice'], True), number(ticker['priceChangePercent']), number(ticker['quoteVolume'])
        fresh_ms(ticker['closeTime'], now)
    else:
        raise ValueError('unsupported venue')
    if size < 0 or volume < 0 or interval not in (1, 2, 4, 8) or abs(ts-mark_ts) > 120000 or abs(ts-rt) > 120000:
        raise ValueError('inconsistent contract snapshots or interval')
    if not clock_ms(now) < next_time <= clock_ms(now)+8*3600000+60000:
        raise ValueError('expired or implausible next funding time')
    return dict(source=venue, source_url=LINKS[venue], scope=f'{venue} {symbol} USDT-PERP', quote_currency='USDT',
                oi_usd=size*mark, oi_ccy=size, mark_price=mark, oi_estimated=True, funding_rate=funding,
                funding_time=int(next_time), next_funding=int(next_time), timestamp=ts/1000, rate_timestamp=rt/1000,
                funding_interval_hours=interval, interval_observed=venue == 'Binance' and not adjusted,
                price=price, change_24h=change, volume_24h=volume)


def settled_week(get, coin, current, now=None):
    end = clock_ms(now)
    start = end-7*DAY
    venue = current['source']
    symbol = coin+'USDT'
    records = []
    if venue == 'Bitget':
        # At most 169 hourly settlements including both boundaries; bounded pages.
        for page in range(1, 4):
            rows = checked(get(BG+'/api/v2/mix/market/history-fund-rate?'+urlencode(
                {'symbol': symbol, 'productType': 'USDT-FUTURES', 'pageSize': 100, 'pageNo': page})))
            records.extend(rows)
            if len(rows) < 100 or min(int(r['fundingTime']) for r in rows) <= start:
                break
    elif venue == 'Binance':
        records = get(BF+'/fapi/v1/fundingRate?'+urlencode({'symbol': symbol, 'startTime': start, 'endTime': end, 'limit': 1000}))
    else:
        raise ValueError('weekly rate source must match contract')
    rates = {}
    for row in records:
        if row.get('symbol') != symbol:
            raise ValueError('wrong history symbol')
        ts, value = int(number(row['fundingTime'], True)), number(row['fundingRate'])*100
        if start <= ts <= end:
            if ts in rates and rates[ts] != value:
                raise ValueError('conflicting settled rate')
            rates[ts] = value
    # Funding timestamps carry exchange-generated millisecond offsets (live Binance
    # observations: 0-5 ms). Compare settlement cadence at second precision;
    # retain original records for duplicate conflicts, amounts and window bounds.
    times = sorted(round(ts/1000)*1000 for ts in rates)
    if len(set(times)) != len(times):
        raise ValueError('duplicate settlement slot')
    interval = number(current['funding_interval_hours'], True)*3600000
    if not times or times[0] > start+interval or times[-1] < end-interval or any(
            b-a != interval for a, b in zip(times, times[1:])):
        raise ValueError('incomplete seven-day rates or changed settlement interval')
    return {**current, 'funding_avg_7d': sum(rates.values())/len(rates), 'funding_sum_7d': sum(rates.values()),
            'samples': len(rates), 'start_timestamp': start/1000, 'end_timestamp': end/1000}
