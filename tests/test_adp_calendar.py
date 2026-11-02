import unittest
from unittest.mock import patch
import notifier
import summary_notifier


class ADPCalendarTests(unittest.TestCase):
    def items(self):
        return [
            {'country':'USD','title':'ADP Non-Farm Employment Change','date':'2026-11-04T08:15:00-05:00'},
            {'country':'USD','title':'Non-Farm Employment Change','date':'2026-11-06T08:30:00-05:00'},
            {'country':'USD','title':'Unemployment Rate','date':'2026-11-06T08:30:00-05:00'},
        ]

    def test_adp_alias_is_not_official_bls_jobs(self):
        for title in ('ADP Non-Farm Employment Change employment situation',
                      'adp nonfarm payrolls employment situation',
                      'Automatic Data Processing employment situation',
                      'ADP National Employment Report employment situation'):
            with self.subTest(title=title):
                self.assertIsNone(notifier.classify(title))

    def test_summary_calendar_keeps_only_bls_jobs(self):
        events=summary_notifier.parse_fair_economy_calendar(self.items())
        self.assertEqual(len(events),2)
        self.assertTrue(all(e['rule']['key']=='jobs' for e in events))
        self.assertTrue(all(e['time'].day==6 and e['time'].hour==13 and e['time'].minute==30 for e in events))
        self.assertTrue(all(e['rule']['source']=='https://www.bls.gov/news.release/empsit.htm' for e in events))

    def test_daily_calendar_uses_same_guard(self):
        with patch.object(notifier,'PUBLIC_CALENDARS',('https://calendar.invalid',)), \
             patch.object(notifier,'http_json_get',return_value=self.items()):
            events,success=notifier.fetch_public_calendar()
        self.assertTrue(success)
        self.assertEqual(len(events),2)
        self.assertTrue(all(e['time'].day==6 for e in events))

    def test_other_existing_calendar_categories_preserved(self):
        events=summary_notifier.parse_fair_economy_calendar([
            {'country':'USD','title':title,'date':'2026-11-03T10:00:00-05:00'}
            for title in ('CPI m/m','JOLTS Job Openings','FOMC Member Waller Speaks')])
        self.assertEqual([e['rule']['key'] for e in events],['cpi','jolts','fed_official'])


if __name__=='__main__':
    unittest.main()
