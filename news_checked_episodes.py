"""Exact, source-checked episode aliases; never general number/stage tolerance.

Coinbase: three Nov9 reports refer to the Nov6 final OCC charter decision.
Elliptic: three reports quote the same six NEAR-pool laundering analysis.
Gnosis: distinct exposure details stay separate in public news; weekly recap only.
URLs, complete RSS title/summary and original publication must all match. Edits,
new figures, new phases or a newly dated article fall back to the strict rules.
No seen state is reset and no old message is changed.
"""
from hashlib import sha256
import re
from notification_quality import published_time

# Public RSS observations 2026-11-10; fingerprints retain no copied article body.
VERIFIED = {'aa668d1d73a13500c2c67fa6bd995ee1289a2e15a95035194658a20981c258f8': ('elliptic_near_pools_20261109', '2026-11-09T15:00:44+00:00'), '1e159175526bb98856a6d25c5f0a7d27ba2579ac4d27c1c6a6b0f2a83a33030a': ('coinbase_final_trust_20261109', '2026-11-09T10:00:00+00:00'), '2b84214042b20212ee3b1025261eec733ef390ae6617959834d34a6f4a859e19': ('gnosis_customer_data_20261106', '2026-11-07T16:51:00+00:00'), '35cedd8c45cefab5bef5789e754a3a537627e8a423f37e8751c68b089e321a53': ('elliptic_near_pools_20261109', '2026-11-09T20:26:34+00:00'), 'be0e709bf75adcfb7ffc05ff4a80c99271e387657024bb509a285cf0edf269fc': ('coinbase_final_trust_20261109', '2026-11-09T11:38:52+00:00'), 'a99b3d35093571b94c140dd29bda6ab43e88daceb9665a93f83ba794bc2fd105': ('gnosis_customer_data_20261106', '2026-11-06T20:51:23+00:00'), '9384d215b6484d6be184f2096c8a65db6e0aaddae3e12ffa313db1929c72f440': ('elliptic_near_pools_20261109', '2026-11-09T19:36:02+00:00'), '12afae6cc75abaa706197c6b7c87ff251da77f6a90c3a278eb2089689cb119e8': ('coinbase_final_trust_20261109', '2026-11-09T11:50:36+00:00'), '60a006612d3e094a189d66b30f8671aeb730c60a015525a3f5287e42b82f9f64': ('gnosis_customer_data_20261106', '2026-11-06T16:41:29+00:00')}

PUBLIC_GROUPS = {'coinbase_final_trust_20261109', 'elliptic_near_pools_20261109'}


def fingerprint(row):
    from crypto_news_notifier import canonical_url
    def normalized(value):
        return re.sub(r'\s+', ' ', str(value or '').replace('’', "'")).strip().casefold()
    return sha256('\n'.join((canonical_url(str(row.get('url') or '')),
                             normalized(row.get('title')),normalized(row.get('summary')))).encode()).hexdigest()


def episode(row):
    matched = VERIFIED.get(fingerprint(row))
    if not matched:
        return None
    group, publication = matched
    try:
        if published_time(row.get('published')) != published_time(publication):
            return None
    except (ValueError,TypeError,AttributeError):
        return None
    return group


def same_checked_event(left,right):
    group=episode(left)
    return bool(group in PUBLIC_GROUPS and group==episode(right))


def same_recap_episode(left,right):
    group=episode(left)
    return bool(group and group==episode(right))
