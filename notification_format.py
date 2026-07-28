"""Shared presentation rules for Discord notification cards."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

CHANNEL_AUTHORS = {
    "macro_alerts": "US MACRO WATCH｜總經數據快訊",
    "exchange_listings": "EXCHANGE LISTING RADAR｜上幣通知",
    "breaking_news": "BREAKING NEWS｜重大快訊",
    "market_risk": "CRYPTO RISK WATCH｜市場風險警報",
    "derivatives": "DERIVATIVES WATCH｜市場風險警報",
    "crypto_news": "CRYPTO NEWS RADAR｜加密新聞",
    "exchange_announcements": "EXCHANGE NOTICE RADAR｜交易所公告",
    "regulation_etf": "REGULATION & ETF｜監管與 ETF",
    "macro_analysis": "MACRO LENS｜每日總經觀察",
    "technical_analysis": "MARKET ANALYSIS｜技術分析",
    "daily_market": "MARKET BRIEF｜市場摘要",
    "weekly_market": "MARKET BRIEF｜市場摘要",
    "bot_log": "SYSTEM HEALTH｜機器人紀錄",
}

SOURCE_STATUS = {
    "ok": ("✅ 正常取得", "主要來源回應正常"),
    "backup": ("🟡 使用備援來源", "主要來源暫時不可用，已由備援資料補足"),
    "partial": ("⚠️ 部分資料缺少", "仍顯示已確認內容，缺少項目不使用推測值"),
    "error": ("❌ 所有來源失敗", "本次無法確認資料，系統稍後自動重試"),
}


def source_status_text(status: str, detail: str | None = None) -> str:
    if status not in SOURCE_STATUS:
        raise ValueError(f"unsupported source status: {status}")
    label, default_detail = SOURCE_STATUS[status]
    return f"**{label}**\n{detail or default_detail}"


def infer_source_status(embed: dict[str, Any]) -> str:
    text = json.dumps(embed, ensure_ascii=False).lower()
    if any(marker in text for marker in (
        "所有來源失敗", "來源暫時無法確認", "暫時無法取得", "httperror", "來源讀取異常",
    )):
        return "error"
    if any(marker in text for marker in ("使用備援", "備援來源", "fallback")):
        return "backup"
    if any(marker in text for marker in ("部分資料缺少", "部分來源", "缺少資料", "未提供")):
        return "partial"
    return "ok"


def apply_delivery_format(
    embed: dict[str, Any],
    channel_key: str,
    *,
    source_status: str | None = None,
) -> dict[str, Any]:
    if channel_key not in CHANNEL_AUTHORS:
        raise ValueError(f"unsupported notification channel: {channel_key}")
    card = copy.deepcopy(embed)
    author = dict(card.get("author") or {})
    author["name"] = CHANNEL_AUTHORS[channel_key]
    card["author"] = author

    fields = list(card.get("fields") or [])
    if len(fields) < 25 and not any(field.get("name") == "🩺 資料狀態" for field in fields):
        fields.append({
            "name": "🩺 資料狀態",
            "value": source_status_text(source_status or infer_source_status(card)),
            "inline": False,
        })
    card["fields"] = fields

    footer = dict(card.get("footer") or {})
    footer_text = str(footer.get("text") or "").strip()
    additions = []
    if "台灣時間" not in footer_text:
        additions.append("台灣時間")
    if channel_key == "bot_log":
        if "系統紀錄" not in footer_text:
            additions.append("系統紀錄")
    elif "不構成投資建議" not in footer_text:
        additions.append("不構成投資建議")
    footer["text"] = "｜".join(part for part in (footer_text, *additions) if part)
    card["footer"] = footer
    card.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    return card


def standard_fields(
    *,
    summary: str,
    details: str,
    event_status: str,
    timing: str,
    source: str,
    source_status: str,
    source_detail: str | None = None,
    original_title: str | None = None,
    test: bool = False,
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = [
        {"name": "📌 繁中標題", "value": f"**{summary}**", "inline": False},
        {"name": "📝 繁中重點", "value": details, "inline": False},
    ]
    if original_title:
        fields.append({"name": "🌐 英文原標題", "value": original_title, "inline": False})
    fields.extend([
        {"name": "📍 數據／事件狀態", "value": event_status, "inline": False},
        {"name": "🕒 時間資訊（台灣）", "value": timing, "inline": False},
        {"name": "🔗 官方原始資料", "value": source, "inline": False},
        {
            "name": "🩺 資料狀態",
            "value": source_status_text(source_status, source_detail),
            "inline": False,
        },
    ])
    if test:
        fields.append({
            "name": "✅ 測試狀態",
            "value": "版面預覽成功｜未送往正式頻道",
            "inline": False,
        })
    return fields
