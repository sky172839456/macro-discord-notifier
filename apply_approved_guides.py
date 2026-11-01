"""Only GET two explicitly authorized guide messages; report anonymous structure."""
import json
import os
import hashlib
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse

def get(url):
    try:
        with urlopen(Request(url,headers={'User-Agent':'WV-guide-structure-audit/1.0'}),timeout=25) as response:
            return json.load(response)
    except Exception as error:
        raise RuntimeError('GET_failed_'+str(getattr(error,'code','unknown'))) from None

rows=json.loads(Path('approved_guides.json').read_text(encoding='utf-8'))
results=[]
for row in rows:
    hook=os.environ[row['secret']].rstrip('/')
    assert urlparse(hook).hostname in ('discord.com','discordapp.com')
    meta=get(hook)
    assert meta['channel_id']==row['channel']
    message=get(hook+'/messages/'+row['id'])
    assert message['id']==row['id'] and message['channel_id']==row['channel']
    content=message.get('content','')
    embeds=message.get('embeds',[])
    public_copy=content+' '.join(str(e.get('title',''))+' '+str(e.get('description',''))+' '+str(e.get('fields','')) for e in embeds)
    result={'messageId':message['id'],'pinned':message.get('pinned'),
            'contentLength':len(content),'embedCount':len(embeds),
            'componentCount':len(message.get('components',[])),
            'contentContainsGuide':'頻道指南' in content,
            'embedContainsGuide':'頻道指南' in public_copy,
            'targetChannelNamePresent':('數據有話說' if row['key']=='macro' else '行情醒腦室') in public_copy,
            'ownedByConfiguredWebhook':message.get('webhook_id')==meta['id'],
            'contentHash':hashlib.sha256(content.encode()).hexdigest(),
            'embedShapes':[{'descriptionLength':len(e.get('description','')),'fields':len(e.get('fields',[]))} for e in embeds],
            'originalMessageTime':message.get('timestamp'),'editedTime':message.get('edited_timestamp'),
            'writes':0}
    print(json.dumps(result))
    results.append(result)
Path('approved-guide-result.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
