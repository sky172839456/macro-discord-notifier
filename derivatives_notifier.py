"""Bitget-first public derivatives snapshot notifier for Discord."""

from __future__ import annotations

from sender_identity import sender_name
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from notification_format import apply_delivery_format

import exchange_market_data as exchange
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TAIPEI = ZoneInfo("Asia/Taipei")
STATE_FILE = Path(os.getenv("DERIVATIVES_STATE_FILE", ".state/derivatives.json"))
PRICE_WARNING = 3.0
PRICE_DANGER = 5.0
OI_WARNING = 8.0
OI_DANGER = 15.0
FUNDING_WARNING = 0.05
FUNDING_DANGER = 0.10
COOLDOWN_HOURS = 2


def get_json(url: str, params=None):
    request = Request(url + ('&' if '?' in url else '?') + urlencode(params or {}), headers={'User-Agent': 'derivatives/2.0'})
    with urlopen(request, timeout=25) as response:
        return json.load(response)


def fetch_ticker(symbol: str) -> dict[str, Any]:
    if symbol not in SYMBOLS:
        raise ValueError('Unsupported perpetual symbol')
    row = exchange.prefer(lambda venue: exchange.contract(get_json, symbol[:-4], venue))
    return {**row, 'symbol': symbol, 'price_24h_change': row['change_24h'],
            'open_interest_usd': row['oi_usd'], 'turnover_24h': row['volume_24h']}


