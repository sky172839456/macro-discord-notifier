"""High-signal crypto news radar for Discord (standard library only)."""

from __future__ import annotations
import slim_policy

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from notification_format import (apply_delivery_format, bilingual_sections, clean_source_text,
                                 english_key_points, english_summary_excerpt)

TAIPEI = ZoneInfo("Asia/Taipei")
STATE_FILE = Path(os.getenv("CRYPTO_NEWS_STATE_FILE", ".state/crypto-news.json"))
MAX_IMMEDIATE_PER_RUN = 4
MAX_DIGEST_ITEMS = 8
DIGEST_ITEMS_PER_CARD = 4
RECENT_HOURS = 48
TRANSLATION_URL = "https://api.mymemory.translated.net/get"

SOURCES = (
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "official": False},
    {"name": "Decrypt", "url": "https://decrypt.co/feed", "official": False},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "official": False},
    {"name": "Ethereum Foundation", "url": "https://blog.ethereum.org/feed.xml", "official": True},
    {"name": "U.S. SEC", "url": "https://www.sec.gov/news/pressreleases.rss", "official": True},
)

HTTP_HEADERS = {
    "User-Agent": "macro-discord-notifier/1.0 crypto-news-radar contact: GitHub Actions",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
}

RELEVANCE = (
    "bitcoin", "btc", "ethereum", "ether", "eth", "crypto", "cryptocurrency", "blockchain",
    "stablecoin", "usdt", "usdc", "tether", "circle", "defi", "solana", "xrp", "ripple",
    "token", "digital asset", "coinbase", "binance", "bybit", "okx", "bitget", "kraken",
    "wallet", "web3", "spot etf", "exchange-traded fund",
)

CATEGORIES = (
    {"key": "security", "icon": "🚨", "label": "資安事件", "priority": "critical",
     "keywords": ("hack", "hacked", "exploit", "breach", "stolen", "attack", "vulnerability", "drain", "phishing")},
    {"key": "regulation", "icon": "🏛️", "label": "監管／政策", "priority": "high",
     "keywords": ("sec ", "cftc", "regulation", "regulator", "lawsuit", "court", "legislation", "sanction", "license", "ban ")},
    {"key": "etf", "icon": "🏦", "label": "ETF／機構", "priority": "high",
     "keywords": ("etf", "blackrock", "fidelity", "institutional", "treasury", "reserve", "fund flow")},
    {"key": "stablecoin", "icon": "💵", "label": "穩定幣", "priority": "high",
     "keywords": ("stablecoin", "usdt", "usdc", "tether", "circle", "depeg")},
    {"key": "exchange", "icon": "🏢", "label": "交易所重大事件", "priority": "high",
     "keywords": ("exchange", "coinbase", "binance", "bybit", "okx", "bitget", "kraken", "withdrawal", "insolvency")},
    {"key": "network", "icon": "⛓️", "label": "區塊鏈／協議", "priority": "normal",
     "keywords": ("upgrade", "hard fork", "mainnet", "outage", "validator", "protocol", "ethereum", "solana", "bitcoin")},
    {"key": "market", "icon": "📊", "label": "市場結構", "priority": "normal",
     "keywords": ("liquidation", "whale", "open interest", "token unlock", "market structure", "funding rate")},
)

EXCLUDE = (
    "price prediction", "could reach", "will hit", "top altcoins", "best crypto", "how to buy",
    "technical analysis", "sponsored", "press release", "casino", "presale",
)

ZH_SUMMARY = {
    "security": "消息涉及加密資產安全事件；請留意官方損失說明、提款狀態與後續處置。",
    "regulation": "消息涉及監管、法律或政策進展；實際適用範圍仍以主管機關及法院文件為準。",
    "etf": "消息涉及 ETF 或機構資金動向，可能影響主流加密資產的市場需求與情緒。",
    "stablecoin": "消息涉及穩定幣、儲備或脫鉤風險；請留意價格、贖回及發行商公告。",
    "exchange": "消息涉及交易所營運、監管或資金狀態；使用者應留意官方服務公告。",
    "network": "消息涉及主要區塊鏈或協議更新；請留意升級時程、相容性與網路穩定度。",
    "market": "消息涉及市場結構或大額部位變化，不代表單一方向的投資訊號。",
}

