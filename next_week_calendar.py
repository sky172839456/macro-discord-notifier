"""週日下週行事曆（2026-11-15 本人確認規格）。

- 每週日台灣 20:00 後，在🏦｜數據有話說發一則，列下週（週一～週日）本群追蹤的數據與官員談話時間。
- 一週只發一次；行事曆來源沒確認時不發空卡，下一輪再試（最晚到週日 23:59）。
- 週一週報的「本週要注意什麼」改成一句指向這則（見 market_brief_v2.build_card）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Taipei')
WEEKDAYS = '一二三四五六日'


def target_week(now):
    """週日晚上要預告的那一週（下週一所在的 ISO 週）與起訖時間。"""
    local = now.astimezone(TZ)
    monday = (local + timedelta(days=7 - local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return f'{monday:%G-W%V}', monday, monday + timedelta(days=7)


def due(state, now):
    local = now.astimezone(TZ)
    week, _, _ = target_week(now)
    return local.weekday() == 6 and local.hour >= 20 and state.get('next_week_calendar') != week


def build_card(now, events, event_error=None):
    week, start, end = target_week(now)
    rows = sorted((e for e in events if start <= e['time'].astimezone(TZ) < end), key=lambda e: e['time'])
    days = []
    current = None
    for e in rows:
        local = e['time'].astimezone(TZ)
        if local.date() != current:
            current = local.date()
            days.append(f'**{local:%m/%d}（週{WEEKDAYS[local.weekday()]}）**')
        days.append(f'{local:%H:%M}｜{e["rule"]["name"]}')
    body = '\n'.join(days) if days else '下週沒有本群追蹤的重要數據或官員談話。'
    if event_error:
        body += '\n⚠️ 行事曆尚未完整確認；未列出不代表沒有事件。'
    last = end - timedelta(days=1)
    return {
        'title': f'【下週行事曆】 🗓️ {start:%m/%d}～{last:%m/%d}',
        'description': body + '\n\n-# 台灣時間｜本群追蹤項目，非全球全部經濟數據；排程可能異動，以官方公告為準。每天 07:00 也會列當日行程。',
        'fields': [],
        'footer': {'text': '台灣時間｜不構成投資建議'},
        'timestamp': now.isoformat(),
    }, week


def check(state, now, fetch_events, send, persist):
    if not due(state, now):
        return False
    events, event_error = fetch_events()
    if event_error and not events:
        return False  # 來源沒確認，不發空卡；下一輪再試。
    card, week = build_card(now, events, event_error)
    state['next_week_calendar'] = week
    persist()
    send(card)
    return True
