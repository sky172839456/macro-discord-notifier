"""Low-noise member notifications; legacy templates remain available for rollback."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
CORE_EVENTS = {"cpi", "jobs", "pce", "fomc"}
CALENDAR_EVENTS = CORE_EVENTS | {"ppi", "gdp", "retail", "claims", "jolts", "durable"}


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


def news_card(item, test=False):
    from notification_format import clean_source_text
    headline = clean_source_text(item.get("title_zh") or item["title"], 200)
    points = [clean_source_text(p, 220) for p in item.get("summary_zh_points", [])
              if not p.startswith("消息涉及")]
    fact = "\n".join(f"• {p}" for p in points[:2])
    if not fact:
        fact = "來源未提供可確認的中文摘要，請閱讀原文；不以分類模板補寫事實。"
    local = item["published"].astimezone(TAIPEI)
    return {
        "title": ("🧪 測試｜" if test else "") + ("🚨 快訊｜" if material_news(item) else "📰 ") + headline,
        "description": fact,
        "url": item["url"],
        "color": 0xE74C3C if material_news(item) else 0x3498DB,
        "fields": [{"name": "來源與發布時間", "value": f"{'官方公告' if item['official'] else '媒體報導'}｜[{item['source']}]({item['url']})｜{local:%m/%d %H:%M}（台灣）", "inline": False}],
        "footer": {"text": "不構成投資建議"},
        "timestamp": item["published"].isoformat(),
    }


def digest_card(items, now):
    lines = []
    for item in items[:5]:
        headline = str(item.get("title_zh") or item["title"])[:150].replace("\n", " ")
        points = [str(p)[:160] for p in item.get("summary_zh_points", []) if not p.startswith("消息涉及")]
        detail = f"\n{points[0]}" if points else ""
        links = [(item["source"], item["url"])] + [(r["source"], r["url"]) for r in item.get("related_sources", [])]
        sources = " · ".join(f"[{name}]({url})" for name, url in links[:3])
        lines.append(f"**{len(lines)+1}｜{headline}**{detail}\n{sources}｜{item['published'].astimezone(TAIPEI):%m/%d %H:%M}")
    return {"title": f"📰 今日新聞重點｜{now.astimezone(TAIPEI):%m/%d}",
            "description": "\n\n".join(lines), "color": 0x3498DB,
            "footer": {"text": "最多五個獨立事件｜來源時間為台灣時間｜不構成投資建議"},
            "timestamp": now.isoformat()}


def merge_pending(rows):
    """Keep one event, retaining multiple source links for transparency."""
    kept = []
    from crypto_news_notifier import similar_title
    for row in rows:
        match = next((k for k in kept if similar_title(k["title"], row["title"])), None)
        if match:
            refs = match.setdefault("related_sources", [])
            if row.get("url") != match.get("url") and not any(r["url"] == row["url"] for r in refs):
                refs.append({"source": row["source"], "url": row["url"]})
        else:
            kept.append(row)
    return kept


def today_events(events, now, days=1):
    today = now.astimezone(TAIPEI).date()
    return [e for e in sorted(events, key=lambda e: e["time"])
            if e["rule"]["key"] in CALENDAR_EVENTS and e["time"] >= now
            and today <= e["time"].astimezone(TAIPEI).date() < today + timedelta(days=days)]


def reminder_due(event, now):
    return event["rule"]["key"] in CORE_EVENTS and 0 < (event["time"]-now).total_seconds()/60 <= 27


def calendar_card(events, now, error=None):
    selected = today_events(events, now)
    lines = [f"**{e['time'].astimezone(TAIPEI):%H:%M}｜{e['rule']['name']}** · [來源]({e['rule']['source']})" for e in selected[:5]]
    if error:
        lines.append("⚠️ 部分行事曆尚未確認；未列出不代表今天沒有事件。")
    return {"title": f"🗓️ 今日總經行事曆｜{now.astimezone(TAIPEI):%m/%d}",
            "description": "\n".join(lines), "fields": [], "color": 0x3498DB,
            "footer": {"text": "台灣時間｜CPI、非農、PCE、FOMC另發提醒與結果"}}


def summary_card(period, now, market, market_error, events, event_error, dashboard):
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
                facts.append(f"美國現貨 {asset} ETF：{row['start_date']:%m/%d}～{row['end_date']:%m/%d} 淨{'流入' if row['net_flow_musd'] >= 0 else '流出'} {abs(row['net_flow_musd']):,.1f} 百萬美元。")
    else:
        for key, asset in (("etf", "BTC"), ("eth_etf", "ETH")):
            row = dashboard.get(key)
            if row:
                facts.append(f"美國現貨 {asset} ETF：{row['date']:%m/%d} 淨{'流入' if row['net_flow_musd'] >= 0 else '流出'} {abs(row['net_flow_musd']):,.1f} 百萬美元。")
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
