"""Source-bounded Chinese copy, explicit time bases and deterministic news ranking."""
import re
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo('Asia/Taipei')
DELAY_MINUTES = 15


def has_chinese(value):
    return bool(re.search(r'[\u3400-\u9fff]', str(value)))


def numeric_values(text):
    scales = {'billion': 10**9, 'bn': 10**9, 'b': 10**9,
              'million': 10**6, 'm': 10**6, 'thousand': 1000, 'k': 1000,
              '億': 10**8, '萬': 10000, '千': 1000}
    pattern = r'(?<![A-Za-z0-9_.])([-+]?\d[\d,]*(?:\.\d+)?)\s*(billion\b|million\b|thousand\b|bn\b|[bmk]\b|億|萬|千)?'
    values = {Decimal(n.replace(',', '')) * scales.get((scale or '').lower(), 1)
              for n, scale in re.findall(pattern, str(text), re.I)}
    # A spelled-out month in an explicit source date may legitimately become
    # a Chinese numeric month. Never treat a bare month mention as a quantity.
    from news_policy_context import MONTHS
    for month in re.findall(r'\b('+'|'.join(MONTHS)+r')\s+\d{1,2},?\s+20\d{2}\b', str(text), re.I):
        values.add(Decimal(MONTHS[month.lower()]))
    return values


def checked_translation(source, translated):
    if not has_chinese(translated):
        raise ValueError('Chinese translation unavailable')
    if not numeric_values(translated).issubset(numeric_values(source)):
        raise ValueError('translation changed numeric facts')
    from news_policy_context import DATE, parse_date
    source_dates = {parse_date(raw) for raw in re.findall(DATE, source, re.I)}
    for year, month, day in re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', translated):
        from datetime import date
        try:
            translated_date = date(int(year), int(month), int(day))
        except ValueError:
            raise ValueError('invalid translated date')
        if translated_date not in source_dates:
            raise ValueError('translation changed date facts')
    if re.search(r'\bCHAD\b', source) and re.search(r'preferred|stock', source, re.I):
        translated = translated.replace('乍得', 'CHAD').replace('查德', 'CHAD')
    result = polish_chinese(source, translated)
    if numeric_values(result) != numeric_values(translated):
        raise ValueError('copy edit changed numeric facts')
    # Fail closed when the subject is a fund flow, but the copy calls it a price move.
    issue = (fund_flow_price_issue(source, result) or rate_step_issue(source, result) or as_clause_issue(source, result)
             or office_title_issue(source, result) or rulemaking_issue(source, result))
    if issue:
        raise ValueError(issue)
    if re.search(r'\bexploits?\b', source, re.I) and re.search(r'\b(?:hacks?|breaches|crypto)\b', source, re.I) and '利用' in result and '漏洞利用' not in result:
        raise ValueError('ambiguous security exploit translation')
    if unverified_name_gloss(source, result):
        raise ValueError('unverified Chinese name for a source proper noun')
    return result


# 2026-11-26 本人要修「ETF 資金流出被寫成價格下跌」：資金流與價格分開判斷，
# 只有原文明確寫價格／股價／淨值同方向變動，譯文才能寫 ETF／基金漲跌。
FUND = r'\b(?:etfs?|etps?|funds?)\b'
FLOW_WORDS = r'(?:\b(?:outflows?|inflows?|withdrawals?|redemptions?|bleed(?:s|ing)?|bled)\b|\bshed(?:s|ding)?\s+(?:US)?\$)'
PRICE_NOUN = r'\b(?:prices?|shares?|stocks?|navs?|net asset values?)\b'
DOWN_VERB = r'\b(?:fell|falls?|falling|drop(?:s|ped|ping)?|declin(?:e|es|ed|ing)|slid(?:e|es|ing)?|slump(?:s|ed|ing)?|tumbl(?:e|es|ed|ing)|sank|sinks?|lower|down)\b'
UP_VERB = r'\b(?:rose|rises?|rising|gain(?:s|ed|ing)?|jump(?:s|ed|ing)?|climb(?:s|ed|ing)?|rall(?:y|ies|ied|ying)|surg(?:e|es|ed|ing)|higher|up)\b'
CLAUSE = r'[^，,。；;：:！!？?\n]{0,12}'


