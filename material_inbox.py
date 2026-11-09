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
import html
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
RESEARCH_SOURCES = (
    ('Microsoft Research', 'https://www.microsoft.com/en-us/research/feed/', 'microsoft.com'),
    ('MIT AI', 'https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml', 'news.mit.edu'),
    ('MIT Robotics', 'https://news.mit.edu/topic/mitrobotics-rss.xml', 'news.mit.edu'),
)
MATERIAL_SOURCES = AI_SOURCES + STORY_SOURCES + RESEARCH_SOURCES
NEW_SOURCE_NAMES = {row[0] for row in AI_SOURCES[2:] + STORY_SOURCES + RESEARCH_SOURCES}


def parse_source_feed(xml, name, host):
    """Share source identity/classification between production and no-send checks."""
    research = name in {r[0] for r in RESEARCH_SOURCES}
    rows = parse_ai_feed(xml, name, host,
                         ai=name in {r[0] for r in AI_SOURCES},
                         official=name not in {r[0] for r in STORY_SOURCES})
    for row in rows:
        row['material_research'] = research
    return rows


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
    'ai': ('AI／新工具', 'AI模型、新工具、系統或研究進展，可轉成使用情境、方法與限制的解說，不限金融用途。',
           '限動介紹原始公告；Reels展示流程；輪播比較用途與限制。',
           '核對發布／開放時間、費用、實際可用範圍、研究條件；官方效能主張不等於獨立實測。'),
    'innovation': ('科技／新發明', '新系統、產品、載具或發明有具體進展，適合說明解決什麼問題、如何運作與目前做到哪一步，不限金融用途。',
                   '限動用有趣問題帶入；Reels解釋運作過程；輪播比較用途、現有做法與限制。',
                   '核對原始展示、日期與實際能力；明列構想／展示／原型／測試／開賣階段，區分廠商主張與獨立實測，不把示意影片當已量產。'),
    'business': ('企業／交易所進展', '合作、收購或服務變更可整理成具體改變與用戶影響。',
                 '限動快訊；貼文整理雙方、合作內容與實際落地階段。',
                 '核對雙方公告、金額與範圍、洽談／簽約／交割／上線階段；不把意向當完成。'),
    'interesting': ('趣聞／人物事件', '人物故事、反常事件、生活應用或文化趣事有具體敘事切入點，可做輕鬆但有知識點的內容，不限金融圈。',
                 '限動用一個問題帶出事件；Reels講故事；輪播補充背景與容易誤解的地方。',
                 '核對人物原話、原始日期與上下文；區分趣味、諷刺、傳聞與事實，不把轉帳等同買賣或替人物推測動機。'),
    'research': ('研究／市場知識', '有報告或研究可拆解方法、數據與限制，延伸成常青教材。',
                 '輪播拆成問題、研究發現、證據與限制；Reels解釋單一概念。',
                 '讀原始論文或報告，核對資料期間、樣本、方法與利益關係；不把相關性寫成因果。'),
}


def clean(value, limit):
    value = html.unescape(html.unescape(str(value)))
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


def collect_feed(xml, cfg, rows, audit=None):
    """Collect raw private candidates before member relevance/budget gates."""
    result = {'source': cfg['name']}
    try:
        host = (urlparse(cfg['url']).hostname or '').removeprefix('www.')
        parsed = parse_ai_feed(xml, cfg['name'], host, ai=False, official=cfg['official'])
        rows.extend(parsed)
        result.update(parsed=len(parsed), error=None)
    except Exception as exc:
        result.update(parsed=0, error=type(exc).__name__)
    if audit is not None:
        audit.append(result)


