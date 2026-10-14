"""Verify chair-policy reminders against the current official roster and agenda."""
import hashlib
import html
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROSTER_URL = 'https://www.federalreserve.gov/monetarypolicy/fomc.htm'
NY = ZoneInfo('America/New_York')
TOPICS = (
    (r'monetary policy|policy outlook', '貨幣政策'),
    (r'economic outlook|u\.s\. economy|economic conditions', '經濟展望'),
    (r'inflation|price stability', '通膨與物價'),
    (r'interest rates?', '利率政策'),
    (r'employment|labor market', '就業與勞動市場'),
    (r'press conference', '利率決議記者會'),
    (r'congress|testimony', '國會證詞'),
    (r'jackson hole', '傑克森洞政策演說'),
)
ROUTINE = r'opening remarks|welcoming remarks|welcome address|commencement|greetings'


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', value))).strip()


def parse_chair(source, year):
    block = re.search(rf'<h4[^>]*>\s*{year} Committee Members\s*</h4>\s*<ul[^>]*>(.*?)</ul>', source, re.S | re.I)
    if not block:
        raise ValueError('official current-year roster missing')
    chairs = []
    for row in re.findall(r'<li[^>]*>(.*?)</li>', block[1], re.S | re.I):
        if re.search(r',\s*Board of Governors,\s*Chairman\s*$', clean(row), re.I):
            name = re.search(r'<a\b[^>]*>(.*?)</a>', row, re.S | re.I)
            if name:
                chairs.append(clean(name[1]))
    if len(chairs) != 1:
        raise ValueError('official chair ambiguous')
    return chairs[0]


def parse_agenda(source, year, month, chair):
    """Keep the official wall clock; match it to an offset-aware calendar event."""
    rows = []
    pattern = r'<div class="col-xs-2">\s*(<p>.*?</p>)\s*</div>\s*<div class="col-xs-7">(.*?)</div>\s*<div class="col-xs-3">(.*?)</div>'
    for cells in re.findall(pattern, source, re.S | re.I):
        time_text, content, day = clean(cells[0]), cells[1], clean(cells[2])
        clock = re.fullmatch(r'(\d{1,2}):(\d{2})\s*([ap])\.m\.', time_text, re.I)
        if not clock or not day.isdigit():
            continue
        text = clean(content)
        identity = re.search(r'(?:Speech|Discussion|Testimony)\s*-\s*(Chairman|Chair|Vice Chair for Supervision|Vice Chair|Governor)\s+([^<]+)</p>', content, re.I)
        topic = re.search(r'<p class=[\'\"]calendar__title[\'\"][^>]*>(.*?)</p>', content, re.S | re.I)
        if identity:
            role, speaker = identity[1], clean(identity[2])
            subject = clean(topic[1]) if topic else ''
        elif 'FOMC Press Conference' in text:
            role, speaker, subject = 'Chairman', chair, 'FOMC Press Conference'
        else:
            continue
        hour = int(clock[1]) % 12 + (12 if clock[3].lower() == 'p' else 0)
        wall = datetime(year, month, int(day), hour, int(clock[2]))
        rows.append({'speaker': speaker, 'role': role, 'topic': subject, 'wall': wall})
    return rows


def policy_topic(topic):
    if re.search(ROUTINE, topic, re.I):
        return None
    return next((label for pattern, label in TOPICS if re.search(pattern, topic, re.I)), None)


def enrich(events, state, now, fetch):
    candidates = [e for e in events if e['rule']['key'] in {'powell', 'fed_official'}
                  and now <= e['time'] < now + timedelta(days=8)]
    if not candidates:
        return events, []
    cache = state.setdefault('fed_policy_sources', {})
    statuses = []

    def read(url):
        old = cache.get(url)
        if old and 0 <= (now - datetime.fromisoformat(old['checked'])).total_seconds() < 3600:
            return old['html']
        source = fetch(url, attempts=1)
        # Cache only the relevant sections, never script/navigation content.
        if url == ROSTER_URL:
            match = re.search(r'<h4[^>]*>\s*\d{4} Committee Members.*?</ul>', source, re.S | re.I)
        else:
            match = re.search(r'<h4[^>]*>Speeches</h4>(.*?)(?:<h4[^>]*>Beige Book</h4>|<h4[^>]*>Statistical Releases</h4>)', source, re.S | re.I)
        if not match:
            raise ValueError('official policy section missing')
        cache[url] = {'checked': now.isoformat(), 'html': match[0]}
        return match[0]

    try:
        chair = parse_chair(read(ROSTER_URL), now.astimezone(NY).year)
        agendas = {}
        for year, month in sorted({(e['time'].astimezone(NY).year, e['time'].astimezone(NY).month) for e in candidates}):
            month_name = datetime(year, month, 1).strftime('%B').lower()
            url = f'https://www.federalreserve.gov/newsevents/{year}-{month_name}.htm'
            agendas[(year, month)] = (url, parse_agenda(read(url), year, month, chair))
        result = []
        for event in events:
            if event not in candidates:
                result.append(event)
                continue
            wall = event['time'].astimezone(NY).replace(tzinfo=None, second=0, microsecond=0)
            url, agenda = agendas[(wall.year, wall.month)]
            matches = [r for r in agenda if r['wall'] == wall and r['speaker'] == chair
                       and r['role'] in {'Chair', 'Chairman'}
                       and re.search(rf'\b{re.escape(chair.split()[-1])}\b|press conference', event.get('title', ''), re.I)]
            if len(matches) != 1 or not policy_topic(matches[0]['topic']):
                result.append(event)  # unchanged rows remain excluded by slim_policy
                continue
            row = matches[0]
            label = policy_topic(row['topic'])
            result.append({**event, 'id': 'fed-chair-' + hashlib.sha256(f'{chair}|{event["time"].isoformat()}|{row["topic"]}'.encode()).hexdigest()[:20],
                           'speaker': chair, 'speaker_role': '聯準會主席', 'topic': label,
                           'official_speech': True,
                           'rule': {'key': 'fed_chair_policy', 'name': f'聯準會主席 {chair}｜{label}', 'source': url}})
        statuses.append(('聯準會主席與談話議程', '官方姓名、職位、主題及時間交叉核對完成', True))
        # Bound cached agenda history while retaining the current roster.
        for url in list(cache):
            if (now - datetime.fromisoformat(cache[url]['checked'])).total_seconds() > 2 * 86400:
                del cache[url]
        return result, statuses
    except Exception as exc:
        statuses.append(('聯準會主席與談話議程', f'{type(exc).__name__}；未確認的官員活動不推播', False))
        return events, statuses
