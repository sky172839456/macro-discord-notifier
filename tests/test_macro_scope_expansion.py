import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import notifier as n
import slim_policy as policy
from macro_calendar import census_calendar, industrial_calendar, CENSUS_URL, G17_URL
from macro_results import retail_details, ppi_details

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
RETAIL = ('FOR IMMEDIATE RELEASE: Thursday, October 15, 2026 '
          'Advance Monthly Sales for Retail and Food Services '
          'Advance estimates of U.S. retail and food services sales for September 2026, '
          'adjusted for seasonal variation and holiday and trading-day differences, '
          'but not for price changes, were $745.0 billion, up 0.8 percent (±0.4 percent) '
          'from the previous month, and up 6.3 percent (±0.5 percent) from September 2025. '
          'The July 2026 to August 2026 percent change was revised from up 1.1 percent '
          '(±0.4 percent) to up 1.3 percent (±0.1 percent).')


def census(year):
    return f'Advance Monthly Sales for Retail and Food Services October 15, {year} 8:30 AM'


class MacroScopeExpansionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'})
        env.start(); self.addCleanup(env.stop)

    def test_wrong_year_default_uses_target_year_and_exposes_source(self):
        pages = {CENSUS_URL: census(2027), CENSUS_URL.replace('.html', '-2026.html'): census(2026)}
        events, status = census_calendar(NOW, pages.__getitem__, n.html_to_text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['time'].year, 2026)
        self.assertIn('-2026.html', events[0]['rule']['source'])
        self.assertIn('年度頁備援', status)

    def test_year_follows_new_york_not_taipei_midnight(self):
        when = datetime.fromisoformat('2027-01-01T00:30:00+08:00')
        pages = {CENSUS_URL: census(2027), CENSUS_URL.replace('.html', '-2026.html'): census(2026)}
        events, _ = census_calendar(when, pages.__getitem__, n.html_to_text)
        self.assertEqual(events[0]['time'].year, 2026)
        events, _ = census_calendar(datetime.fromisoformat('2027-01-01T12:00:00+00:00'), pages.__getitem__, n.html_to_text)
        self.assertEqual(events[0]['time'].year, 2027)

    def test_empty_wrong_year_and_missing_fallback_fail_instead_of_healthy_zero(self):
        for page in ('no rows', census(2027)):
            with self.subTest(page=page), self.assertRaises(ValueError):
                census_calendar(NOW, lambda _: page, n.html_to_text)

    def test_current_year_is_selected_from_mixed_rows(self):
        events, _ = census_calendar(NOW, lambda _: census(2026) + ' ' + census(2027), n.html_to_text)
        self.assertEqual([e['time'].year for e in events], [2026])

    def test_industrial_annual_revision_is_not_a_monthly_release_and_dst_is_local(self):
        source = ('monthly releases are issued at 9:15 a.m. annual revision is issued at noon. '
                  '2026: October 16 (most recent monthly), November 17, November 24 (annual revision), and December 16. '
                  '2027: January 15. Historical Release Dates')
        events = industrial_calendar(NOW, lambda _: source, n.html_to_text)
        self.assertEqual([e['time'].day for e in events], [16, 17, 16, 15])
        self.assertEqual(events[0]['time'].hour, 13)
        self.assertEqual(events[1]['time'].hour, 14)
        self.assertIn('industrial', policy.CALENDAR_EVENTS)
        self.assertNotIn('industrial', policy.REMINDER_EVENTS)
        self.assertNotIn('industrial', policy.RESULT_EVENTS)

    def test_industrial_missing_year_or_time_fails(self):
        for source in ('2026: October 16.', 'monthly releases are issued at 9:15 a.m. 2027: October 16.'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                industrial_calendar(NOW, lambda _: source, n.html_to_text)

    def test_retail_confidence_interval_and_annual_change_never_become_previous(self):
        text, missing = retail_details({'summary': RETAIL})
        self.assertEqual(missing, [])
        self.assertIn('2026/09', text)
        self.assertIn('+0.8%', text)
        self.assertIn('前值 +1.3%', text)
        self.assertIn('-0.5 個百分點', text)
        self.assertNotIn('0.4%', text)
        self.assertNotIn('6.3%', text)

    def test_retail_negative_zero_missing_previous_and_unrelated_revision(self):
        source = RETAIL.split('The July')[0]
        text, missing = retail_details({'summary': source.replace('up 0.8', 'down 0.8')})
        self.assertEqual(missing, [])
        self.assertIn('-0.8%', text)
        self.assertIn('前值 暫缺', text)
        text, _ = retail_details({'summary': source.replace('up 0.8', 'up 0.0')})
        self.assertIn('+0.0%', text)
        text, _ = retail_details({'summary': RETAIL.replace('The July 2026 to August 2026', 'The June 2026 to July 2026')})
        self.assertIn('前值 暫缺', text)

    def test_missing_month_actual_or_basis_blocks_retail_not_inferred_from_other_numbers(self):
        for source in ('Sales were up 6.3 percent from last year.', RETAIL.replace('September 2026', 'this month'), RETAIL.replace('adjusted for seasonal variation', 'seasonal basis unavailable')):
            with self.subTest(source=source):
                row = {'summary': source, 'rule': {'key': 'retail'}}
                self.assertTrue(n.release_critical_missing(row))

    def test_claims_require_actual_and_keep_people_units(self):
        row = {'summary': 'The 4-week moving average was 220,000.', 'rule': {'key': 'claims'}}
        self.assertTrue(n.release_critical_missing(row))
        row['summary'] = "initial claims was 216,000, a decrease of 7,000 from the previous week's unrevised level of 223,000. The 4-week moving average was 220,000."
        self.assertEqual(n.release_critical_missing(row), [])
        copy = n.format_metrics(row['summary'], 'claims')
        for value in ('216,000 人', '223,000 人', '7,000 人', '220,000 人'):
            self.assertIn(value, copy)

    def test_retail_publication_date_is_not_refresh_time(self):
        when = n.official_page_published_at(RETAIL, 'retail', NOW)
        self.assertEqual(when.isoformat(), '2026-10-15T12:30:00+00:00')

    def test_ppi_rss_requires_final_demand_actual_period_and_bases(self):
        item = {'rule': {'key': 'ppi'}, 'title': 'PRODUCER PRICE INDEXES - September 2026',
                'summary': 'The Producer Price Index for final demand rose 0.4 percent in September, seasonally adjusted. For the 12 months ended in September, the index for final demand advanced 3.2 percent on an unadjusted basis.'}
        text, missing = ppi_details(item)
        self.assertEqual(missing, [])
        self.assertIn('0.4%', text)
        self.assertIn('3.2%', text)
        self.assertIn('前值 暫缺', text)
        item['summary'] = 'Core final demand prices rose 0.6 percent. Food prices rose 2.0 percent.'
        self.assertTrue(ppi_details(item)[1])
        item['summary'] = 'The Producer Price Index for final demand rose 0.4 percent. For the 12 months ended in September, the index for final demand advanced 3.2 percent.'
        self.assertIn('月增率季調口徑', ppi_details(item)[1])

    def test_new_calendar_survives_merge_and_is_visible_on_its_release_day(self):
        events = industrial_calendar(NOW, lambda _: 'monthly releases are issued at 9:15 a.m. 2026: October 16. Historical Release Dates', n.html_to_text)
        now = datetime.fromisoformat('2026-10-16T07:00:00+08:00')
        merged = n.merge_calendar_events(events, events)
        cards = policy.calendar_cards(merged, now)
        self.assertEqual(len(cards), 1)
        self.assertIn('21:15', cards[0]['description'])
        self.assertIn('工業生產', cards[0]['description'])
        self.assertEqual(policy.calendar_cards(merged, NOW), [])

    def test_new_results_use_existing_scheduled_dedupe_without_new_reminders(self):
        from test_macro_calendar_delivery import MacroCalendarDeliveryTests
        fixture = MacroCalendarDeliveryTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        now = fixture.now
        def row(key, summary):
            rule = next(r for r in n.EVENT_RULES if r['key'] == key)
            return {'id': 'new-'+key, 'rule': rule, 'published': now, 'summary': summary, 'url': rule['source']}
        rows = [row('retail', RETAIL), row('claims', 'initial claims was 216,000.'), row('ppi', '')]
        rows[-1].update(reference_period='2026-M09', price_metrics={'monthly': 0.4, 'annual': 3.2, 'monthly_seasonally_adjusted': True, 'annual_unadjusted': True})
        fixture.releases = rows
        n.run(now); n.run(now)
        self.assertEqual(len(fixture.member_calls()), 3)
        self.assertEqual(len([k for k in fixture.state['sent'] if k.startswith('release-event:')]), 3)
        self.assertEqual(policy.REMINDER_EVENTS, policy.CORE_EVENTS | {'fed_chair_policy'})


if __name__ == '__main__':
    unittest.main()
