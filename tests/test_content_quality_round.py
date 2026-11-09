"""Synthetic release/event fixtures; real RSS aliases are probed read-only."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from datetime import datetime,timedelta,timezone

import material_inbox as m
from material_source_copy import release_parts,excerpt_parts,display_points,new_connection
from material_editorial import review
from news_auto_recovery import checked_copy
from notification_quality import checked_translation,numeric_values
import news_checked_episodes as episodes
import crypto_news_notifier as news
import market_brief_v2 as brief


class MaterialCompleteCopy(unittest.TestCase):
    now=datetime(2026,11,10,1,tzinfo=timezone.utc)
    model='Added Claude Fable 5.2 (claude-fable-5-2), now the default Fable model — 1M context, $8/$40 per Mtok with $0.20/Mtok cache reads'
    settings='Added --settings 〈file〉 to claude remote-control, which applies a settings file to every session it starts; if the file changes, no new session starts until you restart claude remote-control'
    def row(self):
        return {'title':'Claude Code v2.1.321','source':'Claude Code Releases','official':True,
                'summary':self.model+' '+self.settings+' Fixed MCP OAuth redirect handling.',
                'summary_parts':[self.model,self.settings,'Fixed MCP OAuth redirect handling.'],
                'published':self.now,'material_topic':'ai','url':'https://github.com/anthropics/claude-code/releases/tag/v2.1.321'}
    def test_release_html_retains_bullets_code_and_safe_metavariables(self):
        html='<ul><li>Added <code>--settings &lt;file&gt;</code> to <code>claude remote-control</code>.</li><li>Fixed MCP OAuth handling.</li></ul>'
        parts=release_parts(html)
        self.assertEqual(parts,['Added --settings 〈file〉 to claude remote-control.','Fixed MCP OAuth handling.'])
        self.assertTrue(all(len(p.encode('utf8'))<=450 for p in parts))
    def test_two_complete_release_bullets_never_include_a_cut_third_fix(self):
        row=self.row();before=copy.deepcopy(row)
        parts=excerpt_parts(row);self.assertEqual(parts,[self.model,self.settings])
        self.assertTrue(parts[-1].endswith('claude remote-control'));self.assertEqual(row,before)
    def test_overlong_bullet_is_not_character_cut_or_mixed_with_next(self):
        row=self.row();row['summary_parts']=['A'*700,'Fixed a remote-control issue without changing permissions.']
        self.assertEqual(excerpt_parts(row),[row['summary_parts'][1]])
        row['summary_parts']=['A'*700];self.assertEqual(excerpt_parts(row),[])
        from material_quality import selection
        self.assertEqual(selection(row,self.now),'complete_excerpt_unavailable')
    def test_display_does_not_cut_chinese_at_old_190_character_boundary(self):
        point='更新說明'*55+'；提款仍未恢復，勿重複提交。'
        result=display_points([point]);self.assertIn('提款仍未恢復，勿重複提交。',result)
        self.assertLessEqual(len(result),900)
        self.assertNotIn('斷尾',display_points(['斷尾'*600]))
    def test_release_angle_distinguishes_new_model_settings_and_fixes(self):
        result=review(self.row(),self.now)['concept']
        for term in ('版本更新','模型','--settings','claude remote-control','修補'):self.assertIn(term,result)
        self.assertNotIn('這次串接',result)
    def test_mcp_patch_and_incident_are_not_new_integration_but_real_connector_is(self):
        for title in ('Fixed MCP OAuth redirect checks','MCP server vulnerability patched','MCP integration breach exposed keys'):
            self.assertFalse(new_connection(title,''))
        self.assertTrue(new_connection('TradingView adds a new MCP server','Essential users can query market data in beta.'))
    def test_version_product_copy_retains_version_and_rejects_wrong_number(self):
        result=checked_translation('Claude Code v2.1.321','Claude代碼 v2.1.321')
        self.assertEqual(result,'Claude Code 版本更新 v2.1.321')
        with self.assertRaises(ValueError):checked_translation('Claude Code v2.1.321','Claude代碼 v2.1.322')
    def test_model_name_prices_and_context_amounts_keep_source_facts(self):
        translated='新增克勞德寓言 5.2（claude-fable-5-2），默認寓言模型，1M 上下文；每 Mtok $8/$40，快取讀取 $0.20/Mtok。'
        result=checked_copy(self.model,translated)
        self.assertIn('Claude Fable',result);self.assertNotIn('寓言',result)
        self.assertEqual(numeric_values(self.model),numeric_values(result))
        with self.assertRaises(ValueError):checked_copy(self.model,translated.replace('$40','$400'))
    def test_command_placeholder_is_repaired_only_for_explicit_added_settings(self):
        text='將--settings〈檔案新增〉至 claude 遙控器，它會套用設定檔；如果檔案變更，在重新啟動 claude 遙控器之前不會啟動新工作階段。'
        result=checked_copy(self.settings,text)
        self.assertIn('claude remote-control 新增 --settings〈file〉參數',result)
        self.assertIn('不會',result)
        with self.assertRaises(ValueError):checked_copy(self.settings,'新增設定功能，它會套用設定檔，不會啟動新工作階段。')
    def test_per_point_render_does_not_require_other_bullet_identifiers(self):
        row=self.row();row.update(title_zh='Claude Code 版本更新 v2.1.321',
            summary_check_source=self.model+'\n'+self.settings,
            summary_zh_points=['新增Claude Fable 5.2（claude-fable-5-2），1M 上下文，價格$8/$40，每Mtok快取$0.20。',
                'claude remote-control 新增 --settings〈file〉參數；檔案變更後不會啟動新工作階段，直到重新啟動 claude remote-control。'])
        fields=m.card(row,self.now)['fields'];facts=next(f['value'] for f in fields if f['name'].startswith('📌'))
        self.assertIn('Claude Fable',facts);self.assertIn('--settings〈file〉',facts)
        self.assertEqual(facts.count('•'),2)
    def test_units_preserve_near_asset_but_leave_ordinary_proximity_untouched(self):
        source='Hackers laundered 117,000 NEAR, worth about $430,000, through six memecoins.'
        result=checked_copy(source,'駭客透過六個迷因幣洗錢117,000附近，價值約$430,000。')
        self.assertIn('117,000枚 NEAR',result)
        with self.assertRaises(ValueError):checked_copy(source,'駭客洗錢117,000，價值約$430,000。')
        plain='Customers stood near 117,000 houses.'
        self.assertEqual(checked_translation(plain,'客戶站在117,000間房屋附近。'),'客戶站在117,000間房屋附近。')
    def test_pre_hack_balance_does_not_imply_withdrawal_resumed(self):
        source='Customers can view pre-hack balances. The exchange has not said when withdrawals will resume.'
        result=checked_copy(source,'客戶可查看預先破解餘額。交易所尚未說明何時恢復提款。')
        self.assertIn('遭駭前的餘額',result);self.assertIn('尚未',result)
        with self.assertRaises(ValueError):checked_copy(source,'客戶可查看遭駭前的餘額，交易所已恢復提款。')
    def test_english_headline_keeps_launderer_subject_not_musk_as_attacker(self):
        source='Binance Hack Launderers Mint Elon Musk and Animal Meme Coins to Move Stolen Crypto'
        result=checked_copy(source,'Binance Hack Launderers Mint Elon Musk 和 Animal Meme Coins 轉移被盜的加密資產')
        self.assertIn('洗錢者鑄造',result);self.assertIn('主題迷因幣',result);self.assertNotIn('Hack Launderers',result)
    def test_delivered_and_unknown_material_rows_are_not_reopened(self):
        row=self.row();row['published']=row['published'].isoformat();row['material_key']=m.key(row)
        for status in ('notified','delivery_unknown'):
            item=dict(row,status=status);state={'seen':{'keep':'value'},'material_inbox_v1':{'started_at':(self.now-timedelta(days=1)).isoformat(),'items':[item]}};before=copy.deepcopy(item)
            with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'test'}):
                send=Mock();m.run([dict(self.row(),summary_parts=['Changed display only.'])],state,self.now,fetch=Mock(side_effect=OSError()),send=send,persist=Mock(),verify=Mock(),enrich=Mock())
            send.assert_not_called();self.assertEqual({k:item[k] for k in before},before)
            self.assertEqual(item.get('related_sources',[]),[]);self.assertEqual(state['seen'],{'keep':'value'})


class VerifiedEpisodeGuards(unittest.TestCase):
    now=datetime(2026,11,9,12,tzinfo=timezone.utc)
    def row(self,n):
        return {'title':f'Publisher {n} reports an Example final decision','summary':'A synthetic source statement.',
            'url':f'https://example.com/report/{n}','source':'Example','published':self.now.isoformat(),
            'id':str(n),'official':False,'title_zh':f'來源{n}報導某項最終決定','category':{'key':'security','label':'資安'}}
    def mapping(self,a,b,group='coinbase_final_trust_20261109'):
        return {episodes.fingerprint(r):(group,r['published']) for r in (a,b)}
    def test_exact_source_observations_match_but_any_new_evidence_does_not(self):
        a,b=self.row(1),self.row(2)
        with patch.dict(episodes.VERIFIED,self.mapping(a,b),clear=True):
            self.assertTrue(episodes.same_checked_event(a,b))
            for field,value in [('summary','A revised amount of $500 million.'),('title','Application pending conditional approval'),('url','https://other.example/report/2'),('published',(self.now+timedelta(days=1)).isoformat())]:
                changed=dict(b,**{field:value});self.assertFalse(episodes.same_checked_event(a,changed))
    def test_utm_tracking_does_not_make_same_checked_story_new(self):
        a,b=self.row(1),self.row(2)
        with patch.dict(episodes.VERIFIED,self.mapping(a,b),clear=True):
            self.assertTrue(episodes.same_checked_event(a,dict(b,url=b['url']+'?utm_source=rss')))
    def test_missing_timestamp_or_summary_never_matches_verified_episode(self):
        a,b=self.row(1),self.row(2)
        with patch.dict(episodes.VERIFIED,self.mapping(a,b),clear=True):
            self.assertFalse(episodes.same_checked_event(a,{k:v for k,v in b.items() if k!='published'}))
            self.assertFalse(episodes.same_checked_event(a,dict(b,summary='')))
    def test_public_new_progress_retained_but_weekly_episode_can_group(self):
        a,b=self.row(1),self.row(2)
        with patch.dict(episodes.VERIFIED,self.mapping(a,b,'gnosis_customer_data_20261106'),clear=True):
            self.assertFalse(episodes.same_checked_event(a,b));self.assertTrue(episodes.same_recap_episode(a,b))
    def test_live_dedup_keeps_member_ids_and_does_not_change_seen(self):
        a,b=self.row(1),self.row(2);state={'seen':{'old':'retained'}};before=copy.deepcopy(state)
        with patch.dict(episodes.VERIFIED,self.mapping(a,b),clear=True),patch.dict(os.environ,{'SLIM_NOTIFICATIONS':'1'}):
            result=news.deduplicate([a,b]);self.assertEqual(len(result),1)
            from news_editorial import member_ids
            self.assertEqual(set(member_ids(result[0])),{'1','2'})
        self.assertEqual(state,before)
    def test_weekly_only_combines_known_episode_links_without_mutating_journal(self):
        a,b=self.row(1),self.row(2);b['published']=(self.now-timedelta(hours=1)).isoformat()
        state={'weekly_journal':[a,b],'weekly_journal_started_at':(self.now-timedelta(days=8)).isoformat()};before=copy.deepcopy(state)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'isolated.json';path.write_text(json.dumps(state),encoding='utf8')
            with patch.dict(episodes.VERIFIED,self.mapping(a,b,'gnosis_customer_data_20261106'),clear=True),patch.dict(os.environ,{'SLIM_NOTIFICATIONS':'1'}):
                result=brief.news_review(path,self.now+timedelta(hours=1))
            self.assertEqual(len(result['items']),1);self.assertEqual(len(result['items'][0]['recap_related_sources']),1)
            rendered=brief.review_lines({'news_review':result});self.assertIn(a['url'],rendered);self.assertIn(b['url'],rendered)
            self.assertEqual(json.loads(path.read_text(encoding='utf8')),before)

