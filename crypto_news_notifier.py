"""High-signal crypto news radar for Discord (standard library only)."""

from __future__ import annotations

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

TAIPEI = ZoneInfo("Asia/Taipei")
STATE_FILE = Path(os.getenv("CRYPTO_NEWS_STATE_FILE", ".state/crypto-news.json"))
MAX_IMMEDIATE_PER_RUN = 4
MAX_DIGEST_ITEMS = 8
RECENT_HOURS = 8
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
            with urlopen(Request(url, headers=HTTP_HEADERS), timeout=25) as response:
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
    value = re.sub(r"([\u3400-\u9fff])([A-Za-z0-9])", r"\1 \2", value)
    value = re.sub(r"([A-Za-z0-9])([\u3400-\u9fff])", r"\1 \2", value)
    return re.sub(r"\s+", " ", value).strip()


def translate_title(title: str) -> str:
    """Translate one public English headline to Traditional Chinese without an API key."""
    query = urlencode({"q": title[:450], "langpair": "en|zh-TW", "mt": "1"})
    payload = json.loads(http_text(f"{TRANSLATION_URL}?{query}", attempts=2))
    translated = clean_text(str(payload.get("responseData", {}).get("translatedText", "")))
    if not translated or translated.lower() == title.lower():
        raise ValueError("translation result unavailable")
    return normalize_zh_title(translated)


def add_translated_title(item: dict[str, Any], state: dict[str, Any], now: datetime) -> dict[str, Any]:
    cache = state.setdefault("translation_cache", {})
    key = hashlib.sha256(item["title"].encode()).hexdigest()[:20]
    cached = cache.get(key)
    enriched = dict(item)
    if cached and cached.get("source") == item["title"]:
        enriched["title_zh"] = cached["translated"]
        return enriched
    try:
        translated = translate_title(item["title"])
        enriched["title_zh"] = translated
        cache[key] = {"source": item["title"], "translated": translated, "date": now.date().isoformat()}
    except Exception:
        enriched["title_zh"] = item["title"]
    return enriched


def category_for(text: str) -> dict[str, Any] | None:
    lowered = f" {text.lower()} "
    for category in CATEGORIES:
        if any(keyword in lowered for keyword in category["keywords"]):
            return category
    return None


def is_relevant(text: str, official: bool = False) -> bool:
    lowered = text.lower()
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
        if not title or not link or not published or not category or not is_relevant(combined, source_config["official"]):
            continue
        url = canonical_url(link)
        identifier = hashlib.sha256(f"{source_config['name']}|{url}|{title}".encode()).hexdigest()[:24]
        items.append({
            "id": identifier, "title": title, "summary": summary[:700], "url": url,
            "published": published, "source": source_config["name"],
            "official": source_config["official"], "category": category,
        })
    return items


def title_tokens(title: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "that", "this", "into", "after", "amid", "over", "says"}
    return {word for word in re.findall(r"[a-z0-9]{3,}", title.lower()) if word not in stop}


def similar_title(left: str, right: str) -> bool:
    a, b = title_tokens(left), title_tokens(right)
    return bool(a and b) and len(a & b) / len(a | b) >= 0.55


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: (row["published"], row["official"]), reverse=True):
        duplicate = next((row for row in kept if similar_title(item["title"], row["title"])), None)
        if duplicate:
            if item["official"] and not duplicate["official"]:
                kept.remove(duplicate)
                kept.append(item)
            continue
        kept.append(item)
    return kept


