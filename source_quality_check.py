"""Public checks only: no monitor run, Discord delivery, credentials or state changes."""
import json
from datetime import datetime, timezone
import notifier
import risk_notifier as risk
import slim_risk
from source_diagnostics import error_label


def check(now=None):
    now = now or datetime.now(timezone.utc)
    rows = {'checked_at': now.isoformat()}
    try:
        incidents = risk.bybit_incidents()
        rows['bybit'] = {'readable': True, 'incidents': len(incidents), 'meaning': '官方接口成功不等於所有服務正常'}
    except Exception as exc:
        rows['bybit'] = {'readable': False, 'reason': error_label(exc)}
    diagnostics = {}
    prices = slim_risk.price_sources(risk, now, diagnostics)
    rows['stablecoin'] = {'available_sources': {coin: list(values) for coin, values in prices.items()}, 'details': diagnostics}
    try:
        calendar = notifier.parse_bls_calendar(notifier.http_text(notifier.BLS_CALENDAR_URL, attempts=1))
        if not calendar:
            raise ValueError('empty BLS calendar')
        rows['bls_primary'] = {'readable': True, 'tracked_events': len(calendar)}
    except Exception as exc:
        rows['bls_primary'] = {'readable': False, 'reason': error_label(exc)}
    try:
        events, verified = notifier.validated_bls_snapshot(now)
        rows['bls_snapshot'] = {'usable': True, 'verified_at': verified, 'events': len(events), 'live_primary_recovered': False}
    except Exception as exc:
        rows['bls_snapshot'] = {'usable': False, 'reason': error_label(exc)}
    return rows


if __name__ == '__main__':
    print(json.dumps(check(), ensure_ascii=False))
