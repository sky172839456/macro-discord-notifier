"""Third one-time correction: "strike" mistranslated as 罷工 on 13 old crypto cards; never send, delete or touch state.

2026-11-26 本人說「罷工誤譯也一起修」。7～10 月幣圈又有事 13 張卡把 strike 寫成「罷工」：
對伊朗等的軍事打擊（11 張）、選擇權履約價（1 張）、Strike 這家公司（1 張）。英文原文都已在卡上或連結核對。
每張卡只換列出的原句（必須剛好出現一次），改到的 embed 頁尾加更正註記；其他 embed、欄位、時間都不動。
先審計（apply=false）算計畫雜湊，核過同一個雜湊才寫。做法同 news_copy_corrections_20261126(b).py。
"""
import copy
import hashlib
import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

GUILD = '1524947809499877486'
CHANNEL = '1524973208745279660'
ENV = 'DISCORD_CRYPTO_NEWS_WEBHOOK_URL'
MARK = 'WV更正20261126'
NOTE = '｜' + MARK + '：strike 誤譯已更正（非罷工），原來源與時點保留'

# message id -> expected embed count, and (embed index, source link in that embed, old text, new text)
TARGETS = {
    '1559245453252628512': (1, (
        (0, 'bitcoin-drops-22-as-ukraine-iran-strikes-send-oil-toward-one-month-high',
         'Bitcoin 下跌 2.2 ％ ，因為烏克蘭，伊朗罷工將石油推向一個月高點',
         'Bitcoin 下跌 2.2 ％ ，因為烏克蘭、伊朗相關的軍事打擊將油價推向一個月高點'),)),
    '1558075245024251935': (1, (
        (0, 'bitcoin-steadies-near-usd82-500-after-trump-rules-out-iran-strike-before-midterms',
         '特朗普排除伊朗罷工後，Bitcoin 穩定在 82,500 $附近',
         '川普排除在期中選舉前對伊朗發動軍事打擊後，Bitcoin 穩定在 82,500 $附近'),
        (0, 'bitcoin-steadies-near-usd82-500-after-trump-rules-out-iran-strike-before-midterms',
         '• 特朗普排除伊朗罷工後，Bitcoin 恢復到約 82,500 $ ，但本週仍下跌約 4% ，而 Ethereum 下跌 9%。',
         '• 川普排除對伊朗發動軍事打擊後，Bitcoin 回升到約 82,500 $ ，但本週仍下跌約 4% ，而 Ethereum 下跌 9%。'),)),
    '1557959473555963925': (1, (
        (0, 'bitcoin-rebounds-to-usd82-000-as-trump-rules-out-iran-strikes',
         'Bitcoin 反彈至 82,000 $ ，因為特朗普排除伊朗罷工，油價下跌',
         'Bitcoin 反彈至 82,000 $ ，因為川普排除對伊朗發動軍事打擊，油價下跌'),
        (0, 'bitcoin-rebounds-to-usd82-000-as-trump-rules-out-iran-strikes',
         '• Bitcoin 反彈至 82,000 $ ，因為特朗普在中期選舉之前排除了伊朗罷工的可能性，而加密安全專家則推翻了“掩體模式”的擔憂。',
         '• Bitcoin 反彈至 82,000 $ ，因為川普在期中選舉之前排除了對伊朗發動軍事打擊的可能性，而加密資安專家則反駁了“掩體模式”的擔憂。'),)),
    '1554127159579123836': (4, (
        (3, 'bitcoin-drops-under-83k-as-liquidity-hunting-keeps-bulls-from-targeting-yearly-open',
         '• 週一，在美國總統唐納德·特朗普(Donald Trump)沒有承諾永久停止對伊朗的罷工之後，Bitcoin 加入了美國股票期貨的下跌行列。',
         '• 週一，在美國總統川普（Donald Trump）沒有承諾永久停止對伊朗的軍事打擊之後，Bitcoin 跟著美國股票期貨下跌。'),)),
    '1554009619033231484': (2, (
        (1, 'bitcoin-and-nasdaq-futures-decline-as-trump-won-t-rule-out-more-iran-strikes',
         'Bitcoin，納斯達克期貨下跌，因為特朗普不會排除更多的伊朗罷工',
         'Bitcoin、那斯達克期貨下跌，因為川普不排除對伊朗發動更多軍事打擊'),)),
    '1552394567482085422': (4, (
        (0, '15-6-billion-bitcoin-options-expire-friday-what-means',
         '• 德裏比特（ Deribit ）的罷工數據顯示，一本書堆滿了呼籲，一個價格水平同時吸引了雙方的對沖壓力。',
         '• Deribit 逐一履約價的數據顯示，訂單簿堆滿買權，且有一個價位同時承受多空雙方的避險壓力。'),)),
    '1544585105664639009': (3, (
        (0, 'solana-ether-xrp-lead-majors-slide-as-iran-strikes-drive-a-broad-risk-selloff',
         '隨著伊朗罷工推動廣泛的風險拋售， Solana、ether、xrp 牽頭大型企業下滑',
         '伊朗相關的軍事打擊引發廣泛的風險拋售，Solana、ether、xrp 領跌主流幣'),)),
    '1544407277610598484': (3, (
        (2, 'live-updates-bitcoin-etfs-resume-buying-as-ether-funds-stretch-streak-to-11-days',
         '即時更新：在新的伊朗罷工中，隨著油價飆升至三個月高點，Bitcoin 暴跌',
         '即時更新：伊朗相關的新一輪軍事打擊讓油價飆升至三個月高點，Bitcoin 暴跌'),)),
    '1543993399177252960': (4, (
        (2, 'u-s-strikes-on-iran-fail-to-stir-bitcoin-on-track-for-best-month-since-november-2024',
         '美國對伊朗的首次罷工導致', '美國對伊朗的首次軍事打擊導致'),)),
    '1531431462471991419': (1, (
        (0, 'bitcoin-price-eyes-66k-as-us-stocks-rise-on-iran-strike-pause',
         '⛓️ **隨著美國股市因伊朗罷工暫停而上漲，Bitcoin 價格關注$ 66K**',
         '⛓️ **伊朗軍事打擊暫停、美股上漲，Bitcoin 價格看向 $ 66K**'),
        (0, 'bitcoin-price-eyes-66k-as-us-stocks-rise-on-iran-strike-pause',
         '在美國-伊朗罷工結束時', '在美國與伊朗的軍事打擊停止時'),)),
    '1531342825273299016': (1, (
        (0, 'crypto-steadies-as-iran-u-s-pause-sends-oil-tumbling-lifts-risk-assets',
         '在美國和伊朗暫停霍爾木茲海峽罷工後', '在美國和伊朗暫停霍爾木茲海峽一帶的軍事打擊後'),)),
    '1529211599108444211': (1, (
        (0, 'bitcoin-nears-seven-week-high-as-stocks-ignore-iran-strikes-trump-10-tariff-plans',
         '⛓️ **由於股市忽視伊朗罷工，Bitcoin 接近七週高點，特朗普 10 ％的關稅計劃**',
         '⛓️ **股市無視伊朗相關軍事打擊與川普 10 ％關稅計畫，Bitcoin 接近七週高點**'),)),
    '1529132218037960756': (1, (
        (0, 'tether-twenty-one-strike-merger-plan-scrapped-bloomberg',
         '### Tether 支持的 Twenty One ，罷工合併計劃被取消：彭博社',
         '### Tether 支持的 Twenty One 與 Strike 合併計畫取消：彭博社'),)),
}


