"""One-time correction of two checked news cards; never send, delete or touch state.

2026-11-26 本人：「ETF標題和Megaspeed錯名那兩張也修一下」。
- 幣圈又有事 1574757663424909334 第1項：原文 Bitcoin ETFs keep bleeding 是資金流出，卡上寫成 ETF 持續下跌。
- 全球錢線 1574757664569827369 第1項：原文是新加坡的 Megaspeed，卡上多了不相關的「兆芯」。
只換下面列出的原句（每句必須剛好出現一次），其他內容、來源、時間都不動；先審計，核過計畫雜湊才寫。
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
FOOTER_NOTE = '｜' + MARK + '：譯文已更正，原來源與時點保留'
TARGETS = {
    '1574757663424909334': {
        'channel': '1524973208745279660',
        'env': 'DISCORD_CRYPTO_NEWS_WEBHOOK_URL',
        'link': 'https://cointelegraph.com/markets/bitcoin-etfs-bleed-ibit-shares-gain',
        'replace': (
            ('**01｜隨著 BlackRock 的 IBIT 股份上漲近 5%，Bitcoin ETF 持續下跌**',
             '**01｜Bitcoin ETF 資金持續流出，BlackRock 的 IBIT 股價仍漲近 5%**'),
            ('媒體報導｜儘管 Bitcoin ETF 的提款持續，使得十一月的淨流出達到 47.1億美元，BlackRock 的 IBIT 股份在週一仍上漲了 4.85% 。',
             '媒體報導｜儘管 Bitcoin ETF 資金持續撤出、十一月淨流出累計達 47.1億美元，BlackRock 的 IBIT 股價週一仍上漲 4.85%。'),
        ),
    },
    '1574757664569827369': {
        'channel': '1560822835826532432',
        'env': 'DISCORD_FINANCE_NEWS_WEBHOOK_URL',
        'link': 'https://www.cnbc.com/2026/11/24/us-adds-megaspeed-to-trade-blacklist-over-export-control-concerns-.html',
        'replace': (
            ('美國已將兆芯 (Megaspeed) 及其他六家公司列入貿易黑名單',
             '美國已將 Megaspeed 及其他六家公司列入貿易黑名單'),
        ),
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


def corrected(message):
    mid = message.get('id')
    target = TARGETS.get(mid)
    if not target or message.get('channel_id') != target['channel'] or len(message.get('embeds', [])) != 1:
        raise ValueError('Unexpected message target or layout')
    card = editable(message['embeds'][0])
    description = card.get('description', '')
    if target['link'] not in description:
        raise ValueError('Checked source link missing')
    if MARK in card.get('footer', {}).get('text', ''):
        if any(old in description for old, _ in target['replace']) or not all(new in description for _, new in target['replace']):
            raise ValueError('Marked card differs from the checked correction')
        return card
    for old, new in target['replace']:
        if description.count(old) != 1:
            raise ValueError('Checked original sentence not found exactly once; no write')
        description = description.replace(old, new)
    card['description'] = description
    footer = card.setdefault('footer', {})
    footer['text'] = footer.get('text', '') + FOOTER_NOTE
    return card


def main():
    plans = []
    bases = {}
    for mid, target in TARGETS.items():
        base = os.environ[target['env']].rstrip('/')
        if not re.fullmatch(r'https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[\w.-]+', base):
            raise ValueError('Unexpected configured webhook endpoint')
        meta = checked_request(base, 'GET')
        if meta.get('channel_id') != target['channel'] or meta.get('guild_id') != GUILD:
            raise ValueError('Configured webhook has wrong destination')
        old = checked_request(base, 'GET', '/messages/' + mid)
        if old.get('webhook_id') != meta['id'] or old.get('author', {}).get('id') != meta['id']:
            raise ValueError('Message belongs to another sender')
        before = editable(old['embeds'][0])
        after = corrected(old)
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
