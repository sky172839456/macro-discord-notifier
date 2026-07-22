"""Monitor official exchange listing announcements and notify Discord."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

STATE = Path(".state/exchange-listings.json")
PRODUCTION_WEBHOOK_ENV = "DISCORD_EXCHANGE_LISTING_WEBHOOK_URL"
TEST_WEBHOOK_ENV = "DISCORD_TEST_WEBHOOK_URL"
STATE_VERSION = 2
TAIPEI = ZoneInfo("Asia/Taipei")
SOURCES = {
    "Bybit": "https://announcements.bybit.com/en/?category=new_crypto",
    "OKX": "https://www.okx.com/help/section/announcements-new-listings",
    "Binance": "https://www.binance.com/en/support/announcement/list/48",
    "Bitget": "https://www.bitget.com/support/sections/5955813039257",
    "KuCoin": "https://www.kucoin.com/announcement/new-listings",
    "Kraken": "https://blog.kraken.com/category/product/asset-listings",
    "BingX": "https://bingx.com/en/support/",
}

PAGE_RULES = {
    "Bybit": (r"/en/article/", "https://announcements.bybit.com"),
    "OKX": (r"/help/", "https://www.okx.com"),
    "Binance": (r"/en/support/announcement/detail/", "https://www.binance.com"),
    "Bitget": (r"/support/articles/", "https://www.bitget.com"),
    "KuCoin": (r"/announcement/", "https://www.kucoin.com"),
    "Kraken": (r"/product/asset-listings/", "https://blog.kraken.com"),
    "BingX": (r"/en/support/articles/", "https://bingx.com"),
}


def text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def clean_title(value: str) -> str:
    """Remove markup and Bybit's leaked card suffix such as `lg ... Jul 15`."""
    clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip()
    clean = re.sub(r"\s*lg\s*\.{3}.*$", "", clean, flags=re.I)
    return clean.strip()


def page_items(name: str, url: str) -> list[dict[str, Any]]:
    body = text(url)
    path_pattern, base = PAGE_RULES[name]
    pattern = rf'href=["\']([^"\']*{path_pattern}[^"\']*)["\'][^>]*>(.*?)</a>'
    items = []
    for path, raw_title in re.findall(pattern, body, re.S | re.I):
        title = clean_title(raw_title)
        if title.lower() in {"new listings", "delistings", "delisting", "spot", "futures"}:
            continue
        if title and announcement_kind(title):
            link = urljoin(base, path)
            if name == "OKX" and "/help/section/" in link:
                continue
            if name == "KuCoin" and re.search(
                r"/announcement/(?:new-listings|delistings|product-updates)/?$", link, re.I
            ):
                continue
            if name == "Bitget":
                article = re.search(r"/support/articles/(\d+)", link)
                if article:
                    link = f"https://www.bitget.com/zh-TC/support/articles/{article.group(1)}"
            items.append({
                "id": hashlib.sha256((name + link).encode()).hexdigest()[:24],
                "exchange": name,
                "title": title,
                "url": link,
                "source_type": "announcement",
            })
    return list({item["id"]: item for item in items}.values())[:30]


def api_spot_items(name: str) -> list[dict[str, Any]]:
    """Use official public market metadata when an announcement page is JS-only."""
    if name == "Binance":
        payload = json.loads(text("https://api.binance.com/api/v3/exchangeInfo"))
        markets = [
            (item["baseAsset"], item["quoteAsset"], item["symbol"])
            for item in payload.get("symbols", [])
            if item.get("status") == "TRADING" and item.get("isSpotTradingAllowed")
        ]
        source = SOURCES[name]
    elif name == "BingX":
        payload = json.loads(text("https://open-api.bingx.com/openApi/spot/v1/common/symbols"))
        markets = []
        for item in payload.get("data", {}).get("symbols", []):
            if not (item.get("apiStateBuy") and item.get("apiStateSell")):
                continue
            display = str(item.get("displayName") or item.get("symbol", "")).replace("_", "-")
            parts = re.split(r"[-/]", display, maxsplit=1)
            if len(parts) == 2:
                markets.append((parts[0], parts[1], str(item.get("symbol", display))))
        source = SOURCES[name]
    else:
        raise ValueError(f"沒有 {name} API 設定")

    grouped: dict[str, set[str]] = {}
    for base, quote, _ in markets:
        grouped.setdefault(base, set()).add(quote)
    return [{
        "id": hashlib.sha256((name + base).encode()).hexdigest()[:24],
        "exchange": name,
        "title": f"{name} spot market available: {base}/{'、'.join(sorted(quotes)[:5])}",
        "url": source,
        "source_type": "market",
    } for base, quotes in grouped.items()]


