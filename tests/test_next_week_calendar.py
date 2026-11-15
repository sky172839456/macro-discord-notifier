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

    def test_chair_own_line_and_other_speeches_merged_per_day(self):
        def speech(iso, title):
            return {'time': datetime.fromisoformat(iso), 'title': title,
                    'rule': {'name': '聯準會重要官員談話', 'key': 'fed_official'}}
        events = [speech('2026-11-16T10:00:00+00:00', 'FOMC Member Barr Speaks'),
                  speech('2026-11-16T14:05:00+00:00', 'FOMC Member Williams Speaks'),
                  speech('2026-11-16T17:00:00+00:00', 'Fed Chairman Warsh Speaks'),
                  speech('2026-11-17T12:30:00+00:00', 'FOMC Member Musalem Speaks'),
                  speech('2026-11-17T14:10:00+00:00', 'Fed Vice Chair Jefferson Speaks'),
                  event('2026-11-17T13:30:00+00:00', '美國零售銷售', 'retail'),
                  speech('2026-11-19T13:50:00+00:00', 'FOMC Member Hammack Speaks')]
        card, _ = nwc.build_card(self.sunday_night, events)
        text = card['description']
        self.assertIn('**11/16（週一）**\n18:00～22:05｜聯準會官員談話 2 場', text)
        self.assertIn('**11/17（週二）**\n01:00｜聯準會主席 Warsh 談話', text)  # 美東 11/16 12:00 = 台灣 11/17 01:00
        self.assertIn('20:30～22:10｜聯準會官員談話 2 場\n21:30｜美國零售銷售', text)  # 副主席不算主席
        self.assertIn('**11/19（週四）**\n21:50｜聯準會官員談話', text)
        self.assertNotIn('聯準會重要官員談話', text)

    def test_enriched_chair_policy_keeps_its_name(self):
        chair = {'time': datetime.fromisoformat('2026-11-18T17:00:00+00:00'),
                 'rule': {'name': '聯準會主席 Warsh｜貨幣政策', 'key': 'fed_chair_policy'}}
        card, _ = nwc.build_card(self.sunday_night, [chair])
        self.assertIn('01:00｜聯準會主席 Warsh｜貨幣政策', card['description'])

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
