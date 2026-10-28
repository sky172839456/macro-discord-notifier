import copy
import json
import os
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from notification_format import apply_delivery_format
from notification_layout import readable_card, text_size, paragraphs, SPACER
import slim_preview
import market_brief_v2 as brief


class ReadableLayoutTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"SLIM_NOTIFICATIONS":"1"})
        self.env.start();self.addCleanup(self.env.stop)

    def row(self):
        return {"title":"結果","description":"### 本次數值\n本次 +0.2%\n• 尚未修訂\n• 非預測",
                "fields":[{"name":"數值","value":"**BTC**\n$80,000.00\n來源：https://example.invalid/a?x=1&y=2","inline":True},
                          {"name":"資料時間","value":"2026/10/29 07:04","inline":True}],
                "timestamp":"2026-10-28T23:04:00+00:00"}

    def normalized(self,text):
        return re.sub(r"\s+","",text.replace("\u200b",""))

    def test_real_delivery_keeps_every_fact_link_time_and_input_unchanged(self):
        row=self.row();original=copy.deepcopy(row)
        card=apply_delivery_format(row,"macro_alerts")
        self.assertEqual(row,original)
        self.assertEqual(card["timestamp"],row["timestamp"])
        self.assertEqual(self.normalized(card["description"]),self.normalized(row["description"]))
        for a,b in zip(card["fields"],row["fields"]):
            self.assertEqual(self.normalized(a["value"]),self.normalized(b["value"]))
            self.assertFalse(a["inline"])
        self.assertTrue(card["fields"][0]["value"].endswith(SPACER))
        self.assertIn("### 本次數值\n\n本次",card["description"])

    def test_layout_is_idempotent(self):
        row=self.row()
        first=readable_card(copy.deepcopy(row))
        self.assertEqual(readable_card(copy.deepcopy(first)),first)

    def test_long_field_falls_back_without_truncating_link_or_numeric_value(self):
        url="\nhttps://example.invalid/a?amount=-123.45"
        value="資"*(1023-len(url))+url
        row={"fields":[{"name":"長資料","value":value},{"name":"下一段","value":"保留"}]}
        card=readable_card(row)
        self.assertEqual(card["fields"][0]["value"],value)
        self.assertLessEqual(len(value),1024)

    def test_total_limit_skips_optional_whitespace_without_losing_content(self):
        row={"title":"標題","description":"",
             "fields":[{"name":"來源","value":"https://example.invalid/"},
                       {"name":"區塊一","value":"乙"*950},
                       {"name":"區塊二","value":"丙"*950}]}
        row["description"]="• "+"甲"*(5899-text_size(row)-6)+"\n• 乙"
        self.assertEqual(text_size(row),5899)
        card=readable_card(copy.deepcopy(row))
        self.assertLessEqual(text_size(card),5900)
        self.assertEqual(self.normalized(card["description"]),self.normalized(row["description"]))
        self.assertEqual(card["fields"][0]["value"],row["fields"][0]["value"])

    def test_near_description_limit_has_no_truncation(self):
        value="• "+"甲"*2045+"\n• "+"乙"*2045
        row={"description":value,"fields":[]}
        card=readable_card(row)
        self.assertLessEqual(len(card["description"]),4096)
        self.assertEqual(self.normalized(card["description"]),self.normalized(value))

    def test_code_blocks_are_untouched(self):
        fenced=chr(96)*3+"\n**BTC**\n• code\n"+chr(96)*3
        self.assertEqual(paragraphs(fenced),fenced)

    def test_market_news_macro_and_risk_previews_fit_after_shared_format(self):
        now=datetime(2026,10,29,0,tzinfo=timezone.utc)
        for channel,card in slim_preview.cards(now):
            result=apply_delivery_format(card,channel)
            self.assertLessEqual(text_size(result),6000)
            self.assertLessEqual(len(result.get("description","")),4096)
            self.assertTrue(all(len(f["value"])<=1024 for f in result["fields"]))
            self.assertTrue(all(not f["inline"] for f in result["fields"]))

    def test_admin_logs_use_same_spacing_without_removing_status(self):
        row={"title":"巡檢","description":"• 來源一失敗\n• 備援僅補日期",
             "fields":[{"name":"數量","value":"7個日期"},{"name":"詳細","value":"不是完整日程"}]}
        card=apply_delivery_format(row,"bot_log")
        self.assertIn("資料狀態",card["fields"][-1]["name"])
        self.assertIn("\n\n• 備援",card["description"])
        self.assertIn("7個日期",card["fields"][0]["value"])

    def test_legacy_mode_does_not_gain_new_spacing(self):
        with patch.dict(os.environ,{"SLIM_NOTIFICATIONS":"0"}):
            card=apply_delivery_format({"title":"範例","description":"• 甲\n• 乙","fields":[]},"crypto_news")
        self.assertEqual(card["description"],"• 甲\n• 乙")

    def test_market_coin_groups_and_metadata_are_separate(self):
        now=datetime(2026,10,29,0,tzinfo=timezone.utc)
        data={"crypto":{s:{"price":v,"change_24h":.2,"updated_at":now.timestamp()} for s,v in [("BTC",80000),("ETH",2500)]}}
        text=brief.price_lines(data,None,now,False)
        self.assertIn("資料更新：10/29 08:00\n\n**ETH**",text)
        self.assertIn("\n\n[CoinGecko]",text)

    def test_market_cap_and_sentiment_keep_units_and_comparison(self):
        now=datetime(2026,10,29,0,tzinfo=timezone.utc)
        data={"global":{"market_cap":2.74e12,"market_cap_change_24h":-2.15,"btc_dominance":59.46,"timestamp":now.timestamp()},
              "sentiment":{"value":51,"classification":"Neutral","timestamp":now.timestamp(),"previous_value":48,"previous_timestamp":now.timestamp()-86400}}
        glob=brief.global_lines(data,now)
        self.assertIn("2.74兆美元**\n24h **-2.15%",glob)
        self.assertIn("\n來源：[CoinGecko]",glob)
        sent=brief.sentiment_lines(data,now)
        self.assertIn("51/100｜中性**\n較前一日 +3.00分",sent)
        self.assertIn("\n\n情緒不等同漲跌預測",sent)

if __name__=="__main__":
    unittest.main()