IMPACT = {
    "security": "可能提高短期避險情緒；事件影響需等待官方進一步確認。",
    "regulation": "可能影響相關地區的交易、發行或機構參與條件。",
    "etf": "可能影響 BTC／ETH 現貨需求與機構風險偏好。",
    "stablecoin": "若涉及儲備或贖回問題，可能擴散至交易所與 DeFi 流動性。",
    "exchange": "若服務受限，可能造成資金轉移與短期流動性變化。",
    "network": "重大升級或故障可能影響交易確認、應用服務與鏈上活動。",
    "market": "屬市場觀察資訊，仍需搭配價格、成交量與官方資料判斷。",
}


def http_text(url: str, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers=HTTP_HEADERS), timeout=10 if 'api.mymemory.translated.net' in url else 25) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def clean_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def element_text(node: ElementTree.Element | None) -> str:
    return clean_text("".join(node.itertext())) if node is not None else ""


def child(entry: ElementTree.Element, *names: str) -> ElementTree.Element | None:
    for name in names:
        node = entry.find(name)
        if node is not None:
            return node
    return None


def parse_date(value: str) -> datetime | None:
    try:
        if "," in value:
            result = parsedate_to_datetime(value)
        else:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def canonical_url(value: str) -> str:
    parsed = urlparse(value.strip())
    query = [(key, val) for key, val in parse_qsl(parsed.query) if not key.lower().startswith("utm_")]
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", urlencode(query), ""))


