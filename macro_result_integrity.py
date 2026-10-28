"""Structured member results: a headline or unrelated number is never a result."""
import re
import math
from fractions import Fraction
from datetime import datetime, timedelta
from urllib.parse import urlparse
from cpi_release import MONTH, MONTHS, previous_period

NEW_KEYS = {'fomc', 'pce', 'jobs', 'claims'}


def clean(value):
    import notifier as n
    return n.html_to_text(str(value or ''))


def text_of(item):
    return clean(str(item.get('title') or '')+' '+str(item.get('summary') or ''))


def rate(value):
    value = value.replace('¾', '-3/4').replace('½', '-1/2').replace('¼', '-1/4')
    if '-' in value:
        whole, part = value.split('-', 1)
        return float(whole)+float(Fraction(part))
    return float(Fraction(value))


NUM = r'(?:\d+(?:-\d+/\d+|/\d+|\.\d+)?|\d+[¼½¾])'
MOVE = r'(?P<verb>increased|rose|decreased|fell|declined)\s+(?P<value>\d+(?:\.\d+)?)\s*percent'


def signed(match):
    return float(match['value'])*(-1 if match['verb'].lower() in {'decreased','fell','declined'} else 1)


def fomc(item):
    text = text_of(item)
    pattern = (r'\bThe Committee (?:decided|voted) to '
               r'(?P<action>maintain|raise|lower|reduce|increase) the target range for the federal funds rate '
               r'(?:(?:by (?P<amount>'+NUM+r') (?P<unit>basis points?|percentage points?|percent(?:age)? point) to)|at|to) '
               r'(?P<low>'+NUM+r')\s+(?:to|and)\s+(?P<high>'+NUM+r') percent')
    match = re.search(pattern, text, re.I)
    if not match:
        return '', ['FOMC本次利率決議與目標區間']
    try:
        low, high = rate(match['low']), rate(match['high'])
        if not all(math.isfinite(x) for x in (low, high)) or low >= high:
            raise ValueError('range')
        action = match['action'].lower()
        delta = 0 if action == 'maintain' else rate(match['amount'])*(1 if match['unit'].lower().startswith('basis') else 100) if match['amount'] else None
        if delta is None or (action != 'maintain' and delta <= 0):
            return '', ['FOMC本次調整幅度']
    except (ValueError, ZeroDivisionError):
        return '', ['FOMC利率格式']
    word = '維持利率不變' if action == 'maintain' else '升息' if action in {'raise','increase'} else '降息'
    lines = ['**本次決議**　'+word, f'**聯邦基金目標區間**　{low:.2f}%～{high:.2f}%',
             f'**本次調整**　{delta:g} 基點']
    vote = re.search(r'approved the following statement for release by a (\d+)\s*[-–—]\s*(\d+) vote', text, re.I)
    if vote:
        lines.append(f'**表決**　{vote[1]}票贊成、{vote[2]}票反對')
    if re.search(r'Economic activity is expanding at a strong pace', text, re.I):
        lines.append('**官方重點**　經濟活動仍強勁擴張。')
    if re.search(r'Inflation remains elevated', text, re.I):
        lines.append('**通膨說明**　官方表示通膨仍偏高。')
    minority = re.search(r'Voting against the monetary policy action were .{0,300}?who preferred to '
                         r'(raise|lower|reduce|increase) the target range for the federal funds rate by ('+NUM+r') percentage point', text, re.I)
    if minority:
        amount = rate(minority[2])*100
        direction = '升息' if minority[1].lower() in {'raise','increase'} else '降息'
        lines.append(f'**反對票意見**　偏好{direction}{amount:g}基點；不是本次通過的決議。')
    return '\n\n'.join(lines), []