def money(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    return f"{value:,.0f}"


def percent_change(current: float, previous: float) -> float:
    return ((current / previous) - 1) * 100 if previous else 0.0


def classify(price_change: float, oi_change: float, funding_rate: float) -> str:
    if (abs(price_change) >= PRICE_DANGER or abs(oi_change) >= OI_DANGER
            or abs(funding_rate) >= FUNDING_DANGER
            or (abs(price_change) >= PRICE_WARNING and abs(oi_change) >= OI_WARNING)):
        return "danger"
    if (abs(price_change) >= PRICE_WARNING or abs(oi_change) >= OI_WARNING
            or abs(funding_rate) >= FUNDING_WARNING):
        return "warning"
    return "normal"


def interpretation(price_change: float, oi_change: float, funding_rate: float) -> str:
    if price_change > 0 and oi_change > 0:
        text = "價格與槓桿部位同步增加，追價部位增多，後續波動及多單清算風險提高。"
    elif price_change < 0 and oi_change > 0:
        text = "價格下跌但槓桿部位增加，新增空單可能較多，留意短線軋空風險。"
    elif oi_change < 0:
        text = "未平倉量下降，市場正在去槓桿，可能伴隨平倉或清算。"
    else:
        text = "價格與未平倉量暫無明顯異常。"
    if abs(funding_rate) >= FUNDING_WARNING:
        text += " 資金費率偏極端，市場單邊部位較擁擠。"
    return text


def alert_embed(item: dict[str, Any], price_change: float, oi_change: float, severity: str,
                test: bool = False, interval_minutes: float = 60) -> dict[str, Any]:
    style = {
        "normal": ("🟢 正常", 0x2ECC71),
        "warning": ("🟡 注意", 0xF1C40F),
        "danger": ("🔴 危險", 0xE74C3C),
    }[severity]
    coin = item["symbol"].replace("USDT", "")
    next_funding = datetime.fromtimestamp(item["next_funding"] / 1000, TAIPEI).strftime("%m/%d %H:%M") if item["next_funding"] else "未提供"
    prefix = "🧪 測試｜" if test else ""
    return {
        "author": {"name": "CRYPTO DERIVATIVES WATCH｜衍生品監控"},
        "title": f"{prefix}{style[0]}｜{coin} 衍生品異常監控",
        "description": f"### 約 {max(1, round(interval_minutes))} 分鐘變化\n**價格**　{price_change:+.2f}%\n**未平倉量（OI）**　{oi_change:+.2f}%\n**資金費率**　{item['funding_rate']:+.4f}%",
        "color": style[1],
        "fields": [
            {"name": "📊 即時數據", "value": f"價格　{item['price']:,.2f} USDT\nOI　{money(item['open_interest_usd'])} USDT（估值）\n下次費率結算　{next_funding}", "inline": True},
            {"name": "🧭 市場解讀", "value": interpretation(price_change, oi_change, item["funding_rate"]), "inline": False},
            {"name": "🔗 官方資料", "value": item.get("source_url", "https://www.bitget.com"), "inline": False},
        ],
        "footer": {"text": f"{item.get('source', 'Bitget／幣安')} USDT永續｜估值＝幣數×標記價格｜不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def snapshot_embed(items: list[dict[str, Any]]) -> dict[str, Any]:
    fields = []
    for item in items:
        next_funding = datetime.fromtimestamp(item["next_funding"] / 1000, TAIPEI).strftime("%m/%d %H:%M") if item["next_funding"] else "未提供"
        interpretation = "市場槓桿數據暫無明顯極端訊號。"
        if abs(item["funding_rate"]) >= 0.05:
            side = "多單" if item["funding_rate"] > 0 else "空單"
            interpretation = f"資金費率偏極端，{side}部位可能較為擁擠，留意反向擠壓風險。"
        fields.append({
            "name": f"{item['symbol'].replace('USDT', '')}｜{item.get('source', '來源暫缺')} USDT永續",
            "value": (
                f"**價格**　{item['price']:,.2f} USDT\n"
                f"**24 小時漲跌**　{item['price_24h_change']:+.2f}%\n"
                f"**未平倉量（OI）**　{money(item['open_interest_usd'])} USDT（估值）\n"
                f"**資金費率**　{item['funding_rate']:+.4f}%\n"
                f"**下次結算（台灣）**　{next_funding}\n"
                f"**解讀**　{interpretation}"
            ),
            "inline": False,
        })
    return {
        "author": {"name": "CRYPTO DERIVATIVES WATCH｜衍生品監控"},
        "title": "🧪 測試通知｜BTC／ETH 衍生品即時快照",
        "description": "Bitget公開USDT永續資料優先、幣安備援；各幣標示實際來源，估值＝幣數×標記價格。",
        "color": 0xF7931A,
        "fields": fields,
        "footer": {"text": "官方市場資料｜僅供資訊參考，不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def send_discord(webhook: str, embed: dict[str, Any]) -> None:
    card = apply_delivery_format(embed, "derivatives")
    payload = {"username": sender_name("derivatives"), "embeds": [card], "allowed_mentions": {"parse": []}}
    request = Request(
        webhook + ("&" if "?" in webhook else "?") + "wait=true",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "derivatives-notifier/1.0"},
        method="POST",
    )
    with urlopen(request, timeout=30):
        pass


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"snapshots": {}, "cooldowns": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_monitor(webhook: str) -> None:
    now = datetime.now(timezone.utc)
    state = load_state()
    snapshots = state.setdefault("snapshots", {})
    cooldowns = state.setdefault("cooldowns", {})
    for item in [fetch_ticker(symbol) for symbol in SYMBOLS]:
        history = snapshots.setdefault(item["symbol"], [])
        target = now - timedelta(minutes=55)
        candidates = [row for row in history if datetime.fromisoformat(row["time"]) <= target and row.get("scope") == item.get("scope") and item.get("scope")]
        if candidates:
            previous = candidates[-1]
            interval_minutes = (now - datetime.fromisoformat(previous["time"])).total_seconds() / 60
            price_delta = percent_change(item["price"], previous["price"])
            oi_delta = percent_change(item["open_interest_usd"], previous["open_interest_usd"])
            severity = classify(price_delta, oi_delta, item["funding_rate"])
            last_alert = datetime.fromisoformat(cooldowns[item["symbol"]]) if item["symbol"] in cooldowns else None
            cooled_down = last_alert is None or now - last_alert >= timedelta(hours=COOLDOWN_HOURS)
            if severity != "normal" and cooled_down:
                send_discord(
                    webhook,
                    alert_embed(item, price_delta, oi_delta, severity, interval_minutes=interval_minutes),
                )
                cooldowns[item["symbol"]] = now.isoformat()
        history.append({"time": now.isoformat(), "scope": item.get("scope"), "price": item["price"], "open_interest_usd": item["open_interest_usd"]})
        cutoff = now - timedelta(hours=7)
        snapshots[item["symbol"]] = [row for row in history if datetime.fromisoformat(row["time"]) >= cutoff]
    save_state(state)


def send_test_templates(webhook: str) -> None:
    sample = {"symbol": "BTCUSDT", "price": 65000.0, "open_interest_usd": 2_500_000_000.0,
              "funding_rate": 0.01, "next_funding": int(datetime.now(timezone.utc).timestamp() * 1000)}
    for price_delta, oi_delta, funding, severity in ((0.8, 2.1, 0.01, "normal"),
                                                      (3.2, 8.5, 0.055, "warning"),
                                                      (-5.4, 16.2, -0.11, "danger")):
        sample["funding_rate"] = funding
        send_discord(webhook, alert_embed(sample, price_delta, oi_delta, severity, test=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print", action="store_true", dest="print_only")
    parser.add_argument("--test-templates", action="store_true")
    args = parser.parse_args()
    if args.print_only:
        items = [fetch_ticker(symbol) for symbol in SYMBOLS]
        embed = snapshot_embed(items)
        print(json.dumps(embed, ensure_ascii=False, indent=2))
        return 0
    secret = "DISCORD_TEST_WEBHOOK_URL" if args.test_templates else "DISCORD_DERIVATIVES_WEBHOOK_URL"
    webhook = os.environ.get(secret)
    if not webhook:
        raise RuntimeError(f"缺少 {secret}")
    if args.test_templates:
        send_test_templates(webhook)
        print("完成：已送出正常、注意、危險三種測試模板")
    else:
        run_monitor(webhook)
        print("完成：已更新衍生品狀態，達門檻時才會通知")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
