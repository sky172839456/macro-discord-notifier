"""Low-noise member notifications; legacy templates remain available for rollback."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
CORE_EVENTS = {"cpi", "jobs", "pce", "fomc"}
RESULT_EVENTS = CORE_EVENTS | {"ppi", "retail", "claims", "gdp", "durable", "jolts", "industrial"}
CALENDAR_EVENTS = CORE_EVENTS | {"ppi", "gdp", "retail", "claims", "jolts", "durable", "industrial"}
REMINDER_EVENTS = CORE_EVENTS | {"fed_chair_policy"}
CALENDAR_EVENTS |= {"fed_chair_policy"}


def enabled():
    return os.getenv("SLIM_NOTIFICATIONS", "0") == "1"


def material_news(item):
    """A topic keyword alone never makes an article urgent."""
    import news_auto_recovery as auto
    if auto.enabled():
        return auto.material_news(item)
    from news_editorial import event_kind
    return event_kind(item) in {'safety', 'decision'}


def category(text, categories):
    lowered = f" {text.lower()} "
    from news_verified_context import core_policy_text
    if core_policy_text(text):
        return next(dict(row, priority='normal') for row in categories if row['key'] == 'network')
    from news_editorial import acquisition_with_only_old_incident
    if acquisition_with_only_old_incident(text):
        result = next((dict(row) for row in categories if row['key'] == 'exchange'), None)
        if result:
            result['priority'] = 'critical' if material_news({'title': text}) else 'normal'
            return result
    # 已核對的價格／期權新聞：ETF 流入僅是摘要背景，不覆蓋其市場主題。
    # 完整標題與摘要均相符才修正；新增政策、資安或 ETF 進展仍走既有分類。
    market_context = (
        "Bitcoin drops to $81,400 as Asian chip stocks tumble, options traders seek downside protection "
        "Bitcoin slipped 0.5% to around $81,400 even after the biggest daily spot ETF inflow in nearly "
        "a month as South Korea's Kospi index fell 3.7% on AI worries."
    )
    if re.sub(r'\s+', ' ', text.strip()).casefold() == market_context.casefold():
        result = next((dict(row) for row in categories if row['key'] == 'market'), None)
        if result:
            result['priority'] = 'normal'
            return result
    # OCC 的 GENIUS 法案發行人規則屬監管；reserve 在此不是 ETF 儲備。
    occ_rules = (
        'OCC Finalizes GENIUS Act Stablecoin Rules Ahead of January Deadline '
        'The rule sets reserve, redemption and risk standards for issuers, but the OCC has yet '
        'to say when it will begin accepting applications.'
    )
    if re.sub(r'\s+', ' ', text.strip()).casefold() == occ_rules.casefold():
        result = next((dict(row) for row in categories if row['key'] == 'regulation'), None)
        if result:
            result['priority'] = 'critical' if material_news({'title': text}) else 'normal'
            return result
    tax_policy = (re.search(r'\b(?:stablecoins?|crypto|cryptocurrency|digital assets?)\b', lowered)
                  and re.search(r'\b(?:tax|taxes|taxation)\b', lowered)
                  and re.search(r'\b(?:assembly|parliament|amendments?|proposals?|legislation|tax laws?|tax rules?)\b', lowered))
    # 主題優先於公司名；Fidelity 的網路研究不等同 ETF 公告。
    network_research = (re.search(r'\b(?:report|research|study)\b', lowered)
                        and re.search(r'\b(?:mainnet outages?|network health|network resilience|stake concentration|client software)\b', lowered)
                        and not re.search(r'\b(?:etfs?|exchange.traded|fund flows?)\b', lowered))
    courts_partners = bool(re.search(r'\bcourt(?:s|ed|ing)?\s+(?:(?:its|their|new|existing)\s+)*partners?\b', lowered))
    legal_court = bool(re.search(r'\b(?:court (?:orders?|rulings?|decisions?|cases?|filings?|rejects?|approves?|rules?|hears?|blocks?|denies|overturns?|of appeals)|supreme court|federal court|district court|lawsuit|litigation)\b', lowered))
    stablecoin_reserves = (re.search(r'\b(?:stablecoins?|usdc|usdt|tether)\b', lowered)
                          and re.search(r'\breserves?\s+(?:income|assets?|backing|revenue)\b', lowered))
    for row in categories:
        terms = row["keywords"]
        if row['key'] == 'regulation' and tax_policy:
            result = dict(row)
            result['priority'] = 'critical' if material_news({'title': text}) else 'normal'
            return result
        if row["key"] == "regulation" and courts_partners and not legal_court:
            terms = tuple(t for t in terms if t != 'court')
        if row["key"] == "etf" and stablecoin_reserves:
            terms = tuple(t for t in terms if t != 'reserve')
        if row["key"] == "etf" and network_research:
            result = next((dict(r) for r in categories if r['key'] == 'network'), None)
            if result:
                result['priority'] = 'normal'
                return result
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
    if not item.get('official'):
        headline = '媒體報導｜' + headline
    points = [clean_source_text(p, 220) for p in chinese_points(item)]
    fact = "\n".join(f"• {p}" for p in points[:2])
    if not fact:
        fact = "來源未提供可確認的中文摘要，請閱讀原文；不以分類模板補寫事實。"
    if item.get('summary_basis') == 'headline':
        fact += '\n-# 本則依原文標題整理；完整背景請見來源。'
    from news_editorial import short_context
    context = short_context(item)
    if context:
        fact += f"\n\n**{context[0]}**\n{context[1]}"
    local = item["published"].astimezone(TAIPEI)
    timing, late = time_copy(item['published'], now or item['published'])
    return {
        "title": ("🧪 測試｜" if test else "") + ("🚨 快訊｜" if material_news(item) else "📰 ") + (f"{item['category'].get('label', '市場動態')}｜" if item.get('auto_copy_version') else '') + ("補發｜" if late else "") + headline,
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
        attribution = '' if item.get('official') else '媒體報導｜'
        detail = f"\n{attribution}{points[0]}" if points else "\n中文摘要尚未確認，請閱讀原文。"
        if item.get('summary_basis') == 'headline':
            detail += '\n-# 依原文標題整理；完整背景請見來源。'
        if item.get('auto_copy_version'):
            detail = f"\n{item['category'].get('label', '市場動態')}" + detail
        links = [(item["source"], item["url"])] + [(r["source"], r["url"]) for r in item.get("related_sources", [])]
        sources = " · ".join(f"[{name}]({url})" for name, url in links[:3])
        from news_editorial import short_context
        context = short_context(item)
        if context:
            detail += f"\n{context[0]}｜{context[1]}"
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
    from crypto_news_notifier import same_news_event
    from news_editorial import member_ids, dated_terms
    for row in rows:
        match = next((k for k in kept if same_news_event(k, row)), None)
        if match:
            def completeness(value):
                from notification_quality import digest_exclusion_reason
                return (bool(value.get('official')), not bool(digest_exclusion_reason(value)),
                        len(dated_terms(str(value.get('summary', '')))),
                        'subject to' in str(value.get('summary', '')).lower())
            primary, secondary = (row, match) if completeness(row) > completeness(match) else (match, row)
            if not material_news(row) and not material_news(match):
                from notification_quality import digest_exclusion_reason
                if digest_exclusion_reason(primary) and not digest_exclusion_reason(secondary):
                    primary, secondary = secondary, primary
            merged = dict(primary)
            merged['merged_ids'] = [key for key in dict.fromkeys(member_ids(primary) + member_ids(secondary)) if key != primary['id']]
            merged['event_context'] = list(dict.fromkeys([*primary.get('event_context', []), str(secondary.get('summary', '')), *secondary.get('event_context', [])]))[:12]
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
    if not selected:
        return []  # Never construct an empty member calendar, even via direct callers.
    lines = [f"**{e['time'].astimezone(TAIPEI):%H:%M}｜{e['rule']['name']}**\n🔗 [官方來源]({e['rule']['source']})" for e in selected]
    if error:
        lines.append("⚠️ 部分行事曆尚未確認；未列出不代表今天沒有事件。")
    intro = '台灣時間｜以下為今日尚未發生的追蹤事件。\n\n'
    pages, current = [], []
    for line in lines:
        if current and len(intro + '\n\n'.join(current + [line])) > 3500:
            pages.append(current)
            current = []
        current.append(line)
    if current or not pages:
        pages.append(current)
    return [{"title": f"🗓️ 今日總經行事曆｜{now.astimezone(TAIPEI):%m/%d}｜共{len(selected)}項" + (f"｜{i+1}/{len(pages)}" if len(pages) > 1 else ''),
             "description": intro + "\n\n".join(page), "fields": [], "color": 0x647FB5,
             "footer": {"text": "台灣時間｜核心數據與已核對主席政策談話另發一次提醒"}}
            for i, page in enumerate(pages)]


def calendar_card(events, now, error=None):
    cards = calendar_cards(events, now, error)
    return cards[0] if cards else None


def summary_card(period, now, market, market_error, events, event_error, dashboard):
    from market_brief_v2 import build_card
    return build_card(period, now, market, market_error, events, event_error, dashboard)
