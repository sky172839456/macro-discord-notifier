import unittest
from datetime import datetime, timezone, timedelta
from market_brief_v2 import daily_top_three, build_card

# 2026-11-15 本人確認：「先看三件事」改挑變化最大的三項，不列「待確認／尚未列出」空項。
class DailyThreePointsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,11,7,0,tzinfo=timezone.utc)
    def test_checked_prices_and_distinct_etf_dates_remain_explicit(self):
        data={'crypto':{'BTC':{'price':100,'change_24h':1,'source':'Bitget','updated_at':self.now.isoformat(),'quote_currency':'USDT'}},
              'etf':{'date':self.now-timedelta(days=1),'net_flow_musd':120,'partial':True},
              'eth_etf':{'date':self.now-timedelta(days=2),'net_flow_musd':-30}}
        text=daily_top_three(data,None,[],self.now)
        self.assertIn('100.00 USDT',text);self.assertNotIn('待確認',text)
        self.assertIn('11/06 BTC',text);self.assertIn('11/05 ETH',text);self.assertIn('初值',text)
        self.assertEqual(text.count('01｜'),1);self.assertEqual(text.count('02｜'),1);self.assertNotIn('03｜',text)
    def test_stale_and_disputed_values_never_become_headline_facts(self):
        data={'crypto':{'BTC':{'price':99999,'change_24h':8,'source':'Bitget','updated_at':(self.now-timedelta(hours=1)).isoformat()}},
              'etf':{'date':self.now,'net_flow_musd':99999,'source_issue':'來源分項與合計不符'}}
        text=daily_top_three(data,None,[],self.now,'source unavailable')
        self.assertNotIn('99,999',text);self.assertNotIn('+8.00%',text);self.assertNotIn('ETF｜',text);self.assertIn('未完整確認',text)
    def test_zero_total_with_unlisted_funds_is_not_a_zero_headline(self):
        # Live 11/10-11/12: summary said 合計0美元 while the ETF section said incomplete.
        data={'etf':{'date':self.now,'net_flow_musd':0,'unreported_components':3},
              'eth_etf':{'date':self.now,'net_flow_musd':-39.1,'unreported_components':2}}
        text=daily_top_three(data,None,[],self.now)
        self.assertNotIn('BTC 合計0美元',text);self.assertNotIn('尚未列出',text)
        self.assertIn('ETH 淨流出3,910萬美元（暫定）',text);self.assertNotIn('3,910.0萬',text)
        complete={'etf':{'date':self.now,'net_flow_musd':0}}
        self.assertIn('11/07 BTC 合計0美元',daily_top_three(complete,None,[],self.now))
    def test_daily_gets_three_points_without_changing_weekly_or_detail_sections(self):
        daily=build_card('daily',self.now,None,None,[],None,{})
        weekly=build_card('weekly',self.now,None,None,[],None,{})
        self.assertIn('先看',daily['description']);self.assertNotIn('先看三件事',weekly['description'])
        self.assertEqual(len(daily['fields']),6);self.assertLess(len(daily['description']),4096)
    def test_biggest_changes_are_picked_first(self):
        fresh=self.now.isoformat()
        data={'crypto':{'BTC':{'price':63618.51,'change_24h':-6.47,'source':'Bitget','updated_at':fresh,'quote_currency':'USDT'},
                        'ETH':{'price':1745.33,'change_24h':-9.01,'source':'Bitget','updated_at':fresh,'quote_currency':'USDT'}},
              'sentiment':{'value':13,'previous_value':20,'classification':'Extreme Fear','timestamp':fresh},
              'derivatives':{'BTC':{'oi_change_1d':-2.57,'timestamp':fresh,'funding_rate':-0.0009,'rate_timestamp':fresh},
                             'ETH':{'oi_change_1d':-0.47,'timestamp':fresh,'funding_rate':-0.0069,'rate_timestamp':fresh}},
              'etf':{'date':self.now-timedelta(days=2),'net_flow_musd':-185},'eth_etf':{'date':self.now-timedelta(days=2),'net_flow_musd':2.3}}
        text=daily_top_three(data,None,[],self.now)
        self.assertIn('先看三件事',text)
        self.assertTrue(text.split('\n')[1].startswith('01｜價格'))
        self.assertIn('02｜情緒',text);self.assertIn('較前一日 -7.00分',text)
        self.assertIn('03｜資金費率',text);self.assertIn('空方付多方',text)
        self.assertNotIn('未平倉｜',text)  # -2.57% 未達門檻，也沒有排進前三
    def test_quiet_day_falls_back_to_fixed_items(self):
        fresh=self.now.isoformat()
        data={'crypto':{'BTC':{'price':100,'change_24h':0.4,'source':'Bitget','updated_at':fresh}},
              'sentiment':{'value':50,'previous_value':49,'classification':'Neutral','timestamp':fresh},
              'etf':{'date':self.now,'net_flow_musd':12}}
        text=daily_top_three(data,None,[],self.now)
        self.assertIn('01｜價格',text);self.assertIn('02｜ETF',text);self.assertNotIn('情緒',text)

if __name__ == '__main__':
    unittest.main()
