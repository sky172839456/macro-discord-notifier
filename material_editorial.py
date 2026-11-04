"""Source-bounded editorial first pass. Pure rules, no network or publication."""
from datetime import datetime
import re


def _text(value, limit=150):
    value = re.sub(r'<[^>]*>', ' ', str(value or ''))
    value = re.sub(r'[@`*\[\]<>]', '', value)
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def _has(pattern, value):
    return bool(re.search(pattern, value, re.I))


PLANS = {
    'connection': (
        '這次串接，能替使用者少做哪一步？',
        '原本怎麼完成同一個任務 → 公告新增的串接能力 → 誰用得到及實際開放條件',
        '以同一任務作流程對照，示範只採原文已支持的步驟。'),
    'ai': (
        '這次AI更新，在哪個任務上值得注意？',
        '原先的任務或限制 → 公告列出的新方法／能力 → 使用情境與尚未驗證的部分',
        '挑一項明確任務做圖解，廠商展示與自行實測分開標示。'),
    'innovation': (
        '這項發明想解決什麼問題，目前做到哪一步？',
        '原本的問題 → 原文描述的運作方法 → 展示／原型／測試／開賣階段與限制',
        '用原理流程或前後做法比較，概念示意須明標。'),
    'security': (
        '這次事件最值得讀者留意的是哪個環節？',
        '來源描述發生了什麼 → 已知影響及處置 → 哪些仍待核實、讀者可核對的公告',
        '做事件時間線，未確認的損失、動機及影響不寫成定論。'),
    'policy': (
        '這項變動影響誰，什麼時候才適用？',
        '原有規則 → 公告提出或通過的變動 → 適用對象、地區與生效階段',
        '用一個適用情境對照前後，提案、通過與生效分清。'),
    'business': (
        '這個企業動作，究竟帶來什麼具體改變？',
        '參與者與原有做法 → 原文列出的合作／收購／服務內容 → 用戶影響及落地階段',
        '畫出參與者與流程，未公布的好處不自行補上。'),
    'research': (
        '這個發現，回答了什麼值得知道的問題？',
        '研究要回答的問題 → 原文發現與所用資料 → 方法、適用範圍與反例',
        '用一張圖解釋單一發現，相關性與因果分開。'),
    'interesting': (
        '這件事為什麼讓人想多看一眼，背後還有什麼？',
        '具體人物或反常事件 → 原文交代的經過與背景 → 有趣之外能帶走的知識點',
        '用故事或反差問句開場，保留原話上下文，不替人物推測動機。'),
}


def review(row, now, focus=None):
    """Rank content-making potential, independently of source-verification status."""
    title, summary = _text(row.get('title'), 400), _text(row.get('summary'), 1000)
    value = title + ' ' + summary
    topic = row.get('material_topic', '')
    connection = _has(r'\b(?:MCP|Model Context Protocol|connectors?|plugins?|plug-ins?|automated workflows?|automation|integrat\w*)\b', value)
    novelty = 2 if _has(r'\b(?:new|first|unveil\w*|introduc\w*|releas\w*|launch\w*|adds?|now supports?|approv\w*|enact\w*|confirms?|hack(?:ed)?|discovers?|breakthrough)\b', title) else 0
    useful = 2 if connection or _has(r'\b(?:how to|users?|customers?|workflow|fees?|costs?|access|withdrawals?|affected|security|privacy|open.source|can use)\b', value) else 1 if topic in ('ai', 'innovation', 'policy', 'research', 'business', 'security') else 0
    curiosity = 2 if _has(r'\b(?:world record|guinness|first.ever|unexpected|surprising|lost wallet|dormant|accidental\w*|breakthrough|million|billion)\b', value) else 1 if connection or topic == 'interesting' or _has(r'\b(?:robots?|humanoids?|flying cars?|prototypes?|experiments?)\b', value) else 0
    # Specific source content helps form a story; this is not a truth/confidence score.
    detail = 2 if summary and (_has(r'\b\d[\d,.]*\s*(?:%|million|billion|hours?|minutes?|days?|users?|steps?|dollars?)\b|\bfrom\b.{1,55}\bto\b', summary) or (connection and _has(r'\b(?:servers?|connectors?|tasks?|read.only|read.write|preview|permissions?|files?|workflow|manual)\b', summary))) else 1 if len(summary) >= 60 else 0
    recent = 0
    try:
        date = row.get('published')
        date = date if isinstance(date, datetime) else datetime.fromisoformat(str(date).replace('Z', '+00:00'))
        if date.tzinfo is not None and now.tzinfo is not None:
            recent = int(0 <= (now-date).total_seconds() <= 6*3600)
    except (TypeError, ValueError, OverflowError):
        pass
    total = novelty + useful + curiosity + detail + recent
    stars = 5 if total >= 8 and detail == 2 else 4 if total >= 6 else 3 if total >= 4 else 2 if total >= 2 else 1
    labels = {1: '先留紀錄', 2: '備用選題', 3: '可延伸製作', 4: '值得優先構思', 5: '優先投入構思'}
    reasons = []
    if novelty == 2:
        reasons.append('標題有具體新進展')
    if useful == 2:
        reasons.append('有可說明的用途或讀者影響')
    if curiosity == 2:
        reasons.append('有反差、故事或規模切入點')
    elif curiosity:
        reasons.append('適合用故事或流程對照帶入')
    if detail == 2:
        reasons.append('摘要有具體數字或流程線索')
    if recent:
        reasons.append('發布時間在近六小時內')
    if not reasons:
        reasons.append('現有標題與摘要尚不足以支持鮮明切入點')
    plan_key = 'connection' if connection and topic in ('ai', 'innovation') else topic
    hook, outline, method = PLANS.get(plan_key, PLANS['research'])
    anchor = _text(focus or title, 135)
    return {
        'stars': stars, 'display': '★'*stars+'☆'*(5-stars), 'label': labels[stars],
        'reason': '；'.join(reasons)+'。',
        'concept': f'**本則焦點**　{anchor}\n\n**切入問題**　{hook}\n\n**內容骨架**　{outline}\n\n**表現方式**　{method}',
        'basis': '依標題／摘要作規則初評；星等是製作優先度，高星不代表已完成查證。',
        'version': 1,
    }
