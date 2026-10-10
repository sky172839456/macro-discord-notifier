import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import analysis_notifier
import bybit_notifier
import crypto_news_notifier
import notifier
import summary_notifier
from notification_format import apply_delivery_format, bilingual_sections


class ConsolidationRegressionTests(unittest.TestCase):
    def test_combined_daily_report_sends_once_when_technical_source_fails(self):
        with patch.object(summary_notifier, "collect_dashboard", return_value={}), \
             patch.object(summary_notifier, "current_market", return_value={}), \
             patch.object(summary_notifier, "upcoming_events", return_value=([], None)), \
             patch.object(summary_notifier, "build_embed", return_value={"fields": []}), \
             patch.object(analysis_notifier, "technical_snapshot", side_effect=RuntimeError("unavailable")), \
             patch.object(summary_notifier, "send") as send:
            summary_notifier.run("daily", datetime.now(timezone.utc), dry_run=True)
        send.assert_called_once()
        field = send.call_args.args[1]["fields"][0]
        self.assertIn("BTC 技術資料暫缺", field["value"])
        self.assertIn("ETH 技術資料暫缺", field["value"])

    def test_cross_source_headlines_normalize_without_hiding_changed_amounts(self):
        left = "US Government Moves $1 Billion in Bitcoin Seized From Bitfinex Hacker"
        right = "U.S. government moves $1 billion in bitcoin tied to Bitfinex hack, with no sign of sale"
        self.assertTrue(crypto_news_notifier.similar_title(left, right))
        self.assertFalse(crypto_news_notifier.similar_title(left, left.replace("$1 Billion", "$2 Billion")))

    def test_routing_audit_reports_channel_mismatch_without_secret(self):
        import io
        import json
        import routing_audit
        with patch.object(routing_audit, "urlopen", return_value=io.BytesIO(b'{"channel_id":"wrong"}')):
            results = routing_audit.audit({"DISCORD_LOG_WEBHOOK_URL": "https://example.invalid/SECRET"})
        self.assertEqual(results[1]["status"], "wrong_channel")
        self.assertNotIn("SECRET", json.dumps(results))

    def test_fomc_speech_is_not_a_rate_decision(self):
        self.assertEqual(notifier.classify("FOMC Member Waller Speaks governor speech")["key"], "fed_official")
        self.assertEqual(notifier.classify("FOMC monetary policy statement")["key"], "fomc")

    def test_perps_and_promotions_are_not_spot_listings(self):
        self.assertEqual(bybit_notifier.announcement_kind("Bitget listed CEGUSDT hot stock perps"), "perpetual")
        self.assertEqual(bybit_notifier.announcement_kind("OKX to list AXSUSD X-Perp"), "perpetual")
        self.assertIsNone(bybit_notifier.announcement_kind("Cash Plus Dual Rewards: Earn More on Futures Positions"))
        self.assertIsNone(bybit_notifier.announcement_kind("Adjust funding rate for KAIAUSDT perpetual futures"))

    def test_spot_page_does_not_pick_up_sitewide_leverage_ad(self):
        with patch.object(bybit_notifier, "text", return_value="Trade with 1000x leverage and 000x leverage"):
            details = bybit_notifier.listing_details({"title": "MAGIC gets listed on BingX Spot", "url": "https://example.invalid", "source_type": "announcement"})
        self.assertFalse(any("槓桿" in line for line in details))

    def test_closed_candles_only(self):
        row = ["1", "1", "2", "1", "2", "1", "1", "1", "1"]
        open_row = ["2", "1", "9", "1", "9", "1", "1", "1", "0"]
        with patch.object(analysis_notifier, "get_json", return_value={"code": "0", "data": [open_row, row]}):
            self.assertEqual(analysis_notifier.candles("BTC"), [{"open": 1., "high": 2., "low": 1., "close": 2.}])

    def test_merged_mode_stops_duplicate_daily_analysis(self):
        with patch.dict(os.environ, {"CONSOLIDATED_CHANNELS": "1"}), patch.object(analysis_notifier, "run") as run:
            self.assertEqual(analysis_notifier.run_scheduled(datetime.now(timezone.utc)), [])
            run.assert_not_called()

    def test_compact_delivery_keeps_chinese_and_original_source_title(self):
        description = bilingual_sections(original_title="Original title", english_summary="Long summary.", english_points=["Long summary."], zh_title="中文標題", zh_points=["中文重點"])
        card = apply_delivery_format({"description": description}, "crypto_news")
        self.assertTrue(card["description"].startswith("**📌 繁中標題**"))
        self.assertIn("Original title", card["description"])
        self.assertNotIn("英文摘要", card["description"])

    def test_old_criminal_case_is_not_an_immediate_security_alert(self):
        self.assertEqual(crypto_news_notifier.category_for("Crypto stolen fraudster jailed")["priority"], "normal")


if __name__ == "__main__":
    unittest.main()
