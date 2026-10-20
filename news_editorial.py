"""Conservative editorial gates. No LLM facts, price forecasts or external state."""
from __future__ import annotations

import re
from datetime import timedelta

from notification_quality import published_time, TAIPEI

ALIASES = {
    'circle': ('circle',),
    'payward': ('payward', 'kraken'), 'ledger': ('ledger',), 'trezor': ('trezor',),
    'strategy': ('strategy', 'microstrategy'), 'bitmine': ('bitmine',),
    'coinbase': ('coinbase',), 'binance': ('binance',), 'bybit': ('bybit',),
    'bitget': ('bitget',), 'okx': ('okx',), 'metamask': ('metamask',),
    'solana': ('solana',), 'ethereum': ('ethereum',), 'blackrock': ('blackrock',),
    'standard_chartered': ('standard chartered',),
}
ASSET_CONTEXT = r'\b(?:crypto|bitcoin|btc|ether(?:eum)?|defi|token|wallet|stablecoin|usdt|usdc|tether|circle|exchange|ledger|trezor|metamask|coinbase|binance|bybit|bitget|kraken|okx)\b'
INCIDENT = r'\b(?:unauthori[sz]ed (?:token )?(?:mint(?:ing)?|issuance)|hack(?:s|ed|ing)?|exploit(?:s|ed|ation)?|breach(?:es)?|drain(?:s|ed)?|phishing|stolen|stole|thefts?|wrench attacks?|knife assault|tamper(?:ed|ing)?|implants?|compromis(?:ed|e)|vulnerabilit(?:y|ies)|malicious firmware|supply.chain attacks?|withdrawals? (?:halted|suspended|paused)|major outage|depeg(?:s|ged)?)\b'
HISTORY = r'\b(?:jailed|sentenced|anniversary|last year|years? ago|historical|retrospective)\b'
EXPLAINER = r'^(?:why|how|what|can|opinion[:：]|explained[:：])\b|\b(?:explainer|price prediction|could reach|will hit|safest wallets?)\b'
ACTION = r'\b(?:pull|recall|halt(?:ed|s)?|suspend(?:ed|s)?|paus(?:e|ed|es)|warn(?:s|ed)?|confirm(?:s|ed)?|report(?:s|ed)?|discover(?:s|ed)?|detect(?:s|ed)?|investigat\w*|claimed|lost|steal|stole|stolen|drain(?:s|ed)?|hack(?:s|ed|ing)?|exploit(?:s|ed)?|breach(?:es)?|implants?|tamper(?:ed|ing)?|major outage|depeg(?:s|ged)?)\b'


def text(item):
    return f"{item.get('title', '')} {item.get('summary', '')}"


def acquisition_with_only_old_incident(value):
    """An acquisition's explicitly older hack is background, not a new alert."""
    if not re.search(r'\b(?:acquisition|acquires?|acquiring|merger)\b', value, re.I):
        return False
    historical = (r'\b(?:(?:\d+|a|several|two|three|a few)\s+)?'
                  r'(?:weeks?|months?|years?)\s+(?:after|following)\s+'
                  r'(?:(?:a|the)\s+)?(?:\$?\d[\d,.]*(?:\s?(?:million|billion|[mbk]))?\s+)?'
                  r'(?:crypto\s+)?(?:hack|exploit|breach|attack|theft)\b')
    remaining, count = re.subn(historical, ' ', value, flags=re.I)
    if not count:
        return False
    # 舊事故可作收購背景；同篇損失、受害者或資金處置仍走原資安檢查。
    progress = (r'\b(?:loss(?:es)?|lost|damage\w*|victims?|affected|impacted|'
                r'recover\w*|compensat\w*|reimburs\w*|refund\w*|restitut\w*|'
                r'recoup\w*|repatriat\w*|freez\w*|froze\w*|seiz\w*|unfreez\w*|'
                r'(?:funds?|assets?)\s+(?:(?:have|has|been|were|are|being|now)\s+){0,4}return\w*|'
                r'return\w*\s+(?:the\s+)?funds?|'
                r'(?:additional|more)\s+(?:customers?|users?|wallets?|accounts?)|'
                r'ongoing\s+attack|active\s+attack|new\s+incident|'
                r'revised\s+estimat\w*|updated\s+estimat\w*)\b')
    return not (re.search(INCIDENT, remaining, re.I)
                or re.search(progress, remaining, re.I)
                or re.search(r'\b(?:recall\w*|halt\w*|suspend\w*|paus\w*|resum\w*|restor\w*)\b', remaining, re.I))