def pce(item):
    text = text_of(item)
    period = re.search(r'Personal Income and Outlays,\s*('+MONTH+r')\s+(20\d{2})', text, re.I)
    if not period:
        return '', ['PCE資料月份']
    month, year = MONTHS[period[1].lower()], int(period[2])
    text=re.sub(r'(the PCE price index(?: for (?:'+MONTH+r'))? )(?:(?:was|remained) unchanged)',r'\1increased 0.0 percent',text,flags=re.I)
    monthly = re.search(r'From the preceding month, the PCE price index(?: for ('+MONTH+r'))?\s+'+MOVE, text, re.I)
    annual = re.search(r'From the same month one year ago, the PCE price index(?: for ('+MONTH+r'))?\s+'+MOVE, text, re.I)
    def core_after(main, annual=False):
        if not main:
            return None
        end = text.find('From the same month one year ago', main.end()) if not annual else -1
        tail = text[main.end():end if end >= 0 else main.end()+350]
        pattern = r'Excluding food and energy, the PCE price index\s+(?:also\s+)?'+MOVE
        if annual:
            pattern += r'\s+from one year ago'
        return re.search(pattern, tail, re.I)
    core_monthly, core_annual = core_after(monthly), core_after(annual, True)
    missing = [label for label, value in [('PCE月增率',monthly),('核心PCE月增率',core_monthly),
                                          ('PCE年增率',annual),('核心PCE年增率',core_annual)] if not value]
    for m in (monthly, annual):
        if m and m[1] and MONTHS[m[1].lower()] != month:
            missing.append('PCE本次月份一致性')
    if missing:
        return '', missing
    lines = [f'**資料月份**　{year}/{month:02d}']
    for label, match in [('PCE月增率',monthly),('核心PCE月增率',core_monthly),
                         ('PCE年增率',annual),('核心PCE年增率',core_annual)]:
        lines.append(f'**{label}**　{signed(match):+.1f}%')
    lines.append('月增比較前一月；年增比較去年同月，均非年化增幅。季調標示依官方原表，本文不另推定。')
    lines.append('**前值／修正**　尚未取得可核對的同口徑前值，未以所得或支出增幅代替。')
    return '\n\n'.join(lines), []


def jobs(item):
    text = text_of(item)
    ref = re.fullmatch(r'(20\d{2})-M?(0[1-9]|1[0-2])', str(item.get('reference_period') or ''))
    period = re.search(r'THE EMPLOYMENT SITUATION\s*[-–—]\s*('+MONTH+r')\s+(20\d{2})', text, re.I)
    api = str(item.get('id','')).startswith('bls-api-jobs-')
    metrics = item.get('jobs_metrics') if api and ref else None
    if metrics:
        payroll, unemployment = metrics.get('payroll'), metrics.get('unemployment')
        if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in (payroll,unemployment)):
            return '', ['非農與失業率主數據']
        if not 0 <= unemployment <= 100:
            return '', ['失業率格式']
        previous_payroll, previous_unemployment = metrics.get('previous_payroll'), metrics.get('previous_unemployment')
    else:
        payroll_match = re.search(r'Total nonfarm payroll employment\s+(increased|rose|decreased|fell|declined)\s+by\s+([\d,]+)\s+in\s+('+MONTH+r')', text, re.I)
        unemp_match = re.search(r'unemployment rate\s+(?:was unchanged at|was little changed at|changed little at|was|remained at|rose to|fell to|increased to|decreased to)\s+(\d+(?:\.\d+)?)\s+percent', text, re.I)
        if not payroll_match or not unemp_match:
            return '', ['非農新增就業與失業率']
        payroll = int(payroll_match[2].replace(',',''))*(-1 if payroll_match[1].lower() in {'decreased','fell','declined'} else 1)
        unemployment = float(unemp_match[1])
        if not 0 <= unemployment <= 100:
            return '', ['失業率格式']
        if not period or MONTHS[payroll_match[3].lower()] != MONTHS[period[1].lower()]:
            return '', ['就業資料月份一致性']
        if not re.search(r'All data in this release are seasonally adjusted|Data are seasonally adjusted', text, re.I):
            return '', ['就業季調口徑']
        previous_payroll = previous_unemployment = None
    if not (ref or period):
        return '', ['就業資料月份']
    year, month = (int(ref[1]),int(ref[2])) if ref else (int(period[2]),MONTHS[period[1].lower()])
    lines = [f'**資料月份**　{year}/{month:02d}',f'**非農新增就業（季調）**　{payroll/10000:+.1f} 萬人',
             f'**失業率（季調）**　{unemployment:.1f}%']
    if previous_payroll is not None and previous_unemployment is not None:
        lines.append(f'**前月（本次官方版本）**　非農 {previous_payroll/10000:+.1f} 萬人；失業率 {previous_unemployment:.1f}%')
    else:
        lines.append('**前月值**　暫缺，未以其他月份或非農總人數代替。')
    return '\n\n'.join(lines), []