def _price_move(context, verb):
    """Price evidence: a price noun near the verb, or a fund that itself moves by a non-dollar amount."""
    return bool(re.search(PRICE_NOUN + r'.{0,40}?' + verb, context, re.I)
                or re.search(verb + r'.{0,40}?' + PRICE_NOUN, context, re.I)
                or re.search(FUND + r'(?:\s+[\w’\'-]+){0,3}?\s+' + verb + r'(?!\s*(?:by\s+)?(?:US)?\$)', context, re.I))


def fund_flow_price_issue(context, copy):
    """Context is one source segment, or a headline plus its summary for the headline copy."""
    context = str(context or '')
    if not (re.search(FUND + r'.{0,80}?' + FLOW_WORDS, context, re.I) or re.search(FLOW_WORDS + r'.{0,80}?' + FUND, context, re.I)):
        return None
    if re.search(r'(?:ETF|ETP|基金|資金)' + CLAUSE + r'(?:下跌|跌幅|下滑|走低|走跌|重挫|暴跌)', copy) and not _price_move(context, DOWN_VERB):
        return 'fund flows translated as price decline'
    if re.search(r'(?:ETF|ETP|基金|資金)' + CLAUSE + r'(?:上漲|漲幅|走高|大漲|上揚)', copy) and not _price_move(context, UP_VERB):
        return 'fund flows translated as price rise'
    return None


# 2026-11-26 本人要修CNBC／CoinDesk舊卡（全部舊卡一起修）：以下只擋，不猜正確譯法；
# 可確定的狹義修正在 news_copy_terms.semantic_repairs，修完仍不符就換翻譯來源，最後不採用。
def rate_step_issue(source, copy):
    """1碼＝25個基點：譯文寫的碼數必須是原文明寫的幅度（half-point＝兩碼，不是半碼）。"""
    from news_copy_terms import copy_rate_steps, rate_sizes
    steps = copy_rate_steps(copy)
    if steps and not steps <= rate_sizes(source):
        return 'rate step size changed'
    return None


AS_CLAUSE_VERBS = (r'(?:grew|grows?|rose|rises?|fell|falls?|slid|slides?|sank|sinks?|spreads?|'
                   r'(?:mount|deepen|widen|climb|soar|jump|drop|slump|tumble|decline|ease|cool|intensif(?:y|ie)|worsen|'
                   r'expand|slow|accelerate|loom|persist|continue|weigh|unfold|surge|increase|shrink|narrow|stall|fade|'
                   r'rebound|retreat|rall(?:y|ie))(?:s|d|ed|ped)?)')
AS_NOT_ROLE_BEFORE = {'such', 'well', 'much', 'many', 'long', 'soon', 'far', 'just', 'same', 'so', 'known'}


def as_clause_issue(source, copy):
    """`as`＋主詞＋動詞是「在……之際／隨著」；「作為」多於原文身分用法的 as 就不採用。"""
    role = clause = 0
    for match in re.finditer(r'\bas\b', str(source), re.I):
        before = str(source)[:match.start()].split()
        after = str(source)[match.end():]
        if (before and before[-1].lower().strip('"“‘\'') in AS_NOT_ROLE_BEFORE) or re.match(
                r'\s+(?:well|long|soon|much|many|far|if|though|of|part|to|for|opposed|such|usual|expected)\b', after, re.I):
            continue  # as well as／as of／as expected… never mean 「作為」
        if re.match(r'\s+(?:[^\s;:!?]+\s+){1,6}?' + AS_CLAUSE_VERBS + r'\b', after, re.I):
            clause += 1
        else:
            role += 1
    if clause and copy.count('作為') > role:
        return 'as-clause translated as a role'
    return None


def office_title_issue(source, copy):
    """SEC pick／Fed governor 不是主席；原文沒寫 chair／president／head 就不能自行補上。"""
    from news_copy_terms import CHAIR_SOURCE
    if (re.search(r'(?:SEC|CFTC|FTC|FCC|FDIC|OCC|聯準會|央行|證交會|委員會)\s*的?\s*主席', copy)
            and not re.search(CHAIR_SOURCE, str(source), re.I)):
        return 'translation added a chair title'
    return None


