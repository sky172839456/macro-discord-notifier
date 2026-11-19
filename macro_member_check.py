"""No-send/no-state acceptance for all result gates plus current Fed/BEA releases."""
import json,re
from datetime import datetime,timezone
import notifier as n
import slim_policy
from macro_result_integrity import details,enrich

# Fed press releases that mention the FOMC but are not a rate decision.  The
# decision itself is identified by its official title, never by whether its
# numbers happen to parse (2026-11-20: a 2027 meeting-schedule release was
# picked as "latest FOMC result").
FOMC_DECISION_TITLE = re.compile(r'Federal Reserve issues FOMC statement',re.I)
FOMC_OTHER_TITLES = (('schedule',re.compile(r'schedule of Federal Open Market Committee meetings',re.I)),
                     ('minutes',re.compile(r'^Minutes of the Federal Open Market Committee\b',re.I)),
                     ('projections',re.compile(r'\beconomic projections\b',re.I)))


def fomc_document_type(row):
    title=n.html_to_text(str(row.get('title') or '')).strip()
    if FOMC_DECISION_TITLE.fullmatch(title):
        return 'statement'
    return next((name for name,pattern in FOMC_OTHER_TITLES if pattern.search(title)),'unknown')


def fomc_decision(rows):
    """Latest decision statement; a newer unknown FOMC release stops the check."""
    typed=[(fomc_document_type(row),row) for row in rows]
    statements=[row for kind,row in typed if kind=='statement']
    latest=max(statements,key=lambda x:x['published']) if statements else None
    newer=[{'type':kind,'source':row['url']} for kind,row in typed
           if kind!='statement' and (latest is None or row['published']>latest['published'])]
    unknown=[x['source'] for x in newer if x['type']=='unknown']
    if unknown:
        raise ValueError('fomc: newer FOMC release with unrecognized document type: '+','.join(unknown))
    return latest,newer

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
        skipped=[]
        if key=='fomc':
            rows=[row for row in rows if re.search(r'/monetary\d{8}a\.htm$',row['url'])]
            decision,skipped=fomc_decision(rows)
            rows=[decision] if decision else []
        if not rows:
            live[key]={'state':'no published matching release in current feed;not confirmed','skippedNonDecision':skipped}
            continue
        row=max(rows,key=lambda x:x['published'])
        row=enrich(row,lambda url:n.http_text(url,attempts=1),lambda url:n.http_bytes(url,attempts=1))
        text,missing=details(row)
        if missing:
            # The latest real decision must still pass in full; no older fallback.
            raise ValueError(key+': current official result incomplete: '+','.join(missing))
        live[key]={'state':'parsed','source':row['url'],'published':row['published'].isoformat(),'copy':text}
        if skipped:
            live[key]['skippedNonDecision']=skipped
    return {'checkedAt':now.isoformat(),'headlineOnlyBlocked':failures,'live':live,
            'productionStateRead':False,'productionStateWritten':False,'discordSends':0}

if __name__=='__main__':
    print(json.dumps(check(),ensure_ascii=False))