def current_safety_evidence(item):
    """A report containing an explicit new incident still enters the safety inbox."""
    return any(re.search(r'\b(?:new|today|ongoing|active|currently)\b', sentence, re.I)
               and re.search(INCIDENT, sentence, re.I)
               and re.search(ACTION, sentence, re.I)
               for sentence in re.split(r'[.;!?]', text(item)))


def retrospective(item):
    title = str(item.get('title', ''))
    period = re.search(r'\b(?:q[1-4]|quarter(?:ly)?|annual|year.end|year.in.review)\b', title, re.I)
    review = re.search(r'\b(?:reports?|reviews?|recaps?|losses|hacks|exploits|statistics|total|push)\b', title, re.I)
    historical = bool(re.search(HISTORY, title, re.I) or (period and review))
    return historical and not current_safety_evidence(item)


def event_kind(item):
    """One shared urgency decision; background keywords cannot bypass review."""
    title = str(item.get('title', ''))
    if retrospective(item):
        return 'retrospective'
    if safety_candidate(item):
        return 'safety'
    if re.search(EXPLAINER, title, re.I):
        return 'ordinary'
    decision = re.search(r'\b(?:approves?|approved|rejects?|rejected|enacted|court orders|files for bankruptcy)\b', title, re.I)
    authority = re.search(r'\b(?:sec|regulator|court|etf|exchange|law|bill)\b', title, re.I)
    return 'decision' if decision and authority else 'ordinary'


def safety_candidate(item):
    """Protect current asset-safety candidates before generic relevance/exclusions."""
    title, body = str(item.get('title', '')), text(item)
    if acquisition_with_only_old_incident(body):
        return False
    if retrospective(item) or (re.search(EXPLAINER, title, re.I) and not current_safety_evidence(item)):
        return False
    if not re.search(INCIDENT, title, re.I) and not re.search(r'\b(?:pull|recall|halt\w*|suspend\w*|paus\w*|resellers?)\b', title, re.I):
        return False  # A background attack mentioned in a tax story is not a new incident.
    return bool(re.search(ASSET_CONTEXT, body, re.I) and re.search(INCIDENT, body, re.I)
                and re.search(ACTION, body, re.I))


def review_reason(item):
    if not safety_candidate(item):
        return None
    if not item.get('official'):
        return '媒體資安候選，尚未由直接官方來源核對'
    if re.search(r'\b(?:suspected|alleged|unconfirmed|rumou?r|may|could|potential|possibly)\b', text(item), re.I):
        return '官方內容仍含未確認範圍，先核對再發布'
    from notification_quality import digest_exclusion_reason
    if digest_exclusion_reason(item):
        return '資安公告中文內容未核對，保留原文等待確認'
    return None


def entity(value):
    matches = []
    for key, variants in ALIASES.items():
        for variant in variants:
            match = re.search(rf'\b{re.escape(variant)}\b', value, re.I)
            if match:
                matches.append((match.start(), key))
    return min(matches)[1] if matches else None


def stage(value):
    for name, pattern in (
        ('recovered', r'\b(?:recovered|funds returned|repaid|compensated)\b'),
        ('resumed', r'\b(?:resumes?|resumed|restores?|restored|resolved|reopens?|reopened)\b'),
        ('cancelled', r'\b(?:cancelled|canceled|rejects?|rejected|blocks?|blocked|denied)\b'),
        ('completed', r'\b(?:completed|completes|closes acquisition|closed acquisition|finalized)\b'),
        ('approved', r'\b(?:approved|approves|approval granted)\b'),
        ('halted', r'\b(?:halt(?:ed|s)?|suspend(?:ed|s)?|paus(?:ed|e)|recall|pull devices)\b'),
    ):
        if re.search(pattern, value, re.I):
            return name
    return 'reported'


