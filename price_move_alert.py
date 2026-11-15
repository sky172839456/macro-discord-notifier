"""價格大波動快訊（2026-11-15 本人確認規格）。

- BTC 或 ETH 24 小時漲跌達 ±5% 發一則；同方向當天（台灣日期）不重發，擴大到 ±10% 再發一次。
- 1 小時內漲跌達 ±3% 也發；同幣同方向 6 小時內不重發。
- 兩種合計一天最多 3 則；同一輪同時觸發的合成一張卡，只算 1 則。
- 發到☕｜行情醒腦室（與日報同一 webhook），不 @ 任何人，全天都可發。
- 只列現價、漲跌幅、未平倉變化、資金費率、恐慌指數；不推論原因、不預測。
- 第一次執行只建立基準，不補發已經發生的波動。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Taipei')
SYMBOLS = ('BTC', 'ETH')
DAY_LEVELS = (10.0, 5.0)
HOUR_THRESHOLD = 3.0
HOUR_COOLDOWN = timedelta(hours=6)
DAILY_CAP = 3
SAMPLE_KEEP = timedelta(hours=3)
SPOT_MAX_AGE = 600  # 秒；超過 10 分鐘的報價不拿來觸發


def _time(value):
    return datetime.fromisoformat(value)


def day_level(change):
    for level in DAY_LEVELS:
        if abs(change) >= level:
            return level
    return 0.0


def direction(change):
    return 'up' if change > 0 else 'down'


def hour_change(samples, now):
    """取最接近 60 分鐘前（50～70 分鐘之間）的樣本計算 1 小時漲跌。"""
    target = now - timedelta(hours=1)
    best = None
    for at, price in samples:
        t = _time(at)
        if timedelta(minutes=50) <= now - t <= timedelta(minutes=70):
            if best is None or abs(t - target) < abs(_time(best[0]) - target):
                best = (at, price)
    return best


def triggers(state, now, quotes):
    """回傳本輪要發的觸發清單；不改 state。"""
    today = now.astimezone(TZ).date().isoformat()
    alerts = state.get('price_alerts') or []
    found = []
    for symbol, row in quotes.items():
        change = row.get('change_24h')
        if change is not None:
            level = day_level(change)
            if level:
                side = direction(change)
                sent = max((a['level'] for a in alerts if a['kind'] == '24h' and a['date'] == today
                            and a['symbol'] == symbol and a['direction'] == side), default=0.0)
                if level > sent:
                    found.append({'kind': '24h', 'symbol': symbol, 'direction': side, 'level': level, 'change': change})
        base = hour_change((state.get('price_samples') or {}).get(symbol) or [], now)
        if base and base[1] > 0:
            change_1h = (row['price'] / base[1] - 1) * 100
            row['change_1h'] = change_1h
            if abs(change_1h) >= HOUR_THRESHOLD:
                side = direction(change_1h)
                recent = any(a['kind'] == '1h' and a['symbol'] == symbol and a['direction'] == side
                             and now - _time(a['at']) < HOUR_COOLDOWN for a in alerts)
                if not recent:
                    found.append({'kind': '1h', 'symbol': symbol, 'direction': side, 'level': HOUR_THRESHOLD, 'change': change_1h})
    return found


def _pct(value):
    return f'{value:+.2f}%'


def build_card(now, quotes, found, context):
    arrow = '📉' if all(t['direction'] == 'down' for t in found) else '📈' if all(t['direction'] == 'up' for t in found) else '↕️'
    head = '｜'.join(f'{t["symbol"]} {"24小時" if t["kind"] == "24h" else "1小時"} {_pct(t["change"])}' for t in found)
    lines = []
    for symbol in SYMBOLS:
        row = quotes.get(symbol)
        if not row:
            continue
        part = f'**{symbol}** {row["price"]:,.2f} {row.get("quote_currency", "USDT")}｜24小時 **{_pct(row["change_24h"])}**'
        if row.get('change_1h') is not None:
            part += f'｜1小時 {_pct(row["change_1h"])}'
        lines.append(part)
    reasons = '、'.join(f'{t["symbol"]} {"24小時" if t["kind"] == "24h" else "1小時"}漲跌達 ±{t["level"]:g}%' for t in found)
    fields = []
    contract = []
    deriv = (context or {}).get('derivatives') or {}
    base = (context or {}).get('oi_base') or {}
    for symbol in SYMBOLS:
        row = deriv.get(symbol) or {}
        bits = []
        prior = base.get(symbol) or {}
        if row.get('oi_ccy') and prior.get('oi_ccy'):
            bits.append(f'未平倉數量較{_time(prior["timestamp"]).astimezone(TZ):%m/%d %H:%M} {_pct((row["oi_ccy"] / prior["oi_ccy"] - 1) * 100)}')
        if row.get('funding_rate') is not None:
            bits.append(f'資金費率 {row["funding_rate"]:+.4f}%（每期，非年化）')
        if bits:
            contract.append(f'**{symbol}**｜' + '；'.join(bits))
    if contract:
        fields.append({'name': '⚖️ 合約', 'value': '\n'.join(contract) + '\n未平倉變化不代表多空方向。', 'inline': False})
    mood = (context or {}).get('sentiment') or {}
    if mood.get('value') is not None:
        label = {'extreme fear': '極度恐懼', 'fear': '恐懼', 'neutral': '中性', 'greed': '貪婪', 'extreme greed': '極度貪婪'}.get(
            ' '.join(str(mood.get('classification') or '').lower().split()), '')
        fields.append({'name': '🌡️ 恐慌貪婪指數', 'value': f'{mood["value"]}/100' + (f'（{label}）' if label else '') + '\n每日更新一次，非即時。', 'inline': False})
    return {
        'title': f'【價格快訊】 {arrow} {head}',
        'description': '\n'.join(lines) + f'\n\n觸發條件：{reasons}。\n-# 只列查詢當下的數字，不推論原因、不預測走勢；價格為交易所查詢快照。',
        'fields': fields,
        'footer': {'text': f'查詢：{now.astimezone(TZ):%m/%d %H:%M}（台灣時間）｜不構成投資建議'},
        'timestamp': now.isoformat(),
    }


def check(state, now, fetch_spot, fetch_context, send, persist):
    """每輪排程呼叫一次；有發送回傳 True。"""
    quotes = {}
    for symbol in SYMBOLS:
        try:
            row = fetch_spot(symbol)
        except Exception:
            continue
        updated = row.get('updated_at')
        if row.get('price') and row.get('change_24h') is not None and updated and 0 <= now.timestamp() - float(updated) <= SPOT_MAX_AGE:
            quotes[symbol] = dict(row)
    if not quotes:
        return False
    first_run = 'price_alerts' not in state
    found = [] if first_run else triggers(state, now, quotes)
    samples = state.setdefault('price_samples', {})
    for symbol, row in quotes.items():
        rows = samples.setdefault(symbol, [])
        rows.append([now.isoformat(), row['price']])
        rows[:] = [r for r in rows if now - _time(r[0]) <= SAMPLE_KEEP]
    alerts = state.setdefault('price_alerts', [])
    if first_run:
        # 只記基準：當下已達門檻的 24 小時波動視為已處理，避免上線當下補發。
        today = now.astimezone(TZ).date().isoformat()
        for symbol, row in quotes.items():
            level = day_level(row['change_24h'])
            if level:
                alerts.append({'at': now.isoformat(), 'date': today, 'kind': '24h', 'symbol': symbol,
                               'direction': direction(row['change_24h']), 'level': level, 'baseline': True})
        persist()
        return False
    alerts[:] = [a for a in alerts if now - _time(a['at']) <= timedelta(days=2)]
    if not found:
        persist()
        return False
    today = now.astimezone(TZ).date().isoformat()
    sent_today = len({a['at'] for a in alerts if a['date'] == today and not a.get('baseline')})
    if sent_today >= DAILY_CAP:
        persist()
        return False
    try:
        context = fetch_context()
    except Exception:
        context = {}
    history = state.get('brief_history') or []
    if history:
        context = dict(context or {})
        context['oi_base'] = (history[-1].get('derivatives') or {})
    card = build_card(now, quotes, found, context)
    # 先記錄再送出：送出失敗也不會在下一輪重複轟炸。
    for t in found:
        alerts.append({'at': now.isoformat(), 'date': today, 'kind': t['kind'], 'symbol': t['symbol'],
                       'direction': t['direction'], 'level': t['level']})
    persist()
    send(card)
    return True
