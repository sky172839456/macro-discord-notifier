"""2026-11-15：FOMC 會議紀要不可被當成 FOMC 公告（利率決議）。"""
import unittest
from datetime import datetime, timezone

import notifier
import slim_policy
import summary_notifier


class FomcMinutesLabelTests(unittest.TestCase):
    def test_public_calendar_minutes_is_not_statement(self):
        rows = [{'country': 'USD', 'title': 'FOMC Meeting Minutes', 'date': '2026-11-18T14:00:00-05:00'},
                {'country': 'USD', 'title': 'FOMC Statement', 'date': '2026-12-09T14:00:00-05:00'},
                {'country': 'USD', 'title': 'FOMC Member Barr Speaks', 'date': '2026-11-18T13:35:00-05:00'}]
        keys = [e['rule']['key'] for e in summary_notifier.parse_fair_economy_calendar(rows)]
        self.assertEqual(keys, ['fomc_minutes', 'fomc', 'fed_official'])

    def test_classify_minutes_titles(self):
        self.assertEqual(notifier.classify('FOMC Meeting Minutes monetary policy statement fomc')['key'], 'fomc_minutes')
        self.assertEqual(notifier.classify('Minutes of the Federal Open Market Committee, October 27-28, 2026')['key'], 'fomc_minutes')
        self.assertEqual(notifier.classify('Federal Reserve issues FOMC statement')['key'], 'fomc')

    def test_minutes_listed_daily_without_expecting_result_card(self):
        rule = next(r for r in notifier.EVENT_RULES if r['key'] == 'fomc_minutes')
        self.assertEqual(rule['name'], '美國聯準會 FOMC 會議紀要')
        self.assertNotIn('fomc_minutes', slim_policy.RESULT_EVENTS)
        when = datetime(2026, 11, 18, 19, 0, tzinfo=timezone.utc)
        cards = slim_policy.calendar_cards([{'time': when, 'rule': rule}], datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc))
        text = cards[0]['description'] if 'description' in cards[0] else str(cards[0])
        self.assertIn('FOMC 會議紀要', text)
        self.assertIn('內容見官方來源', text)
        self.assertNotIn('結果另見正式公告', text)


if __name__ == '__main__':
    unittest.main()
