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
    return (f'恐慌貪婪指數 **{row["value"]}/100｜{label}**\n較{"七日前" if weekly else "前一日"} {signed(delta, "分")}\n\n'
            f'資料：{stamp(row["timestamp"])}｜以比特幣情緒為主\n'
            f'來源：[Alternative.me]({SENTIMENT_URL})')


def global_lines(data, now):
    row = data.get('global') or {}
    if not fresh(row.get('timestamp'), now, 3) or not all(number(row.get(k)) for k in ('market_cap', 'market_cap_change_24h', 'btc_dominance')):
        return f'⚠️ 市場總覽暫缺或未更新。\n來源：[CoinGecko]({GLOBAL_URL})'
    return (f'總市值 **{money(row["market_cap"])}**\n24h **{signed(row["market_cap_change_24h"])}**\n'
            f'BTC市占 **{row["btc_dominance"]:.2f}%**\n'
            f'\n資料：{stamp(row["timestamp"])}\n來源：[CoinGecko]({GLOBAL_URL})')


def price_lines(data, market, now, weekly):
    coins = data.get('weekly_crypto' if weekly else 'crypto') or {}
    lines = []
    for symbol in ('BTC', 'ETH'):
        row = coins.get(symbol) or (market or {}).get(symbol) or {}
        if (not number(row.get('price')) or
                (row.get('source') and not fresh(row.get('end_timestamp' if weekly else 'updated_at'), now, 25 if weekly else .5))):
            lines.append(f'⚠️ **{symbol}** 價格暫缺或未更新\nBitget／幣安本輪未取得可核對資料。')
            continue
        change = row.get('change_7d' if weekly else 'change_24h', row.get('change'))
        quote = row.get('quote_currency', 'USD')
        part = f'**{symbol}**　{row["price"]:,.2f} {quote}　**{signed(change)}**'
        if weekly and instant(row.get('start_timestamp')) and instant(row.get('end_timestamp')):
            part += f'\n統計：{stamp(row["start_timestamp"])}～{stamp(row["end_timestamp"])}'
        elif not weekly and row.get('updated_at'):
            part += f'\n資料更新：{stamp(row["updated_at"])}'
        if row.get('source_url'):
            part += f'\n\n來源：[{row["source"]}現貨]({row["source_url"]})'
        if row.get('fallback_reason'):
            part += '\nBitget本輪未取得可核對資料，改用幣安。'
        lines.append(part)
    if weekly:
        lines.append('最近七根完整UTC日線；非即時七日快照。')
    return '\n\n'.join(lines)


