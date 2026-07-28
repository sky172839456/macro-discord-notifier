"""Stablecoin and official exchange-risk monitor using free public sources."""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from notification_format import apply_delivery_format, bilingual_sections, clean_source_text, english_key_points

STATE_FILE = Path(".state/risk-monitor.json")
PAIRS = {"USDT": "USDT-USD", "USDC": "USDC-USD", "DAI": "DAI-USD"}
STATUS_URL = "https://status.coinbase.com/api/v2/incidents.json"
BYBIT_STATUS_URL = "https://api.bybit.com/v5/system/status"
TAIPEI = ZoneInfo("Asia/Taipei")

STATUS_ZH = {
    "investigating": "調查中",
    "identified": "已確認原因",
    "monitoring": "監控恢復狀況",
    "resolved": "已恢復",
    "scheduled": "已排定",
    "in_progress": "處理中",
    "ongoing": "進行中",
    "completed": "已完成",
}

TITLE_TERMS = (
    ("degraded performance", "效能下降"),
    ("service unavailable", "服務無法使用"),
    ("system maintenance", "系統維護"),
    ("partial outage", "部分服務中斷"),
    ("major outage", "重大服務中斷"),
    ("transactions", "交易服務"),
    ("withdrawals", "提款"),
    ("deposits", "充值"),
    ("trading", "交易"),
    ("wallet", "錢包"),
    ("delayed", "延遲"),
    ("outage", "服務中斷"),
    ("incident", "異常事件"),
)


def get_json(url):
    req = Request(url, headers={"User-Agent": "crypto-risk-monitor/2.0"})
    with urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode())


def send(webhook, embed):
    card = apply_delivery_format(embed, "market_risk")
    body = json.dumps({
        "username": "加密市場風險監控",
        "embeds": [card],
        "allowed_mentions": {"parse": []},
    }).encode()
    req = Request(
        webhook + ("&" if "?" in webhook else "?") + "wait=true",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "crypto-risk-monitor/2.0"},
        method="POST",
    )
    with urlopen(req, timeout=25):
        pass


def load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"counts": {}, "incidents": {}}


