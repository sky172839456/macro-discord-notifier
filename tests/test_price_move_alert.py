"""2026-11-15 本人確認的價格大波動快訊規格。"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import price_move_alert as pm


def quote(price, change, now):
    return {'price': price, 'change_24h': change, 'updated_at': now.timestamp(), 'quote_currency': 'USDT'}


class PriceMoveAlertTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc)  # 台灣 10:00
        self.sent = []

    def run_check(self, state, quotes, now=None, context=None):
        now = now or self.now
        return pm.check(state, now, lambda s: quotes[s], lambda: context or {}, self.sent.append, lambda: None)

    def test_first_run_only_records_baseline(self):
        state = {}
        quotes = {'BTC': quote(63000, -6.5, self.now), 'ETH': quote(1745, -9.0, self.now)}
        self.assertFalse(self.run_check(state, quotes))
        self.assertEqual(self.sent, [])
        self.assertTrue(all(a.get('baseline') for a in state['price_alerts']))
        # 同一天同方向、同級距不補發
        self.assertFalse(self.run_check(state, quotes, self.now + timedelta(minutes=5)))

    def test_five_then_ten_percent_same_day(self):
        state = {'price_alerts': []}
        self.assertTrue(self.run_check(state, {'BTC': quote(63000, -5.2, self.now), 'ETH': quote(1900, -1, self.now)}))
        self.assertIn('BTC 24小時 -5.20%', self.sent[-1]['title'])
        later = self.now + timedelta(hours=2)
        self.assertFalse(self.run_check(state, {'BTC': quote(62000, -7.0, later), 'ETH': quote(1900, -1, later)}, later))
        later2 = self.now + timedelta(hours=4)
        self.assertTrue(self.run_check(state, {'BTC': quote(58000, -10.4, later2), 'ETH': quote(1900, -1, later2)}, later2))
        self.assertEqual(len(self.sent), 2)

    def test_one_hour_move_uses_sample_from_an_hour_ago(self):
        state = {'price_alerts': [], 'price_samples': {'ETH': [[(self.now - timedelta(minutes=60)).isoformat(), 2000.0]]}}
        self.assertTrue(self.run_check(state, {'ETH': quote(1930, -2.0, self.now)}))
        self.assertIn('ETH 1小時 -3.50%', self.sent[-1]['title'])
        # 6 小時內同方向不重發
        soon = self.now + timedelta(minutes=65)
        state['price_samples']['ETH'].append([(soon - timedelta(minutes=60)).isoformat(), 1930.0])
        self.assertFalse(self.run_check(state, {'ETH': quote(1860, -2.5, soon)}, soon))

    def test_daily_cap_of_three(self):
        today = self.now.astimezone(pm.TZ).date().isoformat()
        state = {'price_alerts': [{'at': (self.now - timedelta(hours=h)).isoformat(), 'date': today, 'kind': '1h',
                                   'symbol': 'ETH', 'direction': 'up', 'level': 3.0} for h in (1, 2, 3)]}
        self.assertFalse(self.run_check(state, {'BTC': quote(63000, -5.5, self.now)}))
        self.assertEqual(self.sent, [])

    def test_stale_quote_never_triggers(self):
        state = {'price_alerts': []}
        old = quote(63000, -8, self.now - timedelta(minutes=30))
        self.assertFalse(self.run_check(state, {'BTC': old, 'ETH': old}))

    def test_card_lists_numbers_without_reasons_and_passes_member_format(self):
        state = {'price_alerts': [], 'brief_history': [{'derivatives': {'BTC': {'oi_ccy': 100.0, 'timestamp': '2026-11-14T23:05:00+00:00'}}}]}
        context = {'derivatives': {'BTC': {'oi_ccy': 95.0, 'funding_rate': -0.0009}},
                   'sentiment': {'value': 13, 'classification': 'Extreme Fear'}}
        self.assertTrue(self.run_check(state, {'BTC': quote(63618.51, -6.47, self.now), 'ETH': quote(1745.33, -2.0, self.now)}, context=context))
        card = self.sent[-1]
        text = str(card)
        self.assertIn('63,618.51 USDT', text); self.assertIn('-5.00%', text); self.assertIn('-0.0009%', text)
        self.assertIn('13/100（極度恐懼）', text); self.assertIn('不推論原因', text)
        with mock.patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            from notification_format import apply_delivery_format
            delivered = apply_delivery_format(card, 'daily_market')
        self.assertTrue(delivered['title'].startswith('【價格快訊】'))


if __name__ == '__main__':
    unittest.main()
