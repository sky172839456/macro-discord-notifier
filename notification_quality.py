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
    return {Decimal(n.replace(',', '')) * scales.get((scale or '').lower(), 1)
            for n, scale in re.findall(pattern, str(text), re.I)}


def checked_translation(source, translated):
    if not has_chinese(translated):
        raise ValueError('Chinese translation unavailable')
    if not numeric_values(translated).issubset(numeric_values(source)):
        raise ValueError('translation changed numeric facts')
    if re.search(r'\bCHAD\b', source) and re.search(r'preferred|stock', source, re.I):
        translated = translated.replace('乍得', 'CHAD').replace('查德', 'CHAD')
    return translated


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
    source = str(item.get('summary') or item.get('title') or '')
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
