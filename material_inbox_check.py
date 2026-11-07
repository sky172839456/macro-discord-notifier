"""Read-only official AI feed diagnostics, no Discord sends or production state."""
import json
import sys
import material_inbox as inbox
from crypto_news_notifier import http_text


def check():
    results = []
    for name, url, host in inbox.MATERIAL_SOURCES:
        try:
            rows = inbox.parse_source_feed(inbox.fetch_feed(url, attempts=1), name, host)
            if not rows:
                raise ValueError('empty official feed')
            results.append({'source': name, 'readable': True, 'parsed_entries': len(rows), 'latest_publication': max(r['published'] for r in rows).isoformat()})
        except Exception as exc:
            results.append({'source': name, 'readable': False, 'reason': type(exc).__name__})
    print(json.dumps({'read_only': True, 'discord_sends': 0, 'production_state_access': False, 'material_sources': results}, ensure_ascii=False))
    return 0 if all(r['readable'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(check())