def claims(item):
    text = text_of(item)
    section = re.split(r'\bUNADJUSTED DATA\b', text, maxsplit=1, flags=re.I)[0]
    actual = re.search(r'(?<!not )(?<!un)seasonally adjusted initial claims\s+was\s+([\d,]+)', section, re.I)
    if not actual:
        return '', ['本次初領失業金人數']
    period = re.search(r'In the week ending ('+MONTH+r')\s+(\d{1,2}),', section, re.I)
    source = urlparse(item.get('url',''))
    archive = re.fullmatch(r'/press/(20\d{2})/(\d{6})\.pdf',source.path)
    if not period or source.hostname != 'oui.doleta.gov' or not archive:
        return '', ['初領失業金資料週次與官方發布日期']
    try:
        release = datetime.strptime(archive[2],'%m%d%y').date()
        if release.year != int(archive[1]) or (item.get('published') and item['published'].date()!=release):
            raise ValueError()
        month,day = MONTHS[period[1].lower()],int(period[2])
        year = release.year-(month>release.month)
        week = release.replace(year=year,month=month,day=day)
        if not 0 <= (release-week).days <= 14:
            raise ValueError()
    except ValueError:
        return '', ['初領失業金資料週次']
    # The legacy formatter already preserves revised prior, direction and 4-week average.
    import notifier as n
    lines = [f'**資料週次**　截至 {week:%Y/%m/%d}（季調）',n.format_metrics(section,'claims')]
    return '\n\n'.join(lines), []


PARSERS = {'fomc':fomc,'pce':pce,'jobs':jobs,'claims':claims}


def details(item):
    key=item['rule']['key']
    if key in PARSERS:
        return PARSERS[key](item)
    if key == 'ppi':
        from macro_results import ppi_details
        return ppi_details(item)
    if key == 'cpi':
        from cpi_release import details as cpi
        return cpi(item)
    if key == 'retail':
        from macro_results import retail_details
        return retail_details(item)
    from macro_result_extensions import KEYS,details as extended
    if key in KEYS:
        return extended(item)
    return '', ['不支援的結果類型']


def enrich(item, fetch_text, fetch_bytes):
    """Only follow the same responsible agency's actual release/attachment."""
    key=item['rule']['key']
    if key == 'durable':
        from durable_release import enrich as durable
        return durable(item,fetch_text,fetch_bytes)
    if key not in {'fomc','pce','jobs'} or not details(item)[1]:
        from macro_result_extensions import enrich as extended
        return extended(item,fetch_text)
    expected={'fomc':{'www.federalreserve.gov'},'pce':{'www.bea.gov','apps.bea.gov'},'jobs':{'www.bls.gov'}}
    parsed=urlparse(item.get('url',''))
    if parsed.scheme!='https' or parsed.hostname not in expected[key]:
        return item
    if key=='fomc' and not re.fullmatch(r'/newsevents/pressreleases/monetary\d{8}[a-z]\.htm',parsed.path):
        return item
    try:
        raw=fetch_text(item['url'])
        result=dict(item,summary=clean(raw))
        # Never replace the original publication/identity/state with retrieval time.
        return result if not details(result)[1] else item
    except Exception:
        return item
