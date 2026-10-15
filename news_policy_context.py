"""Source-only policy dates. No inference from publication time or translated text."""
import re
from datetime import date

MONTHS = {name: index for index, name in enumerate(
    ('january','february','march','april','may','june','july','august','september','october','november','december'), 1)}
DATE = r'(?:20\d{2}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2})'
SCOPE = {'russia': '俄羅斯', 'russian': '俄羅斯', 'united states': '美國', 'u.s.': '美國',
         'european union': '歐盟', 'united kingdom': '英國', 'hong kong': '香港',
         'singapore': '新加坡', 'japan': '日本', 'south korea': '南韓'}


def parse_date(value):
    try:
        if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', value):
            return date.fromisoformat(value)
        month, day, year = value.replace(',', '').lower().split()
        return date(int(year), MONTHS[month], int(day))
    except (ValueError, KeyError):
        return None


def policy_context(item):
    title, summary = str(item.get('title', '')), str(item.get('summary', ''))
    body = title + ' ' + summary
    if not re.search(r'\b(?:bans?|banned|prohibit\w*|restrictions?|new law|new rules?|legislation)\b', title, re.I):
        return None
    scope = next((label for term, label in SCOPE.items()
                  if re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', body, re.I)), None)
    matches = re.findall(r'\b(from|until|effective(?:\s+(?:on|from))?|takes? effect(?:\s+on)?|starting|beginning|by)\s+(' + DATE + ')', body, re.I)
    dates = {(cue.lower(), parsed) for cue, raw in matches if (parsed := parse_date(raw))}
    distinct = {value for _, value in dates}
    if len(distinct) > 1:
        return {'reason': '政策包含多個時程，尚未核對各日期用途', 'copy': '政策時程待核對。'}
    if not distinct:
        return {'reason': '政策生效或轉換日期尚未核對', 'copy': '原文未提供可核對的完整適用日期。'}
    if not scope:
        return {'reason': '政策適用地區尚未核對', 'copy': '原文適用地區待核對。'}
    value = next(iter(distinct))
    cue = next(cue for cue, _ in dates)
    label = '截止日期' if cue in {'until', 'by'} else '開始適用日期'
    attribution = '官方原文所述' if item.get('official') else '媒體原文所述'
    return {'reason': None, 'date': value.isoformat(), 'scope': scope,
            'copy': f'{attribution}｜{scope}｜{label}：{value:%Y/%m/%d}。報導發布時間與政策適用日期分開看，細節以原公告為準。'}
