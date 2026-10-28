"""Read-only public-source and isolated completion diagnostics; no Discord or state."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from urllib.request import Request,urlopen
import notifier as n
from macro_result_extensions import publication
from macro_result_integrity import details,enrich
from etf_source_context import parse
from etf_followup import ready
from market_brief_data import FARSIDE_BTC,FARSIDE_ETH

URLS={'BTC':FARSIDE_BTC,'ETH':FARSIDE_ETH,
      'durable':'https://www.census.gov/manufacturing/m3/adv/current/index.html',
      'gdp':'https://www.bea.gov/data/gdp/gross-domestic-product',
      'industrial':'https://www.federalreserve.gov/releases/g17/current/default.htm',
      'jolts':'https://www.bls.gov/news.release/jolts.nr0.htm'}


def inspect(pair):
    key,url=pair
    try:
        headers=n.HTTP_HEADERS if key not in {'BTC','ETH'} else {'User-Agent':'Mozilla/5.0 market-brief/4.0','Referer':'https://farside.co.uk/'}
        with urlopen(Request(url,headers=headers),timeout=12) as response:
            raw=response.read().decode('utf-8','replace')
    except Exception as exc:
        return key,{'readable':False,'state':'source pending;not healthy','reason':type(exc).__name__,'source':url}
    if key in {'BTC','ETH'}:
        row=parse(raw)
        return key,{'readable':True,'source':url,'tradeDate':row['date'].date().isoformat(),
                    'complete':ready(row),'flowMUSD':row['net_flow_musd'],
                    'unreported':row['unreported_components'],'sourceIssue':row.get('source_issue')}
    text=n.html_to_text(raw)
    item={'rule':{'key':key},'title':'','summary':text,'url':url}
    item=enrich(item,lambda target:n.http_text(target,attempts=1),lambda target:n.http_bytes(target,attempts=1))
    copy,missing=details(item)
    if missing:
        raise ValueError(key+': readable official current source not parsed: '+','.join(missing))
    return key,{'readable':True,'source':url,'copy':copy,
                'publication':publication(text,key).isoformat() if key!='jolts' else 'not inferred from observation date'}


def check():
    with ThreadPoolExecutor(max_workers=6) as executor:
        rows=dict(executor.map(inspect,URLS.items()))
    return {'checkedAt':datetime.now(timezone.utc).isoformat(),'sources':rows,
            'sourceAvailabilityIsNotWorkflowSuccess':True,
            'productionStateRead':False,'productionStateWritten':False,'discordSends':0}


if __name__=='__main__':
    print(json.dumps(check(),ensure_ascii=False))
