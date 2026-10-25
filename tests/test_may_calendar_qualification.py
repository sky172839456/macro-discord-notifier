import copy
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
import news_auto_recovery as auto
import crypto_news_notifier as news
from test_rules_claims_copy import QBODY,QUBIC

class MayCalendarQualificationTests(unittest.TestCase):
    def test_real_modal_outside_date_is_still_required(self):
        for source in (QBODY+" Claims may be rejected.", "Claims may remain open until May 1, 2027.",
                       "May 1, 2027 may change."):
            with self.subTest(source=source),self.assertRaises(ValueError):
                auto.checked_copy(source,'申請期限為2027年5月1日。')
        self.assertIn('可能',auto.checked_copy(
            "Claims may remain open until May 1, 2027.",'申請可能開放至2027年5月1日。'))
    def test_invalid_or_incomplete_date_does_not_bypass_guard(self):
        for source in ("Claims remain open until May 32, 2027.","Claims remain open until May 1.",
                       "Claims remain open until May 0, 2027.","May changes are possible."):
            with self.subTest(source=source),self.assertRaises(ValueError):
                auto.checked_copy(source,'申請將結束。')
    def test_wrong_translated_date_is_still_rejected(self):
        for text in ('申請開放至2027年6月1日。','申請開放至2027年5月2日。','申請開放至2028年5月1日。'):
            with self.subTest(text=text),self.assertRaises(ValueError):
                auto.checked_copy(QBODY,text)
    def test_other_qualifications_are_not_masked(self):
        for source in (QBODY+" Applications might be rejected.",QBODY+" The amount could change.",
                       QBODY+" Recovery is not guaranteed."):
            with self.subTest(source=source),self.assertRaises(ValueError):
                auto.checked_copy(source,'申請開放至2027年5月1日。')
    def test_current_rss_summary_can_render_without_touching_source_or_state(self):
        now=datetime(2026,10,26,tzinfo=timezone.utc)
        row={'id':'fixture','title':QUBIC,'summary':QBODY,'source':'fixture',
             'published':now,'url':'https://example.invalid/qubic'}
        before=copy.deepcopy(row)
        def translated(source):
            return ('Qubic在140萬美元駭客攻擊後重啟區塊鏈，開放資產追回申請' if source==QUBIC
                    else '該網路驗證者已通過復原計畫，並開放申請至2027年5月1日。')
        with patch.object(news,'translate_text',side_effect=translated):
            result=auto.enrich(row,{},now)
        self.assertEqual(result['summary_basis'],'rss')
        self.assertIn('2027年5月1日',str(result['summary_zh_points']))
        self.assertEqual(row,before)

if __name__=="__main__":unittest.main()
