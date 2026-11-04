"""Private IG topic inbox. Public facts only; never publishes to IG/member channels."""
from sender_identity import sender_name
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import gzip
import io
import os
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Taipei')
CHANNEL = '1567112861287710741'
GUILD = '1524947809499877486'
AI_SOURCES = (
    ('OpenAI News', 'https://openai.com/news/rss.xml', 'openai.com'),
    ('Google DeepMind', 'https://deepmind.google/blog/rss.xml', 'deepmind.google'),
    ('Google AI', 'https://blog.google/technology/ai/rss/', 'blog.google'),
    ('Hugging Face', 'https://huggingface.co/blog/feed.xml', 'huggingface.co'),
)
STORY_SOURCES = (('The Verge', 'https://www.theverge.com/rss/index.xml', 'theverge.com'),)
MATERIAL_SOURCES = AI_SOURCES + STORY_SOURCES
NEW_SOURCE_NAMES = {row[0] for row in AI_SOURCES[2:] + STORY_SOURCES}


def fetch_feed(url, attempts=1):
    if url not in {r[1] for r in MATERIAL_SOURCES}:
        raise ValueError('unapproved material feed')
    request = Request(url, headers={'User-Agent': 'WV-material-inbox/1.0', 'Accept': 'application/rss+xml,application/xml', 'Accept-Encoding': 'identity'})
    with urlopen(request, timeout=15) as response:
        raw = response.read(2000001)
    if len(raw) > 2000000:
        raise ValueError('compressed feed too large')
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(4000001)
    if len(raw) > 4000000:
        raise ValueError('expanded feed too large')
    return raw.decode('utf-8-sig')
ANGLES = {
    'security': ('資安／服務事件', '涉及資安或服務異常，適合拆解事件、受影響範圍與已確認處置。',
                 '限動追蹤進展；資料核對完整後做Reels時間線或事件輪播。',
                 '核對當事方公告、事件日期、受害範圍、金額與追回進度；不要把傳聞或舊事故當新事件。'),
    'policy': ('政策／監管', '制度或適用範圍有變化，適合說明誰受影響、何時生效。',
               '貼文比較變更前後；Reels用一個實際情境解說。',
               '核對地區、生效日、適用對象及草案／通過／生效階段；不把提議當已實施。'),
    'ai': ('AI／研究', '有產品或研究進展，可轉成使用情境、方法或限制的解說。',
           '限動介紹原始公告；Reels展示流程；輪播比較用途與限制。',
           '核對發布／開放時間、費用、實際可用範圍、研究條件；官方效能主張不等於獨立實測。'),
    'business': ('企業／交易所進展', '合作、收購或服務變更可整理成具體改變與用戶影響。',
                 '限動快訊；貼文整理雙方、合作內容與實際落地階段。',
                 '核對雙方公告、金額與範圍、洽談／簽約／交割／上線階段；不把意向當完成。'),
    'interesting': ('趣聞／人物事件', '具體人物故事、反常事件或生活應用有敘事切入點，可做輕鬆但有知識點的內容。',
                 '限動用一個問題帶出事件；Reels講故事；輪播補充背景與容易誤解的地方。',
                 '核對人物原話、原始日期與上下文；區分趣味、諷刺、傳聞與事實，不把轉帳等同買賣或替人物推測動機。'),
    'research': ('研究／市場知識', '有報告或研究可拆解方法、數據與限制，延伸成常青教材。',
                 '輪播拆成問題、研究發現、證據與限制；Reels解釋單一概念。',
                 '讀原始論文或報告，核對資料期間、樣本、方法與利益關係；不把相關性寫成因果。'),
}


def clean(value, limit):
    value = re.sub(r'<[^>]*>', ' ', str(value))
    value = re.sub(r'[@`*\[\]<>]', '', value)
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def public_url(url, host=None):
    parsed = urlparse(str(url))
    actual = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or parsed.username or parsed.password or not actual:
        return False
    if host and actual not in (host, 'www.'+host):
        return False
    return True


