"""One completion notice per asset/trade date, only for a previously sent brief."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import math

NY = ZoneInfo('America/New_York')
TZ = ZoneInfo('Asia/Taipei')


def day(value):
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def ready(row):
    v = row.get('net_flow_musd')
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and row.get('component_count', 0) > 0
            and row.get('unreported_components') == 0 and not row.get('source_issue'))


def capture(data, now):
    result = {}
    for key, symbol in (('etf', 'BTC'), ('eth_etf', 'ETH')):
        row = data.get(key) or {}
        d = day(row.get('date'))
        # Carry only the current source row; previous_complete is display-only.
        if d and 0 <= (now.astimezone(NY).date()-d).days <= 4:
            result[symbol] = {'date': d.isoformat(), 'pending': not ready(row)}
        elif not d:
            result[symbol] = {'date': None, 'pending': True}
    return result


def remember(state, snapshot, now):
    pending = state.setdefault('etf_pending', {})
    done = state.setdefault('etf_completed', {})
    for symbol, row in snapshot.get('etf_status', {}).items():
        key = symbol+':'+(row['date'] or 'unavailable:'+now.date().isoformat())
        if not row['pending']:
            done[key] = now.isoformat()
            pending.pop(key, None)  # Today's brief already contains the complete value.
            for old,task in list(pending.items()):
                if task['symbol']==symbol and task['date'] is None:
                    pending.pop(old,None)
        elif key not in done and key not in pending:
            pending[key] = {'symbol': symbol, 'date': row['date'], 'created': now.isoformat()}
    prune(state, now)


def prune(state, now):
    for name in ('etf_pending', 'etf_completed'):
        rows = state.setdefault(name, {})
        for key, row in list(rows.items()):
            stamp = row.get('created') if isinstance(row, dict) else row
            try:
                age = now-datetime.fromisoformat(stamp)
            except (ValueError, TypeError):
                age = timedelta(days=99)
            if age > timedelta(hours=36 if name == 'etf_pending' else 10*24) or age < timedelta(0):
                rows.pop(key, None)


def check(state, now, fetch, send, persist):
    prune(state, now)
    pending = state.setdefault('etf_pending', {})
    if not pending:
        return False
    last = state.get('etf_checked_at')
    if last and now-datetime.fromisoformat(last) < timedelta(minutes=15):
        return False
    # No legacy seeding, retrospective sends, or empty-state first-run dispatch.
    state['etf_checked_at'] = now.isoformat()
    selected = []
    selected_dates = set()
    for key, task in list(pending.items()):
        if now-datetime.fromisoformat(task['created']) < timedelta(minutes=15):
            continue
        try:
            row = fetch(task['symbol'])
            d = day(row.get('date'))
            query = datetime.fromisoformat(row.get('retrieved_at', ''))
            if (not ready(row) or not d or (task['date'] is not None and d.isoformat() != task['date'])
                    or query.tzinfo is None or not 0 <= (now-query).total_seconds() <= 900):
                continue
            if not 0 <= (now.astimezone(NY).date()-d).days <= 4:
                continue
            if d > now.astimezone(NY).date() or (d == now.astimezone(NY).date() and now.astimezone(NY).hour < 16):
                continue
            completed_key=task['symbol']+':'+d.isoformat()
            if completed_key in state['etf_completed']:
                pending.pop(key,None)
                continue
            if completed_key not in selected_dates:
                selected.append((key, dict(task,date=d.isoformat()), row))
                selected_dates.add(completed_key)
        except Exception:
            # Failure remains pending, never zero or a recovery assertion.
            continue
    if selected:
        from notification_quality import money_musd
        lines = []
        for _, task, row in selected:
            flow = money_musd(row['net_flow_musd']) if row['net_flow_musd'] else '0美元'
            url = 'https://farside.co.uk/btc/' if task['symbol'] == 'BTC' else 'https://farside.co.uk/eth/'
            lines.append(f"**{task['symbol']} ETF**｜交易日 {task['date']}\n來源目前合計 **{flow}**\n[Farside來源]({url})")
        send({'title': '💸 ETF資金更新｜先前缺列數據已補齊',
              'description': '\n\n'.join(lines)+'\n\n基金欄位已列齊；來源合計仍可能修訂，非即時資金流。',
              'fields': [], 'color': 0x647FB5,
              'footer': {'text': f'查詢：{now.astimezone(TZ):%m/%d %H:%M}（台灣）｜不構成投資建議'},
              'timestamp': now.isoformat()})
        for key, task, row in selected:
            pending.pop(key, None)
            state['etf_completed'][task['symbol']+':'+task['date']] = now.isoformat()
            for old, other in list(pending.items()):
                if other['symbol']==task['symbol'] and other['date'] in {None,task['date']}:
                    pending.pop(old,None)
        persist()
        return True
    persist()
    return False