def binance_announcement_items() -> list[dict[str, Any]]:
    endpoint = (
        "https://www.binance.com/bapi/composite/v1/public/cms/article/"
        "catalog/list/query?catalogId=48&pageNo=1&pageSize=50"
    )
    payload = json.loads(text(endpoint))
    items = []
    for article in payload.get("data", {}).get("articles", []):
        title = clean_title(str(article.get("title", "")))
        code = str(article.get("code", ""))
        if not title or not code or not announcement_kind(title):
            continue
        link = f"https://www.binance.com/en/support/announcement/{code}"
        items.append({
            "id": hashlib.sha256(("Binance" + link).encode()).hexdigest()[:24],
            "exchange": "Binance", "title": title, "url": link,
            "source_type": "announcement",
        })
    return items


def bingx_announcement_items() -> list[dict[str, Any]]:
    endpoint = (
        "https://open-api.bingx.com/openApi/content/v1/announcement"
        "?contentType=NewCryptocurrency&language=en-us&page=1"
    )
    request = Request(endpoint, headers={
        "User-Agent": "exchange-listing-monitor/4.0",
        "X-SOURCE-KEY": "BX-AI-SKILL",
    })
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    if payload.get("code") != 0:
        raise RuntimeError(f"BingX API: {payload.get('msg') or payload.get('code')}")
    data = payload.get("data", [])
    articles = data.get("list", []) if isinstance(data, dict) else data
    items = []
    for article in articles:
        title = clean_title(str(article.get("title", "")))
        link = str(article.get("link") or article.get("url") or "")
        if not title or not link or not announcement_kind(title):
            continue
        published = None
        raw_time = str(article.get("time") or article.get("releaseTime") or "")
        try:
            published = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
        items.append({
            "id": hashlib.sha256(("BingX" + link).encode()).hexdigest()[:24],
            "exchange": "BingX", "title": title, "url": link,
            "source_type": "announcement", "published": published,
        })
    return items


def announcement_kind(title: str) -> str | None:
    """Classify only listing-related notices and keep the labels consistent."""
    lower = title.lower()
    if any(word in lower for word in ("delist", "remove trading", "cease trading", "suspend trading permanently")):
        return "delist"
    if any(word in lower for word in ("migration", "token swap", "rebrand", "rename", "brand upgrade")):
        return "migration"
    if any(word in lower for word in ("pre-market", "pre market", "premarket", "pre-ipo", "pre ipo")):
        return "premarket"
    if any(word in lower for word in ("perpetual", "futures", "future contract")):
        return "perpetual"
    if any(word in lower for word in (
        "spot trading", "spot market", "new listing", "initial listing", "will list", "to list",
        "listed on", "available for trading", "market available", "adds trading pair", "add trading pair",
        "gets listed", "get listed",
    )):
        return "spot"
    return None


def coinbase_items() -> list[dict[str, str]]:
    products = json.loads(text("https://api.exchange.coinbase.com/products"))
    items = []
    for product in products:
        if product.get("status") == "online":
            product_id = product["id"]
            items.append({
                "id": hashlib.sha256(("Coinbase" + product_id).encode()).hexdigest()[:24],
                "exchange": "Coinbase",
                "title": f"Coinbase market available: {product_id}",
                "url": f"https://exchange.coinbase.com/trade/{product_id}",
                "source_type": "market",
            })
    return items


def format_time(value: datetime | None) -> str:
    return value.astimezone(TAIPEI).strftime("%m/%d %H:%M") if value else "官方頁面未提供"


