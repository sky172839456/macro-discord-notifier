"""Cross-layer positive, adversarial, cache and no-send acceptance tests."""
import copy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock,patch

import content_contract as c
import content_interpretation as interpretation
import crypto_news_notifier as news
import material_inbox as material
import news_auto_recovery as auto
import slim_policy
from notification_format import apply_delivery_format

CASES=json.loads((Path(__file__).parent/'fixtures/content_contract_cases.json').read_text(encoding='utf8'))


class ContentContractTests(TestCase):
    now=datetime(2026,11,10,1,tzinfo=timezone.utc)
    def setUp(self):
        self.env=patch.dict(os.environ,{'CONTENT_PREFLIGHT_STRICT':'1','NEWS_AUTO_RECOVERY':'1','SLIM_NOTIFICATIONS':'1'})
        self.env.start();self.addCleanup(self.env.stop)
    def row(self):
        row={'id':'article-1','title':'SEC approves Bitcoin ETF','title_zh':'SEC核准比特幣ETF',
             'summary':'The fund costs $5. Only eligible users can join.',
             'summary_zh_points':['基金費用5美元。僅符合資格的使用者可參加。'],
             'source':'Example News','url':'https://example.com/article','official':False,
             'published':self.now-timedelta(minutes=2),'category':{'key':'regulation','label':'監管','priority':'normal'}}
        return c.stamp(row,[{'source':row['summary'],'zh':row['summary_zh_points'][0]}])
    def test_historical_and_unseen_translation_corpus(self):
        for case in CASES:
            with self.subTest(case=case['case'],valid=True):auto.checked_copy(case['source'],case['good'])
            with self.subTest(case=case['case'],valid=False):
                with self.assertRaises(ValueError):auto.checked_copy(case['source'],case['bad'])
    def test_identifier_protection_is_generic_and_rejects_lost_or_repeated_tokens(self):
        source='Use `atlas --limit 10` with Claude Code v7.8.9 and 5 BTC.'
        masked,mapping=c.protect(source)
        self.assertNotIn('atlas --limit',masked);self.assertNotIn('v7.8.9',masked)
        self.assertEqual(c.restore(masked,mapping),source)
        for bad in (masked.replace(next(iter(mapping)),''),masked+' '+next(iter(mapping))):
            with self.assertRaises(ValueError):c.restore(bad,mapping)
    def test_provider_protects_identifiers_before_translation(self):
        def response(url,**kwargs):
            from urllib.parse import urlsplit,parse_qs
            source=parse_qs(urlsplit(url).query)['q'][0]
            self.assertNotIn('Claude Code',source)
            return json.dumps({'responseStatus':200,'responseData':{'translatedText':'請使用'+source.replace('Use ','')}})
        with patch.object(news,'http_text',side_effect=response):
            value=auto.translate('Use Claude Code v7.8.9.')
        self.assertIn('Claude Code v7.8.9',value)
    def test_excerpt_keeps_exception_and_never_cuts_an_overlong_claim(self):
        value='The tool is available. Only eligible users can join.'
        self.assertEqual(c.segments(value),[value])
        overlong='A'*435+'. Only eligible users can join.'
        self.assertEqual(c.segments(overlong),[])
        self.assertEqual(c.segments('A short complete result. The source ends with...'),['A short complete result.'])
    def test_decimal_and_abbreviated_dates_survive_sentence_split(self):
        value='U.S. firm Atlas released v4.3.2 for $5.20. Only eligible users can join.'
        self.assertEqual(c.segments(value),[value])
    def test_evidence_survives_serialization_and_is_invalidated_by_source_changes(self):
        row=self.row();self.assertEqual(c.article_issues(row,self.now),[])
        stored=copy.deepcopy(row);stored['published']=stored['published'].isoformat()
        self.assertEqual(c.article_issues(json.loads(json.dumps(stored)),self.now),[])
        for key,value in [('summary','The fund costs $50.'),('url','https://example.com/other'),('official',True),('published',self.now)]:
            with self.subTest(field=key):self.assertIn('stale_source_evidence',c.article_issues(dict(row,**{key:value}),self.now))
    def test_cross_bullet_number_borrowing_is_rejected(self):
        row=self.row();row['summary']='The fund costs $5. The other fund costs $50.'
        row['summary_zh_points']=['基金費用50美元。']
        c.stamp(row,[{'source':'The fund costs $5.','zh':row['summary_zh_points'][0]}])
        self.assertIn('segment_translation_invalid',c.article_issues(row,self.now))
    def test_missing_or_mutated_display_and_partial_translation_stay_held(self):
        row=self.row()
        self.assertIn('source_copy_evidence_missing',c.article_issues({k:v for k,v in row.items() if k!='content_contract'}))
        row['summary_zh_points']=['基金費用5美元。']
        self.assertIn('display_evidence_mismatch',c.article_issues(row))
        row=self.row();row['content_contract']['complete_selected_excerpt']=False
        self.assertIn('incomplete_selected_excerpt',c.article_issues(row))
    def test_source_link_time_and_excerpt_provenance_are_required(self):
        for key,value,error in [('url','http://example.com/a','invalid_source_url'),('published',self.now.replace(tzinfo=None),'source_timezone_missing'),('published',self.now-timedelta(days=2),'source_outside_window')]:
            row=self.row();row[key]=value;c.stamp(row,row['content_contract']['pairs'])
            self.assertIn(error,c.article_issues(row,self.now))
        row=self.row();c.stamp(row,[{'source':'A different report.','zh':'另一份報告。'}]);row['summary_zh_points']=['另一份報告。']
        self.assertIn('excerpt_not_in_source',c.article_issues(row,self.now))
    def test_new_enrichment_keeps_exact_pairs_and_rechecks_legacy_cache(self):
        row=self.row();row.pop('content_contract');row['summary']='The fund costs $5.'
        with patch.object(news,'translate_text',side_effect=lambda value:'SEC核准比特幣ETF' if value==row['title'] else '基金費用5美元。'):
            fixed=auto.enrich(row,{},self.now)
        self.assertEqual(c.article_issues(fixed,self.now),[])
        self.assertEqual(fixed['content_contract']['pairs'][0]['source'],row['summary'])
        stale=dict(fixed,category={'key':'market'},auto_copy_version=2)
        self.assertIn('source_category_mismatch',c.article_issues(stale,self.now))
        with patch.object(news,'translate_text',side_effect=AssertionError('verified copy needs no provider')):
            refreshed=news.add_translated_title(stale,{},self.now)
        self.assertEqual(refreshed['category']['key'],'regulation')
        self.assertEqual(c.article_issues(refreshed,self.now),[])
    def test_failed_translation_does_not_turn_source_body_into_headline_success(self):
        row=self.row();row.pop('content_contract')
        def translate(value):
            if value==row['title']:return row['title_zh']
            raise ValueError('provider unavailable')
        with patch.object(news,'translate_text',side_effect=translate):result=auto.enrich(row,{},self.now)
        self.assertIn('incomplete_selected_excerpt',c.article_issues(result,self.now))
    def test_final_formatter_cannot_drop_negation_or_second_point(self):
        row=self.row();card=slim_policy.news_card(row,now=self.now)
        self.assertEqual(c.final_article_issues([row],card,self.now),[])
        card['description']=card['description'].replace('僅符合資格的使用者可參加。','')
        self.assertIn('render_cut_verified_copy',c.final_article_issues([row],card,self.now))
    def test_long_news_and_digest_keep_whole_verified_sentences(self):
        row=self.row();point='來源說明。'*48+'僅符合資格的使用者可參加。'
        # A long Chinese sentence is allowed if it is exactly bound to its source.
        row['summary']='Eligible users can use the fund. '*10+'Only eligible users can join.';row['summary_zh_points']=[point]
        c.stamp(row,[{'source':row['summary'],'zh':point}])
        for card in (slim_policy.news_card(row,now=self.now),slim_policy.digest_card([row],self.now)):
            self.assertIn(point,card['description']);self.assertEqual(c.final_article_issues([row],card,self.now),[])
    def test_transport_rejects_unbound_news_before_any_network_request(self):
        with patch.object(news,'urlopen') as request:
            with self.assertRaises(ValueError):news.send_discord('https://example.invalid/webhook',{'title':'測試'})
        request.assert_not_called()
    def test_transport_rejects_mutated_copy_before_any_network_request(self):
        row=self.row();card=slim_policy.news_card(row,now=self.now);card['description']='基金費用5美元。'
        with patch.object(news,'urlopen') as request:
            with self.assertRaises(ValueError):news.send_discord('https://example.invalid/webhook',card,source_items=[row],observed_at=self.now)
        request.assert_not_called()
    def test_final_payload_uses_utf16_and_aggregate_limits_without_truncation(self):
        card={'title':'標題','description':'😀'*2049};before=copy.deepcopy(card)
        self.assertIn('text_limit',c.payload_issues([card]));self.assertEqual(card,before)
        self.assertIn('embed_total_limit',c.payload_issues([{'description':'文'*3500},{'description':'文'*3500}]))
    def test_bad_encoding_secret_and_missing_numbers_never_reach_any_public_sender(self):
        values=['資料�','費用：**NaN**','資料：undefined','https://discord.com/api/webhooks/123/FAKE_TEST_ONLY']
        for channel in ('macro_alerts','daily_market','weekly_market','crypto_news','finance_news','market_risk'):
            for text in values:
                with self.subTest(channel=channel,text=text),self.assertRaises(ValueError):apply_delivery_format({'title':'品質檢查','description':text},channel)
    def test_holds_do_not_consume_seen_or_daily_quota(self):
        row=self.row();state={'seen':{},'stream_digest_progress':{'crypto':{'ids':[]}}};before=copy.deepcopy(state)
        card=slim_policy.news_card(row,now=self.now);card['description']='不完整摘要'
        self.assertFalse(c.record_preflight(state,[row],card,self.now))
        self.assertEqual(state['seen'],before['seen']);self.assertEqual(state['stream_digest_progress'],before['stream_digest_progress'])
        self.assertEqual(state['content_preflight_status']['held'],1)
    def test_material_with_failed_copy_is_held_and_delivered_item_never_reopened(self):
        row=self.row();row['material_topic']='policy'
        state={'seen':{'member':'kept'},'material_inbox_v1':{'started_at':(self.now-timedelta(hours=1)).isoformat(),'items':[]}}
        with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'test'}),patch('material_quality.selection',return_value=None):
            send=Mock();material.run([row],state,self.now,fetch=Mock(side_effect=OSError()),send=send,persist=Mock(),verify=Mock(),enrich=Mock(side_effect=ValueError('unavailable')))
        send.assert_not_called();self.assertEqual(state['material_inbox_v1']['items'][0]['status'],'quality_hold');self.assertEqual(state['seen'],{'member':'kept'})
    def test_generic_interpretation_requires_real_action_and_keeps_evidence(self):
        for title in ('MCP security patch available','Researchers discuss MCP integration','Tool does not add MCP support'):
            self.assertFalse(interpretation.connection_claim(title,''))
        self.assertTrue(interpretation.connection_claim('Atlas adds an MCP server','Users can query market data in beta.'))
        row={'title':'Atlas adds an MCP server','summary':'Users can query market data in beta, with read-only access.','material_topic':'ai'}
        hook,evidence=interpretation.specific_hook(row,row['title'],'通用問題')
        self.assertIn('行情資料',hook);self.assertIn('Atlas',hook)
        for quote in evidence.values():self.assertIn(quote,row['title']+'\n'+row['summary'])
    def test_generic_event_identity_keeps_stage_amount_authority_and_object_changes(self):
        a={'title':'Coinbase gets final OCC federal trust charter','summary':'OCC confirms the decision.','published':self.now}
        b=dict(a,title='Coinbase receives full OCC federal trust charter')
        self.assertTrue(interpretation.same_structured_event(a,b))
        for change in ('Coinbase applies for OCC federal trust charter','Coinbase gets conditional OCC federal trust charter','Coinbase did not get final OCC federal trust charter','Coinbase gets final FCA federal trust charter'):
            self.assertFalse(interpretation.same_structured_event(a,dict(b,title=change)))
        self.assertFalse(interpretation.same_structured_event(a,dict(b,summary='OCC confirms the decision for $50.')))
        a={'title':'Ledger releases Nano X v1.2.3','summary':'The release is available.','published':self.now}
        self.assertFalse(interpretation.same_structured_event(a,dict(a,title='Ledger releases Nano S v1.2.3')))
        for title in ('Ledger plans to release Nano X v1.2.3','Ledger cancels release Nano X v1.2.3','Ledger releases Nano S v1.2.3'):
            changed=dict(a,title=title)
            self.assertFalse(interpretation.same_structured_event(a,changed))
            self.assertFalse(news.same_news_event(a,changed))
        self.assertFalse(news.same_news_event(a,dict(a,summary='The release fixes a vulnerability.')))
    def test_untranslated_prose_or_extraneous_expansion_is_not_a_chinese_summary(self):
        with self.assertRaises(ValueError):auto.checked_copy('The bank approves the charter for users.','銀行approves the charter for users。')
        with self.assertRaises(ValueError):auto.checked_copy('The tool is available.','工具已開放。'+'來源說明。'*60)
    def test_quotes_inside_verified_copy_do_not_create_a_false_render_failure(self):
        row=self.row();row['summary']='The fund is called "Example".';row['summary_zh_points']=['基金名為"Example"。']
        c.stamp(row,[{'source':row['summary'],'zh':row['summary_zh_points'][0]}])
        self.assertEqual(c.final_article_issues([row],slim_policy.news_card(row,now=self.now),self.now),[])
    def test_strict_public_pipeline_retains_rejected_card_and_does_not_close_quota(self):
        import news_streams
        now=self.now.replace(hour=13)
        row=self.row();row['published']=now-timedelta(minutes=2);c.stamp(row,row['content_contract']['pairs'])
        state={'initialized':True,'finance_initialized':True,'seen':{},'pending':[],'headline_history':[]}
        with patch.dict(os.environ,{'DISCORD_CRYPTO_NEWS_WEBHOOK_URL':'crypto','DISCORD_FINANCE_NEWS_WEBHOOK_URL':'finance','MATERIAL_INBOX_ENABLED':'0'}),\
             patch.object(news,'load_state',return_value=state),patch.object(news,'save_state'),\
             patch.object(news,'fetch_all',return_value=([row],[('Example',1,None)])),\
             patch.object(news_streams,'fetch_finance',return_value=([],[('Example',0,None)])),\
             patch.object(auto,'route',return_value=[row]),patch.object(slim_policy,'material_news',return_value=False),\
             patch.object(slim_policy,'digest_card',return_value={'title':'新聞','description':'被切斷的內容'}),\
             patch.object(news,'send_discord') as send:
            news_streams.run(now)
        send.assert_not_called();self.assertEqual(state['seen'],{})
        self.assertEqual(state['pending'][0]['id'],row['id'])
        self.assertFalse(state['stream_digest_progress']['crypto']['closed'])
        self.assertEqual(state['content_preflight_status']['held'],1)
    def test_strict_material_success_stores_proof_and_uncertain_delivery_is_not_retried(self):
        row=self.row();state={'seen':{},'material_inbox_v1':{'started_at':(self.now-timedelta(hours=1)).isoformat(),'items':[]}}
        row.update(title='TradingView adds an MCP server',title_zh='TradingView新增MCP伺服器',
                   summary='Users on Essential can query market data and manage watchlists in beta, with read-only access.',
                   summary_zh_points=['Essential使用者可在測試版查詢行情與管理觀察清單，提供唯讀存取。'])
        def translate(value):return row['title_zh'] if value==row['title'] else row['summary_zh_points'][0]
        with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'test'}),patch('material_quality.selection',return_value=None):
            send=Mock(return_value='999')
            material.run([row],state,self.now,fetch=Mock(side_effect=OSError()),send=send,persist=Mock(),verify=Mock(),enrich=translate)
            self.assertEqual(send.call_count,1)
            item=state['material_inbox_v1']['items'][0]
            self.assertEqual(c.article_issues(item,self.now),[])
            self.assertEqual(item['status'],'notified')
            item['status']='delivery_unknown';send.reset_mock()
            material.run([row],state,self.now,fetch=Mock(side_effect=OSError()),send=send,persist=Mock(),verify=Mock(),enrich=Mock(side_effect=AssertionError('must not reopen')))
            send.assert_not_called();self.assertEqual(item['status'],'delivery_unknown')
    def test_unsent_release_empty_parts_cannot_reuse_old_bullets_and_retry_is_bounded(self):
        row=self.row();row.update(title='Claude Code v7.8.9',source='Claude Code Releases',summary='Updated release details.',summary_parts=[])
        old=dict(row,summary='Old release details.',summary_parts=['Added old settings.'],status='queued',material_topic='ai',material_key=material.key(row))
        state={'seen':{},'material_inbox_v1':{'started_at':(self.now-timedelta(hours=1)).isoformat(),'items':[old]}}
        with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'test'}),patch('material_quality.selection',return_value=None):
            send=Mock();enrich=Mock(side_effect=ValueError('provider unavailable'))
            material.run([row],state,self.now,fetch=Mock(side_effect=OSError()),send=send,persist=Mock(),verify=Mock(),enrich=enrich)
            self.assertEqual(old['summary_parts'],[]);self.assertIn('copy_retry',old)
            self.assertEqual(old['copy_retry']['attempts'],1)
            enrich.reset_mock()
            material.run([row],state,self.now+timedelta(minutes=5),fetch=Mock(side_effect=OSError()),send=send,persist=Mock(),verify=Mock(),enrich=enrich)
            enrich.assert_not_called();send.assert_not_called()
