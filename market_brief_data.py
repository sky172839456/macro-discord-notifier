"""Free public data collectors for the richer Discord market brief."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

USER_AGENT = "Mozilla/5.0 market-brief/4.0"
COINGECKO = "https://api.coingecko.com/api/v3"
OKX = "https://www.okx.com"
FARSIDE = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
COINBASE_STATUS = "https://status.coinbase.com/api/v2/incidents.json"
TREASURY_YIELDS = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)


def get_text(url: str, *, referer: str | None = None) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/html,application/xml;q=0.9,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")


def get_json(url: str) -> Any:
    return json.loads(get_text(url))


def crypto_snapshot() -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    query = urlencode({
        "vs_currency": "usd",
        "ids": "bitcoin,ethereum,tether,usd-coin",
        "price_change_percentage": "7d",
        "sparkline": "false",
    })
    rows = get_json(f"{COINGECKO}/coins/markets?{query}")
    by_id = {row["id"]: row for row in rows}
    coins: dict[str, dict[str, float]] = {}
    for symbol, coin_id in (("BTC", "bitcoin"), ("ETH", "ethereum")):
        row = by_id[coin_id]
        coins[symbol] = {
            "price": float(row["current_price"]),
            "change_24h": float(row.get("price_change_percentage_24h") or 0),
            "change_7d": float(row.get("price_change_percentage_7d_in_currency") or 0),
            "high_24h": float(row.get("high_24h") or 0),
            "low_24h": float(row.get("low_24h") or 0),
            "volume_24h": float(row.get("total_volume") or 0),
        }
    stablecoins = {
        "USDT": float(by_id["tether"]["current_price"]),
        "USDC": float(by_id["usd-coin"]["current_price"]),
    }
    return coins, stablecoins


def global_snapshot() -> dict[str, float]:
    data = get_json(f"{COINGECKO}/global")["data"]
    return {
        "market_cap": float(data["total_market_cap"]["usd"]),
        "volume_24h": float(data["total_volume"]["usd"]),
        "btc_dominance": float(data["market_cap_percentage"]["btc"]),
        "market_cap_change_24h": float(data.get("market_cap_change_percentage_24h_usd") or 0),
    }


def derivatives_snapshot() -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for coin in ("BTC", "ETH"):
        inst_id = f"{coin}-USDT-SWAP"
        interest = get_json(f"{OKX}/api/v5/public/open-interest?instType=SWAP&instId={inst_id}")
        funding = get_json(f"{OKX}/api/v5/public/funding-rate?instId={inst_id}")
        if interest.get("code") != "0" or not interest.get("data"):
            raise RuntimeError(f"OKX {coin} OI 沒有資料")
        if funding.get("code") != "0" or not funding.get("data"):
            raise RuntimeError(f"OKX {coin} 資金費率沒有資料")
        oi = interest["data"][0]
        rate = funding["data"][0]
        result[coin] = {
            "oi_usd": float(oi.get("oiUsd") or 0),
            "funding_rate": float(rate.get("fundingRate") or 0) * 100,
            "next_funding": float(rate.get("nextFundingTime") or rate.get("fundingTime") or 0),
        }
    return result


def fear_greed_snapshot() -> dict[str, Any]:
    row = get_json("https://api.alternative.me/fng/?limit=1")["data"][0]
    return {
        "value": int(row["value"]),
        "classification": str(row["value_classification"]),
        "timestamp": int(row["timestamp"]),
    }


def yahoo_quote(symbol: str) -> dict[str, float]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?range=5d&interval=1d"
    result = get_json(url)["chart"]["result"][0]
    meta = result["meta"]
    price = float(meta["regularMarketPrice"])
    closes = [float(value) for value in result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
              if value is not None]
    previous = closes[-2] if len(closes) >= 2 else float(meta.get("previousClose") or meta.get("chartPreviousClose") or 0)
    change = (price / previous - 1) * 100 if previous else 0
    return {"price": price, "change": change, "timestamp": float(meta.get("regularMarketTime") or 0)}


def traditional_snapshot() -> dict[str, dict[str, float]]:
    return {
        "DXY": yahoo_quote("DX-Y.NYB"),
        "GOLD": yahoo_quote("GC=F"),
        "NASDAQ": yahoo_quote("^IXIC"),
        "US10Y": treasury_10y_snapshot(),
    }


def treasury_10y_snapshot() -> dict[str, float]:
    root = ElementTree.fromstring(get_text(TREASURY_YIELDS.format(year=datetime.now(timezone.utc).year)))
    namespace = {
        "a": "http://www.w3.org/2005/Atom",
        "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    }
    observations = []
    for entry in root.findall("a:entry", namespace):
        props = entry.find("a:content/m:properties", namespace)
        if props is None:
            continue
        date_node = props.find("d:NEW_DATE", namespace)
        yield_node = props.find("d:BC_10YEAR", namespace)
        if date_node is not None and yield_node is not None and yield_node.text:
            date = datetime.fromisoformat((date_node.text or "").replace("Z", "+00:00"))
            observations.append((date, float(yield_node.text)))
    if not observations:
        raise ValueError("美國財政部 10 年期殖利率沒有資料")
    observations.sort(key=lambda item: item[0])
    date, value = observations[-1]
    previous = observations[-2][1] if len(observations) > 1 else value
    return {"price": value, "change_bp": (value - previous) * 100, "timestamp": date.timestamp()}


def _number(value: str) -> float:
    clean = value.replace(",", "").replace("$", "").strip()
    if not clean or clean in {"-", "—", "N/A"}:
        return 0.0
    negative = clean.startswith("(") and clean.endswith(")")
    clean = clean.strip("()")
    number = float(clean)
    return -number if negative else number


def parse_farside_latest(source: str) -> dict[str, Any]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", source, re.I | re.S)
    candidates = []
    for row in rows:
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(cell))).strip()
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
        ]
        if len(cells) < 2 or not re.fullmatch(r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}", cells[0]):
            continue
        date = datetime.strptime(cells[0], "%d %b %Y").replace(tzinfo=timezone.utc)
        candidates.append((date, _number(cells[-1])))
    if not candidates:
        raise ValueError("Farside ETF 表格沒有可辨識的日期資料")
    date, flow = max(candidates, key=lambda item: item[0])
    return {"date": date, "net_flow_musd": flow}


def etf_flow_snapshot() -> dict[str, Any]:
    return parse_farside_latest(get_text(FARSIDE, referer="https://farside.co.uk/"))


def liquidation_snapshot(now: datetime) -> dict[str, Any]:
    cutoff = int((now - timedelta(hours=24)).timestamp() * 1000)
    totals = {"long": 0.0, "short": 0.0}
    by_coin: dict[str, float] = {}
    for coin, contract_value in (("BTC", 0.01), ("ETH", 0.1)):
        data = get_json(
            f"{OKX}/api/v5/public/liquidation-orders?instType=SWAP&uly={coin}-USDT&state=filled&limit=100"
        )
        if data.get("code") != "0":
            raise RuntimeError(f"OKX {coin} 清算資料錯誤")
        total = 0.0
        for group in data.get("data", []):
            if group.get("instId") != f"{coin}-USDT-SWAP":
                continue
            for item in group.get("details", []):
                if int(item.get("ts") or item.get("time") or 0) < cutoff:
                    continue
                usd = float(item.get("sz") or 0) * contract_value * float(item.get("bkPx") or 0)
                side = str(item.get("posSide") or "").lower()
                if side in totals:
                    totals[side] += usd
                total += usd
        by_coin[coin] = total
    return {"total_usd": sum(by_coin.values()), "by_coin": by_coin, **totals, "scope": "OKX BTC／ETH USDT 永續"}


def exchange_risk_snapshot() -> dict[str, Any]:
    incidents = get_json(COINBASE_STATUS).get("incidents", [])
    active = [item for item in incidents if item.get("status") not in {"resolved", "completed"}]
    return {"active_count": len(active), "names": [str(item.get("name") or "Coinbase 事件") for item in active[:2]]}


def collect_dashboard(now: datetime) -> dict[str, Any]:
    dashboard: dict[str, Any] = {"errors": {}}

    def collect(name: str, function: Any) -> None:
        try:
            dashboard[name] = function()
        except Exception as exc:
            dashboard[name] = None
            dashboard["errors"][name] = f"{type(exc).__name__}"

    try:
        dashboard["crypto"], dashboard["stablecoins"] = crypto_snapshot()
    except Exception as exc:
        dashboard["crypto"] = dashboard["stablecoins"] = None
        dashboard["errors"]["crypto"] = f"{type(exc).__name__}"
    collect("global", global_snapshot)
    collect("derivatives", derivatives_snapshot)
    collect("sentiment", fear_greed_snapshot)
    collect("traditional", traditional_snapshot)
    collect("etf", etf_flow_snapshot)
    collect("liquidations", lambda: liquidation_snapshot(now))
    collect("exchange_risk", exchange_risk_snapshot)
    return dashboard
