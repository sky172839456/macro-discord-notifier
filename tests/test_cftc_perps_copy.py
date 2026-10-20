import unittest

import news_auto_recovery as auto
import notification_quality as quality
from news_copy_terms import repair_translation


TITLE = 'U.S. CFTC rebuffs CME legal stance in consequential fight over perpetual futures'
SUMMARY = ("The future of perps in the U.S. may be at stake as the CFTC argues that CME "
           "hasn't shown the new policy is hurting it after the agency OK'd its first bitcoin perp.")
BAD_TITLE = '美國 CFTC 在永久期貨的關鍵鬥爭中反駁 CME 的法律立場'
BAD_SUMMARY = '美國犯罪分子的未來可能受到威脅，因為 CFTC 認為 CME 尚未表明新政策正在損害它，該機構批准了它的第一個 Bitcoin 犯罪。'


class CftcPerpsCopyTests(unittest.TestCase):
    def test_headline_uses_perpetual_futures(self):
        result = quality.checked_translation(TITLE, BAD_TITLE)
        self.assertIn('永續期貨', result)
        self.assertIn('反駁 CME', result)
        self.assertNotIn('永久', result)

    def test_summary_preserves_uncertainty_and_unproven_harm(self):
        result = auto.checked_copy(SUMMARY, BAD_SUMMARY)
        self.assertIn('永續合約', result)
        self.assertIn('可能', result)
        self.assertIn('主張', result)
        self.assertIn('CME 並未證明', result)
        self.assertNotIn('犯罪', result)
        self.assertNotIn('已證明', result)

    def test_cached_copy_is_repaired_at_render(self):
        row = dict(title=TITLE, summary=SUMMARY, title_zh=BAD_TITLE,
                   summary_zh_points=[BAD_SUMMARY], category={'key': 'regulation'})
        self.assertIn('永續期貨', quality.headline(row))
        self.assertIn('CME 並未證明', quality.chinese_points(row)[0])
        self.assertIn('犯罪', row['summary_zh_points'][0])

    def test_exact_source_guard_preserves_changed_facts(self):
        changes = [
            SUMMARY.replace("hasn't shown", 'has shown'),
            SUMMARY.replace('may be', 'will be'),
            SUMMARY.replace("OK'd", 'rejected'),
            SUMMARY.replace('first bitcoin', 'first ether'),
            SUMMARY+' Fees are 0.5%.',
            SUMMARY+' Approval is subject to a new rule.',
        ]
        for source in changes:
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, BAD_SUMMARY), BAD_SUMMARY)

    def test_real_criminal_perp_is_not_rewritten(self):
        text = '警方逮捕犯罪嫌疑人。'
        self.assertEqual(repair_translation('Police arrest the perps.', text), text)

    def test_mixed_crime_and_derivatives_are_not_globally_replaced(self):
        source = 'CFTC investigates perps trading and a criminal perpetrator.'
        text = 'CFTC 調查永續合約交易與犯罪嫌疑人。'
        self.assertEqual(repair_translation(source, text), text)

    def test_whitespace_and_smart_apostrophes_do_not_change_meaning(self):
        source = SUMMARY.replace("'", '’').replace(' may ', '  may  ')
        self.assertIn('CME 並未證明', auto.checked_copy(source, BAD_SUMMARY))

    def test_numeric_guard_is_not_bypassed_by_fixed_copy(self):
        with self.assertRaises(ValueError):
            quality.checked_translation(SUMMARY, BAD_SUMMARY+' 收入增加31%。')

    def test_repair_is_idempotent(self):
        fixed = auto.checked_copy(SUMMARY, BAD_SUMMARY)
        self.assertEqual(auto.checked_copy(SUMMARY, fixed), fixed)
