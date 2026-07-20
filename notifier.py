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

from config import BLS_CALENDAR_URL, DAY_BEFORE_MINUTES, EVENT_RULES, MARKET_INTERPRETATIONS, OFFICIAL_FEEDS, PRE_ALERT_MINUTES, PRE_ALERT_WINDOW_MINUTES, TAIPEI_ZONE

STATE_FILE = Path(os.getenv("STATE_FILE", ".state/notified.json"))
NY = ZoneInfo("America/New_York")
TAIPEI = ZoneInfo(TAIPEI_ZONE)
BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_API_GROUPS = {
    "cpi": ("CUSR0000SA0", "CUUR0000SA0"),
    "ppi": ("WPSFD4", "WPUFD4"),
    "jobs": ("CES0000000001", "LNS14000000"),
    "jolts": ("JTS000000000000000JOL",),
}
PUBLIC_CALENDARS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
)
OFFICIAL_PAGE_RELEASES = (
    ("claims", "DOL", "https://oui.doleta.gov/unemploy/DataDashboard.asp", "seasonally adjusted initial claims"),
    ("retail", "CENSUS", "https://www.census.gov/retail/sales.html", "advance monthly sales for retail and food services"),
    ("durable", "CENSUS", "https://www.census.gov/manufacturing/m3/adv/current/index.html", "monthly advance report on durable goods"),
)
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


def http_json_get(url: str) -> Any:
    return json.loads(http_text(url))


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
        elif event_key == "jobs":
            payroll_change = float(datasets[0][0]["value"]) - float(datasets[0][1]["value"])
            summary = f"Payroll employment changed {payroll_change:+.0f} thousand; unemployment rate {latest[1]['value']} percent."
        else:
            current = float(datasets[0][0]["value"])
            previous_value = float(datasets[0][1]["value"]) if len(datasets[0]) > 1 else current
            summary = f"Job openings were {current / 1000:.1f} million; previous value {previous_value / 1000:.1f} million."
        releases.append({
            "id": f"bls-api-{event_key}-{reference}-{signature}",
            "title": rule["name"], "summary": summary, "url": rule["source"],
            "published": now, "rule": rule,
        })
    return releases


def html_to_text(source: str) -> str:
    source = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", source)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", source))).strip()


