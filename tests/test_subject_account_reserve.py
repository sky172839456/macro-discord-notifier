import copy
import hashlib
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from xml.sax.saxutils import escape

import crypto_news_notifier as news
import news_auto_recovery as auto
import news_streams
import notification_quality as quality
import slim_policy
from news_copy_terms import repair_translation

BITHUMB = "Bithumb hacked through employee system as South Korean financial firms face cyberattacks"
WRONG = "由於韓國金融公司面臨網路攻擊， Bithumb 駭入員工系統"
BODY = ("The breach hit an internal employee system that Bithumb says is separate from its trading platform, "
        "while the exchange is still determining whether customer information was exposed.")
BODY_ZH = "Bithumb表示遭入侵的是獨立於交易平台的內部員工系統，客戶資訊是否外洩仍在確認。"
XRP = "XRP Ledger developers propose creating wallets with zero XRP for stablecoin payments"
XBODY = ("An experimental change would let companies cover the reserve for customer and AI-agent accounts, "
         "allowing users to start with stablecoins without first acquiring XRP.")
XZH = "XRP Ledger開發人員提案讓穩定幣支付錢包無須先取得XRP"
XBZH = "這項實驗性變更將允許企業負擔客戶與AI代理帳戶的儲備要求，使用者可先使用穩定幣而不必取得XRP。"
NOW = datetime(2026, 10, 28, 12, 30, tzinfo=timezone.utc)
XURL = "https://www.coindesk.com/tech/2026/10/28/xrp-ledger-developers-propose-creating-wallets-with-zero-xrp-for-stablecoin-payments"

class SubjectAndAccountReserveTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"SLIM_NOTIFICATIONS":"1","NEWS_AUTO_RECOVERY":"1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def row(self):
        return {"id":"xrp-unsent","title":XRP,"summary":XBODY,"title_zh":XZH,
                "summary_zh_points":[XBZH],"auto_copy_version":2,"source":"CoinDesk",
                "published":NOW,"url":XURL,"official":False,
                "category":next(c for c in news.CATEGORIES if c["key"]=="etf")}

    def test_observed_bithumb_subject_is_repaired(self):
        text = auto.checked_copy(BITHUMB, WRONG)
        self.assertIn("Bithumb 遭駭", text)
        self.assertIn("員工系統", text)
        self.assertNotIn("Bithumb 駭入", text)

    def test_cached_final_card_repairs_headline_and_keeps_body_uncertainty(self):
        row = dict(self.row(),title=BITHUMB,title_zh=WRONG,summary=BODY,
                   summary_zh_points=[BODY_ZH],
                   category=next(c for c in news.CATEGORIES if c["key"]=="security"))
        card = slim_policy.news_card(row,now=NOW)
        self.assertIn("Bithumb 遭駭",card["title"])
        self.assertIn("獨立於交易平台",card["description"])
        self.assertIn("是否外洩仍在確認",card["description"])

    def test_cached_translation_is_rechecked_without_provider_or_cache_reset(self):
        cache={}
        for source,text in [(BITHUMB,WRONG),(BODY,BODY_ZH)]:
            key="auto-v2-"+hashlib.sha256(source.encode()).hexdigest()[:24]
            cache[key]={"source":source,"translated":text,"date":"2026-10-28"}
        state={"translation_cache":copy.deepcopy(cache)}
        row=dict(self.row(),title=BITHUMB,summary=BODY,auto_copy_version=1)
        with patch.object(news,"translate_text",side_effect=AssertionError("no provider")):
            fixed=auto.enrich(row,state,NOW)
        self.assertIn("Bithumb 遭駭",fixed["title_zh"])
        self.assertEqual(state["translation_cache"],cache)

    def test_changed_source_is_not_fixed_to_old_facts_but_actor_reversal_rejected(self):
        changed=BITHUMB+"; customer data exposure remains unconfirmed"
        self.assertEqual(repair_translation(changed,"Bithumb遭駭，客戶資料外洩仍未確認"),"Bithumb遭駭，客戶資料外洩仍未確認")
        with self.assertRaisesRegex(ValueError,"victim and attacker"):
            auto.checked_copy(changed,WRONG)

    def test_correct_passive_or_attacker_sentence_survives_on_changed_source(self):
        source="Bithumb was hacked through an employee system"
        for translated in ("Bithumb員工系統遭駭","駭客經員工系統入侵Bithumb"):
            self.assertEqual(auto.checked_copy(source,translated),translated)

    def test_explicit_active_attack_is_not_reversed(self):
        source="Security researchers hacked an employee system in an authorized test"
        translated="安全研究人員在授權測試中入侵員工系統"
        self.assertEqual(repair_translation(source,translated),translated)
        self.assertEqual(repair_translation("Bithumb hacked an employee system in an authorized test","Bithumb在授權測試中入侵員工系統"),"Bithumb在授權測試中入侵員工系統")

    def test_denial_and_possible_event_never_receive_fixed_confirmed_copy(self):
        for source,text in [
            ("Bithumb denies being hacked through employee system","Bithumb否認員工系統遭駭"),
            ("Bithumb may have been hacked through employee system","Bithumb員工系統可能遭駭")]:
            self.assertEqual(auto.checked_copy(source,text),text)
        with self.assertRaises(ValueError):
            auto.checked_copy("Bithumb may have been hacked through employee system","Bithumb遭駭")

    def test_invented_figures_remain_rejected(self):
        with self.assertRaises(ValueError):
            auto.checked_copy(BITHUMB,WRONG+"，損失200萬美元")

    def test_actual_xrp_account_reserve_is_protocol_not_etf(self):
        result=news.category_for(XRP+" "+XBODY)
        self.assertEqual(result["key"],"network")
        self.assertEqual(result["priority"],"normal")

    def test_explicit_etf_institutional_and_treasury_contexts_keep_route(self):
        for suffix in (" A spot XRP ETF launched.", " BlackRock invests in XRP.",
                       " Institutional funds cover wallet reserves.", " A corporate treasury buys XRP."):
            with self.subTest(suffix=suffix):
                self.assertEqual(news.category_for(XRP+" "+XBODY+suffix)["key"],"etf")

    def test_security_and_regulation_keep_precedence(self):
        for suffix,key in [(" A hack exposed accounts.","security"),
                           (" SEC approves the wallet rule.","regulation")]:
            self.assertEqual(news.category_for(XRP+" "+XBODY+suffix)["key"],key)

    def test_non_protocol_reserve_context_is_unchanged(self):
        for text in ("Company holds Bitcoin treasury reserves.",
                     "Fidelity expands ETF reserves.", "XRP investment fund expands reserves."):
            self.assertEqual(news.category_for(text)["key"],"etf")
        self.assertFalse(slim_policy.account_reserve_context("XRP price reserve forecast"))

    def test_reusable_unsent_copy_reclassifies_without_provider_or_input_mutation(self):
        row=self.row()
        with patch.object(news,"translate_text",side_effect=AssertionError("no provider")):
            ready=news.add_translated_title(row,{},NOW)
        self.assertEqual(ready["category"]["key"],"network")
        self.assertEqual(row["category"]["key"],"etf")
        self.assertEqual(ready["published"],NOW)
        self.assertEqual(ready["url"],XURL)
        self.assertIn("區塊鏈／協議",slim_policy.digest_card([ready],NOW)["description"])

    def test_rss_preserves_date_link_and_source_while_fixing_category(self):
        feed=("<rss><channel><item><title>"+escape(XRP)+"</title><description>"+escape(XBODY)+
              "</description><link>"+XURL+"</link><pubDate>Wed, 28 Oct 2026 11:52:14 +0000</pubDate></item></channel></rss>")
        row=news.parse_feed(feed,{"name":"CoinDesk","official":False})[0]
        self.assertEqual(row["category"]["key"],"network")
        self.assertEqual(row["url"],XURL)
        self.assertEqual(row["published"],datetime(2026,10,28,11,52,14,tzinfo=timezone.utc))

    def test_actual_split_stream_pending_path_uses_correct_category_once(self):
        row=self.row()
        stored=news.serialize_pending(row)
        state={"initialized":True,"finance_initialized":True,"seen":{},"pending":[stored],
               "translation_cache":{},"headline_history":[]}
        with patch.dict(os.environ,{"DISCORD_CRYPTO_NEWS_WEBHOOK_URL":"https://crypto.invalid",
                                   "DISCORD_FINANCE_NEWS_WEBHOOK_URL":"https://finance.invalid"}), \
             patch.object(news,"load_state",return_value=state), patch.object(news,"save_state"), \
             patch.object(news,"fetch_all",return_value=([],[("mock",0,None)])), \
             patch.object(news_streams,"fetch_finance",return_value=([],[("mock",0,None)])), \
             patch.object(news,"translate_text",side_effect=AssertionError("no provider")), \
             patch.object(news,"send_discord") as send:
            news_streams.run(NOW)
            news_streams.run(NOW)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0],"https://crypto.invalid")
        self.assertIn("區塊鏈／協議",send.call_args.args[1]["description"])
        self.assertNotIn("ETF／機構",send.call_args.args[1]["description"])
        self.assertIn("xrp-unsent",state["seen"])

    def test_already_seen_item_is_not_reopened(self):
        row=self.row()
        state={"seen":{row["id"]:"2026-10-28"},"headline_history":[]}
        with patch.object(news,"save_state"), patch.object(news,"add_translated_title") as add:
            self.assertEqual(auto.route([row],state,NOW),[])
        add.assert_not_called()

if __name__=="__main__":
    unittest.main()

