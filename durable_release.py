"""Census headline + actually linked Table 1; no assumed period/basis."""
import re,io
from datetime import datetime
from urllib.parse import urljoin,urlparse
from pypdf import PdfReader
from cpi_release import MONTH,MONTHS,previous_period

SHORT={name[:3].lower():number for name,number in MONTHS.items()}
ABBR='|'.join(SHORT)


def table_metrics(text):
    from macro_result_extensions import clean
    text=clean(text)
    if not text.startswith("Table 1.") or "Durable Goods Manufacturers'" not in text[:120]:
        raise ValueError('table identity')
    header=text.split('DURABLE GOODS',1)[0]
    if not re.search(r'Seasonally Adjusted\s+Not Seasonally Adjusted',header):
        raise ValueError('column basis/order')
    month_row=re.search(r'Item\s+Percent\s+('+ABBR+r')\s+('+ABBR+r')\s+('+ABBR+r')\b',header,re.I)
    years=re.search(r'\b(20\d{2})\s+2\s+(20\d{2})\s+r\s+(20\d{2})\b',header)
    if not month_row or not years:
        raise ValueError('explicit table period')
    period=int(years[1]),SHORT[month_row[1].lower()]
    prior=previous_period(*period); earlier=previous_period(*prior)
    if (int(years[2]),SHORT[month_row[2].lower()])!=prior or (int(years[3]),SHORT[month_row[3].lower()])!=earlier:
        raise ValueError('nonadjacent table months')
    row=re.search(r'DURABLE GOODS\s+Total:\s+Shipments.*?New Orders\d*[^0-9-]+(.+?)\s+Excluding transportation:',text,re.I)
    if not row:
        raise ValueError('total new orders row')
    values=re.findall(r'(?<!\w)-?\d[\d,]*(?:\.\d+)?',row[1])
    if len(values)!=12:
        raise ValueError('table cells missing')
    numbers=[float(x.replace(',','')) for x in values]
    if min(numbers[:3])<=0:
        raise ValueError('invalid levels')
    for index in (0,1):
        actual=(numbers[index]/numbers[index+1]-1)*100
        if abs(actual-numbers[3+index])>0.055:
            raise ValueError('table level/change inconsistent')
    footer=re.search(r'Source: U\.S\. Census Bureau,.*?Survey,\s+('+MONTH+r') Advance Report,\s+((?:'+MONTH+r')\s+\d{1,2},\s+20\d{2})',text,re.I)
    if not footer or MONTHS[footer[1].lower()]!=period[1]:
        raise ValueError('table source/date')
    if not re.search(r'Estimates are not adjusted for price changes',text,re.I):
        raise ValueError('price basis')
    release=datetime.strptime(footer[2],'%B %d, %Y').date()
    period_start=datetime(period[0],period[1],1).date()
    if not 0 <= (release-period_start).days <= 93:
        raise ValueError('stale/future table period')
    return {'year':period[0],'month':period[1],'current':numbers[3],'previous':numbers[4],
            'release':release.isoformat(),'seasonally_adjusted':True,'price_adjusted':False}


def details(item):
    from macro_result_extensions import clean,publication,VERB,VALUE,signed
    table=item.get('durable_table') or {}
    text=clean(item.get('summary',''))
    subject=re.search(r'New orders for manufactured durable goods in ('+MONTH+r')\b(.{0,280}?)\b'+VERB+r'.{0,100}?\b'+VALUE+r'\s+percent',text,re.I)
    try:
        if not subject or MONTHS[subject[1].lower()]!=table['month']:
            raise ValueError('headline period')
        if table.get('seasonally_adjusted') is not True or table.get('price_adjusted') is not False:
            raise ValueError('basis')
        if abs(signed(subject)-table['current'])>0.001:
            raise ValueError('headline/table current disagreement')
        release=publication(text,'durable').date().isoformat()
        if release!=table['release']:
            raise ValueError('different publication dates')
        previous=re.search(r'followed a (\d+(?:\.\d+)?) percent ('+MONTH+r') (increase|decrease)',text,re.I)
        if previous:
            value=float(previous[1])*(-1 if previous[3].lower()=='decrease' else 1)
            if MONTHS[previous[2].lower()]!=previous_period(table['year'],table['month'])[1] or abs(value-table['previous'])>0.001:
                raise ValueError('headline/table previous disagreement')
    except (ValueError,KeyError,TypeError):
        return '', ['耐久財主文與官方附表的期間、數值及口徑一致性']
    lines=[f"**資料月份**　{table['year']}/{table['month']:02d}",
           f"**耐久財新訂單月增率（季調、未扣除價格變動）**　{table['current']:+.1f}%",
           f"**前月增率（本次官方修訂版本）**　{table['previous']:+.1f}%",
           '主文與官方表1「總新訂單」交叉核對；不以排除運輸或未季調欄替代。']
    return '\n\n'.join(lines),[]


def enrich(item,fetch_text,fetch_bytes):
    from macro_result_extensions import details as existing
    if not existing(item)[1]:
        return item
    url=item.get('url','')
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='www.census.gov' or parsed.path!='/manufacturing/m3/adv/current/index.html':
        return item
    try:
        raw=fetch_text(url)
        from macro_result_extensions import clean
        # Only the official table URL actually linked in this release is eligible.
        links=re.findall(r'href\s*=\s*["\']([^"\']+)["\']',raw,re.I)
        target=next((urljoin(url,x) for x in links if urlparse(urljoin(url,x)).hostname=='www.census.gov'
                     and urlparse(urljoin(url,x)).path=='/manufacturing/m3/adv/pdf/table1a.pdf'),None)
        if not target:
            return item
        payload=fetch_bytes(target)
        if not payload.startswith(b'%PDF'):
            return item
        reader=PdfReader(io.BytesIO(payload))
        text='\n'.join(page.extract_text() or '' for page in reader.pages[:2])
        result=dict(item,summary=clean(raw),durable_table=table_metrics(text),durable_source_urls=[url,target])
        return result if not details(result)[1] else item
    except Exception:
        return item
