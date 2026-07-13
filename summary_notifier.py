"""Daily and weekly Discord market summaries using free public data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from config import BLS_CALENDAR_URL, TAIPEI_ZONE
from notifier import http_text, parse_bls_calendar

TAIPEI = ZoneInfo(TAIPEI_ZONE)
COINGECKO_SIMPLE = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_HISTORY = "https://api.coingecko.com/api/v3/coins/{coin}/market_chart"


def http_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "macro-discord-notifier/3.0"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def current_market() -> dict[str, dict[str, float]]:
    query = urlencode({
        "ids": "bitcoin,ethereum",
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    })
    data = http_json(f"{COINGECKO_SIMPLE}?{query}")
    return {
        "BTC": {"price": float(data["bitcoin"]["usd"]), "change": float(data["bitcoin"]["usd_24h_change"])},
        "ETH": {"price": float(data["ethereum"]["usd"]), "change": float(data["ethereum"]["usd_24h_change"])},
    }


def weekly_market() -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}
    for symbol, coin in (("BTC", "bitcoin"), ("ETH", "ethereum")):
        query = urlencode({"vs_currency": "usd", "days": "7", "interval": "daily"})
        data = http_json(f"{COINGECKO_HISTORY.format(coin=coin)}?{query}")
        prices = [float(point[1]) for point in data.get("prices", [])]
        if len(prices) < 2:
            raise ValueError(f"{symbol} 歷史價格資料不足")
        results[symbol] = {"price": prices[-1], "change": (prices[-1] / prices[0] - 1) * 100}
    return results


def upcoming_events(now: datetime, days: int) -> tuple[list[dict[str, Any]], str | None]:
    try:
        events = parse_bls_calendar(http_text(BLS_CALENDAR_URL))
    except Exception as exc:
        return [], f"BLS 行事曆暫時無法取得（{type(exc).__name__}）"
    end = now + timedelta(days=days)
    return sorted((event for event in events if now <= event["time"] < end), key=lambda item: item["time"]), None


def market_lines(market: dict[str, dict[str, float]] | None, error: str | None) -> str:
    if error or not market:
        return f"⚠️ {error or '市場資料暫時無法取得'}"
    lines = []
    for symbol in ("BTC", "ETH"):
        item = market[symbol]
        marker = "🟢" if item["change"] >= 0 else "🔴"
        lines.append(f"{marker} **{symbol}**　${item['price']:,.2f}　`{item['change']:+.2f}%`")
    return "\n".join(lines)


def event_lines(events: list[dict[str, Any]], error: str | None, empty: str) -> str:
    if error:
        return f"⚠️ {error}"
    if not events:
        return empty
    return "\n".join(
        f"• `{event['time'].astimezone(TAIPEI):%m/%d %H:%M}`　{event['rule']['name']}"
        for event in events[:8]
    )


def build_embed(period: str, now: datetime, market: dict[str, dict[str, float]] | None,
                market_error: str | None, events: list[dict[str, Any]], event_error: str | None) -> dict[str, Any]:
    local = now.astimezone(TAIPEI)
    daily = period == "daily"
    return {
        "author": {"name": "MARKET BRIEF｜市場摘要"},
        "title": f"{'📅 每日市場重點' if daily else '🗓️ 每週市場摘要'}｜{local:%Y/%m/%d}",
        "description": "以下數字來自免費公開資料；來源異常時保留警告，不以舊資料或推測值代替。",
        "color": 0x3498DB if daily else 0x8E44AD,
        "fields": [
            {"name": "📊 BTC／ETH 市場概況", "value": market_lines(market, market_error), "inline": False},
            {"name": "🗓️ 今日重要總經事件" if daily else "🗓️ 未來七日總經事件",
             "value": event_lines(events, event_error, "✅ 目前沒有符合條件的 BLS 重要事件。"), "inline": False},
            {"name": "🔎 閱讀方式", "value": "漲跌幅僅描述價格變化，不等同交易訊號；重大事件前後請留意流動性與滑價。", "inline": False},
            {"name": "🔗 原始資料", "value": "https://www.coingecko.com/\nhttps://www.bls.gov/schedule/news_release/", "inline": False},
        ],
        "footer": {"text": "台灣時間｜免費公開資料｜僅供資訊參考，不構成投資建議"},
        "timestamp": now.isoformat(),
    }


def send(webhook: str, embed: dict[str, Any], dry_run: bool) -> None:
    payload = {"username": "市場摘要", "embeds": [embed], "allowed_mentions": {"parse": []}}
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    request = Request(webhook + ("&" if "?" in webhook else "?") + "wait=true",
                      data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", "User-Agent": "macro-discord-notifier/3.0"},
                      method="POST")
    with urlopen(request, timeout=30):
        pass


def run(period: str, now: datetime, dry_run: bool = False) -> None:
    secret = "DISCORD_DAILY_SUMMARY_WEBHOOK_URL" if period == "daily" else "DISCORD_WEEKLY_SUMMARY_WEBHOOK_URL"
    webhook = os.environ.get(secret)
    if not webhook and not dry_run:
        raise RuntimeError(f"缺少 {secret}")
    try:
        market = current_market() if period == "daily" else weekly_market()
        market_error = None
    except Exception as exc:
        market, market_error = None, f"CoinGecko 暫時無法取得（{type(exc).__name__}）"
    events, event_error = upcoming_events(now, 1 if period == "daily" else 7)
    send(webhook or "https://discord.invalid/webhook", build_embed(period, now, market, market_error, events, event_error), dry_run)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=("daily", "weekly"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.period, datetime.now(timezone.utc), args.dry_run)


if __name__ == "__main__":
    main()