def editable(embeds):
    keys = ('title', 'description', 'url', 'color', 'fields', 'footer', 'author', 'timestamp', 'image', 'thumbnail')
    return [{k: copy.deepcopy(e[k]) for k in keys if k in e} for e in embeds]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def checked_request(base, method, suffix='', body=None, opener=urlopen, sleeper=time.sleep):
    if method not in ('GET', 'PATCH') or (method == 'PATCH' and suffix.split('/')[-1] not in TARGETS):
        raise ValueError('Only original target reads/patches are allowed')
    req = Request(base + suffix, method=method, data=json.dumps(body).encode() if body is not None else None,
                  headers={'Content-Type': 'application/json', 'User-Agent': 'WV-checked-copy-correction/1.0'})
    for attempt in range(4):
        try:
            with opener(req, timeout=20) as response:
                result = json.load(response)
                if response.headers.get('X-RateLimit-Remaining') == '0':
                    delay = float(response.headers.get('X-RateLimit-Reset-After', '0'))
                    if not 0 <= delay <= 30:
                        raise ValueError('Rate-limit wait exceeds maintenance bound')
                    sleeper(delay + 0.1)
                return result
        except HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            data = json.load(exc)
            delay = float(exc.headers.get('Retry-After') or data.get('retry_after', 0))
            if not 0 < delay <= 30:
                raise ValueError('Rate-limit wait exceeds maintenance bound') from None
            sleeper(delay + 0.1)


