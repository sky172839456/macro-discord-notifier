"""Daily macro and technical-analysis cards for dedicated Discord channels."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from market_brief_data import collect_dashboard
from summary_notifier import event_lines, upcoming_events

TAIPEI = ZoneInfo("Asia/Taipei")
STATE_FILE = Path(".state/channel-analysis.json")
OKX_API = "https://www.okx.com"


def get_json(url, params):
    request = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": "macro-analysis/1.0"})
    with urlopen(request, timeout=25) as response:
        return json.load(response)


def candles(symbol):
    payload = get_json(f"{OKX_API}/api/v5/market/candles", {
        "instId": f"{symbol}-USDT", "bar": "1D", "limit": "60",
    })
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX candles: {payload.get('msg') or payload.get('code')}")
    rows = sorted(payload.get("data", []), key=lambda row: int(row[0]))
    return [{"open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in rows]


def rsi(values, period=14):
    changes = [b - a for a, b in zip(values, values[1:])]
    gains = [max(change, 0) for change in changes[-period:]]
    losses = [max(-change, 0) for change in changes[-period:]]
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0
    return 100 - 100 / (1 + average_gain / average_loss)


def technical_snapshot(symbol):
    rows = candles(symbol)
    closes = [row["close"] for row in rows]
    if len(closes) < 50:
        raise ValueError(f"{symbol} K 線不足 50 根")
    current = closes[-1]
    return {
        "symbol": symbol,
        "price": current,
        "change": (current / closes[-2] - 1) * 100,
        "sma20": sum(closes[-20:]) / 20,
        "sma50": sum(closes[-50:]) / 50,
        "rsi": rsi(closes),
        "high20": max(row["high"] for row in rows[-20:]),
        "low20": min(row["low"] for row in rows[-20:]),
    }


def technical_view(item):
    if item["price"] > item["sma20"] > item["sma50"]:
        trend = "偏多排列"
    elif item["price"] < item["sma20"] < item["sma50"]:
        trend = "偏空排列"
    else:
        trend = "震盪／方向尚未一致"
    momentum = "過熱" if item["rsi"] >= 70 else "超賣" if item["rsi"] <= 30 else "中性"
    return trend, momentum


def technical_embed(items, now):
    lines = []
    for item in items:
        trend, momentum = technical_view(item)
        lines.append(
            f"### {item['symbol']}　`${item['price']:,.2f}`　`{item['change']:+.2f}%`\n"
            f"趨勢：**{trend}**｜RSI(14)：`{item['rsi']:.1f}`（{momentum}）\n"
            f"SMA20 `${item['sma20']:,.2f}`｜SMA50 `${item['sma50']:,.2f}`\n"
            f"20 日區間 `${item['low20']:,.2f}` ～ `${item['high20']:,.2f}`"
        )
    return {
        "author": {"name": "MARKET ANALYSIS｜技術分析"},
        "title": f"📐 BTC／ETH 技術狀態｜{now.astimezone(TAIPEI):%Y/%m/%d}",
        "description": "\n\n".join(lines),
        "color": 0x5865F2,
        "fields": [{
            "name": "閱讀方式",
            "value": "均線與 RSI 只描述目前狀態，不預測價格；區間突破仍需搭配成交量及風險管理確認。",
            "inline": False,
        }, {
            "name": "資料來源",
            "value": "[OKX 公開日線](https://www.okx.com/markets/prices)",
            "inline": False,
        }],
        "footer": {"text": "台灣時間｜每日更新｜不構成投資建議"},
        "timestamp": now.isoformat(),
    }


def macro_embed(dashboard, events, event_error, now):
    traditional = dashboard.get("traditional", {})
    errors = dashboard.get("errors", {})
    names = {"DXY": "DXY", "US10Y": "美債 10Y", "GOLD": "黃金期貨", "NASDAQ": "Nasdaq"}
    lines = []
    for key, label in names.items():
        item = traditional.get(key)
        if not item:
            lines.append(f"⚠️ **{label}**　暫時無法取得（{errors.get('traditional', '來源異常')}）")
            continue
        if key == "US10Y":
            lines.append(f"**{label}**　`{item['price']:.3f}%`　`{item['change_bp']:+.1f} bp`")
        else:
            lines.append(f"**{label}**　`{item['price']:,.3f}`　`{item['change']:+.2f}%`")
    return {
        "author": {"name": "MACRO LENS｜總體經濟"},
        "title": f"🏛️ 每日總體經濟觀察｜{now.astimezone(TAIPEI):%Y/%m/%d}",
        "description": "追蹤傳統市場對加密資產風險偏好的背景影響，不與數據公布通知重複。",
        "color": 0x3498DB,
        "fields": [
            {"name": "市場環境", "value": "\n".join(lines), "inline": False},
            {"name": "未來三日重要事件", "value": event_lines(events, event_error, "✅ 目前沒有符合條件的官方重要事件。"), "inline": False},
            {"name": "觀察重點", "value": "美元與殖利率上升通常提高風險資產壓力；實際反應仍應搭配股市、黃金與事件結果判讀。", "inline": False},
        ],
        "footer": {"text": "台灣時間｜公開資料｜不構成投資建議"},
        "timestamp": now.isoformat(),
    }


def send(webhook, username, embed):
    payload = json.dumps({"username": username, "embeds": [embed], "allowed_mentions": {"parse": []}}).encode()
    request = Request(
        webhook + ("&" if "?" in webhook else "?") + "wait=true",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "macro-analysis/1.0"},
        method="POST",
    )
    with urlopen(request, timeout=25):
        pass


def run(now, test=False):
    sent = []
    test_webhook = os.environ.get("DISCORD_TEST_WEBHOOK_URL") if test else None
    macro_webhook = test_webhook or os.environ.get("DISCORD_MACRO_ANALYSIS_WEBHOOK_URL")
    technical_webhook = test_webhook or os.environ.get("DISCORD_TECHNICAL_ANALYSIS_WEBHOOK_URL")
    if macro_webhook:
        dashboard = collect_dashboard(now)
        events, error = upcoming_events(now, 3)
        card = macro_embed(dashboard, events, error, now)
        if test:
            card["title"] = "🧪 測試｜" + card["title"]
        send(macro_webhook, "總體經濟觀察", card)
        sent.append("macro")
    if technical_webhook:
        card = technical_embed([
            technical_snapshot("BTC"), technical_snapshot("ETH"),
        ], now)
        if test:
            card["title"] = "🧪 測試｜" + card["title"]
        send(technical_webhook, "技術分析雷達", card)
        sent.append("technical")
    return sent


def run_scheduled(now):
    local = now.astimezone(TAIPEI)
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    today = local.date().isoformat()
    if local.hour < 8 or state.get("daily") == today:
        return []
    sent = run(now)
    if sent:
        state["daily"] = today
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return sent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--test-templates", action="store_true")
    args = parser.parse_args()
    if args.test_templates and not os.environ.get("DISCORD_TEST_WEBHOOK_URL"):
        raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL")
    sent = run_scheduled(datetime.now(timezone.utc)) if args.scheduled else run(
        datetime.now(timezone.utc), test=args.test_templates
    )
    print("完成：" + ("、".join(sent) if sent else "本輪無需發送"))


if __name__ == "__main__":
    main()
