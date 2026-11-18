"""2026-11-18 本人選 DC 功能細節 #7「時間標籤＋倒數」。

今日行事曆與每日行情「今日關注」在台灣時間後面加 Discord 倒數標籤 <t:秒數:R>，
成員看到「13 小時後」，Discord 會自己更新；過了排定時間的項目不加。
"""
import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import notifier
import slim_policy
from market_brief_v2 import events_lines

NOW = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)  # 台灣 11/19（四）07:00


def event(key, minutes):
    return {'id': f'{key}-{minutes}', 'time': NOW + timedelta(minutes=minutes),
            'rule': next(rule for rule in notifier.EVENT_RULES if rule['key'] == key)}


def tag(minutes):
    return f'<t:{int((NOW + timedelta(minutes=minutes)).timestamp())}:R>'


class DiscordTimestampTests(unittest.TestCase):
    def test_countdown_markup_is_discord_relative_timestamp(self):
        self.assertEqual(slim_policy.countdown(NOW), f'<t:{int(NOW.timestamp())}:R>')
        self.assertRegex(slim_policy.countdown(NOW), r'^<t:\d{10}:R>$')

    def test_today_calendar_keeps_taiwan_time_and_adds_countdown(self):
        cpi = event('cpi', 13 * 60 + 30)  # 台灣 20:30
        card = slim_policy.calendar_cards([cpi], NOW)[0]
        self.assertIn(f'**20:30｜{cpi["rule"]["name"]}**（{tag(13 * 60 + 30)}）\n待公布', card['description'])
        self.assertTrue(card['description'].startswith('台灣時間｜'))

    def test_elapsed_items_have_no_countdown(self):
        later = NOW + timedelta(hours=14)
        card = slim_policy.calendar_cards([event('cpi', 13 * 60 + 30)], later)[0]
        self.assertNotIn('<t:', card['description'])
        self.assertIn('已過排定時間', card['description'])

    def test_daily_focus_adds_countdown_only_for_upcoming(self):
        text = events_lines([event('cpi', 13 * 60 + 30)], NOW, None, False, budget=650)
        self.assertIn(f'**11/19 20:30｜', text)
        self.assertIn(f'**（{tag(13 * 60 + 30)}）\n', text)
        self.assertEqual(text.count('<t:'), 1)

    def test_member_delivery_keeps_the_tag_and_stays_within_limits(self):
        events = [event(key, 60 * (i + 1)) for i, key in enumerate(('cpi', 'jobs', 'pce'))]
        card = slim_policy.calendar_cards(events, NOW)[0]
        with mock.patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            from notification_format import apply_delivery_format
            out = apply_delivery_format(card, 'macro_alerts')
        self.assertEqual(len(re.findall(r'<t:\d{10}:R>', out['description'])), 3)
        self.assertLessEqual(len(out['description']), 4096)


if __name__ == '__main__':
    unittest.main()
