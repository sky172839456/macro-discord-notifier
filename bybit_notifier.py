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
from urllib.request import Request, urlopen

STATE = Path(".state/exchange-listings.json")
PRODUCTION_WEBHOOK_ENV = "DISCORD_EXCHANGE_LISTING_WEBHOOK_URL"
TEST_WEBHOOK_ENV = "DISCORD_TEST_WEBHOOK_URL"
SOURCES = {
    "Bybit": "https://announcements.bybit.com/en/?category=new_crypto",
    "OKX": "https://www.okx.com/help/section/announcements-new-listings",
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


def page_items(name: str, url: str) -> list[dict[str, str]]:
    body = text(url)
    patterns = {
        "Bybit": r'href=["\'](/en/article/[^"\']+)["\'][^>]*>(.*?)</a>',
        "OKX": r'href=["\'](/help/[^"\']+)["\'][^>]*>(.*?)</a>',
    }
    items = []
    for path, raw_title in re.findall(patterns[name], body, re.S | re.I):
        title = clean_title(raw_title)
        lower = title.lower()
        if title and any(word in lower for word in ("list", "perpetual", "delist", "migration", "upgrade")):
            base = "https://announcements.bybit.com" if name == "Bybit" else "https://www.okx.com"
            link = base + path
            items.append({
                "id": hashlib.sha256((name + link).encode()).hexdigest()[:24],
                "exchange": name,
                "title": title,
                "url": link,
            })
    return list({item["id"]: item for item in items}.values())[:30]


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
            })
    return items


def embed(item: dict[str, str], test: bool = False) -> dict[str, Any]:
    lower = item["title"].lower()
    kind = "下架／調整" if "delist" in lower else "永續合約" if "perpetual" in lower else "新市場／上架"
    return {
        "title": f"{'🧪 測試｜' if test else ''}🟢 {item['exchange']} {kind}",
        "description": (
            f"### {item['title']}\n\n**繁體中文摘要**\n"
            f"{item['exchange']} 發布{kind}資訊，請開啟官方原文確認交易時間、交易對與適用地區。"
        ),
        "color": 0x2ECC71,
        "fields": [
            {"name": "交易所", "value": item["exchange"], "inline": True},
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


def run(test: bool = False, dry_run: bool = False) -> None:
    webhook_env = TEST_WEBHOOK_ENV if test else PRODUCTION_WEBHOOK_ENV
    webhook = os.environ.get(webhook_env)
    if not webhook and not dry_run:
        raise RuntimeError(f"缺少 {webhook_env}")

    if test:
        sample = {"exchange": "Bybit", "title": "New Listing: ABCUSDT Perpetual Contract", "url": SOURCES["Bybit"]}
        send(webhook or "https://discord.invalid/webhook", embed(sample, test=True), dry_run)
        return

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    fresh: dict[str, list[str]] = {}
    functions = {
        "Bybit": lambda: page_items("Bybit", SOURCES["Bybit"]),
        "OKX": lambda: page_items("OKX", SOURCES["OKX"]),
        "Coinbase": coinbase_items,
    }
    for name, function in functions.items():
        try:
            items = function()
        except Exception as exc:
            print(f"警告：{name} 讀取失敗：{exc}", file=sys.stderr)
            continue
        old = set(state.get(name, []))
        fresh[name] = [item["id"] for item in items]
        if old:
            for item in reversed(items):
                if item["id"] not in old:
                    send(webhook or "https://discord.invalid/webhook", embed(item), dry_run)

    if not dry_run:
        state.update(fresh)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Send one clearly labelled template to the test webhook")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without contacting Discord or changing state")
    args = parser.parse_args()
    try:
        run(test=args.test, dry_run=args.dry_run)
        return 0
    except Exception as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
