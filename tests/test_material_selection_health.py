import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import material_inbox as m
import material_quality as q
import realtime_health as h
from material_editorial import review
from notification_quality import checked_translation

STARTUP = "America's newest small business owners with no employees are off to a hot start in AI era"
POLITICS = 'Democrat shaping AI policy bought chip stocks despite backing congressional trading ban'

class SelectionHealth(unittest.TestCase):
    now = datetime(2026,11,8,9,tzinfo=timezone.utc)
    def row(self, title=STARTUP, **extra):
        row = dict(id='item',title=title,summary='New small business formation is rising for owners who can grow with AI serving in finance, marketing and design roles, eliminating the need for hiring.',
            published=self.now.isoformat(),url='https://example.com/story',source='Media',official=False,material_topic='ai')
        row.update(extra)
        return row
    def state(self):
        return {'seen':{'public':'keep'},'material_inbox_v1':{'started_at':(self.now-timedelta(hours=1)).isoformat(),'items':[]}}
    def run_box(self, rows, state, **extra):
        args=dict(fetch=Mock(side_effect=OSError()),send=Mock(return_value='123'),persist=Mock(),verify=Mock())
        args.update(extra)
        with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'https://discord.com/api/webhooks/123/TEST'}):
            return m.run(rows,state,self.now,**args)
    def healthy(self):
        state=self.state();box=state['material_inbox_v1']
        box['selection_audit']={'completed_at':self.now.isoformat(),'decisions':[]}
        box['source_status']=[{'source':'Official','readable':True}]
        state['content_source_audit']={'checked_at':self.now.isoformat(),'sources':[{'source':'Media','count':4,'error':None}]}
        return state
    def test_startup_and_politics_override_ai_without_inventing_findings(self):
        for title,topic,needle in ((STARTUP,'business','財務、行銷、設計'),(POLITICS,'policy','持股揭露')):
            row=self.row(title);before=copy.deepcopy(row)
            self.assertEqual(m.topic(row),topic)
            text=json.dumps(m.card(row,self.now),ensure_ascii=False)
            self.assertIn(needle,text)
            self.assertNotIn('這次AI更新',text)
            self.assertIn('★',text)
            self.assertEqual(row,before)
        text=review(self.row(POLITICS),self.now)['concept']
        self.assertIn('不由持股推定違法',text)
    def test_unknown_ai_task_and_two_star_commentary_are_held(self):
        row=self.row('AI is a hot topic',summary='Investors continue to talk about artificial intelligence and the future.')
        row['material_topic']=m.topic(row)
        self.assertEqual(q.selection(row,self.now),'no_concrete_ai_change')
        row=self.row('CZ says crypto needs better education',summary='The speaker discusses education and his hopes for the future.',material_topic='interesting')
        self.assertEqual(q.selection(row,self.now),'low_editorial_value')
    def test_high_stars_do_not_overrule_missing_source_detail(self):
        row=self.row('New AI breakthrough launches for one billion users',summary='More details later.')
        self.assertEqual(q.selection(row,self.now),'thin_source')
    def test_new_capability_and_fun_story_both_survive(self):
        for row in (self.row('Existing editor adds MCP support',summary='The MCP server connects files and tasks in a limited preview, replacing manual workflow steps.'),
                    self.row('Museum unveils unexpected experiment',summary='The unexpected experiment lasted 40 days and visitors can use its interactive exhibit.',material_topic='interesting')):
            self.assertIsNone(q.selection(row,self.now))
    def test_security_evidence_priority_is_not_reduced_by_star_threshold(self):
        self.assertIsNone(q.selection(self.row('Platform hacked; withdrawals paused',summary='',material_topic='security'),self.now))
    def test_exact_translations_do_not_leak_to_changed_source(self):
        self.assertIn('民主黨議員',checked_translation(POLITICS,'民主黨購買晶片股'))
        from news_copy_terms import repair_translation
        self.assertEqual(repair_translation(POLITICS.replace('bought','denies buying'),'原譯'),'原譯')
    def test_quality_hold_keeps_evidence_seen_and_does_not_send_or_reopen_unknown(self):
        state=self.state();send=Mock(return_value='123')
        row=self.row('AI is a hot topic',summary='More details later.')
        self.assertEqual(self.run_box([row],state,send=send),0)
        send.assert_not_called()
        item=state['material_inbox_v1']['items'][0]
        self.assertEqual(item['status'],'quality_hold')
        self.assertEqual(item['quality_hold_reason'],'thin_source')
        item['status']='delivery_unknown'
        self.assertEqual(self.run_box([row],state,send=send),0)
        self.assertEqual(item['status'],'delivery_unknown')
        self.assertEqual(state['seen'],{'public':'keep'})
    def test_later_summary_can_release_unsent_hold_without_duplicate(self):
        state=self.state();row=self.row('Existing editor adds MCP support',summary='More details later.')
        self.assertEqual(self.run_box([row],state),0)
        row['summary']='The MCP server connects files and tasks in a limited preview, replacing manual workflow steps.'
        self.assertEqual(self.run_box([row],state),1)
        self.assertEqual(len(state['material_inbox_v1']['items']),1)
        self.assertEqual(self.run_box([row],state),0)
    def test_source_candidate_missing_from_queue_is_detected_even_when_queue_zero(self):
        state=self.healthy();state['material_inbox_v1']['selection_audit']['decisions']=[{'key':'lost','decision':'accepted'}]
        text=json.dumps(q.inspect(state,self.now),ensure_ascii=False)
        self.assertIn('未進待送紀錄',text)
    def test_broad_recall_probe_exposes_unclassified_source_candidates(self):
        state=self.healthy();state['material_inbox_v1']['selection_audit']['decisions']=[{'decision':'no_topic','recall_hint':True}]
        self.assertIn('被排除待複核',json.dumps(q.inspect(state,self.now),ensure_ascii=False))
    def test_source_failure_unknown_and_overdue_are_visible(self):
        state=self.healthy();box=state['material_inbox_v1']
        box['source_status'][0]['readable']=False
        box['items']=[self.row(status='queued',collected_at=(self.now-timedelta(hours=2)).isoformat()), self.row(status='delivery_unknown')]
        text=json.dumps(q.inspect(state,self.now),ensure_ascii=False)
        for needle in ('來源讀取待核','超過60分鐘','不自動重送'):
            self.assertIn(needle,text)
    def test_old_sent_misclassification_remains_visible_without_rewriting_card(self):
        state=self.healthy();state['material_inbox_v1']['items']=[self.row(POLITICS,status='notified',notified_at=self.now.isoformat())]
        before=copy.deepcopy(state)
        text=json.dumps(q.inspect(state,self.now),ensure_ascii=False)
        self.assertIn('分類1筆',text);self.assertIn('需實讀',text)
        self.assertEqual(state,before)
    def test_card_checks_missing_stars_garbled_copy_and_generic_angle(self):
        row=self.row();card=m.card(row,self.now)
        self.assertNotIn('category_mismatch',q.card_issues(row,card))
        card['description']='分類：AI／新工具'
        card['fields'][0]['value']='\ufffd'
        issues=q.card_issues(row,card)
        self.assertIn('stars_missing',issues);self.assertIn('text_encoding',issues);self.assertIn('category_mismatch',issues)
    def test_daily_report_is_yellow_if_evidence_missing_and_green_only_for_bounded_checks(self):
        results={name:('ok','完成') for name in h.MONITOR_LABELS}
        card=h.daily_health_embed(results,{},self.now)
        self.assertEqual(card['color'],0xF1C40F)
        self.assertIn('內容待核',card['title'])
        audit=q.inspect(self.healthy(),self.now)
        self.assertEqual(audit['warnings'],[])
        card=h.daily_health_embed(results,{'content_audit':audit},self.now)
        self.assertEqual(card['color'],0x2ECC71)
        self.assertIn('不等於完整語意驗收',json.dumps(card,ensure_ascii=False))
    def test_stale_audit_not_confused_with_no_new_stories(self):
        state=self.healthy();state['material_inbox_v1']['selection_audit']['completed_at']=(self.now-timedelta(hours=1)).isoformat()
        self.assertIn('逾時',json.dumps(q.inspect(state,self.now),ensure_ascii=False))

    def test_private_crypto_candidates_do_not_depend_on_member_gate(self):
        import crypto_news_notifier as news
        xml='<rss><channel><item><title>Existing editor adds MCP support</title><description>Its MCP server connects files and tasks in a limited preview for users.</description><link>https://example.com/story</link><pubDate>Sun, 08 Nov 2026 09:00:00 GMT</pubDate></item></channel></rss>'
        cfg={'name':'Existing source','url':'https://example.com/feed','official':False}
        rows, audits=[],[]
        with patch.object(news,'SOURCES',(cfg,)),patch.object(news,'http_text',return_value=xml) as fetch,patch.object(news,'parse_feed',return_value=[]):
            public,status=news.fetch_all(material_rows=rows,material_audit=audits)
        self.assertEqual(public,[]);self.assertEqual(len(rows),1)
        self.assertIsNone(audits[0]['error']);fetch.assert_called_once()
    def test_private_parser_error_does_not_break_public_feed_or_hide_health(self):
        import crypto_news_notifier as news
        cfg={'name':'Existing source','url':'https://example.com/feed','official':False}
        audit=[]
        with patch.object(news,'SOURCES',(cfg,)),patch.object(news,'http_text',return_value='<broken'),patch.object(news,'parse_feed',return_value=[]):
            public,status=news.fetch_all(material_rows=[],material_audit=audit)
        self.assertEqual(status[0][1],0)
        state=self.healthy();state['content_source_audit']['private_parsers']=audit
        self.assertIn('原始素材解析失敗',json.dumps(q.inspect(state,self.now),ensure_ascii=False))
    def test_summary_translation_is_checked_and_retained_in_card(self):
        state=self.state();send=Mock(return_value='123')
        row=self.row('Existing editor adds MCP support',summary='Its MCP server connects files and tasks in a limited preview for users.')
        self.assertEqual(self.run_box([row],state,send=send,enrich=Mock(side_effect=['編輯器新增MCP支援','MCP伺服器在預覽版連接檔案與任務。'])),1)
        text=json.dumps(send.call_args.args[1],ensure_ascii=False)
        self.assertIn('MCP伺服器在預覽版',text)
        self.assertNotIn('中文未完整核對',text)
    def test_concrete_life_contrast_survives_without_becoming_a_finance_gate(self):
        row=self.row("NYT Cooking's AI assistant saved my weeknight chicken, but almost ruined my cake",summary='The author tested the cooking assistant on two meals, describing the instructions and an unsuccessful cake.',material_topic='interesting')
        self.assertIsNone(q.selection(row,self.now))
    def test_startup_without_ai_does_not_get_an_invented_ai_task(self):
        row=self.row('Startup raises funding for finance software',summary='The company raised funding to develop finance software for business owners.',material_topic='business')
        self.assertNotIn('交給AI',review(row,self.now)['concept'])
    def test_render_fault_is_held_while_good_candidate_can_continue(self):
        state=self.state();send=Mock(return_value='123')
        row=self.row('Existing editor adds MCP support',summary='Its MCP server connects files and tasks in a limited preview for users.')
        bad=m.card(row,self.now);bad['description']='No stars'
        with patch.object(m,'card',return_value=bad):
            self.assertEqual(self.run_box([row],state,send=send),0)
        send.assert_not_called()
        self.assertEqual(state['material_inbox_v1']['items'][0]['quality_hold_reason'],'render_quality')