def parse_ai_feed(xml, name, host, *, ai=True, official=True):
    rows = []
    tree = ElementTree.fromstring(xml)
    atom = '{http://www.w3.org/2005/Atom}'
    entries = tree.findall('.//item') or tree.findall('.//'+atom+'entry')
    for entry in entries[:30]:
        title = entry.findtext('title') or entry.findtext(atom+'title') or ''
        summary = entry.findtext('description') or entry.findtext(atom+'summary') or entry.findtext(atom+'content') or ''
        url = entry.findtext('link') or ''
        if not url:
            link = next((x for x in entry.findall(atom+'link') if x.get('rel', 'alternate') == 'alternate'), None)
            url = link.get('href', '') if link is not None else ''
        date = entry.findtext('pubDate') or entry.findtext(atom+'published') or entry.findtext(atom+'updated') or ''
        try:
            published = parsedate_to_datetime(date) if ',' in date else datetime.fromisoformat(date.replace('Z', '+00:00'))
            if published.tzinfo is None or not public_url(url, host):
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        rows.append({'id': sha256(url.encode()).hexdigest()[:24], 'title': clean(title, 300),
                     'summary': clean(summary, 800), 'url': url, 'published': published,
                     'source': name, 'official': official, 'material_ai': ai})
    return rows


def topic(row):
    title = str(row.get('title', ''))
    body = title+' '+str(row.get('summary', ''))
    if re.search(r'\b(?:sponsored|presale|giveaway|airdrop|price prediction|stocks? to buy|hiring|webinar|podcast|live updates?)\b', title, re.I):
        return None
    from news_editorial import safety_candidate, retrospective, verified_security_explainer
    if verified_security_explainer(row):
        return "research"
    if safety_candidate(row):
        return 'security'
    if retrospective(row) or re.search(r'\b(?:weekly|monthly|daily) (?:recap|roundup|round-up|review)\b', title, re.I):
        return None
    if row.get('material_ai') or re.search(r'\b(?:artificial intelligence|openai|anthropic|deepmind|claude|chatgpt|gemini|AI|LLMs?|GPT|Copilot|machine learning|generative|agentic)\b', title, re.I):
        return 'ai'
    key = (row.get('category') or {}).get('key') if isinstance(row.get('category'), dict) else row.get('category')
    if key in ('regulation', 'finance_policy') or re.search(r'\b(?:law|regulation|regulator|legislation|monetary policy)\b', title, re.I):
        return 'policy'
    if re.search(r'\b(?:study|research|paper|report finds|researchers)\b', title, re.I):
        return 'research'
    if re.search(r'\b(?:partnership|partners with|collaborat\w*|acquir\w*|acquisition|merger|launch\w*|expands?|investment)\b', title, re.I):
        return 'business'
    # Concrete story hooks from existing feeds, not a blanket catch-all for hype.
    if re.search(
        r'\b(?:bitcoin pizza|pizza day|solo miner|lottery miner|lost (?:bitcoin |crypto )?wallet|'
        r'dormant (?:bitcoin |crypto )?wallet|accidental(?:ly)?|mistaken(?:ly)?|'
        r'world record|guinness|meme culture|crypto wedding|bitcoin wedding|'
        r'(?:robot|humanoid)\w* .{0,65}(?:dance|dances|cook|cooks|play|plays|learn|learns|paint|paints)|'
        r'(?:weird|surprising|unexpected) .{0,65}(?:experiment|invention|discovery|technology)|'
        r'(?:buys?|bought|pays?|paid) .{0,65} (?:with|using|in) (?:bitcoin|crypto|btc)|'
        r'(?:cz|changpeng zhao|vitalik buterin|elon musk) (?:says?|said|reveals?|responds?|jokes?|shares?))\b',
        title, re.I):
        return 'interesting'
    return None


def urgent(row):
    if row['material_topic'] == 'security':
        return True
    return row['material_topic'] == 'policy' and bool(re.search(
        r'\b(?:enacts?|enacted|approves?|approved|court orders|signs? into law|emergency|imposes? sanctions?|capital controls?)\b',
        str(row.get('title', '')), re.I))


def key(row):
    value = str(row.get('url', ''))+'|'+str(row.get('title', ''))+'|'+str(row.get('summary', ''))
    return sha256(value.encode()).hexdigest()[:32]


def equivalent(a, b):
    from crypto_news_notifier import same_news_event
    return key(a) == key(b) or same_news_event(a, b)