def normalize_zh_title(value: str) -> str:
    """Keep common crypto names recognizable in automatically translated titles."""
    replacements = {
        "比特幣": "Bitcoin", "位元幣": "Bitcoin", "以太坊": "Ethereum", "乙太坊": "Ethereum",
        "索拉納": "Solana", "美國證券交易委員會": "SEC", "證券交易委員會": "SEC",
        "交易所交易基金": "ETF", "SPOT": "現貨", "Spot": "現貨", "加密貨幣": "加密資產",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    value = value.replace("BitcoinETF", "Bitcoin ETF").replace("EthereumETF", "Ethereum ETF")
    value = re.sub(r"([\u3400-\u9fff])([A-Za-z0-9])", r"\1 \2", value)
    value = re.sub(r"([A-Za-z0-9])([\u3400-\u9fff])", r"\1 \2", value)
    return re.sub(r"\s+", " ", value).strip()


def utf8_prefix(value: str, limit: int = 450) -> str:
    """Trim text to an API byte limit without breaking a UTF-8 character."""
    encoded = value.encode("utf-8")[:limit]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""


def translate_text(value: str) -> str:
    import news_auto_recovery as auto
    if auto.enabled() and len(clean_text(value).encode('utf-8')) > 450:
        raise ValueError('translation sentence exceeds provider limit')
    if auto.enabled():
        return auto.translate(clean_text(value))
    query = urlencode({"q": utf8_prefix(clean_text(value)), "langpair": "en|zh-TW", "mt": "1"})
    payload = json.loads(http_text(f"{TRANSLATION_URL}?{query}", attempts=1 if auto.enabled() else 2))
    translated = clean_text(str(payload.get("responseData", {}).get("translatedText", "")))
    if not translated or translated.lower() == value.lower():
        raise ValueError("translation result unavailable")
    result = normalize_zh_title(translated)
    if slim_policy.enabled():
        from notification_quality import checked_translation
        result = checked_translation(value, result)
    return result


def translate_title(title: str) -> str:
    """Translate one public English headline to Traditional Chinese without an API key."""
    return translate_text(title)


def summary_points(value: str) -> list[str]:
    translated = translate_text(value)
    parts = [part.strip(" •-。") for part in re.split(r"[。！？!?；;]+", translated) if part.strip(" •-。")]
    if len(parts) == 1 and len(parts[0]) > 90:
        clauses = [part.strip(" ，,") for part in re.split(r"[，,]", parts[0]) if len(part.strip()) >= 12]
        if len(clauses) >= 2:
            parts = clauses
    return [part + ("。" if not part.endswith(("。", "！", "？")) else "") for part in parts[:3]]


def add_translated_title(item: dict[str, Any], state: dict[str, Any], now: datetime) -> dict[str, Any]:
    import news_auto_recovery as auto
    if auto.enabled():
        if item.get('auto_copy_version') == 2:
            from notification_quality import digest_exclusion_reason
            if not digest_exclusion_reason(item):
                return dict(item)
        return auto.enrich(item, state, now)
    cache = state.setdefault("translation_cache", {})
    key = hashlib.sha256(item["title"].encode()).hexdigest()[:20]
    cached = cache.get(key)
    enriched = dict(item)
    if cached and cached.get("source") == item["title"]:
        enriched["title_zh"] = cached["translated"]
        if slim_policy.enabled():
            from notification_quality import checked_translation
            try:
                enriched['title_zh'] = checked_translation(item['title'], enriched['title_zh'])
            except ValueError:
                enriched['title_zh'] = ''
    else:
        try:
            translated = translate_title(item["title"])
            enriched["title_zh"] = translated
            cache[key] = {"source": item["title"], "translated": translated, "date": now.date().isoformat()}
        except Exception:
            enriched["title_zh"] = '' if slim_policy.enabled() else item["title"]

    summary_key = "summary-" + hashlib.sha256(item["summary"].encode()).hexdigest()[:20]
    summary_cached = cache.get(summary_key)
    if summary_cached and summary_cached.get("source") == item["summary"]:
        points = list(summary_cached["points"])
    else:
        try:
            points = summary_points(item["summary"])
            cache[summary_key] = {
                "source": item["summary"], "points": points, "date": now.date().isoformat()
            }
        except Exception:
            points = []
    fallback = ZH_SUMMARY[item["category"]["key"]]
    if not slim_policy.enabled() and len(points) < 2 and fallback not in points:
        points.append(fallback)
    enriched["summary_zh_points"] = points[:3]
    return enriched


def category_for(text: str) -> dict[str, Any] | None:
    if slim_policy.enabled():
        return slim_policy.category(text, CATEGORIES)
    lowered = f" {text.lower()} "
    for category in CATEGORIES:
        if any(keyword in lowered for keyword in category["keywords"]):
            if category["key"] == "security" and any(term in lowered for term in ("jailed", "sentenced", "scanner", "have they solved", "one-year", "one year")):
                return {**category, "priority": "normal"}
            return category
    return None


def is_relevant(text: str, official: bool = False) -> bool:
    lowered = text.lower()
    if slim_policy.enabled():
        from news_editorial import safety_candidate
        if safety_candidate({'title': text}):
            return True
    if any(term in lowered for term in EXCLUDE):
        return False
    return (official and "ethereum" in lowered) or any(term in lowered for term in RELEVANCE)


def parse_feed(source: str, source_config: dict[str, Any]) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(source)
    entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    items: list[dict[str, Any]] = []
    for entry in entries[:30]:
        title = element_text(child(entry, "title", "{http://www.w3.org/2005/Atom}title"))
        summary = element_text(child(entry, "description", "summary", "content",
                                     "{http://www.w3.org/2005/Atom}summary",
                                     "{http://www.w3.org/2005/Atom}content"))
        link_node = child(entry, "link", "{http://www.w3.org/2005/Atom}link")
        link = (link_node.get("href") if link_node is not None else "") or element_text(link_node)
        date_value = element_text(child(entry, "pubDate", "published", "updated",
                                        "{http://www.w3.org/2005/Atom}published",
                                        "{http://www.w3.org/2005/Atom}updated"))
        published = parse_date(date_value)
        combined = f"{title} {summary}"
        category = category_for(combined)
        financial = None
        if source_config.get('stream') == 'finance':
            from news_streams import finance_topic
            financial = finance_topic({'title': title, 'summary': summary})
            if not financial:
                continue
            category = financial['category']
        if slim_policy.enabled():
            from news_editorial import safety_candidate
            if safety_candidate({'title': title, 'summary': summary}):
                category = dict(CATEGORIES[0])
        if not title or not link or not published or not category or (not financial and not is_relevant(combined, source_config["official"])):
            continue
        url = canonical_url(link)
        identifier = hashlib.sha256(f"{source_config['name']}|{url}|{title}".encode()).hexdigest()[:24]
        items.append({
            "id": identifier, "title": title, "summary": summary[:700], "url": url,
            "published": published, "source": source_config["name"],
            "official": source_config["official"], "category": category,
            **({'stream': 'finance', 'transmission': financial['copy']} if financial else {}),
        })
    return items


def title_tokens(title: str) -> set[str]:
    title = re.sub(r"\bu\.s\.", "us", title, flags=re.I)
    title = re.sub(r"\$?(\d+(?:\.\d+)?)\s*billion\b", r"\1b", title, flags=re.I)
    title = re.sub(r"\b(moves|moved|moving)\b", "move", title, flags=re.I)
    title = re.sub(r"\b(hacker|hacked)\b", "hack", title, flags=re.I)
    stop = {"the", "and", "for", "with", "from", "that", "this", "into", "after", "amid", "over", "says"}
    return {word for word in re.findall(r"[a-z0-9]{3,}", title.lower()) if word not in stop}


def similar_title(left: str, right: str) -> bool:
    if slim_policy.enabled() and slim_policy.same_event(left, right):
        return True
    def amounts(value):
        value = re.sub(r"\b(\d+(?:\.\d+)?)\s*billion\b", r"\1b", value.lower())
        return set(re.findall(r"\b\d+(?:\.\d+)?[bmkt]?\b", value))
    if amounts(left) != amounts(right):
        return False  # 數字改變可能代表新進展，不能只因標題相似就吞掉。
    a, b = title_tokens(left), title_tokens(right)
    return bool(a and b) and len(a & b) / len(a | b) >= 0.55


def same_news_event(left, right):
    if slim_policy.enabled():
        import news_auto_recovery as auto
        if auto.enabled() and auto.same_article(left, right):
            return True
        from news_editorial import equivalent
        return equivalent(left, right, similar_title)
    return similar_title(left['title'], right['title'])


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: (row["published"], row["official"]), reverse=True):
        duplicate = next((row for row in kept if same_news_event(item, row)), None)
        if duplicate:
            if slim_policy.enabled():
                merged = slim_policy.merge_pending([duplicate, item])
                kept[kept.index(duplicate)] = merged[0]
                continue
            if item["official"] and not duplicate["official"]:
                kept.remove(duplicate)
                kept.append(item)
            continue
        kept.append(item)
    return kept


