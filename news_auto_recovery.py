"""Automatic news selection and bounded translation recovery; no manual inbox.

Rules are factual guards, not a language-model semantic certification. Source
attribution and uncertainty remain in member copy. Unrecoverable copy stays out.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import timedelta
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

from notification_quality import checked_translation, news_score, published_time, numeric_values


def enabled():
    return os.getenv('NEWS_AUTO_RECOVERY', '0') == '1'


def checked_copy(source, translated):
    for old, new in (('存儲', '儲存'), ('應用程序', '應用程式'), ('批準', '核准')):
        translated = translated.replace(old, new)
    # Ledger the hardware-wallet company is not an accounting ledger.
    if re.search(r'\bLedgers?\b', source) and re.search(r'wallet|tamper|hardware|device', source, re.I):
        translated = translated.replace('分類帳', 'Ledger').replace('總賬', 'Ledger').replace('總帳', 'Ledger')
    # A permitted trading window is not an obligation to trade before the date.
    if re.search(r'\bhave until\b.+\bto (?:buy|sell|trade)\b', source, re.I):
        translated = translated.replace('必須在', '仍可在')
    result = checked_translation(source, translated)
    from news_copy_terms import validate_identifiers
    validate_identifiers(source,result)
    from content_contract import segment_issues
    issues = segment_issues(source,result)
    if issues:
        raise ValueError('source/copy contract: '+','.join(issues))
    if not numeric_values(source).issubset(numeric_values(result)):
        raise ValueError('translation dropped numeric facts')
    from news_streak_guard import validate
    validate(source, result)
    # A fund-flow headline about fleeing FROM ETFs cannot become an inflow.
    if (re.search(r'\b(?:funds?|money|investors?)\b.*\b(?:fled|fleeing|flee)\s+(?:from\s+)?(?:bitcoin\s+)?etfs?\b', source, re.I)
            and re.search(r'流入|湧入|淨流入', result)
            and not re.search(r'\b(?:stepped in|inflows?|into)\b', source, re.I)):
        raise ValueError('translation reversed ETF money leaving into entering')
    ongoing_recovery = re.search(r'''\b(?:race|game|attempting|working|efforts|seeks?|trying)['’"]?\s+(?:against time\s+)?to recover\b''', source, re.I)
    if ongoing_recovery and not re.search(r'\b(?:recovered|returned|repaid)\b', source, re.I):
        if (re.search(r'(?:已|成功|完成).{0,5}(?:追回|追討|收回)', result)
                or not re.search(r'追查|追索|搶救|追回.{0,8}中|正(?:在)?|嘗試|試圖|競速|設法|努力|尋求', result)):
            raise ValueError('translation turned an ongoing recovery effort into a result')
    # Preserve qualifications instead of converting an allegation into a fact.
    checks = (
        (r'\b(?:may|might|could|potential(?:ly)?|possibly)\b', r'可能|或許|潛在|有望|或將'),
        (r'\b(?:suspected|alleged|unconfirmed|rumou?red)\b', r'疑似|懷疑|涉嫌|據稱|指稱|未證實|未確認|傳聞|傳出'),
        (r"\b(?:not|never|cannot|denies?|denied)\b|n[’']t\b", r'不|未|無|否認|否決|拒絕'),
        (r'\b(?:expects?|expected|plans?|planned|proposed)\b', r'預計|預期|計劃|計畫|擬|提議|提案|提出'),
    )
    # Valid explicit dates use May as a month, not an uncertainty modal.
    # Invalid/partial dates and any separate may remain subject to the guard.
    from news_policy_context import DATE, parse_date
    qualification_source = re.sub(
        r'\b' + DATE + r'\b',
        lambda match: ' [calendar date] ' if parse_date(match.group(0)) else match.group(0),
        source, flags=re.I,
    )
    for english, chinese in checks:
        qualifier_text = qualification_source if english == checks[0][0] else source
        if re.search(english, qualifier_text, re.I) and not re.search(chinese, result):
            raise ValueError('translation lost source qualification')
    for english, wrong in ((r'\b(?:outflows?|withdrawals?)\b', r'淨流入'),
                           (r'\b(?:inflows?)\b', r'淨流出')):
        if re.search(english, source, re.I) and re.search(wrong, result):
            # Mixed inflow/outflow comparisons need both directions preserved.
            opposite = r'\binflows?\b' if 'outflow' in english else r'\boutflows?\b'
            if not re.search(opposite, source, re.I):
                raise ValueError('translation reversed fund flow')
    return result


_bing_session = None
_bing_form = None


def translate_bing(source):
    """Normal public Bing Translator form; no paid key, CAPTCHA or block bypass.

    This web interface is not a supported Azure API. HTTP errors stop this
    provider for the call; state-driven retries happen later at bounded rates.
    The public form token/cookies stay only in process memory, never in state.
    """
    global _bing_session, _bing_form
    headers = {'User-Agent': 'macro-discord-notifier/1.0', 'Accept': 'application/json,text/html'}
    if _bing_form is None or time.monotonic() - _bing_form['at'] > 300:
        _bing_session = build_opener(HTTPCookieProcessor(CookieJar()))
        with _bing_session.open(Request('https://www.bing.com/translator', headers=headers), timeout=10) as response:
            page = response.read().decode('utf-8')
        ig = re.search(r'IG:"([A-Za-z0-9]+)"', page)
        form = re.search(r'params_AbusePreventionHelper\s*=\s*(\[[^;]+\])', page)
        if not ig or not form:
            raise ValueError('Bing public translation form unavailable')
        params = json.loads(form.group(1))
        _bing_form = {'ig': ig.group(1), 'key': params[0], 'token': params[1], 'at': time.monotonic()}
    endpoint = 'https://www.bing.com/ttranslatev3?' + urlencode({'isVertical': '1', 'IG': _bing_form['ig'], 'IID': 'translator.5028.1'})
    data = urlencode({'fromLang':'en', 'to':'zh-Hant', 'text':source,
                      'key':_bing_form['key'], 'token':_bing_form['token']}).encode()
    request = Request(endpoint, data=data, headers={**headers, 'Content-Type':'application/x-www-form-urlencoded'}, method='POST')
    with _bing_session.open(request, timeout=10) as response:
        result = json.loads(response.read().decode('utf-8'))
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        raise ValueError('Bing translation response unavailable')
    translations = result[0].get('translations') or []
    if not translations or translations[0].get('to') != 'zh-Hant':
        raise ValueError('Bing Traditional Chinese translation unavailable')
    return translations[0].get('text', '')


def translate(source):
    import crypto_news_notifier as news
    from content_contract import protect, restore
    request_source, protected = protect(source)
    if len(request_source.encode('utf8'))>450:
        raise ValueError('protected segment exceeds provider limit')
    # Independent free providers. Alternatives are accepted only for the exact
    # same source segment; cache/backoff prevent repeated free-service requests.
    try:
        query = urlencode({'q':request_source, 'langpair':'en|zh-TW', 'mt':'1'})
        payload = json.loads(news.http_text(news.TRANSLATION_URL+'?'+query, attempts=1))
        if str(payload.get('responseStatus', 200)) == '200' and not payload.get('quotaFinished'):
            choices = [payload.get('responseData', {}).get('translatedText', '')]
            choices.extend(m.get('translation', '') for m in payload.get('matches', [])
                           if m.get('segment', '').strip().casefold() == request_source.casefold())
            for choice in dict.fromkeys(choices):
                try:
                    return checked_copy(source, news.normalize_zh_title(restore(news.clean_text(str(choice)),protected)))
                except ValueError:
                    continue
    except Exception:
        pass
    return checked_copy(source, news.normalize_zh_title(restore(news.clean_text(translate_bing(request_source)),protected)))


def material_news(item):
    if item.get('stream') == 'finance':
        from news_streams import CRYPTO
        title = str(item.get('title', ''))
        if not re.search(CRYPTO, title, re.I):
            return bool(re.search(r'\b(?:imposes? tariffs?|enacts?|announces? emergency|bank collapse|capital controls?|halts? withdrawals?)\b', title, re.I))
    from news_editorial import event_kind
    kind = event_kind(item)
    if kind != 'safety':
        return kind == 'decision'
    title = str(item.get('title', ''))
    body = title + ' ' + str(item.get('summary', ''))
    # Commentary alone cannot become another major incident. Preserve concrete
    # losses, victims, recovery and official actions appearing in the same item.
    commentary = re.search(
        r'\b(?:exposes? .{0,35}(?:risks?|flaws?)|raises? questions|buying opportunity|'
        r'what it means|analysts? (?:say|says|argue\w*)|'
        # Periodic statistics ("reports seven-fold increase in phishing alerts") are not an incident.
        r'reports? (?:a |an )?(?:\w+-?fold|\d+%|\d+x|sharp|significant)?\s*(?:increase|rise|jump|surge|drop|decline)s? in|'
        r'(?:price|stocks?|shares?|bitcoin|ether) (?:falls?|drops?|rises?|slumps?|rebounds?|rallies) (?:after|following))\b', title, re.I)
    material_progress = re.search(
        r'\b(?:loss(?:es)?\s+(?:rise\w*|revis\w*|increas\w*|updat\w*)|'
        r'(?:additional|more|new)\s+(?:victims?|users?|wallets?|accounts?)|'
        r'(?:froze|frozen|freeze\w*|seiz\w*|recover\w*|reimburse\w*|compensat\w*)\s+(?:\$|funds?|assets?|victims?|users?)|'
        r'(?:fbi|police|authorities|regulators?)\s+(?:begins?|launch\w*|open\w*|order\w*|announc\w*)|'
        r'(?:withdrawals?|deposits?)\s+(?:resum\w*|halt\w*|suspend\w*)|'
        r'(?:new|active|ongoing)\s+(?:exploit|attack|breach|vulnerability))\b', body, re.I)
    material_progress = material_progress or re.search(
        r'\b(?:(?:loss(?:es)?|victims?)\s+(?:estimate\s+|count\s+)?(?:rise\w*|revis\w*|increas\w*|updat\w*)|'
        r'\d+\s+(?:customer\s+)?(?:accounts?|wallets?|users?)\s+(?:are\s+|were\s+)?(?:affected|impacted)|'
        r'(?:funds?|assets?)\s+(?:(?:have|has|been|were|are|being|now)\s+){0,5}(?:recover\w*|return\w*|froze\w*|seiz\w*)|'
        r'(?:confirms?|confirmed)\s+(?:a\s+|new\s+)?(?:breach|exploit)|'
        r'return\w*\s+(?:the\s+)?funds?)\b', body, re.I)
    if commentary and not material_progress:
        return False
    progress = re.search(r'\b(?:new vulnerability|new exploit|active exploit|ongoing attack|additional (?:victims|users|wallets)|recall\w*|halt\w*|suspend\w*|resum\w*|restor\w*|loss(?:es)? (?:rise|rises|revised)|confirms? (?:a )?(?:new )?(?:breach|exploit))\b', body, re.I)
    background = re.search(r'\b(?:scammer gets scammed|scammer (?:lost|loses)|victim profile|questioning (?:its|their) response|early .{0,25}warnings|months before|years ago|deserved more action)\b', body, re.I)
    if background and not progress:
        return False
    # Products referring to an older security incident do not become alerts.
    if re.search(r'\b(?:costs?|ships?|unveils?|introduces?|new (?:wallet|device))\b', title, re.I):
        return bool(re.search(r'\b(?:halt\w*|recall\w*|confirms? breach|confirms? exploit)\b', title, re.I))
    return True


def selection_reason(item, now):
    published = published_time(item['published'])
    if published < now - timedelta(hours=24):
        return '舊文'
    if published > now + timedelta(minutes=5):
        return '來源發布時間異常'
    title = str(item.get('title', ''))
    from news_streams import finance_topic
    if item.get('stream') == 'finance':
        return None if finance_topic(item) else '缺少金融傳導事件'
    if re.search(r'\b(?:recap|conference roundup|conference highlights)\b', title, re.I):
        if not re.search(r'\b(?:approves?|enacts?|signs? (?:a |the )?(?:law|bill|deal)|halts?|recalls?|launches? (?:a |the )?(?:fund|mainnet)|announces? (?:a |the )?(?:ban|acquisition))\b', title, re.I):
            return '活動回顧，未見重要新進展'
    if re.search(r'\b(?:asia express|finance redefined|weekly roundup|weekly recap|what happened in crypto today|daily roundup|news roundup)\b', title, re.I):
        return '多事件回顧彙整'
    from news_editorial import retrospective
    if material_news(item):
        return None
    if retrospective(item):
        return '回顧舊事'
    if re.search(r'\b(?:live updates?|price prediction|opinion|uptober|could reach|will hit|may see|predicts?|top altcoins|best crypto|sponsored|presale)\b|^(?:why|how|what|can)\b', title, re.I):
        return '低價值導讀或價格追蹤'
    if re.search(r'\b(?:bans?|prohibits?|enacts?|sues?|files? lawsuit|grants? licen[cs]e)\b', title, re.I):
        return None
    if re.search(r'\b(?:draft bill|tax reporting|stablecoins?|etfs?|custody|treasury|mainnet|hard fork)\b', title, re.I):
        return None
    if news_score(item) < 40:
        return '缺少重要事件進展'
    return None


def same_article(left, right):
    """Merge edits to one article, but retain material changes to that article."""
    from crypto_news_notifier import canonical_url
    from news_editorial import event_key, event_kind, stage, progress_terms, scope_terms, measures
    if not left.get('url') or not right.get('url'):
        return False
    if canonical_url(left['url']) != canonical_url(right['url']):
        return False
    if abs(published_time(left['published']) - published_time(right['published'])) > timedelta(hours=24):
        return False
    a, b = str(left.get('title', '')), str(right.get('title', ''))
    if re.search(r'\b(?:greece|greek)\b', a+' '+b, re.I) and re.search(r'\b(?:tax|levy)\b', a+' '+b, re.I):
        from news_editorial import dated_terms
        full_a, full_b = a+' '+str(left.get('summary', '')), b+' '+str(right.get('summary', ''))
        if any(extract(full_a) != extract(full_b) for extract in (measures, dated_terms, progress_terms, stage)):
            return False
    from news_editorial import commentary_only, INCIDENT
    if (commentary_only(left) or commentary_only(right)) and re.search(INCIDENT, a+' '+b, re.I) and measures(a) != measures(b):
        return False  # 同URL的評論也可能更正數字；不可吞掉不同金額。
    ka, kb = event_key(left), event_key(right)
    if ka and kb and ka != kb:
        return False
    if stage(a) != stage(b) or progress_terms(a) != progress_terms(b):
        return False
    if ka or kb or event_kind(left) in {'safety', 'decision'} or event_kind(right) in {'safety', 'decision'}:
        full_a, full_b = a+' '+str(left.get('summary', '')), b+' '+str(right.get('summary', ''))
        if any(extract(full_a) != extract(full_b) for extract in (stage, progress_terms, measures, scope_terms)):
            return False
    if event_kind(left) == 'decision' or event_kind(right) == 'decision':
        if measures(a) != measures(b):
            return False
    if (ka and ka[0] in {'security', 'service', 'purchase', 'trading'}) or (kb and kb[0] in {'security', 'service', 'purchase', 'trading'}):
        if scope_terms(a) != scope_terms(b) or measures(a) != measures(b):
            return False
    # An updated policy date, regulator, or explicit approval is a real update.
    if re.search(r'\b(?:ban|law|regulat|policy|court|sec)\w*\b', a+' '+b, re.I):
        from news_editorial import dated_terms, entity
        if dated_terms(a) != dated_terms(b) or entity(a) != entity(b):
            return False
    return True


def source_sentences(value):
    from content_contract import strict, segments
    if strict():
        return segments(value)
    # Short RSS paragraphs need no English splitting at all. Preserve names.
    value = value.strip()
    if len(value.encode('utf-8')) <= 450:
        return [value] if value else []
    protected = re.sub(r'\b(?:Mt|Dr|Mr|Mrs|Ms|Prof|Inc|Corp|Ltd)\.|\b(?:[A-Z]\.){2,}|(?<=\d)\.(?=\d)',
                       lambda m: m.group().replace('.', '\u2024'), value)
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z“"\d])|[\r\n]+', protected)
    return [s.replace('\u2024', '.').strip() for s in sentences
            if s.strip() and len(s.encode('utf-8')) <= 450][:2]


def enrich(item, state, now):
    import crypto_news_notifier as news
    cache = state.setdefault('translation_cache', {})

    def translate(source):
        from content_contract import VERSION, strict
        prefix='auto-contract-v'+str(VERSION)+'-' if strict() else 'auto-v2-'
        key = prefix + hashlib.sha256(source.encode()).hexdigest()[:24]
        cached = cache.get(key) or {}
        if cached.get('source') == source:
            try:
                return checked_copy(source, cached.get('translated', ''))
            except ValueError:
                cache.pop(key, None)
        result = checked_copy(source, news.translate_text(source))
        cache[key] = {'source': source, 'translated': result, 'date': now.date().isoformat()}
        return result

    enriched = dict(item)
    try:
        enriched['title_zh'] = translate(str(item['title']))
    except Exception:
        enriched['title_zh'] = ''
        enriched['summary_zh_points'] = []
        return enriched
    points, pairs = [], []
    summary = str(item.get('summary') or '')
    # Reject an incomplete publisher clause rather than invent its missing verb.
    if re.search(r'\b(?:as|while|because|although)\s+(?:banks?|companies|payment firms?|investors)(?:\s+and\s+(?:banks?|companies|payment firms?|investors))*\s*[.!]?$', summary, re.I):
        summary = ''
    selected = source_sentences(summary)
    for sentence in selected:
        if re.fullmatch(r'(?:your )?day[- ]ahead look.*', sentence, re.I):
            continue
        try:
            translated = translate(sentence)
            points.append(translated)
            pairs.append({'source':sentence,'zh':translated})
        except Exception:
            continue
    # A headline is already source content: repeat its fact when the RSS body is
    # a teaser/unavailable. Clearly disclose the shorter basis; invent nothing.
    from content_contract import strict
    if not points and not (strict() and selected):
        points = [enriched['title_zh']]
        enriched['summary_basis'] = 'headline'
        enriched['summary_check_source'] = item['title']
        pairs = [{'source':item['title'],'zh':enriched['title_zh']}]
    else:
        enriched['summary_basis'] = 'rss'
        enriched['summary_check_source'] = summary
    enriched['summary_zh_points'] = points[:2]
    enriched['auto_copy_version'] = 2
    from content_contract import stamp
    stamp(enriched,pairs[:2],enriched['summary_basis'])
    enriched['content_contract']['complete_selected_excerpt'] = len(pairs)==len(selected) if selected else bool(pairs)
    return enriched


def route(items, state, now):
    import crypto_news_notifier as news
    from notification_quality import digest_exclusion_reason, rank_news
    # Migrate the legacy manual inbox into automatic retries, without re-posting
    # already delivered items or erasing the old audit records.
    categories = {r['key']: r for r in news.CATEGORIES}
    legacy = []
    for row in state.get('safety_review', []):
        if row.get('status') == 'pending_review':
            restored = dict(row)
            restored['published'] = published_time(row['published'])
            if isinstance(restored.get('category'), str):
                restored['category'] = categories[restored['category']]
            legacy.append(restored)
            row['status'] = 'auto_processing'
    retries = state.setdefault('news_auto_retry', {})
    ignored = state.setdefault('news_auto_ignored', {})
    cutoff = (now - timedelta(days=2)).isoformat()
    ignored_keys = [key for key, row in ignored.items() if row['at'] < cutoff]
    for key in ignored_keys:
        ignored.pop(key)
    rows = [*items, *legacy, *[r['item'] for r in retries.values()]]
    # JSON caches restore dates as strings. Every processing path (including
    # cached ready copy) must return datetimes; serialize only when storing.
    rows = [{**row, 'published': published_time(row['published'])} for row in rows]
    rows = news.slim_policy.merge_pending(rows)
    ready, attempts, failed = [], 0, 0
    for item in rank_news(rows):
        key = item['id']
        reason = selection_reason(item, now)
        delivered = key in state.get('seen', {}) or any(
            news.same_news_event(item, {**r, 'published': r.get('published') or r['date']})
            for r in state.get('headline_history', []))
        if reason or delivered or key in ignored:
            if reason:
                ignored[key] = {'at': now.isoformat(), 'reason': reason}
            retries.pop(key, None)
            continue
        from crypto_news_notifier import canonical_url
        item = dict(item)
        item['source_update'] = any(
            r.get('url') and item.get('url')
            and canonical_url(r['url']) == canonical_url(item['url'])
            and abs(published_time(item['published']) - published_time(r.get('published') or r['date'])) <= timedelta(hours=24)
            for r in state.get('headline_history', []))
        retry = retries.get(key) or {}
        if retry.get('next_at') and published_time(retry['next_at']) > now:
            continue
        # Bound provider requests and runtime when the free service is offline.
        reusable = item.get('auto_copy_version') == 2 and not digest_exclusion_reason(item)
        if attempts >= 4 and not reusable:
            stored = dict(item); stored['published'] = published_time(item['published']).isoformat()
            retries.setdefault(key, {'item': stored, 'attempts': 0, 'next_at': now.isoformat()})
            continue
        if not reusable:
            attempts += 1
        item = news.add_translated_title(item, state, now)
        reason = digest_exclusion_reason(item)
        if reason:
            count = retry.get('attempts', 0) + 1
            stored = dict(item); stored['published'] = published_time(item['published']).isoformat()
            retries[key] = {'item': stored, 'attempts': count,
                            'reason':reason,
                            'next_at': (now + timedelta(minutes=min(120, 15 * 2**min(count-1, 3)))).isoformat()}
            failed += 1
            continue
        retries.pop(key, None)
        ready.append(item)
    state['news_auto_status'] = {'at': now.isoformat(), 'ready': len(ready), 'retrying': len(retries),
                                 'ignored': len(ignored), 'failed_this_run': failed}
    # Aggregate sustained copy failures; do not infer a provider outage from
    # content gates rejecting otherwise readable source/translation responses.
    outage = state.setdefault('news_translation_health', {})
    if failed >= 3 and not ready:
        outage.setdefault('since', now.isoformat())
        if now - published_time(outage['since']) >= timedelta(minutes=15) and outage.get('notified_day') != now.date().isoformat():
            log = os.getenv('DISCORD_LOG_WEBHOOK_URL')
            if log:
                try:
                    news.send_discord(log, {'title': '🔧 新聞中文／內容檢查持續未通過',
                        'description': '多篇新聞的中文或原文對照尚未通過；翻譯取得與內容條件須分別核對，不能直接判定供應商故障。候選已保留，系統會自動重試並略過過期內容；完整語意仍待驗收。',
                        'color': 0x7566A5, 'timestamp': now.isoformat()}, '新聞系統｜服務紀錄')
                except Exception:
                    pass  # Retry the aggregate alert; never reroute to members.
                else:
                    outage['notified_day'] = now.date().isoformat()
    elif ready:
        outage.pop('since', None)
    news.save_state(state)
    return ready
