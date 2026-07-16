"""Free official-source US macro notifier for Discord (standard library only)."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from config import BLS_CALENDAR_URL, EVENT_RULES, MARKET_INTERPRETATIONS, OFFICIAL_FEEDS, PRE_ALERT_MINUTES, PRE_ALERT_WINDOW_MINUTES, TAIPEI_ZONE

STATE_FILE = Path(os.getenv("STATE_FILE", ".state/notified.json"))
NY = ZoneInfo("America/New_York")
TAIPEI = ZoneInfo(TAIPEI_ZONE)
BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_API_GROUPS = {
    "cpi": ("CUSR0000SA0", "CUUR0000SA0"),
    "ppi": ("WPSFD4", "WPUFD4"),
    "jobs": ("CES0000000001", "LNS14000000"),
}
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/calendar, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Referer": "https://www.bls.gov/",
}


def http_text(url: str, attempts: int = 3) -> str:
    """Read an official source with browser-like headers and bounded retries."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers=HTTP_HEADERS)
            with urlopen(request, timeout=30) as response:
                return response.read().decode(
                    response.headers.get_content_charset() or "utf-8", errors="replace"
                )
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def http_json_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": HTTP_HEADERS["User-Agent"]},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bls_api_releases(now: datetime, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Use the official BLS API as a release-feed fallback."""
    series_ids = [series_id for ids in BLS_API_GROUPS.values() for series_id in ids]
    response = http_json_post(
        BLS_API_URL,
        {"seriesid": series_ids, "startyear": str(now.year - 1), "endyear": str(now.year)},
    )
    if response.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("BLS API request failed: " + "; ".join(response.get("message", [])))

    series = {item["seriesID"]: item.get("data", []) for item in response["Results"]["series"]}
    observations = state.setdefault("bls_api", {})
    releases: list[dict[str, Any]] = []
    for event_key, ids in BLS_API_GROUPS.items():
        datasets = [series.get(series_id, []) for series_id in ids]
        latest = [values[0] for values in datasets if values]
        if len(latest) != len(datasets):
            continue
        reference = f"{latest[0]['year']}-{latest[0]['period']}"
        signature = hashlib.sha256(
            "|".join(f"{item['year']}:{item['period']}:{item['value']}" for item in latest).encode()
        ).hexdigest()[:20]
        previous = observations.get(event_key)
        observations[event_key] = {"reference": reference, "signature": signature}
        if previous is None or previous.get("signature") == signature:
            continue

        rule = next(rule for rule in EVENT_RULES if rule["key"] == event_key)
        if event_key in {"cpi", "ppi"}:
            monthly, annual = datasets
            monthly_change = (float(monthly[0]["value"]) / float(monthly[1]["value"]) - 1) * 100
            prior_year = next(
                (item for item in annual if item["period"] == annual[0]["period"]
                 and int(item["year"]) == int(annual[0]["year"]) - 1),
                None,
            )
            summary = f"The index changed {monthly_change:.1f} percent"
            if prior_year:
                annual_change = (float(annual[0]["value"]) / float(prior_year["value"]) - 1) * 100
                summary += f" and {annual_change:.1f} percent over the last 12 months"
            summary += "."
        else:
            payroll_change = float(datasets[0][0]["value"]) - float(datasets[0][1]["value"])
            summary = f"Payroll employment changed {payroll_change:+.0f} thousand; unemployment rate {latest[1]['value']} percent."
        releases.append({
            "id": f"bls-api-{event_key}-{reference}-{signature}",
            "title": rule["name"], "summary": summary, "url": rule["source"],
            "published": now, "rule": rule,
        })
    return releases


def classify(text: str) -> dict[str, Any] | None:
    value = text.lower()
    for rule in EVENT_RULES:
        if any(keyword in value for keyword in rule["keywords"]):
            return rule
    return None


def unfold_ics(source: str) -> list[str]:
    lines: list[str] = []
    for line in source.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def parse_ics_datetime(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=NY).astimezone(timezone.utc)


def parse_bls_calendar(source: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, str] | None = None
    for line in unfold_ics(source):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            summary = current.get("SUMMARY", "")
            rule = classify(summary)
            if rule and "DTSTART" in current:
                events.append({"id": current.get("UID", summary + current["DTSTART"]), "title": summary,
                               "time": parse_ics_datetime(current["DTSTART"]), "rule": rule})
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.split(";", 1)[0]] = value.replace("\\,", ",")
    return events


def element_text(node: ElementTree.Element | None) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape("".join(node.itertext()))).strip()


