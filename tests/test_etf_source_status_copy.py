import unittest
from datetime import datetime,timezone
from etf_source_context import parse
from market_brief_v2 import etf_lines


class EtfSourceStatusCopyTests(unittest.TestCase):
    def text(self,values):
        row=parse("<table><tr><td>29 Oct 2026</td>"+''.join("<td>"+x+"</td>" for x in values)+"</tr></table>")
        return etf_lines({"etf":row,"eth_etf":row},False)

    def test_source_blank_and_missing_total_are_not_fetch_failure_or_official_release(self):
        for cells in (["-","-","0.0"],["-","-","-"]):
            text=self.text(cells)
            self.assertIn("Farside 尚未列出完整數據",text)
            self.assertIn("交易日：10/29",text)
            self.assertNotIn("無法取得",text)
            self.assertNotIn("官方",text)
            self.assertNotIn("0美元",text)

    def test_no_snapshot_does_not_claim_source_or_official_has_not_published(self):
        text=etf_lines({},False)
        self.assertEqual(text.count("暫時無法取得 Farside 數據"),2)
        self.assertNotIn("尚未列出",text)
        self.assertNotIn("官方",text)

    def test_inconsistent_total_is_a_separate_verification_state(self):
        text=self.text(["1.0","2.0","9.0"])
        self.assertIn("Farside 分項與合計待核對",text)
        self.assertNotIn("尚未列出",text)
        self.assertNotIn("900萬",text)

    def test_partial_nonzero_is_provisional_and_complete_zero_stays_numeric(self):
        text=self.text(["-","1.0","1.0"])
        self.assertIn("來源目前合計 **淨流入100萬美元**（暫定）",text)
        self.assertIn("部分基金未列數值",text)
        self.assertIn("[Farside來源]",text)
        text=self.text(["0.0","0.0","0.0"])
        self.assertIn("來源目前合計 **0美元**",text)
        self.assertNotIn("尚未列出",text)
        self.assertNotIn("（暫定）",text)