def corrected(message):
    mid = message.get('id')
    target = TARGETS.get(mid)
    embeds = message.get('embeds') or []
    if not target or message.get('channel_id') != CHANNEL or len(embeds) != target[0]:
        raise ValueError('Unexpected message target or layout')
    cards = editable(embeds)
    changed = sorted({index for index, *_ in target[1]})
    for index, link, _, _ in target[1]:
        if link not in json.dumps(cards[index], ensure_ascii=False):
            raise ValueError('Checked source link missing')
    marked = [MARK in cards[i].get('footer', {}).get('text', '') for i in changed]
    if any(marked):
        if not all(marked) or any(old in cards[i].get('description', '') for i, _, old, _ in target[1]) \
                or not all(new in cards[i].get('description', '') for i, _, _, new in target[1]):
            raise ValueError('Marked card differs from the checked correction')
        return cards
    for index, _, old, new in target[1]:
        text = cards[index].get('description', '')
        if text.count(old) != 1:
            raise ValueError('Checked original text not found exactly once; no write')
        cards[index]['description'] = text.replace(old, new)
    for index in changed:
        footer = cards[index].setdefault('footer', {})
        footer['text'] = footer.get('text', '') + NOTE
    if any('罷工' in card.get('description', '') for card in cards):
        raise ValueError('A 罷工 mistranslation would remain; no write')
    return cards


def main():
    base = os.environ[ENV].rstrip('/')
    if not re.fullmatch(r'https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[\w.-]+', base):
        raise ValueError('Unexpected configured webhook endpoint')
    meta = checked_request(base, 'GET')
    if meta.get('channel_id') != CHANNEL or meta.get('guild_id') != GUILD:
        raise ValueError('Configured webhook has wrong destination')
    plans = []
    for mid in TARGETS:
        old = checked_request(base, 'GET', '/messages/' + mid)
        if old.get('webhook_id') != meta['id'] or old.get('author', {}).get('id') != meta['id']:
            raise ValueError('Message belongs to another sender')
        before, after = editable(old['embeds']), corrected(old)
        plans.append({'id': mid, 'before': digest(before), 'after': digest(after), 'cards': after})
    plan_hash = digest([{k: v for k, v in p.items() if k != 'cards'} for p in plans])
    if os.getenv('APPLY_CHECKED_COPY') == 'true':
        if os.getenv('EXPECTED_COPY_PLAN_HASH') != plan_hash:
            raise ValueError('Reviewed plan hash does not match live messages')
        for p in plans:
            if p['before'] != p['after']:
                checked_request(base, 'PATCH', '/messages/' + p['id'], {'embeds': p['cards'], 'allowed_mentions': {'parse': []}})
                if digest(editable(checked_request(base, 'GET', '/messages/' + p['id'])['embeds'])) != p['after']:
                    raise ValueError('Message readback differs')
    print(json.dumps({'plan_hash': plan_hash, 'applied': os.getenv('APPLY_CHECKED_COPY') == 'true',
                      'messages': [{k: v for k, v in p.items() if k != 'cards'} for p in plans],
                      'new_messages': 0, 'deleted_messages': 0, 'state_access': False}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__, 'status': getattr(exc, 'code', None)}))
        raise SystemExit(1)