def embed(item: dict[str, Any], test: bool = False) -> dict[str, Any]:
    kind_key = announcement_kind(item["title"]) or "spot"
    kind, icon, color = {
        "spot": ("現貨上幣", "🟢", 0x2ECC71),
        "perpetual": ("永續合約", "🔵", 0x3498DB),
        "premarket": ("預上市／盤前交易", "🟡", 0xF1C40F),
        "delist": ("下架", "🔴", 0xE74C3C),
        "migration": ("代幣遷移／更名", "🔄", 0x9B59B6),
    }[kind_key]
    return {
        "title": f"{'🧪 測試｜' if test else ''}{icon} {item['exchange']} {kind}",
        "description": (
            f"### {item['title']}\n\n**繁體中文摘要**\n"
            f"{item['exchange']} 發布{kind}資訊，請開啟官方原文確認交易時間、交易對與適用地區。"
        ),
        "color": color,
        "fields": [
            {"name": "交易所", "value": item["exchange"], "inline": True},
            {"name": "官方公告時間（台灣）", "value": format_time(item.get("published")), "inline": True},
            {"name": "機器人發現時間（台灣）", "value": format_time(item.get("discovered") or datetime.now(timezone.utc)), "inline": True},
            {"name": "官方原始資料", "value": item["url"], "inline": False},
        ],
        "footer": {"text": "交易所官方資料｜請以原文為準｜不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def send(webhook: str, message: dict[str, Any], dry_run: bool = False) -> None:
    payload = {"username": "交易所上幣通知", "embeds": [message], "allowed_mentions": {"parse": []}}
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        webhook + ("&" if "?" in webhook else "?") + "wait=true",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "exchange-monitor/3.0"},
        method="POST",
    )
    with urlopen(request, timeout=30):
        pass


def fetch_exchange(name: str) -> tuple[list[dict[str, Any]], str]:
    if name == "Binance":
        try:
            items = binance_announcement_items()
            if items:
                return items, "announcement"
        except Exception as exc:
            print(f"Binance 公告來源失敗，改用市場 API：{exc}", file=sys.stderr)
        return api_spot_items("Binance"), "market"
    if name == "BingX":
        try:
            items = bingx_announcement_items()
            if items:
                return items, "announcement"
        except Exception as exc:
            print(f"BingX 公告來源失敗，改用市場 API：{exc}", file=sys.stderr)
        return api_spot_items("BingX"), "market"
    if name == "Coinbase":
        return coinbase_items(), "market"
    return page_items(name, SOURCES[name]), "announcement"


def source_check() -> list[tuple[str, int, str]]:
    results = []
    for name in (*SOURCES, "Coinbase"):
        items, source_type = fetch_exchange(name)
        if not items:
            raise RuntimeError(f"{name} 來源取得 0 筆資料")
        results.append((name, len(items), source_type))
    return results


def run(test: bool = False, production_test: bool = False, dry_run: bool = False) -> None:
    webhook_env = TEST_WEBHOOK_ENV if test and not production_test else PRODUCTION_WEBHOOK_ENV
    webhook = os.environ.get(webhook_env)
    if not webhook and not dry_run:
        raise RuntimeError(f"缺少 {webhook_env}")

    if test or production_test:
        sample = {"exchange": "Binance", "title": "Binance Will List ABC (ABC) for Spot Trading", "url": SOURCES["Binance"]}
        message = embed(sample, test=True)
        if production_test:
            message["title"] = message["title"].replace("🧪 測試｜", "🧪 正式頻道連線測試｜")
            message["description"] += "\n\n> 這是連線測試，不是最新上幣公告。"
        send(webhook or "https://discord.invalid/webhook", message, dry_run)
        return

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    fresh: dict[str, list[str]] = {}
    migrating = state.get("_version") != STATE_VERSION
    for name in (*SOURCES, "Coinbase"):
        try:
            items, source_type = fetch_exchange(name)
            if not items:
                raise RuntimeError("官方來源回傳 0 筆，保留既有基準並等待下次重試")
        except Exception as exc:
            print(f"警告：{name} 讀取失敗：{exc}", file=sys.stderr)
            continue
        state_key = f"{name}:{source_type}"
        old = set(state.get(state_key, []))
        fresh[state_key] = [item["id"] for item in items]
        if old and not migrating:
            for item in reversed(items):
                if item["id"] not in old:
                    item["discovered"] = datetime.now(timezone.utc)
                    send(webhook or "https://discord.invalid/webhook", embed(item), dry_run)

    if not dry_run:
        state.update(fresh)
        state["_version"] = STATE_VERSION
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--test", action="store_true", help="Send one clearly labelled template to the test webhook")
    target.add_argument("--production-test", action="store_true", help="Send a clearly labelled connectivity test to production")
    target.add_argument("--source-check", action="store_true", help="Check every official source without sending Discord messages")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without contacting Discord or changing state")
    args = parser.parse_args()
    try:
        if args.source_check:
            results = source_check()
            print("上幣通知來源：" + ", ".join(
                f"{name}={count} ({'公告' if source_type == 'announcement' else '市場備援'})"
                for name, count, source_type in results
            ))
        else:
            run(test=args.test, production_test=args.production_test, dry_run=args.dry_run)
        return 0
    except Exception as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
