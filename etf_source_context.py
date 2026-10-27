"""Latest row integrity plus explicitly dated prior complete context."""
import re
from datetime import datetime, timezone
from market_brief_data import _number


def parse(source):
    import html
    rows = []
    for raw in re.findall(r'<tr[^>]*>(.*?)</tr>',source,re.I|re.S):
        cells = [re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',html.unescape(c))).strip()
                 for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>',raw,re.I|re.S)]
        if len(cells)<3 or not re.fullmatch(r'\d{1,2} [A-Za-z]{3} \d{4}',cells[0]):
            continue
        d=datetime.strptime(cells[0],'%d %b %Y').replace(tzinfo=timezone.utc)
        funds=[]
        for cell in cells[1:-1]:
            try:funds.append(_number(cell))
            except ValueError:funds.append(None)
        try:total=_number(cells[-1])
        except ValueError:total=None
        row={'date':d,'net_flow_musd':total,'component_count':len(funds),
             'unreported_components':sum(x is None for x in funds)}
        if total is None:
            row['source_issue']='來源合計尚未列值'
        elif not row['unreported_components'] and abs(sum(funds)-total)>max(.2,len(funds)*.06):
            row['source_issue']='來源分項與合計不符'
        rows.append(row)
    if not rows:
        raise ValueError('Farside ETF 表格沒有可核對分項的日期資料')
    rows.sort(key=lambda r:r['date'])
    latest=rows[-1]
    previous=[r for r in rows[:-1] if not r['unreported_components'] and r['net_flow_musd'] is not None
              and not r.get('source_issue') and 0<(latest['date']-r['date']).days<=10]
    if previous:
        latest['previous_complete']=previous[-1]
    return latest
