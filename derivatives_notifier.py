"""Free Bybit derivatives snapshot notifier for Discord."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BYBIT_API = "https://api.bybit.com/v5/market/tickers"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TAIPEI = ZoneInfo("Asia/Taipei")


def get_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={"User-Agent": "macro-discord-notifier/derivatives-1.0"},
    )
    with urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_ticker(symbol: str) -> dict[str, Any]:
    payload = get_json(BYBIT_API, {"category": "linear", "symbol": symbol})
    if payload.get("retCode") != 0 or not payload.get("result", {}).get("list"):
        raise RuntimeError(f"Bybit 回傳異常：{payload.get('retMsg', '沒有資料')}")
    item = payload["result"]["list"][0]
    return {
        "symbol": symbol,
        "price": float(item["lastPrice"]),
        "price_1h": float(item.get("prevPrice1h") or item["lastPrice"]),
        "price_24h_change": float(item.get("price24hPcnt") or 0) * 100,
        "open_interest_usd": float(item.get("openInterestValue") or 0),
        "funding_rate": float(item.get("fundingRate") or 0) * 100,
        "turnover_24h": float(item.get("turnover24h") or 0),
        "next_funding": int(item.get("nextFundingTime") or 0),
    }


def money(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    return f"${value:,.0f}"


def snapshot_embed(items: list[dict[str, Any]]) -> dict[str, Any]:
    fields = []
    for item in items:
        one_hour = ((item["price"] / item["price_1h"]) - 1) * 100 if item["price_1h"] else 0
        next_funding = datetime.fromtimestamp(item["next_funding"] / 1000, TAIPEI).strftime("%m/%d %H:%M") if item["next_funding"] else "未提供"
        interpretation = "市場槓桿數據暫無明顯極端訊號。"
        if abs(item["funding_rate"]) >= 0.05:
            side = "多單" if item["funding_rate"] > 0 else "空單"
            interpretation = f"資金費率偏極端，{side}部位可能較為擁擠，留意反向擠壓風險。"
        fields.append({
            "name": f"{item['symbol'].replace('USDT', '')} 永續合約",
            "value": (
                f"**價格**　${item['price']:,.2f}\n"
                f"**1 小時漲跌**　{one_hour:+.2f}%\n"
                f"**24 小時漲跌**　{item['price_24h_change']:+.2f}%\n"
                f"**未平倉量（OI）**　{money(item['open_interest_usd'])}\n"
                f"**資金費率**　{item['funding_rate']:+.4f}%\n"
                f"**下次結算（台灣）**　{next_funding}\n"
                f"**解讀**　{interpretation}"
            ),
            "inline": False,
        })
    return {
        "author": {"name": "CRYPTO DERIVATIVES WATCH｜衍生品監控"},
        "title": "🧪 測試通知｜BTC／ETH 衍生品即時快照",
        "description": "資料直接取自 Bybit 公開市場 API，不需要 CoinGlass 付費方案。",
        "color": 0xF7931A,
        "fields": fields,
        "footer": {"text": "官方市場資料｜僅供資訊參考，不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def send_discord(webhook: str, embed: dict[str, Any]) -> None:
    payload = {"username": "加密衍生品監控", "embeds": [embed], "allowed_mentions": {"parse": []}}
    request = Request(
        webhook + ("&" if "?" in webhook else "?") + "wait=true",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "derivatives-notifier/1.0"},
        method="POST",
    )
    with urlopen(request, timeout=30):
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print", action="store_true", dest="print_only")
    args = parser.parse_args()
    items = [fetch_ticker(symbol) for symbol in SYMBOLS]
    embed = snapshot_embed(items)
    if args.print_only:
        print(json.dumps(embed, ensure_ascii=False, indent=2))
        return 0
    webhook = os.environ.get("DISCORD_TEST_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL")
    send_discord(webhook, embed)
    print("完成：已送出衍生品測試通知")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
