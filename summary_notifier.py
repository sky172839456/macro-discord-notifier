"""Daily and weekly Discord market summaries using free public data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from config import BLS_CALENDAR_URL, TAIPEI_ZONE
from notifier import NY, classify, http_text, parse_bls_calendar
from market_brief_data import collect_dashboard

TAIPEI = ZoneInfo(TAIPEI_ZONE)
COINGECKO_SIMPLE = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_HISTORY = "https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
BLS_CALENDAR_MIRRORS = (
    BLS_CALENDAR_URL,
    f"{BLS_CALENDAR_URL}?download=1",
)
FAIR_ECONOMY_CALENDARS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
)


class BLSMonthlyParser(HTMLParser):
    """Collect text from BLS monthly schedule table rows."""

    def __init__(self) -> None:
        super().__init__()
        self.in_row = False
        self.parts: list[str] = []
        self.rows: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.in_row, self.parts = True, []

    def handle_data(self, data: str) -> None:
        if self.in_row and data.strip():
            self.parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.in_row:
            self.rows.append(" ".join(self.parts))
            self.in_row = False


def parse_bls_month_page(source: str) -> list[dict[str, Any]]:
    parser = BLSMonthlyParser()
    parser.feed(source)
    events: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<date>(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"\d{1,2},\s+\d{4})\s+(?P<time>\d{1,2}:\d{2}\s+[AP]M)", re.I
    )
    for row in parser.rows:
        rule = classify(row)
        match = pattern.search(row)
        if not rule or not match:
            continue
        local = datetime.strptime(
            f"{match.group('date')} {match.group('time')}", "%A, %B %d, %Y %I:%M %p"
        ).replace(tzinfo=NY)
        events.append({
            "id": hashlib.sha256(row.encode("utf-8")).hexdigest(),
            "title": row[:match.start()].strip(),
            "time": local.astimezone(timezone.utc),
            "rule": rule,
        })
    return events


def official_calendar_fallback(now: datetime, days: int) -> list[dict[str, Any]]:
    end = now + timedelta(days=days)
    months = {(now.astimezone(NY).year, now.astimezone(NY).month),
              (end.astimezone(NY).year, end.astimezone(NY).month)}
    events: list[dict[str, Any]] = []
    for year, month in sorted(months):
        url = f"https://www.bls.gov/schedule/{year}/{month:02d}_sched_list.htm"
        try:
            events.extend(parse_bls_month_page(http_text(url)))
        except Exception:
            continue
    return events


def parse_fair_economy_calendar(data: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        if str(item.get("country", "")).upper() != "USD":
            continue
        title = str(item.get("title", ""))
        aliases = {
            "cpi": "consumer price index",
            "ppi": "producer price index",
            "non-farm": "employment situation",
            "unemployment rate": "employment situation",
            "advance gdp": "gross domestic product",
            "final gdp": "gross domestic product",
            "prelim gdp": "gross domestic product",
        }
        lower_title = title.lower()
        if "fomc" in lower_title and any(word in lower_title for word in ("speaks", "speech", "member")):
            expanded = "governor speaks"
        elif "fomc" in lower_title:
            expanded = title + " fomc monetary policy statement"
        else:
            expanded = title + " " + " ".join(value for key, value in aliases.items() if key in lower_title)
        rule = classify(expanded)
        if not rule:
            continue
        try:
            event_time = datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00"))
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=NY)
        except (KeyError, ValueError):
            continue
        events.append({
            "id": hashlib.sha256(f"{title}|{event_time.isoformat()}".encode()).hexdigest(),
            "title": title,
            "time": event_time.astimezone(timezone.utc),
            "rule": rule,
        })
    return events


def public_calendar_fallback() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for url in FAIR_ECONOMY_CALENDARS:
        try:
            events.extend(parse_fair_economy_calendar(http_json(url)))
        except Exception:
            continue
    return events


def public_calendar_fallback_with_status() -> tuple[list[dict[str, Any]], bool]:
    """Return whether at least one public calendar responded, even with no matching events."""
    events: list[dict[str, Any]] = []
    succeeded = False
    for url in FAIR_ECONOMY_CALENDARS:
        try:
            payload = http_json(url)
            succeeded = True
            events.extend(parse_fair_economy_calendar(payload))
        except Exception:
            continue
    return events, succeeded


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
    events: list[dict[str, Any]] = []
    # BLS occasionally rejects requests from shared cloud IPs. Try the official
    # calendar endpoint more than once, then its official download variant.
    for url in BLS_CALENDAR_MIRRORS:
        for attempt in range(2):
            try:
                events = parse_bls_calendar(http_text(url))
                if events:
                    break
            except Exception:
                if attempt == 0:
                    time.sleep(1)
        if events:
            break
    if not events:
        events = official_calendar_fallback(now, days)
    public_succeeded = False
    if not events:
        events, public_succeeded = public_calendar_fallback_with_status()
    if not events and not public_succeeded:
        return [], "官方行事曆目前未完成同步，系統將於下次排程自動重試。"
    end = now + timedelta(days=days)
    filtered = sorted((event for event in events if now <= event["time"] < end), key=lambda item: item["time"])
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, datetime, str]] = set()
    for event in filtered:
        # Different Fed officials can speak at the same time. Preserve their
        # names/titles while still collapsing duplicated calendar entries.
        identity = event["title"].strip().lower() if event["rule"]["key"] == "fed_official" else ""
        key = (event["rule"]["key"], event["time"].replace(second=0, microsecond=0), identity)
        if key not in seen:
            seen.add(key)
            unique.append(event)
    return unique, None


def market_lines(market: dict[str, dict[str, float]] | None, error: str | None) -> str:
    if error or not market:
        return f"⚠️ {error or '市場資料暫時無法取得'}"
    lines = []
    for symbol in ("BTC", "ETH"):
        item = market[symbol]
        marker = "🟢" if item["change"] >= 0 else "🔴"
        lines.append(f"{marker} **{symbol}**　${item['price']:,.2f}　`{item['change']:+.2f}%`")
    return "\n".join(lines)


def money(value: float) -> str:
    value = float(value)
    if abs(value) >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.0f}"


def unavailable(dashboard: dict[str, Any], key: str) -> str:
    error = dashboard.get("errors", {}).get(key, "來源暫時無法取得")
    return f"⚠️ 暫時無法取得（{error}）"


def crypto_detail_lines(dashboard: dict[str, Any]) -> str:
    coins = dashboard.get("crypto")
    if not coins:
        return unavailable(dashboard, "crypto")
    lines = []
    for symbol in ("BTC", "ETH"):
        item = coins[symbol]
        marker = "🟢" if item["change_24h"] >= 0 else "🔴"
        lines.append(
            f"{marker} **{symbol}**　${item['price']:,.2f}　`{item['change_24h']:+.2f}%`\n"
            f"└ 24h 高／低 `${item['high_24h']:,.2f}`／`${item['low_24h']:,.2f}`　量 {money(item['volume_24h'])}"
        )
    return "\n".join(lines)


def derivatives_lines(dashboard: dict[str, Any]) -> str:
    data = dashboard.get("derivatives")
    if not data:
        return unavailable(dashboard, "derivatives")
    lines = []
    for symbol in ("BTC", "ETH"):
        item = data[symbol]
        funding_at = datetime.fromtimestamp(item["next_funding"] / 1000, TAIPEI).strftime("%m/%d %H:%M")
        lines.append(
            f"**{symbol}**　OI {money(item['oi_usd'])}　資金費率 `{item['funding_rate']:+.4f}%`\n"
            f"└ 下次結算 {funding_at}"
        )
    return "\n".join(lines)


def breadth_lines(dashboard: dict[str, Any]) -> str:
    global_data = dashboard.get("global")
    sentiment = dashboard.get("sentiment")
    lines = []
    if global_data:
        lines.append(
            f"總市值 **{money(global_data['market_cap'])}**　`{global_data['market_cap_change_24h']:+.2f}%`\n"
            f"24h 成交量 {money(global_data['volume_24h'])}　BTC 市占 `{global_data['btc_dominance']:.2f}%`"
        )
    else:
        lines.append(unavailable(dashboard, "global"))
    if sentiment:
        labels = {
            "Extreme Fear": "極度恐慌", "Fear": "恐慌", "Neutral": "中性",
            "Greed": "貪婪", "Extreme Greed": "極度貪婪",
        }
        classification = labels.get(sentiment["classification"], sentiment["classification"])
        lines.append(f"恐慌貪婪 **{sentiment['value']}／100**　{classification}")
    else:
        lines.append(unavailable(dashboard, "sentiment"))
    return "\n".join(lines)


def traditional_lines(dashboard: dict[str, Any]) -> str:
    data = dashboard.get("traditional")
    if not data:
        return unavailable(dashboard, "traditional")
    return "\n".join([
        f"**DXY**　{data['DXY']['price']:.3f}　`{data['DXY']['change']:+.2f}%`",
        f"**美債 10Y**　{data['US10Y']['price']:.3f}%　`{data['US10Y']['change_bp']:+.1f} bp`",
        f"**黃金期貨**　${data['GOLD']['price']:,.2f}　`{data['GOLD']['change']:+.2f}%`",
        f"**Nasdaq**　{data['NASDAQ']['price']:,.2f}　`{data['NASDAQ']['change']:+.2f}%`",
    ])


def risk_status_lines(dashboard: dict[str, Any]) -> str:
    stablecoins = dashboard.get("stablecoins")
    exchange = dashboard.get("exchange_risk")
    lines = []
    if stablecoins:
        parts = []
        for symbol in ("USDT", "USDC"):
            price = stablecoins[symbol]
            marker = "✅" if abs(price - 1) < 0.005 else "⚠️"
            parts.append(f"{marker} {symbol} `${price:.4f}`")
        lines.append("　".join(parts))
    else:
        lines.append(unavailable(dashboard, "crypto"))
    if exchange:
        if exchange["active_count"]:
            lines.append(f"⚠️ Coinbase 未解決事件 {exchange['active_count']} 件：{'、'.join(exchange['names'])}")
        else:
            lines.append("✅ Coinbase 官方狀態目前無未解決事件")
    else:
        lines.append(unavailable(dashboard, "exchange_risk"))
    return "\n".join(lines)


def flow_lines(dashboard: dict[str, Any]) -> str:
    etf = dashboard.get("etf")
    eth_etf = dashboard.get("eth_etf")
    liquidations = dashboard.get("liquidations")
    lines = []
    if etf:
        direction = "淨流入" if etf["net_flow_musd"] >= 0 else "淨流出"
        lines.append(
            f"**美國現貨 BTC ETF**　{etf['date']:%m/%d} {direction} `${abs(etf['net_flow_musd']):,.1f}M`"
        )
    else:
        lines.append("BTC ETF：" + unavailable(dashboard, "etf"))
    if eth_etf:
        direction = "淨流入" if eth_etf["net_flow_musd"] >= 0 else "淨流出"
        lines.append(
            f"**美國現貨 ETH ETF**　{eth_etf['date']:%m/%d} {direction} `${abs(eth_etf['net_flow_musd']):,.1f}M`"
        )
    else:
        lines.append("ETH ETF：" + unavailable(dashboard, "eth_etf"))
    if liquidations:
        lines.append(
            f"**24h 清算（{liquidations['scope']}）**　{money(liquidations['total_usd'])}\n"
            f"└ 多單 {money(liquidations['long'])}　空單 {money(liquidations['short'])}"
        )
    else:
        lines.append("清算：" + unavailable(dashboard, "liquidations"))
    return "\n".join(lines)


def risk_summary(dashboard: dict[str, Any], events: list[dict[str, Any]], event_error: str | None) -> str:
    notes = []
    sentiment = dashboard.get("sentiment")
    if sentiment and sentiment["value"] <= 25:
        notes.append("市場情緒處於極度恐慌區，短線波動與非理性拋售風險較高。")
    elif sentiment and sentiment["value"] >= 75:
        notes.append("市場情緒處於極度貪婪區，追價與回撤風險提高。")
    derivatives = dashboard.get("derivatives") or {}
    crowded = [symbol for symbol, item in derivatives.items() if abs(item["funding_rate"]) >= 0.05]
    if crowded:
        notes.append(f"{'／'.join(crowded)} 資金費率偏高，留意擁擠部位反向擠壓。")
    stablecoins = dashboard.get("stablecoins") or {}
    deviated = [symbol for symbol, price in stablecoins.items() if abs(price - 1) >= 0.005]
    if deviated:
        notes.append(f"{'／'.join(deviated)} 偏離 1 美元超過 0.5%，留意流動性與充提狀態。")
    exchange = dashboard.get("exchange_risk") or {}
    if exchange.get("active_count"):
        notes.append("交易所官方狀態頁有未解決事件，操作前請確認服務狀態。")
    if events and not event_error:
        notes.append(f"今日有 {len(events)} 項追蹤中的重要總經事件，公布前後留意滑價。")
    elif event_error:
        notes.append("總經行事曆尚未完成同步，今日事件風險目前無法確認。")
    if not notes:
        notes.append("目前監測項目未出現明顯極端訊號；仍請依自身風險承受度管理部位。")
    errors = dashboard.get("errors", {})
    if errors:
        notes.append(f"部分資料來源暫缺：{'、'.join(errors)}；結論未使用猜測值補齊。")
    return "\n".join(f"• {note}" for note in notes[:4])


def event_display_name(event: dict[str, Any]) -> str:
    if event["rule"]["key"] != "fed_official":
        return event["rule"]["name"]
    title = re.sub(r"\s+", " ", str(event.get("title", "")).strip())
    match = re.match(r"FOMC Member (.+?) Speaks(?:\b.*)?$", title, re.I)
    if match:
        return f"聯準會官員 {match.group(1)} 發言（{title}）"
    return f"聯準會官員談話（{title}）" if title else event["rule"]["name"]


def event_lines(events: list[dict[str, Any]], error: str | None, empty: str) -> str:
    if error:
        return f"🗓️ {error}"
    if not events:
        return empty
    return "\n".join(
        f"• `{event['time'].astimezone(TAIPEI):%m/%d %H:%M}`　{event_display_name(event)}"
        for event in events[:8]
    )


def build_embed(period: str, now: datetime, market: dict[str, dict[str, float]] | None,
                market_error: str | None, events: list[dict[str, Any]], event_error: str | None,
                dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    local = now.astimezone(TAIPEI)
    daily = period == "daily"
    fields = [
        {"name": "📊 BTC／ETH 市場概況", "value": market_lines(market, market_error), "inline": False},
        {"name": "🗓️ 今日重要總經事件" if daily else "🗓️ 未來七日總經事件",
         "value": event_lines(events, event_error, "✅ 目前沒有符合條件的官方重要事件。"), "inline": False},
    ]
    if dashboard:
        fields = [
            {"name": "📊 BTC／ETH 價格與成交", "value": crypto_detail_lines(dashboard), "inline": False},
            {"name": "⚙️ 衍生品部位", "value": derivatives_lines(dashboard), "inline": False},
            {"name": "🌐 市場廣度與情緒", "value": breadth_lines(dashboard), "inline": False},
            {"name": "🏛️ 傳統市場", "value": traditional_lines(dashboard), "inline": False},
            {"name": "🗓️ 今日重要總經事件" if daily else "🗓️ 未來七日總經事件",
             "value": event_lines(events, event_error, "✅ 目前沒有符合條件的官方重要事件。"), "inline": False},
            {"name": "🛡️ 穩定幣與交易所狀態", "value": risk_status_lines(dashboard), "inline": False},
            {"name": "💸 ETF 資金流與清算", "value": flow_lines(dashboard), "inline": False},
            {"name": "🧭 今日風險摘要", "value": risk_summary(dashboard, events, event_error), "inline": False},
        ]
    fields.extend([
        {"name": "🔎 閱讀方式", "value": "數據只描述市場狀態，不等同交易訊號；清算為 OKX 可觀測範圍，ETF 為最近完成更新的美國交易日。", "inline": False},
        {"name": "🔗 原始資料", "value": (
            "[CoinGecko](https://www.coingecko.com/)｜[OKX](https://www.okx.com/)｜"
            "[恐慌貪婪](https://alternative.me/crypto/fear-and-greed-index/)｜"
            "[美國財政部](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/)｜"
            "[Yahoo Finance](https://finance.yahoo.com/)｜[Farside](https://farside.co.uk/btc/)｜"
            "[Coinbase Status](https://status.coinbase.com/)｜"
            "[BLS](https://www.bls.gov/schedule/news_release/)／[Forex Factory](https://www.forexfactory.com/calendar)"
        ), "inline": False},
    ])
    return {
        "author": {"name": "MARKET BRIEF｜市場摘要"},
        "title": f"{'📅 每日市場重點' if daily else '🗓️ 每週市場摘要'}｜{local:%Y/%m/%d}",
        "description": "以下數字來自免費公開資料；來源異常時保留警告，不以舊資料或推測值代替。",
        "color": 0x3498DB if daily else 0x8E44AD,
        "fields": fields,
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
    dashboard = collect_dashboard(now)
    if period == "daily" and dashboard.get("crypto"):
        market = {symbol: {"price": item["price"], "change": item["change_24h"]}
                  for symbol, item in dashboard["crypto"].items()}
        market_error = None
    else:
        try:
            market = weekly_market() if period == "weekly" else current_market()
            market_error = None
        except Exception as exc:
            market, market_error = None, f"CoinGecko 暫時無法取得（{type(exc).__name__}）"
    events, event_error = upcoming_events(now, 1 if period == "daily" else 7)
    embed = build_embed(period, now, market, market_error, events, event_error, dashboard)
    if os.environ.get("MARKET_SUMMARY_TEST") == "1":
        embed["title"] = f"🧪 測試｜{embed['title']}"
        embed["description"] = "這是測試頻道預覽，不是正式公告。\n" + embed["description"]
    send(webhook or "https://discord.invalid/webhook", embed, dry_run)


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
