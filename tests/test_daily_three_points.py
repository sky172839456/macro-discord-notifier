import unittest
from datetime import datetime, timezone, timedelta
from market_brief_v2 import daily_top_three, build_card

class DailyThreePointsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,11,7,0,tzinfo=timezone.utc)
    def test_checked_prices_and_distinct_etf_dates_remain_explicit(self):
        data={'crypto':{'BTC':{'price':100,'change_24h':1,'source':'Bitget','updated_at':self.now.isoformat(),'quote_currency':'USDT'}},
              'etf':{'date':self.now-timedelta(days=1),'net_flow_musd':120,'partial':True},
              'eth_etf':{'date':self.now-timedelta(days=2),'net_flow_musd':-30}}
        text=daily_top_three(data,None,[],self.now)
        self.assertIn('100.00 USDT',text);self.assertIn('ETH價格或漲跌待確認',text)
        self.assertIn('11/06 BTC',text);self.assertIn('11/05 ETH',text);self.assertIn('初值',text)
        self.assertEqual(text.count('01｜'),1);self.assertEqual(text.count('02｜'),1);self.assertEqual(text.count('03｜'),1)
    def test_stale_and_disputed_values_never_become_headline_facts(self):
        data={'crypto':{'BTC':{'price':99999,'change_24h':8,'source':'Bitget','updated_at':(self.now-timedelta(hours=1)).isoformat()}},
              'etf':{'date':self.now,'net_flow_musd':99999,'source_issue':'來源分項與合計不符'}}
        text=daily_top_three(data,None,[],self.now,'source unavailable')
        self.assertNotIn('99,999',text);self.assertNotIn('+8.00%',text);self.assertIn('ETF資料待核對',text);self.assertIn('未完整確認',text)
    def test_daily_gets_three_points_without_changing_weekly_or_detail_sections(self):
        daily=build_card('daily',self.now,None,None,[],None,{})
        weekly=build_card('weekly',self.now,None,None,[],None,{})
        self.assertIn('先看三件事',daily['description']);self.assertNotIn('先看三件事',weekly['description'])
        self.assertEqual(len(daily['fields']),6);self.assertLess(len(daily['description']),4096)
