import copy
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import material_inbox as inbox
import news_editorial
from notification_quality import checked_translation
from news_copy_terms import repair_translation

POLICY = (('CFTC Lets Traders Bet on Stocks With Crypto-Style Perpetual Futures', 'Chairman Michael Selig said “equity perpetual futures” can now trade on CFTC-registered exchanges, extending a crypto-native instrument to traditional stocks.'), ('CFTC clears stock perpetual futures for trading on US exchanges', 'US regulators are opening the door to stock-based perpetual futures, extending a popular crypto trading product into traditional markets amid ongoing legal disputes.'))
EDUCATION = ('Five Ways North Korea Breaks Into Crypto Firms—and How Binance Was Hacked', "From AI deepfakes to poisoning code libraries: here's how North Korean hackers get inside crypto companies.")
GITBOOK = 'Crypto Docs Host GitBook Hit by AI Agent Security Breach, Urges Users to Rotate Keys'

class MaterialContentFixes(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{'SLIM_NOTIFICATIONS':'1','NEWS_AUTO_RECOVERY':'1'})
        env.start();self.addCleanup(env.stop)
        self.now=datetime(2026,11,3,20,tzinfo=timezone.utc)

    def row(self,pair,index=0):
        return dict(title=pair[0],summary=pair[1],url='https://example.com/'+str(index),published=self.now,source='media',official=False,category={'key':'regulation'})

    def test_verified_cftc_pair_is_one_material_event(self):
        self.assertTrue(inbox.equivalent(self.row(POLICY[0]),self.row(POLICY[1],1)))

    def test_changed_cftc_evidence_and_later_day_are_not_suppressed(self):
        a=self.row(POLICY[0]);b=self.row(POLICY[1],1)
        for addition in (' Trading begins on December 1, 2026.',' Fees rise to 2%.',' The court revoked the decision.',' Additional losses reach $5 million.'):
            changed=dict(b,summary=b['summary']+addition)
            with self.subTest(addition=addition):self.assertFalse(inbox.equivalent(a,changed))
        self.assertFalse(inbox.equivalent(a,dict(b,published=self.now+timedelta(days=2))))

    def test_duplicate_joins_existing_private_ledger_without_replay(self):
        a=self.row(POLICY[0]);b=self.row(POLICY[1],1)
        a.update(published=self.now.isoformat(),material_topic='policy',status='notified',notified_at=self.now.isoformat())
        state={'seen':{'public':'kept'},'material_inbox_v1':{'started_at':(self.now-timedelta(hours=1)).isoformat(),'items':[a]}}
        from unittest.mock import Mock
        send=Mock()
        with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'https://discord.com/api/webhooks/123/TEST'}):
            result=inbox.run([b],state,self.now,fetch=Mock(side_effect=OSError),send=send,persist=Mock(),verify=Mock())
        self.assertEqual(result,0);send.assert_not_called()
        self.assertEqual(state['seen'],{'public':'kept'})
        self.assertEqual(len(state['material_inbox_v1']['items']),1)

    def test_rotate_keys_is_replacing_credentials(self):
        translated=checked_translation(GITBOOK,'Crypto Docs 主機 GitBook 被 AI 代理安全漏洞擊中，敦促用戶旋轉密鑰')
        self.assertIn('更換金鑰',translated)
        self.assertNotIn('旋轉',translated)

    def test_cftc_clears_means_approval_not_trade_clearing(self):
        translated=checked_translation(POLICY[1][0],'CFTC 為美國交易所的交易清算股票永續期貨')
        self.assertEqual(translated,'CFTC 核准股票永續期貨在美國交易所交易')

    def test_exact_copies_do_not_apply_to_changed_source(self):
        text='可能要求旋轉密鑰'
        self.assertEqual(repair_translation(GITBOOK+' in a simulation',text),text)
        self.assertEqual(repair_translation('CFTC clears stock trades through a clearinghouse','CFTC 清算股票交易'),'CFTC 清算股票交易')

    def test_verified_five_ways_explainer_is_knowledge_not_security_alert(self):
        row=self.row(EDUCATION)
        self.assertFalse(news_editorial.safety_candidate(row))
        self.assertEqual(inbox.topic(row),'research')

    def test_explainer_with_new_incident_does_not_use_verified_exception(self):
        row=self.row((EDUCATION[0],EDUCATION[1]+' A new ongoing hack today drains another $5 million.'))
        self.assertTrue(news_editorial.safety_candidate(row))

if __name__=='__main__': unittest.main()
