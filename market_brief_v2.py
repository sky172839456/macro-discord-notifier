"""Source-bounded daily snapshots and weekly review; no generated price forecasts."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from notification_quality import money_musd, headline, chinese_points, news_score

TZ = ZoneInfo('Asia/Taipei')
SENTIMENT_URL = 'https://alternative.me/crypto/fear-and-greed-index/'
GLOBAL_URL = 'https://www.coingecko.com/en/charts'
OKX_URL = 'https://www.okx.com/trade-market/info/swap'


def number(value):
    try:
        return value is not None and not isinstance(value, bool) and math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def instant(value):
    try:
        result = datetime.fromtimestamp(float(value), timezone.utc) if isinstance(value, (int, float)) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def fresh(value, now, hours):
    time = instant(value)
    return time is not None and -300 <= (now - time).total_seconds() <= hours * 3600


def stamp(value):
    time = instant(value)
    return time.astimezone(TZ).strftime('%m/%d %H:%M') if time else '來源時間暫缺'


def money(value):
    amount = abs(float(value))
    if amount >= 1e12:
        return f'{value / 1e12:,.2f}兆美元'
    if amount >= 1e8:
        return f'{value / 1e8:,.2f}億美元'
    if amount >= 1e4:
        return f'{value / 1e4:,.1f}萬美元'
    return f'{value:,.2f}美元'


def signed(value, unit='%'):
    return f'{value:+.2f}{unit}' if number(value) else '暫缺'


def field(name, value):
    # Sources are attached to their section; never silently truncate a source URL.
    if len(value) > 1024:
        raise ValueError('Market brief section exceeds Discord limit')
    return {'name': name, 'value': value, 'inline': False}


def sentiment_lines(data, now, weekly=False):
    row = data.get('weekly_sentiment' if weekly else 'sentiment') or {}
    if not fresh(row.get('timestamp'), now, 48) or not number(row.get('value')) or not 0 <= row['value'] <= 100:
        return f'⚠️ 恐慌貪婪指數暫缺或未更新。\n來源：[Alternative.me]({SENTIMENT_URL})'
    label = {'extreme fear': '極度恐懼', 'fear': '恐懼', 'neutral': '中性', 'greed': '貪婪', 'extreme greed': '極度貪婪'}.get(' '.join(str(row.get('classification') or '').lower().split()), '分類暫缺')
    delta = row['value'] - row['previous_value'] if number(row.get('previous_value')) else None
    interval = 7 * 86400 if weekly else 86400
    if not instant(row.get('previous_timestamp')) or abs((instant(row['timestamp']) - instant(row['previous_timestamp'])).total_seconds() - interval) > 60:
        delta = None
    return (f'恐慌貪婪指數 **{row["value"]}/100｜{label}**　較{"七日前" if weekly else "前一日"} {signed(delta, "分")}\n'
            f'資料：{stamp(row["timestamp"])}｜以比特幣情緒為主\n'
            f'來源：[Alternative.me]({SENTIMENT_URL})｜情緒不等同漲跌預測')


def global_lines(data, now):
    row = data.get('global') or {}
    if not fresh(row.get('timestamp'), now, 3) or not all(number(row.get(k)) for k in ('market_cap', 'market_cap_change_24h', 'btc_dominance')):
        return f'⚠️ 市場總覽暫缺或未更新。\n來源：[CoinGecko]({GLOBAL_URL})'
    return (f'總市值 **{money(row["market_cap"])}**｜24h **{signed(row["market_cap_change_24h"])}**\n'
            f'BTC市占 **{row["btc_dominance"]:.2f}%**\n'
            f'資料：{stamp(row["timestamp"])}｜[CoinGecko]({GLOBAL_URL})\n市占是市值占比，並非資金流量。')


def price_lines(data, market, now, weekly):
    coins = data.get('weekly_crypto' if weekly else 'crypto') or {}
    lines = []
    for symbol in ('BTC', 'ETH'):
        row = coins.get(symbol) or (market or {}).get(symbol) or {}
        if not number(row.get('price')) or (not weekly and row.get('source') == 'CoinGecko' and not fresh(row.get('updated_at'), now, 3)):
            lines.append(f'⚠️ {symbol}價格暫缺')
            continue
        change = row.get('change_7d' if weekly else 'change_24h', row.get('change'))
        lines.append(f'**{symbol}**　${row["price"]:,.2f}　**{signed(change)}**')
        if weekly and instant(row.get('start_timestamp')) and instant(row.get('end_timestamp')):
            lines.append(f'↳ 統計：{stamp(row["start_timestamp"])}～{stamp(row["end_timestamp"])}')
        elif not weekly and row.get('updated_at'):
            lines.append(f'↳ 資料更新：{stamp(row["updated_at"])}')
        if weekly and row.get('source') == 'OKX':
            lines.append('↳ OKX USDT現貨：最近七根完整UTC日線；非即時七日快照。')
    lines.append('七日區間；各來源截止時間可能不同。' if weekly else '近24小時漲跌；查詢快照，非即時報價。')
    lines.append('[CoinGecko](https://www.coingecko.com/) · [OKX現貨](https://www.okx.com/markets/prices)')
    return '\n'.join(lines)


def etf_lines(data, weekly):
    lines = []
    for key, symbol, url in (('weekly_btc_etf' if weekly else 'etf', 'BTC', 'https://farside.co.uk/btc/'),
                             ('weekly_eth_etf' if weekly else 'eth_etf', 'ETH', 'https://farside.co.uk/eth/')):
        row = data.get(key) or {}
        if number(row.get('net_flow_musd')):
            date = f'{row["start_date"]:%m/%d}～{row["end_date"]:%m/%d}' if weekly else f'{row["date"]:%m/%d}'
            count = f'｜{row.get("trading_days", "未確認")}個交易日' if weekly else ''
            lines.append(f'**{symbol} ETF**｜{date}{count}\n{money_musd(row["net_flow_musd"])}｜[Farside]({url})')
        else:
            lines.append(f'⚠️ {symbol} ETF資料暫缺｜[Farside]({url})')
    return '\n\n'.join(lines) + '\n美國現貨ETF；依標示交易日，非今天即時流量。'


def add_context(data, history, now):
    """Only compare matching instrument quantities with a close historical sample."""
    for days in (1, 7):
        target = now - timedelta(days=days)
        tolerance = timedelta(hours=4 if days == 1 else 12)
        for symbol, current in (data.get('weekly_derivatives') or data.get('derivatives') or {}).items():
            candidates = []
            for sample in history or []:
                prior = (sample.get('derivatives') or {}).get(symbol) or {}
                time = instant(prior.get('timestamp'))
                if (time and abs(time - target) <= tolerance and prior.get('scope') == current.get('scope')
                        and number(prior.get('oi_ccy')) and prior['oi_ccy'] > 0 and number(current.get('oi_ccy'))
                        and fresh(current.get('timestamp'), now, .5)):
                    candidates.append((abs(time - target), prior))
            if candidates:
                prior = min(candidates, key=lambda p: p[0])[1]
                current[f'oi_change_{days}d'] = (current['oi_ccy'] / prior['oi_ccy'] - 1) * 100
                current[f'oi_base_{days}d'] = prior['timestamp']
    return data


def snapshot(data, now):
    deriv = data.get('weekly_derivatives') or data.get('derivatives') or {}
    return {'at': now.isoformat(), 'derivatives': {
        symbol: {k: row[k] for k in ('scope', 'oi_ccy', 'oi_usd', 'timestamp') if k in row}
        for symbol, row in deriv.items() if fresh(row.get('timestamp'), now, .5)}}


def contract_lines(data, now, weekly):
    rows = data.get('weekly_derivatives' if weekly else 'derivatives') or {}
    lines = []
    for symbol in ('BTC', 'ETH'):
        row = rows.get(symbol) or {}
        if not fresh(row.get('timestamp'), now, .5) or not number(row.get('oi_usd')):
            lines.append(f'⚠️ {symbol}合約資料暫缺或未更新')
            continue
        days = 7 if weekly else 1
        delta = row.get(f'oi_change_{days}d')
        base = row.get(f'oi_base_{days}d')
        lines.append(f'**{symbol}**｜未平倉名目額 {money(row["oi_usd"])}\n'
                     + (f'數量較{stamp(base)} **{signed(delta)}**' if number(delta) else f'約{days}日前的數量比較暫缺'))
        if weekly and number(row.get('funding_avg_7d')):
            lines.append(f'七日已結算費率：每次平均 **{row["funding_avg_7d"]:+.4f}%**｜{row["samples"]}次\n'
                         f'期間 {stamp(row["start_timestamp"])}～{stamp(row["end_timestamp"])}')
        elif number(row.get('funding_rate')) and fresh(row.get('rate_timestamp'), now, .5) and instant(row.get('funding_time', 0) / 1000) and now < instant(row['funding_time'] / 1000):
            lines.append(f'本期預估資金費率 **{row["funding_rate"]:+.4f}%**｜結算 {stamp(row["funding_time"] / 1000)}')
        else:
            lines.append('本期費率／結算時間尚未確認')
        lines.append(f'未平倉資料：{stamp(row["timestamp"])}')
    return '\n\n'.join(lines) + f'\n僅[OKX BTC／ETH USDT永續]({OKX_URL})；數量變化不代表多空方向。\n費率為每期數值，非年化；正值通常由多方支付空方。'


def observations(data, weekly, now=None):
    coins = data.get('weekly_crypto' if weekly else 'crypto') or {}
    key = 'change_7d' if weekly else 'change_24h'
    changes = {s: r[key] for s, r in coins.items() if number(r.get(key))
               and not (now and not weekly and r.get('source') == 'CoinGecko' and not fresh(r.get('updated_at'), now, 3))}
    rows = []
    if 'BTC' in changes and 'ETH' in changes:
        a, b = changes['BTC'], changes['ETH']
        if a * b < 0:
            rows.append('BTC與ETH漲跌方向分化，單一幣種無法代表整體。')
        else:
            lead = 'BTC' if a >= b else 'ETH'
            rows.append(f'{lead}在這段價格區間領先{abs(a-b):.2f}個百分點。')
    flows = [data.get(k) or {} for k in (('weekly_btc_etf', 'weekly_eth_etf') if weekly else ('etf', 'eth_etf'))]
    same_period = all(r.get('start_date') == flows[0].get('start_date') and r.get('end_date') == flows[0].get('end_date') for r in flows) if weekly else flows[0].get('date') == flows[1].get('date')
    if same_period and all(number(r.get('net_flow_musd')) for r in flows):
        a, b = (r['net_flow_musd'] for r in flows)
        if a * b < 0:
            rows.append('同一統計期間BTC與ETH ETF資金方向不同，與價格表現分開看。')
        elif a > 0 and b > 0:
            rows.append('同一統計期間兩類ETF皆淨流入；這只涵蓋ETF通路。')
        elif a < 0 and b < 0:
            rows.append('同一統計期間兩類ETF皆淨流出；這只涵蓋ETF通路。')
    if weekly:
        mood = data.get('weekly_sentiment') or {}
        if (now and fresh(mood.get('timestamp'), now, 48) and number(mood.get('value'))
                and number(mood.get('previous_value')) and instant(mood.get('previous_timestamp'))
                and (instant(mood['timestamp']) - instant(mood['previous_timestamp'])).total_seconds() == 7 * 86400):
            delta = mood['value'] - mood['previous_value']
            rows.append(f'情緒指數較七日前{signed(delta, "分")}；情緒與價格分開判讀。')
    return rows[:3 if weekly else 2] or ['可比較資料不足，本次不補寫市場方向。']


def weekly_conclusion(data):
    coins = data.get('weekly_crypto') or {}
    a = (coins.get('BTC') or {}).get('change_7d')
    b = (coins.get('ETH') or {}).get('change_7d')
    if not number(a) or not number(b):
        return '可比較價格資料不足，暫不下市場方向結論。'
    price = '價格同步上漲' if a > 0 and b > 0 else '價格同步下跌' if a < 0 and b < 0 else '價格表現分化或持平'
    btc, eth = data.get('weekly_btc_etf') or {}, data.get('weekly_eth_etf') or {}
    flows = ''
    if (number(btc.get('net_flow_musd')) and number(eth.get('net_flow_musd'))
            and btc.get('start_date') == eth.get('start_date') and btc.get('end_date') == eth.get('end_date')
            and btc['net_flow_musd'] * eth['net_flow_musd'] < 0):
        flows = '，ETF資金方向卻不同'
    return f'這段統計呈現{price}{flows}；各資料期間依上方標示，不能據此斷言漲跌原因或預測下週。'


EVENT_WATCH = {
    'cpi': '留意整體／核心物價及前值修正。', 'pce': '留意核心PCE及前值修正。',
    'jobs': '一起看新增就業、失業率與前值修正。', 'fomc': '留意利率決議與聲明變化。',
    'fed_chair_policy': '核對實際談話內容，預告不代表政策結論。',
}


def events_lines(events, now, error, weekly, budget=1000):
    from slim_policy import today_events, CORE_EVENTS
    rows = today_events(events, now, 7 if weekly else 1)
    # Weekly focus is explicitly selected, while the separate daily calendar lists all.
    if weekly:
        selected = sorted(rows, key=lambda r: (r['rule']['key'] not in CORE_EVENTS, r['time']))[:3]
        selected.sort(key=lambda r: r['time'])
    else:
        selected = rows[:3]
    source = '\n[官方行事曆](https://www.bls.gov/schedule/news_release/) · [聯準會](https://www.federalreserve.gov/newsevents/calendar.htm)'
    parts = []
    for r in selected:
        part = (f'**{r["time"].astimezone(TZ):%m/%d %H:%M}｜{r["rule"]["name"]}**\n'
                f'{EVENT_WATCH.get(r["rule"]["key"], "核對公布結果、前值與資料所屬期間。")}')
        if len('\n\n'.join(parts + [part])) + len(source) + 100 > budget:
            break
        parts.append(part)
    text = '\n\n'.join(parts)
    if not text:
        text = '目前未查到符合追蹤範圍的未來事件。'
    if len(rows) > len(parts):
        text += f'\n另有{len(rows)-len(parts)}項；完整當日清單見「總經數據快訊」。'
    if error:
        text += '\n⚠️ 行事曆尚未完整確認；未列出不代表沒有事件。'
    return text + source


def remember_news(state, item, now):
    """Archive only successfully delivered facts for the next weekly review."""
    journal = state.setdefault('weekly_journal', [])
    state.setdefault('weekly_journal_started_at', now.isoformat())
    cutoff = now - timedelta(days=8)
    journal[:] = [r for r in journal if instant(r.get('published')) and cutoff <= instant(r['published']) <= now]
    if not instant(item.get('published')) or not cutoff <= instant(item['published']) <= now:
        return
    row = {k: item[k] for k in ('id', 'title', 'title_zh', 'summary', 'summary_zh_points', 'url', 'source', 'official', 'category') if k in item}
    row['published'] = instant(item['published']).isoformat()
    row['delivered_at'] = now.isoformat()
    journal[:] = [r for r in journal if r.get('id') != row.get('id')]
    journal.append(row)


def news_review(path, now):
    try:
        state = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'items': [], 'complete_window': False}
    start = now - timedelta(days=7)
    selected = []
    seen = set()
    from slim_policy import same_event
    from crypto_news_notifier import similar_title
    for row in sorted(state.get('weekly_journal', []), key=lambda r: (news_score(r), str(r.get('published', ''))), reverse=True):
        time = instant(row.get('published'))
        if not time or not start <= time <= now or not str(row.get('url', '')).startswith('https://'):
            continue
        title = headline(row)
        if '中文標題待確認' in title or row['url'] in seen or any(same_event(row.get('title', ''), r.get('title', '')) or similar_title(row.get('title', ''), r.get('title', '')) for r in selected):
            continue
        seen.add(row['url'])
        selected.append(row)
        if len(selected) == 3:
            break
    since = instant(state.get('weekly_journal_started_at'))
    return {'items': selected, 'complete_window': bool(since and since <= start)}


def review_lines(data):
    review = data.get('news_review') or {}
    lines = []
    for i, row in enumerate(review.get('items') or []):
        title = headline(row).replace('[', '').replace(']', '')[:90]
        points = chinese_points(row)
        detail = ('\n' + points[0][:120]) if points else ''
        part = f'**{i+1:02d}｜{title}**{detail}\n{stamp(row["published"])}｜[{str(row["source"])[:50]}]({row["url"]})'
        if len('\n\n'.join(lines + [part])) > 850:
            part = f'**{i+1:02d}｜{title}**\n[{str(row["source"])[:50]}]({row["url"]})'
        if len('\n\n'.join(lines + [part])) <= 850:
            lines.append(part)
    if not lines:
        lines.append('暫無可核對的已推播新聞紀錄；不代表上週沒有重要消息。')
    lines.append('僅整理已核對且已推播的消息，並非全市場完整回顧。')
    if not review.get('complete_window'):
        lines.append('⚠️ 歷史紀錄尚未涵蓋完整七日。')
    return '\n\n'.join(lines)


def build_card(period, now, market, market_error, events, event_error, data):
    data = data or {}
    weekly = period == 'weekly'
    fields = [field('📈 一週價格變化' if weekly else '📈 價格表現｜24小時', price_lines(data, market, now, weekly))]
    if not weekly:
        fields.append(field('🌐 市場概況', global_lines(data, now)))
    fields.extend([field('🌡️ 一週情緒變化' if weekly else '🌡️ 市場情緒', sentiment_lines(data, now, weekly)),
                   field('💰 一週ETF資金' if weekly else '💰 ETF資金動向', etf_lines(data, weekly)),
                   field('⚖️ 合約概況｜OKX', contract_lines(data, now, weekly))])
    if weekly:
        fields.append(field('📰 上週關鍵事件｜已推播紀錄', review_lines(data)))
        fields.append(field('🧩 一週統整與總結', '\n\n'.join('• ' + line for line in observations(data, True, now)) + '\n\n**本週總結**｜' + weekly_conclusion(data)))
        fields.append(field('📅 本週要注意什麼｜未來七日', events_lines(events, now, event_error, True)))
    else:
        fields.append(field('📅 今日關注', events_lines(events, now, event_error, False, budget=650) + '\n\n**📌 市場觀察**\n' + '\n'.join('• ' + line for line in observations(data, False, now))))
    description = '用一週的變化做整理，再準備這週的行程。' if weekly else '價格、情緒、資金，一張掌握今天的市場狀態。'
    if data.get('errors') or market_error:
        description += '\n⚠️ 部分資料暫缺；各區塊只顯示已取得的內容。'
    card = {'title': f'{"🧭 每週市場導航" if weekly else "📊 每日市場情報"}｜{now.astimezone(TZ):%m/%d}',
            'description': description, 'fields': fields, 'color': 0x8274B0 if weekly else 0x647FB5,
            'footer': {'text': f'查詢：{now.astimezone(TZ):%m/%d %H:%M}（台灣時間）｜各資料依標示期間｜不構成投資建議'}, 'timestamp': now.isoformat()}
    total = len(card['title']) + len(description) + len(card['footer']['text']) + sum(len(f['name']) + len(f['value']) for f in fields)
    if total > 5800:
        raise ValueError('Market brief exceeds Discord total limit')
    return card