def rulemaking_issue(source, copy):
    """機關的規則制定／公眾意見程序不是國會立法。"""
    from news_copy_terms import LEGISLATION, RULEMAKING
    source = str(source)
    if (re.search(RULEMAKING, source, re.I) and '立法' in copy
            and not (re.search(LEGISLATION, source, re.I) or re.search(r'\bAct\b', source))):
        return 'agency rulemaking translated as legislation'
    return None


# 2026-11-26 本人要修「Megaspeed 被寫成兆芯」：翻譯器自帶的「中文（English）」單字專名配對，
# 只接受下面已核對的中文名；沒核對過的就換別的翻譯來源，最後仍不行就不採用，保留原文由下一輪處理。
# 表內是 11/26 掃過全球錢線、幣圈又有事最近 522 張卡實際出現且核對正確的配對。
VERIFIED_NAME_GLOSSES = {
    'Nvidia': ('輝達', '英偉達'), 'Tesla': ('特斯拉',), 'Citigroup': ('花旗集團', '花旗'), 'Citi': ('花旗', '花旗集團'),
    'Binance': ('幣安',), 'Thales': ('泰雷茲',), 'Deribit': ('德裏比特', '德瑞比特'), 'Waller': ('沃勒',),
    'Sacks': ('薩克斯',), 'Winklevoss': ('溫克沃斯', '溫克沃斯兄弟'), 'BlackRock': ('貝萊德',), 'Fed': ('聯準會',),
}


def unverified_name_gloss(source, copy):
    """Return a source proper noun the copy glosses with an unverified Chinese name."""
    for match in re.finditer(r'([㐀-鿿])\s*[（(]\s*([A-Z][a-z][A-Za-z0-9]*)\s*[)）]', copy):
        name = match[2]
        if not re.search(r'(?<![A-Za-z])' + re.escape(name) + r'(?![A-Za-z])', str(source)):
            continue
        head = copy[:match.start(1) + 1]
        if not any(head.endswith(alias) for alias in VERIFIED_NAME_GLOSSES.get(name, ())):
            return name
    return None