def topic(row):
    title = str(row.get('title', ''))
    body = title+' '+str(row.get('summary', ''))
    if re.search(r'\b(?:sponsored|presale|giveaway|airdrop|price prediction|stocks? to buy|hiring|webinar|podcast|live updates?)\b', title, re.I):
        return None
    from news_editorial import safety_candidate, retrospective, verified_security_explainer
    if verified_security_explainer(row):
        return "research"
    if safety_candidate(row) or mcp_incident(row):
        return 'security'
    if retrospective(row) or re.search(r'\b(?:weekly|monthly|daily) (?:recap|roundup|round-up|review)\b', title, re.I):
        return None
    if exchange_access_notice(title):
        return 'policy' if re.search(r'\b(?:regulator|regulatory|regulation|compliance|law)\b', body, re.I) else 'business'
    if (re.search(r'\b(?:U\.?S\.? Treasury|SEC|regulators?)\b', title, re.I)
            and re.search(r'\b(?:crypto exchange|exchange)\b', title, re.I)
            and re.search(r'\b(?:cut off|sanctions?|ban\w*|restrict\w*|charges?)\b', title, re.I)):
        return 'policy'
    from material_editorial import editorial_angle
    angle = editorial_angle(title, str(row.get('summary', '')))
    if angle in ('people', 'startup'):
        return 'business'
    if angle == 'politics':
        return 'policy'
    if angle in ('market', 'research_review', 'security_review'):
        return 'research'
    if angle == 'usage_review':
        return 'interesting'
    key = (row.get('category') or {}).get('key') if isinstance(row.get('category'), dict) else row.get('category')
    if key in ('regulation', 'finance_policy') or re.search(r'\b(?:law|regulation|regulator|legislation|monetary policy)\b', title, re.I):
        return 'policy'
    if re.search(r'\b(?:partnership|partners with|acquir\w*|acquisition|merger)\b', title, re.I):
        return 'business'
    from material_share_value import activity_kind
    if activity_kind(title):
        return 'business'
    if row.get('material_ai') or re.search(r'\b(?:artificial intelligence|openai|anthropic|deepmind|claude|chatgpt|gemini|AI|LLMs?|GPT|Copilot|machine learning|generative|agentic)\b', title, re.I):
        return 'ai'
    if re.search(r'\bMCP\b', title, re.I) and re.search(r'\b(?:stocks?|shares?) (?:price|rises?|falls?|gains?|drops?|surges?|rallies?)\b', title, re.I):
        return None  # A ticker reaction is not an MCP connection update.
    capability = integration_topic(title)
    if capability:
        return capability
    if re.search(r'\b(?:study|research|paper|report finds|researchers)\b', title, re.I):
        return 'research'
    if innovation_candidate(title):
        return 'innovation'
    if re.search(r'\b(?:partnership|partners with|collaborat\w*|acquir\w*|acquisition|merger|launch\w*|expands?|investment)\b', title, re.I):
        return 'business'
    # Concrete story hooks from existing feeds, not a blanket catch-all for hype.
    if re.search(
        r'\b(?:bitcoin pizza|pizza day|solo miner|lottery miner|lost (?:bitcoin |crypto )?wallet|'
        r'dormant (?:bitcoin |crypto )?wallet|accidental(?:ly)?|mistaken(?:ly)?|'
        r'world record|guinness|meme culture|crypto wedding|bitcoin wedding|'
        r'(?:museum|game|gaming|video game|artist|community|animal|pet)\w* .{0,65}(?:unexpected|unusual|surprising|experiment|record|discovery)|'
        r'(?:robot|humanoid)\w* .{0,65}(?:dance|dances|cook|cooks|play|plays|learn|learns|paint|paints)|'
        r'(?:weird|surprising|unexpected) .{0,65}(?:experiment|invention|discovery|technology)|'
        r'(?:buys?|bought|pays?|paid) .{0,65} (?:with|using|in) (?:bitcoin|crypto|btc)|'
        r'(?:cz|changpeng zhao|vitalik buterin|elon musk) (?:says?|said|reveals?|responds?|jokes?|shares?))\b',
        title, re.I):
        return 'interesting'
    return 'research' if row.get('material_research') else None


