import unittest
import os
from unittest.mock import patch
import news_auto_recovery as auto
import news_copy_terms as terms
import notification_quality as quality

CANADA="Canada’s Draft Stablecoin Rules Cap Redemption Fees at 1% and Ban Yield"
FED='Bitcoin Dips Below $80,000 Ahead of Fed Decision, Midterms'
KEYSTONE='Bitcoin Wallet Maker Keystone Pulls Devices as Stolen Key Opens Door to Fakes'

class LaunchTermsTests(unittest.TestCase):
 def test_actual_canada_headline_preserves_draft_fee_cap_and_holder_interest(self):
  value=auto.checked_copy(CANADA,'加拿大穩定幣規則草案上限贖回費為 1 ％和禁令收益率')
  self.assertIn('草案',value);self.assertIn('贖回費上限1%',value);self.assertIn('持幣利息',value)
  self.assertNotIn('禁令收益率',value)

 def test_actual_fed_headline_keeps_two_distinct_events(self):
  value=auto.checked_copy(FED,'中期聯準會決定前，Bitcoin 跌破80,000美元')
  self.assertIn('聯準會決策與期中選舉前',value)
  self.assertIn('8萬美元',value)

 def test_actual_device_pull_is_not_market_demand_pull(self):
  value=auto.checked_copy(KEYSTONE,'比特幣錢包製造商 Keystone 拉動設備，被盜金鑰打開了假貨大門')
  self.assertIn('撤回',value);self.assertIn('偽造風險',value);self.assertNotIn('拉動',value)

 def test_changed_figures_are_not_repaired_away(self):
  for original,wrong in ((CANADA,'加拿大穩定幣草案贖回費上限2%'),(FED,'比特幣在聯準會決策前跌破70,000美元')):
   with self.subTest(original=original),self.assertRaises(ValueError):auto.checked_copy(original,wrong)

 def test_scope_does_not_replace_different_sources_or_new_policy_status(self):
  self.assertIn('已通過',auto.checked_copy('Canada approved stablecoin rules','加拿大已通過穩定幣規則'))
  self.assertIn('中期',auto.checked_copy('Midterm bond outlook','中期債券展望'))
  self.assertIn('帶動',auto.checked_copy('Device demand pulls sales higher','設備需求帶動銷售上升'))

 def test_same_source_changed_status_still_preserves_negation(self):
  with self.assertRaises(ValueError):
   auto.checked_copy('Keystone denies pulling devices after stolen key report','Keystone 撤回設備，金鑰遭竊')

 def test_old_cached_headline_is_repaired_at_render_without_mutation(self):
  row={'title':FED,'title_zh':'中期聯準會決定前，Bitcoin 跌破80,000美元','summary':''}
  before=dict(row)
  with patch.dict(os.environ,{'NEWS_AUTO_RECOVERY':'1'}):
   self.assertIn('期中選舉',quality.headline(row))
  self.assertEqual(row,before)

 def test_changed_source_number_or_decision_does_not_use_fixed_headline(self):
  bad='保留原待核譯文'
  for original in (CANADA.replace('1%','2%'),FED.replace('$80,000','$70,000'),
                   FED.replace('Dips Below','Rises Above'),KEYSTONE.replace('Pulls','Plans to Pull')):
   with self.subTest(original=original):self.assertEqual(terms.repair_translation(original,bad),bad)

if __name__=='__main__':unittest.main()
