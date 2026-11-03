"""Live public exchange validation. No Discord, credentials or state access."""
from datetime import datetime, timezone
import json
import sys
import exchange_market_data as exchange
from market_brief_data import get_json
from market_brief_v2 import price_lines, contract_lines


def check():
    now = datetime.now(timezone.utc)
    report, available = [], set()
    for coin in ('BTC', 'ETH'):
        for venue in exchange.SOURCES:
            row = {'coin': coin, 'source': venue}
            try:
                spot = exchange.spot(get_json, coin, venue, now)
                candles = exchange.daily_candles(get_json, coin, venue, now=now)
                contract = exchange.contract(get_json, coin, venue, now)
                week = exchange.settled_week(get_json, coin, contract, now)
                row.update(usable=True, quote=spot['quote_currency'], completed_utc_days=len(candles['candles']),
                           settled_samples=week['samples'], interval_hours=contract['funding_interval_hours'])
                # Check live per-section Discord bounds, not just fixture lengths.
                assert len(price_lines({'crypto': {coin: spot}}, None, now, False)) <= 1024
                assert len(contract_lines({'weekly_derivatives': {coin: week}}, now, True)) <= 1024
                available.add(coin)
            except Exception as exc:
                row.update(usable=False, reason=exchange.reason(exc))
            report.append(row)
    print(json.dumps({'checked_at': now.isoformat(), 'read_only': True, 'sources': report}, ensure_ascii=False))
    return 0 if available == {'BTC', 'ETH'} else 1


if __name__ == '__main__':
    sys.exit(check())
