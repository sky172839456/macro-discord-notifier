"""Low-noise member notifications; legacy templates remain available for rollback."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
CORE_EVENTS = {"cpi", "jobs", "pce", "fomc"}
CALENDAR_EVENTS = CORE_EVENTS | {"ppi", "gdp", "retail", "claims", "jolts", "durable"}
REMINDER_EVENTS = CORE_EVENTS | {"fed_chair_policy"}
CALENDAR_EVENTS |= {"fed_chair_policy"}


def enabled():
    return os.getenv("SLIM_NOTIFICATIONS", "0") == "1"


def material_news(item):
    """A topic keyword alone never makes an article urgent."""
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    historical = ("jailed", "sentenced", "debate", "safer", "price prediction", "could", "opinion")
    if any(term in text for term in historical):
        return False
    incident = any(term in text for term in (
        "hacked", "exploit", "breach", "funds stolen", "withdrawals halted",
        "withdrawals suspended", "withdrawals paused", "major outage", "depeg",
    ))
    decision = any(term in text for term in (
        "approves", "approved", "rejects", "rejected", "enacted", "court orders", "files for bankruptcy",
    )) and any(term in text for term in ("sec", "regulator", "court", "etf", "exchange"))
    return incident or decision


def category(text, categories):
    lowered = f" {text.lower()} "
    for row in categories:
        terms = row["keywords"]
        if row["key"] == "network":
            terms = tuple(t for t in terms if t not in {"bitcoin", "ethereum", "solana"})
        if any(t in lowered for t in terms):
            result = dict(row)
            result["priority"] = "critical" if material_news({"title": text}) else "normal"
            return result
    if any(t in lowered for t in ("bitcoin", "btc", "ether", "crypto", "xrp")):
        return {"key": "market", "icon": "📊", "label": "市場動態", "priority": "normal"}
    return None


def event_identity(title):
    """Conservative identity for recurring treasury purchases, not entity-only dedup."""
    text = title.lower()
    entity = next((s for s in ("strategy", "bitmine") if re.search(rf"\b{s}\b", text)), None)
    action = re.search(r"\b(adds?|buys?|bought|purchases?|scoops? up|acquires?|accumulat\w*)\b", text)
    asset = "btc" if re.search(r"\b(bitcoin|btc)\b", text) else "eth" if re.search(r"\b(ethereum|ether|eth)\b", text) else None
    if not (entity and action and asset):
        return None
    quantities = set(re.findall(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:bitcoin|btc|ether|eth)\b", text))
    return entity, asset, quantities


def same_event(left, right):
    a, b = event_identity(left), event_identity(right)
    if not a or not b or a[:2] != b[:2]:
        return False
    # Contradicting explicit purchase sizes can represent a new material event.
    return not (a[2] and b[2] and not (a[2] & b[2]))


def news_card(item, test=False, now=None):
    from notification_format import clean_source_text
    from notification_quality import headline as checked_headline, chinese_points, time_copy
    headline = clean_source_text(checked_headline(item), 200)
    points = [clean_source_text(p, 220) for p in chinese_points(item)]
    fact = "\n".join(f"• {p}" for p in points[:2])
    if not fact:
        fact = "來源未提供可確認的中文摘要，請閱讀原文；不以分類模板補寫事實。"
    local = item["published"].astimezone(TAIPEI)
    timing, late = time_copy(item['published'], now or item['published'])
    return {
        "title": ("🧪 測試｜" if test else "") + ("🚨 快訊｜" if material_news(item) else "📰 ") + ("補發｜" if late else "") + headline,
        "description": fact,
        "url": item["url"],
        "color": 0xE74C3C if material_news(item) else 0x3498DB,
        "fields": [{"name": "🔗 原文與時間", "value": f"{'官方公告' if item['official'] else '媒體報導'}｜[{item['source']}]({item['url']})\n{timing}", "inline": False}],
        "footer": {"text": "不構成投資建議"},
        "timestamp": item["published"].isoformat(),
    }


def digest_card(items, now):
    from notification_quality import headline, chinese_points
    lines = []
    for item in items[:5]:
        title = headline(item)[:150].replace("\n", " ")
        points = [str(p)[:160] for p in chinese_points(item)]
        detail = f"\n{points[0]}" if points else "\n中文摘要尚未確認，請閱讀原文。"
        links = [(item["source"], item["url"])] + [(r["source"], r["url"]) for r in item.get("related_sources", [])]
        sources = " · ".join(f"[{name}]({url})" for name, url in links[:3])
        lines.append(f"**{len(lines)+1:02d}｜{title}**{detail}\n🔗 {sources}\n📅 原文發布：{item['published'].astimezone(TAIPEI):%m/%d %H:%M}")
    return {"title": f"📰 今日新聞重點｜{now.astimezone(TAIPEI):%m/%d}",
            "description": "\n\n".join(lines), "color": 0x3498DB,
            "footer": {"text": "依事件影響、來源與時效排序｜每日最多五件｜不構成投資建議"},
            "timestamp": now.isoformat()}


def digest_groups(items, now):
    groups, current = [], []
    for item in items[:5]:
        candidate = dict(item)
        if len(digest_card([candidate], now)['description']) > 3500:
            candidate['related_sources'] = []  # retain the primary article URL
        if current and len(digest_card(current + [candidate], now)['description']) > 3500:
            groups.append(current)
            current = []
        current.append(candidate)
    if current:
        groups.append(current)
    return groups


def digest_cards(items, now):
    cards = [digest_card(group, now) for group in digest_groups(items, now)]
    if len(cards) > 1:
        for i, card in enumerate(cards):
            card['title'] += f'｜{i+1}/{len(cards)}'
    return cards


def merge_pending(rows):
    """Keep one event, retaining multiple source links for transparency."""
    kept = []
    from crypto_news_notifier import similar_title
    for row in rows:
        match = next((k for k in kept if similar_title(k["title"], row["title"])), None)
        if match:
            primary, secondary = (row, match) if row.get('official') and not match.get('official') else (match, row)
            merged = dict(primary)
            refs, seen = [], {primary.get('url')}
            for ref in [*primary.get('related_sources', []), {'source': secondary['source'], 'url': secondary['url']}, *secondary.get('related_sources', [])]:
                if ref.get('url') and ref['url'] not in seen:
                    refs.append(ref)
                    seen.add(ref['url'])
            merged['related_sources'] = refs
            kept[kept.index(match)] = merged
        else:
            kept.append(row)
    return kept


def today_events(events, now, days=1):
    today = now.astimezone(TAIPEI).date()
    kept, seen = [], set()
    for event in sorted(events, key=lambda e: e['time']):
        identity = (event['rule']['key'], event['time'].replace(second=0, microsecond=0), event.get('speaker', ''))
        if (event['rule']['key'] in CALENDAR_EVENTS and event['time'] >= now
                and today <= event['time'].astimezone(TAIPEI).date() < today + timedelta(days=days)
                and identity not in seen):
            kept.append(event)
            seen.add(identity)
    return kept


def reminder_due(event, now):
    return event["rule"]["key"] in REMINDER_EVENTS and 0 < (event["time"]-now).total_seconds()/60 <= 27


def calendar_cards(events, now, error=None):
    selected = today_events(events, now)
    lines = [f"**{e['time'].astimezone(TAIPEI):%H:%M}｜{e['rule']['name']}**\n🔗 [官方來源]({e['rule']['source']})" for e in selected]
    if error:
        lines.append("⚠️ 部分行事曆尚未確認；未列出不代表今天沒有事件。")
    pages, current = [], []
    for line in lines:
        if current and len('\n\n'.join(current + [line])) > 3500:
            pages.append(current)
            current = []
        current.append(line)
    if current or not pages:
        pages.append(current)
    return [{"title": f"🗓️ 今日總經行事曆｜{now.astimezone(TAIPEI):%m/%d}｜共{len(selected)}項" + (f"｜{i+1}/{len(pages)}" if len(pages) > 1 else ''),
             "description": "\n\n".join(page), "fields": [], "color": 0x647FB5,
             "footer": {"text": "台灣時間｜核心數據與已核對主席政策談話另發一次提醒"}}
            for i, page in enumerate(pages)]


def calendar_card(events, now, error=None):
    return calendar_cards(events, now, error)[0]


def summary_card(period, now, market, market_error, events, event_error, dashboard):
    from notification_quality import money_musd
    dashboard = dashboard or {}
    weekly = period == "weekly"
    coins = dashboard.get("weekly_crypto" if weekly else "crypto") or {}
    lines = []
    for symbol in ("BTC", "ETH"):
        item = coins.get(symbol) or (market or {}).get(symbol)
        if item:
            change = item.get("change_7d" if weekly else "change_24h", item.get("change"))
            suffix = f"　{change:+.2f}%" if change is not None else "　漲跌幅暫缺"
            lines.append(f"**{symbol}**　${item['price']:,.2f}{suffix}")
        else:
            lines.append(f"⚠️ {symbol} 價格暫缺")
    facts = []
    if weekly:
        for key, asset in (("weekly_btc_etf", "BTC"), ("weekly_eth_etf", "ETH")):
            row = dashboard.get(key)
            if row:
                facts.append(f"美國現貨 {asset} ETF：{row['start_date']:%m/%d}～{row['end_date']:%m/%d} {money_musd(row['net_flow_musd'])}。")
    else:
        for key, asset in (("etf", "BTC"), ("eth_etf", "ETH")):
            row = dashboard.get(key)
            if row:
                facts.append(f"美國現貨 {asset} ETF：{row['date']:%m/%d} {money_musd(row['net_flow_musd'])}。")
        sentiment = dashboard.get("sentiment")
        if sentiment and (sentiment["value"] <= 25 or sentiment["value"] >= 75):
            facts.append(f"恐慌貪婪指數 {sentiment['value']}/100，位於極端區間；不等同價格方向訊號。")
    errors = dashboard.get("errors") or {}
    if errors or market_error:
        facts = ["⚠️ 部分資料暫缺；下方僅列已取得的資料。"] + facts
    selected = today_events(events, now, 7 if weekly else 1)
    event_text = "\n".join(f"{e['time'].astimezone(TAIPEI):%m/%d %H:%M}｜{e['rule']['name']}" for e in selected[:3])
    if event_error:
        event_text += "\n⚠️ 行事曆尚未完整確認。"
    fields = [{"name": "本週表現" if weekly else "24 小時表現", "value": "\n".join(lines), "inline": False}]
    if facts:
        fields.append({"name": "重點資料", "value": "\n".join(f"• {f}" for f in facts[:3]), "inline": False})
    fields.append({"name": "未來七日重點" if weekly else "今日事件", "value": event_text.strip() or "目前未查到已排定的追蹤事件。", "inline": False})
    fields.append({"name": "資料來源", "value": "[價格](https://www.coingecko.com/) · [BTC ETF](https://farside.co.uk/btc/) · [ETH ETF](https://farside.co.uk/eth/) · [行事曆](https://www.forexfactory.com/calendar)", "inline": False})
    return {"title": f"{'🗓️ 本週市場重點' if weekly else '📊 每日市場重點'}｜{now.astimezone(TAIPEI):%m/%d}",
            "description": "先看價格表現，再看資金資料與事件時間。", "fields": fields,
            "color": 0x8E44AD if weekly else 0x3498DB,
            "footer": {"text": "價格為查詢快照；ETF依標示日期｜不構成投資建議"}, "timestamp": now.isoformat()}