def polish_chinese(source, translated):
    """Narrow source-led copy edits; never change figures or government entities."""
    from news_copy_terms import repair_translation
    translated = repair_translation(source, translated)
    corporate = bool(re.search(r"\b(?:its|their|corporate|company'?s?|firm'?s?)\s+(?:(?:bitcoin|crypto|digital.asset)\s+)?treasur(?:y|ies)\b|\btreasury\s+(?:compan(?:y|ies)|firms?)\b|\b(?:bitcoin|crypto|digital.asset)\s+treasur(?:y|ies)\b|\b(?:bitcoin|crypto)\s+(?:firm|company)\b.{0,70}\btreasury\s+(?:ranks|rankings)\b", source, re.I))
    government = bool(re.search(r'\b(?:(?:U\.?S\.?|United States)\s+Treasury|Treasury\s+(?:Department|Secretary))\b', source, re.I))
    if corporate and '財政部' in translated:
        if government:
            raise ValueError('ambiguous treasury translation')
        translated = translated.replace('財政部', '資產儲備')
    # 資金流出不是交易虧損；只修明確的資金流語境，混合損益時交回核對。
    if not re.search(r'\b(?:trading losses?|net loss|profits?|pnl)\b', source, re.I):
        if re.search(r'\b(?:ETFs?|funds?)\b.{0,90}\b(?:outflows?|shed)\b', source, re.I):
            translated = re.sub(r'((?:ETF|基金).{0,12}?)(?:淨虧損|淨損失|虧損)', r'\1資金淨流出', translated)
        if re.search(r'\b(?:customers?|users?)\b.{0,65}\b(?:net outflows?|shed|lost)\b|\b(?:net outflows?)\b.{0,45}\b(?:customers?|users?)\b', source, re.I) and re.search(r'\b(?:outflows?|net)\b', source, re.I):
            translated = re.sub(r'((?:Binance|幣安).{0,8}(?:客戶|用戶|使用者).{0,8}?)(?:淨虧損|淨損失)', r'\1資金淨流出', translated)
    if re.search(r'\bCapital B\b', source):
        translated = translated.replace('資本 B', 'Capital B').replace('資本B', 'Capital B')
    for old, new in (('芯片', '晶片'), ('硬件', '硬體'), ('在線', '線上'),
                     # One card must not mix 聯準會／美聯儲／聯儲局 or mainland/Taiwan terms.
                     ('美聯儲', '聯準會'), ('美聯準會', '聯準會'), ('聯儲局', '聯準會'), ('人工智能', '人工智慧'),
                     ('黑客', '駭客'), ('網絡', '網路'), ('數據中心', '資料中心'), ('加息', '升息'), ('減息', '降息')):
        translated = translated.replace(old, new)
    # Proper names the translator turns into common words; only when the source names them.
    if re.search(r'\bSecuritize\b', source) and not re.search(r'\bsecuriti[sz]ation\b', source, re.I):
        translated = translated.replace('證券化', 'Securitize')
    if re.search(r'\bElliptic\b', source):
        translated = re.sub(r'橢圓形?', 'Elliptic', translated)
    if re.search(r'\bMeta\b', source) and 'Meta' not in translated:
        translated = re.sub(r'(?<=的)元(?=前景|股|平台|公司)|^元(?=前景|股|平台|公司)', 'Meta ', translated)
    if re.search(r'\b(?:buy|buying|bought|slam|slams|scoop|scoops)\s+(?:up\s+)?the\s+dip\b', source, re.I):
        translated = re.sub(r'(?:猛烈抨擊|抨擊|購買|買入|猛買)\s*(?:the\s*)?(?:DIP|Dip|dip|下跌)', '逢低買進', translated)
    translated = re.sub(r'(?<=[a-z])(?=Bitcoin\b|Ethereum\b)', ' ', translated)
    if re.search(r'\bwarrant exercises?\b|\bexercis\w*\b.{0,30}\bwarrants?\b', source, re.I):
        translated = translated.replace('認股權證活動', '認股權證行使金額')
    translated = re.sub(r'\b([A-Z][A-Z0-9]{1,9})\s*[（(]\s*\1\s*[)）]', r'\1', translated)
    if re.search(r'\$\s*\d|\bUSD\b|U\.S\. dollars?', source, re.I) and not re.search(r'(?:[CA]|HK|NZ|SG)\$|\b(?:CAD|AUD|HKD|NZD|SGD)\b', source, re.I):
        translated = re.sub(r'(?<![A-Za-z$])\$\s*(\d[\d,]*(?:\.\d+)?)\s*(億|萬|千)?(?:\s*美元)?', lambda m: m[1]+(m[2] or '')+'美元', translated)
        translated = re.sub(r'(\d[\d,]*(?:\.\d+)?\s*(?:億|萬|千)?)\s*\$(?:\s*美元)?', r'\1美元', translated)
    if re.search(r'(?:億|萬|千)\s*[$€£]|[$€£]\s*[$€£]', translated):
        raise ValueError('ambiguous currency format')
    translated = re.sub(r'(\d)\s+%', r'\1%', translated)
    translated = re.sub(r'(\d)\s+(億|萬|千)', r'\1\2', translated)
    return translated


def digest_exclusion_reason(item):
    import news_auto_recovery as auto
    from content_contract import article_issues
    if article_issues(item):
        return '原文與逐段中文證據未通過'
    try:
        checker = auto.checked_copy if auto.enabled() else checked_translation
        title = checker(str(item.get('title') or ''), str(item.get('title_zh') or ''))
    except ValueError:
        return '中文標題未確認'
    if re.search(r'待確認|尚未確認|請閱讀原文', title):
        return '中文標題未確認'
    if not auto.enabled() and re.fullmatch(r'(?:your\s+)?day[- ]ahead look(?:\s+for\s+.+)?[.!]?', str(item.get('summary') or '').strip(), re.I):
        return '摘要僅為導讀'
    points = chinese_points(item)
    if not points:
        return '中文摘要未確認'
    if all(re.search(r'待確認|尚未確認|請閱讀原文|仍需核對|來源已確認的事實', point) for point in points):
        return '摘要僅為提示'
    from news_policy_context import policy_context
    context = policy_context(item)
    if context and context['reason'] and not auto.enabled():
        return context['reason']
    return None


