"""Regression for the 2026-11-17 parsing gaps (retail footnote, industrial prior, FOMC document type)."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import notifier as n
from macro_calendar import census_calendar, with_schedule_reference
from macro_result_extensions import details as extended
from macro_results import retail_details
import macro_member_check as member_check

# Official Census wording of the 2026-11-17 release (sales for October 2026).
RETAIL_1117 = ('FOR IMMEDIATE RELEASE: Tuesday, November 17, 2026 Advance Monthly Sales for Retail and Food Services '
               'November 17, 2026 CB26-181 Advance Estimates of U.S. Retail and Food Services '
               'Advance estimates of U.S. retail and food services sales for October 2026, adjusted for seasonal '
               'variation and holiday and trading-day differences, but not for price changes, were $748.2 billion, '
               'up 0.2 percent (±0.4 percent)* from the previous month, and up 6.8 percent (±0.5 percent) from '
               'October 2025. Total sales for the August 2026 through October 2026 period were up 6.4 percent '
               '(±0.5 percent) from the same period a year ago. The August 2026 to September 2026 percent change '
               'was unrevised from up 0.8 percent (±0.2 percent). Additional Release Tables - October 2026')
# Official Fed G.17 wording of the same day (October 2026 data).
IP_1117 = ('Release Date: November 17, 2026 Industrial production (IP) decreased 0.4 percent in October after '
           'increasing 0.7 percent in September. Manufacturing output rose 0.3 percent in October, while mining '
           'output decreased 0.8 percent and the index for utilities fell 4.3 percent. Capacity utilization dropped '
           'to 76.4 percent in October, a rate that is 3.0 percentage points below its long-run average. '
           'Seasonally adjusted')
CENSUS_ROW = ('Advance Monthly Sales for Retail and Food Services November 17, 2026 8:30 AM October 2026 '
              'A202611170830 A202610 Manufacturing and Trade: Inventories and Sales November 17, 2026 10:00 AM '
              'September 2026 A202611171000 A202609')
RETAIL_TIME = datetime(2026, 11, 17, 13, 30, tzinfo=timezone.utc)


def rule(key):
    return next(r for r in n.EVENT_RULES if r['key'] == key)


def retail(summary, reference='2026-M10'):
    return {'summary': summary, 'scheduled_reference_period': reference}


def industrial(summary):
    return {'rule': rule('industrial'), 'title': '', 'summary': summary}


class RetailFootnoteAndScheduleTests(unittest.TestCase):
    def test_official_1117_text_reads_value_footnote_and_unrevised_prior(self):
        text, missing = retail_details(retail(RETAIL_1117))
        self.assertEqual(missing, [])
        self.assertIn('2026/10｜前期 2026/09', text)
        self.assertIn('+0.2%', text)
        self.assertIn('前值 +0.8%', text)
        self.assertIn('未修訂', text)
        for unrelated in ('6.8%', '6.4%', '0.4%', '0.5%'):
            self.assertNotIn(unrelated, text)

    def test_mismatched_reference_month_is_blocked(self):
        # Codex negative case 1: body says September while the schedule says October.
        source = RETAIL_1117.replace('sales for October 2026', 'sales for September 2026')
        self.assertEqual(retail_details(retail(source))[1], ['零售資料月份與官方排程不一致'])
        # Also blocked when the release names the right month but the schedule row is another month.
        self.assertEqual(retail_details(retail(RETAIL_1117, '2026-M09'))[1], ['零售資料月份與官方排程不一致'])

    def test_unrelated_survey_percentage_is_never_the_headline(self):
        # Codex negative case 2: an unrelated "up 9.9 percent from the previous month".
        headline_gone = RETAIL_1117.replace('up 0.2 percent (±0.4 percent)* from the previous month, and ', '')
        source = headline_gone + ' Another survey was up 9.9 percent from the previous month.'
        text, missing = retail_details(retail(source))
        self.assertIn('零售銷售月增率', missing)
        self.assertEqual(text, '')
        # Even with a real headline, the extra sentence never replaces it.
        text, missing = retail_details(retail(RETAIL_1117 + ' Another survey was up 9.9 percent from the previous month.'))
        self.assertEqual(missing, [])
        self.assertIn('+0.2%', text)
        self.assertNotIn('9.9', text)

    def test_missing_schedule_blocks_instead_of_inferring_from_release_date(self):
        self.assertEqual(retail_details({'summary': RETAIL_1117})[1], ['零售官方排程資料月份'])
        self.assertEqual(retail_details(retail(RETAIL_1117, 'October'))[1], ['零售官方排程資料月份'])

    def test_only_the_confirmed_single_footnote_format_is_accepted(self):
        for source in (RETAIL_1117.replace(')* from', ')** from'),
                       RETAIL_1117.replace(')* from', ')*see note from')):
            with self.subTest(source=source[300:420]):
                self.assertIn('零售銷售月增率', retail_details(retail(source))[1])

    def test_basis_must_be_in_the_headline_sentence(self):
        source = RETAIL_1117.replace('adjusted for seasonal variation', 'not adjusted for seasonal variation')
        self.assertEqual(retail_details(retail(source))[1], ['零售銷售季調口徑'])
        moved = (RETAIL_1117.replace('adjusted for seasonal variation and holiday and trading-day differences, ', '')
                 + ' Figures are adjusted for seasonal variation.')
        self.assertEqual(retail_details(retail(moved))[1], ['零售銷售季調口徑'])

    def test_prior_only_from_adjacent_months_of_this_release(self):
        revised = RETAIL_1117.replace('was unrevised from up 0.8 percent (±0.2 percent).',
                                      'was revised from up 0.6 percent (±0.2 percent)* to down 0.1 percent (±0.1 percent).')
        text, _ = retail_details(retail(revised))
        self.assertIn('前值 -0.1%', text)
        self.assertIn('修訂後', text)
        self.assertNotIn('0.6%', text)
        for wrong in ('The July 2026 to August 2026', 'The August 2025 to September 2025'):
            with self.subTest(wrong=wrong):
                text, missing = retail_details(retail(RETAIL_1117.replace('The August 2026 to September 2026', wrong)))
                self.assertEqual(missing, [])
                self.assertIn('前值 暫缺', text)
        both = RETAIL_1117 + ' The August 2026 to September 2026 percent change was revised from up 0.8 percent to up 0.9 percent.'
        self.assertIn('前值 暫缺', retail_details(retail(both))[0])

    def test_january_release_crosses_the_year_for_prior(self):
        source = (RETAIL_1117.replace('sales for October 2026', 'sales for January 2027')
                  .replace('The August 2026 to September 2026', 'The November 2026 to December 2026'))
        text, missing = retail_details(retail(source, '2027-M01'))
        self.assertEqual(missing, [])
        self.assertIn('2027/01｜前期 2026/12', text)
        self.assertIn('前值 +0.8%', text)


class CensusScheduleReferenceTests(unittest.TestCase):
    NOW = datetime(2026, 11, 17, 14, tzinfo=timezone.utc)

    def test_schedule_row_keeps_its_data_month_only_when_text_and_code_agree(self):
        events, _ = census_calendar(self.NOW, lambda _: CENSUS_ROW, n.html_to_text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['time'], RETAIL_TIME)
        self.assertEqual(events[0]['reference_period'], '2026-M10')
        disagree = CENSUS_ROW.replace('A202610', 'A202609')
        events, _ = census_calendar(self.NOW, lambda _: disagree, n.html_to_text)
        self.assertNotIn('reference_period', events[0])
        events, _ = census_calendar(self.NOW, lambda _: 'Advance Monthly Sales for Retail and Food Services November 17, 2026 8:30 AM', n.html_to_text)
        self.assertNotIn('reference_period', events[0])

    def test_reference_follows_official_publication_time_not_detection_time(self):
        events, _ = census_calendar(self.NOW, lambda _: CENSUS_ROW, n.html_to_text)
        item = {'rule': rule('retail'), 'summary': RETAIL_1117, 'published': RETAIL_TIME}
        self.assertEqual(with_schedule_reference(item, events)['scheduled_reference_period'], '2026-M10')
        late = dict(item, published=RETAIL_TIME + timedelta(days=1))
        self.assertNotIn('scheduled_reference_period', with_schedule_reference(late, events))
        other = dict(events[0], reference_period='2026-M09', id='other')
        self.assertNotIn('scheduled_reference_period', with_schedule_reference(item, events + [other]))
        claims = dict(item, rule=rule('claims'))
        self.assertIs(with_schedule_reference(claims, events), claims)

    def test_merge_keeps_census_data_month_when_another_source_listed_it_first(self):
        census_event, = census_calendar(self.NOW, lambda _: CENSUS_ROW, n.html_to_text)[0]
        auxiliary = {'id': 'aux', 'title': 'Retail Sales m/m', 'time': RETAIL_TIME, 'rule': rule('retail')}
        merged = n.merge_calendar_events([auxiliary], [census_event])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['id'], 'aux')
        self.assertEqual(merged[0]['reference_period'], '2026-M10')
        self.assertNotIn('reference_period', auxiliary)  # source event is not mutated


class RetailDeliveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        from test_macro_calendar_delivery import MacroCalendarDeliveryTests
        self.fixture = MacroCalendarDeliveryTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        # 22:00 Taiwan on release day; the schedule row was read earlier that day.
        self.now = RETAIL_TIME + timedelta(minutes=30)
        events, _ = census_calendar(self.now, lambda _: CENSUS_ROW, n.html_to_text)
        self.fixture.calendar = events
        self.fixture.releases = [{'id': 'page-retail-x', 'title': '美國零售銷售', 'summary': RETAIL_1117,
                                  'url': 'https://www.census.gov/retail/sales.html', 'rule': rule('retail'),
                                  'published': n.official_page_published_at(RETAIL_1117, 'retail', self.now)}]

    def result_cards(self):
        return [c.args[1] for c in self.fixture.member_calls() if '零售銷售月增率' in c.args[1].get('description', '')]

    def test_official_text_is_delivered_once_with_value_and_prior(self):
        n.run(self.now); n.run(self.now + timedelta(minutes=5))
        cards = self.result_cards()
        self.assertEqual(len(cards), 1)
        self.assertIn('+0.2%', cards[0]['description'])
        self.assertIn('前值 +0.8%', cards[0]['description'])
        self.assertTrue(any(k.startswith('release-event:retail:') for k in self.fixture.state['sent']))

    def test_wrong_month_body_is_held_privately_and_not_marked_sent(self):
        self.fixture.releases[0]['summary'] = RETAIL_1117.replace('sales for October 2026', 'sales for September 2026')
        n.run(self.now)
        self.assertEqual(self.result_cards(), [])
        held = [c.args[1] for c in self.fixture.admin_calls() if '暫緩' in c.args[1].get('title', '')]
        self.assertTrue(held)
        self.assertIn('零售資料月份與官方排程不一致', str(held[0]))
        self.assertFalse(any(k.startswith('release-event:retail:') for k in self.fixture.state['sent']))

    def test_missing_schedule_holds_the_result(self):
        self.fixture.calendar = []
        n.run(self.now)
        self.assertEqual(self.result_cards(), [])


class IndustrialPriorTests(unittest.TestCase):
    def test_official_1117_text_reads_prior_after_increasing_and_capacity(self):
        text, missing = extended(industrial(IP_1117))
        self.assertEqual(missing, [])
        self.assertIn('2026/10｜前期 2026/09', text)
        self.assertIn('-0.4%', text)
        self.assertIn('前值 +0.7%', text)
        self.assertIn('76.4%', text)
        self.assertNotIn('0.3%', text)

    def test_prior_direction_and_wording(self):
        cases = [('after decreasing 0.3 percent in September', '前值 -0.3%'),
                 ('after falling 0.2 percent in September', '前值 -0.2%'),
                 ('after edging down 0.1 percent in September', '前值 -0.1%'),
                 ('after rising 0.5 percent in September', '前值 +0.5%'),
                 ('after a downwardly revised gain of 0.1 percent in September', '前值 +0.1%'),
                 ('after a decline of 0.6 percent in September', '前值 -0.6%'),
                 ('after being unchanged in September', '前值 +0.0%')]
        for clause, expected in cases:
            with self.subTest(clause=clause):
                text, missing = extended(industrial(IP_1117.replace('after increasing 0.7 percent in September', clause)))
                self.assertEqual(missing, [])
                self.assertIn(expected, text)

    def test_prior_never_taken_from_another_month_or_indicator(self):
        wrong_month = IP_1117.replace('in September. Manufacturing', 'in August. Manufacturing')
        self.assertIn('前值 暫缺', extended(industrial(wrong_month))[0])
        other_indicator = (IP_1117.replace(' after increasing 0.7 percent in September', '')
                           .replace('Manufacturing output rose 0.3 percent in October,',
                                    'Manufacturing output rose 0.3 percent in October after increasing 0.5 percent in September,'))
        text, missing = extended(industrial(other_indicator))
        self.assertEqual(missing, [])
        self.assertIn('前值 暫缺', text)
        self.assertNotIn('0.5%', text)

    def test_january_prior_is_december_of_previous_year(self):
        source = ('Release Date: February 17, 2027 Industrial production (IP) decreased 0.2 percent in January after '
                  'rising 0.4 percent in December. Seasonally adjusted')
        text, missing = extended(industrial(source))
        self.assertEqual(missing, [])
        self.assertIn('2027/01｜前期 2026/12', text)
        self.assertIn('前值 +0.4%', text)


def fed_row(day, title, published):
    return {'id': day, 'title': title, 'summary': title, 'rule': rule('fomc'), 'time_label': '來源標示發布時間',
            'url': f'https://www.federalreserve.gov/newsevents/pressreleases/monetary{day}a.htm', 'published': published}


STATEMENT_1028 = ('October 28, 2026 Federal Reserve issues FOMC statement The Federal Open Market Committee approved the '
                  'following statement for release by a 10 – 2 vote: The Committee decided to maintain the target range '
                  'for the federal funds rate at 3-3/4 to 4 percent, in support of the Federal Reserve\'s dual mandate.')
ROWS = [fed_row('20261112', 'Federal Reserve announces revised tentative schedule of Federal Open Market Committee meetings in 2027',
                datetime(2026, 11, 12, 17, 45, tzinfo=timezone.utc)),
        fed_row('20261028', 'Federal Reserve issues FOMC statement', datetime(2026, 10, 28, 18, tzinfo=timezone.utc)),
        fed_row('20260916', 'Federal Reserve issues FOMC statement', datetime(2026, 9, 16, 18, tzinfo=timezone.utc))]


class FomcDocumentTypeTests(unittest.TestCase):
    def test_official_titles_are_typed(self):
        self.assertEqual([member_check.fomc_document_type(r) for r in ROWS], ['schedule', 'statement', 'statement'])
        self.assertEqual(member_check.fomc_document_type({'title': 'Minutes of the Federal Open Market Committee, October 27-28, 2026'}), 'minutes')
        self.assertEqual(member_check.fomc_document_type({'title': 'Federal Reserve Board and Federal Open Market Committee release economic projections from the June 16-17 FOMC meeting'}), 'projections')
        self.assertEqual(member_check.fomc_document_type({'title': 'Federal Reserve issues FOMC statement on something else'}), 'unknown')

    def test_latest_decision_is_chosen_over_newer_schedule_release(self):
        decision, skipped = member_check.fomc_decision(ROWS)
        self.assertEqual(decision['id'], '20261028')
        self.assertEqual(skipped, [{'type': 'schedule', 'source': ROWS[0]['url']}])

    def test_newer_unrecognized_fomc_release_stops_instead_of_skipping(self):
        rows = ROWS + [fed_row('20261119', 'Federal Reserve announces policy action', datetime(2026, 11, 19, tzinfo=timezone.utc))]
        with self.assertRaises(ValueError):
            member_check.fomc_decision(rows)

    def run_check(self, pages):
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}), \
             patch.object(n, 'parse_feed', side_effect=lambda _s, _u, provider: list(ROWS) if provider == 'FED_POLICY' else []), \
             patch.object(n, 'http_text', side_effect=lambda url, **_: pages.get(url, '<rss/>')), \
             patch.object(n, 'http_bytes', side_effect=lambda url, **_: b''):
            return member_check.check()

    def test_audit_parses_latest_real_decision(self):
        result = self.run_check({ROWS[1]['url']: STATEMENT_1028})
        self.assertEqual(result['live']['fomc']['state'], 'parsed')
        self.assertEqual(result['live']['fomc']['source'], ROWS[1]['url'])
        self.assertIn('3.75%～4.00%', result['live']['fomc']['copy'])
        self.assertEqual(result['live']['fomc']['skippedNonDecision'][0]['type'], 'schedule')
        self.assertEqual(result['discordSends'], 0)

    def test_audit_never_falls_back_to_an_older_parseable_decision(self):
        older = STATEMENT_1028.replace('October 28', 'September 16')
        with self.assertRaises(ValueError) as caught:
            self.run_check({ROWS[1]['url']: 'Federal Reserve issues FOMC statement (text unavailable)',
                            ROWS[2]['url']: older})
        self.assertIn('fomc', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