def first_swiss_retail_bitcoin_approval(item):
    """Only the two unqualified descriptions of Switzerland's first retail approval."""
    title = str(item.get('title', '')).replace('’', "'").strip()
    patterns = (
        r"FINMA approves Switzerland's first Bitcoin (?:ETF|exchange-traded fund) for retail investors",
        r"Swiss Regulator Approves (?:Switzerland's )?First Retail Fund That Holds Bitcoin Directly",
    )
    return any(re.fullmatch(pattern, title, re.I) for pattern in patterns)


def swiss_approval_has_unresolved_update(item):
    """A product identity or material development needs its own review."""
    summary = str(item.get('summary', ''))
    if re.search(r'\b(?:new|updated|revised|amended|additional|another|second|third|launch\w*|'
                 r'list(?:ed|ing|s)?|start\w*|begin\w*|trad(?:e|ing)|conditional|subject to|pending|'
                 r'effective|withdraw\w*|cancel\w*|revok\w*|halt\w*|suspend\w*|tighten\w*|'
                 r'restrict\w*|lift\w*|issuer|issued by|managed by|fund named|fund called|ticker)\b',
                 summary, re.I):
        return True
    # 未知發行人／基金專名不能因相同監管機關而被吞掉。
    names = set(re.findall(r'\b[A-Z][A-Za-z0-9]+\b', summary))
    return bool(names - {'The', 'Swiss', 'FINMA', 'Bitcoin', 'ETF', 'ETFs'})


def event_key(item):
    """Narrow high-confidence event keys; unsupported events use guarded title overlap."""
    title, body = str(item.get('title', '')), text(item)
    if first_swiss_retail_bitcoin_approval(item):
        return 'swiss_first_retail_approval', 'finma', 'btc'
    actor = entity(title) or entity(body)
    if not actor:
        return None
    # 僅合併同一 Circle 市場擴張計畫；不同數量、區域或落地進展保留。
    if (actor == 'circle' and re.search(r'\b(?:plans?|planning|looking to enter|aims?|seeks?)\b', title, re.I)
            and not re.search(r'\b(?:approved|approval|authorization|licen[cs]e|launch(?:ed|es)?|entered|enters|completed)\b', body, re.I)):
        count = re.search(r'\b(\d+)\s+(?:(?:new|emerging|developing|and)\s+)*markets\b', body, re.I)
        regions = {name for name, pattern in (
            ('southeast_asia', r'\bsouth(?:east| east) asia\b'),
            ('latin_america', r'\blatin americ(?:a|an)\b'),
            ('africa', r'\bafrica\b'),
            ('middle_east', r'\bmiddle east\b'),
        ) if re.search(pattern, body, re.I)}
        if count and regions:
            return 'market_expansion', actor, count.group(1) + ':' + '+'.join(sorted(regions))
    if re.search(r'\b(?:opens?|unlocks?|expands?|launch(?:es)?|offers?)\b', title, re.I) and re.search(r'\btrading\b', title, re.I):
        assets = set(re.findall(r'\b(?:bitcoin|btc|ether|ethereum|eth|usdt|usdc|rlusd)\b', title.lower()))
        assets = {'btc' if a == 'bitcoin' else 'eth' if a in {'ether', 'ethereum'} else a for a in assets}
        if assets:
            return 'trading', actor, '+'.join(sorted(assets))
    # Require a transaction verb paired with its target, not a bare company mention.
    deal = re.search(r'(?i:\b(?:buy|buys|buying|acquire[sd]?|acquiring|acquisition of)\s+(?:(?:Lithuania[’\']s|Lithuanian|the)\s+)?)([A-Z][\w-]+(?:\s+Bank)?)', body)
    if deal and re.search(r'\b(?:buy|acquir\w*|deal)\b', title, re.I):
        target = deal.group(1).lower()
        if target not in {'bitcoin', 'btc', 'ethereum', 'ether', 'eth', 'sol', 'xrp', 'eu', 'us'}:
            return 'acquisition', actor, target
    if re.search(r'\b(?:withdrawals?|deposits?)\b', title, re.I) and re.search(r'\b(?:halt\w*|suspend\w*|paus\w*|resum\w*|restor\w*|unavailable)\b', title, re.I):
        service = 'withdrawals' if re.search(r'\bwithdrawals?\b', title, re.I) else 'deposits'
        return 'service', actor, service
    if re.search(INCIDENT, title, re.I):
        if re.search(r'\b(?:devices?|implants?|resellers?|firmware|hardware wallet|supply.chain|tamper)\b', body, re.I):
            return 'security', actor, 'device'
        return 'security', actor, 'incident'
    if re.search(r'\b(?:adds?|buys?|bought|purchases?|scoops? up|accumulat\w*)\b', title, re.I):
        asset = 'btc' if re.search(r'\b(?:bitcoin|btc)\b', title, re.I) else 'eth' if re.search(r'\b(?:ether|ethereum|eth)\b', title, re.I) else None
        if asset and actor in {'strategy', 'bitmine'}:
            return 'purchase', actor, asset
    return None


