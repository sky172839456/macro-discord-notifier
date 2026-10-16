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
    if not numeric_values(source).issubset(numeric_values(result)):
        raise ValueError('translation dropped numeric facts')
    # Preserve qualifications instead of converting an allegation into a fact.
    checks = (
        (r'\b(?:may|might|could|potential(?:ly)?|possibly)\b', r'可能|或許|潛在|有望|或將'),
        (r'\b(?:suspected|alleged|unconfirmed|rumou?red)\b', r'疑似|懷疑|涉嫌|據稱|指稱|未證實|未確認|傳聞|傳出'),
        (r"\b(?:not|never|cannot|denies?|denied)\b|n[’']t\b", r'不|未|無|否認|否決|拒絕'),
        (r'\b(?:expects?|expected|plans?|planned|proposed)\b', r'預計|預期|計劃|計畫|擬|提議|提案|提出'),
    )
    for english, chinese in checks:
        if re.search(english, source, re.I) and not re.search(chinese, result):
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
    # Independent free providers. Alternatives are accepted only for the exact
    # same source segment; cache/backoff prevent repeated free-service requests.
    try:
        query = urlencode({'q':source, 'langpair':'en|zh-TW', 'mt':'1'})
        payload = json.loads(news.http_text(news.TRANSLATION_URL+'?'+query, attempts=1))
        if str(payload.get('responseStatus', 200)) == '200' and not payload.get('quotaFinished'):
            choices = [payload.get('responseData', {}).get('translatedText', '')]
            choices.extend(m.get('translation', '') for m in payload.get('matches', [])
                           if m.get('segment', '').strip().casefold() == source.casefold())
            for choice in dict.fromkeys(choices):
                try:
                    return checked_copy(source, news.normalize_zh_title(news.clean_text(str(choice))))
                except ValueError:
                    continue
    except Exception:
        pass
    return checked_copy(source, news.normalize_zh_title(news.clean_text(translate_bing(source))))


def material_news(item):
    from news_editorial import event_kind
    kind = event_kind(item)
    if kind != 'safety':
        return kind == 'decision'
    title = str(item.get('title', ''))
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
    # Do not cut a sentence at the provider's byte boundary or at decimal points.
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z“"\d])|[\r\n]+', value.strip())
    return [s.strip() for s in sentences if s.strip() and len(s.encode('utf-8')) <= 450][:2]


def enrich(item, state, now):
    import crypto_news_notifier as news
    cache = state.setdefault('translation_cache', {})

    def translate(source):
        key = 'auto-v1-' + hashlib.sha256(source.encode()).hexdigest()[:24]
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
    points = []
    summary = str(item.get('summary') or '')
    for sentence in source_sentences(summary):
        if re.fullmatch(r'(?:your )?day[- ]ahead look.*', sentence, re.I):
            continue
        try:
            points.append(translate(sentence))
        except Exception:
            continue
    # A headline is already source content: repeat its fact when the RSS body is
    # a teaser/unavailable. Clearly disclose the shorter basis; invent nothing.
    if not points:
        points = [enriched['title_zh']]
        enriched['summary_basis'] = 'headline'
        enriched['summary_check_source'] = item['title']
    else:
        enriched['summary_basis'] = 'rss'
        enriched['summary_check_source'] = summary
    enriched['summary_zh_points'] = points[:2]
    enriched['auto_copy_version'] = 1
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
        retry = retries.get(key) or {}
        if retry.get('next_at') and published_time(retry['next_at']) > now:
            continue
        # Bound provider requests and runtime when the free service is offline.
        reusable = item.get('auto_copy_version') == 1 and not digest_exclusion_reason(item)
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
                            'next_at': (now + timedelta(minutes=min(120, 15 * 2**min(count-1, 3)))).isoformat()}
            failed += 1
            continue
        retries.pop(key, None)
        ready.append(item)
    state['news_auto_status'] = {'at': now.isoformat(), 'ready': len(ready), 'retrying': len(retries),
                                 'ignored': len(ignored), 'failed_this_run': failed}
    # Only a sustained service-wide failure gets one aggregate daily alert.
    outage = state.setdefault('news_translation_health', {})
    if failed >= 3 and not ready:
        outage.setdefault('since', now.isoformat())
        if now - published_time(outage['since']) >= timedelta(minutes=15) and outage.get('notified_day') != now.date().isoformat():
            log = os.getenv('DISCORD_LOG_WEBHOOK_URL')
            if log:
                try:
                    news.send_discord(log, {'title': '🔧 新聞翻譯服務持續異常',
                        'description': '多篇新聞中文整理仍無法完成；系統會自動重試並略過過期內容。無需逐篇人工核對，其他通知照常處理。',
                        'color': 0x7566A5, 'timestamp': now.isoformat()}, '新聞系統｜服務紀錄')
                except Exception:
                    pass  # Retry the aggregate alert; never reroute to members.
                else:
                    outage['notified_day'] = now.date().isoformat()
    elif ready:
        outage.pop('since', None)
    news.save_state(state)
    return ready
