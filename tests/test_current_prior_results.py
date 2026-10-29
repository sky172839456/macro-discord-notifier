"""Same-release comparison acceptance; no state writes or real Discord sends."""
import copy,io,os,re,unittest,zipfile
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import notifier as n
from macro_result_integrity import details,enrich,pce_values
from macro_result_display import comparison
from pce_comparison import workbook_previous,inline_previous
from notification_format import apply_delivery_format
from notification_layout import text_size

FIX=Path(__file__).parent/"fixtures"
URL="https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026"
XLS="https://www.bea.gov/sites/default/files/2026-10/pi0926-hist.xlsx"
NOW=datetime(2026,10,29,12,34,tzinfo=timezone.utc)


def item():
    return {"id":"synthetic-comparison-test","title":"",
            "summary":(FIX/"pce_20261029.txt").read_text(encoding="utf-8"),
            "rule":next(r for r in n.EVENT_RULES if r["key"]=="pce"),
            "published":NOW,"url":URL}


class CurrentPriorTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{"SLIM_NOTIFICATIONS":"1"})
        env.start();self.addCleanup(env.stop)
        self.book=(FIX/"pce_20261029_hist.xlsx").read_bytes()

    def enriched(self,row=None,link=XLS,book=None):
        row=item() if row is None else row
        html=row["summary"]+' <a href="'+link+'">Historical Comparisons</a>'
        return enrich(row,lambda _:html,lambda _:self.book if book is None else book)

    def test_actual_official_workbook_yields_all_four_adjacent_prior_values(self):
        y,m,values,missing=pce_values(item())
        self.assertFalse(missing);self.assertEqual((y,m),(2026,9))
        self.assertEqual(workbook_previous(self.book,y,m,values),
                         {"monthly":.3,"core_monthly":.3,"annual":3.4,"core_annual":3.0})

    def test_full_card_has_vertical_current_prior_and_change_with_same_vintage_revision(self):
        row=item();original=copy.deepcopy(row);result=self.enriched(row)
        text,missing=details(result)
        self.assertFalse(missing);self.assertEqual(row,original)
        for expected in ("本次 **+0.5%**\n前值 +0.3%\n變化 +0.2 個百分點",
                         "核心PCE月增率**\n本次 **+0.3%**\n前值 +0.3%\n變化 +0.0 個百分點",
                         "PCE年增率**\n本次 **+3.6%**\n前值 +3.4%",
                         "核心PCE年增率**\n本次 **+3.1%**\n前值 +3.0%"):
            self.assertIn(expected,text)
        card=apply_delivery_format(n.release_embed(result,detected_at=NOW),"macro_alerts")
        self.assertIn("[本次公告比較表]("+XLS+")",card["fields"][-1]["value"])
        for old in ("尚未取得可核對的同口徑前值","本文不另推定","市場預期未納入"):
            self.assertNotIn(old,card["description"])
        self.assertLessEqual(text_size(card),5900)
        self.assertNotIn("\\n",card["description"]) # No escaped newline text.

    def test_same_release_core_revision_is_not_replaced_by_prior_release_point_two(self):
        result=self.enriched()
        self.assertEqual(result["pce_previous"]["core_monthly"],.3)
        self.assertEqual(result["pce_previous_period"],"2026/08")

    def test_inline_monthly_table_conflict_blocks_member_send(self):
        row=item();row["summary"]=row["summary"].replace("PCE price index 0.3 0.5","PCE price index 0.3 0.7")
        self.assertTrue(details(row)[1])
        with patch.object(n,"send_discord") as send:
            self.assertFalse(n.deliver_release("https://example.invalid",row,None,None,NOW,False,{}))
        send.assert_not_called()

    def test_workbook_current_disagreement_blocks_not_silently_replaced(self):
        y,m,values,_=pce_values(item());values["annual"]=9
        with self.assertRaises(ValueError):workbook_previous(self.book,y,m,values)

    def test_nonadjacent_or_different_vintage_workbook_does_not_supply_prior(self):
        y,m,values,_=pce_values(item())
        self.assertEqual(workbook_previous(self.book,y,m-1,values),{})
        row=self.enriched(link=XLS.replace("pi0926","pi0826"))
        self.assertEqual(set(row["pce_previous"]),{"monthly","core_monthly"})

    def test_external_or_unlinked_workbook_is_never_fetched(self):
        row=item()
        html=row["summary"]+' <a href="https://example.invalid/pi0926-hist.xlsx">bad</a>'
        with patch("builtins.print"),patch("pce_comparison.workbook_previous") as parse:
            with patch.object(n,"http_bytes") as fetch:
                result=enrich(row,lambda _:html,fetch)
        fetch.assert_not_called();parse.assert_not_called()
        self.assertEqual(set(result["pce_previous"]),{"monthly","core_monthly"})

    def test_attachment_unavailable_retains_real_current_and_verified_monthly_comparisons(self):
        row=item()
        def fail(_):raise OSError("fixture unavailable")
        result=enrich(row,lambda _:row["summary"]+f' <a href="{XLS}">table</a>',fail)
        text,missing=details(result)
        self.assertFalse(missing)
        self.assertIn("本次 **+3.6%**\n前值 暫缺",text)
        self.assertIn("本次 **+0.5%**\n前值 +0.3%",text)
        self.assertNotIn("變化 +3.6",text)

    def test_workbook_without_adjacent_year_is_not_previous(self):
        # Preserve workbook layout and numbers, replace only explicit period labels.
        src=zipfile.ZipFile(io.BytesIO(self.book));buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as dst:
            for name in src.namelist():
                data=src.read(name)
                if name=="xl/sharedStrings.xml":data=data.replace(b"2026M08",b"2025M08")
                dst.writestr(name,data)
        y,m,values,_=pce_values(item())
        self.assertEqual(workbook_previous(buf.getvalue(),y,m,values),{})

    def test_bad_book_is_not_zero_and_no_comparison_is_fabricated(self):
        result=self.enriched(book=b"not an xlsx")
        self.assertEqual(set(result["pce_previous"]),{"monthly","core_monthly"})
        self.assertNotIn("annual",result["pce_previous"])

    def test_gdp_labels_quarters_and_does_not_compare_same_quarter_estimates(self):
        row=item();row["rule"]={"key":"gdp","name":"GDP"}
        row["summary"]="Real gross domestic product (GDP) increased at an annual rate of 3.4 percent in the third quarter of 2026, according to the advance estimate. In the second quarter, real GDP increased 2.2 percent. Prior estimate of this quarter was 9.9 percent."
        text,missing=details(row)
        self.assertFalse(missing)
        for value in ("2026年第3季（初估）","本次 **+3.4%**（2026年第3季）",
                      "前值 +2.2%（2026年第2季）","變化 +1.2 個百分點","並非全年成長率"):
            self.assertIn(value,text)
        self.assertNotIn("9.9%",text)

    def test_comparison_unknown_and_zero_are_distinct_and_precision_is_displayed(self):
        self.assertNotIn("變化",comparison("test",1,None))
        self.assertIn("前值 0.0%",comparison("test",1,0))
        self.assertIn("變化 +0.2 個百分點",comparison("test",.6485,.39))
        self.assertNotIn("-0.0",comparison("test",.02,.03))
        self.assertNotIn("變化",comparison("test",float("nan"),.3))