def fetch_official_page_releases(now: datetime, state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Detect updates on official pages that do not provide a dependable RSS feed."""
    saved = state.setdefault("official_pages", {})
    releases, ok, errors = [], [], []
    for event_key, provider, url, marker in OFFICIAL_PAGE_RELEASES:
        try:
            text = html_to_text(http_text(url))
            index = text.lower().find(marker)
            if index < 0:
                raise ValueError(f"missing marker: {marker}")
            excerpt = text[index:index + 2200]
            signature = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()[:20]
            previous = saved.get(event_key)
            saved[event_key] = signature
            ok.append(f"{provider} {next(r['name'] for r in EVENT_RULES if r['key'] == event_key)}")
            if previous and previous != signature:
                rule = next(rule for rule in EVENT_RULES if rule["key"] == event_key)
                releases.append({"id": f"page-{event_key}-{signature}", "title": rule["name"],
                                 "summary": excerpt, "url": url, "published": now, "rule": rule})
        except Exception as exc:
            errors.append(f"{provider} {event_key}：{type(exc).__name__} / {exc}")
    return releases, ok, errors


def fetch_public_calendar() -> tuple[list[dict[str, Any]], bool]:
    events, succeeded = [], False
    aliases = {
        "core pce": "personal consumption expenditures", "pce price": "personal consumption expenditures",
        "jobless claims": "initial jobless claims", "unemployment claims": "initial jobless claims", "jolts": "jolts",
        "retail sales": "retail sales", "durable goods": "durable goods",
        "non-farm": "employment situation", "unemployment rate": "employment situation",
        "advance gdp": "gross domestic product", "fomc": "monetary policy statement fomc",
    }
    for url in PUBLIC_CALENDARS:
        try:
            payload = http_json_get(url)
            succeeded = True
        except Exception:
            continue
        for item in payload if isinstance(payload, list) else []:
            if str(item.get("country", "")).upper() != "USD":
                continue
            title = str(item.get("title", ""))
            lower = title.lower()
            if "fomc" in lower and any(word in lower for word in ("speaks", "speech", "member")):
                expanded = title + " governor speech"
            else:
                expanded = title + " " + " ".join(value for key, value in aliases.items() if key in lower)
            rule = classify(expanded)
            if not rule:
                continue
            try:
                event_time = datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00"))
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=NY)
            except (KeyError, ValueError):
                continue
            events.append({"id": hashlib.sha256(f"{title}|{event_time.isoformat()}".encode()).hexdigest(),
                           "title": title, "time": event_time.astimezone(timezone.utc), "rule": rule,
                           "calendar_source": "公開行事曆輔助"})
    return events, succeeded


def merge_calendar_events(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged, seen = [], set()
    for event in sorted((item for group in groups for item in group), key=lambda item: item["time"]):
        key = (event["rule"]["key"], event["time"].replace(second=0, microsecond=0))
        if key not in seen:
            seen.add(key)
            merged.append(event)
    return merged


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
    if event_key == "pce" and values:
        labels = ("PCE 月增率", "核心 PCE 月增率", "PCE 年增率", "核心 PCE 年增率")
        return "\n".join(f"**{label}**　{value}" for label, value in zip(labels, values[:4]))
    if event_key == "jolts":
        amounts = re.findall(r"\d[\d,.]*\s*(?:million|thousand)", clean, flags=re.I)
        labels = ("職位空缺", "前值／聘僱", "離職／其他")
        return "\n".join(f"**{label}**　{value}" for label, value in zip(labels, amounts[:3])) or extract_numbers(summary)
    if event_key == "claims":
        claims = re.search(r"initial claims was ([\d,]+)", clean, re.I)
        previous = re.search(r"previous week(?:'s)?(?: revised)? level.*?([\d,]+)", clean, re.I)
        lines = [f"**初領失業金**　{claims.group(1)}" if claims else ""]
        if previous:
            lines.append(f"**前週／修正值**　{previous.group(1)}")
        return "\n".join(line for line in lines if line) or extract_numbers(summary)
    if event_key in {"retail", "durable"} and values:
        label = "零售銷售月增率" if event_key == "retail" else "耐久財訂單月增率"
        lines = [f"**{label}**　{values[0]}"]
        if len(values) > 1:
            lines.append(f"**前期數值**　{values[1]}")
        return "\n".join(lines)
    return extract_numbers(summary)


def revision_lines(summary: str) -> str | None:
    clean = re.sub(r"\s+", " ", html_to_text(summary))
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    revisions = [sentence for sentence in sentences if re.search(r"revis(?:ed|ion)", sentence, re.I)]
    if not revisions:
        return None
    return "\n".join(f"• {sentence[:300]}" for sentence in revisions[:2])


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


def pre_embed(event: dict[str, Any], day_before: bool = False) -> dict[str, Any]:
    local = event["time"].astimezone(TAIPEI)
    title = "📆 明日重要事件提醒" if day_before else "⏰ 公布前提醒"
    description = ("明日將公布最高重要度總經數據，請提前準備波動與風險管理。" if day_before
                   else f"距離公布約 {PRE_ALERT_MINUTES} 分鐘\n請留意公布前後的價格波動、流動性與滑價風險。")
    return {"author": {"name": "US MACRO WATCH｜美國總體經濟"},
            "title": f"{title}｜{event['rule']['name']}",
            "description": f"### {description}",
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
    fields = [{"name": "📌 事件類型", "value": item["rule"]["name"], "inline": True},
              {"name": "🕐 台灣時間", "value": local.strftime("%Y/%m/%d %H:%M"), "inline": True},
              {"name": "🧭 市場解讀參考", "value": MARKET_INTERPRETATIONS.get(item["rule"]["key"], "請綜合市場預期與官方完整內容判讀。"), "inline": False}]
    revisions = revision_lines(item["summary"])
    if revisions:
        fields.append({"name": "🔄 前值與修正資訊", "value": revisions, "inline": False})
    fields.append({"name": "🔗 官方原始資料", "value": source, "inline": False})
    return {"author": {"name": "US MACRO WATCH｜美國總體經濟"},
            "title": f"🔴 最新公布｜{item['rule']['name']}",
            "description": f"### 📊 官方摘要重點\n**{numbers}**\n\n> 數值由官方摘要擷取，請以原始公告內容為準。",
            "color": 0xE74C3C,
            "fields": fields,
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


def full_source_health_embed(statuses: list[tuple[str, str, bool]]) -> dict[str, Any]:
    """Render the once-daily report, including sources that are healthy."""
    failures = sum(not healthy for _, _, healthy in statuses)
    lines = [f"{'✅' if healthy else '❌'} **{name}**：{detail}" for name, detail, healthy in statuses]
    title = f"🟡 每日來源健康狀態｜{failures} 個來源異常" if failures else "🟢 每日來源健康狀態｜全部正常"
    lines.append("\n註：輔助行事曆只補足提醒時間；正式數據與原文連結仍以政府官方來源為準。")
    return health_embed(title, "\n".join(lines), 0xF1C40F if failures else 0x2ECC71)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sent": {}, "digests": []}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def legacy_run(now: datetime, dry_run: bool = False, force_digest: bool = False) -> tuple[int, int]:
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


def run(now: datetime, dry_run: bool = False, force_digest: bool = False) -> tuple[int, int]:
    """Complete macro radar pipeline with redundant calendars and full health reporting."""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook and not dry_run:
        raise RuntimeError("缺少 DISCORD_WEBHOOK_URL")
    webhook = webhook or "https://discord.invalid/webhook"
    state = load_state()
    errors: list[str] = []
    recoveries: list[str] = []
    statuses: list[tuple[str, str, bool]] = []

    try:
        official_calendar = parse_bls_calendar(http_text(BLS_CALENDAR_URL))
        statuses.append(("BLS 官方行事曆", f"正常，{len(official_calendar)} 個追蹤事件", True))
    except Exception as exc:
        official_calendar = []
        errors.append(f"BLS 行事曆：{type(exc).__name__} / {exc}")
        statuses.append(("BLS 官方行事曆", f"{type(exc).__name__} / {exc}", False))
    auxiliary_calendar, auxiliary_ok = fetch_public_calendar()
    statuses.append(("輔助經濟行事曆", f"正常，{len(auxiliary_calendar)} 個追蹤事件" if auxiliary_ok else "所有端點皆無法讀取", auxiliary_ok))
    calendar = merge_calendar_events(official_calendar, auxiliary_calendar)
    calendar_error = None if calendar else "官方與輔助行事曆皆無法讀取"

    releases: list[dict[str, Any]] = []
    for provider, url in OFFICIAL_FEEDS:
        try:
            parsed = parse_feed(http_text(url), url, provider)
            releases.extend(parsed)
            statuses.append((f"{provider} 官方動態", f"正常，讀取 {len(parsed)} 筆", True))
            if provider == "BLS":
                statuses.append(("BLS API 備援", "待命，本次無須啟用", True))
        except Exception as exc:
            errors.append(f"{provider}：{type(exc).__name__} / {exc}")
            statuses.append((f"{provider} 官方動態", f"{type(exc).__name__} / {exc}", False))
            if provider == "BLS":
                try:
                    fallback = fetch_bls_api_releases(now, state)
                    releases.extend(fallback)
                    recoveries.append("BLS 官方 API 備援成功，可取得 CPI、PPI、就業與 JOLTS 數據")
                    statuses.append(("BLS API 備援", f"正常，{len(fallback)} 筆候選更新", True))
                except Exception as api_exc:
                    errors.append(f"BLS API 備援：{type(api_exc).__name__} / {api_exc}")
                    statuses.append(("BLS API 備援", f"{type(api_exc).__name__} / {api_exc}", False))

    page_releases, healthy_pages, page_errors = fetch_official_page_releases(now, state)
    releases.extend(page_releases)
    statuses.extend((label, "官方頁面正常", True) for label in healthy_pages)
    for error in page_errors:
        errors.append(error)
        statuses.append((error.split("：", 1)[0], error.split("：", 1)[-1], False))

    sent = state.setdefault("sent", {})
    digests = state.setdefault("digests", [])
    health_alerts = state.setdefault("health_alerts", {})
    daily_health = state.setdefault("daily_health", [])
    local = now.astimezone(TAIPEI)
    log_webhook = os.environ.get("DISCORD_LOG_WEBHOOK_URL")
    health_key = f"sources:v3:{local:%Y-%m-%d}"
    if errors and log_webhook and health_key not in health_alerts:
        send_discord(log_webhook, source_health_embed(errors, recoveries), dry_run)
        health_alerts[health_key] = local.date().isoformat()
    digest_key = local.strftime("%Y-%m-%d")
    if (force_digest or local.hour >= 7) and log_webhook and digest_key not in daily_health:
        send_discord(log_webhook, full_source_health_embed(statuses), dry_run)
        daily_health.append(digest_key)
    if (force_digest or local.hour >= 7) and digest_key not in digests:
        send_discord(webhook, daily_embed(calendar, now, calendar_error), dry_run)
        digests.append(digest_key)

    for event in calendar:
        minutes = (event["time"] - now).total_seconds() / 60
        day_key = f"day-before:{event['id']}"
        if (event["rule"].get("priority") == "highest"
                and 0 <= minutes - DAY_BEFORE_MINUTES <= PRE_ALERT_WINDOW_MINUTES
                and day_key not in sent):
            send_discord(webhook, pre_embed(event, day_before=True), dry_run)
            sent[day_key] = now.date().isoformat()
        pre_key = f"pre:{event['id']}"
        if 0 <= minutes - PRE_ALERT_MINUTES <= PRE_ALERT_WINDOW_MINUTES and pre_key not in sent:
            send_discord(webhook, pre_embed(event), dry_run)
            sent[pre_key] = now.date().isoformat()
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
    state["daily_health"] = [date for date in daily_health if date >= cutoff]
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
                    counts[provider] = -1
                    if provider == "BLS":
                        fetch_bls_api_releases(datetime.now(timezone.utc), load_state())
                        counts["BLS_API_FALLBACK"] = len(BLS_API_GROUPS)
            auxiliary, auxiliary_ok = fetch_public_calendar()
            counts["AUXILIARY_CALENDAR"] = len(auxiliary) if auxiliary_ok else -1
            _, healthy_pages, page_errors = fetch_official_page_releases(datetime.now(timezone.utc), load_state())
            counts["OFFICIAL_PAGES"] = len(healthy_pages) if not page_errors else -len(page_errors)
            print("官方來源檢查成功：" + ", ".join(f"{name}={count}" for name, count in counts.items()))
            return 0
        if args.test_notification:
            webhook = os.environ.get("DISCORD_TEST_WEBHOOK_URL")
            if not webhook:
                raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL；測試通知禁止改送正式頻道")
            now = datetime.now(timezone.utc)
            sample = {
                "published": now,
                "summary": "PCE prices increased 0.2 percent; core PCE increased 0.3 percent. The prior value was revised from 0.1 percent to 0.2 percent.",
                "url": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
                "rule": next(rule for rule in EVENT_RULES if rule["key"] == "pce"),
            }
            embed = release_embed(sample)
            embed["title"] = "🧪 總經雷達 v2 測試｜PCE／核心 PCE"
            embed["description"] = "### 📊 模擬官方摘要重點\n**PCE 月增率**　0.2%\n**核心 PCE 月增率**　0.3%\n\n> 這是版面與功能測試，並非真實最新數據。新版另含初領失業金、JOLTS、零售銷售、耐久財、前一天提醒與前值／修正資訊。"
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