def measures(value):
    """Keep units and currencies. Quantities in unrelated summaries never erase updates."""
    scales = {'billion': 1e9, 'million': 1e6, 'thousand': 1e3, 'b': 1e9, 'm': 1e6, 'k': 1e3}
    found = set()
    for currency, number, scale, unit in re.findall(
        r'(?<![\w.])([$€£]?)\s*(\d[\d,]*(?:\.\d+)?)\s*(billion\b|million\b|thousand\b|[bmk]\b)?\s*(%|btc\b|bitcoin\b|eth\b|ether\b|usd\b|eur\b)?', value, re.I
    ):
        if not (currency or scale or unit):
            continue
        amount = float(number.replace(',', '')) * scales.get(scale.lower(), 1)
        denomination = currency or {'bitcoin': 'btc', 'ether': 'eth', 'usd': '$', 'eur': '€'}.get(unit.lower(), unit.lower()) or 'count'
        found.add((denomination, amount))
    return found


def dated_terms(value):
    return set(re.findall(r'\b(?:20\d{2}|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+\d{1,2}|q[1-4])\b', value.lower()))


def progress_terms(value):
    return {name for name, pattern in (
        ('conditional', r'\b(?:subject to|pending regulatory|if approved)\b'),
        ('authorization', r'\b(?:won|secured|obtained)\b.{0,45}\b(?:approval|authorization|licen[cs]e)\b'),
        ('confirmed_loss', r'\b(?:confirmed loss|losses confirmed|confirmed.*stolen)\b'),
        ('suspected', r'\b(?:suspected|alleged|unconfirmed)\b'),
        ('new_restriction', r'\b(?:withdrawals? (?:halted|suspended)|devices? recalled)\b'),
    ) if re.search(pattern, value, re.I)}


def scope_terms(value):
    tokens = set(re.findall(r'\b(?:btc|bitcoin|eth|ether|ethereum|solana|usdt|usdc|europe|asia|germany|france|japan|korea|us|uk|uae|retail clients|new firmware|additional users|all users|all chains|spreads? to)\b', value.lower()))
    normalized = {'bitcoin': 'btc', 'ethereum': 'eth', 'ether': 'eth'}
    tokens = {normalized.get(v, v) for v in tokens}
    tokens.update(re.findall(r'\b\d[\d,]*\s+(?:users|wallets|devices|markets|countries)\b', value.lower()))
    return tokens


