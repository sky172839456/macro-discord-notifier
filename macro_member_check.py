"""No-send/no-state acceptance for all result gates plus current Fed/BEA releases."""
import json,re
from datetime import datetime,timezone
import notifier as n
import slim_policy
from macro_result_integrity import details,enrich

def check():
    failures={}
    for key in sorted(slim_policy.RESULT_EVENTS):
        row={'rule':{'key':key},'title':'','summary':'Publication announcement. Inflation objective 2 percent.'}
        missing=details(row)[1]
        if not missing:
            raise ValueError(key+': headline/unrelated number passed result gate')
        failures[key]=missing
    live={}
    now=datetime.now(timezone.utc)
    for key,provider in [('fomc','FED_POLICY'),('pce','BEA')]:
        url=next(url for name,url in n.OFFICIAL_FEEDS if name==provider)
        try:
            rows=n.parse_feed(n.http_text(url,attempts=1),url,provider)
        except Exception as exc:
            live[key]={'state':'source pending;not healthy','reason':type(exc).__name__}
            continue
        rows=[row for row in rows if row['rule']['key']==key and row['published']<=now]
        if key=='fomc':
            rows=[row for row in rows if re.search(r'/monetary\d{8}a\.htm$',row['url'])]
        if not rows:
            live[key]={'state':'no published matching release in current feed;not confirmed'}
            continue
        row=max(rows,key=lambda x:x['published'])
        row=enrich(row,lambda url:n.http_text(url,attempts=1),lambda url:n.http_bytes(url,attempts=1))
        text,missing=details(row)
        if missing:
            raise ValueError(key+': current official result incomplete: '+','.join(missing))
        live[key]={'state':'parsed','source':row['url'],'published':row['published'].isoformat(),'copy':text}
    return {'checkedAt':now.isoformat(),'headlineOnlyBlocked':failures,'live':live,
            'productionStateRead':False,'productionStateWritten':False,'discordSends':0}

if __name__=='__main__':
    print(json.dumps(check(),ensure_ascii=False))
