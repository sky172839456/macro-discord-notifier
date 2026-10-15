import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import market_brief_data as source
import market_brief_v2 as brief
from config import EVENT_RULES


class EtfUpdateContextTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,15,0,tzinfo=timezone.utc)
        self.html = '<table><tr><td>14 Oct 2026</td><td>-</td><td>0.0</td><td>0.0</td></tr></table>'

    def test_dash_component_does_not_change_explicit_zero_total(self):
        row = source.parse_farside_latest(self.html)
        self.assertEqual(row['net_flow_musd'],0)
        self.assertEqual(row['unreported_components'],1)

    def test_total_dash_still_raises_instead_of_zero_or_old_day_fallback(self):
        for missing in ('-', '', 'N/A'):
            html = '<tr><td>13 Oct 2026</td><td>100</td></tr><tr><td>14 Oct 2026</td><td>'+missing+'</td></tr>'
            with self.subTest(missing=missing), self.assertRaises(ValueError): source.parse_farside_latest(html)

    def test_retrieval_time_is_captured_by_fetcher_not_fabricated_from_trade_date(self):
        with patch.object(source,'get_text',return_value=self.html): row=source.etf_flow_snapshot()
        self.assertIsNotNone(brief.instant(row['retrieved_at']))
        self.assertEqual(row['date'].day,14)

    def test_partial_row_has_specific_quiet_context_without_generic_error_banner(self):
        row=source.parse_farside_latest(self.html);row['retrieved_at']=self.now.isoformat()
        text=brief.etf_lines({'etf':row,'eth_etf':row},False)
        for expected in ('目前已列合計0美元','查詢：10/15 08:00','分項含「—」','來源持續更新','非最終結算','Farside'): self.assertIn(expected,text)
        self.assertNotIn('資料缺少',text)
        self.assertNotIn('資料狀態',text)
        self.assertNotIn('淨流入0',text)

    def test_fully_numeric_row_does_not_claim_dash_cells_or_finality(self):
        row=source.parse_farside_latest(self.html.replace('<td>-</td>','<td>2.2</td>'))
        self.assertEqual(row['unreported_components'],0)
        text=brief.etf_lines({'etf':row},False)
        self.assertNotIn('分項含',text)
        self.assertIn('非最終結算',text)

    def test_weekly_counts_unreported_cells_and_preserves_total(self):
        row=source.parse_farside_week(self.html.replace('<td>0.0</td></tr>','<td>2.2</td></tr>'))
        self.assertEqual(row['net_flow_musd'],2.2)
        self.assertEqual(row['unreported_components'],1)
        with patch.object(source,'get_text',return_value=self.html): fetched=source.weekly_etf_snapshot(source.FARSIDE_BTC)
        self.assertIn('retrieved_at',fetched)

    def test_focus_events_link_to_each_responsible_agency(self):
        events=[{'time':self.now,'rule':next(r for r in EVENT_RULES if r['key']==key)} for key in ('ppi','retail','claims')]
        text=brief.events_lines(events,self.now,None,False)
        for event in events: self.assertIn(event['rule']['source'],text)
        self.assertEqual(text.count('[官方來源]'),3)
        self.assertNotIn('[官方行事曆]',text)

    def test_focus_budget_never_cuts_a_source_link(self):
        events=[{'time':self.now,'rule':next(r for r in EVENT_RULES if r['key']==key)} for key in ('ppi','retail','claims')]
        text=brief.events_lines(events,self.now,None,False,budget=300)
        self.assertLessEqual(len(text),300)
        self.assertIn('另有',text)
        self.assertEqual(text.count('[官方來源]('),text.count(')'))


if __name__=='__main__': unittest.main()
