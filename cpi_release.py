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
    match = re.search(r'(?:CONSUMER PRICE INDEX\s*[-–:]?\s*|PRODUCER PRICE INDEX(?:ES)?\s*[-–:]?\s*|[CP]PI\s*[-–:]?\s*)('+MONTH+r')\s+(20\d{2})\b', text, re.I)
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
    metrics = dict(item.get('cpi_metrics') or item.get('price_metrics') or {})
    period = period_from(item, text)
    verb = r'(?P<verb>increased|rose|fell|declined|decreased|changed)\s+(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?:percent|%)'
    monthly_copy = ''
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
    # Only an explicitly named, adjacent month can supply a prose previous value.
    if period and not finite(metrics.get('previous_monthly')):
        prior = re.search(r'after\s+(?:an?\s+)?(?P<verb>rising|increasing|falling|declining|decreasing|rose|fell)\s+(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?:percent|%)\s+in\s+(?P<month>' + MONTH + r' )', monthly_copy, re.I | re.X)
        prior_year, prior_month = previous_period(*map(int, period.split('/')))
        if prior and MONTHS[prior['month'].lower()] == prior_month:
            metrics['previous_monthly'] = float(prior['value']) * (-1 if prior['verb'].lower() in {'falling','declining','decreasing','fell'} else 1)
            metrics['previous_period'] = f'{prior_year}/{prior_month:02d}'
    prior_period = str(metrics.get('previous_period') or '')
    expected_prior = '%04d/%02d' % previous_period(*map(int, period.split('/'))) if period else None
    comparable = bool(expected_prior and prior_period == expected_prior)
    missing, lines = [], []
    for key, label, basis_key, basis in [('monthly','月增率','monthly_seasonally_adjusted','季調'), ('annual','年增率','annual_unadjusted','未季調')]:
        if finite(metrics.get(key)):
            confirmed = isinstance(metrics.get(basis_key), bool)
            actual_basis = basis if metrics.get(basis_key) else ('未季調' if key == 'monthly' else '季調')
            previous = metrics.get('previous_' + key) if comparable else None
            comparison = f'{previous:.1f}%' if finite(previous) else '暫缺'
            from macro_result_display import comparison as block
            line = block(f'{label}（{actual_basis if confirmed else "口徑未確認"}）',
                         metrics[key], previous, comparable=confirmed)
            lines.append(line)
            if not confirmed:
                missing.append(label+'季調口徑')
        else:
            previous = metrics.get('previous_' + key) if comparable else None
            comparison = f'{previous:.1f}%' if finite(previous) else '暫缺'
            lines.append(f'**{label}**\n本次 暫缺｜前值 {comparison}')
            missing.append(label)
    if not period:
        missing.append('資料月份')
    lines.insert(0, f'**資料月份**　{period or "未確認"}' + (f'｜前期 {prior_period}' if comparable else ''))
    return '\n\n'.join(lines), missing


def official_source(item):
    source = str(item.get('url') or '')
    parsed = urlparse(source)
    if parsed.scheme == 'https' and parsed.hostname in {'www.bls.gov','bls.gov','api.bls.gov','data.bls.gov'} and parsed.path.rstrip('/') not in {'','/cpi'}:
        return source
    # A data-specific official link is preferable to an unverified archive URL.
    return 'https://data.bls.gov/timeseries/CUUR0000SA0'


def previous_period(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def index_metrics(monthly_rows, annual_rows, reference):
    """Compare adjacent periods from the same official series/vintage only."""
    year, month = int(reference[:4]), int(reference[-2:])
    if not 1 <= month <= 12:
        return None
    def rows_by_period(rows):
        result = {}
        for row in rows:
            if not re.fullmatch(r'M(?:0[1-9]|1[0-2])', str(row.get('period',''))):
                continue
            try:
                value = float(row['value'])
                period = int(row['year']), int(row['period'][1:])
            except (KeyError, TypeError, ValueError):
                continue  # Official missing-value markers are not numbers or zero.
            if finite(value):
                result[period] = value
        return result
    monthly, annual = rows_by_period(monthly_rows), rows_by_period(annual_rows)
    current = year, month
    prior = previous_period(year, month)
    def rate(rows, end, start):
        a, b = rows.get(end), rows.get(start)
        return (a / b - 1) * 100 if finite(a) and finite(b) and a > 0 and b > 0 else None
    current_monthly = rate(monthly, current, prior)
    if current_monthly is None:
        return None
    return {'monthly': current_monthly,
            'annual': rate(annual, current, (year - 1, month)),
            'previous_monthly': rate(monthly, prior, previous_period(*prior)),
            'previous_annual': rate(annual, prior, (prior[0] - 1, prior[1])),
            'previous_period': '%04d/%02d' % prior,
            'monthly_seasonally_adjusted': True, 'annual_unadjusted': True}
