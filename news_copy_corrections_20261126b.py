"""Second one-time correction of checked news cards; never send, delete or touch state.

2026-11-26 本人：「CertiK那張也一起修一下 還有沒有其它要修的一起修」。
每張卡只做下面列出的修改：標題／內文原句必須剛好出現一次才換，其他欄位、來源與時間都不動；
先審計（apply=false）算計畫雜湊，核過同一個雜湊才寫。做法同 news_copy_corrections_20261126.py。
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
MARK = 'WV更正20261126'
CRYPTO = ('1524973208745279660', 'DISCORD_CRYPTO_NEWS_WEBHOOK_URL')
FINANCE = ('1560822835826532432', 'DISCORD_FINANCE_NEWS_WEBHOOK_URL')
NON_ALERT_COLOR = 0x647FB5

# Each target: channel/env, a source link that must appear in the card, title/description
# replacements (old must appear exactly once), optional new color, and the footer note.
TARGETS = {
    # 🪙｜幣圈又有事：CertiK 在河內辦執法人員培訓（真實舊案例教學），不是新資安事件，不該是重大快訊。
    '1574784124563230731': {
        'where': CRYPTO,
        'link': 'https://decrypt.co/383857/certik-trains-interpol-investigators-to-trace-and-freeze-stolen-crypto',
        'title': ('【重大快訊】 <:wv_risk:1572476054231056485> 快訊｜資安事件｜媒體報導｜CertiK 培訓國際刑警組織調查人員追蹤並凍結被盜加密資產',
                  '【市場新聞】培訓活動｜CertiK 培訓國際刑警組織調查人員追蹤並凍結被盜加密資產'),
        'description': (('• 這家區塊鏈安全公司在河內舉辦的研討會上，向來自亞洲和南太平洋的執法人員講解了一個真實的錢包盜竊案例。',
                         '媒體報導｜這家區塊鏈安全公司在河內舉辦的研討會上，向來自亞洲和南太平洋的執法人員講解了一個真實的錢包盜竊案例。'
                         '這是執法人員培訓活動的報導，並非本次推播時新發生的盜竊或凍結事件。'),),
        'color': NON_ALERT_COLOR,
        'note': '分類已更正（培訓活動，非新資安事件），原來源與時點保留',
    },
    # 🌐｜全球錢線 11/19 第3項：CNBC "half-point rate hike" 是 0.5 個百分點，不是半碼（0.125）。
    '1572945765607669791': {
        'where': FINANCE,
        'link': 'https://www.cnbc.com/2026/11/18/federal-reserve-governor-christopher-waller.html',
        'description': (('**03｜聯準會的華勒表示，央行可能需要透過升息半碼來「震撼人心」**',
                         '**03｜聯準會的華勒表示，央行可能需要透過升息半個百分點來「震撼人心」**'),),
        'note': '升息幅度用詞已更正（半個百分點），原來源與時點保留',
    },
    # 🌐｜全球錢線 11/10 第1項：CNBC "opens door to possible half-point increase"（內文 50 個基點）。
    '1569684238650048595': {
        'where': FINANCE,
        'link': 'https://www.cnbc.com/2026/11/10/fed-governor-waller-sees-december-hike-likely.html',
        'description': (('**01｜聯準會官員沃勒認為十二月可能加息，並為可能的半碼升息開啟大門**',
                         '**01｜聯準會官員沃勒認為十二月可能升息，並為可能的半個百分點升息開啟大門**'),),
        'note': '升息幅度用詞已更正（半個百分點），原來源與時點保留',
    },
    # 🌐｜全球錢線 11/20：第1、2項是 CNBC Peterson 署名分析；第3項 as 是「之際」，不是「作為聯邦交易」，debt 不只債券。
    '1573308213389037619': {
        'where': FINANCE,
        'link': 'https://www.cnbc.com/2026/11/19/trump-nvidia-spacex-palantir-stock-trades-september.html',
        'description': (
            ('**01｜彼得森：輝達的領導層危機考驗了這家晶片製造商作為「AI 中央銀行」的角色**',
             '**01｜分析｜Peterson：輝達的領導層危機考驗了這家晶片製造商作為「AI 中央銀行」的角色**'),
            ('媒體報導｜這家科技巨頭與其他公司的關係網路正增加其可能造成深遠經濟與財務損害的可能性。',
             '分析／專欄｜這家科技巨頭與其他公司的關係網路正增加其可能造成深遠經濟與財務損害的可能性。'),
            ('**02｜彼特森：聯準會主席認為人工智慧革命即將到來。現在他必須弄清楚這代表什麼意思。**',
             '**02｜分析｜Peterson：聯準會主席認為人工智慧革命即將到來。現在他必須弄清楚這代表什麼意思。**'),
            ('媒體報導｜凱文·沃什 (Kevin Warsh) 認為人工智慧正處於轉捩點。',
             '分析／專欄｜凱文·沃什 (Kevin Warsh) 認為人工智慧正處於轉捩點。'),
            ('**03｜特朗普在九月購買了 Nvidia、Palantir、SpaceX 作為聯邦交易，白宮關係增強**',
             '**03｜聯邦合約增加、與白宮關係加深之際，川普在九月買進 Nvidia、Palantir、SpaceX**'),
            ('SpaceX 債券以及', 'SpaceX 債務工具以及'),
        ),
        'note': '分析標示與用詞已更正，原來源與時點保留',
    },
    # 🪙｜幣圈又有事 11/20 第2項：CoinDesk 是 SEC 委員提名人（不是主席），談的是規則制定程序（不是立法）。
    '1573308211870826557': {
        'where': CRYPTO,
        'link': 'https://www.coindesk.com/policy/2026/11/19/trump-s-democratic-sec-pick-suggests-tokenization-policy-deserves-full-rule-process',
        'description': (('**02｜川普提名的民主黨籍 SEC 主席人選認為，代幣化政策應經過完整的立法程序**',
                         '**02｜川普提名的民主黨籍 SEC 委員人選認為，代幣化政策應經過完整的規則制定程序**'),),
        'note': '職稱與用詞已更正（SEC 委員人選、規則制定），原來源與時點保留',
    },
}


def editable(card):
    return {k: copy.deepcopy(card[k]) for k in ('title', 'description', 'url', 'color', 'fields', 'footer', 'author', 'timestamp') if k in card}


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


def footer_note(target):
    return '｜' + MARK + '：' + target['note']


def corrected(message):
    mid = message.get('id')
    target = TARGETS.get(mid)
    if not target or message.get('channel_id') != target['where'][0] or len(message.get('embeds', [])) != 1:
        raise ValueError('Unexpected message target or layout')
    card = editable(message['embeds'][0])
    if target['link'] not in json.dumps(card, ensure_ascii=False):
        raise ValueError('Checked source link missing')
    pairs = [('description', old, new) for old, new in target.get('description', ())]
    if target.get('title'):
        pairs.append(('title', *target['title']))
    if MARK in card.get('footer', {}).get('text', ''):
        if any(old in card.get(key, '') for key, old, _ in pairs) or not all(new in card.get(key, '') for key, _, new in pairs):
            raise ValueError('Marked card differs from the checked correction')
        return card
    for key, old, new in pairs:
        value = card.get(key, '')
        if value.count(old) != 1:
            raise ValueError('Checked original text not found exactly once; no write')
        card[key] = value.replace(old, new)
    if 'color' in target:
        card['color'] = target['color']
    footer = card.setdefault('footer', {})
    footer['text'] = footer.get('text', '') + footer_note(target)
    return card


def main():
    plans, bases = [], {}
    for mid, target in TARGETS.items():
        channel, env = target['where']
        base = os.environ[env].rstrip('/')
        if not re.fullmatch(r'https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[\w.-]+', base):
            raise ValueError('Unexpected configured webhook endpoint')
        meta = checked_request(base, 'GET')
        if meta.get('channel_id') != channel or meta.get('guild_id') != GUILD:
            raise ValueError('Configured webhook has wrong destination')
        old = checked_request(base, 'GET', '/messages/' + mid)
        if old.get('webhook_id') != meta['id'] or old.get('author', {}).get('id') != meta['id']:
            raise ValueError('Message belongs to another sender')
        before, after = editable(old['embeds'][0]), corrected(old)
        bases[mid] = base
        plans.append({'id': mid, 'before': digest(before), 'after': digest(after), 'card': after})
    plan_hash = digest([{k: v for k, v in p.items() if k != 'card'} for p in plans])
    if os.getenv('APPLY_CHECKED_COPY') == 'true':
        if os.getenv('EXPECTED_COPY_PLAN_HASH') != plan_hash:
            raise ValueError('Reviewed plan hash does not match live messages')
        for p in plans:
            if p['before'] != p['after']:
                base = bases[p['id']]
                checked_request(base, 'PATCH', '/messages/' + p['id'], {'embeds': [p['card']], 'allowed_mentions': {'parse': []}})
                if digest(editable(checked_request(base, 'GET', '/messages/' + p['id'])['embeds'][0])) != p['after']:
                    raise ValueError('Message readback differs')
    print(json.dumps({'plan_hash': plan_hash, 'applied': os.getenv('APPLY_CHECKED_COPY') == 'true',
                      'messages': [{k: v for k, v in p.items() if k != 'card'} for p in plans],
                      'new_messages': 0, 'deleted_messages': 0, 'state_access': False}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__, 'status': getattr(exc, 'code', None)}))
        raise SystemExit(1)