def news_embed(item: dict[str, Any], test: bool = False) -> dict[str, Any]:
    category = item["category"]
    priority = "重大" if category["priority"] == "critical" else "重要"
    status = "✅ 官方確認" if item["official"] else "📰 媒體報導"
    prefix = "🧪 測試｜" if test else ""
    local = item["published"].astimezone(TAIPEI)
    excerpt = item["summary"][:360].rstrip()
    if len(item["summary"]) > 360:
        excerpt += "…"
    translated = item.get("title_zh", item["title"])
    headline = f"### {translated}"
    if translated != item["title"]:
        headline += f"\n*英文原標題：{item['title']}*"
    return {
        "author": {"name": "CRYPTO NEWS RADAR｜加密新聞"},
        "title": f"{prefix}{category['icon']} {priority}｜{category['label']}",
        "description": f"{headline}\n\n**繁體中文重點**\n• {ZH_SUMMARY[category['key']]}\n\n**可能影響**\n{IMPACT[category['key']]}",
        "color": 0xE74C3C if category["priority"] == "critical" else 0xF39C12,
        "fields": [
            {"name": "可信狀態", "value": status, "inline": True},
            {"name": "來源", "value": item["source"], "inline": True},
            {"name": "發布時間", "value": local.strftime("%m/%d %H:%M（台灣）"), "inline": True},
            {"name": "英文原文摘要", "value": excerpt or "來源未提供摘要，請開啟原文確認。", "inline": False},
            {"name": "🔗 原文連結", "value": item["url"], "inline": False},
        ],
        "footer": {"text": "原標題與原文連結保留｜繁中重點為分類式摘要｜不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def digest_embed(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    lines = []
    for item in items[:MAX_DIGEST_ITEMS]:
        category = item["category"]
        translated = item.get("title_zh", item["title"])
        original = f"\n└ 原標題：{item['title']}" if translated != item["title"] else ""
        lines.append(f"{category['icon']} **{translated}**{original}\n└ {item['source']}｜[原文]({item['url']})")
    return {
        "author": {"name": "CRYPTO NEWS RADAR｜加密新聞"},
        "title": "📰 加密新聞三小時摘要",
        "description": "\n\n".join(lines) or "本時段沒有符合條件的重要新聞。",
        "color": 0x3498DB,
        "footer": {"text": "已排除價格預測、業配與重複報導｜僅供資訊參考"},
        "timestamp": now.isoformat(),
    }


def send_discord(webhook: str, embed: dict[str, Any]) -> None:
    payload = json.dumps({"username": "加密新聞雷達", "embeds": [embed]}).encode("utf-8")
    url = webhook + ("&" if "?" in webhook else "?") + "wait=true"
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "macro-discord-notifier/2.0"},
        method="POST",
    )
    with urlopen(request, timeout=25):
        pass


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
    webhook = os.environ.get("DISCORD_CRYPTO_NEWS_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("缺少 DISCORD_CRYPTO_NEWS_WEBHOOK_URL")
    state = load_state()
    items, statuses = fetch_all()
    if not any(count >= 0 for _, count, _ in statuses):
        raise RuntimeError("所有加密新聞來源皆無法讀取")
    seen = state.setdefault("seen", {})
    recent_cutoff = now - timedelta(hours=RECENT_HOURS)
    candidates = [item for item in items if item["published"] >= recent_cutoff and item["id"] not in seen]

    if not state.get("initialized"):
        for item in items:
            seen[item["id"]] = now.date().isoformat()
        state["initialized"] = True
        save_state(state)
        return len(items), 0

    immediate = [item for item in candidates if item["category"]["priority"] in {"critical", "high"}]
    normal = [item for item in candidates if item["category"]["priority"] == "normal"]
    sent = 0
    for item in immediate[:MAX_IMMEDIATE_PER_RUN]:
        item = add_translated_title(item, state, now)
        send_discord(webhook, news_embed(item))
        seen[item["id"]] = now.date().isoformat()
        sent += 1

    pending = state.setdefault("pending", [])
    pending_ids = {item["id"] for item in pending}
    for item in normal + immediate[MAX_IMMEDIATE_PER_RUN:]:
        if item["id"] not in pending_ids:
            stored = add_translated_title(item, state, now)
            stored["published"] = item["published"].isoformat()
            stored["category"] = item["category"]["key"]
            pending.append(stored)
            pending_ids.add(item["id"])

    local = now.astimezone(TAIPEI)
    digest_slot = f"{local:%Y-%m-%d}-{local.hour // 3}"
    if pending and state.get("last_digest_slot") != digest_slot and local.hour % 3 == 0:
        restored = []
        categories = {category["key"]: category for category in CATEGORIES}
        for item in pending[:MAX_DIGEST_ITEMS]:
            item = dict(item)
            item["published"] = datetime.fromisoformat(item["published"])
            item["category"] = categories[item["category"]]
            restored.append(item)
        send_discord(webhook, digest_embed(restored, now))
        for item in pending[:MAX_DIGEST_ITEMS]:
            seen[item["id"]] = now.date().isoformat()
        pending[:] = pending[MAX_DIGEST_ITEMS:]
        state["last_digest_slot"] = digest_slot
        sent += 1

    cutoff = (now - timedelta(days=14)).date().isoformat()
    state["seen"] = {key: date for key, date in seen.items() if date >= cutoff}
    translation_cutoff = (now - timedelta(days=30)).date().isoformat()
    state["translation_cache"] = {
        key: value for key, value in state.get("translation_cache", {}).items()
        if value.get("date", "") >= translation_cutoff
    }
    save_state(state)
    return len(items), sent


def sample_item(now: datetime) -> dict[str, Any]:
    return {
        "id": "test-security", "title": "Major exchange confirms security incident affecting withdrawals",
        "title_zh": "大型交易所確認安全事件影響部分提款",
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
            print("完成：已送出加密新聞測試通知")
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
