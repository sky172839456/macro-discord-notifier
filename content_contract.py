"""Shared source/copy contract. Deterministic evidence checks, not truth certification.

No networking or production state writes. Admission, source availability, editorial
value, transport success and human semantic acceptance remain separate results.
"""
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
import os
import re
from urllib.parse import urlsplit

VERSION = 1


def strict():
    return os.getenv('CONTENT_PREFLIGHT_STRICT', '0') == '1'


def normalized(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def source_hash(row):
    date = row.get('published')
    date = date.isoformat() if hasattr(date, 'isoformat') else date
    value = [row.get(k) for k in ('title', 'summary', 'summary_parts', 'url', 'source', 'official')]+[date]
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def segments(value, limit=450, count=2):
    """Select complete sentences; keep a following exception with its claim.

    Never cut bytes/characters, join unrelated list items, or show the first
    half of a claim whose immediately following sentence qualifies it.
    """
    value = str(value or '').strip()
    if not value:
        return []
    protected = re.sub(r'\b(?:Mt|Dr|Mr|Mrs|Ms|Prof|Inc|Corp|Ltd)\.|\b(?:[A-Z]\.){2,}|(?<=\d)\.(?=\d)',
                       lambda m:m[0].replace('.', '\u2024'),value)
    parts = [normalized(p.replace('\u2024','.')) for p in re.split(r'(?<=[.!?。！？])\s+(?=[A-Z“"\d])|[\r\n]+',protected) if p.strip()]
    groups = []
    for part in parts:
        dependent = re.match(r'^(?:but|however|except|unless|only|if|subject to|excluding|eligible|not all|this does not)\b',part,re.I)
        if dependent:
            if groups:
                groups[-1] += ' '+part
            else:
                # An orphan qualification is not a self-contained summary.
                continue
        else:
            groups.append(part)
    return [p for p in groups if len(p.encode('utf8'))<=limit and not re.search(r'(?:\.{3}|…|\b(?:because|although|unless|and|but|which|with|to))\s*$',p,re.I)][:count]


# Reusable product/syntax protection, independent of any article URL or version.
IDENTIFIERS = r'Claude Code|Claude (?:Fable|Opus|Sonnet|Haiku)|TradingView|ChatGPT|OpenAI|DeepMind|GitHub Copilot|Model Context Protocol|claude remote-control'


def asset_symbols(value):
    if not re.search(r'\b(?:holds?|mint\w*|launder\w*|crypto|coins?|tokens?)\b',value,re.I):return set()
    candidates=set(re.findall(r'\b\d[\d,.]*\s*(?:million |billion |thousand |[MBK]\s*)?([A-Z][A-Z0-9]{1,9})\b',value))
    return candidates-{'AI','API','MCP','CEO','CFO','GPU','CPU','RAM','USB','ETF','UTC','GMT','PDF','CSV'}


def protect(source):
    from news_editorial import ALIASES
    brands='|'.join(re.escape(v.title()) for variants in ALIASES.values() for v in variants)
    pattern = (r'`[^`\n]+`|(?<!\w)--[a-z][a-z-]*(?:\s*[〈<][^>〉\n]+[>〉])?'
               r'|\bv\d+\.\d+(?:\.\d+)*(?:[-.][A-Za-z0-9]+)*'
               r'|\b(?:'+IDENTIFIERS+r')\b|\b(?:BTC|ETH|NEAR|USDT|USDC|XRP|SOL|BNB|BGB)\b')
    pattern+=r'|\b(?:'+brands+r')\b|\b[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+\b'
    if asset_symbols(source):pattern+=r'|\b(?:'+'|'.join(map(re.escape,sorted(asset_symbols(source))))+r')\b'
    mapping = {}
    def replace(match):
        index = len(mapping)
        label = 'WVZX'+chr(65+index//26)+chr(65+index%26)+'ZXWV'
        mapping[label] = match[0]
        return label
    return re.sub(pattern,replace,source),mapping


def restore(value, mapping):
    for label, original in mapping.items():
        if value.count(label)!=1:
            raise ValueError('protected identifier lost or duplicated')
        value = value.replace(label,original)
    if re.search(r'WVZX[A-Z]{2}ZXWV',value):
        raise ValueError('unresolved protected identifier')
    return value


def quantities(value, symbols=None):
    """Comparable amount+denomination pairs, separate from naked number sets."""
    scales={'billion':10**9,'million':10**6,'thousand':1000,'bn':10**9,'b':10**9,'m':10**6,'k':1000,'億':10**8,'萬':10000,'千':1000}
    units={'bitcoin':'BTC','比特幣':'BTC','ether':'ETH','ethereum':'ETH','以太幣':'ETH','usd':'USD','美元':'USD','美金':'USD','eur':'EUR','歐元':'EUR','英鎊':'GBP','twd':'TWD','台幣':'TWD','新台幣':'TWD'}
    pattern=(r'(?<![A-Za-z0-9_.])(?P<currency>US\$|HK\$|C\$|A\$|[$€£])?\s*'
             r'(?P<number>[-+]?\d[\d,]*(?:\.\d+)?)\s*'
             r'(?P<scale>billion\b|million\b|thousand\b|bn\b|[bmk](?![A-Za-z])|億|萬|千)?\s*'
             r'(?:枚\s*)?(?P<unit>%|BTC(?![A-Za-z])|ETH(?![A-Za-z])|NEAR(?![A-Za-z])|USDT(?![A-Za-z])|USDC(?![A-Za-z])|XRP(?![A-Za-z])|SOL(?![A-Za-z])|BNB(?![A-Za-z])|BGB(?![A-Za-z])|bitcoin\b|ether(?:eum)?\b|USD\b|EUR\b|TWD\b|比特幣|以太幣|新台幣|台幣|美元|美金|歐元|英鎊)?')
    symbols=asset_symbols(value) if symbols is None else symbols
    if symbols:
        pattern=pattern.replace('(?P<unit>','(?P<unit>(?:'+'|'.join(map(re.escape,sorted(symbols)))+r')(?![A-Za-z])|',1)
    found=Counter()
    for m in re.finditer(pattern,value,re.I):
        c,n,s,u=(m[k] or '' for k in ('currency','number','scale','unit'))
        if not c and not u:
            continue
        amount=Decimal(n.replace(',',''))*scales.get(s.lower(),1)
        unit=units.get(u.lower(),u.upper()) if u else {'$':'USD','US$':'USD','€':'EUR','£':'GBP','HK$':'HKD','C$':'CAD','A$':'AUD'}.get(c,c)
        found[(unit,amount)]+=1
    return found


def segment_issues(source, copy):
    """Check the same full source segment, never a union of unrelated bullets."""
    issues=[]
    if len(copy)>max(180,len(source)*2.5):issues.append('translation_expansion')
    prose=copy
    _,identifiers=protect(source)
    for value in identifiers.values():prose=prose.replace(value,'')
    if len(re.findall(r'(?<![A-Za-z])(?:added|fixed|exposes?|launches?|approves?|denies?|withdrawals?|balances?|hackers?|launderers?|memecoins?|funds?|customers?|users?|available|following|because|which|while|with|and|the|to|from)(?![A-Za-z])',prose,re.I))>=3:
        issues.append('untranslated_prose')
    if re.search(r'\ufffd|&(?:amp|lt|gt|quot|#\d+);|WVZX[A-Z]{2}ZXWV',copy):issues.append('encoding_or_placeholder')
    if re.search(r'(?:\.{3}|…)\s*$',copy):issues.append('truncated_copy')
    symbols=asset_symbols(source)
    source_units,copy_units=quantities(source,symbols),quantities(copy,symbols)
    if source_units!=copy_units:issues.append('quantity_unit_mismatch')
    def quarters(value):
        result=set(re.findall(r'\bQ([1-4])\b',value,re.I))
        result.update({'一':'1','二':'2','三':'3','四':'4'}.get(q,q) for q in re.findall(r'第?([一二三四1-4])季',value))
        for word,num in (('first','1'),('second','2'),('third','3'),('fourth','4')):
            if re.search(r'\b'+word+r' quarter\b',value,re.I):result.add(num)
        return result
    if quarters(source) and quarters(source)!=quarters(copy):issues.append('reference_period_mismatch')
    annual=bool(re.search(r'\b(?:annualized|annual rate|APR|APY|per annum)\b',source,re.I))
    if annual and not re.search(r'年化|年率|APR|APY',copy,re.I):issues.append('rate_basis_missing')
    if not annual and re.search(r'\b(?:funding rate|per period|per \d+ hours?)\b',source,re.I) and re.search(r'年化|年率|APR|APY',copy,re.I):issues.append('rate_basis_invented')
    for v in re.findall(r'\bv\d+\.\d+(?:\.\d+)*(?:[-.][A-Za-z0-9]+)*',source):
        if v not in copy:issues.append('version_missing')
    for code in re.findall(r'`([^`\n]+)`',source):
        if code.replace('<','〈').replace('>','〉') not in copy.replace('<','〈').replace('>','〉'):issues.append('code_identifier_missing')
    qualifiers=(
        (r'(?<![-.])\bonly\b|\b(?:eligible|excluding|except|subject to)\b',r'僅|只|唯一|限|合資格|符合資格|除外|不含|不包括|須|需|取決'),
        (r'\b(?:up to|at most)\b',r'最多|最高|上限|至多|高達'),
        (r'\b(?:at least)\b',r'至少|最低|下限'),
        (r'\bread.only\b',r'唯讀|只讀|僅.*讀取'),
        (r'\b(?:prototype|proof.of.concept)\b',r'原型|概念驗證'),
        (r'\b(?:beta|preview)\b',r'測試|預覽|beta|preview'),
        (r'\b(?:conditional|provisional|preliminary approval)\b',r'附條件|有條件|初步|暫准|尚須|尚需'),
    )
    for src,dst in qualifiers:
        if re.search(src,source,re.I) and not re.search(dst,copy,re.I):issues.append('scope_or_stage_missing')
    # A global 不 elsewhere in a paragraph cannot excuse a reversed key claim.
    for concept,english,chinese,negative in (
        ('approval',r'(?:not|never|yet to|hasn.t)\s+(?:been\s+)?approv\w*',r'核准|批准|通過',r'(?:不|未|否認|拒絕).{0,8}(?:核准|批准|通過)'),
        ('withdrawal',r'withdrawals?.{0,30}(?:not|never|yet to|hasn.t).{0,20}resum\w*',r'恢復.{0,6}提款|提款.{0,6}恢復',r'(?:不|未).{0,8}恢復.{0,6}提款|提款.{0,8}(?:不|未).{0,6}恢復'),
        ('recovery',r'(?:not|never|yet to|hasn.t)\s+(?:been\s+)?recover\w*',r'追回|收回|歸還',r'(?:不|未|否認).{0,8}(?:追回|收回|歸還)'),
    ):
        if re.search(english,source,re.I):
            clauses=[s for s in re.split(r'[。；;!?\n]',copy) if re.search(chinese,s)]
            if not clauses or any(not re.search(negative,s) for s in clauses):issues.append('claim_polarity_'+concept)
    return list(dict.fromkeys(issues))


def stamp(row, pairs, basis='rss'):
    row['content_contract']={'version':VERSION,'source_hash':source_hash(row),'basis':basis,'pairs':pairs}
    return row


def article_issues(row, now=None, required=None):
    required=strict() if required is None else required
    proof=row.get('content_contract')
    if not proof:
        return ['source_copy_evidence_missing'] if required else []
    errors=[]
    if proof.get('version')!=VERSION or proof.get('source_hash')!=source_hash(row):errors.append('stale_source_evidence')
    try:
        parsed=urlsplit(str(row.get('url') or ''))
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:errors.append('invalid_source_url')
        from notification_quality import published_time
        at=published_time(row.get('published'))
        if at.tzinfo is None:errors.append('source_timezone_missing')
        elif now and (at>now+timedelta(minutes=5) or at<now-timedelta(hours=24)):errors.append('source_outside_window')
    except (ValueError,TypeError,AttributeError):errors.append('invalid_source_time')
    pairs=proof.get('pairs') or []
    if not pairs:errors.append('source_copy_pairs_missing')
    if proof.get('complete_selected_excerpt') is False:errors.append('incomplete_selected_excerpt')
    displayed=row.get('summary_zh_points') or []
    if [p.get('zh') for p in pairs]!=displayed:errors.append('display_evidence_mismatch')
    basis=str(row.get('title') if proof.get('basis')=='headline' else row.get('summary') or '')
    parts=row.get('summary_parts') or []
    sources=[normalized(basis),*[normalized(p) for p in parts]]
    from news_auto_recovery import checked_copy
    for pair in pairs:
        source=str(pair.get('source') or '')
        if len(source.encode('utf8'))>450:errors.append('excerpt_exceeds_provider_limit')
        if not source or not any(normalized(source) in original for original in sources):errors.append('excerpt_not_in_source')
        try:checked_copy(source,str(pair.get('zh') or ''))
        except (ValueError,TypeError):errors.append('segment_translation_invalid')
    try:checked_copy(str(row.get('title') or ''),str(row.get('title_zh') or ''))
    except (ValueError,TypeError):errors.append('title_translation_invalid')
    return list(dict.fromkeys(errors))


def utf16(value):
    return len(str(value).encode('utf-16-le'))//2


def payload_issues(cards):
    """Validate the actual final payload after layout; never trim it to pass."""
    errors=[];total=0
    if not isinstance(cards,list) or not 1<=len(cards)<=10:return ['embed_count']
    for card in cards:
        strings=[]
        for value,limit in ((card.get('title',''),256),(card.get('description',''),4096),((card.get('author') or {}).get('name',''),256),((card.get('footer') or {}).get('text',''),2048)):
            if utf16(value)>limit:errors.append('text_limit')
            strings.append(str(value))
        fields=card.get('fields') or []
        if len(fields)>25:errors.append('field_count')
        for field in fields:
            for key,limit in (('name',256),('value',1024)):
                value=str(field.get(key) or '')
                if not value or utf16(value)>limit:errors.append('field_limit_or_empty')
                strings.append(value)
        text='\n'.join(strings);total+=sum(utf16(s) for s in strings)
        if re.search(r'\ufffd|WVZX[A-Z]{2}ZXWV|&(?:amp|lt|gt|quot|#\d+);',text):errors.append('payload_encoding')
        if re.search(r'https?://(?:[^/]+\.)?discord(?:app)?\.com/api/webhooks/|\b(?:sk-proj-|service_role\s*[=:])',text):errors.append('secret_in_payload')
        plain=re.sub(r'[*_`]', '', text)
        if re.search(r'(?im)(?:^|[:：])\s*(?:nan|[+-]?infinity|undefined|null)\s*(?:美元|USDT|%)?\s*$',plain):errors.append('nonfinite_or_missing_value')
    if total>6000:errors.append('embed_total_limit')
    return list(dict.fromkeys(errors))


def require_payload(cards):
    errors=payload_issues(cards)
    if errors:raise ValueError('content preflight: '+','.join(errors))


def final_article_issues(rows, card, now=None):
    errors=payload_issues([card])
    text='\n'.join([str(card.get('title','')),str(card.get('description','')),
                     *[str(f.get('name',''))+'\n'+str(f.get('value','')) for f in card.get('fields',[])]])
    for row in rows:
        errors+=article_issues(row,now)
        if row.get('content_contract'):
            # A formatter must not silently cut a verified sentence/condition.
            points=row.get('summary_zh_points') or []
            if points and not all(p in text for p in points):errors.append('render_cut_verified_copy')
            if row.get('title_zh') and row['title_zh'] not in text:errors.append('render_cut_verified_title')
            if row.get('url') not in text:errors.append('render_source_missing')
    return list(dict.fromkeys(errors))


def record_preflight(state, rows, card, now):
    """One per-run machine ledger; article IDs only, never members or secrets."""
    if not strict():return True
    errors=final_article_issues(rows,card,now)
    audit=state.setdefault('content_preflight_status',{'at':now.isoformat(),'checked':0,'passed':0,'held':0,'reasons':{}})
    audit['checked']+=len(rows)
    audit['held' if errors else 'passed']+=len(rows)
    for error in errors:audit['reasons'][error]=audit['reasons'].get(error,0)+len(rows)
    if errors:
        audit.setdefault('held_articles',[]).extend({'id':str(row.get('id','')),'reasons':errors} for row in rows)
        audit['held_articles']=audit['held_articles'][-20:]
    return not errors