def headline(item):
    value = str(item.get('title_zh') or '')
    try:
        return checked_translation(item.get('title', ''), value)
    except ValueError:
        category = item.get('category')
        key = category.get('key') if isinstance(category, dict) else category
        label = {'security': '資安消息', 'regulation': '監管政策', 'etf': '機構與ETF',
                 'stablecoin': '穩定幣消息', 'exchange': '交易所消息', 'network': '協議動態'}.get(key, '市場消息')
        return f'{label}｜中文標題待確認'


def chinese_points(item):
    if item.get('content_contract'):
        from content_contract import article_issues
        if article_issues(item):
            return []
        return [p['zh'] for p in item['content_contract']['pairs']]
    points = []
    source = str(item.get('summary_check_source') or item.get('summary') or item.get('title') or '')
    for point in item.get('summary_zh_points') or []:
        if str(point).startswith('消息涉及'):
            continue
        try:
            points.append(checked_translation(source, str(point)))
        except ValueError:
            continue
    return points


def published_time(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def elapsed_copy(minutes):
    """2026-11-15 本人選「推播文字修正」：讀者看「約21小時」比「約1288分鐘」直覺。"""
    if minutes < 120:
        return f'約{minutes}分鐘'
    hours = round(minutes / 60)
    if hours < 48:
        return f'約{hours}小時'
    return f'約{round(hours / 24)}天'


def time_copy(published, observed, *, scheduled=False):
    published, observed = published_time(published), published_time(observed)
    minutes = max(0, int((observed - published).total_seconds() // 60))
    base = '官方排定時間' if scheduled else '來源發布時間'
    # 「機器人發現」是內部用語；讀者看到的是本群送出的時間。
    rows = [f'📅 {base}：{published.astimezone(TAIPEI):%Y/%m/%d %H:%M}',
            f'🕒 {"本群發布" if scheduled else "本次整理時間"}：{observed.astimezone(TAIPEI):%Y/%m/%d %H:%M}']
    late = minutes >= DELAY_MINUTES
    if late:
        rows.append(f'⏳ 補發｜距{base}{elapsed_copy(minutes)}；請留意原始時間。')
    return '\n'.join(rows), late


def news_score(item):
    from slim_policy import material_news
    title = str(item.get('title') or '')
    text = (title + ' ' + str(item.get('summary') or '')).lower()
    if material_news(item):
        score = 100
    elif re.search(r'\b(approved|approves|rejected|enacted|court orders|ruling|regulation|policy|redemption)\b', text):
        score = 70
    elif re.search(r'\b(etf|fund flows?|net inflows?|net outflows?|upgrade|hard fork|mainnet)\b', text):
        score = 60
    elif re.search(r'\b(treasury|custody|institutional|stablecoin)\b', text):
        score = 45
    else:
        score = 20
    if re.search(r'\b(opinion|prediction|could|debate|why you|how to)\b', title.lower()):
        score -= 35
    return score + (10 if item.get('official') else 0)


def rank_news(items):
    return sorted(items, key=lambda r: (news_score(r), published_time(r['published']), str(r.get('id', ''))), reverse=True)


def money_musd(value):
    value = float(value)
    if value == 0:
        return '合計0美元（依來源數值）'
    amount = abs(value)
    if amount >= 100:
        text = f'{amount / 100:,.2f}億美元'
    elif amount >= .01:
        # 3,910萬 and 3,910.0萬 must not appear side by side on the same card.
        text = re.sub(r'\.0$', '', f'{amount * 100:,.1f}') + '萬美元'
    else:
        text = f'{amount * 1_000_000:,.2f}美元'
    return f'淨{"流入" if value > 0 else "流出"}{text}'