def save(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def translate_status(status):
    return STATUS_ZH.get(str(status).lower(), "狀態更新")


def translate_title(title):
    translated = str(title)
    lower = translated.lower()
    found = []
    for english, chinese in TITLE_TERMS:
        if english in lower:
            found.append(chinese)
            lower = lower.replace(english, " ")
    return "、".join(dict.fromkeys(found)) if found else "交易所官方事件更新"


def update_summary(status, body):
    lower = str(body).lower()
    if status == "resolved" or "has been resolved" in lower:
        return "官方表示事件已解決，相關服務已恢復；若仍有異常請以官方最新狀態為準。"
    if status == "monitoring":
        return "官方已採取修復措施，目前正在監控服務恢復狀況。"
    if status == "identified":
        return "官方已確認問題原因並著手處理，恢復時間仍以後續更新為準。"
    if status == "scheduled":
        return "官方已排定維護或服務調整，請留意公告所列影響範圍與時間。"
    return "官方正在調查服務異常，期間請避免重複操作並留意後續更新。"


def depeg_embed(coin, price, level, test=False):
    danger = level == "danger"
    prefix = "🧪 測試｜" if test else ""
    persistence = "已偵測到明顯異常" if danger else "已連續兩次偵測到異常"
    return {
        "title": f"{prefix}{'🔴 危險' if danger else '🟡 注意'}｜{coin} 穩定幣價格偏離",
        "description": (
            f"### 現價　`${price:.4f}`\n**偏離 1 美元**　{(price-1)*100:+.2f}%\n\n"
            f"{persistence}，請留意流動性、充提與相關 DeFi 風險。"
        ),
        "color": 0xE74C3C if danger else 0xF1C40F,
        "fields": [{
            "name": "🔗 官方價格來源",
            "value": f"https://exchange.coinbase.com/trade/{PAIRS.get(coin, 'USDT-USD')}",
            "inline": False,
        }],
        "footer": {"text": "Coinbase 公開行情｜僅供資訊參考，不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def exchange_incident_embed(exchange, item, test=False):
    status = str(item.get("status") or item.get("state") or "investigating").lower()
    resolved = status in {"resolved", "completed"}
    original_title = str(item.get("name") or item.get("title") or f"{exchange} 事件")
    original_body = str(item.get("body") or "")
    if not original_body:
        original_body = str((item.get("incident_updates") or [{}])[0].get("body", ""))
    updated = item.get("updated_at") or item.get("endTime") or item.get("beginTime")
    source = item.get("shortlink") or item.get("url") or {
        "Coinbase": "https://status.coinbase.com/",
        "Bybit": "https://announcements.bybit.com/en/",
    }.get(exchange, "")
    prefix = "🧪 測試｜" if test else ""
    zh_title = translate_title(original_title)
    source_summary = clean_source_text(original_body, 1300)
    bilingual = bilingual_sections(
        original_title=original_title,
        english_summary=source_summary,
        english_points=english_key_points(source_summary),
        zh_title=zh_title,
        zh_points=[update_summary(status, original_body)],
    )
    return {
        "title": f"{prefix}{'✅ 已恢復' if resolved else '🚨 交易所服務異常'}｜{exchange}｜{zh_title}",
        "description": bilingual,
        "color": 0x2ECC71 if resolved else 0xE74C3C,
        "fields": [
            {"name": "狀態", "value": f"{translate_status(status)}（{status}）", "inline": True},
            {"name": "官方更新時間", "value": str(updated or "官方未提供"), "inline": True},
            {
                "name": "機器人發現時間",
                "value": datetime.now(timezone.utc).astimezone(TAIPEI).strftime("%Y/%m/%d %H:%M（台灣）"),
                "inline": True,
            },
            {"name": "官方來源", "value": source or "官方公告頁", "inline": False},
        ],
        "footer": {"text": f"{exchange} 官方資料｜繁中為重點整理，原文保留｜不構成投資建議"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def incident_embed(item, test=False):
    """Backward-compatible Coinbase embed helper."""
    return exchange_incident_embed("Coinbase", item, test)


def official_notice_embed(item):
    category = item["category"]
    title = str(item.get("title", "官方公告"))
    exchange = item["exchange"]
    zh_point = (
        "官方公告涉及安全或資產風險，請優先確認受影響服務與官方處置。"
        if category["key"] == "security"
        else "官方公告涉及服務中斷或重大異常，請留意交易、登入與充提功能。"
    )
    bilingual = bilingual_sections(
        original_title=title,
        english_summary=None,
        english_points=None,
        zh_title=translate_title(title),
        zh_points=[zh_point],
    )
    return {
        "title": f"{category['icon']} {exchange}｜{category['label']}",
        "description": bilingual,
        "color": 0xE74C3C,
        "fields": [
            {"name": "事件類型", "value": category["label"], "inline": True},
            {"name": "機器人發現時間", "value": datetime.now(timezone.utc).astimezone(TAIPEI).strftime("%Y/%m/%d %H:%M（台灣）"), "inline": True},
            {"name": "官方來源", "value": item["url"], "inline": False},
        ],
        "footer": {"text": f"{exchange} 官方公告｜僅同步重大風險，不重複一般維護公告"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def bybit_incidents():
    payload = get_json(BYBIT_STATUS_URL)
    if payload.get("retCode") != 0:
        raise RuntimeError(f"Bybit status API: {payload.get('retMsg') or payload.get('retCode')}")
    result = []
    for item in payload.get("result", {}).get("list", []):
        normalized = dict(item)
        normalized["url"] = "https://announcements.bybit.com/en/"
        result.append(normalized)
    return result


def critical_official_notices():
    """Use each exchange's official announcement collector; mirror only critical risk."""
    from exchange_announcement_notifier import PAGE_SOURCES, page_items

    items = []
    for exchange in ("Binance", "OKX", "Bybit", "Bitget"):
        try:
            current = page_items(exchange, PAGE_SOURCES[exchange])
            items.extend(
                item for item in current
                if item.get("category", {}).get("key") in {"security", "outage"}
            )
        except Exception as exc:
            print(f"警告：{exchange} 官方風險公告無法取得：{exc}")
    return items


def monitor(webhook):
    state = load()
    counts = state.setdefault("counts", {})
    active = state.setdefault("active", {})
    known = state.setdefault("incidents", {})
    exchange_events = state.setdefault("exchange_events", {})
    baselines = state.setdefault("baselines", {})

    for coin, pair in PAIRS.items():
        try:
            price = float(get_json(f"https://api.exchange.coinbase.com/products/{pair}/ticker")["price"])
        except Exception as exc:
            print(f"警告：{coin} 價格無法取得：{exc}")
            continue
        level = "danger" if price < .99 or price > 1.01 else "warning" if price < .995 or price > 1.005 else "normal"
        counts[coin] = counts.get(coin, 0) + 1 if level != "normal" else 0
        should_alert = level == "danger" or (level == "warning" and counts[coin] >= 2)
        if should_alert and not active.get(coin):
            send(webhook, depeg_embed(coin, price, level))
            active[coin] = True
        elif level == "normal":
            active[coin] = False

    first_coinbase = not baselines.get("CoinbaseStatus", bool(known))
    try:
        for item in get_json(STATUS_URL).get("incidents", [])[:20]:
            key = item["id"]
            marker = str(item.get("updated_at", "")) + str(item.get("status", ""))
            if not first_coinbase and known.get(key) != marker:
                send(webhook, incident_embed(item))
            known[key] = marker
    except Exception as exc:
        print(f"警告：Coinbase 官方狀態無法取得：{exc}")
    else:
        baselines["CoinbaseStatus"] = True

    bybit_known = exchange_events.setdefault("BybitStatus", {})
    first_bybit = not baselines.get("BybitStatus", bool(bybit_known))
    try:
        for item in bybit_incidents():
            key = str(item.get("id") or item.get("title"))
            marker = "|".join(str(item.get(field, "")) for field in ("state", "beginTime", "endTime", "title"))
            if not first_bybit and bybit_known.get(key) != marker:
                send(webhook, exchange_incident_embed("Bybit", item))
            bybit_known[key] = marker
    except Exception as exc:
        print(f"警告：Bybit 官方狀態無法取得：{exc}")
    else:
        baselines["BybitStatus"] = True

    notice_known = exchange_events.setdefault("CriticalNotices", {})
    first_notices = not baselines.get("CriticalNotices", bool(notice_known))
    notices = critical_official_notices()
    for item in notices:
        key = f"{item['exchange']}:{item['id']}"
        if not first_notices and key not in notice_known:
            send(webhook, official_notice_embed(item))
        notice_known[key] = datetime.now(timezone.utc).isoformat()
    baselines["CriticalNotices"] = True

    # Keep state bounded while retaining the newest insertion order.
    state["incidents"] = dict(list(known.items())[-100:])
    exchange_events["BybitStatus"] = dict(list(bybit_known.items())[-100:])
    exchange_events["CriticalNotices"] = dict(list(notice_known.items())[-300:])
    save(state)


def tests(webhook):
    send(webhook, depeg_embed("USDC", .993, "warning", True))
    send(webhook, depeg_embed("USDT", .986, "danger", True))
    send(webhook, incident_embed({
        "name": "Degraded Performance - Transactions",
        "status": "investigating",
        "shortlink": "https://status.coinbase.com/",
        "incident_updates": [{"body": "Some users may experience delayed transactions. We are investigating."}],
    }, True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-templates", action="store_true")
    args = parser.parse_args()
    secret = "DISCORD_TEST_WEBHOOK_URL" if args.test_templates else "DISCORD_RISK_WEBHOOK_URL"
    webhook = os.environ.get(secret)
    if not webhook:
        raise RuntimeError(f"缺少 {secret}")
    tests(webhook) if args.test_templates else monitor(webhook)
    print("完成：風險監控已執行")


if __name__ == "__main__":
    main()
