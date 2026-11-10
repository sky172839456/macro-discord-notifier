"""Reusable action/object interpretation with quoted evidence, not article exceptions."""
import re


def has(pattern,value):
    return bool(re.search(pattern,str(value),re.I))


def connection_claim(title,summary):
    # Mentioning a technology, a patch or a research topic is not a new capability.
    clauses=re.split(r'(?<=[.!?])\s+(?=[A-Z])|[\n;]',str(title)+'\n'+str(summary))
    for clause in clauses:
        if has(r'\b(?:fixed|fixes|patched|repair|vulnerabilit\w*|breach|leak\w*|not|never|no plans|doesn.t|may|could|plans? to|proposed)\b',clause):continue
        if (has(r'\b(?:MCP|Model Context Protocol|connectors?|plugins?|plug-ins?|integration|automated workflows?)\b',clause)
                and has(r'\b(?:adds?|added|launch\w*|introduc\w*|now supports?|enables?|connects?|integrates?)\b',clause)):
            return True
    return False


def evidence(row):
    """Every feature has an actual matched source span, useful for negative tests."""
    title,summary=str(row.get('title') or ''),str(row.get('summary') or '')
    body=title+'\n'+summary
    patterns={
        '模型更新':r'\b(?:new model|added Claude|default .{0,20}model)\b',
        '設定參數':r'(?<!\w)--[a-z][a-z-]*',
        '安全修補':r'\b(?:fix(?:ed|es)?|patch(?:ed|es)?)\b',
        '預覽／測試':r'\b(?:beta|preview|prototype|pilot)\b',
        '資格／權限':r'\b(?:eligible|only|permissions?|read.only|read.write|Essential|paid plans?)\b',
        '期限／生效':r'\b(?:effective|deadline|until|begins?|starts?|ends?)\b',
        '卡號':r'\bcard (?:numbers?|details)\b',
        '住址':r'\bhome address\w*\b',
        '錢包關聯':r'\b(?:linked .{0,20}wallets?|wallet information)\b',
        '金鑰':r'\b(?:private keys?|API keys?|refresh tokens?)\b',
        '提款狀態':r'\bwithdrawals?\b',
        '樣本／比較方法':r'\b(?:benchmark|sample|controlled experiment|randomized)\b',
    }
    found={}
    for label,pattern in patterns.items():
        match=re.search(pattern,body,re.I)
        if match:found[label]=match[0]
    return found


def specific_hook(row,anchor,base,route=None):
    """Use source-supported objects; questions are production suggestions, not facts."""
    info=evidence(row)
    topic=row.get('material_topic')
    from material_editorial import editorial_angle
    angle=editorial_angle(str(row.get('title','')),str(row.get('summary','')))
    if angle:
        return base,info
    tasks=[]
    from material_share_value import TASK_NAMES
    for pattern,label in TASK_NAMES:
        if has(pattern,row.get('summary','')):tasks.append(label)
    if connection_claim(row.get('title',''),row.get('summary','')) and tasks:
        hook='這次串接的'+ '、'.join(tasks)+'流程多了哪一步，適用方案與權限有哪些限制？'
    elif topic=='security' and set(info)&{'卡號','住址','錢包關聯','金鑰'}:
        hook='原文提到的'+ '、'.join(k for k in ('卡號','住址','錢包關聯','金鑰') if k in info)+'各有什麼風險，哪些處置已確認？'
    elif topic in ('ai','innovation') and '安全修補' in info and not connection_claim(row.get('title',''),row.get('summary','')):
        hook='這次修補處理了什麼問題，受影響版本、更新方式與未解限制有哪些？'
    elif topic in ('ai','innovation') and tasks:
        hook='來源描述的'+ '、'.join(tasks)+'任務如何完成，'+('測試／預覽階段有哪些限制？' if '預覽／測試' in info else '哪些能力已開放、哪些還只是主張？')
    elif topic=='policy' and '期限／生效' in info:
        hook='適用對象與原文期限如何對照，哪些已生效、哪些仍是提案？'
    elif topic=='research' and '樣本／比較方法' in info:
        hook='原文的樣本與比較方法，能支持這個結論到什麼程度？'
    elif info:
        hook='原文提到的'+ '、'.join(list(info)[:2])+'如何影響讀者，還缺哪些證據？'
    else:
        hook=base
    return '針對「'+anchor+'」：'+hook,info


def event_profile(row):
    """Small explicit event vocabulary. Unknown/ambiguous subjects never auto-merge."""
    title=str(row.get('title') or '')
    from news_editorial import entity,dated_terms,progress_terms,scope_terms
    from content_contract import quantities
    actor=entity(title)
    if not actor:return None
    kind=phase=None
    if has(r'\b(?:trust bank|national trust|trust charter|federal trust)\b',title):
        kind='trust_charter'
        if has(r'\b(?:not|never|denied|reject\w*|withdrawn|may|could)\b',title):return None
        if has(r'\b(?:application|applies?|seeks?|pending)\b',title):phase='application'
        elif has(r'\bconditional\b',title):phase='conditional'
        elif has(r'\b(?:provisional|preliminary)\b',title):phase='preliminary'
        elif has(r'\b(?:full|final|takes effect|becomes effective)\b',title):phase='final'
    elif connection_claim(title,''):
        kind='connection'
        if has(r'\bMCP\b',title):phase='mcp'
    elif has(r'\b(?:releases?|launches?)\b',title) and re.search(r'\bv\d+\.\d+',title):
        kind='release';phase='released'
    if not kind or not phase:return None
    body=title+' '+str(row.get('summary') or '')
    authority=tuple(sorted(set(re.findall(r'\b(?:OCC|SEC|CFTC|FINMA|BaFin|FCA|MAS)\b',body))))
    objects=()
    if kind=='trust_charter':
        if not authority:return None
        objects=tuple(sorted(set(re.findall(r'\b(?:retail|institutional|conditional|provisional|national|federal)\b',title,re.I))))
    elif kind=='connection':
        from material_share_value import TASK_NAMES
        tasks=tuple(label for pattern,label in TASK_NAMES if has(pattern,body))
        tools=tuple(sorted(set(re.findall(r'\b(?:Claude|ChatGPT|TradingView|Gemini|Copilot)\b',body))))
        if not tasks or not tools:return None
        objects=(tasks,tools)
    elif kind=='release':
        target=re.search(r'\b(?:releases?|launches?)\s+(.+?)\s+v\d',title,re.I)
        if not target:return None
        objects=(target[1].casefold(),)
    return (kind,actor,phase,tuple(sorted(quantities(body).items())),
            tuple(sorted(dated_terms(body))),tuple(sorted(progress_terms(body))),
            tuple(sorted(scope_terms(body))),tuple(re.findall(r'\bv\d+(?:\.\d+)+',body)),authority,objects)


def same_structured_event(left,right):
    a,b=event_profile(left),event_profile(right)
    if not a or a!=b:return False
    from datetime import timedelta
    from notification_quality import published_time
    try:
        return abs(published_time(left['published'])-published_time(right['published']))<=timedelta(hours=24)
    except (ValueError,TypeError,KeyError,AttributeError):return False
