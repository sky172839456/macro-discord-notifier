"""Read-only acceptance of the expanded macro calendar and retail result copy."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import notifier as n
from macro_calendar import census_calendar, industrial_calendar
from macro_results import retail_details


def check():
    now = datetime.now(timezone.utc)
    fetch = lambda url: n.http_text(url, attempts=1)
    census, detail = census_calendar(now, fetch, n.html_to_text)
    industrial = industrial_calendar(now, fetch, n.html_to_text)
    retail = n.html_to_text(fetch('https://www.census.gov/retail/sales.html'))
    index = retail.lower().find('advance monthly sales for retail and food services')
    if index < 0:
        raise ValueError('retail official headline missing')
    excerpt = retail[max(0, index-100):index+2200]
    numbers, missing = retail_details({'summary': excerpt})
    if missing:
        raise ValueError('retail: '+','.join(missing))
    def row(e):
        return {'key': e['rule']['key'], 'time': e['time'].astimezone(n.TAIPEI).isoformat(), 'source': e['rule']['source']}
    return {'checkedAt': now.isoformat(), 'census': {'detail': detail, 'nextEvents': [row(e) for e in census if e['time']>=now][:4]},
            'industrial': {'monthlyEvents': len(industrial), 'nextEvents': [row(e) for e in industrial if e['time']>=now][:3]},
            'retail': {'copy': numbers, 'officialPublication': n.official_page_published_at(excerpt, 'retail', now).isoformat()},
            'productionStateRead': False, 'productionStateWritten': False, 'discordSends': 0}


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    result = check()
    if len(sys.argv)>1:
        Path(sys.argv[1]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
