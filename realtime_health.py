"""Heartbeat, delay detection, and daily execution health for realtime monitors."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from notification_format import apply_delivery_format

TAIPEI = ZoneInfo("Asia/Taipei")
STATE_FILE = Path(os.getenv("REALTIME_HEALTH_STATE_FILE", ".state/realtime-health.json"))
RESULTS_FILE = Path(os.getenv("REALTIME_RESULTS_FILE", ".state/realtime-results.txt"))
EXPECTED_INTERVAL_MINUTES = 5
DELAY_TOLERANCE_MINUTES = 10
GAP_ALERT_MINUTES = EXPECTED_INTERVAL_MINUTES + DELAY_TOLERANCE_MINUTES
DAILY_REPORT_HOUR = 7

MONITOR_LABELS = (
    "總經數據",
    "上幣通知",
    "交易所公告",
    "加密新聞",
    "市場風險",
    "衍生品",
    "市場分析",
    "市場摘要",
)


def load_state(path: Path = STATE_FILE) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any], path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_results(path: Path = RESULTS_FILE) -> dict[str, tuple[str, str]]:
    results: dict[str, tuple[str, str]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return results
    for line in lines:
        parts = line.split("|", 2)
        if len(parts) == 3:
            results[parts[0]] = (parts[1], parts[2])
    return results


def delay_embed(previous: datetime, now: datetime, gap_minutes: int) -> dict[str, Any]:
    previous_local = previous.astimezone(TAIPEI)
    now_local = now.astimezone(TAIPEI)
    return {
        "title": "🟠 即時監控排程間隔異常",
        "description": (
            f"前後兩次監控啟動相隔 **{gap_minutes} 分鐘**；"
            f"正常約 {EXPECTED_INTERVAL_MINUTES} 分鐘，已超過允許延遲 "
            f"{DELAY_TOLERANCE_MINUTES} 分鐘。\n\n"
            "本輪仍會執行所有監控，並使用加長回補視窗搜尋可能遺漏的內容。"
        ),
        "color": 0xE67E22,
        "fields": [
            {
                "name": "上次啟動（台灣）",
                "value": previous_local.strftime("%Y/%m/%d %H:%M"),
                "inline": True,
            },
            {
                "name": "本次啟動（台灣）",
                "value": now_local.strftime("%Y/%m/%d %H:%M"),
                "inline": True,
            },
            {
                "name": "自動回補範圍",
                "value": "總經 48 小時｜加密新聞 48 小時｜上幣公告 72 小時｜交易所公告依未讀 ID 回補",
                "inline": False,
            },
            {
                "name": "🩺 資料狀態",
                "value": "**⚠️ 排程間隔異常**\n本輪監控仍在執行，回補完成前不宣稱資料完整。",
                "inline": False,
            },
        ],
        "footer": {"text": "GitHub Actions 排程心跳｜系統將於下一輪繼續檢查"},
        "timestamp": now.isoformat(),
    }


def daily_health_embed(
    results: dict[str, tuple[str, str]],
    state: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    lines = []
    failures = 0
    skipped = 0
    for name in MONITOR_LABELS:
        status, detail = results.get(name, ("missing", "本輪沒有執行紀錄"))
        if status == "ok":
            icon, label = "✅", "執行成功"
        elif status == "skipped":
            icon, label = "⚪", "未設定／已略過"
            skipped += 1
        else:
            icon, label = "❌", "執行失敗或缺少紀錄"
            failures += 1
        lines.append(f"{icon} **{name}**｜{label}｜{detail}")

    gap = state.get("last_gap_minutes")
    gap_text = f"{gap} 分鐘" if isinstance(gap, int) else "首次建立基準"
    title = (
        f"🟡 每日掃描健康報告｜{failures} 個監控異常"
        if failures
        else f"🟡 每日掃描健康報告｜{skipped} 個監控未設定"
        if skipped
        else "🟢 每日掃描健康報告｜全部正常"
    )
    return {
        "title": title,
        "description": "\n".join(lines),
        "color": 0xF1C40F if failures else 0x2ECC71,
        "fields": [
            {"name": "最近排程間隔", "value": gap_text, "inline": True},
            {
                "name": "延遲判定",
                "value": f"間隔超過 {GAP_ALERT_MINUTES} 分鐘即警告",
                "inline": True,
            },
            {
                "name": "遺漏保障",
                "value": "各監控保留去重狀態；延遲恢復後會重新掃描回補視窗內的未讀項目。",
                "inline": False,
            },
            {
                "name": "🩺 資料狀態",
                "value": (
                    f"**⚠️ {failures} 個監控異常**\n請依上方逐項結果判讀。"
                    if failures
                    else f"**⚠️ {skipped} 個監控未設定**\n未執行項目不會被標示為正常。"
                    if skipped
                    else "**✅ 執行正常**\n八個監控本輪皆已完成。"
                ),
                "inline": False,
            },
        ],
        "footer": {"text": "每日一次｜顯示程式執行狀態，不把未執行誤報為來源正常"},
        "timestamp": now.isoformat(),
    }


def send_webhook(webhook: str, embed: dict[str, Any]) -> None:
    card = apply_delivery_format(embed, "bot_log")
    payload = {
        "username": "通知系統｜健康監控",
        "embeds": [card],
        "allowed_mentions": {"parse": []},
    }
    request = Request(
        webhook + ("&" if "?" in webhook else "?") + "wait=true",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "realtime-health/1.0"},
        method="POST",
    )
    with urlopen(request, timeout=20):
        pass


def begin(now: datetime, webhook: str | None = None, path: Path = STATE_FILE) -> int | None:
    state = load_state(path)
    previous = parse_time(state.get("last_started_at"))
    gap_minutes = None
    if previous:
        gap_minutes = max(0, round((now - previous).total_seconds() / 60))
        state["last_gap_minutes"] = gap_minutes
        if gap_minutes > GAP_ALERT_MINUTES and webhook:
            send_webhook(webhook, delay_embed(previous, now, gap_minutes))
            state["last_delay_alert_at"] = now.isoformat()
    state["last_started_at"] = now.isoformat()
    save_state(state, path)
    return gap_minutes


def finish(
    now: datetime,
    results: dict[str, tuple[str, str]],
    webhook: str | None = None,
    path: Path = STATE_FILE,
) -> bool:
    state = load_state(path)
    state["last_completed_at"] = now.isoformat()
    state["last_results"] = {
        name: {"status": status, "detail": detail}
        for name, (status, detail) in results.items()
    }
    local = now.astimezone(TAIPEI)
    today = local.date().isoformat()
    sent = False
    if local.hour >= DAILY_REPORT_HOUR and state.get("daily_report_date") != today and webhook:
        send_webhook(webhook, daily_health_embed(results, state, now))
        state["daily_report_date"] = today
        sent = True
    save_state(state, path)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--begin", action="store_true")
    mode.add_argument("--finish", action="store_true")
    mode.add_argument("--test-preview", action="store_true")
    parser.add_argument("--results-file", type=Path, default=RESULTS_FILE)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if args.test_preview:
        webhook = os.environ.get("DISCORD_TEST_WEBHOOK_URL")
        if not webhook:
            raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL；健康預覽不可改送正式頻道")
        sample = {name: ("ok", "測試執行成功") for name in MONITOR_LABELS}
        card = daily_health_embed(sample, {"last_gap_minutes": 5}, now)
        card["title"] = "🧪 測試｜" + card["title"]
        card["description"] = "以下為測試資料，不代表正式監控結果。\n\n" + card["description"]
        send_webhook(webhook, card)
        return

    webhook = os.environ.get("DISCORD_LOG_WEBHOOK_URL")
    try:
        if args.begin:
            begin(now, webhook)
        else:
            finish(now, read_results(args.results_file), webhook)
    except Exception as exc:
        # Health reporting must never prevent the production monitors from
        # running. The workflow log still exposes the failure for diagnosis.
        print(f"警告：即時監控健康報告失敗：{type(exc).__name__} / {exc}")


if __name__ == "__main__":
    main()
