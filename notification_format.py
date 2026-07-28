"""Shared presentation rules for Discord notification cards."""
from __future__ import annotations

from typing import Any

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