def parse_feed(source: str, base_url: str, provider: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(source)
    entries = root.findall(".//item")
    if not entries:
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    results = []
    for entry in entries[:20]:
        title = element_text(entry.find("title")) or element_text(entry.find("{http://www.w3.org/2005/Atom}title"))
        description = element_text(entry.find("description")) or element_text(entry.find("{http://www.w3.org/2005/Atom}summary"))
        rule = classify(f"{title} {description}")
        if not rule or (rule["key"] in {"powell", "fed_official"} and provider != "FED_SPEECH"):
            continue
        link_node = entry.find("link")
        if link_node is None:
            link_node = entry.find("{http://www.w3.org/2005/Atom}link")
        link = (link_node.get("href") if link_node is not None else None) or element_text(link_node)
        date_text = element_text(entry.find("pubDate")) or element_text(entry.find("{http://www.w3.org/2005/Atom}updated"))
        try:
            published = parsedate_to_datetime(date_text).astimezone(timezone.utc) if "," in date_text else datetime.fromisoformat(date_text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        identifier = hashlib.sha256(f"{provider}|{title}|{link}|{date_text}".encode()).hexdigest()[:24]
        results.append({"id": identifier, "title": title, "summary": description, "url": urljoin(base_url, link),
                        "published": published, "rule": rule})
    return results


def extract_numbers(summary: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", html.unescape(summary))
    matches = re.findall(r"(?:[-+]?\d[\d,.]*\s*(?:percent|%|thousand|million|billion))", clean, flags=re.I)
    return "、".join(matches[:4]) if matches else "請開啟官方公告查看完整數據"


def format_metrics(summary: str, event_key: str) -> str:
    """Add human-readable labels to values extracted from official summaries."""
    clean = re.sub(r"<[^>]+>", " ", html.unescape(summary))
    values = re.findall(r"[-+]?\d[\d,.]*\s*(?:percent|%)", clean, flags=re.I)
    values = [re.sub(r"\s*percent$", "%", value, flags=re.I) for value in values]
    if event_key in {"cpi", "ppi"} and len(values) >= 2:
        # BLS CPI/PPI summary convention lists the monthly change first and
        # the 12-month change second.
        return f"**月增率（MoM）**　{values[0]}\n**年增率（YoY）**　{values[1]}"
    if event_key == "gdp" and values:
        return f"**GDP 年化季增率**　{values[0]}"
    return extract_numbers(summary)


def send_discord(webhook: str, embed: dict[str, Any], dry_run: bool) -> None:
    payload = {"username": "美國總經通知", "embeds": [embed], "allowed_mentions": {"parse": []}}
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    data = json.dumps(payload).encode("utf-8")
    request = Request(webhook + ("&" if "?" in webhook else "?") + "wait=true", data=data,
                      headers={"Content-Type": "application/json", "User-Agent": "macro-discord-notifier/2.0"}, method="POST")
    with urlopen(request, timeout=30):
        pass


def pre_embed(event: dict[str, Any]) -> dict[str, Any]:
    local = event["time"].astimezone(TAIPEI)
    return {"author": {"name": "US MACRO WATCH｜美國總體經濟"},
            "title": f"⏰ 公布前提醒｜{event['rule']['name']}",
            "description": f"### 距離公布約 {PRE_ALERT_MINUTES} 分鐘\n請留意公布前後的價格波動、流動性與滑價風險。",
            "color": 0xF1C40F,
            "fields": [{"name": "🗓️ 公布日期", "value": local.strftime("%Y/%m/%d"), "inline": True},
                       {"name": "🕐 台灣時間", "value": local.strftime("%H:%M"), "inline": True},
                       {"name": "🔗 官方來源", "value": event["rule"]["source"], "inline": False}],
            "footer": {"text": "資料來源：官方網站｜僅供資訊參考，不構成投資建議"},
            "timestamp": datetime.now(timezone.utc).isoformat()}


def release_embed(item: dict[str, Any]) -> dict[str, Any]:
    local = item["published"].astimezone(TAIPEI)
    source = item["url"] or item["rule"]["source"]
    numbers = format_metrics(item["summary"], item["rule"]["key"])
    return {"author": {"name": "US MACRO WATCH｜美國總體經濟"},
            "title": f"🔴 最新公布｜{item['rule']['name']}",
            "description": f"### 📊 官方摘要重點\n**{numbers}**\n\n> 數值由官方摘要擷取，請以原始公告內容為準。",
            "color": 0xE74C3C,
            "fields": [{"name": "📌 事件類型", "value": item["rule"]["name"], "inline": True},
                       {"name": "🕐 台灣時間", "value": local.strftime("%Y/%m/%d %H:%M"), "inline": True},
                       {"name": "🧭 市場解讀參考", "value": MARKET_INTERPRETATIONS.get(item["rule"]["key"], "請綜合市場預期與官方完整內容判讀。"), "inline": False},
                       {"name": "🔗 官方原始資料", "value": source, "inline": False}],
            "footer": {"text": "官方免費資料｜不含市場預期值｜僅供資訊參考，不構成投資建議"},
            "timestamp": item["published"].isoformat()}


def daily_embed(events: list[dict[str, Any]], now: datetime, calendar_error: str | None = None) -> dict[str, Any]:
    local = now.astimezone(TAIPEI)
    today = [event for event in events if event["time"].astimezone(TAIPEI).date() == local.date()]
    lines = [f"`{event['time'].astimezone(TAIPEI):%H:%M}`　**{event['rule']['name']}**\n└ {event['rule']['source']}"
             for event in sorted(today, key=lambda event: event["time"])]
    description = "\n\n".join(lines) if lines else "✅ 今日暫無符合條件的最高重要度事件。"
    color = 0x3498DB
    if calendar_error:
        description = "⚠️ BLS 官方行事曆目前未完成同步，無法確認今日是否有重要事件。系統將於下次排程自動重試。"
        color = 0xF1C40F
    return {"author": {"name": "US MACRO WATCH｜每日行事曆"},
            "title": f"📅 今日重要事件｜{local:%Y/%m/%d}",
            "description": description,
            "color": color,
            "fields": [{"name": "🌏 時區", "value": "Asia/Taipei（台灣時間）", "inline": True}],
            "footer": {"text": "BLS 官方行事曆｜僅供資訊參考，不構成投資建議"},
            "timestamp": now.isoformat()}


def health_embed(title: str, description: str, color: int = 0xF1C40F) -> dict[str, Any]:
    return {"author": {"name": "US MACRO WATCH｜系統監控"},
            "title": title,
            "description": description[:3800],
            "color": color,
            "footer": {"text": "自動健康監控｜相同來源異常每日最多通知一次"},
            "timestamp": datetime.now(timezone.utc).isoformat()}


def source_health_embed(errors: list[str], recoveries: list[str]) -> dict[str, Any]:
    """Explain both failed primary sources and successful fallbacks."""
    lines = [*(f"⚠️ 主來源失敗：{error}" for error in errors)]
    lines.extend(f"✅ 備援成功：{recovery}" for recovery in recoveries)
    if any("BLS 官方 API" in recovery for recovery in recoveries):
        lines.append("ℹ️ BLS API 可補 CPI／PPI／就業數據，但不能完全取代發布行事曆。")
    if recoveries:
        return health_embed("🟡 部分來源異常｜備援正常", "\n".join(lines), 0xF1C40F)
    lines.append("❌ 目前沒有確認成功的對應備援；系統將於下次排程重試。")
    return health_embed("🔴 官方來源讀取失敗｜備援未確認", "\n".join(lines), 0xE74C3C)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sent": {}, "digests": []}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run(now: datetime, dry_run: bool = False, force_digest: bool = False) -> tuple[int, int]:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook and not dry_run:
        raise RuntimeError("缺少 DISCORD_WEBHOOK_URL")
    webhook = webhook or "https://discord.invalid/webhook"
    state = load_state()
    source_errors: list[str] = []
    source_recoveries: list[str] = []
    calendar_error: str | None = None
    try:
        calendar = parse_bls_calendar(http_text(BLS_CALENDAR_URL))
    except Exception as exc:
        # BLS occasionally rejects GitHub-hosted runners with HTTP 403.  A
        # temporary calendar outage must not stop release-feed notifications.
        print(f"警告：BLS 官方行事曆暫時無法讀取：{exc}", file=sys.stderr)
        source_errors.append(f"BLS 行事曆：{type(exc).__name__} / {exc}")
        calendar_error = str(exc)
        calendar = []
    releases: list[dict[str, Any]] = []
    for provider, url in OFFICIAL_FEEDS:
        try:
            releases.extend(parse_feed(http_text(url), url, provider))
        except Exception as exc:
            if provider == "BLS":
                try:
                    api_releases = fetch_bls_api_releases(now, state)
                    releases.extend(api_releases)
                    source_recoveries.append("BLS 官方 API 正常（CPI／PPI／就業數據）")
                    print(f"BLS RSS 無法讀取，官方 API 備援成功（{len(api_releases)} 筆更新）")
                    continue
                except Exception as api_exc:
                    source_errors.append(f"BLS API 備援：{type(api_exc).__name__} / {api_exc}")
            print(f"警告：{provider} 官方來源暫時無法讀取：{exc}", file=sys.stderr)
            source_errors.append(f"{provider}：{type(exc).__name__} / {exc}")
    sent = state.setdefault("sent", {})
    digests = state.setdefault("digests", [])
    health_alerts = state.setdefault("health_alerts", {})
    local = now.astimezone(TAIPEI)
    # Version the key when the health-message semantics change so the improved
    # status is emitted once even if an older-format alert was already sent.
    health_key = f"sources:v2:{local:%Y-%m-%d}"
    log_webhook = os.environ.get("DISCORD_LOG_WEBHOOK_URL")
    if source_errors and log_webhook and health_key not in health_alerts:
        try:
            send_discord(log_webhook, source_health_embed(source_errors, source_recoveries), dry_run)
            health_alerts[health_key] = local.date().isoformat()
        except Exception as exc:
            print(f"警告：健康監控通知無法送出：{exc}", file=sys.stderr)
    digest_key = local.strftime("%Y-%m-%d")
    if (force_digest or local.hour >= 7) and digest_key not in digests:
        send_discord(webhook, daily_embed(calendar, now, calendar_error), dry_run)
        digests.append(digest_key)
    for event in calendar:
        minutes = (event["time"] - now).total_seconds() / 60
        key = f"pre:{event['id']}"
        if 0 <= minutes - PRE_ALERT_MINUTES <= PRE_ALERT_WINDOW_MINUTES and key not in sent:
            send_discord(webhook, pre_embed(event), dry_run)
            sent[key] = now.date().isoformat()
    for item in releases:
        age = (now - item["published"]).total_seconds() / 60
        key = f"release:{item['id']}"
        if 0 <= age <= 240 and key not in sent:
            send_discord(webhook, release_embed(item), dry_run)
            sent[key] = now.date().isoformat()
    cutoff = (now - timedelta(days=45)).date().isoformat()
    state["sent"] = {key: date for key, date in sent.items() if date >= cutoff}
    state["digests"] = [date for date in digests if date >= cutoff]
    state["health_alerts"] = {key: date for key, date in health_alerts.items() if date >= cutoff}
    if not dry_run:
        save_state(state)
    return len(calendar), len(releases)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--digest", action="store_true")
    parser.add_argument("--test-notification", action="store_true")
    parser.add_argument("--source-check", action="store_true")
    args = parser.parse_args()
    try:
        if args.source_check:
            counts: dict[str, int] = {}
            try:
                counts["BLS_CALENDAR"] = len(parse_bls_calendar(http_text(BLS_CALENDAR_URL)))
            except Exception:
                counts["BLS_CALENDAR"] = -1
            for provider, url in OFFICIAL_FEEDS:
                try:
                    counts[provider] = len(parse_feed(http_text(url), url, provider))
                except Exception:
                    if provider != "BLS":
                        raise
                    fetch_bls_api_releases(datetime.now(timezone.utc), load_state())
                    counts["BLS_API_FALLBACK"] = len(BLS_API_GROUPS)
            print("官方來源檢查成功：" + ", ".join(f"{name}={count}" for name, count in counts.items()))
            return 0
        if args.test_notification:
            webhook = os.environ.get("DISCORD_TEST_WEBHOOK_URL")
            if not webhook:
                raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL；測試通知禁止改送正式頻道")
            now = datetime.now(timezone.utc)
            sample = {
                "published": now,
                "summary": "The Consumer Price Index increased 0.2 percent and 3.0 percent over the last 12 months.",
                "url": "https://www.bls.gov/cpi/",
                "rule": next(rule for rule in EVENT_RULES if rule["key"] == "cpi"),
            }
            embed = release_embed(sample)
            embed["title"] = "🧪 測試通知｜美國消費者物價指數（CPI）"
            embed["description"] = "### 📊 模擬官方摘要重點\n**年增率（YoY）**　3.0%\n**月增率（MoM）**　0.2%\n\n> 這是版面測試訊息，並非真實最新數據。"
            send_discord(webhook, embed, False)
            log_webhook = os.environ.get("DISCORD_LOG_WEBHOOK_URL")
            if log_webhook:
                send_discord(log_webhook, health_embed(
                    "✅ 健康監控測試成功",
                    "測試通知已成功執行，GitHub Actions、Discord Webhook 與通知程式皆可正常運作。",
                    0x2ECC71,
                ), False)
            print("完成：已送出 Discord 測試通知")
            return 0
        calendar_count, release_count = run(datetime.now(timezone.utc), args.dry_run, args.digest)
        print(f"完成：行事曆 {calendar_count} 筆，官方更新 {release_count} 筆")
        return 0
    except Exception as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
