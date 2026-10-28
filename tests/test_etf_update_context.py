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
        for expected in ('等候數據更新','交易日：10/14','查詢時間：10/15 08:00（台灣）','來源尚有基金未列數值','不代表資金沒有流入或流出','https://farside.co.uk/btc/'): self.assertIn(expected,text)
        self.assertEqual(text.count('交易日：'),1)
        self.assertEqual(text.count('查詢時間：'),1)
        self.assertEqual(text.count('來源尚有基金未列數值'),1)
        self.assertNotIn('0美元',text)
        self.assertNotIn('分項含',text)
        self.assertNotIn('資料缺少',text)
        self.assertNotIn('資料狀態',text)
        self.assertNotIn('淨流入0',text)

    def test_fully_numeric_row_does_not_claim_dash_cells_or_finality(self):
        row=source.parse_farside_latest(self.html.replace('<td>-</td>','<td>2.2</td>'))
        self.assertEqual(row['unreported_components'],0)
        text=brief.etf_lines({'etf':row},False)
        self.assertNotIn('分項含',text)
        self.assertNotIn('部分基金未列數值',text)
        self.assertIn('非最終結果',text)

    def test_complete_explicit_zero_remains_a_number(self):
        row=source.parse_farside_latest(self.html.replace('<td>-</td>','<td>0.0</td>'))
        text=brief.etf_lines({'etf':row,'eth_etf':row},False)
        self.assertEqual(text.count('來源目前合計 **0美元**'),2)
        self.assertNotIn('等候數據更新',text)

    def test_incomplete_zero_does_not_hide_other_asset_flow(self):
        pending=source.parse_farside_latest(self.html)
        ready=source.parse_farside_latest(self.html.replace('<td>-</td>','<td>(18.8)</td>').replace('<td>0.0</td></tr>','<td>(18.8)</td></tr>'))
        text=brief.etf_lines({'etf':pending,'eth_etf':ready},False)
        self.assertIn('**BTC ETF**\n**等候數據更新**',text)
        self.assertIn('淨流出1,880萬美元',text)
        self.assertNotIn('0美元',text)
        self.assertEqual(text.count('交易日：'),1)

    def test_weekly_incomplete_zero_does_not_claim_a_complete_flat_week(self):
        row=source.parse_farside_week(self.html)
        text=brief.etf_lines({'weekly_btc_etf':row,'weekly_eth_etf':row},True)
        self.assertIn('統計期間：',text)
        self.assertIn('等候數據更新',text)
        self.assertNotIn('0美元',text)

    def test_different_trade_dates_and_query_times_stay_with_each_asset(self):
        from datetime import date, timedelta
        btc={'date':date(2026,10,14),'net_flow_musd':0,'retrieved_at':self.now.isoformat()}
        eth={'date':date(2026,10,13),'net_flow_musd':-18.8,'retrieved_at':(self.now+timedelta(minutes=1)).isoformat()}
        text=brief.etf_lines({'etf':btc,'eth_etf':eth},False)
        self.assertIn('交易日：10/14',text);self.assertIn('交易日：10/13',text)
        self.assertIn('查詢時間：10/15 08:00',text);self.assertIn('查詢時間：10/15 08:01',text)
        self.assertIn('淨流出1,880萬美元',text)

    def test_missing_asset_is_not_zero_and_missing_query_time_not_invented(self):
        from datetime import date
        text=brief.etf_lines({'etf':{'date':date(2026,10,14),'net_flow_musd':0}},False)
        self.assertNotIn('查詢時間：',text)
        self.assertIn('**ETH ETF**\n資料暫缺',text)
        self.assertEqual(text.count('0美元'),1)

    def test_weekly_period_counts_and_shared_notice_are_preserved(self):
        row=source.parse_farside_week(self.html.replace('<td>0.0</td></tr>','<td>2.2</td></tr>'))
        row['retrieved_at']=self.now.isoformat()
        text=brief.etf_lines({'weekly_btc_etf':row,'weekly_eth_etf':row},True)
        self.assertIn('統計期間：',text);self.assertIn('個交易日',text)
        self.assertEqual(text.count('統計期間：'),1)
        self.assertEqual(text.count('部分基金未列數值'),1)

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
