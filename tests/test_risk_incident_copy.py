import copy,json,unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch
import risk_notifier as risk
import slim_risk
import crypto_news_notifier as news

class RiskIncidentCopyTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,2,tzinfo=timezone.utc)
  self.api=SimpleNamespace(clean_source_text=risk.clean_source_text,
   translate_title=lambda _: '服務事件更新',translate_status=risk.translate_status)
 def text(self,card):return json.dumps(card,ensure_ascii=False)
 def test_bybit_ongoing_does_not_claim_investigation(self):
  payload={'retCode':0,'result':{'list':[{'id':'fixture','title':'Service incident',
    'state':'ongoing','maintainType':3,'env':1,'begin':'1793574000000','end':'1793577600000'}]}}
  with patch.object(risk,'get_json',return_value=payload):row=risk.bybit_incidents()[0]
  self.assertEqual(row['status'],'ongoing')
  card=slim_risk.incident_card(self.api,'Bybit',row,self.now)
  self.assertIn('進行中',self.text(card));self.assertNotIn('調查中',self.text(card))
  self.assertNotIn('官方未提供詳細影響範圍',self.text(card))
 def test_missing_status_is_unknown_not_investigating(self):
  card=slim_risk.incident_card(self.api,'Coinbase',{'name':'Service incident'},self.now)
  self.assertIn('狀態未確認',self.text(card));self.assertNotIn('調查中',self.text(card))
 def test_missing_update_time_is_payload_limit_and_query_time_visible(self):
  card=slim_risk.incident_card(self.api,'Bybit',{'status':'ongoing','title':'Service incident','endTime':'1999999999999'},self.now)
  text=self.text(card)
  self.assertIn('此狀態資料未列更新時間',text);self.assertIn('本次查詢',text)
  self.assertNotIn('1999999999999',text)
 def test_explicit_component_scope_and_state_are_preserved(self):
  row={'status':'identified','name':'Withdrawals unavailable','components':[
   {'name':'ETH Withdrawals','status':'major_outage'},{'name':'BTC Deposits','status':'operational'}]}
  before=copy.deepcopy(row)
  card=slim_risk.incident_card(self.api,'Coinbase',row,self.now);text=self.text(card)
  for term in ('ETH','BTC','提款','充值','重大中斷','正常'):self.assertIn(term,text)
  self.assertEqual(row,before)
 def test_latest_source_update_time_can_be_used_without_inventing_it(self):
  row={'status':'monitoring','name':'Service incident','incident_updates':[{
   'body':'A fictional source update.','created_at':'2026-11-01T23:50:00Z'}]}
  with patch.object(news,'translate_text',return_value='虛構來源更新。'):
   text=self.text(slim_risk.incident_card(self.api,'Coinbase',row,self.now))
  self.assertIn('2026/11/02 07:50',text);self.assertNotIn('此狀態資料未列更新時間',text)
 def test_resolved_incident_does_not_claim_entire_platform_restored(self):
  card=slim_risk.incident_card(self.api,'Coinbase',{'status':'resolved','name':'Service incident'},self.now)
  self.assertIn('事件已解決',card['title']);self.assertNotIn('服務已恢復',card['title'])
 def test_bybit_existing_service_product_and_expected_end_are_used(self):
  row={'title':'Service incident','status':'ongoing','state':'ongoing','serviceTypes':[2,5],
   'product':[1,2],'begin':'1793574000000','end':'1793577600000'}
  text=self.text(slim_risk.incident_card(self.api,'Bybit',row,self.now))
  for term in ('HTTP交易','行情資料','期貨','現貨','事件開始','預計結束'):self.assertIn(term,text)
  self.assertIn('此狀態資料未列更新時間',text);self.assertNotIn('實際結束',text)
 def test_unknown_scope_codes_are_not_mapped_to_known_services(self):
  text=self.text(slim_risk.incident_card(self.api,'Bybit',{'status':'ongoing','serviceTypes':[99],'product':[99]},self.now))
  self.assertIn('未識別服務代碼',text);self.assertIn('未識別產品代碼',text)
  self.assertNotIn('HTTP交易',text);self.assertNotIn('現貨',text)
 def test_long_component_list_has_explicit_remaining_count_not_cut_line(self):
  row={'status':'identified','components':[{'name':'Fictional Service '+str(i)+'x'*35,'status':'major_outage'} for i in range(50)]}
  card=slim_risk.incident_card(self.api,'Coinbase',row,self.now)
  field=next(f for f in card['fields'] if f['name']=='公告列出的服務')
  self.assertLessEqual(len(field['value']),1024);self.assertIn('另有',field['value']);self.assertIn('請查看官方清單',field['value'])

if __name__=='__main__':unittest.main()