def exchange_access_notice(title):
    """Service-access changes are private research leads, never signup advice."""
    exchange = r'\b(?:Binance|Bitget|Bitfinex|Bybit|OKX|Coinbase|Kraken|crypto exchanges?)\b'
    access = r'\b(?:registrations?|sign.?ups?|onboarding|verification|KYC|services?|accounts?|withdrawals?)\b'
    change = r'\b(?:restrict\w*|unavailable|suspend\w*|halt\w*|stop\w*|resume\w*|eligibility|no longer|not available|clos(?:e|es|ing)|pull crypto)\b'
    return bool(re.search(exchange, title, re.I) and re.search(access, title, re.I) and re.search(change, title, re.I))





def mcp_incident(row):
    """Private tech-source candidates only; public asset-safety routing is unchanged."""
    from news_editorial import INCIDENT, ACTION, EXPLAINER, retrospective, commentary_only, current_safety_evidence
    title = str(row.get('title', ''))
    context = re.search(r'\b(?:MCP|Model Context Protocol)\b', title, re.I)
    if not context or retrospective(row) or commentary_only(row):
        return False
    if re.search(EXPLAINER, title, re.I) and not current_safety_evidence(row):
        return False
    body = title + ' ' + str(row.get('summary', ''))
    return bool(re.search(INCIDENT, title, re.I) and re.search(ACTION, body, re.I))


def integration_topic(title):
    """A concrete new connection/workflow, not a keyword-only MCP mention."""
    if re.search(r'\b(?:stocks?|shares?|price prediction)\b', title, re.I):
        return None
    action = r'\b(?:support\w*|connect\w*|integrat\w*|adds?|enable\w*|introduc\w*|launch\w*|releas\w*|rolls? out|now available|now works|compatible)\b'
    if not re.search(action, title, re.I):
        return None
    protocol = re.search(r'\bModel Context Protocol\b', title, re.I)
    mcp = re.search(r'\bMCP\b', title, re.I)
    context = re.search(r'\b(?:servers?|clients?|support\w*|connect\w*|integrat\w*|compatible)\b', title, re.I)
    if protocol or (mcp and context):
        return 'ai'
    product = re.search(r'\b(?:tools?|apps?|platforms?|editors?|browsers?|services?|software|SDKs?|APIs?)\b', title, re.I)
    capability = re.search(r'\b(?:connectors?|plugins?|plug-ins?|extensions?|automation|automated workflows?|integrat\w*|connect\w*|interoperability)\b', title, re.I)
    return 'innovation' if product and capability else None


