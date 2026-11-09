"""Private official announcement intake. No credentials, sends or public-news state.

Indexes establish a first-success baseline. Only subsequent, genuinely new articles
get bounded detail reads; errors remain visible and retry with backoff, never as
empty announcements. Dates come from the publisher, never the discovery clock.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

BG = 'https://api.bitget.com/api/v3/public/annoucements?language=en_US&limit=10&annType='
BN = 'https://www.binance.com/bapi/composite/v1/public/cms/article/'
SOURCES = tuple(
    {'name': name, 'url': BG+kind, 'kind': 'bitget'} for name, kind in (
        ('Bitget News', 'latest_news'), ('Bitget Products', 'product_updates'),
        ('Bitget Listings', 'coin_listings'))
) + tuple(
    {'name': name, 'url': BN+f'list/query?type=1&pageNo=1&pageSize=50&catalogId={catalog}', 'kind': 'binance'}
    for name, catalog in (('Binance News', 49), ('Binance Listings', 48), ('Binance Activities', 93))
) + ({'name': 'TradingView Blog', 'url': 'https://www.tradingview.com/blog/en/', 'kind': 'tradingview'},)
MAX_DETAILS = 6


def promotional_title(title):
    return bool(re.search(r'\b(?:word of the day|WOTD|quiz|learn (?:and|&) earn|trade to win|trading competition|referral challenge)\b',title,re.I))


def allowed(url):
    p = urlparse(url)
    if p.scheme != 'https' or p.username or p.password or p.port or p.fragment:
        return False
    if url in {s['url'] for s in SOURCES}:
        return True
    if p.hostname == 'api.bitget.com':
        return any(url.startswith(s['url']+'&cursor=') and re.fullmatch(r'\d+', url[len(s['url'])+8:])
                   for s in SOURCES if s['kind']=='bitget')
    if p.hostname == 'www.bitget.com':
        return not p.query and bool(re.fullmatch(r'/(?:en/)?support/articles/\d+', p.path))
    if p.hostname == 'www.binance.com':
        return bool(re.fullmatch(re.escape(BN)+r'detail/query\?articleCode=[a-f0-9]{28,40}', url))
    if p.hostname == 'www.tradingview.com':
        return not p.query and bool(re.fullmatch(r'/blog/en/[a-z0-9-]+-\d+/', p.path))
    return False


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError('unapproved official redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, attempts=1):
    if not allowed(url):
        raise ValueError('unapproved official URL')
    req = Request(url, headers={'User-Agent': 'WV-material-inbox/1.0', 'Accept-Encoding': 'identity'})
    with build_opener(SafeRedirect()).open(req, timeout=12) as response:
        raw = response.read(2000001)
    if len(raw)>2000000:
        raise ValueError('official response too large')
    return raw.decode('utf-8-sig')


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()
    def text(self):
        if self.tag in ('script','style','nav','header','footer'):
            return ''
        return ' '.join(c.text() if isinstance(c,Node) else c for c in self.children)


class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(raw)
    def handle_starttag(self, tag, attrs):
        node=Node(tag,attrs)
        self.stack[-1].children.append(node)
        if tag not in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):
            self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.stack[-1].children.append(Node(tag,attrs))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:
                del self.stack[i:]
                break
    def handle_data(self,value):
        self.stack[-1].children.append(value)


def clean(value, limit=6000):
    return re.sub(r'\s+', ' ', unescape(unescape(str(value or '')))).strip()[:limit]


def stamp(value):
    if isinstance(value, (int,float)) or str(value).isdigit():
        result=datetime.fromtimestamp(int(value)/1000,timezone.utc)
    else:
        result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if result.tzinfo is None or result.year<2020:
        raise ValueError('official publication timestamp missing')
    return result


def article_url(kind, url):
    p=urlparse(url)
    return (p.scheme=='https' and not p.query and not p.fragment and not p.username and not p.password
            and not p.port and ((kind=='bitget' and p.hostname=='www.bitget.com'
            and re.fullmatch(r'/(?:en/)?support/articles/\d+',p.path))
            or (kind=='tradingview' and allowed(url))))


def parse_index(raw, source):
    kind=source['kind']
    if kind=='tradingview':
        articles=[n for n in Page(raw).root.walk() if n.tag=='article']
        rows=[]
        for article in articles[:30]:
            links=[n.attrs.get('href','') for n in article.walk() if n.tag=='a'
                   and n.attrs.get('rel')=='bookmark']
            titles=[clean(n.text(),300) for n in article.walk() if n.tag in ('h2','h3')]
            if links and titles and article_url(kind,links[0]):
                rows.append({'url':links[0], 'title':titles[0], 'published':None})
        if not rows:
            raise ValueError('official blog structure missing')
        return list({r['url']:r for r in rows}.values())
    data=json.loads(raw)
    if data.get('code')!=('00000' if kind=='bitget' else '000000'):
        raise ValueError('official API did not succeed')
    if kind=='bitget':
        values=data['data']
    else:
        catalogs=data['data']['catalogs']
        values=[a for c in catalogs for a in c['articles']]
    if not isinstance(values,list):
        raise ValueError('official article list missing')
    rows=[]
    for item in values:
        if kind=='bitget':
            url=item['annUrl']
            if not article_url(kind,url):
                raise ValueError('unapproved Bitget article')
            title=item['annTitle']
            date=stamp(item.get('createdTime') or item.get('cTime'))
        else:
            code=str(item['code'])
            if not re.fullmatch(r'[a-f0-9]{28,40}',code):
                raise ValueError('invalid Binance article code')
            url='https://www.binance.com/en/support/announcement/'+code
            title=item['title']
            date=stamp(item['releaseDate'])
        if not clean(title):
            raise ValueError('official title missing')
        rows.append({'url':url,'title':clean(title,300),
                     'published':date.isoformat() if kind=='binance' else None,
                     **({'created':date.isoformat()} if kind=='bitget' else {})})
    return rows


def body_text(node):
    if isinstance(node,str):
        return node
    if not isinstance(node,dict):
        return ''
    if node.get('node')=='text':
        return str(node.get('text',''))
    return ' '.join(body_text(c) for c in node.get('child',[]))


def parse_detail(raw, item, source):
    kind=source['kind']
    if kind=='binance':
        payload=json.loads(raw)
        data=payload['data']
        if payload.get('code')!='000000' or data['code']!=item['url'].rsplit('/',1)[-1] or clean(data['title'],300)!=item['title']:
            raise ValueError('Binance detail identity mismatch')
        date=stamp(data['publishDate'])
        body=data['body']
        if isinstance(body,str) and body.lstrip().startswith('{'):
            summary=body_text(json.loads(body))
        else:
            summary=Page(str(body)).root.text()
    else:
        nodes=list(Page(raw).root.walk())
        title=next((clean(n.text(),300) for n in nodes if n.tag=='h1'), '')
        # Never substitute a login page, navigation or related articles for body.
        if not title or title!=item['title']:
            raise ValueError('official detail title mismatch')
        if kind=='bitget':
            article=next((n for n in nodes if n.attrs.get('data-article-content')=='true'),None)
            created=set(re.findall(r'"longCreateTime"\s*:\s*"?(\d{13})',raw))
            if len(created)!=1 or stamp(created.pop())!=stamp(item['created']):
                raise ValueError('Bitget creation time identity mismatch')
            dates=set(re.findall(r'"(?:showTime|unifiedDisplayTime)"\s*:\s*"?(\d{13})',raw))
            if len(dates)!=1:
                raise ValueError('Bitget publication time missing/conflicting')
            date=stamp(dates.pop())
            if date<stamp(item['created']):
                raise ValueError('Bitget publication before creation')
        else:
            article=next((n for n in nodes if 'entry-content' in n.attrs.get('class','').split()),None)
            dates={n.attrs.get('content') for n in nodes if n.tag=='meta' and n.attrs.get('property')=='article:published_time'}
            if len(dates)!=1:
                raise ValueError('TradingView original publication time missing')
            date=stamp(dates.pop())  # dateModified is deliberately not used.
        if article is None:
            raise ValueError('official article body missing')
        summary=article.text()
    if item.get('published') and date!=stamp(item['published']):
        raise ValueError('official list/detail date conflict')
    summary=clean(summary)
    if len(summary)<60:
        raise ValueError('official body too short')
    return {'id':sha256(item['url'].encode()).hexdigest()[:24], 'title':item['title'],
            'summary':summary,'url':item['url'],'published':date.isoformat(),
            'source':source['name'],'official':True,'detail_parsed':True}


def collect(now, ledger, *, fetch=fetch, sources=SOURCES, max_details=MAX_DETAILS):
    """Mutate only caller-owned private source cache; persist with the existing outbox."""
    statuses=[]
    tasks=[]
    def read(source):
        try:
            rows=parse_index(fetch(source['url'],attempts=1),source)
            # The documented BG cursor is capped to three pages per category.
            if source['kind']=='bitget':
                for _ in range(2):
                    if len(rows)<10 or stamp(rows[-1]['created'])<now-timedelta(hours=24):
                        break
                    cursor=rows[-1]['url'].rsplit('/',1)[-1]
                    more=parse_index(fetch(source['url']+'&cursor='+cursor,attempts=1),source)
                    if not more or all(r['url'] in {x['url'] for x in rows} for r in more):
                        break
                    rows.extend(more)
            return rows,None
        except Exception as exc:
            return [],type(exc).__name__
    with ThreadPoolExecutor(max_workers=4) as pool:
        reads=list(pool.map(read,sources))
    for source,(rows,error) in zip(sources,reads):
        state=ledger.setdefault(source['name'],{})
        if not isinstance(state,dict):
            raise ValueError('official source cache invalid')
        status={'source':source['name'],'readable':not error,'parsed':len(rows),'detail_pending':0,'excluded_promotions':0}
        statuses.append(status)
        if error:
            status['reason']=error
            continue
        if not state:
            state.update(started_at=now.isoformat(),known=[r['url'] for r in rows],pending=[],cache=[])
            status['baseline']=True
            continue
        if not all(isinstance(state.get(k),list) for k in ('known','pending','cache')):
            raise ValueError('official source cache fields invalid')
        known=set(state['known'])|{r['url'] for r in state['pending']}
        for item in rows:
            if item['url'] not in known:
                if promotional_title(item['title']):
                    state['known'].append(item['url'])
                    status['excluded_promotions']+=1
                elif item.get('published') and stamp(item['published'])<max(stamp(state['started_at']),now-timedelta(hours=24)):
                    state['known'].append(item['url'])
                else:
                    state['pending'].append(dict(item,discovered_at=now.isoformat()))
                known.add(item['url'])
        state['pending']=[r for r in state['pending'] if stamp(r['discovered_at'])>=now-timedelta(hours=24)]
        state['cache']=[r for r in state['cache'] if stamp(r['published'])>=now-timedelta(hours=24)]
        available=[r for r in state['pending'] if not r.get('retry_at') or stamp(r['retry_at'])<=now]
        available.sort(key=lambda r:stamp(r.get('published') or r.get('created') or r['discovered_at']),reverse=True)
        tasks.append((source,state,status,available))
    # Round-robin: one busy exchange cannot consume every detail read.
    tasks.sort(key=lambda task:task[1].get('last_detail_at',''))
    chosen=[]
    for i in range(max_details):
        for source,state,status,available in tasks:
            if i<len(available) and len(chosen)<max_details:
                chosen.append((source,state,status,available[i]))
                state['last_detail_at']=now.isoformat()
    def detail(task):
        source,state,status,item=task
        url=BN+'detail/query?articleCode='+item['url'].rsplit('/',1)[-1] if source['kind']=='binance' else item['url']
        try:
            return parse_detail(fetch(url,attempts=1),item,source),None
        except Exception as exc:
            return None,type(exc).__name__
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(detail,chosen))
    for (source,state,status,item),(row,error) in zip(chosen,results):
        if error:
            item.update(error=error,retry_at=(now+timedelta(minutes=30)).isoformat())
            continue
        if stamp(row['published'])>now+timedelta(minutes=5):
            item.update(error='future_publication',retry_at=row['published'])
            continue
        state['pending'].remove(item)
        state['known'].append(item['url'])
        if max(stamp(state['started_at']),now-timedelta(hours=24))<=stamp(row['published'])<=now+timedelta(minutes=5):
            state['cache'].append(row)
    combined=[]
    for source,status in zip(sources,statuses):
        state=ledger[source['name']]
        if not state:
            continue
        state['known']=state['known'][-512:]
        pending=state['pending']
        errors=[r for r in pending if r.get('error')]
        status.update(detail_pending=len(pending),detail_errors=len(errors),cached=len(state['cache']))
        if errors:
            status.update(readable=False,reason='official_detail_unavailable')
        combined.extend(dict(r,published=stamp(r['published'])) for r in state['cache'])
    return list({r['url']:r for r in combined}.values()),statuses


def probe(now, *, fetch=fetch):
    """Independent no-state, no-send source/first-article parser check."""
    results=[]
    for source in SOURCES:
        try:
            rows=parse_index(fetch(source['url']),source)
            if not rows:
                raise ValueError('official list empty; detail not verified')
            item=rows[0]
            url=BN+'detail/query?articleCode='+item['url'].rsplit('/',1)[-1] if source['kind']=='binance' else item['url']
            row=parse_detail(fetch(url),item,source)
            results.append({'source':source['name'],'readable':True,'parsed_entries':len(rows),
                            'latest_publication':row['published'],'body_characters':len(row['summary'])})
        except Exception as exc:
            results.append({'source':source['name'],'readable':False,'reason':type(exc).__name__})
    return results
