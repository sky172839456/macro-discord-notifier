"""Explicit headline metrics for the four approved result extensions."""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from cpi_release import MONTH, MONTHS, previous_period

KEYS = {'durable', 'gdp', 'jolts', 'industrial'}
NY = ZoneInfo('America/New_York')
Q = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4}
VERB = r'(?P<verb>increased|decreased|rose|fell|declined|advanced|moved up|moved down|edging up|edging down)'
VALUE = r'(?P<value>\d+(?:\.\d+)?)'


def clean(value):
    import html
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', str(value or '')))).strip()


def signed(match):
    if not match:
        return None
    return float(match['value'])*(-1 if match['verb'].lower() in {'decreased','fell','declined','moved down','edging down'} else 1)


def publication(text, key):
    if key == 'gdp':
        m = re.search(r'Current release:\s*('+MONTH+r')\s+(\d{1,2}),?\s+(20\d{2})', text, re.I)
    elif key == 'industrial':
        m = re.search(r'Release Date:\s*('+MONTH+r')\s+(\d{1,2}),?\s+(20\d{2})', text, re.I)
    else:
        m = re.search(r'\b('+MONTH+r')\s+(\d{1,2}),?\s+(20\d{2})', text, re.I)
    if not m:
        raise ValueError('official publication date missing for '+key)
    return datetime(int(m[3]),MONTHS[m[1].lower()],int(m[2]),
                    9 if key == 'industrial' else 8,
                    15 if key == 'industrial' else 30,tzinfo=NY).astimezone(timezone.utc)


