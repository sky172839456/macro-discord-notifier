"""Monitor high-signal operational announcements from major exchanges."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from bybit_notifier import PAGE_RULES, announcement_kind, clean_title, send, text
from crypto_news_notifier import normalize_zh_title, summary_points, translate_title

TAIPEI = ZoneInfo("Asia/Taipei")
STATE = Path(".state/exchange-announcements.json")
PRODUCTION_WEBHOOK_ENV = "DISCORD_EXCHANGE_ANNOUNCEMENT_WEBHOOK_URL"
TEST_WEBHOOK_ENV = "DISCORD_TEST_WEBHOOK_URL"

PAGE_SOURCES = {
    "Binance": "https://www.binance.com/en/support/announcement",
    "OKX": "https://www.okx.com/help/section/announcements-latest-announcements",
    "Bybit": "https://announcements.bybit.com/en/?category=maintenance_updates",
    "Bitget": "https://www.bitget.com/support",
    "KuCoin": "https://www.kucoin.com/announcement/product-updates",
    "BingX": "https://bingx.com/en/support/",
}

STATUS_SOURCES = {
    "Coinbase": "https://status.coinbase.com/history.atom",
    "Kraken": "https://status.kraken.com/history.atom",
}

CATEGORIES = (
    {"key": "security", "icon": "🚨", "label": "安全／重大異常", "priority": "critical",
     "keywords": ("hack", "breach", "exploit", "unauthorized", "security incident", "vulnerability", "stolen")},
    {"key": "outage", "icon": "🔴", "label": "服務中斷／異常", "priority": "critical",
     "keywords": ("outage", "service unavailable", "system issue", "degraded", "incident", "trading interrupted", "emergency maintenance")},
    {"key": "regional", "icon": "🌍", "label": "區域／監管服務變更", "priority": "high",
     "keywords": ("regulatory", "regulation", "restricted region", "cease service", "discontinue service", "verification", "kyc", "fiat channel")},
    {"key": "maintenance", "icon": "🛠️", "label": "維護／充提／鏈上升級", "priority": "normal",
     "keywords": ("maintenance", "network upgrade", "hard fork", "wallet upgrade", "deposit", "withdrawal", "resume", "reopen")},
    {"key": "rules", "icon": "⚙️", "label": "交易規則調整", "priority": "normal",
     "keywords": ("tick size", "risk limit", "margin requirement", "leverage", "minimum order", "price precision", "api update", "api change", "collateral tier")},
    {"key": "reserves", "icon": "🏦", "label": "儲備／財務透明度", "priority": "normal",
     "keywords": ("proof of reserves", "reserve report", "insurance fund", "custody", "audit report")},
    {"key": "product", "icon": "💰", "label": "重大產品更新", "priority": "normal",
     "keywords": ("staking", "institutional product", "new product", "lending service", "earn product")},
)

EXCLUDE = (
    "giveaway", "rewards", "reward pool", "campaign", "competition", "lucky draw", "airdrop event",
    "refer a friend", "deposit to earn", "trade to win", "apr boost", "quiz", "ama ",
)

ZH_FALLBACK = {
    "security": "公告涉及安全事件；請優先查看交易所官方處置、資產影響與服務限制。",
    "outage": "交易所回報服務異常或中斷；請留意交易、登入及充提是否受到影響。",
    "regional": "公告涉及特定地區、法規或驗證規則變更；適用範圍以官方原文為準。",
    "maintenance": "公告涉及系統維護、充提調整或區塊鏈升級；請確認開始與恢復時間。",
    "rules": "公告涉及交易規則、槓桿、保證金或 API 調整；既有策略可能需要更新。",
    "reserves": "公告涉及儲備、託管或保險基金資訊；請以正式報告內容為準。",
    "product": "公告涉及交易所重要產品變更；請確認資格、風險與適用地區。",
}

OBSERVATION = {
    "security": "可能引發資金轉移與短期避險情緒，仍需等待官方完整調查。",
    "outage": "服務中斷期間避免重複操作，恢復時間以官方狀態更新為準。",
    "regional": "可能影響當地帳戶功能、法幣通道或產品使用資格。",
    "maintenance": "維護期間充提或部分功能可能暫停，交易是否受影響需逐項確認。",
    "rules": "自動交易、槓桿部位與下單參數可能需要重新檢查。",
    "reserves": "單一報告不等同完整風險保證，仍需持續觀察負債與流動性。",
    "product": "新產品不代表適合所有使用者，應先確認成本、鎖定期與風險。",
}


def operational_kind(value: str) -> dict[str, Any] | None:
    lower = f" {value.lower()} "
    if announcement_kind(value) or any(keyword in lower for keyword in EXCLUDE):
        return None
    for category in CATEGORIES:
        if any(keyword in lower for keyword in category["keywords"]):
            return category
    return None


def page_items(exchange: str, url: str) -> list[dict[str, Any]]:
    if exchange == "Binance":
        return binance_items()
    body = text(url)
    path_pattern, base = PAGE_RULES[exchange]
    pattern = rf'href=["\']([^"\']*{path_pattern}[^"\']*)["\'][^>]*>(.*?)</a>'
    items = []
    for path, raw_title in re.findall(pattern, body, re.S | re.I):
        title = clean_title(raw_title)
        category = operational_kind(title)
        if not title or not category:
            continue
        link = urljoin(base, path)
        items.append({
            "id": hashlib.sha256((exchange + link).encode()).hexdigest()[:24],
            "exchange": exchange, "title": title, "summary": title, "url": link,
            "category": category, "published": datetime.now(timezone.utc),
        })
    return list({item["id"]: item for item in items}.values())[:40]


def binance_items() -> list[dict[str, Any]]:
    """Read Binance's official public CMS JSON because its HTML list is JS-only."""
    items = []
    # 49 is the latest general announcements catalog; 51 is API maintenance.
    for catalog_id in (49, 51):
        endpoint = (
            "https://www.binance.com/bapi/composite/v1/public/cms/article/"
            f"catalog/list/query?catalogId={catalog_id}&pageNo=1&pageSize=50"
        )
        payload = json.loads(text(endpoint))
        for article in payload.get("data", {}).get("articles", []):
            title = clean_title(str(article.get("title", "")))
            category = operational_kind(title)
            code = str(article.get("code", ""))
            if not title or not code or not category:
                continue
            link = f"https://www.binance.com/en/support/announcement/{code}"
            items.append({
                "id": hashlib.sha256(("Binance" + link).encode()).hexdigest()[:24],
                "exchange": "Binance", "title": title, "summary": title, "url": link,
                "category": category, "published": datetime.now(timezone.utc),
            })
    return list({item["id"]: item for item in items}.values())