def card(row, now):
    label, why, formats, checks = ANGLES[row['material_topic']]
    from notification_quality import checked_translation, chinese_points, published_time
    title = clean(row.get('title_zh', ''), 180)
    try:
        title = checked_translation(row['title'], title)
    except ValueError:
        title = f'{label}候選｜原文標題待中文核對'
    points = chinese_points(row)
    facts = '\n'.join('• '+clean(p, 190) for p in points[:2]) if points else clean(row.get('summary') or row['title'], 430)
    status = ('官方自行公布；效能、適用範圍與發布階段仍須讀原文核對。' if row['material_topic'] == 'ai' and row.get('official') else
              '官方來源候選；列示內容仍須核對範圍與實施階段。' if row.get('official') else
              '媒體報導候選；尚未以直接官方資料完成獨立核實。')
    fields = [
        {'name': '📌 來源內容'+('（中文未完整核對，保留原文片段）' if not points else ''), 'value': facts or '請開啟原文核對。', 'inline': False},
        {'name': '💡 為什麼值得做', 'value': why, 'inline': False},
        {'name': '🎬 建議形式', 'value': formats, 'inline': False},
        {'name': '🔎 查證狀態／製作前要補', 'value': status+'\n\n'+checks, 'inline': False},
    ]
    refs = [{'source': row.get('source', '來源'), 'url': row['url']}, *row.get('related_sources', [])]
    refs = [r for r in refs if public_url(r.get('url'))][:3]
    links = '\n'.join(f'[{clean(r["source"], 60)}]({r["url"]})' for r in refs)
    fields.append({'name': '🔗 來源與時間', 'value': links+f'\n原文：{published_time(row["published"]).astimezone(TZ):%Y/%m/%d %H:%M}\n收錄：{now.astimezone(TZ):%Y/%m/%d %H:%M}（台灣）', 'inline': False})
    result = {'title': '📝 素材候選｜'+title, 'description': f'分類：{label}\n\n【僅管理員】選題建議，不代表事實已全部核實或已製作發布。\n\n原文標題：'+clean(row['title'], 210),
              'fields': fields, 'color': 0xB99B66, 'timestamp': now.isoformat(),
              'footer': {'text': 'WV素材整理｜先查證再製作｜不會自動發布IG'}}
    if any(len(f['value']) > 1024 for f in fields) or sum(len(f['name'])+len(f['value']) for f in fields)+len(result['description']) > 5500:
        raise ValueError('material card exceeds bounds')
    return result


def verify_destination(webhook):
    # GET only; never guess a public/log destination when the new secret is absent.
    parsed = urlparse(webhook)
    if parsed.scheme != 'https' or parsed.hostname not in ('discord.com', 'discordapp.com') or not parsed.path.startswith('/api/webhooks/'):
        raise ValueError('invalid material webhook')
    with urlopen(Request(webhook, headers={'User-Agent': 'WV-material-inbox/1.0'}), timeout=15) as response:
        meta = json.load(response)
    if str(meta.get('channel_id')) != CHANNEL or str(meta.get('guild_id')) != GUILD:
        raise ValueError('material destination mismatch')


class DeliveryUncertain(RuntimeError):
    """A request might have reached Discord. Do not auto-replay it."""


def send_card(webhook, embed, username):
    from notification_format import readable_card
    embed = readable_card({**embed, 'author': {'name': 'W VIEWTURE｜私人素材整理'}})
    payload = json.dumps({'username': sender_name('material_inbox'), 'embeds': [embed], 'allowed_mentions': {'parse': []}}).encode()
    request = Request(webhook+'?wait=true', data=payload, headers={'Content-Type': 'application/json', 'User-Agent': 'WV-material-inbox/1.0'}, method='POST')
    try:
        with urlopen(request, timeout=25) as response:
            result = json.load(response)
    except HTTPError:
        raise  # Explicit HTTP rejection remains queued for the existing next scan.
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise DeliveryUncertain('material delivery not confirmed') from exc
    if str(result.get('channel_id')) != CHANNEL or not str(result.get('id', '')).isdigit():
        raise DeliveryUncertain('material response not confirmed')
    return str(result['id'])


