"""2026-11-15 本人確認：週日 20:00 下週行事曆＋週報簡化。"""
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

import next_week_calendar as nwc
from market_brief_v2 import build_card as brief_card


def event(iso, name, key='cpi'):
    return {'time': datetime.fromisoformat(iso), 'rule': {'name': name, 'key': key}}


class NextWeekCalendarTests(unittest.TestCase):
    def setUp(self):
        self.sunday_night = datetime(2026, 11, 15, 12, 30, tzinfo=timezone.utc)  # 台灣週日 20:30
        self.sent = []

    def test_only_sunday_after_eight_pm_once_per_week(self):
        saturday = datetime(2026, 11, 14, 12, 30, tzinfo=timezone.utc)
        sunday_noon = datetime(2026, 11, 15, 4, 0, tzinfo=timezone.utc)
        state = {}
        fetch = lambda: ([event('2026-11-17T13:30:00+00:00', '美國零售銷售')], None)
        self.assertFalse(nwc.check(state, saturday, fetch, self.sent.append, lambda: None))
        self.assertFalse(nwc.check(state, sunday_noon, fetch, self.sent.append, lambda: None))
        self.assertTrue(nwc.check(state, self.sunday_night, fetch, self.sent.append, lambda: None))
        self.assertFalse(nwc.check(state, self.sunday_night.replace(minute=45), fetch, self.sent.append, lambda: None))
        self.assertEqual(state['next_week_calendar'], '2026-W47')

    def test_card_groups_by_day_and_skips_other_weeks(self):
        events = [event('2026-11-17T13:30:00+00:00', '美國零售銷售'),
                  event('2026-11-19T13:30:00+00:00', '美國初領失業救濟金人數', 'claims'),
                  event('2026-11-24T13:30:00+00:00', '下下週的數據')]
        card, week = nwc.build_card(self.sunday_night, events)
        self.assertEqual(card['title'], '【下週行事曆】 🗓️ 11/16～11/22')
        self.assertIn('**11/17（週二）**\n21:30｜美國零售銷售', card['description'])
        self.assertIn('11/19（週四）', card['description'])
        self.assertNotIn('下下週', card['description'])
        with mock.patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            from notification_format import apply_delivery_format
            self.assertTrue(apply_delivery_format(card, 'macro_alerts')['title'].startswith('【下週行事曆】'))

    def test_unconfirmed_source_sends_nothing(self):
        state = {}
        self.assertFalse(nwc.check(state, self.sunday_night, lambda: ([], '官方行事曆目前未完成同步'), self.sent.append, lambda: None))
        self.assertNotIn('next_week_calendar', state)
        self.assertEqual(self.sent, [])

    def test_weekly_report_points_to_sunday_calendar(self):
        monday = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
        posted = brief_card('weekly', monday, None, None, [], None, {'next_week_calendar_posted': True})
        normal = brief_card('weekly', monday, None, None, [], None, {})
        posted_field = next(f for f in posted['fields'] if f['name'].startswith('📅'))
        normal_field = next(f for f in normal['fields'] if f['name'].startswith('📅'))
        self.assertIn('週日 20:00', posted_field['value'])
        self.assertNotIn('週日 20:00', normal_field['value'])


if __name__ == '__main__':
    unittest.main()
