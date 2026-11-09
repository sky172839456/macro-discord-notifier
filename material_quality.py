"""Bounded selection and read-only health checks; never send, repair or reset state."""
from datetime import datetime
import json
import re
from material_editorial import editorial_angle, review, _text

VERSION = 2


def selection(row, now):
    """All private categories must supply a reader takeaway and source detail."""
    from material_source_copy import RELEASE_SOURCES, excerpt_parts
    if row.get('source') in RELEASE_SOURCES and not excerpt_parts(row):
        return 'complete_excerpt_unavailable'
    from material_share_value import assess
    return assess(row)['reason']


def card_issues(row, card):
    text = json.dumps(card, ensure_ascii=False)
    description = card.get('description', '')
    fields = {f.get('name', ''): f.get('value', '') for f in card.get('fields', [])}
    problems = []
    if not re.search(r'[★☆]{5} [1-5]/5', description):
        problems.append('stars_missing')
    concept = fields.get('🧩 初步內容構思', '')
    if not all(x in concept for x in ('切入問題', '內容骨架', '本則焦點')):
        problems.append('angle_missing')
    if '原文標題待中文核對' in text:
        problems.append('translation_pending')
    if re.search(r'\ufffd|&(?:amp|lt|gt|quot|#\d+);', text):
        problems.append('text_encoding')
    if not fields.get('🔗 來源與時間') or row.get('url', '') not in text:
        problems.append('source_missing')
    angle = editorial_angle(row.get('title',''), row.get('summary',''))
    if angle in ('people', 'startup', 'politics') and '這次AI更新' in concept:
        problems.append('generic_angle')
    expected = {'people':'企業', 'startup':'創業', 'politics':'政治'}.get(angle)
    if expected and expected not in description.split('\n')[0]:
        problems.append('category_mismatch')
    return problems


def hint(row):
    """Independent broad recall probe, not another auto-accept classifier."""
    if re.search(r'\b(?:sponsored|presale|giveaway|recap|roundup|podcast|webinar)\b', row.get('title',''), re.I):
        return False
    return bool(re.search(r'\b(?:MCP|registrations?|withdrawals?|onboarding|startups?|small business|congress|lawmakers?|robot|new tool|new system)\b', row.get('title',''), re.I))


def inspect(state, now):
    """Read saved source/decision/render evidence; missing evidence stays pending."""
    warnings, metrics = [], {}
    box = state.get('material_inbox_v1', {})
    audit = box.get('selection_audit', {})
    def recent(value, minutes=15):
        try:
            age = (now-datetime.fromisoformat(value)).total_seconds()
            return 0 <= age <= minutes*60
        except (ValueError, TypeError):
            return False
    if not recent(audit.get('completed_at')):
        warnings.append('素材本輪篩選／送達對帳缺漏或逾時')
    else:
        decisions = audit.get('decisions', [])
        metrics['raw'] = len(decisions)
        metrics['held'] = sum(d['decision'] == 'quality_hold' for d in decisions)
        metrics['excluded'] = sum(d['decision'] in ('no_topic','outside_window','invalid_source') for d in decisions)
        metrics['recall_pending'] = sum(d['decision']=='no_topic' and d.get('recall_hint') for d in decisions)
        # Do not infer completeness from queue==0: verify each accepted source key.
        keys = {r.get('material_key') for r in box.get('items', [])}
        missing = sum(d['decision']=='accepted' and d.get('key') not in keys for d in decisions)
        if missing:
            warnings.append(f'來源候選未進待送紀錄：{missing}筆')
        if metrics['recall_pending']:
            warnings.append(f'關鍵題材被排除待複核：{metrics["recall_pending"]}筆')
        unreadable = sum(not r.get('readable') for r in box.get('source_status', []))
        if unreadable or not box.get('source_status'):
            warnings.append(f'素材來源讀取待核：{unreadable}個失敗' if unreadable else '素材來源狀態缺漏')
        pending_details = sum(r.get('detail_pending',0) for r in box.get('source_status',[]))
        metrics['official_detail_pending'] = pending_details
        if pending_details:
            warnings.append(f'官方素材正文尚待讀取：{pending_details}筆（不以標題代替正文）')
    items = box.get('items', [])
    metrics['queued'] = sum(r.get('status')=='queued' for r in items)
    metrics['unknown'] = sum(r.get('status')=='delivery_unknown' for r in items)
    if metrics['unknown']:
        warnings.append(f'素材送達不明：{metrics["unknown"]}筆（不自動重送）')
    overdue = sum(r.get('status')=='queued' and not recent(r.get('collected_at'), 60) for r in items)
    if overdue:
        warnings.append(f'素材待送超過60分鐘或收錄時間缺漏：{overdue}筆')
    delivered = [r for r in items if r.get('status')=='notified' and recent(r.get('notified_at'), 24*60)]
    metrics['delivered24h'] = len(delivered)
    unchecked = sum(not r.get('render_audit') for r in delivered)
    issues = sum(bool(r.get('render_audit',{}).get('issues')) for r in delivered)
    mismatch = sum({'people':'business','startup':'business','politics':'policy'}.get(
        editorial_angle(r.get('title',''),r.get('summary','')), r.get('material_topic')) != r.get('material_topic') for r in delivered)
    if unchecked:
        warnings.append(f'近24小時舊卡未留卡面品質證據：{unchecked}筆，需實讀')
    held_issues = sum(r.get('status')=='quality_hold' and r.get('quality_hold_reason')=='render_quality' for r in items)
    if held_issues:
        warnings.append(f'素材卡面品質未過、暫緩發送：{held_issues}筆')
    if issues or mismatch:
        warnings.append(f'已送素材品質待核：卡面{issues}筆／分類{mismatch}筆')
    source = state.get('content_source_audit', {})
    if not recent(source.get('checked_at')):
        warnings.append('公開新聞原始來源對帳缺漏或逾時')
    else:
        bad = [s for s in source.get('sources', []) if s.get('error') or s.get('count',-1)<0]
        if not source.get('sources'):
            warnings.append('公開新聞來源明細缺漏')
        if bad:
            warnings.append(f'公開新聞來源暫缺：{len(bad)}個')
        parse_errors = sum(bool(r.get('error')) for r in source.get('private_parsers',[]))
        if parse_errors:
            warnings.append(f'原始素材解析失敗：{parse_errors}個來源')
    metrics['source_rows'] = source.get('raw_material_finance', '待核')
    return {'warnings': warnings, 'metrics': metrics,
            'scope':'自動核對來源／篩選／佇列與可判定卡面；未讀Discord實卡、完整語意與未提供的來源仍待人工驗收。'}
