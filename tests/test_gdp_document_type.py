"""BEA feed: only the national GDP release is a GDP result candidate (2026-11-18 outdoor release)."""
import os
import unittest
from unittest.mock import patch

import notifier as n
from macro_result_extensions import details, gdp_release_title

SECOND = ('Real gross domestic product (GDP) increased at an annual rate of 4.3 percent in the third quarter of 2026 '
          '(July, August, and September), according to the second estimate released today by the U.S. Bureau of '
          'Economic Analysis (BEA). In the second quarter, real GDP increased 2.2 percent.')
ADVANCE = ('Real gross domestic product (GDP) increased at an annual rate of 1.4 percent in the fourth quarter of 2025 '
           '(October, November, and December), according to the advance estimate released today by the U.S. Bureau of '
           'Economic Analysis. In the third quarter, real GDP increased 4.4 percent.')
THIRD = ('Real gross domestic product (GDP) increased at an annual rate of 2.2 percent in the second quarter of 2026, '
         'according to the third estimate. In the first quarter, real GDP increased 2.5 percent (revised).')
OUTDOOR = ('The value added of the outdoor recreation economy accounted for 2.3 percent ($704.2 billion) of current-dollar '
           'gross domestic product (GDP) for the nation in 2025. Across states and the District of Columbia, value added '
           'for outdoor recreation as a share of state GDP ranged from 6.1 percent in Hawaii to 1.0 percent in the District of Columbia.')
STATE = ('Real gross domestic product (GDP) increased in all 50 states and the District of Columbia in the third quarter of 2025. '
         'State-level changes ranged from a 6.5 percent increase in Kansas to a 0.4 percent increase in North Dakota.')
COUNTY = ('Real gross domestic product (GDP) increased in 2,273 counties, decreased in 809 counties, and was unchanged in 24 counties in 2024.')
TRADE = ('The U.S. current-account deficit widened by $33.4 billion to $246.0 billion in the second quarter of 2026. '
         'The second-quarter deficit was 3.0 percent of current-dollar gross domestic product, up from 2.7 percent in the first quarter.')
PCE = ('Personal income increased $201.8 billion (0.7 percent at a monthly rate) in October, according to estimates released '
       'today by the U.S. Bureau of Economic Analysis (BEA). Personal consumption expenditures (PCE) increased $63.8 billion (0.3 percent).')

ENTRIES = (
    ('GDP, (Second Estimate) and Corporate Profits, 3rd Quarter 2026', SECOND, 'Wed, 25 Nov 2026 08:30:00 EST'),
    ('Personal Income and Outlays, October 2026', PCE, 'Wed, 25 Nov 2026 08:30:00 EST'),
    ('Outdoor Recreation Economic Statistics, U.S. and States, 2025', OUTDOOR, 'Wed, 18 Nov 2026 10:00:00 EST'),
    ('U.S. International Transactions and Investment Position, 2nd Quarter 2026', TRADE, 'Thu, 24 Sep 2026 08:30:00 EDT'),
    ('GDP (Advance Estimate), 4th Quarter and Year 2025', ADVANCE, 'Fri, 20 Feb 2026 08:30:00 EST'),
    ('Gross Domestic Product by County and Personal Income by County, 2024', COUNTY, 'Thu, 05 Feb 2026 08:30:00 EST'),
    ('Gross Domestic Product by State and Personal Income by State, 3rd Quarter 2025', STATE, 'Fri, 23 Jan 2026 08:30:00 EST'),
    ('Gross Domestic Product, 2nd Quarter 2026 (Third Estimate), GDP by Industry, and Corporate Profits (Revised)', THIRD, 'Thu, 24 Sep 2026 08:30:00 EDT'),
    ('Gross Domestic Product by Industry, 2nd Quarter 2026', STATE, 'Thu, 24 Sep 2026 10:00:00 EDT'),
    ('Gross Domestic Product for Puerto Rico, 2024', COUNTY, 'Tue, 16 Sep 2025 10:00:00 EDT'),
    ('Arts and Cultural Production Satellite Account, U.S. and States, 2024', OUTDOOR.replace('outdoor recreation', 'arts and cultural'), 'Wed, 02 Apr 2025 10:00:00 EDT'),
)


def feed(entries=ENTRIES):
    items = ''.join(f'<item><title>{t}</title><description>{d}</description>'
                    f'<link>https://www.bea.gov/news/2026/{i}</link><pubDate>{p}</pubDate></item>'
                    for i, (t, d, p) in enumerate(entries))
    return f'<rss><channel>{items}</channel></rss>'


class GdpDocumentTypeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'})
        env.start()
        self.addCleanup(env.stop)

    def test_only_national_gdp_releases_become_gdp_candidates(self):
        rows = n.parse_feed(feed(), 'https://apps.bea.gov/rss/rss.xml', 'BEA')
        gdp = [r['title'] for r in rows if r['rule']['key'] == 'gdp']
        self.assertEqual(gdp, ['GDP, (Second Estimate) and Corporate Profits, 3rd Quarter 2026',
                               'GDP (Advance Estimate), 4th Quarter and Year 2025',
                               'Gross Domestic Product, 2nd Quarter 2026 (Third Estimate), GDP by Industry, and Corporate Profits (Revised)'])
        self.assertIn('Personal Income and Outlays, October 2026', [r['title'] for r in rows if r['rule']['key'] == 'pce'])
        for title in ('Outdoor Recreation Economic Statistics, U.S. and States, 2025',
                      'Gross Domestic Product by State and Personal Income by State, 3rd Quarter 2025',
                      'Gross Domestic Product by County and Personal Income by County, 2024',
                      'Gross Domestic Product by Industry, 2nd Quarter 2026',
                      'Gross Domestic Product for Puerto Rico, 2024',
                      'U.S. International Transactions and Investment Position, 2nd Quarter 2026',
                      'Arts and Cultural Production Satellite Account, U.S. and States, 2024'):
            with self.subTest(title=title):
                self.assertNotIn(title, [r['title'] for r in rows])

    def test_real_advance_second_third_estimates_still_parse(self):
        rows = {r['title']: r for r in n.parse_feed(feed(), 'https://apps.bea.gov/rss/rss.xml', 'BEA') if r['rule']['key'] == 'gdp'}
        expected = {
            'GDP, (Second Estimate) and Corporate Profits, 3rd Quarter 2026': ('2026年第3季（第二次估計）', '+4.3%', '+2.2%'),
            'GDP (Advance Estimate), 4th Quarter and Year 2025': ('2025年第4季（初估）', '+1.4%', '+4.4%'),
            'Gross Domestic Product, 2nd Quarter 2026 (Third Estimate), GDP by Industry, and Corporate Profits (Revised)':
                ('2026年第2季（第三次估計）', '+2.2%', '+2.5%'),
        }
        for title, values in expected.items():
            with self.subTest(title=title):
                text, missing = details(rows[title])
                self.assertEqual(missing, [])
                for value in values:
                    self.assertIn(value, text)
                self.assertEqual(n.release_critical_missing(rows[title]), [])

    def test_real_gdp_release_with_missing_headline_is_still_reported_not_skipped(self):
        broken = (('GDP (Advance Estimate), 3rd Quarter 2026', 'Real GDP estimates were released today.', 'Thu, 29 Oct 2026 08:30:00 EDT'),)
        row, = n.parse_feed(feed(broken), 'https://apps.bea.gov/rss/rss.xml', 'BEA')
        self.assertEqual(row['rule']['key'], 'gdp')
        self.assertEqual(n.release_critical_missing(row), ['實質GDP本季年化季增率與季度'])

    def test_title_document_type(self):
        for title in ('GDP (Advance Estimate), 3rd Quarter 2026', 'GDP, (Second Estimate) and Corporate Profits, 3rd Quarter 2026',
                      'Gross Domestic Product, Third Quarter 2026 (Advance Estimate)', 'Gross Domestic Product',
                      'GDP (Third Estimate), GDP by Industry, and Corporate Profits, 2nd Quarter 2026'):
            with self.subTest(title=title):
                self.assertTrue(gdp_release_title(title))
        for title in ('Outdoor Recreation Economic Statistics, U.S. and States, 2025', 'Gross Domestic Product by State, 2025',
                      'GDP by Industry, 2nd Quarter 2026', 'Real GDP by County and Metropolitan Area, 2024',
                      'Gross Domestic Product for the U.S. Virgin Islands, 2024', 'Marine Economy Satellite Account, 2024',
                      'U.S. International Transactions, 3rd Quarter 2026', ''):
            with self.subTest(title=title):
                self.assertFalse(gdp_release_title(title))

    def test_other_feeds_and_rules_unchanged(self):
        rss = ('<rss><channel><item><title>Gross Domestic Product</title><description>GDP increased 3.0 percent.</description>'
               '<link>https://www.bea.gov/news/1</link><pubDate>Thu, 30 Jul 2026 12:30:00 GMT</pubDate></item></channel></rss>')
        self.assertEqual(n.parse_feed(rss, 'https://www.bea.gov/', 'BEA')[0]['rule']['key'], 'gdp')
        self.assertEqual(n.classify('Advance GDP q/q gross domestic product')['key'], 'gdp')


if __name__ == '__main__':
    unittest.main()