def equivalent(left, right, fallback=None):
    """Only suppress near-time repeats; changes of stage/amount/conditions stay visible."""
    if left.get('published') and right.get('published'):
        if abs(published_time(left['published']) - published_time(right['published'])) > timedelta(hours=24):
            return False
    a, b = str(left.get('title', '')), str(right.get('title', ''))
    if same_victim_episode(left, right):
        return True
    key_a, key_b = event_key(left), event_key(right)
    # A known mismatch must not be overridden by a bag-of-words fallback.
    if (key_a or key_b) and key_a != key_b:
        return False
    if not key_a:
        # Similar wording from distinct agencies/companies is not one event.
        if entity(a) != entity(b):
            return False
        stop = {'The', 'A', 'An', 'After', 'Before', 'New', 'Major', 'Crypto', 'Bitcoin', 'Ethereum'}
        def named_subject(value):
            return next((word for word in re.findall(r'\b[A-Z][A-Za-z0-9]+\b', value) if word not in stop), None)
        if named_subject(a) != named_subject(b):
            return False
    if key_a and key_a[0] == 'swiss_first_retail_approval':
        if any(swiss_approval_has_unresolved_update(row) for row in (left, right)):
            return False
    if stage(text(left)) != stage(text(right)):
        return False
    if key_a and key_a[0] == 'market_expansion':
        x, y = scope_terms(text(left)), scope_terms(text(right))
        assets = {'btc', 'eth', 'solana', 'usdt', 'usdc', 'eurc', 'rlusd'}
        # 同一狹義計畫可補齊缺省的幣種名稱，明確矛盾的幣種仍保留新件。
        explicit = [set(re.findall(r'\b(?:usdc|usdt|eurc|rlusd)\b', text(row), re.I)) for row in (left, right)]
        explicit = [{v.lower() for v in group} | (scope & assets) for group, scope in zip(explicit, (x, y))]
        if x - assets != y - assets or (explicit[0] and explicit[1] and explicit[0] != explicit[1]):
            return False
    if key_a and key_a[0] in {'security', 'service', 'trading'} and scope_terms(text(left)) != scope_terms(text(right)):
        return False
    for extract in (measures, dated_terms, progress_terms):
        # For acquisitions a bank's total assets in a summary are not deal price.
        def evidence(row, title):
            if key_a and key_a[0] == 'acquisition' and extract is measures:
                price = re.findall(r'\b(?:deal|transaction|acquisition|purchase)\s+(?:price|valued|worth|for|at|value)[^.]{0,90}', str(row.get('summary', '')), re.I)
                return title + ' ' + ' '.join(price)
            return text(row)
        x, y = extract(evidence(left, a)), extract(evidence(right, b))
        if x != y:
            if key_a and key_a[0] == 'acquisition' and extract in (dated_terms, progress_terms) and (not x or not y):
                # Missing timeline/conditions may be complementary reporting. The merger
                # retains the fuller context; conflicting explicit terms stay separate.
                continue
            # Missing evidence is not evidence that numbers/conditions agree.
            if key_a and key_a[0] == 'purchase' and extract is measures:
                # A source may express purchase size in dollars instead of coins.
                common = {u for u, _ in x} & {u for u, _ in y}
                if all({n for u, n in x if u == unit} == {n for u, n in y if u == unit} for unit in common):
                    continue
            return False
    if key_a:
        return True
    return bool(fallback and fallback(a, b))


def member_ids(item):
    return list(dict.fromkeys([item['id'], *item.get('merged_ids', [])]))


def same_victim_episode(left, right):
    """One source-qualified scammer profile, never global amount tolerance."""
    bodies = [text(left), text(right)]
    if any(not re.search(r'\bChainalysis\b', b, re.I) or
           not re.search(r'\b(?:scammer|fraudster)\b', b, re.I) or
           not re.search(r'\bLedger\w*\b', b, re.I) or
           not re.search(r'\b(?:fake online jobs|task scam|fake product sales)\b', b, re.I) or
           re.search(r'\b(?:another|second|additional|different) (?:scammer|fraudster|victim)\b', b, re.I)
           for b in bodies):
        return False
    if left.get('published') and right.get('published') and abs(
        published_time(left['published']) - published_time(right['published'])) > timedelta(hours=24):
        return False
    if any(extract(bodies[0]) != extract(bodies[1]) for extract in (stage, progress_terms, dated_terms)):
        return False
    # Actual service actions and changed incident scope always remain visible.
    if any(re.search(r'\b(?:recall\w*|halt\w*|resum\w*|additional users|new vulnerability|losses? (?:rise|rises|revised))\b', b, re.I) for b in bodies):
        return False
    amounts = [{n for u, n in measures(b) if u == '$'} for b in bodies]
    if any(len(a) != 1 for a in amounts):
        return False
    x, y = next(iter(amounts[0])), next(iter(amounts[1]))
    if x == y:
        return True
    for rounded, precise, body in ((x, y, bodies[0]), (y, x, bodies[1])):
        if re.search(r'\b(?:almost|nearly|close to)\s+\$?\s*5\s*(?:million|m)\b', body, re.I):
            if rounded == 5_000_000 and 4_500_000 <= precise < 5_000_000:
                return True
    return False