def news_embed(item: dict[str, Any], test: bool = False, observed_at: datetime | None = None) -> dict[str, Any]:
    if slim_policy.enabled():
        return slim_policy.news_card(item, test, observed_at)
    category = item["category"]
    priority = {"critical": "重大", "high": "重要", "normal": "一般"}[category["priority"]]
    status = "✅ 官方確認" if item["official"] else "📰 媒體報導"
    prefix = "🧪 測試｜" if test else ""
    local = item["published"].astimezone(TAIPEI)
    excerpt = english_summary_excerpt(item["title"], item.get("summary"), 700)
    translated = item.get("title_zh", item["title"])
    points = item.get("summary_zh_points") or [ZH_SUMMARY[category["key"]]]
    bilingual = bilingual_sections(
        original_title=item["title"],
        english_summary=excerpt,
        english_points=english_key_points(excerpt),
        zh_title=translated,
        zh_points=points,
    )
    return {
        "author": {"name": "CRYPTO NEWS RADAR｜加密新聞"},
        "title": f"{prefix}{category['icon']} {priority}｜{category['label']}",
        "description": f"{bilingual}\n\n**市場觀察**\n{IMPACT[category['key']]}",
        "color": 0xE74C3C if category["priority"] == "critical" else 0xF39C12,
        "fields": [
            {"name": "可信狀態", "value": status, "inline": True},
            {"name": "來源", "value": item["source"], "inline": True},
            {"name": "發布時間", "value": local.strftime("%m/%d %H:%M（台灣）"), "inline": True},
            {"name": "🔗 原文連結", "value": item["url"], "inline": False},
        ],
        "footer": {"text": "原標題與原文連結保留｜繁中重點為分類式摘要｜不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def digest_embed(items: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Render one readable card per article for the hourly digest."""
    if slim_policy.enabled():
        return slim_policy.digest_cards(items, now)
    cards = []
    for item in items[:DIGEST_ITEMS_PER_CARD]:
        card = news_embed(item)
        card["title"] = "📰 每小時摘要｜" + card["title"]
        card["footer"]["text"] = "每小時一般新聞摘要｜每則新聞獨立顯示｜僅供資訊參考"
        card["timestamp"] = now.isoformat()
        cards.append(card)
    return cards


def send_discord(webhook: str, embed: dict[str, Any] | list[dict[str, Any]],
                 username: str = "加密新聞雷達") -> None:
    channel_key = {
        "加密重大快訊": "breaking_news",
        "監管與 ETF 雷達": "regulation_etf",
        "新聞核對｜管理員": "bot_log",
        "金融風向": "finance_news",
        "新聞系統｜服務紀錄": "bot_log",
    }.get(username, "crypto_news")
    embeds = embed if isinstance(embed, list) else [embed]
    cards = [apply_delivery_format(card, channel_key) for card in embeds]
    payload = json.dumps({
        "username": username,
        "embeds": cards,
        "allowed_mentions": {"parse": []},
    }).encode("utf-8")
    url = webhook + ("&" if "?" in webhook else "?") + "wait=true"
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "macro-discord-notifier/2.0"},
        method="POST",
    )
    with urlopen(request, timeout=25):
        pass