def etf_lines(data, weekly):
    rows = []
    for key, symbol, url in (('weekly_btc_etf' if weekly else 'etf', 'BTC', 'https://farside.co.uk/btc/'),
                             ('weekly_eth_etf' if weekly else 'eth_etf', 'ETH', 'https://farside.co.uk/eth/')):
        row = data.get(key) or {}
        if not weekly and (row.get('source_issue') or (row.get('date') and not number(row.get('net_flow_musd')))):
            period = f'交易日：{row["date"]:%m/%d}'
            previous = row.get('previous_complete') or {}
            fallback = (f'\n前次完整資料｜交易日 {previous["date"]:%m/%d}：{money_musd(previous["net_flow_musd"])}（非本交易日）'
                        if number(previous.get('net_flow_musd')) else '')
            issue = row.get('source_issue')
            if issue == '來源合計尚未列值':
                label, detail = 'Farside 尚未列出完整數據', '來源合計欄尚未列值。'
            elif issue == '來源分項與合計不符':
                label, detail = 'Farside 分項與合計待核對', '暫不列本日合計。'
            else:
                label, detail = '暫時無法取得可核對的 Farside 數據', '本日合計尚未確認。'
            rows.append({'symbol':symbol,'url':url,'source_label':label,
                         'source_status':period+'\n'+detail+fallback})
            continue
        if number(row.get('net_flow_musd')):
            period = f'統計期間：{row["start_date"]:%m/%d}～{row["end_date"]:%m/%d}' if weekly else f'交易日：{row["date"]:%m/%d}'
            count = f'｜{row["trading_days"]}個交易日' if weekly and row.get('trading_days') is not None else ''
            flow = money_musd(row['net_flow_musd'])
            if float(row['net_flow_musd']) == 0:
                flow = '0美元'
            import re
            flow = re.sub(r'(\d)\.0+(?=(?:億|萬)?美元)', r'\1', flow)
            query = f'查詢時間：{stamp(row["retrieved_at"])}（台灣）' if instant(row.get('retrieved_at')) else ''
            rows.append({'symbol': symbol, 'url': url, 'period': period, 'query': query,
                         'count': count, 'flow': flow, 'partial': bool(row.get('unreported_components', 0)),
                         # A source total of zero with unlisted fund cells cannot
                         # establish a complete zero net flow. Keep its date and
                         # retrieval time, but do not present a numeric aggregate.
                         'pending_zero': float(row['net_flow_musd']) == 0 and
                                         bool(row.get('unreported_components', 0)),
                         'previous_complete': row.get('previous_complete')})
        else:
            rows.append({'symbol': symbol, 'url': url})
    available = [row for row in rows if 'flow' in row]
    valid = [row for row in available if not row['pending_zero']]
    shared_period = len(available) == 2 and available[0]['period'] == available[1]['period']
    shared_query = len(available) == 2 and available[0]['query'] and available[0]['query'] == available[1]['query']
    header = ['美國現貨ETF｜非即時流量']
    if shared_period:
        header.append(available[0]['period'])
    if shared_query:
        header.append(available[0]['query'])
    lines = ['\n'.join(header)]
    for row in rows:
        if 'flow' not in row:
            lines.append(f'⚠️ **{row["symbol"]} ETF**\n'+row.get('source_label','暫時無法取得 Farside 數據')
                         +'\n'+row.get('source_status','本輪未取得可核對數值。')+f'\n[Farside來源]({row["url"]})')
            continue
        context = []
        if not shared_period:
            context.append(row['period'])
        if not shared_query and row['query']:
            context.append(row['query'])
        status = ('**Farside 尚未列出完整數據**' if row['pending_zero'] else
                  f'來源目前合計 **{row["flow"]}**{row["count"]}'+('（暫定）' if row['partial'] else ''))
        if row['pending_zero'] and not weekly and row.get('previous_complete'):
            previous = row['previous_complete']
            context.append(f'前次完整資料｜交易日 {previous["date"]:%m/%d}：{money_musd(previous["net_flow_musd"])}（非本交易日）')
        lines.append(f'**{row["symbol"]} ETF**\n{status}'
                     + ('\n'+'\n'.join(context) if context else '') + f'\n[Farside來源]({row["url"]})')
    if any(row.get('pending_zero') for row in rows):
        lines.append('📝 來源尚有基金未列數值，暫不列合計；不代表資金沒有流入或流出。')
    if valid:
        partial = '部分基金未列數值，' if any(row['partial'] for row in valid) else ''
        lines.append(f'📝 {partial}以上合計仍可能更新，非最終結果。')
    return '\n\n'.join(lines)


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
    from etf_followup import capture
    return {'at': now.isoformat(), 'etf_status': capture(data, now), 'derivatives': {
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
        delta, base = row.get(f'oi_change_{days}d'), row.get(f'oi_base_{days}d')
        venue = row.get('source') or str(row.get('scope', '')).split(' ')[0] or '來源暫缺'
        amount = money(row['oi_usd'])
        if row.get('quote_currency') == 'USDT':
            amount = amount.replace('美元', ' USDT')
        label = '未平倉估值' if row.get('oi_estimated') else '未平倉名目額'
        parts = [f'**{symbol}｜{venue} USDT永續**\n{label} {amount}',
                 f'數量較{stamp(base)} **{signed(delta)}**' if number(delta) else f'約{days}日前同交易所的數量比較暫缺']
        if weekly:
            if number(row.get('funding_avg_7d')):
                parts.append(f'七日已結算費率：每次平均 **{row["funding_avg_7d"]:+.4f}%**｜{row["samples"]}次\n'
                             f'期間 {stamp(row["start_timestamp"])}～{stamp(row["end_timestamp"])}')
            else:
                parts.append('七日已結算費率暫缺：歷史區間尚未核對完整。')
        elif number(row.get('funding_rate')) and fresh(row.get('rate_timestamp'), now, .5) and instant(row.get('funding_time', 0)/1000) and now < instant(row['funding_time']/1000):
            parts.append(f'目前資金費率 **{row["funding_rate"]:+.4f}%**（結算前可能更新）\n下次結算 {stamp(row["funding_time"]/1000)}')
        else:
            parts.append('本期費率／結算時間尚未確認')
        if number(row.get('funding_interval_hours')):
            prefix = '最近已結算間隔' if row.get('interval_observed') else '目前結算間隔'
            parts.append(f'{prefix}：{row["funding_interval_hours"]:g}小時')
        parts.append(f'未平倉資料：{stamp(row["timestamp"])}')
        if row.get('source_url'):
            parts.append(f'[來源：{venue}]({row["source_url"]})')
        if row.get('fallback_reason'):
            parts.append('Bitget本輪未取得可核對資料，改用幣安。')
        lines.append('\n'.join(parts))
    lines.append('估值＝幣數×標記價格；費率為每期值，非年化。')
    return '\n\n'.join(lines)


def observations(data, weekly, now=None):
    coins = data.get('weekly_crypto' if weekly else 'crypto') or {}
    key = 'change_7d' if weekly else 'change_24h'
    changes = {s: r[key] for s, r in coins.items() if number(r.get(key))
               and not (now and not weekly and r.get('source') in ('CoinGecko', 'Bitget', 'Binance') and not fresh(r.get('updated_at'), now, .5))}
    rows = []
    if 'BTC' in changes and 'ETH' in changes:
        a, b = changes['BTC'], changes['ETH']
        if a * b < 0:
            rows.append('BTC與ETH漲跌方向分化，單一幣種無法代表整體。')
        elif weekly:
            # Daily: the price lines above already show this; it adds no information.
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
    if not weekly:
        return rows[:2]  # Daily: say nothing rather than a stock sentence.
    return rows[:3] or ['可比較資料不足，本次不補寫市場方向。']


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
    source = ''
    parts = []
    for r in selected:
        part = (f'**{r["time"].astimezone(TZ):%m/%d %H:%M}｜{r["rule"]["name"]}**\n'
                f'{EVENT_WATCH.get(r["rule"]["key"], "核對公布結果、前值與資料所屬期間。")}')
        url = str(r['rule'].get('source') or '')
        if url.startswith('https://'):
            part += f'\n🔗 [官方來源]({url})'
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
    from crypto_news_notifier import same_news_event
    from news_checked_episodes import same_recap_episode
    for row in sorted(state.get('weekly_journal', []), key=lambda r: (news_score(r), str(r.get('published', ''))), reverse=True):
        time = instant(row.get('published'))
        if not time or not start <= time <= now or not str(row.get('url', '')).startswith('https://'):
            continue
        title = headline(row)
        if '中文標題待確認' in title:
            continue
        previous = next((prior for prior in selected if same_news_event(row, prior) or same_recap_episode(row,prior)),None)
        if previous:
            if row['url']!=previous['url']:
                refs=previous.setdefault('recap_related_sources',[])
                if all(r['url']!=row['url'] for r in refs) and len(refs)<2:
                    refs.append({'source':row['source'],'url':row['url'],'published':row['published']})
            continue
        selected.append({**row,'recap_related_sources':[dict(ref) for ref in row.get('recap_related_sources',[])]})
    since = instant(state.get('weekly_journal_started_at'))
    return {'items': selected[:3], 'complete_window': bool(since and since <= start)}


def review_lines(data):
    review = data.get('news_review') or {}
    lines = []
    for i, row in enumerate(review.get('items') or []):
        title = headline(row).replace('[', '').replace(']', '')[:90]
        points = chinese_points(row)
        detail = ('\n' + points[0]) if points else ''
        part = f'**{i+1:02d}｜{title}**{detail}\n{stamp(row["published"])}｜[{str(row["source"])[:50]}]({row["url"]})'
        for ref in row.get('recap_related_sources',[])[:2]:
            related=f'\n同事件其他報導｜[{str(ref["source"])[:50]}]({ref["url"]})'
            if len('\n\n'.join(lines+[part+related]))<=850:
                part+=related
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


def daily_top_three(data, market, events, now, event_error=None):
    """Summarize only checked values; missing, stale and partial inputs stay explicit."""
    prices = []
    for symbol in ('BTC', 'ETH'):
        row = (data.get('crypto') or {}).get(symbol) or (market or {}).get(symbol) or {}
        if (number(row.get('price')) and number(row.get('change_24h', row.get('change')))
                and (not row.get('source') or fresh(row.get('updated_at'), now, .5))):
            prices.append(f'{symbol} {row["price"]:,.2f} {row.get("quote_currency", "USD")}（{signed(row.get("change_24h", row.get("change")))}）')
        else:
            prices.append(f'{symbol}價格或漲跌待確認')
    flows = []
    for key, symbol in (('etf', 'BTC'), ('eth_etf', 'ETH')):
        row = data.get(key) or {}
        date = row.get('date')
        unlisted = bool(row.get('unreported_components', 0))
        if not row.get('source_issue') and number(row.get('net_flow_musd')) and hasattr(date, 'strftime'):
            if float(row['net_flow_musd']) == 0 and unlisted:
                # Same rule as the ETF section below: a zero total with unlisted
                # fund cells is not a confirmed zero flow.
                flows.append(f'{date:%m/%d} {symbol} Farside尚未列出完整數據')
                continue
            partial = '（初值）' if row.get('partial') else '（暫定）' if unlisted else ''
            flows.append(f'{date:%m/%d} {symbol} {money_musd(row["net_flow_musd"])}{partial}')
        else:
            flows.append(f'{symbol} ETF資料待核對')
    calendar = ('行事曆未完整確認，請查看下方來源狀態。' if event_error else
                events_lines(events, now, None, False, budget=650).split('\n')[0])
    return '\n'.join(('**先看三件事**', '01｜價格：'+'；'.join(prices),
                      '02｜ETF：'+'；'.join(flows), '03｜行程：'+calendar,
                      '各資料期間、來源與完整度見下方；不據此推論漲跌原因。'))


def build_card(period, now, market, market_error, events, event_error, data):
    data = data or {}
    weekly = period == 'weekly'
    fields = [field('📈 一週價格變化' if weekly else '📈 價格表現｜24小時', price_lines(data, market, now, weekly))]
    if not weekly:
        fields.append(field('🌐 市場概況', global_lines(data, now)))
    fields.extend([field('🌡️ 一週情緒變化' if weekly else '🌡️ 市場情緒', sentiment_lines(data, now, weekly)),
                   field('💰 一週ETF資金' if weekly else '💰 ETF資金動向', etf_lines(data, weekly)),
                   field('⚖️ 合約概況｜Bitget優先・幣安備援', contract_lines(data, now, weekly))])
    if weekly:
        fields.append(field('📰 上週關鍵事件｜已推播紀錄', review_lines(data)))
        fields.append(field('🧩 一週統整與總結', '\n\n'.join('• ' + line for line in observations(data, True, now)) + '\n\n**本週總結**｜' + weekly_conclusion(data)))
        fields.append(field('📅 本週要注意什麼｜未來七日', events_lines(events, now, event_error, True)))
    else:
        notes = observations(data, False, now)
        fields.append(field('📅 今日關注', events_lines(events, now, event_error, False, budget=650)
                            + ('\n\n**📌 市場觀察**\n' + '\n'.join('• ' + line for line in notes) if notes else '')
                            # One reading note replaces the per-section caveats.
                            + '\n\n-# 讀法：市占是市值占比、非資金流量；情緒不等於漲跌預測；未平倉變化不代表多空方向；價格為查詢快照。'))
    description = '用一週的變化做整理，再準備這週的行程。' if weekly else '價格、情緒、資金，一張掌握今天的市場狀態。'
    if not weekly:
        description += '\n\n' + daily_top_three(data, market, events, now, event_error)
    if data.get('errors') or market_error or any(
            row.get('error') or row.get('weekly_error')
            for key in ('crypto', 'weekly_crypto', 'derivatives', 'weekly_derivatives')
            for row in (data.get(key) or {}).values()):
        description += '\n⚠️ 部分資料暫缺；各區塊只顯示已取得的內容。'
    card = {'title': f'{"🧭 每週市場導航" if weekly else "📊 每日市場情報"}｜{now.astimezone(TZ):%m/%d}',
            'description': description, 'fields': fields, 'color': 0x8274B0 if weekly else 0x647FB5,
            'footer': {'text': f'查詢：{now.astimezone(TZ):%m/%d %H:%M}（台灣時間）｜各資料依標示期間｜不構成投資建議'}, 'timestamp': now.isoformat()}
    total = len(card['title']) + len(description) + len(card['footer']['text']) + sum(len(f['name']) + len(f['value']) for f in fields)
    if total > 5800:
        raise ValueError('Market brief exceeds Discord total limit')
    return card