def history_row(item, now):
    return {k: (v.isoformat() if hasattr(v, 'isoformat') else v)
            for k, v in {**{k: item.get(k, '') for k in ('title', 'summary', 'published', 'url', 'source', 'official', 'event_context')}, 'date': now}.items()}


def review_card(rows, now):
    """Admin-only editorial inbox; original English is intentionally preserved here."""
    lines = []
    for row in rows[:4]:
        safe_title = re.sub(r'[\[\]*`<>]', '', str(row['title']))[:210]
        links = [(row['source'], row['url']), *[(r['source'], r['url']) for r in row.get('related_sources', [])]]
        refs = ' · '.join(f'[{re.sub(r"[\[\]]", "", name)}]({url})' for name, url in links[:3])
        lines.append(f"**{len(lines)+1:02d}｜{safe_title}**\n⚠️ {row['review_reason']}\n🔗 {refs}\n📅 原文：{published_time(row['published']).astimezone(TAIPEI):%Y/%m/%d %H:%M}（台灣）")
    safety = all(safety_candidate(row) for row in rows)
    return {'title': '🛡️ 資安候選待核對｜僅管理員' if safety else '🔎 新聞內容待核對｜僅管理員', 'description': '\n\n'.join(lines),
            'color': 0x7566A5, 'footer': {'text': '候選不等於已確認事件｜未送成員、不占每日五件名額'},
            'fields': [{'name': '🩺 資料狀態', 'value': '🔎 待核對｜僅確認來源有此報導；各項日期、翻譯或事件證據仍須依上列原因核對。', 'inline': False}],
            'timestamp': now.isoformat()}


def short_context(item):
    """Deterministic reading guidance, not generated investment conclusions."""
    body = text(item)
    from news_policy_context import policy_context
    policy = policy_context(item)
    if policy:
        return ('📅 政策時程', policy['copy'])
    if retrospective(item):
        return ('📌 回顧範圍', '這是原文所述期間的回顧統計，不能當作剛發生的新攻擊；損失口徑與範圍請對照原報告。')
    if re.search(r'\b(?:aum|assets under management|etf assets)\b', body, re.I):
        return ('📌 閱讀重點', '資產管理規模包含價格變動等因素，不能直接當作新增淨流入，也不等於公司自有資金買幣。')
    key = event_key(item)
    if key and key[0] == 'acquisition':
        if stage(body) in {'completed', 'cancelled'}:
            return None
        context = body + ' ' + ' '.join(item.get('event_context') or [])
        closing = re.search(r'\b(?:expects? to close|expected to close|closing expected|close the acquisition in)\b.{0,45}?\b(20\d{2})\b', context, re.I)
        prefix = f'原文預計{closing.group(1)}年交割；' if closing else ''
        if closing:
            from notification_quality import chinese_points
            if any(closing.group(1) in point for point in chinese_points(item)):
                prefix = ''
        return ('🔎 待確認', prefix + '交易公告不等於已完成交割；實際時程與監管條件請以原公告為準。')
    if re.search(r'\b(?:study|research|report finds|survey)\b', body, re.I):
        return ('📌 閱讀重點', '研究結論須對照樣本、地區與資料期間，不能直接當成即時價格訊號。')
    return None
