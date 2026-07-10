"""Free official-source US macro notifier for Discord (standard library only)."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from config import BLS_CALENDAR_URL, EVENT_RULES, OFFICIAL_FEEDS, PRE_ALERT_MINUTES, PRE_ALERT_WINDOW_MINUTES, TAIPEI_ZONE

STATE_FILE = Path(os.getenv("STATE_FILE", ".state/notified.json"))
NY = ZoneInfo("America/New_York")
TAIPEI = ZoneInfo(TAIPEI_ZONE)


def http_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "macro-discord-notifier/2.0 (official sources)"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


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
        if not rule or (rule["key"] == "powell" and provider != "FED_SPEECH"):
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
    return {"title": f"⏰ {event['rule']['name']} 將於約 {PRE_ALERT_MINUTES} 分鐘後公布",
            "description": "請留意公布前後的價格波動與流動性變化。",
            "color": 0xF1C40F,
            "fields": [{"name": "台灣時間", "value": local.strftime("%Y/%m/%d %H:%M"), "inline": True},
                       {"name": "資料來源", "value": event["rule"]["source"], "inline": False}],
            "footer": {"text": "官方免費資料｜不構成投資建議"}}


def release_embed(item: dict[str, Any]) -> dict[str, Any]:
    local = item["published"].astimezone(TAIPEI)
    source = item["url"] or item["rule"]["source"]
    return {"title": f"🔴 {item['rule']['name']}已有官方更新",
            "description": f"**官方摘要中的主要數值**\n{extract_numbers(item['summary'])}\n\n請以原始公告內容為準。",
            "color": 0xE74C3C,
            "fields": [{"name": "發布時間", "value": local.strftime("%Y/%m/%d %H:%M（台灣時間）"), "inline": True},
                       {"name": "資料來源", "value": source, "inline": False}],
            "footer": {"text": "官方免費資料｜不含市場共識預期值｜不構成投資建議"}}


def daily_embed(events: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    local = now.astimezone(TAIPEI)
    today = [event for event in events if event["time"].astimezone(TAIPEI).date() == local.date()]
    lines = [f"**{event['time'].astimezone(TAIPEI):%H:%M}**　{event['rule']['name']} ⭐⭐⭐⭐⭐\n{event['rule']['source']}"
             for event in sorted(today, key=lambda event: event["time"])]
    return {"title": f"📅 {local:%Y/%m/%d} 今日重要美國經濟事件",
            "description": "\n\n".join(lines) if lines else "BLS 今日沒有符合條件的最高重要度事件。",
            "color": 0x3498DB,
            "footer": {"text": "Asia/Taipei｜BLS 官方行事曆"}}


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
    try:
        calendar = parse_bls_calendar(http_text(BLS_CALENDAR_URL))
    except Exception as exc:
        # BLS occasionally rejects GitHub-hosted runners with HTTP 403.  A
        # temporary calendar outage must not stop release-feed notifications.
        print(f"警告：BLS 官方行事曆暫時無法讀取：{exc}", file=sys.stderr)
        calendar = []
    releases: list[dict[str, Any]] = []
    for provider, url in OFFICIAL_FEEDS:
        try:
            releases.extend(parse_feed(http_text(url), url, provider))
        except Exception as exc:
            print(f"警告：{provider} 官方來源暫時無法讀取：{exc}", file=sys.stderr)
    state = load_state()
    sent = state.setdefault("sent", {})
    digests = state.setdefault("digests", [])
    local = now.astimezone(TAIPEI)
    digest_key = local.strftime("%Y-%m-%d")
    if (force_digest or local.hour >= 7) and digest_key not in digests:
        send_discord(webhook, daily_embed(calendar, now), dry_run)
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
    if not dry_run:
        save_state(state)
    return len(calendar), len(releases)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--digest", action="store_true")
    args = parser.parse_args()
    try:
        calendar_count, release_count = run(datetime.now(timezone.utc), args.dry_run, args.digest)
        print(f"完成：行事曆 {calendar_count} 筆，官方更新 {release_count} 筆")
        return 0
    except Exception as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
