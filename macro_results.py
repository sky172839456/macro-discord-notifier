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


def retail_move(name):
    return (rf'\b(?P<{name}_dir>up|down|increased|decreased|rose|fell)\s+'
            rf'(?P<{name}_value>\d+(?:\.\d+)?)\s*(?:percent|%)')


# Census prints the confidence interval in parentheses and may mark a change
# that is not statistically significant with one footnote asterisk.
RETAIL_INTERVAL = r'(?:\s*\([^)]*\))?(?:\s*\*)?'
# Stay inside the headline sentence: "$748.2 billion" is fine, ". " ends it.
RETAIL_SAME_SENTENCE = r'(?P<clause>(?:(?!\.\s).){0,400}?)'
RETAIL_HEADLINE = re.compile(
    r'estimates of U\.S\. retail and food services sales for (?P<month>' + MONTH + r')\s+(?P<year>20\d{2})\s*,'
    + RETAIL_SAME_SENTENCE + retail_move('cur') + RETAIL_INTERVAL + r'\s+from (?:the )?previous month', re.I)
RETAIL_PAIR = (r'The (?P<from_month>' + MONTH + r')\s+(?P<from_year>20\d{2})\s+to\s+'
               r'(?P<to_month>' + MONTH + r')\s+(?P<to_year>20\d{2})\s+percent change was ')
RETAIL_REVISED = re.compile(RETAIL_PAIR + r'revised from\s+' + retail_move('old') + RETAIL_INTERVAL
                            + r'\s+to\s+' + retail_move('prev') + RETAIL_INTERVAL + r'\s*\.', re.I)
RETAIL_UNREVISED = re.compile(RETAIL_PAIR + r'unrevised from\s+' + retail_move('prev') + RETAIL_INTERVAL + r'\s*\.', re.I)


def retail_details(item):
    """Headline monthly change of total retail and food services sales.

    The value, data month and seasonal basis must all come from the headline
    sentence, the data month must equal the official schedule row, and the
    prior value is the adjacent month from this same release (2026-11-20).
    """
    text = re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', str(item.get('summary') or ''))))
    headline = RETAIL_HEADLINE.search(text)
    def number(m, name):
        return float(m[name+'_value']) * (-1 if m[name+'_dir'].lower() in {'down', 'decreased', 'fell'} else 1)
    if not headline:
        period = re.search(r'sales for (' + MONTH + r')\s+(20\d{2})', text, re.I)
        return '', [x for x, ok in [('資料月份', period), ('零售銷售月增率', False)] if not ok]
    clause = headline['clause']
    if not re.search(r'(?<!not )adjusted for seasonal variation', clause, re.I):
        return '', ['零售銷售季調口徑']
    year, month = int(headline['year']), MONTHS[headline['month'].lower()]
    scheduled = re.fullmatch(r'(20\d{2})-M?(0[1-9]|1[0-2])', str(item.get('scheduled_reference_period') or ''))
    if not scheduled:
        return '', ['零售官方排程資料月份']
    if (int(scheduled[1]), int(scheduled[2])) != (year, month):
        return '', ['零售資料月份與官方排程不一致']
    prior = previous_period(year, month)
    earlier = previous_period(*prior)
    def adjacent(m):
        return (m and (int(m['from_year']), MONTHS[m['from_month'].lower()]) == earlier
                and (int(m['to_year']), MONTHS[m['to_month'].lower()]) == prior)
    revised, unrevised = RETAIL_REVISED.search(text), RETAIL_UNREVISED.search(text)
    usable = [m for m in (revised, unrevised) if adjacent(m)]
    # Exactly one statement about the prior month, or no prior value at all.
    previous = number(usable[0], 'prev') if len(usable) == 1 else None
    value = number(headline, 'cur')
    from macro_result_display import comparison
    lines = [f'**資料月份**　{year}/{month:02d}｜前期 {prior[0]}/{prior[1]:02d}',
             comparison('零售銷售月增率（季調）',value,previous,signed=True)]
    if previous is not None:
        lines.append('前值採本次官方修訂後的前一期。' if usable[0] is revised else '前值採本次官方公布的前一期（未修訂）。')
    return '\n\n'.join(lines), []
