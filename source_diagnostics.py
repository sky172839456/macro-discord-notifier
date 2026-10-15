"""Public source error labels; never echo request URLs, headers or exception bodies."""
from urllib.error import HTTPError, URLError


def error_label(exc):
    if isinstance(exc, HTTPError):
        return f'HTTP {exc.code}'
    if isinstance(exc, (TimeoutError,)) or (isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)):
        return '連線逾時'
    if isinstance(exc, URLError):
        return '網路連線失敗'
    if getattr(exc, 'public_code', None) is not None:
        return f'官方API回應碼 {exc.public_code}'
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return '官方回應格式或數值未通過核對'
    return type(exc).__name__


def remember(health, key, ok, now, reason=None, **details):
    old = health.get(key, {})
    row = {'ok': ok, 'checked': now.isoformat(), **details}
    if ok:
        row['last_success'] = now.isoformat()
    elif old.get('last_success'):
        row['last_success'] = old['last_success']
    if reason:
        row['reason'] = reason
    health[key] = row
    return row