def details(item):
    key = item['rule']['key']
    if key == 'durable' and item.get('durable_table'):
        from durable_release import details as table_details
        return table_details(item)
    text = clean(item.get('title','')+' '+item.get('summary',''))
    lines, missing = [], []
    if key == 'industrial' and re.search(r'annual revision',item.get('title',''),re.I):
        return '', ['年度修訂不是本月工業生產結果']
    if key == 'gdp':
        m = re.search(r'real gross domestic product\s*\(GDP\)\s+'+VERB+r'\s+at an annual rate of\s+'+VALUE+r'\s+percent in the (first|second|third|fourth) quarter of (20\d{2})',text,re.I)
        if not m:
            return '', ['實質GDP本季年化季增率與季度']
        y,q = int(m[4]), Q[m[3].lower()]
        # Explicit annual rate; never use nominal GDP, industry or annual growth.
        from macro_result_display import comparison
        stage = re.search(r'(advance|second|third) estimate',text,re.I)
        version={'advance':'初估','second':'第二次估計','third':'第三次估計'}.get(stage[1].lower()) if stage else None
        prev_q, prev_y = (q-1,y) if q>1 else (4,y-1)
        prev = re.search(r'In the (first|second|third|fourth) quarter(?: of (20\d{2}))?, real GDP\s+'+VERB+r'\s+'+VALUE+r'\s+percent', text,re.I)
        prior_value=signed(prev) if prev and Q[prev[1].lower()]==prev_q and (not prev[2] or int(prev[2])==prev_y) else None
        lines=[f'**資料季度**　{y}年第{q}季'+(f'（{version}）' if version else ''),
               comparison('實質GDP年化季增率',signed(m),prior_value,signed=True,
                          current_period=f'{y}年第{q}季',previous_period=f'{prev_y}年第{prev_q}季'),
               '季增年率：與上一季比較後換算成年率，並非全年成長率。前值採本次公告的前一季。']
    elif key == 'jolts':
        ref = re.fullmatch(r'(20\d{2})-M?(0[1-9]|1[0-2])',str(item.get('reference_period','')))
        period = re.search(r'JOB OPENINGS AND LABOR TURNOVER\s*[-–—]\s*('+MONTH+r')\s+(20\d{2})',text,re.I)
        m = re.search(r'(?:number of job openings was (?:little changed at|unchanged at|increased to|decreased to)|Job openings were)\s*(\d+(?:\.\d+)?)\s+million',text,re.I)
        if not m or not (ref or period):
            return '', ['JOLTS職位空缺與資料月份']
        if not (item.get('id','').startswith('bls-api-jolts-') or re.search(r'(?<!not )(?<!un)seasonally adjusted|Seasonal Adjustment',text,re.I)):
            return '', ['JOLTS季調口徑']
        y,mo = (int(ref[1]),int(ref[2])) if ref else (int(period[2]),MONTHS[period[1].lower()])
        from macro_result_display import comparison
        prior = re.search(r'previous value (\d+(?:\.\d+)?) million',text,re.I) if ref else None
        previous=float(prior[1])*100 if prior else None
        prev_y,prev_m=previous_period(y,mo)
        lines=[f'**資料月份**　{y}/{mo:02d}｜前期 {prev_y}/{prev_m:02d}',
               comparison('職位空缺（季調）',float(m[1])*100,previous,
                          unit='萬人',change_unit='萬人')]
    else:
        if not re.search(r'(?<!not )adjusted for seasonal variation|(?<!not )(?<!un)seasonally adjusted',text,re.I):
            return '', ['主數據季調口徑']
        if key == 'durable':
            subject = re.search(r'New orders for manufactured durable goods in ('+MONTH+r')\b(.{0,280}?)\b'+VERB+r'.{0,100}?\b'+VALUE+r'\s+percent',text,re.I)
            if not subject:
                return '', ['耐久財訂單主數據與月份']
            month = MONTHS[subject[1].lower()]
            period = re.search(r'\b'+re.escape(subject[1])+r'\s+(20\d{2})\b',text,re.I)
            if not period:
                return '', ['耐久財訂單資料年份']
            y = int(period[1])
            current = signed(subject)
            label = '耐久財新訂單月增率（季調、未扣除價格變動）'
            previous = re.search(r'followed a (\d+(?:\.\d+)?) percent ('+MONTH+r') (increase|decrease)',text,re.I)
            prior_value = (float(previous[1])*(-1 if previous[3].lower()=='decrease' else 1)
                           if previous and MONTHS[previous[2].lower()] == previous_period(y,month)[1] else None)
        else:
            subject = re.search(r'(?:Industrial production\s*\(IP\)|Total industrial production|Industrial production)\s+'+VERB+r'\s+'+VALUE+r'\s+percent in ('+MONTH+r')',text,re.I)
            if not subject:
                return '', ['工業生產主數據與月份']
            try:
                released = publication(text,key).astimezone(NY)
            except ValueError:
                return '', ['工業生產發布日期與資料年份']
            month = MONTHS[subject[3].lower()]
            y = released.year-(month>released.month)
            current = signed(subject)
            label = '工業生產月增率（季調）'
            previous = re.search(r'after\s+'+VERB+r'\s+'+VALUE+r'\s+percent in ('+MONTH+r')',text,re.I)
            prior_value = signed(previous) if previous and MONTHS[previous[3].lower()] == previous_period(y,month)[1] else None
            capacity = re.search(r'Capacity utilization\s+(?:moved up to|moved down to|was|remained at|decreased to|increased to)\s+(\d+(?:\.\d+)?) percent in ('+MONTH+r')',text,re.I)
            if capacity and MONTHS[capacity[2].lower()] == month:
                lines.append(f'**產能利用率**　{float(capacity[1]):.1f}%')
        from macro_result_display import comparison
        prior=previous_period(y,month)
        lines[:0]=[f'**資料月份**　{y}/{month:02d}｜前期 {prior[0]}/{prior[1]:02d}',
                   comparison(label,current,prior_value,signed=True)]
    return '\n\n'.join(lines), missing


def enrich(item, fetch):
    """Fetch the same official release only when headline metrics lack context."""
    if item['rule']['key'] not in KEYS or not details(item)[1]:
        return item
    from urllib.parse import urlparse
    host = urlparse(item.get('url','')).hostname
    expected = {'gdp':{'www.bea.gov','apps.bea.gov'},'jolts':{'www.bls.gov'},
                'durable':{'www.census.gov'},'industrial':{'www.federalreserve.gov'}}
    if host not in expected[item['rule']['key']]:
        return item
    try:
        text = clean(fetch(item['url']))
        # Keep only this source; no additional source or synthetic metric.
        copy = dict(item,summary=text)
        return copy if not details(copy)[1] else item
    except Exception:
        return item
