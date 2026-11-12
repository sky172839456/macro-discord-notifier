"""Daily brief reads lighter; critical flashes stay for real incidents (titles from 2026-11-11)."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from market_brief_v2 import build_card, observations


class DailyBriefSlim(unittest.TestCase):
    now = datetime(2026, 11, 12, 23, tzinfo=timezone.utc)

    def test_caveats_move_to_one_reading_note(self):
        card = build_card('daily', self.now, None, None, [], None, {})
        text = card['description'] + ''.join(f['value'] for f in card['fields'])
        for caveat in ('情緒不等同漲跌預測', '市占是市值占比，並非資金流量。', '近24小時漲跌；查詢快照，非即時報價。',
                       '數量變化不代表多空方向；費率非年化，正值通常由多方付空方。'):
            self.assertNotIn(caveat, text)
        self.assertEqual(text.count('-# 讀法：'), 1)

    def test_daily_drops_trivial_lead_but_keeps_divergence(self):
        same = {'crypto': {'BTC': {'change_24h': 0.46}, 'ETH': {'change_24h': 0.69}}}
        split = {'crypto': {'BTC': {'change_24h': 0.43}, 'ETH': {'change_24h': -0.49}}}
        self.assertEqual(observations(same, False), [])
        self.assertIn('分化', observations(split, False)[0])
        self.assertTrue(any('領先' in r for r in observations({'weekly_crypto': {'BTC': {'change_7d': 1}, 'ETH': {'change_7d': 2}}}, True)))


class CriticalFlash(unittest.TestCase):
    def setUp(self):
        p = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1'})
        p.start(); self.addCleanup(p.stop)

    def test_statistics_report_is_not_a_critical_flash(self):
        import news_auto_recovery as auto
        if not auto.enabled():
            self.skipTest('auto recovery switch differs in this environment')
        report = {'title': 'Bitget Wallet reports seven-fold increase in crypto phishing risk alerts',
                  'summary': 'The wallet saw about 37,000 signing phishing requests per week in Q3.'}
        incident = {'title': 'Bitget Wallet confirms new exploit drains crypto wallets today',
                    'summary': 'A new exploit drains wallets today; users are told to revoke approvals.'}
        self.assertFalse(auto.material_news(report))
        self.assertTrue(auto.material_news(incident))
        # The live card (2026-11-11 18:04) was a flash; the old pattern list let it through.
        import news_editorial
        self.assertEqual(news_editorial.event_kind(report), 'safety')


if __name__ == '__main__':
    unittest.main()