def innovation_candidate(title):
    """Concrete developments from the approved tech feed, without a finance gate."""
    subject = r'\b(?:robots?|humanoids?|flying cars?|eVTOLs?|air taxis?|drones?|wearables?|batter(?:y|ies)|chips?|quantum computers?|telescopes?|satellites?|fusion reactors?|solar cells?|smart glasses|3D print\w*|inventions?|prototypes?|open-source (?:apps?|tools?|systems?)|new (?:apps?|tools?|systems?|devices?))\b'
    development = r'\b(?:unveil\w*|introduc\w*|reveal\w*|announc\w*|debut\w*|launch\w*|releas\w*|demonstrat\w*|invent\w*|develop\w*|test\w*|prototype\w*|builds?|built|can|first flight)\b'
    # A named tech company alone or a share-price move is not a new invention.
    if re.search(r'\b(?:stock|shares?) (?:price|rises?|falls?|gains?|drops?|surges?|rallies?)\b', title, re.I):
        return False
    return bool(re.search(subject, title, re.I) and re.search(development, title, re.I))


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
    # Reclassify only this unsent rendering, without reopening delivered history.
    row = dict(row)
    selected = topic(row)
    from material_editorial import editorial_angle
    if selected and row.get('material_topic') == 'ai' and editorial_angle(str(row.get('title', '')), str(row.get('summary', ''))):
        row['material_topic'] = selected
    label, why, formats, checks = ANGLES[row['material_topic']]
    from material_editorial import editorial_angle
    angle = editorial_angle(str(row.get('title', '')), str(row.get('summary', '')))
    if angle == 'people':
        why = '這則是企業高層人事異動，可整理原任職與新職責、已公布時程，不當成新工具發布。'
        formats = '限動列已確認異動；輪播做原公司／新公司及職位對照。'
        checks = '核對原公司、新公司、姓名、職位、宣布與到任時間；未公布的離職動機、策略影響及股價方向不自行推測。'
    elif angle == 'startup':
        label = '企業／創業應用'
        why = '聚焦創業者的營運做法、工作分工或資金進展，依原文細節評估能否做成實例。'
        formats = '輪播拆解工作分工；Reels用原文案例說明做法與限制。'
        checks = '核對公司／創業者、資料期間、樣本、實際工作、成本及收入證據；成立數、融資額不等於獲利。'
    elif angle == 'politics':
        label = '政治／公共治理'
        why = '人物的政策立場與公開行為可作事實對照，重點是時間與規則階段，而非以AI字眼當新工具。'
        formats = '輪播對照已揭露事實與政策時程；限動標清來源及仍待查證項目。'
        checks = '核對人物身分、揭露文件與時間、提案／表決／生效階段；持股不直接代表違法或內線交易。'
    elif angle == 'recruiting':
        why = '這則聚焦AI在招募流程的應用與收費討論，可拆解改變了哪個工作環節，而不是泛稱AI更新。'
        formats = 'Reels圖解篩選流程；輪播區分效率、服務費及業者觀點。'
        checks = '核對測試或受訪對象、候選人篩選環節、費用口徑、資料權限及適用範圍；不把個別經驗當成整體就業結論。'
    elif angle == 'market':
        why = '這則是市場價格與風險討論，可拆解股價表現、融資壓力及來源觀點，不當成新工具發布。'
        formats = '輪播對照行情、背景與證據；Reels解釋市場疑問，不把反彈當作風險解除。'
        checks = '核對報價時間、統計期間與消息歸屬；泡沫疑問或受訪者判斷不是已證實結論。'
    elif angle in ('research_review', 'security_review'):
        why = '這則討論研究發現或專家觀點，適合拆解證據、方法與反例，不當成新功能上線。'
        formats = '輪播區分原研究、受訪者說法及尚待驗證的部分。'
        checks = '回查原報告、研究方法與受訪上下文；不把評論、研究警訊當成已發生的新攻擊。'
    elif angle == 'usage_review':
        why = '這則是生活使用經驗，適合以成功與出錯的對照帶出工具的能力邊界。'
        formats = '限動提問；Reels比較同一工具的成功與失敗案例，明示為來源作者經驗。'
        checks = '核對原作者測試條件與產品版本；個案經驗不等於所有人都會得到相同結果。'
    from material_share_value import assess, value_copy, activity_kind
    value_result = assess(row)
    if value_result['eligible']:
        why = value_copy(value_result)
    if activity_kind(str(row.get('title',''))):
        label = '活動／產品條件'
        formats = '輪播拆解產品、資格、時程與資金限制；限動附原始公告及截止時間。'
        checks = '核對實際產品是Launchpool、IPO認購或代幣化權益，不能混稱；確認發行方、標的關係、地區／資格、費用、資金限制與風險，不承諾配發或收益。'
    if exchange_access_notice(str(row.get('title', ''))):
        why = '交易所註冊、驗證或服務資格變動，會影響讀者能否使用服務，適合整理適用對象與生效階段。'
        checks += '\n核對交易所原始公告、更新日期、國籍／居住地條件、新戶／既有帳戶、產品及生效範圍；截圖與推薦連結只作線索，不寫成全面禁用，也不建議搶註冊、虛報資格或規避限制。'
    if row['material_topic'] in ('ai', 'innovation') and integration_topic(str(row.get('title', ''))):
        why = '報導涉及既有工具新增串接或自動化能力，可用更新前後的具體任務比較，說明多做了什麼、誰用得到。'
        formats = '限動說明新增能力；Reels對照原流程與串接流程；輪播整理用途、適用對象與使用條件。'
        checks += '\n核對串接是否已開放、官方或第三方提供、適用版本、費用、讀寫權限與地區；範例流程不等於已實測，MCP支援不等於所有功能都可操作。'
    from notification_quality import checked_translation, chinese_points, published_time
    title = clean(row.get('title_zh', ''), 180)
    try:
        title = checked_translation(row['title'], title)
    except ValueError:
        title = f'{label}候選｜原文標題待中文核對'
    points = chinese_points(row)
    facts = '\n'.join('• '+clean(p, 190) for p in points[:2]) if points else clean(row.get('summary') or row['title'], 430)
    from material_editorial import review
    editorial = review(row, now, focus=title if '原文標題待中文核對' not in title else row['title'])
    status = ('官方自行公布；效能、適用範圍與發布階段仍須讀原文核對。' if row['material_topic'] == 'ai' and row.get('official') else
              '官方來源候選；列示內容仍須核對範圍與實施階段。' if row.get('official') else
              '媒體報導候選；尚未以直接官方資料完成獨立核實。')
    fields = [
        {'name': '📌 來源內容'+('（中文未完整核對，保留原文片段）' if not points else ''), 'value': facts or '請開啟原文核對。', 'inline': False},
        {'name': '💡 為什麼值得做', 'value': why+'\n\n**本則初評理由**　'+editorial['reason'], 'inline': False},
        {'name': '🧩 初步內容構思', 'value': editorial['concept'], 'inline': False},
        {'name': '🎬 建議形式', 'value': formats, 'inline': False},
        {'name': '🔎 查證狀態／製作前要補', 'value': status+'\n\n'+checks, 'inline': False},
    ]
    refs = [{'source': row.get('source', '來源'), 'url': row['url']}, *row.get('related_sources', [])]
    refs = [r for r in refs if public_url(r.get('url'))][:3]
    links = '\n'.join(f'[{clean(r["source"], 60)}]({r["url"]})' for r in refs)
    fields.append({'name': '🔗 來源與時間', 'value': links+f'\n原文：{published_time(row["published"]).astimezone(TZ):%Y/%m/%d %H:%M}\n收錄：{now.astimezone(TZ):%Y/%m/%d %H:%M}（台灣）', 'inline': False})
    result = {'title': '📝 素材候選｜'+title, 'description': f'分類：{label}\n\n**製作優先度　{editorial["display"]} {editorial["stars"]}/5｜{editorial["label"]}**\n{editorial["basis"]}\n\n【僅管理員】選題建議，不代表事實已全部核實或已製作發布。\n\n原文標題：'+clean(row['title'], 210),
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
            parsed = parse_source_feed(fetch(url, attempts=1), name, host)
            if not parsed:
                raise ValueError('empty official AI feed')
            if name in NEW_SOURCE_NAMES:
                source_starts = box.setdefault('source_started_at', {})
                if not isinstance(source_starts, dict):
                    raise ValueError('material source ledger invalid')
                source_start = source_starts.setdefault(name, now.isoformat())
                parsed = [r for r in parsed if r['published'] >= published_time(source_start)]
            combined.extend(parsed)
            statuses.append({'source': name, 'readable': True, 'parsed': len(parsed)})
        except Exception as exc:
            statuses.append({'source': name, 'readable': False, 'reason': type(exc).__name__})
    box['source_status'] = statuses
    box['items'] = [r for r in box['items'] if published_time(r['published']) >= now-timedelta(days=30)]
    decisions = []
    from material_quality import selection, hint, card_issues, VERSION
    for raw in combined:
        evidence = {'key': key(raw), 'source': raw.get('source', ''), 'recall_hint': hint(raw)}
        decisions.append(evidence)
        try:
            date = published_time(raw['published'])
            if date.tzinfo is None:
                evidence['decision'] = 'invalid_source'
                continue
        except (KeyError, ValueError, TypeError):
            evidence['decision'] = 'invalid_source'
            continue
        selected = topic(raw)
        if date < max(started, now-timedelta(hours=24)) or date > now+timedelta(minutes=5):
            evidence['decision'] = 'outside_window'
            continue
        if not public_url(raw.get('url')):
            evidence['decision'] = 'invalid_source'
            continue
        if not selected:
            evidence['decision'] = 'no_topic'
            continue
        evidence['decision'] = 'accepted'

        old = next((r for r in box['items'] if equivalent(raw, r)), None)
        if old:
            evidence['key'] = old.get('material_key', key(old))
            if old.get('status') in ('queued', 'quality_hold') and old.get('url') == raw.get('url') and old.get('title') == raw.get('title'):
                if raw.get('summary'):
                    old['summary'] = raw['summary']
            refs = old.setdefault('related_sources', [])
            if raw['url'] != old['url'] and all(r['url'] != raw['url'] for r in refs) and len(refs) < 2:
                refs.append({'source': raw.get('source', '來源'), 'url': raw['url']})
            continue
        row = {k: raw.get(k) for k in ('id', 'title', 'summary', 'url', 'source', 'official', 'title_zh', 'summary_zh_points', 'event_context') if raw.get(k) is not None}
        row.update(published=date.isoformat(), material_key=key(raw), material_topic=selected, status='queued', collected_at=now.isoformat())
        box['items'].append(row)
    # Re-evaluate only unsent candidates; never reopen delivered/unknown items.
    for item in box['items']:
        if item.get('status') in ('queued', 'quality_hold'):
            selected = topic(item)
            if selected:
                item['material_topic'] = selected
            reason = selection(item, now) if selected else 'no_longer_relevant'
            item['status'] = 'quality_hold' if reason else 'queued'
            item['quality_hold_reason'] = reason
    by_key = {r.get('material_key'):r for r in box['items']}
    for evidence in decisions:
        item = by_key.get(evidence['key'])
        if evidence['decision']=='accepted' and item and item.get('status')=='quality_hold':
            evidence.update(decision='quality_hold', reason=item.get('quality_hold_reason'))
    box['selection_audit'] = {'version': VERSION, 'started_at': now.isoformat(), 'decisions': decisions}
    box['items'] = box['items'][-500:]
    persist()  # Outbox is durable before a send can fail.
    waiting = [r for r in box['items'] if r.get('status') == 'queued' and published_time(r['published']) >= now-timedelta(hours=24)]
    waiting.sort(key=lambda r: (urgent(r), r['published']), reverse=True)
    print(json.dumps({'material_diagnostics': {
        'eligible_queued': len(waiting),
        'quality_held': sum(r.get('status') == 'quality_hold' for r in box['items']),
        'raw_candidates': len(decisions),
        'delivery_unknown': sum(r.get('status') == 'delivery_unknown' for r in box['items']),
        'notified_retained': sum(r.get('status') == 'notified' for r in box['items']),
        'sources': statuses}}, ensure_ascii=True))
    if not waiting:
        box['selection_audit']['completed_at'] = now.isoformat()
        persist()
        return 0
    verify(webhook)
    count = 0
    for row in waiting:
        if count >= 2:
            break  # Batch only; no daily quota. Remaining candidates wait for the next scan.
        if enrich:
            # Reuse the existing checked free provider; no generated facts or new paid API.
            try:
                from notification_quality import checked_translation
                row['title_zh'] = checked_translation(row['title'], enrich(row['title']))
                if row.get('summary') and not row.get('summary_zh_points'):
                    summary = clean(row['summary'], 430)
                    row['summary_check_source'] = summary
                    row['summary_zh_points'] = [checked_translation(summary, enrich(summary))]
            except Exception:
                pass
        try:
            rendered = card(row, now)
            row['render_audit'] = {'checked_at': now.isoformat(), 'issues': card_issues(row, rendered), 'curation_version': VERSION}
            blockers = set(row['render_audit']['issues']) - {'translation_pending'}
            if blockers:
                row['status'], row['quality_hold_reason'] = 'quality_hold', 'render_quality'
                persist()
                continue
            message_id = send(webhook, rendered, 'WV素材整理｜私人選題')
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
    box['selection_audit']['completed_at'] = now.isoformat()
    box['selection_audit']['sent'] = count
    persist()
    return count
