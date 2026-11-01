import json
import tempfile
import unittest
import os
import shutil
import subprocess
from pathlib import Path

import state_restore_guard as guard


class RestoreGuardTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'notified.json'

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding='utf-8')

    def test_exact_and_prefix_restore_keep_original_bytes(self):
        self.write({'sent': {'release:fixture': '2026-10-29'}, 'digests': ['2026-10-29']})
        before = self.path.read_bytes()
        for hit in ('true', 'false'):
            self.assertTrue(guard.check('macro', self.path, hit)[0])
        self.assertEqual(self.path.read_bytes(), before)

    def test_partial_extraction_is_not_a_confirmed_restore(self):
        self.write({'sent': {}, 'digests': []})
        self.assertFalse(guard.check('macro', self.path, '')[0])

    def test_failure_never_sends_or_reinitializes_or_overwrites(self):
        for data in ('', '{', '{}', '[]', '{"sent": []}', '{"sent": {}, "digests": [1]}'):
            with self.subTest(data=data):
                self.path.write_text(data, encoding='utf-8')
                calls = []
                ready, _ = guard.check('macro', self.path, 'false')
                if ready:
                    calls.append('send')
                    self.path.write_text('OVERWRITTEN')
                self.assertEqual(calls, [])
                self.assertEqual(self.path.read_text(encoding='utf-8'), data)

    def test_missing_state_does_not_silently_bootstrap_production(self):
        self.assertFalse(guard.check('macro', self.path, '')[0])
        self.assertFalse(guard.check('macro', self.path, 'false')[0])
        self.assertFalse(self.path.exists())

    def test_module_isolation(self):
        (self.root / 'risk-monitor.json').write_text('{"counts": {}, "incidents": {}}')
        result = guard.inspect(self.root, {'risk': 'false', 'macro': ''})
        self.assertTrue(result['risk'][0])
        self.assertFalse(result['macro'][0])
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_news_requires_existing_baseline(self):
        for initialized in (False, True):
            self.write({'seen': {}, 'pending': [], 'initialized': initialized})
            self.assertEqual(guard.check('news', self.path, 'false')[0], initialized)

    def test_summary_and_health_require_history(self):
        for kind, good in (('summary', {'daily': '2026-10-30'}),
                           ('health', {'last_started_at': '2026-10-30T22:09:00+00:00'})):
            self.write(good)
            self.assertTrue(guard.check(kind, self.path, 'false')[0])
            self.write({'unrelated': True})
            self.assertFalse(guard.check(kind, self.path, 'false')[0])

    def test_workflow_gates_every_cache_save_and_active_sender(self):
        workflow = Path('.github/workflows/realtime-monitors.yml').read_text(encoding='utf-8')
        self.assertIn('python state_restore_guard.py', workflow)
        for kind in guard.FILES:
            self.assertIn(f'id: restore_{kind}', workflow)
            self.assertIn(f"steps.state_guard.outputs.{kind} == 'true'", workflow)
        for flag in ('MACRO', 'NEWS', 'RISK', 'SUMMARY', 'HEALTH'):
            self.assertIn(f'READY_{flag}:', workflow)
            self.assertIn(f'"$READY_{flag}"', workflow)

    def test_real_workflow_shell_blocks_bad_module_but_runs_healthy_ones(self):
        bash = shutil.which('bash')
        if os.name == 'nt':
            bash = r'C:\Program Files\Git\bin\bash.exe'
        if not bash or not Path(bash).exists():
            self.skipTest('bash not available')
        lines = Path('.github/workflows/realtime-monitors.yml').read_text(encoding='utf-8').splitlines()
        start = lines.index('          failures=0')
        end = next(i for i in range(start, len(lines)) if lines[i].startswith('      - name: Save'))
        script = '\n'.join(line[10:] for line in lines[start:end])
        script = 'python() { echo "$*" >> calls.txt; return 0; };\n' + script
        (self.root / 'run.sh').write_text(script, encoding='utf-8')
        env = dict(os.environ, CONSOLIDATED_CHANNELS='1', READY_MACRO='false',
                   READY_NEWS='true', READY_RISK='true', READY_HEALTH='true',
                   READY_SUMMARY='false', READY_ANALYSIS='false')
        for secret in ('DISCORD_WEBHOOK_URL', 'DISCORD_CRYPTO_NEWS_WEBHOOK_URL',
                       'DISCORD_RISK_WEBHOOK_URL'):
            env[secret] = 'fixture-configured'
        result = subprocess.run([bash, 'run.sh'], cwd=self.root, env=env,
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 1, result.stderr)
        calls = (self.root / 'calls.txt').read_text()
        self.assertNotIn('python notifier.py', calls)
        self.assertNotIn('\nnotifier.py', '\n'+calls)
        self.assertNotIn('summary_notifier.py', calls)
        self.assertIn('crypto_news_notifier.py', calls)
        self.assertIn('risk_notifier.py', calls)
        self.assertIn('realtime_health.py --finish', calls)
        results = (self.root / '.state/realtime-results.txt').read_text(encoding='utf-8')
        self.assertIn('總經數據|failed|', results)
        self.assertIn('市場摘要|failed|', results)


if __name__ == '__main__':
    unittest.main()
