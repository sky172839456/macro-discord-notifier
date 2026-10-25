import copy
import os
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import crypto_news_notifier as news
import news_editorial as editorial
import news_streams as streams
import news_verified_context as context
import test_news_streams as stream_tests

class VerifiedNewsContextTests(unittest.TestCase):
    def setUp(self):
        p=patch.dict(os.environ,{"SLIM_NOTIFICATIONS":"1","NEWS_AUTO_RECOVERY":"1","NEWS_SPLIT_STREAMS":"1"})
        p.start();self.addCleanup(p.stop)
        self.now=datetime(2026,10,24,12,4,43,tzinfo=timezone.utc)
    def row(self,title,summary,url,name="one",hours=1):
        return dict(id=name,title=title,summary=summary,url=url,source=name,official=False,
                    published=self.now-timedelta(hours=hours),category=news.CATEGORIES[2],
                    title_zh="已核對的來源標題",summary_zh_points=["來源摘要已確認"],auto_copy_version=2)
    def core_pair(self):
        a=self.row(context.CORE_TITLES[0],"AI-assisted bug finding changed disclosure policy.","https://ct.invalid/core","ct",31.5)
        b=self.row(context.CORE_TITLES[1],"Developers backport fixes and release patched software.","https://decrypt.invalid/core","decrypt",18.8)
        return a,b
    def solana_pair(self):
        a=self.row("Solana's biggest network change since 2020 is live. Here's how users benefit",
                   "The voting system targets 150 milliseconds; existing wallets continue working.",
                   "https://www.coindesk.com"+context.SOLANA_PATH,"cd",6.6)
        b=self.row("Solana Alpenglow Goes Live in 'Most Ambitious' Upgrade Since Ethereum's Merge",
                   "The consensus protocol replaces TowerBFT, used since 2020.",
                   "https://decrypt.co/381484/solana-upgrade","decrypt",21.7)
        return a,b
    def test_same_activation_keeps_both_sources_and_ids(self):
        a,b=self.solana_pair()
        self.assertTrue(news.same_news_event(a,b))
        kept=news.deduplicate([a,b])
        self.assertEqual(len(kept),1)
        self.assertEqual(set(editorial.member_ids(kept[0])),{"cd","decrypt"})
        self.assertEqual(len(kept[0].get("related_sources",[])),1)
    def test_activation_changes_remain_visible(self):
        a,b=self.solana_pair()
        for extra in (" New exploit confirmed."," It has not replaced TowerBFT."," Targets 200 milliseconds."," New outage reported.",
                      " Quantumglow is proposed."," Fees change to 0.8 SOL."," Additional victims reported."):
            with self.subTest(extra=extra):
                self.assertFalse(news.same_news_event(a,{**b,"summary":b["summary"]+extra}))
        self.assertFalse(news.same_news_event(a,{**b,"title":b["title"].replace("Goes Live","Plans Launch")}))
        self.assertFalse(news.same_news_event(a,{**b,"published":a["published"]+timedelta(hours=25)}))
    def test_core_policy_category_and_incident_protection(self):
        a,b=self.core_pair()
        self.assertEqual(news.category_for(b["title"]+" "+b["summary"])["key"],"network")
        self.assertFalse(context.core_policy_text(b["title"]+" New exploit confirmed."))
        for extra in (" New vulnerabilities are under active attack.", " The policy was not adopted.",
                      " Developers revoked the policy.", " Additional victims confirmed."):
            with self.subTest(extra=extra):
                self.assertFalse(context.core_policy_text(b["title"]+extra))
                self.assertFalse(context.same_verified_event(a,{**b,"summary":b["summary"]+extra}))
        self.assertTrue(news.same_news_event(a,b))
        self.assertFalse(news.same_news_event(a,{**b,"summary":b["summary"]+" Losses revised to $20M."}))
    def test_only_verified_context_history_gets_bounded_retention(self):
        a,_=self.core_pair()
        saved=editorial.history_row(a,self.now-timedelta(hours=24,seconds=3))
        self.assertTrue(context.keep_history(saved,self.now))
        self.assertFalse(context.keep_history({**saved,"title":"Unrelated story"},self.now))
        self.assertFalse(context.keep_history({**saved,"date":self.now-timedelta(hours=49)},self.now))
    def test_actual_split_stream_does_not_repeat_next_day_policy(self):
        fixture=stream_tests.StreamTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.now=self.now
        a,b=self.core_pair()
        state={"initialized":True,"finance_initialized":True,"seen":{},"pending":[],
               "headline_history":[editorial.history_row(a,self.now-timedelta(hours=24,seconds=3))]}
        with patch("news_auto_recovery.route",side_effect=lambda rows,*_:rows):
            send=fixture.run_rows([b],state)
        send.assert_not_called()
        self.assertIn(b["id"],state["seen"])
    def test_swiss_unchanged_source_version_is_not_republished(self):
        summary="BIT Asset Management expects its ETF to trade on SIX Swiss Exchange in November; offering is restricted to Switzerland."
        a=self.row("Switzerland approves first spot Bitcoin ETF for retail investors",summary,
                   "https://cointelegraph.com"+context.SWISS_PATH,"old")
        b={**a,"id":"new","title":"Switzerland's first retail spot Bitcoin ETF targets November launch"}
        self.assertTrue(news.same_news_event(a,b))
        for changed in ({**b,"summary":summary+" Losses rise to $20M."},
                        {**b,"title":b["title"].replace("November","December")},
                        {**b,"published":b["published"]+timedelta(hours=1)},
                        {**b,"title":"Switzerland revokes Bitcoin ETF approval"}):
            self.assertFalse(context.same_swiss_launch_version(a,changed))

if __name__=="__main__":unittest.main()
