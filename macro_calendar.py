"""Year-scoped official calendars; never call a wrong-year/empty page healthy."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from config import EVENT_RULES
from cpi_release import MONTH, MONTHS

NY = ZoneInfo('America/New_York')
CENSUS_URL = 'https://www.census.gov/economic-indicators/calendar-listview.html'
G17_URL = 'https://www.federalreserve.gov/releases/g17/default.htm'
# Results whose data month must match the official schedule row (2026-11-20).
SCHEDULE_REFERENCE_KEYS = {'retail'}


def census_reference(match):
    """Data month printed on the same Census schedule row, only when its text and code agree."""
    if not match['ref_month']:
        return None
    year, month = int(match['ref_year']), MONTHS[match['ref_month'].lower()]
    if (year, month) != (int(match['code_year']), int(match['code_month'])):
        return None
    return f'{year}-M{month:02d}'


def census_calendar(now, fetch, clean):
    year = now.astimezone(NY).year
    # A row reads: title, release date and time, data month, release code, data-month code.
    pattern = re.compile(
        r"(Advance Monthly Sales for Retail and Food Services|"
        r"Advance Report on Durable Goods--Manufacturers' Shipments, Inventories, and Orders) "
        r"([A-Z][a-z]+ \d{1,2}), (\d{4}) (\d{1,2}:\d{2}) (AM|PM)\b"
        r"(?: (?P<ref_month>(?i:" + MONTH + r")) (?P<ref_year>20\d{2}) A\d{12} A(?P<code_year>20\d{2})(?P<code_month>0[1-9]|1[0-2])\b)?")
    failures = []
    for url in (CENSUS_URL, CENSUS_URL.replace('.html', f'-{year}.html')):
        try:
            source = clean(fetch(url))
            rows = [m for m in pattern.finditer(source) if int(m[3]) == year]
            if not rows:
                raise ValueError(f'no {year} retail/durable events; wrong year or empty parser')
            events = []
            for m in rows:
                key = 'retail' if m[1].startswith('Advance Monthly') else 'durable'
                when = datetime.strptime(f'{m[2]} {year} {m[4]} {m[5]}', '%B %d %Y %I:%M %p').replace(tzinfo=NY).astimezone(timezone.utc)
                rule = dict(next(r for r in EVENT_RULES if r['key'] == key))
                event = {'id': f'census-{key}-{when.isoformat()}', 'title': m[1], 'time': when,
                         'rule': {**rule, 'source': url}, 'calendar_source': 'Census 官方排程'}
                reference = census_reference(m)
                if reference:
                    event['reference_period'] = reference
                events.append(event)
            return events, f'{year}年度｜{len(events)}個零售／耐久財事件｜' + ('年度頁備援' if failures else '預設頁年份已核對')
        except Exception as exc:
            failures.append(type(exc).__name__ + ': ' + str(exc))
    raise ValueError('; '.join(failures))


def industrial_calendar(now, fetch, clean):
    source = clean(fetch(G17_URL))
    # Monthly releases and annual revisions have different times; never mix them.
    clock = re.search(r'monthly releases are issued at (\d{1,2}):(\d{2})\s*a\.?m\.?', source, re.I)
    if not clock:
        raise ValueError('G.17 monthly release time missing')
    current = now.astimezone(NY).year
    events = []
    for year in (current, current + 1):
        block = re.search(rf'\b{year}:\s*(.*?)(?=\b20\d{{2}}:|Historical Release Dates|$)', source, re.I)
        if not block:
            if year == current:
                raise ValueError(f'G.17 {year} schedule missing')
            continue
        dates = list(re.finditer(r'([A-Z][a-z]+)\s+(\d{1,2})\b', block[1]))
        for i, m in enumerate(dates):
            suffix = block[1][m.end():dates[i+1].start() if i+1 < len(dates) else len(block[1])]
            if re.search('annual revision', suffix, re.I):
                continue
            when = datetime.strptime(f'{m[1]} {m[2]} {year}', '%B %d %Y').replace(
                hour=int(clock[1]), minute=int(clock[2]), tzinfo=NY).astimezone(timezone.utc)
            rule = dict(next(r for r in EVENT_RULES if r['key'] == 'industrial'))
            events.append({'id': f'fed-industrial-{when.isoformat()}', 'title': 'Industrial Production and Capacity Utilization',
                           'time': when, 'rule': {**rule, 'source': G17_URL}, 'calendar_source': 'Fed G.17 官方排程'})
        if year == current and not events:
            raise ValueError('G.17 current-year monthly dates empty')
    return events


def with_schedule_reference(item, calendar, window=timedelta(hours=12)):
    """Attach the data month from the official schedule row of this same release.

    Matches on the release's official publication time, not on when the bot
    noticed it, so a later backfill still compares with the right row.  Leaves
    the item unchanged unless exactly one data month is scheduled there; the
    result gate then blocks instead of inferring a month from the release date.
    """
    key = item.get('rule', {}).get('key')
    published = item.get('published')
    if key not in SCHEDULE_REFERENCE_KEYS or not published:
        return item
    found = {event['reference_period'] for event in calendar
             if event.get('rule', {}).get('key') == key and event.get('reference_period')
             and abs(event['time'] - published) <= window}
    return dict(item, scheduled_reference_period=found.pop()) if len(found) == 1 else item
