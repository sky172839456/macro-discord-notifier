"""One-off user-approved update of exactly two existing pinned guides."""
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse

rows=json.loads(Path('approved_guides.json').read_text(encoding='utf-8'))
expected={('1524973145780654091','1560879858110824489'),('1526037827115028622','1560879861248036926')}
assert {(r['channel'],r['id']) for r in rows} == expected and len(rows)==2
expected_hashes={
    '1560879858110824489':'ba1f4824916db25ede918c3b494532085a5c9ad6b199e3bf612b3b3ea60ccc03',
    '1560879861248036926':'705fc6ed6cda6328a9956ac8b3674bf2e7fde179d3907e3e63e2b9172e13ea62',
}

def request(url, method='GET', data=None):
    req=Request(url, method=method, headers={'Content-Type':'application/json','User-Agent':'WV-approved-guide-maintenance/1.0'},
                data=json.dumps(data,ensure_ascii=False).encode('utf-8') if data is not None else None)
    try:
        with urlopen(req,timeout=25) as response:
            return json.load(response)
    except Exception as error:
        # Never print the request URL or exception string containing a webhook.
        raise RuntimeError(f'{method}_failed_http_{getattr(error,"code","unknown")}') from None

checks=[]
for row in rows:
    hook=os.environ[row['secret']].rstrip('/')
    parsed=urlparse(hook)
    assert parsed.scheme=='https' and parsed.hostname in ('discord.com','discordapp.com')
    info=request(hook)
    assert info['channel_id']==row['channel'] and info['guild_id']=='1524947809499877486'
    route=hook+'/messages/'+row['id']
    old=request(route)
    assert old['id']==row['id'] and old['channel_id']==row['channel'] and old['pinned']
    old_hash=hashlib.sha256(old.get('content','').encode()).hexdigest()
    new_hash=hashlib.sha256(row['content'].encode()).hexdigest()
    assert old_hash in (expected_hashes[row['id']],new_hash)
    assert old.get('webhook_id')==info['id'] and not old.get('components') and not old.get('embeds')
    assert len(row['content'])<2000
    checks.append((row, route, old))

results=[]
for row,route,old in checks:
    current=request(route)
    assert current['content']==old['content'] and current['pinned']
    before_hash=hashlib.sha256(old['content'].encode()).hexdigest()
    if current['content']!=row['content']:
        request(route,'PATCH',{'content':row['content'],'allowed_mentions':{'parse':[]}})
    after=request(route)
    assert after['id']==row['id'] and after['pinned'] and after['content']==row['content']
    results.append({'messageId':after['id'],'time':after.get('edited_timestamp'),
                    'contentMatches':True,'pinned':True,'beforeHash':before_hash,
                    'afterHash':hashlib.sha256(row['content'].encode()).hexdigest(),
                    'newMessages':0,'permissionsChanged':False})
    print(json.dumps(results[-1]))
Path('approved-guide-result.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
