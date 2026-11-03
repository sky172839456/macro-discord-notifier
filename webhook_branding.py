"""One-time webhook display branding. Never sends or edits messages."""
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from routing_audit import EXPECTED
from sender_identity import sender_name

GUILD = '1524947809499877486'
CHANNEL_KEYS = {
    '1567112861287710741': 'material_inbox',
    '1524973145780654091': 'macro_alerts',
    '1524973428296257616': 'bot_log',
    '1524973451306340494': 'preview',
    '1524973208745279660': 'crypto_news',
    '1560822835826532432': 'finance_news',
    '1526037827115028622': 'daily_market',
}
SECRETS = (
    'DISCORD_MATERIAL_WEBHOOK_URL', 'DISCORD_WEBHOOK_URL', 'DISCORD_LOG_WEBHOOK_URL',
    'DISCORD_TEST_WEBHOOK_URL', 'DISCORD_CRYPTO_NEWS_WEBHOOK_URL',
    'DISCORD_FINANCE_NEWS_WEBHOOK_URL', 'DISCORD_DAILY_SUMMARY_WEBHOOK_URL',
    'DISCORD_WEEKLY_SUMMARY_WEBHOOK_URL', 'DISCORD_BREAKING_NEWS_WEBHOOK_URL',
    'DISCORD_REGULATION_ETF_WEBHOOK_URL', 'DISCORD_MACRO_ANALYSIS_WEBHOOK_URL',
    'DISCORD_TECHNICAL_ANALYSIS_WEBHOOK_URL',
)
ASSET_SHA = '6d1d407bf7bb4b307fd9198b49b6582551118a1235caa3c0cec2c0f965effd23'


def api(webhook, changes=None):
    parsed = urlparse(webhook)
    if parsed.scheme != 'https' or parsed.hostname not in ('discord.com', 'discordapp.com') or not parsed.path.startswith('/api/webhooks/') or parsed.query or parsed.fragment:
        raise ValueError('unapproved webhook URL')
    request = Request(webhook, data=json.dumps(changes).encode() if changes is not None else None,
                      headers={'Content-Type': 'application/json', 'User-Agent': 'WV-display-branding/1.0'},
                      method='PATCH' if changes is not None else 'GET')
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def validate(meta, expected):
    if str(meta.get('guild_id')) != GUILD or str(meta.get('channel_id')) != expected or meta.get('type') != 1 or not str(meta.get('id', '')).isdigit():
        raise ValueError('webhook destination mismatch')


def run(environ=None, *, apply=False, call=api, asset=None):
    environ = os.environ if environ is None else environ
    image = asset if asset is not None else Path(__file__).with_name('assets').joinpath('wv-information-avatar.png').read_bytes()
    if hashlib.sha256(image).hexdigest() != ASSET_SHA:
        raise ValueError('avatar asset changed')
    destinations = {}
    for secret in SECRETS:
        webhook = environ.get(secret)
        if not webhook:
            raise ValueError('required webhook missing')
        expected = EXPECTED[secret]
        meta = call(webhook)
        validate(meta, expected)
        name = sender_name(CHANNEL_KEYS[expected])
        old = destinations.get(meta['id'])
        if old and (old['channel'] != expected or old['name'] != name):
            raise ValueError('duplicate webhook conflict')
        destinations.setdefault(meta['id'], {'webhook': webhook, 'channel': expected, 'name': name, 'before': meta})
    # Validate every destination before any PATCH. No message POST, state or fallback.
    results = []
    for target in destinations.values():
        if apply:
            patched = call(target['webhook'], {'name': target['name'], 'avatar': 'data:image/png;base64,'+base64.b64encode(image).decode()})
            validate(patched, target['channel'])
            after = call(target['webhook'])
            validate(after, target['channel'])
            if after.get('name') != target['name'] or not after.get('avatar') or after['avatar'] != patched.get('avatar'):
                raise ValueError('webhook branding readback mismatch')
        else:
            after = target['before']
        results.append({'channel_id': target['channel'], 'expected_name': target['name'],
                        'name_matches': after.get('name') == target['name'], 'avatar_set': bool(after.get('avatar')),
                        'avatar_hash': after.get('avatar'), 'applied': apply})
    return {'message_sends': 0, 'message_edits': 0, 'state_access': False, 'asset_sha256': ASSET_SHA, 'webhooks': results}


if __name__ == '__main__':
    try:
        print(json.dumps(run(apply=os.getenv('APPLY_WEBHOOK_BRANDING') == 'true'), ensure_ascii=False))
    except Exception as exc:
        # Do not print request URLs, exception bodies or tokens.
        print(json.dumps({'branding_failed': True, 'error_type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)}))
        raise SystemExit(1)
