"""Shared presentation rules for Discord notification cards."""
from __future__ import annotations

import copy
import html
import json
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

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


def clean_source_text(value: str, limit: int = 900) -> str:
    """Turn source-provided HTML/text into a compact Discord-safe excerpt."""
    cleaned = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit].rstrip()


def english_key_points(value: str, limit: int = 3) -> list[str]:
    """Extract factual English bullets from source text without adding new claims."""
    cleaned = clean_source_text(value, 1800)
    if not cleaned:
        return []
    parts = [
        part.strip(" •-\t")
        for part in re.split(r"(?<=[.!?])\s+|[;\n]+", cleaned)
        if part.strip(" •-\t")
    ]
    if len(parts) == 1 and len(parts[0]) > 220:
        clauses = [part.strip(" ,") for part in parts[0].split(",") if len(part.strip()) >= 20]
        if len(clauses) >= 2:
            parts = clauses
    return [part[:320].rstrip() for part in parts[:limit]]


def bilingual_sections(
    *,
    original_title: str,
    english_summary: str | None,
    english_points: list[str] | tuple[str, ...] | str | None,
    zh_title: str,
    zh_points: list[str] | tuple[str, ...] | str,
) -> str:
    """Render the shared English-first, Traditional-Chinese-second layout."""
    source_summary = clean_source_text(english_summary or "")
    if isinstance(english_points, str):
        en_points = english_key_points(english_points)
    else:
        en_points = [clean_source_text(point, 320) for point in (english_points or [])]
        en_points = [point for point in en_points if point]
    if not en_points:
        en_points = english_key_points(source_summary)
    if not source_summary:
        source_summary = "The official source did not provide a separate English summary."
    if not en_points:
        en_points = ["Open the official source for the complete announcement details."]

    if isinstance(zh_points, str):
        zh_point_text = zh_points
    else:
        zh_point_text = "\n".join(f"• {point}" for point in zh_points if point)

    return (
        f"**🌐 英文原標題**\n{clean_source_text(original_title, 900)}\n\n"
        f"**📰 英文摘要**\n{source_summary}\n\n"
        f"**🔎 英文重點**\n" + "\n".join(f"• {point}" for point in en_points) +
        "\n\n\u200b\n\n"
        f"**📌 繁中標題**\n{zh_title}\n\n"
        f"**📝 繁中重點**\n{zh_point_text}"
    )


def infer_source_status(embed: dict[str, Any]) -> str:
    text = json.dumps(embed, ensure_ascii=False).lower()
    if any(marker in text for marker in (
        "所有來源失敗", "備援未確認", "沒有確認成功的對應備援", "來源暫時無法確認",
    )):
        return "error"
    if any(marker in text for marker in (
        "使用備援", "備援來源", "備援成功", "備援正常", "fallback",
    )):
        return "backup"
    if any(marker in text for marker in (
        "暫時無法取得", "httperror", "來源讀取異常",
    )):
        return "error"
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
    sent_at = datetime.now(timezone.utc).astimezone(TAIPEI)
    if "機器人送出：" not in footer_text:
        additions.append(f"機器人送出：{sent_at:%Y/%m/%d %H:%M}")
    footer["text"] = "｜".join(part for part in (footer_text, *additions) if part)
    card["footer"] = footer
    card.setdefault("timestamp", sent_at.astimezone(timezone.utc).isoformat())
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
    english_summary: str | None = None,
    english_points: list[str] | tuple[str, ...] | str | None = None,
    test: bool = False,
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    if original_title:
        source_summary = clean_source_text(english_summary or "")
        points = english_key_points(english_points if isinstance(english_points, str) else source_summary)
        if not isinstance(english_points, str) and english_points:
            points = [clean_source_text(point, 320) for point in english_points if clean_source_text(point, 320)]
        fields.extend([
            {"name": "🌐 英文原標題", "value": original_title, "inline": False},
            {
                "name": "📰 英文摘要",
                "value": source_summary or "The official source did not provide a separate English summary.",
                "inline": False,
            },
            {
                "name": "🔎 英文重點",
                "value": "\n".join(f"• {point}" for point in points)
                or "• Open the official source for the complete announcement details.",
                "inline": False,
            },
            {"name": "\u200b", "value": "\u200b", "inline": False},
        ])
    fields.extend([
        {"name": "📌 繁中標題", "value": f"**{summary}**", "inline": False},
        {"name": "📝 繁中重點", "value": details, "inline": False},
    ])
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
