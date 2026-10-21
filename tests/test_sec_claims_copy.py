import unittest

import news_auto_recovery as auto
import notification_quality as quality
from news_copy_terms import repair_translation

TITLE = 'Market participants weigh in on SEC’s proposed crypto regulations'
BODY = ('The financial agency is scheduled to close public comments on its '
        '‘Regulation Crypto Assets’ proposed in August.')
COURT = ('Nine other crypto platforms voluntarily restricted app access in Kazakhstan, '
         'prompting the regulator to withdraw its claims against them.')
BAD_TITLE = '市場參與者參與 SEC 提議的加密資產規則'
BAD_BODY = '金融機構預定在八月提出的《加密資產規範》上結束公眾意見徵集。'
BAD_COURT = '其他九個加密平台自願限制在哈薩克的應用程式存取，促使監管機關撤回對其索賠。'


class SecAndClaimsCopyTests(unittest.TestCase):
    def test_sec_headline_keeps_proposal_and_comments(self):
        result = auto.checked_copy(TITLE, BAD_TITLE)
        self.assertIn('SEC', result)
        self.assertIn('擬議', result)
        self.assertIn('發表意見', result)

    def test_august_modifies_proposal_not_comment_deadline(self):
        result = auto.checked_copy(BODY, BAD_BODY)
        self.assertIn('監管機關', result)
        self.assertIn('八月提出', result)
        self.assertIn('預定結束', result)
        self.assertIn('Regulation Crypto Assets', result)
        self.assertNotIn('預定在八月', result)
        self.assertNotIn('金融機構', result)
        self.assertNotIn('截止', result)

    def test_cached_sec_copy_is_repaired_at_render(self):
        row = dict(title=TITLE, summary=BODY, title_zh=BAD_TITLE,
                   summary_zh_points=[BAD_BODY], category={'key': 'regulation'})
        self.assertIn('發表意見', quality.headline(row))
        self.assertIn('八月提出', quality.chinese_points(row)[0])
        self.assertEqual(row['summary_zh_points'], [BAD_BODY])

    def test_changed_month_stage_and_deadline_are_not_overwritten(self):
        for source in (BODY.replace('August', 'September'),
                       BODY.replace('is scheduled to close', 'closed'),
                       BODY+' The deadline is November 1, 2026.',
                       BODY.replace('proposed in August', 'to be proposed in August')):
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, BAD_BODY), BAD_BODY)

    def test_legal_claims_do_not_invent_compensation(self):
        result = auto.checked_copy(COURT, BAD_COURT)
        self.assertIn('九個', result)
        self.assertIn('法律請求', result)
        self.assertIn('自願', result)
        self.assertNotIn('索賠', result)
        self.assertNotIn('賠償', result)

    def test_insurance_and_damage_claims_are_not_globally_changed(self):
        for source in ('The insurer denied nine insurance claims.',
                       COURT+' The claims seek damages.'):
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, '相關索賠。'), '相關索賠。')

    def test_changed_platform_count_is_not_overwritten(self):
        self.assertEqual(repair_translation(COURT.replace('Nine', 'Ten'), BAD_COURT), BAD_COURT)

    def test_numeric_guard_still_rejects_invented_figures(self):
        with self.assertRaises(ValueError):
            quality.checked_translation(BODY, BAD_BODY+' 有31%的新稅率。')

    def test_new_uncertainty_is_not_removed(self):
        changed = COURT+' This may change.'
        self.assertEqual(repair_translation(changed, BAD_COURT), BAD_COURT)
        with self.assertRaises(ValueError):
            auto.checked_copy(changed, BAD_COURT)

    def test_straight_quotes_and_repeated_render_are_stable(self):
        source = BODY.replace('‘', "'").replace('’', "'")
        fixed = auto.checked_copy(source, BAD_BODY)
        self.assertEqual(auto.checked_copy(source, fixed), fixed)
