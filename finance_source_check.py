"""Read-only public feed diagnostics; never touches delivery state or Discord."""
import json
import os
os.environ['SLIM_NOTIFICATIONS']='1'
os.environ['NEWS_AUTO_RECOVERY']='1'
from news_streams import fetch_finance
if __name__ == '__main__':
    rows,statuses=fetch_finance()
    print(json.dumps({'sources':[{'source':n,'selected':c,'error':e} for n,c,e in statuses],
        'selected_count':len(rows),'not_sent':True},ensure_ascii=True))
    raise SystemExit(0 if any(c >= 0 for _,c,_ in statuses) else 1)
