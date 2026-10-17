import copy
import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import crypto_news_notifier as news
import news_auto_recovery as auto
import news_editorial as editorial
import news_streams as streams
import notification_quality as quality

class StreamTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,17,12,tzinfo=timezone.utc)
        p=patch.dict(os.environ,{'NEWS_SPLIT_STREAMS':'1','SLIM_NOTIFICATIONS':'1','NEWS_AUTO_RECOVERY':'1',
            'DISCORD_CRYPTO_NEWS_WEBHOOK_URL':'https://crypto.invalid','DISCORD_FINANCE_NEWS_WEBHOOK_URL':'https://finance.invalid'})
        p.start();self.addCleanup(p.stop)
    def row(self,n,finance=False):
        title=f'Federal Reserve signals liquidity changes {n}%' if finance else f'BlackRock Bitcoin ETF assets rise {n}%'
        zh=f'聯準會釋出流動性變化訊號{n}%' if finance else f'BlackRock Bitcoin ETF資產增加{n}%'
        row={'id':('f' if finance else 'c')+str(n),'title':title,'summary':title,'title_zh':zh,
            'summary_zh_points':[zh],'published':self.now,'url':'https://example.invalid/'+('f' if finance else 'c')+str(n),
            'source':'mock','official':False,'auto_copy_version':2,'category':news.CATEGORIES[2]}
        if finance:
            topic=streams.finance_topic(row);row.update(stream='finance',category=topic['category'],transmission=topic['copy'])
        return row
    def run_rows(self,rows,state,finance=None,side_effect=None):
        with patch.object(news,'load_state',return_value=state),patch.object(news,'save_state'), \
             patch.object(news,'fetch_all',return_value=(rows,[('mock',len(rows),None)])), \
             patch.object(streams,'fetch_finance',return_value=(finance or [],[('finance',len(finance or []),None)])), \
             patch.object(news,'send_discord',side_effect=side_effect) as send:
            news.run(self.now)
        return send
    def test_each_stream_five_cap_and_persistent_no_repeat(self):
        state={'initialized':True,'finance_initialized':True,'seen':{},'pending':[]}
        rows=[self.row(n) for n in range(1,7)]+[self.row(n,True) for n in range(1,7)]
        send=self.run_rows(rows,state)
        self.assertEqual(send.call_count,2)
        self.assertEqual({c.args[0] for c in send.call_args_list},{'https://crypto.invalid','https://finance.invalid'})
        for progress in state['stream_digest_progress'].values():self.assertEqual(len(progress['ids']),5)
        self.assertEqual(len(state['seen']),10)
        state=json.loads(json.dumps(state))
        self.run_rows(rows,state).assert_not_called()
    def test_success_first_stream_failure_second_does_not_replay_first(self):
        state={'initialized':True,'finance_initialized':True,'seen':{},'pending':[]}
        rows=[self.row(1),self.row(1,True)]
        with self.assertRaises(RuntimeError):self.run_rows(rows,state,side_effect=[None,RuntimeError('offline')])
        self.assertIn('c1',state['seen']);self.assertNotIn('f1',state['seen'])
        send=self.run_rows(rows,json.loads(json.dumps(state)))
        self.assertEqual(send.call_count,1);self.assertEqual(send.call_args.args[0],'https://finance.invalid')
    def test_new_finance_sources_baseline_without_replaying(self):
        state={'initialized':True,'seen':{},'pending':[]}
        send=self.run_rows([],state,finance=[self.row(1,True)])
        send.assert_not_called();self.assertIn('f1',state['seen']);self.assertTrue(state['finance_initialized'])
    def test_same_url_on_finance_and_crypto_only_one_destination(self):
        a=self.row(1);b={**a,'id':'finance-copy','stream':'finance'}
        state={'initialized':True,'finance_initialized':True,'seen':{},'pending':[]}
        send=self.run_rows([a],state,finance=[b])
        self.assertEqual(send.call_count,1);self.assertEqual(send.call_args.args[0],'https://crypto.invalid')
        self.assertIn('c1',state['seen']);self.assertIn('finance-copy',state['seen'])
    def test_missing_destination_fails_closed_not_rerouted(self):
        with patch.dict(os.environ,{'DISCORD_FINANCE_NEWS_WEBHOOK_URL':''}),patch.object(news,'send_discord') as send:
            with self.assertRaises(RuntimeError):news.run(self.now)
            send.assert_not_called()
    def test_policy_and_company_filters_exclude_gossip_and_macro_duplicates(self):
        for title in ['Trump posts a joke about golf','Musk shows off new sunglasses','US consumer price index rises',
                      'Federal Reserve issues FOMC statement','CONNECT recap about stablecoin payments',
                      'Federal Reserve Board approves bank application',
                      'World Bank jobs council urges crisis-era employment support',
                      'Analysis: Everyone expects the Fed to hold rates. Warsh could surprise',
                      'Economists: Hot PPI shows Fed work is not done']:
            self.assertIsNone(streams.finance_topic({'title':title}),title)
        for title in ['Trump imposes tariffs on imports','Nvidia faces new export restrictions',
                      'Mastercard launches stablecoin payments','Bank liquidity crisis triggers rescue']:
            self.assertIsNotNone(streams.finance_topic({'title':title}),title)
    def test_short_summary_preserves_abbreviations_and_incomplete_source_falls_back(self):
        for text in ['Former Mt. Gox CEO questions Ledger response.','U.S. SEC meets Dr. Smith.','Growth reached 3.7%. It rose.']:
            self.assertEqual(auto.source_sentences(text),[text])
        row=self.row(1);row['summary']='Demand is growing as banks and payment firms.'
        with patch.object(news,'translate_text',return_value=row['title_zh']) as trans:
            result=auto.enrich(row,{},self.now)
        self.assertEqual(trans.call_count,1);self.assertEqual(result['summary_basis'],'headline')
    def test_long_summary_preserves_names_and_decimals(self):
        text='Former Mt. Gox CEO speaks to U.S. SEC and Dr. Smith about 3.7% growth. '+ 'A long sentence '+('x'*400)+'.'
        chunks=auto.source_sentences(text)
        self.assertIn('Mt. Gox',chunks[0]);self.assertIn('U.S. SEC',chunks[0]);self.assertIn('3.7%',chunks[0])
    def test_victim_episode_not_urgent_but_new_action_is(self):
        row=self.row(1);row.update(title='Scammer gets scammed in Ledger spy-chip exploit, loses almost $5 million in bitcoin',
            summary='Chainalysis says a fraudster who tricked people through fake online jobs became one of the biggest victims of compromised hardware wallets.')
        other={**row,'title':'Scammer Lost $4.8M in Bitcoin to Tampered Ledger Wallets: Chainalysis',
               'summary':'The funds came from a task scam that paid people to fake product sales and reviews, then demanded deposits before releasing their pay.'}
        self.assertFalse(auto.material_news(row));self.assertFalse(auto.material_news(other))
        # Chainalysis is in the other title, so identity remains source-qualified.
        self.assertTrue(news.same_news_event(row,other))
        for title in ['Another scammer lost $4.8M in tampered Ledger wallets: Chainalysis',
                      'Scammer lost $10M in tampered Ledger wallets: Chainalysis',
                      'Ledger recalls devices after scammer lost $4.8M: Chainalysis']:
            self.assertFalse(news.same_news_event(row,{**other,'title':title}),title)
        self.assertTrue(auto.material_news({**row,'title':'Ledger recalls devices after new exploit'}))
    def test_corporate_treasury_and_government_are_distinct(self):
        self.assertIn('資產儲備',quality.checked_translation("Europe’s second-largest Bitcoin treasury raised $30 million",
            '歐洲第二大Bitcoin財政部籌集3000萬美元'))
        self.assertIn('美國財政部',quality.checked_translation('U.S. Treasury announces rules','美國財政部宣布規則'))
    def test_old_pending_refreshed_without_losing_merged_ids(self):
        row=self.row(1);row['auto_copy_version']=1;row['title_zh']='舊標題';row['merged_ids']=['old-alias']
        state={'initialized':True,'finance_initialized':True,'seen':{},'pending':[news.serialize_pending(row)]}
        with patch.object(news,'translate_text',return_value='BlackRock Bitcoin ETF資產增加1%'):
            send=self.run_rows([],state)
        self.assertEqual(send.call_count,1)
        self.assertNotIn('舊標題',str(send.call_args.args[1]));self.assertIn('old-alias',state['seen'])
    def test_ready_retry_not_lost_when_urgent_send_fails(self):
        row=self.row(1);row.update(title='SEC approves Bitcoin ETF',summary='SEC approves Bitcoin ETF',
            title_zh='SEC核准Bitcoin ETF',summary_zh_points=['SEC核准Bitcoin ETF'])
        state={'initialized':True,'finance_initialized':True,'seen':{},'pending':[],
            'news_auto_retry':{'c1':{'item':{**row,'published':self.now.isoformat()},'attempts':1,'next_at':self.now.isoformat()}}}
        with self.assertRaises(RuntimeError):self.run_rows([],state,side_effect=RuntimeError('offline'))
        self.assertEqual(state['seen'],{});self.assertEqual(state['pending'][0]['id'],'c1')
        self.assertEqual(self.run_rows([],json.loads(json.dumps(state))).call_count,1)

if __name__=='__main__':unittest.main()
