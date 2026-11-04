"""Reformat exactly four existing pinned guides; never post messages."""
import hashlib,json,os,re
from routing_audit import EXPECTED
from webhook_branding import api,validate
LINE='──────────────'
TARGETS=(('DISCORD_WEBHOOK_URL','1560879858110824489'),
         ('DISCORD_CRYPTO_NEWS_WEBHOOK_URL','1560878046884667483'),
         ('DISCORD_FINANCE_NEWS_WEBHOOK_URL','1560879859604004926'),
         ('DISCORD_DAILY_SUMMARY_WEBHOOK_URL','1560879861248036926'))

def layout(value):
    value=re.sub(r'(?<!\]\()(?<!\[)https://www\.wviewture\.com/?(?![\w/.-])',
                 '[https://www.wviewture.com](https://www.wviewture.com/)',value)
    result=[]
    for part in re.split(r'\n{2,}',value):
        if result and re.match(r'^(?:#{1,3} |\*\*[^*]+\*\*|📌)',part) and result[-1]!=LINE:
            result.append(LINE)
        result.append(part)
    return '\n\n'.join(result)

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def run(environ=None,call=api):
    env=os.environ if environ is None else environ
    plans=[]
    for secret,message_id in TARGETS:
        webhook=env.get(secret)
        if not webhook:raise ValueError('guide connection missing')
        meta=call(webhook);validate(meta,EXPECTED[secret])
        route=webhook+'/messages/'+message_id
        before=call(route)
        if (str(before.get('id'))!=message_id or str(before.get('channel_id'))!=EXPECTED[secret]
            or str(before.get('webhook_id'))!=str(meta['id']) or not before.get('pinned')
            or before.get('embeds') or before.get('components') or not before.get('content')):
            raise ValueError('guide identity mismatch')
        content=layout(before['content'])
        if len(content)>2000:raise ValueError('guide length exceeded')
        plans.append(dict(route=route,content=content,before=before,
                          summary=dict(message_id=message_id,channel_id=EXPECTED[secret],before_hash=digest(before['content']),after_hash=digest(content))))
    summaries=[p['summary'] for p in plans]
    plan_hash=digest(json.dumps(summaries,sort_keys=True))
    apply=env.get('APPLY_GUIDE_LAYOUT')=='true'
    if apply:
        if env.get('EXPECTED_GUIDE_PLAN_HASH')!=plan_hash:raise ValueError('guide plan changed')
        for p in plans:
            current=call(p['route'])
            if current['content']!=p['before']['content'] or not current.get('pinned'):raise ValueError('guide changed before apply')
        for p in plans:
            if p['content']!=p['before']['content']:call(p['route'],{'content':p['content'],'allowed_mentions':{'parse':[]}})
            after=call(p['route'])
            if after.get('content')!=p['content'] or not after.get('pinned') or after.get('webhook_id')!=p['before']['webhook_id']:raise ValueError('guide readback mismatch')
    return dict(applied=apply,plan_hash=plan_hash,messages=summaries,new_messages=0,state_access=False)

if __name__=='__main__':
    try:print(json.dumps(run(),ensure_ascii=False))
    except Exception as e:
        print(json.dumps(dict(failed=True,error_type=type(e).__name__,http_status=getattr(e,'code',None))))
        raise SystemExit(1)
