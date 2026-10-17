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
    if re.search(r'\b(?:etfs?|funds?)\b', source, re.I) and re.search(r'\b(?:outflows?|inflows?)\b|\bshed\s+\$', source, re.I):
        if re.search(r'(?:ETF|基金|資金).{0,12}(?:下跌|上漲|跌幅|漲幅)', result) and not re.search(r'\b(?:price|shares?|stocks?|nav)\b', source, re.I):
            raise ValueError('fund flows translated as price moves')
    if re.search(r'\bexploits?\b', source, re.I) and re.search(r'\b(?:hacks?|breaches|crypto)\b', source, re.I) and '利用' in result and '漏洞利用' not in result:
        raise ValueError('ambiguous security exploit translation')
    return result


def polish_chinese(source, translated):
    """Narrow source-led copy edits; never change figures or government entities."""
    corporate = bool(re.search(r"\b(?:its|their|corporate|company'?s?|firm'?s?)\s+(?:(?:bitcoin|crypto|digital.asset)\s+)?treasur(?:y|ies)\b|\btreasury company\b|\b(?:bitcoin|crypto|digital.asset)\s+treasur(?:y|ies)\b", source, re.I))
    government = bool(re.search(r'\b(?:(?:U\.?S\.?|United States)\s+Treasury|Treasury\s+(?:Department|Secretary))\b', source, re.I))
    if corporate and '財政部' in translated:
        if government:
            raise ValueError('ambiguous treasury translation')
        translated = translated.replace('財政部', '資產儲備')
    if re.search(r'\bCapital B\b', source):
        translated = translated.replace('資本 B', 'Capital B').replace('資本B', 'Capital B')
    for old, new in (('芯片', '晶片'), ('硬件', '硬體'), ('在線', '線上')):
        translated = translated.replace(old, new)
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


def time_copy(published, observed, *, scheduled=False):
    published, observed = published_time(published), published_time(observed)
    minutes = max(0, int((observed - published).total_seconds() // 60))
    base = '官方排定時間' if scheduled else '來源發布時間'
    rows = [f'📅 {base}：{published.astimezone(TAIPEI):%Y/%m/%d %H:%M}',
            f'🕒 機器人發現：{observed.astimezone(TAIPEI):%Y/%m/%d %H:%M}']
    late = minutes >= DELAY_MINUTES
    if late:
        rows.append(f'⏳ 補發｜距{base}約{minutes}分鐘；請留意原始時間。')
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
        text = f'{amount * 100:,.1f}萬美元'
    else:
        text = f'{amount * 1_000_000:,.2f}美元'
    return f'淨{"流入" if value > 0 else "流出"}{text}'