def destination_for(item: dict[str, Any], default_webhook: str) -> tuple[str, str]:
    """Route specialized categories once; fall back to the general news channel."""
    category = item["category"]
    if os.environ.get("CONSOLIDATED_CHANNELS") == "1":
        return default_webhook, "市場快訊"
    if category["priority"] == "critical":
        webhook = os.environ.get("DISCORD_BREAKING_NEWS_WEBHOOK_URL")
        if webhook:
            return webhook, "加密重大快訊"
    if category["key"] in {"regulation", "etf"}:
        webhook = os.environ.get("DISCORD_REGULATION_ETF_WEBHOOK_URL")
        if webhook:
            return webhook, "監管與 ETF 雷達"
    return default_webhook, "加密新聞雷達"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"initialized": False, "seen": {}, "pending": [], "last_digest_slot": "", "translation_cache": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_all() -> tuple[list[dict[str, Any]], list[tuple[str, int, str | None]]]:
    items, statuses = [], []
    for source_config in SOURCES:
        try:
            parsed = parse_feed(http_text(source_config["url"]), source_config)
            items.extend(parsed)
            statuses.append((source_config["name"], len(parsed), None))
        except Exception as exc:
            statuses.append((source_config["name"], -1, f"{type(exc).__name__} / {exc}"))
    return deduplicate(items), statuses


def initialize_baseline(now: datetime) -> tuple[int, list[tuple[str, int, str | None]]]:
    """Record current articles without publishing them, preventing a first-run flood."""
    items, statuses = fetch_all()
    if not any(count >= 0 for _, count, _ in statuses):
        raise RuntimeError("所有加密新聞來源皆無法讀取")
    state = load_state()
    seen = state.setdefault("seen", {})
    for item in items:
        seen[item["id"]] = now.date().isoformat()
    state["initialized"] = True
    save_state(state)
    return len(items), statuses


def connectivity_embed(count: int, statuses: list[tuple[str, int, str | None]], now: datetime) -> dict[str, Any]:
    lines = [f"{'✅' if error is None else '⚠️'} **{name}**｜{count if error is None else error}"
             for name, count, error in statuses]
    return {
        "author": {"name": "CRYPTO NEWS RADAR｜加密新聞"},
        "title": "✅ 加密新聞雷達正式連線成功",
        "description": (
            f"已建立 **{count} 篇**現有新聞基準，不會把舊文章洗進正式頻道。\n\n"
            + "\n".join(lines)
            + "\n\n接下來只會通知新出現且符合高訊號條件的新聞。"
        ),
        "color": 0x2ECC71,
        "footer": {"text": "正式頻道連線測試｜這不是新聞公告"},
        "timestamp": now.isoformat(),
    }


