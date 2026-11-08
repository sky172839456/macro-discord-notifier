"""Read approved feeds and evaluate selection; no state, secrets or Discord sends."""
import json
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import crypto_news_notifier as news
import material_inbox as m
from material_quality import selection
from material_editorial import review
from news_streams import FINANCE_SOURCES


def check():
    now=datetime.now(timezone.utc)
    sources=[(n,u,h,True) for n,u,h in m.MATERIAL_SOURCES]
    from urllib.parse import urlparse
    sources += [(c['name'],c['url'],(urlparse(c['url']).hostname or '').removeprefix('www.'),False) for c in (*news.SOURCES,*FINANCE_SOURCES)]
    def read(cfg):
        name,url,host,own=cfg
        try:
            raw=m.fetch_feed(url) if own else news.http_text(url,attempts=1)
            rows=m.parse_source_feed(raw,name,host) if own else m.parse_ai_feed(raw,name,host,ai=False,official=False)
            current=[r for r in rows if now-timedelta(hours=24)<=r['published']<=now+timedelta(minutes=5)]
            values=[]
            for row in current:
                kind=m.topic(row)
                if not kind: continue
                row['material_topic']=kind
                values.append({'title':row['title'],'source':name,'topic':kind,'stars':review(row,now)['stars'],
                    'hold':selection(row,now),'url':row['url']})
            return {'source':name,'parsed':len(rows),'current':len(current),'candidates':values}
        except Exception as exc:
            return {'source':name,'error':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(read,sources))
    print(json.dumps({'read_only':True,'discord_sends':0,'production_state_access':False,'sources':result},ensure_ascii=False))

if __name__=='__main__':
    check()