def atom_text(entry: ElementTree.Element, name: str) -> str:
    node = entry.find(f"{{http://www.w3.org/2005/Atom}}{name}")
    return re.sub(r"\s+", " ", html.unescape("".join(node.itertext()) if node is not None else "")).strip()


def status_items(exchange: str, url: str) -> list[dict[str, Any]]:
    request = Request(url, headers={"User-Agent": "exchange-announcement-monitor/1.0"})
    with urlopen(request, timeout=30) as response:
        root = ElementTree.fromstring(response.read())
    items = []
    for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:30]:
        title = atom_text(entry, "title")
        summary = atom_text(entry, "content") or atom_text(entry, "summary")
        category = operational_kind(f"{title} {summary}")
        if not category:
            continue
        link_node = entry.find("{http://www.w3.org/2005/Atom}link")
        link = link_node.get("href", url) if link_node is not None else url
        published_text = atom_text(entry, "updated") or atom_text(entry, "published")
        try:
            published = datetime.fromisoformat(published_text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            try:
                published = parsedate_to_datetime(published_text).astimezone(timezone.utc)
            except (TypeError, ValueError):
                published = datetime.now(timezone.utc)
        items.append({
            "id": hashlib.sha256((exchange + link + title).encode()).hexdigest()[:24],
            "exchange": exchange, "title": title, "summary": summary, "url": link,
            "category": category, "published": published,
        })
    return items


def enrich(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    try:
        result["title_zh"] = translate_title(item["title"])
    except Exception:
        result["title_zh"] = item["title"]
    try:
        points = summary_points(item["summary"])
    except Exception:
        points = []
    fallback = ZH_FALLBACK[item["category"]["key"]]
    if len(points) < 2 and fallback not in points:
        points.append(fallback)
    result["points"] = points[:3]
    return result


def embed(item: dict[str, Any], test: bool = False) -> dict[str, Any]:
    category = item["category"]
    title_zh = item.get("title_zh", item["title"])
    headline = f"### {title_zh}"
    if title_zh != item["title"]:
        headline += f"\n*英文原標題：{item['title']}*"
    points = item.get("points") or [ZH_FALLBACK[category["key"]]]
    point_text = "\n".join(f"• {point}" for point in points)
    local = item["published"].astimezone(TAIPEI)
    return {
        "author": {"name": "EXCHANGE NOTICE RADAR｜交易所公告"},
        "title": f"{'🧪 測試｜' if test else ''}{category['icon']} {item['exchange']}｜{category['label']}",
        "description": f"{headline}\n\n**繁體中文重點**\n{point_text}\n\n**市場觀察**\n{OBSERVATION[category['key']]}",
        "color": 0xE74C3C if category["priority"] == "critical" else 0xF39C12 if category["priority"] == "high" else 0x3498DB,
        "fields": [
            {"name": "交易所", "value": item["exchange"], "inline": True},
            {"name": "公告時間", "value": local.strftime("%m/%d %H:%M（台灣）"), "inline": True},
            {"name": "官方原始資料", "value": item["url"], "inline": False},
        ],
        "footer": {"text": "交易所官方資料｜已排除上幣與行銷活動｜不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def digest_embed(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    lines = [f"{item['category']['icon']} **{item['exchange']}｜{item.get('title_zh', item['title'])}**\n└ [官方原文]({item['url']})"
             for item in items[:8]]
    return {
        "author": {"name": "EXCHANGE NOTICE RADAR｜交易所公告"},
        "title": "📢 交易所公告三小時摘要",
        "description": "\n\n".join(lines), "color": 0x3498DB,
        "footer": {"text": "維護、規則與服務變更彙整｜已排除上幣與行銷活動"},
        "timestamp": now.isoformat(),
    }


def fetch_all() -> tuple[list[dict[str, Any]], list[tuple[str, int, str | None]]]:
    items, statuses = [], []
    for exchange, url in PAGE_SOURCES.items():
        try:
            parsed = page_items(exchange, url)
            items.extend(parsed)
            statuses.append((exchange, len(parsed), None))
        except Exception as exc:
            statuses.append((exchange, -1, f"{type(exc).__name__} / {exc}"))
    for exchange, url in STATUS_SOURCES.items():
        try:
            parsed = status_items(exchange, url)
            items.extend(parsed)
            statuses.append((exchange, len(parsed), None))
        except Exception as exc:
            statuses.append((exchange, -1, f"{type(exc).__name__} / {exc}"))
    return items, statuses


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"initialized": False, "seen": {}, "pending": [], "last_digest": ""}


def save_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def initialize(now: datetime) -> tuple[int, list[tuple[str, int, str | None]]]:
    items, statuses = fetch_all()
    state = load_state()
    for item in items:
        state.setdefault("seen", {})[item["id"]] = now.date().isoformat()
    state["initialized"] = True
    save_state(state)
    return len(items), statuses


def connectivity_embed(count: int, statuses: list[tuple[str, int, str | None]], now: datetime) -> dict[str, Any]:
    lines = [f"{'❌' if error else '⚠️' if count == 0 else '✅'} **{name}**｜{count if error is None else error}"
             for name, count, error in statuses]
    healthy = all(error is None and count > 0 for _, count, error in statuses)
    return {
        "title": f"{'✅' if healthy else '⚠️'} 交易所公告雷達來源檢查",
        "description": f"已建立 **{count} 筆**公告基準，不會把舊公告洗進頻道。\n\n" + "\n".join(lines),
        "color": 0x2ECC71 if healthy else 0xF1C40F,
        "footer": {"text": "正式連線測試｜零筆表示可連線，但目前未解析到符合條件的公告"},
        "timestamp": now.isoformat(),
    }


def run(now: datetime) -> tuple[int, int]:
    webhook = os.environ.get(PRODUCTION_WEBHOOK_ENV)
    if not webhook:
        raise RuntimeError(f"缺少 {PRODUCTION_WEBHOOK_ENV}")
    state = load_state()
    items, statuses = fetch_all()
    if not any(count > 0 for _, count, _ in statuses):
        raise RuntimeError("所有交易所公告來源皆無法讀取")
    seen = state.setdefault("seen", {})
    if not state.get("initialized"):
        for item in items:
            seen[item["id"]] = now.date().isoformat()
        state["initialized"] = True
        save_state(state)
        return len(items), 0

    candidates = [item for item in items if item["id"] not in seen]
    immediate = [item for item in candidates if item["category"]["priority"] in {"critical", "high"}]
    normal = [item for item in candidates if item["category"]["priority"] == "normal"]
    sent_count = 0
    for item in immediate[:4]:
        item = enrich(item)
        send(webhook, embed(item))
        seen[item["id"]] = now.date().isoformat()
        sent_count += 1

    pending = state.setdefault("pending", [])
    pending_ids = {item["id"] for item in pending}
    for item in normal + immediate[4:]:
        if item["id"] not in pending_ids:
            item = enrich(item)
            stored = dict(item)
            stored["published"] = item["published"].isoformat()
            stored["category"] = item["category"]["key"]
            pending.append(stored)
            pending_ids.add(item["id"])

    local = now.astimezone(TAIPEI)
    slot = f"{local:%Y-%m-%d}-{local.hour // 3}"
    if pending and local.hour % 3 == 0 and state.get("last_digest") != slot:
        category_map = {category["key"]: category for category in CATEGORIES}
        restored = []
        for item in pending[:8]:
            item = dict(item)
            item["published"] = datetime.fromisoformat(item["published"])
            item["category"] = category_map[item["category"]]
            restored.append(item)
        send(webhook, digest_embed(restored, now))
        for item in pending[:8]:
            seen[item["id"]] = now.date().isoformat()
        pending[:] = pending[8:]
        state["last_digest"] = slot
        sent_count += 1

    cutoff = (now - timedelta(days=21)).date().isoformat()
    state["seen"] = {key: date for key, date in seen.items() if date >= cutoff}
    save_state(state)
    return len(items), sent_count


def sample(now: datetime) -> dict[str, Any]:
    return {
        "id": "test", "exchange": "Bybit", "title": "Bybit to support network upgrade and suspend withdrawals",
        "title_zh": "Bybit 將支援網路升級並暫停提款", "summary": "Scheduled maintenance notice.",
        "points": ["Bybit 將支援區塊鏈網路升級。", "升級期間相關資產提款將暫停。", "恢復時間以官方公告為準。"],
        "url": PAGE_SOURCES["Bybit"], "published": now, "category": operational_kind("network upgrade withdrawal"),
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
            print("交易所公告來源：" + ", ".join(f"{name}={count}" if error is None else f"{name}=-1 ({error})"
                                              for name, count, error in statuses))
            return 0 if any(count > 0 for _, count, _ in statuses) else 1
        if args.test:
            webhook = os.environ.get(TEST_WEBHOOK_ENV)
            if not webhook:
                raise RuntimeError(f"缺少 {TEST_WEBHOOK_ENV}")
            send(webhook, embed(sample(now), test=True))
            return 0
        if args.production_test:
            webhook = os.environ.get(PRODUCTION_WEBHOOK_ENV)
            if not webhook:
                raise RuntimeError(f"缺少 {PRODUCTION_WEBHOOK_ENV}")
            count, statuses = initialize(now)
            send(webhook, connectivity_embed(count, statuses, now))
            return 0
        count, sent_count = run(now)
        print(f"完成：公告 {count} 筆，本次送出 {sent_count} 則")
        return 0
    except Exception as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