def run(now: datetime) -> tuple[int, int]:
    if os.getenv('NEWS_SPLIT_STREAMS') == '1':
        from news_streams import run as run_streams
        return run_streams(now)
    webhook = os.environ.get("DISCORD_CRYPTO_NEWS_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("缺少 DISCORD_CRYPTO_NEWS_WEBHOOK_URL")
    state = load_state()
    items, statuses = fetch_all()
    if not any(count >= 0 for _, count, _ in statuses):
        raise RuntimeError("所有加密新聞來源皆無法讀取")
    seen = state.setdefault("seen", {})
    import news_auto_recovery as auto
    recent_cutoff = now - timedelta(hours=24 if auto.enabled() else RECENT_HOURS)
    candidates = [item for item in items if item["published"] >= recent_cutoff and item["id"] not in seen]
    # 跨輪次也保留已發送標題，避免同事件換媒體網址後再次即時推送。
    history = [row for row in state.get("headline_history", []) if row.get("date", "") >= (now - timedelta(hours=24)).isoformat()]
    unique = []
    for item in candidates:
        if any(same_news_event(item, {**row, 'published': row.get('published') or row['date']}) for row in history):
            from news_editorial import member_ids
            for identifier in member_ids(item):
                seen[identifier] = now.date().isoformat()
        else:
            unique.append(item)
    candidates = unique
    state["headline_history"] = history

    if not state.get("initialized"):
        for item in items:
            seen[item["id"]] = now.date().isoformat()
        state["initialized"] = True
        save_state(state)
        return len(items), 0

    if slim_policy.enabled():
        from notification_quality import rank_news
        # Recheck old pending items too: deployment must not leak legacy safety claims.
        categories = {row['key']: row for row in CATEGORIES}
        existing = []
        for row in state.setdefault('pending', []):
            restored = dict(row)
            restored['published'] = datetime.fromisoformat(row['published'])
            if isinstance(restored.get('category'), str):
                restored['category'] = categories[restored['category']]
            existing.append(restored)
        # Revalidate every legacy pending item with the same gate as urgent news.
        # Keep the existing storage until the review route has persisted its queue.
        candidates = route_safety_review(slim_policy.merge_pending(candidates + [row for row in existing if row['id'] not in seen]), state, now)
        ready_ids = {row['id'] for row in candidates}
        refreshed = {row['id']: row for row in candidates}
        state['pending'][:] = [serialize_pending({**row, **refreshed[row['id']]})
                               for row in state['pending'] if row['id'] in ready_ids]
        candidates = rank_news(candidates)
    immediate = [item for item in candidates if (slim_policy.material_news(item) if slim_policy.enabled() else item["category"]["priority"] in {"critical", "high"})]
    normal = [item for item in candidates if item not in immediate]
    sent = 0
    for item in immediate[:MAX_IMMEDIATE_PER_RUN]:
        item = add_translated_title(item, state, now)
        destination, username = destination_for(item, webhook)
        send_discord(destination, news_embed(item, observed_at=now), username)
        from news_editorial import member_ids, history_row
        for identifier in member_ids(item):
            seen[identifier] = now.date().isoformat()
        history.append(history_row(item, now))
        # Successful sends are persisted after weekly history is updated.
        if slim_policy.enabled():
            from market_brief_v2 import remember_news
            remember_news(state, item, now)
        save_state(state)  # Persist before another urgent send can fail.
        sent += 1

    pending = state.setdefault("pending", [])
    pending[:] = [row for row in pending if row["id"] not in seen]
    pending_ids = {item["id"] for item in pending}
    for item in normal + immediate[MAX_IMMEDIATE_PER_RUN:]:
        if item["id"] not in pending_ids:
            stored = add_translated_title(item, state, now)
            stored["published"] = item["published"].isoformat()
            stored["category"] = item["category"]["key"]
            pending.append(stored)
            pending_ids.add(item["id"])

    local = now.astimezone(TAIPEI)
    if slim_policy.enabled():
        pending[:] = slim_policy.merge_pending(pending)
        pending[:] = rank_news([row for row in pending if datetime.fromisoformat(row["published"]) >= now - timedelta(hours=48)])
        digest_slot = f"daily:{local:%Y-%m-%d}"
        if local.hour < 20:
            save_state(state)
            return len(candidates), sent
    else:
        digest_slot = f"{local:%Y-%m-%d}-{local.hour}"
    if pending and state.get("last_digest_slot") != digest_slot:
        restored = []
        categories = {category["key"]: category for category in CATEGORIES}
        digest_limit = 5 if slim_policy.enabled() else MAX_DIGEST_ITEMS
        if slim_policy.enabled():
            progress = state.get('digest_progress') or {}
            if progress.get('slot') != digest_slot:
                progress = {'slot': digest_slot, 'ids': []}
                state['digest_progress'] = progress
            digest_limit = max(0, 5 - len(progress['ids']))
        selected = pending
        if slim_policy.enabled():
            from notification_quality import digest_exclusion_reason
            ready, excluded = [], []
            for row in pending:
                reason = digest_exclusion_reason(row)
                if reason:
                    excluded.append({'id': row['id'], 'reason': reason})
                else:
                    ready.append(row)
            state['digest_quality'] = {'slot': digest_slot, 'excluded': excluded[:100]}
            if excluded:
                print(f'新聞品質篩選：暫緩{len(excluded)}則；原因：' + '、'.join(sorted({row['reason'] for row in excluded})))
            selected = rank_news(ready)
        for item in selected[:digest_limit]:
            item = dict(item)
            item["published"] = datetime.fromisoformat(item["published"])
            item["category"] = categories[item["category"]]
            restored.append(item)
        batch_size = 5 if slim_policy.enabled() else DIGEST_ITEMS_PER_CARD
        digest_messages = 0
        for index in range(0, len(restored), batch_size):
            if slim_policy.enabled():
                groups = slim_policy.digest_groups(restored[index:index + batch_size], now)
                for page, group in enumerate(groups):
                    card = slim_policy.digest_card(group, now)
                    if len(groups) > 1:
                        card['title'] += f'｜{page+1}/{len(groups)}'
                    send_discord(webhook, [card])
                    delivered = {row['id'] for row in group}
                    for row in group:
                        from news_editorial import member_ids, history_row
                        for identifier in member_ids(row):
                            seen[identifier] = now.date().isoformat()
                        history.append(history_row(row, now))
                        from market_brief_v2 import remember_news
                        remember_news(state, row, now)
                        progress['ids'].append(row['id'])
                    pending[:] = [row for row in pending if row['id'] not in delivered]
                    save_state(state)
                    digest_messages += 1
            else:
                send_discord(webhook, digest_embed(restored[index:index + batch_size], now))
                digest_messages += 1
        if not slim_policy.enabled():
            for item in pending[:digest_limit]:
                seen[item["id"]] = now.date().isoformat()
                history.append({"title": item["title"], "date": now.isoformat()})
            pending[:] = pending[digest_limit:]
        if digest_messages or not slim_policy.enabled():
            state["last_digest_slot"] = digest_slot
        sent += digest_messages

    cutoff = (now - timedelta(days=14)).date().isoformat()
    state["seen"] = {key: date for key, date in seen.items() if date >= cutoff}
    translation_cutoff = (now - timedelta(days=30)).date().isoformat()
    state["translation_cache"] = {
        key: value for key, value in state.get("translation_cache", {}).items()
        if value.get("date", "") >= translation_cutoff
    }
    save_state(state)
    return len(items), sent


def serialize_pending(item):
    from notification_quality import published_time
    row = dict(item)
    row['published'] = published_time(row['published']).isoformat()
    if isinstance(row.get('category'), dict):
        row['category'] = row['category']['key']
    return row


def route_safety_review(items, state, now):
    """Shared safety/copy/date gate; preserve legacy inbox and retry semantics."""
    import news_auto_recovery as auto
    if auto.enabled():
        return auto.route(items, state, now)
    from news_editorial import safety_candidate, review_reason, review_card, member_ids, published_time
    queue = state.setdefault('safety_review', [])
    queue[:] = [r for r in queue if published_time(r['published']) >= now - timedelta(days=14)]
    ready = []
    for item in items:
        item = add_translated_title(item, state, now)
        from notification_quality import digest_exclusion_reason
        reason = review_reason(item) or digest_exclusion_reason(item)
        if not reason:
            ready.append(item)
            for old in queue:
                if same_news_event(item, old):
                    old['status'] = 'member_ready'
            continue
        stored = dict(item)
        stored['published'] = published_time(item['published']).isoformat()
        if isinstance(stored.get('category'), dict):
            stored['category'] = stored['category']['key']
        stored.update(review_reason=reason, status='pending_review')
        old = next((r for r in queue if same_news_event(item, r)), None)
        if old:
            merged = slim_policy.merge_pending([old, stored])[0]
            merged['notified_at'] = old.get('notified_at')
            merged.update(review_reason=reason, status='pending_review')
            queue[queue.index(old)] = merged
        else:
            queue.append(stored)
    # Official candidates already prepared for release no longer need an admin ping.
    waiting = [r for r in queue if r.get('status') == 'pending_review' and not r.get('notified_at')]
    waiting.sort(key=lambda r: (safety_candidate(r), published_time(r['published'])), reverse=True)
    if waiting:
        log = os.getenv('DISCORD_LOG_WEBHOOK_URL')
        if log:
            batch = waiting[:4]
            while len(batch) > 1 and len(review_card(batch, now)['description']) > 3500:
                batch.pop()
            try:
                send_discord(log, review_card(batch, now), '新聞核對｜管理員')
            except Exception as exc:
                print(f'警告：新聞核對提示暫未送達（{type(exc).__name__}）；已保留佇列，稍後重試。')
            else:
                for row in batch:
                    row['notified_at'] = now.isoformat()
        else:
            print(f'警告：有{len(waiting)}項新聞候選待核對，管理員Webhook未配置；未改送成員。')
    save_state(state)
    return ready


def sample_item(now: datetime) -> dict[str, Any]:
    return {
        "id": "test-security", "title": "Major exchange confirms security incident affecting withdrawals",
        "title_zh": "大型交易所確認安全事件影響部分提款",
        "summary_zh_points": [
            "該交易所確認正在調查一宗安全事件。",
            "調查期間已暫停部分提款服務。",
            "目前尚未公布完整影響範圍與損失金額。",
        ],
        "summary": "The exchange said it is investigating a security incident and temporarily paused selected withdrawals while it reviews affected systems.",
        "url": "https://example.com/crypto-news-test", "published": now,
        "source": "官方來源示範", "official": True, "category": CATEGORIES[0],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--production-test", action="store_true")
    parser.add_argument("--source-check", action="store_true")
    args = parser.parse_args()
    try:
        now = datetime.now(timezone.utc)
        if args.source_check:
            _, statuses = fetch_all()
            print("新聞來源檢查：" + ", ".join(
                f"{name}={count}" if error is None else f"{name}=-1 ({error})"
                for name, count, error in statuses
            ))
            return 0 if any(count >= 0 for _, count, _ in statuses) else 1
        if args.test:
            webhook = os.environ.get("DISCORD_TEST_WEBHOOK_URL")
            if not webhook:
                raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL；測試禁止發到正式頻道")
            send_discord(webhook, news_embed(sample_item(now), test=True))
            digest_samples = []
            for index, (title, title_zh) in enumerate((
                ("Bitcoin network publishes a scheduled protocol update", "Bitcoin 網路發布例行協議更新"),
                ("Ethereum developers confirm the next client release", "Ethereum 開發團隊確認下一版客戶端更新"),
            )):
                item = sample_item(now)
                item.update({
                    "id": f"test-digest-{index}", "title": title, "title_zh": title_zh,
                    "summary": "Developers published the update schedule and advised operators to review compatibility before deployment.",
                    "summary_zh_points": ["官方已公布更新時程。", "節點營運者應先確認相容性。"],
                    "category": next(category for category in CATEGORIES if category["key"] == "network"),
                })
                digest_samples.append(item)
            digest_cards = digest_embed(digest_samples, now)
            for card in digest_cards:
                card["title"] = "🧪 測試｜" + card["title"]
            send_discord(webhook, digest_cards)
            print("完成：已送出加密新聞即時通知與每小時摘要測試")
            return 0
        if args.production_test:
            webhook = os.environ.get("DISCORD_CRYPTO_NEWS_WEBHOOK_URL")
            if not webhook:
                raise RuntimeError("缺少 DISCORD_CRYPTO_NEWS_WEBHOOK_URL")
            count, statuses = initialize_baseline(now)
            send_discord(webhook, connectivity_embed(count, statuses, now))
            print(f"完成：已建立 {count} 篇基準並送出正式連線測試")
            return 0
        count, sent = run(now)
        print(f"完成：符合條件 {count} 筆，本次送出 {sent} 則")
        return 0
    except Exception as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
