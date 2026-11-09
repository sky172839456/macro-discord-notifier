"""Synthetic editorial fixtures; no assertion of a real campaign or release."""
import copy
import json
import os
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch
import material_inbox as m
from material_share_value import assess,activity_kind
from material_quality import selection
from material_editorial import review

class ShareValue(unittest.TestCase):
    now=datetime(2026,11,9,2,tzinfo=timezone.utc)
    def row(self,title,summary,topic=None,**extra):
        row=dict(title=title,summary=summary,url='https://example.com/story',source='Example',official=False,published=self.now)
        row.update(extra)
        row['material_topic']=topic or m.topic(row)
        return row
    def connector(self):
        return self.row('TradingView adds an MCP server for Claude and ChatGPT',
            'Users on Essential and other paid plans can query market data and manage watchlists and alerts through MCP in beta, with OAuth permissions.')
    def campaign(self):
        return self.row('Bitget Launchpool introduces Project Example: stake BGB',
            'Eligible users who complete KYC can stake BGB from Nov. 10 to Nov. 17. The minimum is 10 BGB and redemption is available during the 7 days.')
    def test_concrete_connector_and_conditions_have_reader_value(self):
        row=self.connector();before=copy.deepcopy(row)
        self.assertIsNone(selection(row,self.now))
        result=assess(row)
        self.assertEqual(result['route'],'capability')
        self.assertIn('觀察清單',result['tasks']);self.assertIn('提醒',result['tasks'])
        self.assertEqual(row,before)
        text=review(row,self.now)['concept']
        self.assertIn('觀察清單',text);self.assertIn('權限',text)
    def test_launchpool_is_business_and_keeps_product_boundaries(self):
        row=self.campaign()
        self.assertEqual(row['material_topic'],'business')
        self.assertIsNone(selection(row,self.now))
        text=json.dumps(m.card(row,self.now),ensure_ascii=False)
        for value in ('活動／產品條件','資格','時程','資金限制','不承諾配發或收益','IPO認購'):
            self.assertIn(value,text)
        self.assertNotIn('這次AI更新',text)
    def test_subscription_not_mislabeled_launchpool_or_company_endorsement(self):
        row=self.row('Bitget opens IPO subscription for Example rToken',
            'Eligible users complete KYC and subscribe with USDT from Nov. 10 to Nov. 17, with a maximum allocation and a 30 days holding condition.')
        self.assertEqual(activity_kind(row['title']),'subscription')
        self.assertEqual(row['material_topic'],'business')
        self.assertIsNone(selection(row,self.now))
        self.assertIn('發行關係',review(row,self.now)['concept'])
    def test_common_gate_rejects_generic_copy_in_every_category(self):
        for kind in m.ANGLES:
            row=self.row('A new major update for one billion users',
                'The company says this is a major breakthrough that will transform the industry and create enormous value for everyone.',kind)
            with self.subTest(kind=kind):self.assertIsNotNone(selection(row,self.now))
    def test_recent_official_high_star_hype_does_not_override_usefulness(self):
        row=self.row('New AI breakthrough launches for one billion users',
            'One billion users may benefit from the biggest launch; the new product changes everything for customers.', 'ai',official=True)
        self.assertGreaterEqual(review(row,self.now)['stars'],3)
        self.assertIsNotNone(selection(row,self.now))
    def test_funding_and_ceo_change_are_not_automatically_shareable(self):
        for title in ('Company appoints a new CFO','AI startup raises one billion dollars'):
            row=self.row(title,'The company confirmed a new appointment and a billion dollars of interest, with more details expected later.','business')
            self.assertIsNotNone(selection(row,self.now))
    def test_bare_campaign_promotion_and_keyword_connection_are_held(self):
        for title,summary in (
            ('Bitget launches a new Launchpool','Stake now and get amazing rewards from the latest project; everyone is talking about the opportunity.'),
            ('TradingView adds MCP support','It supports Claude and ChatGPT and offers exciting new experiences for traders around the world.')):
            self.assertIsNotNone(selection(self.row(title,summary),self.now))
    def test_service_access_change_has_scope_and_timeline(self):
        row=self.row('Binance changes withdrawal fees and closes some European accounts',
            'Affected accounts in Spain and France are scheduled to close on Dec. 31. Users can withdraw before the withdrawal fee applies.')
        self.assertIsNone(selection(row,self.now))
    def test_private_security_requires_impact_and_explainable_detail(self):
        vague=self.row('Company confirms a security incident','The company is investigating a major incident and says that more information will be provided soon.','security')
        self.assertIsNotNone(selection(vague,self.now))
        concrete=self.row('Payment service discloses customer data breach',
            'The exposed card numbers and home address are linked to affected accounts, increasing the risk of targeted scams. Users should check the notice.','security')
        self.assertIsNone(selection(concrete,self.now))
    def test_research_requires_a_result_and_method_not_just_report(self):
        good=self.row('Researchers publish a study of offline navigation',
            'A controlled experiment with a sample of 100 participants reduced errors by 20% using an offline benchmark; the study describes its limitations.','research')
        self.assertIsNone(selection(good,self.now))
        bad=self.row('New AI report alarms researchers','The report raises significant questions about the future of AI and calls for more work to understand what could happen.','research')
        self.assertIsNotNone(selection(bad,self.now))
    def test_fun_does_not_need_finance_but_needs_explanation(self):
        good=self.row('A museum opens an unusual experiment',
            'The interactive exhibit runs offline on solar power for 40 days, explaining how visitors can test the mechanism without the internet.','interesting')
        self.assertIsNone(selection(good,self.now))
        thin=self.row('A robot learns to cook','The funny robot video is trending everywhere and people are excited to see what comes next.','interesting')
        self.assertIsNotNone(selection(thin,self.now))
    def test_prototype_measurement_and_stage_can_be_a_good_story(self):
        row=self.row('Company unveils flying car prototype',
            'The prototype carried 2 participants for 15 minutes during a controlled experiment, and the company says commercial certification is not yet available.','innovation')
        self.assertIsNone(selection(row,self.now))
    def test_time_numbers_without_takeaway_do_not_pass(self):
        row=self.row('Elon Musk shares his plans','The event lasted 30 days and drew 100 participants, while supporters said it was a major moment for the company.','interesting')
        self.assertGreaterEqual(len(assess(row)['details']),2)
        self.assertIsNotNone(selection(row,self.now))
    def test_official_flag_neither_grants_admission_nor_confirms_claims(self):
        row=self.connector();self.assertEqual(assess(row),assess({**row,'official':True}))
        text=json.dumps(m.card({**row,'official':True},self.now),ensure_ascii=False)
        self.assertIn('不等於獨立實測',text)
    def test_queued_low_value_is_held_and_confirmed_history_not_reopened(self):
        old=self.row('OpenAI launches a new tool','The company announced a new tool for one billion people and expects users to love the experience.','ai')
        old.update(status='queued',collected_at=self.now.isoformat(),published=self.now.isoformat(),material_key=m.key(old))
        done={**old,'url':'https://example.com/already-sent','status':'notified','notified_at':self.now.isoformat()}
        state={'seen':{'member':'keep'},'material_inbox_v1':{'started_at':(self.now-timedelta(hours=1)).isoformat(),'items':[old,done]}}
        send=Mock();before=copy.deepcopy(done)
        with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'https://discord.com/api/webhooks/123/TEST'}):
            count=m.run([],state,self.now,fetch=Mock(side_effect=OSError()),send=send,persist=Mock(),verify=Mock())
        self.assertEqual(count,0);send.assert_not_called()
        self.assertEqual(old['status'],'quality_hold');self.assertEqual(done,before)
        self.assertEqual(state['seen'],{'member':'keep'})
    def test_strict_gate_allows_useful_candidate_without_forcing_a_quota(self):
        bad=self.row('OpenAI launches a new tool','The tool is exciting and developers say the future is bright, but no use cases or conditions are available.','ai')
        good=self.connector();good['url']='https://example.com/connector'
        state={'seen':{'member':'keep'},'material_inbox_v1':{'started_at':(self.now-timedelta(hours=1)).isoformat(),'items':[]}}
        send=Mock(return_value='123')
        with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'https://discord.com/api/webhooks/123/TEST'}):
            count=m.run([bad,good],state,self.now,fetch=Mock(side_effect=OSError()),send=send,persist=Mock(),verify=Mock())
        self.assertEqual(count,1);self.assertEqual(send.call_count,1)
        self.assertEqual(sum(i['status']=='quality_hold' for i in state['material_inbox_v1']['items']),1)
        self.assertEqual(state['seen'],{'member':'keep'})
