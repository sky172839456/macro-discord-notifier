"""Read-only gate for already-initialized production caches; never seed seen state."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

FILES = {
    'macro': 'notified.json', 'news': 'crypto-news.json',
    'risk': 'risk-monitor.json', 'summary': 'market-summaries.json',
    'health': 'realtime-health.json', 'listing': 'exchange-listings.json',
    'announcement': 'exchange-announcements.json', 'derivatives': 'derivatives.json',
    'analysis': 'channel-analysis.json',
}
REQUIRED = {
    'macro': {'sent': dict, 'digests': list},
    'news': {'seen': dict, 'pending': list, 'initialized': bool},
    'risk': {'counts': dict, 'incidents': dict},
    'health': {'last_started_at': str},
}


def check(kind, path, cache_hit):
    # actions/cache reports "false" for a successfully restored prefix match.
    # Missing/failed download leaves this output empty. Never infer a new install.
    if cache_hit not in ('true', 'false'):
        return False, '去重紀錄未確認恢復；暫停此模組，不自動初始化'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return False, '恢復的紀錄缺失、空白或損壞'
    if not isinstance(value, dict) or not value:
        return False, '恢復的紀錄不是完整狀態物件'
    for key, expected in REQUIRED.get(kind, {}).items():
        if key not in value or type(value[key]) is not expected:
            return False, '恢復的紀錄缺少必要欄位或型別錯誤'
    if kind == 'news' and value['initialized'] is not True:
        return False, '新聞基準尚未建立，不能當成既有正式去重紀錄'
    if kind == 'summary' and not any(isinstance(value.get(k), str) and value[k] for k in ('daily', 'weekly')):
        return False, '日週報紀錄缺少既有發送日期'
    if kind == 'macro':
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in value['sent'].items()):
            return False, '總經已送紀錄格式損壞'
        if not all(isinstance(v, str) for v in value['digests']):
            return False, '總經時間表紀錄格式損壞'
    return True, '紀錄已恢復並通過必要欄位檢查'


def inspect(root, statuses):
    return {kind: check(kind, root / name, statuses.get(kind, ''))
            for kind, name in FILES.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', type=Path, default=Path('.state'))
    args = parser.parse_args()
    results = inspect(args.state_dir, {k: os.getenv('RESTORE_' + k.upper(), '') for k in FILES})
    output = os.getenv('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as handle:
            for kind, (ready, _) in results.items():
                handle.write(f'{kind}={str(ready).lower()}\n')
    for kind, (ready, reason) in results.items():
        print(f'{kind}: {"ready" if ready else "blocked"} | {reason}')


if __name__ == '__main__':
    main()
