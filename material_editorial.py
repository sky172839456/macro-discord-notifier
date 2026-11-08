"""Source-bounded editorial first pass. Pure rules, no network or publication."""
from datetime import datetime
import re
import html


def _text(value, limit=150):
    value = html.unescape(html.unescape(str(value or '')))
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


def editorial_angle(title, summary=''):
    """Match the kind of evidence, not every mention of AI to a tool release."""
    role = r'\b(?:CEO|CFO|CTO|COO|chief (?:\w+ ){0,3}officer|executives?|presidents?|founders?)\b'
    move = r'\b(?:leaves?|left|steps? down|resigns?|joins?|joined|appoints?|appointed|named|becomes?)\b'
    synthetic = r'\b(?:AI|robot|agent|assistant|model|tool)\s+(?:is\s+)?(?:appointed|named|joins?|becomes?)\b'
    if _has(role, title) and _has(move, title) and not _has(synthetic, title):
        return 'people'
    if (_has(r'\b(?:Democrats?|Republicans?|congress(?:ional)?|senators?|lawmakers?|Rep\.|parliament|election)\b', title)
            and _has(r'\b(?:policy|ban|vot\w*|disclos\w*|bought|purchases?|trading|regulat\w*)\b', title+' '+summary)):
        return 'politics'
    if (_has(r'\b(?:small business|business owners?|entrepreneurs?|solo founders?|one.person business|startups?|start-ups?)\b', title)
            and _has(r'\b(?:formation|no employees|finance|marketing|design|automat\w*|grow|founded|funding|raises?)\b', title+' '+summary)):
        return 'startup'
    if _has(r'\b(?:AI|artificial intelligence)\b', title):
        if (_has(r'\b(?:recruitment|recruiters?|candidate screening|placement fees?)\b', title)
                and _has(r'\b(?:speed\w*|screen\w*|reshap\w*|fees?|automat\w*)\b', title+' '+summary)):
            return 'recruiting'
        if (_has(r'\b(?:stocks?|equities|trade)\b', title)
                and _has(r'\b(?:bounce|rebound|rout|meltdown|selloff|sell-off|bubble|rall\w*|falls?|drops?)\b', title)):
            return 'market'
        if _has(r'\b(?:report|study|research)\b', title) and _has(r'\b(?:researchers|alarming|findings|finds|investigation)\b', title+' '+summary):
            return 'research_review'
        if _has(r'\bcybersecurity\b', title) and _has(r'\b(?:talking with|episode|interview|expert)\b', summary):
            return 'security_review'
        if _has(r'\b(?:saved my|ruined my|my experience|I tried)\b', title):
            return 'usage_review'
    return None


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
    detail = 2 if summary and (_has(r'(?<!\w)\d[\d,.]*\s*(?:%(?!\w)|(?:million|billion|hours?|minutes?|days?|users?|steps?|dollars?)\b)|\bfrom\b.{1,55}\bto\b', summary) or (connection and _has(r'\b(?:servers?|connectors?|tasks?|read.only|read.write|preview|permissions?|files?|workflow|manual)\b', summary))) else 1 if len(summary) >= 60 else 0
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
    angle = editorial_angle(title, summary)
    if angle == 'people':
        hook = '這次高層異動是誰離開哪家公司、轉去哪裡，原文確認了哪些職責？'
        outline = '原任職位與公司 → 新公司、職位及已公布時間 → 已確認事實與尚未證實的策略影響分開'
        method = '做任職前後對照，不以跳槽推論公司前景、內幕或股價方向。'
    elif angle == 'startup':
        tasks = [label for pattern, label in ((r'\bfinance\b','財務'), (r'\bmarketing\b','行銷'), (r'\bdesign\b','設計')) if _has(pattern, summary)]
        hook = ('原文中的創業者把'+ '、'.join(tasks) +'哪些工作交給AI，與不僱員工有何關係？') if tasks and _has(r'\bAI\b', value) and _has(r'no employees|no.employee|without employees', value) else '這則創業消息的新進展是什麼，原文提供了哪些營運或資金證據？'
        outline = '創業者／公司與來源所述進展 → 已交代的工作做法或資金用途 → 規模、成本、資料期間與未說明的限制'
        method = '用原文支持的工作分工或資金用途做圖解，不把成立數增加當獲利保證，也不宣稱AI能取代所有員工。'
    elif angle == 'politics':
        disclosure = _has(r'\b(?:disclos\w*|bought|purchases?)\b', value) and _has(r'\b(?:stocks?|shares?|trading)\b', value) and _has(r'\b(?:ban|restrictions?|limits?)\b', value)
        hook = '議員的持股揭露與其支持的交易限制，時間、適用範圍和法律階段如何對照？' if disclosure else '這位政治人物提出或支持什麼變動，原文確認到了哪個政策階段？'
        outline = '人物與原文已揭露事實 → 表決／提案／規則的時間與範圍 → 已生效規定、政治主張與待核指控分開'
        method = '用時間線與規則範圍對照，不把支持禁令寫成禁令已生效，不由持股推定違法、內線或動機。'
    elif angle == 'recruiting':
        hook = 'AI加快了招募的哪一步，為什麼招募服務費也受到討論？' if _has(r'\bfees?\b', value) else 'AI介入了招募的哪個步驟，原文提供了什麼效率證據？'
        outline = '原文描述的篩選／招募流程 → AI介入的環節 → 招募業者對收費的說法及仍待驗證的影響'
        method = '用流程前後對照，效率、費用與當事人觀點分欄，不自行宣稱已取代招募人員。'
    elif angle == 'market':
        hook = 'AI相關股價反彈，與來源提出的泡沫／融資疑慮，是同一件事嗎？' if _has(r'\b(?:bubble|financing|funding)\b',value) else '這次AI相關股價變動，原文提供了哪些時點、幅度與背景？'
        outline = '原文報價與時間 → 作者提出的風險及證據 → 哪些是行情事實、哪些仍是判斷'
        method = '做行情與風險的雙欄對照，不自行判定泡沫已破裂或行情將延續。'
    elif angle == 'research_review':
        hook = 'AI協助開發AI的報告，究竟量到了什麼，研究者又在擔心什麼？' if _has(r'automat\w* AI development', title) else '這份AI研究的結論，能由哪些資料支持？'
        outline = '原研究問題 → 測量方法與發現 → 限制、反例與評論者的疑慮'
        method = '分開畫出研究觀察與推論，未回查原報告前不下定論。'
    elif angle == 'security_review':
        hook = 'AI改變了哪些資安攻防環節，哪些只是受訪者的預期？'
        outline = '受訪者討論的攻防問題 → 提出的例子 → 建議、預測與已確認事件分開'
        method = '做觀點與證據對照，不把訪談當成新入侵警報。'
    elif angle == 'usage_review':
        hook = '同一個料理AI為何能幫上晚餐，卻差點搞砸蛋糕？' if _has(r'\b(?:cooking|chicken|cake)\b', title) else '來源作者的AI使用經驗，哪些成功、哪些出錯？'
        outline = '作者交給AI的任務 → 成功與出錯的環節 → 測試條件及不能類推的部分'
        method = '用一成一敗講能力邊界，作者經驗與自行實測分開。'
    return {
        'stars': stars, 'display': '★'*stars+'☆'*(5-stars), 'label': labels[stars],
        'reason': '；'.join(reasons)+'。',
        'concept': f'**本則焦點**　{anchor}\n\n**切入問題**　{hook}\n\n**內容骨架**　{outline}\n\n**表現方式**　{method}',
        'basis': '依標題／摘要作規則初評；星等是製作優先度，高星不代表已完成查證。',
        'version': 2,
    }
