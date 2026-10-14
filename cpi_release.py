"""CPI-U release copy with explicit reference period and measurement bases."""
import html
import math
import re
from urllib.parse import urlparse

MONTHS = {name.lower(): i for i, name in enumerate(('January','February','March','April','May','June','July','August','September','October','November','December'), 1)}
MONTH = '|'.join(MONTHS)


def period_from(item, text):
    reference = str(item.get('reference_period') or '')
    match = re.fullmatch(r'(20\d{2})-M?(0[1-9]|1[0-2])', reference)
    if match:
        return f'{match[1]}/{match[2]}'
    match = re.search(r'(?:CONSUMER PRICE INDEX\s*[-–:]?\s*|CPI\s*[-–:]?\s*)('+MONTH+r')\s+(20\d{2})\b', text, re.I)
    if match:
        return f'{match[2]}/{MONTHS[match[1].lower()]:02d}'
    return None


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def change(match):
    if not match:
        return None
    value = float(match.group('value'))
    return -abs(value) if match.group('verb').lower() in {'fell','declined','decreased'} else value


def details(item):
    text = re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', str(item.get('title') or '')+' '+str(item.get('summary') or ''))))
    metrics = dict(item.get('cpi_metrics') or {})
    period = period_from(item, text)
    verb = r'(?P<verb>increased|rose|fell|declined|decreased|changed)\s+(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?:percent|%)'
    if not metrics:
        # Anchors avoid confusing August's previous value with September's annual change.
        monthly = re.search(r'(?:CPI-U\)?|all urban consumers\)?|the index)\s*'+verb, text, re.I)
        annual = re.search(r'(?:over (?:the )?(?:last|past) 12 months[, ]*(?:the )?all items index\s*'+verb+r'|'+verb.replace('verb','verb2').replace('value','value2')+r'(?:\s+before seasonal adjustment)?\s+(?:for|over) (?:the )?(?:last|past) 12 months)', text, re.I)
        metrics['monthly'] = change(monthly)
        if annual:
            if annual.group('value') is not None:
                metrics['annual'] = change(annual)
            else:
                value = float(annual.group('value2'))
                metrics['annual'] = -abs(value) if annual.group('verb2').lower() in {'fell','declined','decreased'} else value
        def clause(match):
            if not match:
                return ''
            tail = re.split(r'(?<=[.!?;])\s+|,\s*(?:and|while|whereas)\b', text[match.end():], maxsplit=1)[0]
            return text[match.start():match.end()] + tail
        monthly_copy = clause(monthly)
        metrics['monthly_seasonally_adjusted'] = (True if re.search(r'(?<!not )(?<!un)seasonally adjusted', monthly_copy, re.I)
                                                 else False if re.search(r'not seasonally adjusted|unadjusted|before seasonal adjustment', monthly_copy, re.I) else None)
        annual_copy = clause(annual)
        metrics['annual_unadjusted'] = (True if re.search(r'before seasonal adjustment|unadjusted|not seasonally adjusted', annual_copy, re.I)
                                       else False if re.search(r'(?<!not )(?<!un)seasonally adjusted', annual_copy, re.I) else None)
    missing, lines = [], []
    for key, label, basis_key, basis in [('monthly','月增率','monthly_seasonally_adjusted','季調'), ('annual','年增率','annual_unadjusted','未季調')]:
        if finite(metrics.get(key)):
            confirmed = isinstance(metrics.get(basis_key), bool)
            actual_basis = basis if metrics.get(basis_key) else ('未季調' if key == 'monthly' else '季調')
            lines.append(f'**{label}（{actual_basis if confirmed else "口徑未確認"}）**　{metrics[key]:.1f}%')
            if not confirmed:
                missing.append(label+'季調口徑')
        else:
            lines.append(f'**{label}**　暫缺')
            missing.append(label)
    if not period:
        missing.append('資料月份')
    lines.insert(0, f'**資料月份**　{period or "未確認"}')
    return '\n'.join(lines), missing


def official_source(item):
    source = str(item.get('url') or '')
    parsed = urlparse(source)
    if parsed.scheme == 'https' and parsed.hostname in {'www.bls.gov','bls.gov','api.bls.gov','data.bls.gov'} and parsed.path.rstrip('/') not in {'','/cpi'}:
        return source
    # A data-specific official link is preferable to an unverified archive URL.
    return 'https://data.bls.gov/timeseries/CUUR0000SA0'