def run(rows, state, now, *, fetch, send, persist, enrich=None, verify=verify_destination):
    if os.getenv('MATERIAL_INBOX_ENABLED') != '1':
        return 0
    webhook = os.getenv('DISCORD_MATERIAL_WEBHOOK_URL')
    if not webhook:
        print('素材整理：私人目的地未設定，不改送其他頻道。')
        return 0
    box = state.get('material_inbox_v1')
    if box is None:
        state['material_inbox_v1'] = {'started_at': now.isoformat(), 'items': [], 'source_status': [], 'source_started_at': {n: now.isoformat() for n in NEW_SOURCE_NAMES}}
        persist()
        return 0  # New feature starts now; do not replay old feed entries.
    from notification_quality import published_time
    if not isinstance(box, dict) or not isinstance(box.get('items'), list) or not box.get('started_at'):
        raise ValueError('material ledger invalid; do not initialize or resend')
    started = published_time(box['started_at'])
    if started.tzinfo is None:
        raise ValueError('material start timestamp invalid')
    combined = list(rows)
    statuses = []
    for name, url, host in MATERIAL_SOURCES:
        try:
            parsed = parse_ai_feed(fetch(url, attempts=1), name, host, ai=name not in {r[0] for r in STORY_SOURCES}, official=name not in {r[0] for r in STORY_SOURCES})
            if not parsed:
                raise ValueError('empty official AI feed')
            if name in NEW_SOURCE_NAMES:
                source_starts = box.setdefault('source_started_at', {})
                if not isinstance(source_starts, dict):
                    raise ValueError('material source ledger invalid')
                source_start = source_starts.setdefault(name, now.isoformat())
                parsed = [r for r in parsed if r['published'] >= published_time(source_start)]
            combined.extend(parsed)
            statuses.append({'source': name, 'readable': True})
        except Exception as exc:
            statuses.append({'source': name, 'readable': False, 'reason': type(exc).__name__})
    box['source_status'] = statuses
    box['items'] = [r for r in box['items'] if published_time(r['published']) >= now-timedelta(days=30)]
    for raw in combined:
        try:
            date = published_time(raw['published'])
            if date.tzinfo is None:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        selected = topic(raw)
        if not selected or date < max(started, now-timedelta(hours=24)) or date > now+timedelta(minutes=5) or not public_url(raw.get('url')):
            continue
        old = next((r for r in box['items'] if equivalent(raw, r)), None)
        if old:
            refs = old.setdefault('related_sources', [])
            if raw['url'] != old['url'] and all(r['url'] != raw['url'] for r in refs) and len(refs) < 2:
                refs.append({'source': raw.get('source', '來源'), 'url': raw['url']})
            continue
        row = {k: raw.get(k) for k in ('id', 'title', 'summary', 'url', 'source', 'official', 'title_zh', 'summary_zh_points', 'event_context') if raw.get(k) is not None}
        row.update(published=date.isoformat(), material_key=key(raw), material_topic=selected, status='queued', collected_at=now.isoformat())
        box['items'].append(row)
    box['items'] = box['items'][-500:]
    persist()  # Outbox is durable before a send can fail.
    waiting = [r for r in box['items'] if r.get('status') == 'queued' and published_time(r['published']) >= now-timedelta(hours=24)]
    waiting.sort(key=lambda r: (urgent(r), r['published']), reverse=True)
    if not waiting:
        return 0
    verify(webhook)
    count = 0
    for row in waiting:
        if count >= 2:
            break  # Batch only; no daily quota. Remaining candidates wait for the next scan.
        if enrich:
            # Title-only translation through the existing checked free provider.
            # Do not invent Chinese summaries or consume a new paid AI service.
            try:
                from notification_quality import checked_translation
                row['title_zh'] = checked_translation(row['title'], enrich(row['title']))
            except Exception:
                pass
        try:
            message_id = send(webhook, card(row, now), 'WV素材整理｜私人選題')
        except DeliveryUncertain:
            row['status'], row['delivery_checked_at'] = 'delivery_unknown', now.isoformat()
            persist()
            print('素材整理：本則送達未確認，保留紀錄、停止自動重送，待讀回核對。')
            continue
        if message_id:
            row['message_id'] = str(message_id)
        row['status'], row['notified_at'] = 'notified', now.isoformat()
        persist()  # A later failed send must not replay an already confirmed item.
        count += 1
    return count
