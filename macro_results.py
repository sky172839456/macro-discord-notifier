"""Headline retail metrics anchored to their period and basis, not number order."""
import html
import re
from cpi_release import MONTH, MONTHS, previous_period


def ppi_details(item):
    from cpi_release import details, period_from
    if item.get('price_metrics'):
        return details(item)
    text = re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', str(item.get('title') or '')+' '+str(item.get('summary') or ''))))
    subject = r'(?:producer price index for final demand|index for final demand|final demand (?:index|prices))'
    movement = r'(?P<verb>advanced|increased|rose|fell|declined|decreased|moved up|moved down)\s+(?P<value>\d+(?:\.\d+)?)\s*percent'
    monthly = re.search(subject+r'\s+'+movement, text, re.I)
    annual = re.search(r'(?:for|over) the 12 months(?: ended(?: in)?\s+(?:'+MONTH+r'))?[, ]+(?:the )?'+subject+r'\s+'+movement, text, re.I)
    if not annual:
        annual = re.search(subject+r'\s+'+movement+r'(?:\s+before seasonal adjustment)?\s+(?:for|over) the (?:last |past )?12 months', text, re.I)
    def number(m):
        return None if not m else float(m['value'])*(-1 if m['verb'].lower() in {'fell','declined','decreased','moved down'} else 1)
    month_clause = text[monthly.start():monthly.end()+120] if monthly else ''
    metrics = {'monthly': number(monthly), 'annual': number(annual),
               'monthly_seasonally_adjusted': True if re.search('seasonally adjusted', month_clause, re.I) and not re.search('not seasonally adjusted|unadjusted', month_clause, re.I) else None,
               'annual_unadjusted': True if annual and re.search('unadjusted|not seasonally adjusted|before seasonal adjustment', text[annual.start():annual.end()+100], re.I) else None}
    period = period_from(item, text)
    copy = dict(item, price_metrics=metrics)
    if period:
        copy['reference_period'] = period.replace('/', '-M')
    return details(copy)


def retail_details(item):
    text = re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', str(item.get('summary') or ''))))
    period = re.search(r'sales for (' + MONTH + r')\s+(20\d{2})', text, re.I)
    # Ignore annual growth, confidence intervals and earlier press-release boilerplate.
    movement = r'(?P<direction>up|down|increased|decreased|rose|fell)\s+(?P<value>\d+(?:\.\d+)?)\s*(?:percent|%)'
    monthly = re.search(movement + r'\s*(?:\([^)]*\)\s*)?from (?:the )?previous month', text, re.I)
    def number(m):
        return float(m['value']) * (-1 if m['direction'].lower() in {'down', 'decreased', 'fell'} else 1)
    if not period or not monthly:
        return '', [x for x, ok in [('資料月份', period), ('零售銷售月增率', monthly)] if not ok]
    year, month = int(period[2]), MONTHS[period[1].lower()]
    prior = previous_period(year, month)
    earlier = previous_period(*prior)
    revision = re.search(r'The ('+MONTH+r')\s+(20\d{2})\s+to\s+('+MONTH+r')\s+(20\d{2})\s+percent change was revised from\s+.*?\s+to\s+'+movement, text, re.I)
    previous = None
    if revision and (int(revision[2]), MONTHS[revision[1].lower()]) == earlier and (int(revision[4]), MONTHS[revision[3].lower()]) == prior:
        previous = number(revision)
    basis = bool(re.search(r'adjusted for seasonal variation', text, re.I))
    if not basis:
        return '', ['零售銷售季調口徑']
    value = number(monthly)
    lines = [f'**資料月份**　{year}/{month:02d}',
             '**零售銷售月增率（季調）**\n本次 **' + f'{value:+.1f}%' + '**｜前值 ' + (f'{previous:+.1f}%' if previous is not None else '暫缺')]
    if previous is not None:
        lines[-1] += f'｜變化 {round(value, 1)-round(previous, 1):+.1f} 個百分點'
        lines.append('前值採本次官方修訂後的前一期。')
    return '\n\n'.join(lines), []
