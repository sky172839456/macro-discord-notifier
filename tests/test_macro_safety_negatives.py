"""PR128 additional safety boundaries (Codex 2026-11-20 synthetic negatives, fixed 2026-11-26).

1. A percentage of another subject inside the retail headline sentence is never the headline value.
2. Conflicting statements about the same adjacent month pair leave the retail prior empty.
3. An industrial-production prior with an explicit wrong year is not used.
"""
import unittest

from macro_result_extensions import details as extended
from test_macro_parse_gaps import RETAIL_1117, IP_1117, retail, industrial
from macro_results import retail_details


class RetailHeadlineSubjectTests(unittest.TestCase):
    def test_other_subject_in_the_same_sentence_is_not_the_headline(self):
        for other in (
                'were $748.2 billion, while e-commerce sales, a different survey, were up 9.9 percent (±0.4 percent) from the previous month, and ',
                'were $748.2 billion; another survey was up 9.9 percent (±0.4 percent) from the previous month, and ',
                'were $748.2 billion, and nonstore retailers were up 9.9 percent (±0.4 percent) from the previous month, and '):
            with self.subTest(other=other):
                source = RETAIL_1117.replace('were $748.2 billion, up 0.2 percent (±0.4 percent)* from the previous month, and ', other)
                text, missing = retail_details(retail(source))
                self.assertIn('零售銷售月增率', missing)
                self.assertNotIn('9.9', text)

    def test_official_headline_and_other_level_formats_still_parse(self):
        text, missing = retail_details(retail(RETAIL_1117))
        self.assertEqual(missing, [])
        self.assertIn('+0.2%', text)
        down = RETAIL_1117.replace('were $748.2 billion, up 0.2 percent', 'were $1,012.5 billion, down 0.3 percent')
        text, missing = retail_details(retail(down))
        self.assertEqual(missing, [])
        self.assertIn('-0.3%', text)


class RetailPriorConflictTests(unittest.TestCase):
    PAIR = ' The August 2026 to September 2026 percent change was unrevised from up {} percent (±0.2 percent).'

    def test_conflicting_unrevised_statements_leave_the_prior_empty(self):
        text, missing = retail_details(retail(RETAIL_1117 + self.PAIR.format('0.5')))
        self.assertEqual(missing, [])
        self.assertIn('前值 暫缺', text)
        self.assertNotIn('0.8%', text)
        self.assertNotIn('0.5%', text)

    def test_conflicting_revised_statements_leave_the_prior_empty(self):
        revised = RETAIL_1117.replace('was unrevised from up 0.8 percent (±0.2 percent).',
                                      'was revised from up 0.6 percent (±0.2 percent) to down 0.1 percent (±0.1 percent).')
        extra = ' The August 2026 to September 2026 percent change was revised from up 0.6 percent to up 0.3 percent.'
        self.assertIn('前值 暫缺', retail_details(retail(revised + extra))[0])

    def test_repeated_identical_statement_is_consistent(self):
        text, _ = retail_details(retail(RETAIL_1117 + self.PAIR.format('0.8')))
        self.assertIn('前值 +0.8%', text)
        self.assertIn('未修訂', text)

    def test_other_month_pairs_do_not_conflict(self):
        other = ' The July 2026 to August 2026 percent change was unrevised from up 0.5 percent (±0.2 percent).'
        self.assertIn('前值 +0.8%', retail_details(retail(RETAIL_1117 + other))[0])


class IndustrialPriorYearTests(unittest.TestCase):
    def test_explicit_wrong_prior_year_is_not_used(self):
        for year in ('2025', '2027'):
            with self.subTest(year=year):
                source = IP_1117.replace('increasing 0.7 percent in September.', f'increasing 0.7 percent in September {year}.')
                text, missing = extended(industrial(source))
                self.assertEqual(missing, [])
                self.assertIn('前值 暫缺', text)
                self.assertNotIn('+0.7%', text)

    def test_explicit_right_year_and_no_year_still_use_the_prior(self):
        for source in (IP_1117, IP_1117.replace('in September.', 'in September 2026.')):
            with self.subTest(source=source[60:140]):
                text, missing = extended(industrial(source))
                self.assertEqual(missing, [])
                self.assertIn('前值 +0.7%', text)

    def test_january_release_prior_is_december_of_the_previous_year(self):
        source = (IP_1117.replace('Release Date: November 17, 2026', 'Release Date: February 17, 2027')
                  .replace('in October after increasing 0.7 percent in September.', 'in January after increasing 0.7 percent in December 2026.')
                  .replace('in October', 'in January'))
        text, missing = extended(industrial(source))
        self.assertEqual(missing, [])
        self.assertIn('前值 +0.7%', text)
        wrong = source.replace('December 2026', 'December 2027')
        self.assertIn('前值 暫缺', extended(industrial(wrong))[0])


if __name__ == '__main__':
    unittest.main()
