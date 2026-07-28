import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analysis_notifier
import crypto_news_notifier


class AnalysisNotifierTests(unittest.TestCase):
    def test_technical_snapshot_calculates_indicators(self):
        rows = [
            {"open": float(i), "high": float(i + 2), "low": float(i - 1), "close": float(i + 1)}
            for i in range(1, 61)
        ]
        with patch.object(analysis_notifier, "candles", return_value=rows):
            item = analysis_notifier.technical_snapshot("BTC")
        self.assertEqual(item["symbol"], "BTC")
        self.assertGreater(item["sma20"], item["sma50"])
        self.assertEqual(item["rsi"], 100.0)

    def test_macro_embed_uses_bp_for_treasury(self):
        dashboard = {"traditional": {
            "DXY": {"price": 100.0, "change": 0.1},
            "US10Y": {"price": 4.5, "change_bp": -2.0},
            "GOLD": {"price": 4000.0, "change": 0.2},
            "NASDAQ": {"price": 25000.0, "change": -1.0},
        }, "errors": {}}
        card = analysis_notifier.macro_embed(dashboard, [], None, datetime.now(timezone.utc))
        self.assertIn("-2.0 bp", card["fields"][0]["value"])
        self.assertIn("未來三日", card["fields"][1]["name"])

    def test_specialized_news_routes_once(self):
        default = "https://discord.invalid/general"
        item = {"category": crypto_news_notifier.CATEGORIES[1]}
        with patch.dict(os.environ, {
            "DISCORD_REGULATION_ETF_WEBHOOK_URL": "https://discord.invalid/regulation",
        }, clear=True):
            destination, username = crypto_news_notifier.destination_for(item, default)
        self.assertEqual(destination, "https://discord.invalid/regulation")
        self.assertIn("ETF", username)

    def test_specialized_news_falls_back_when_secret_missing(self):
        default = "https://discord.invalid/general"
        item = {"category": crypto_news_notifier.CATEGORIES[0]}
        with patch.dict(os.environ, {}, clear=True):
            destination, username = crypto_news_notifier.destination_for(item, default)
        self.assertEqual(destination, default)
        self.assertEqual(username, "加密新聞雷達")

    def test_daily_analysis_sends_once(self):
        now = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(analysis_notifier, "STATE_FILE", Path(directory) / "state.json"), \
             patch.object(analysis_notifier, "run", return_value=["macro", "technical"]) as run:
            first = analysis_notifier.run_scheduled(now)
            second = analysis_notifier.run_scheduled(now)
        self.assertEqual(first, ["macro", "technical"])
        self.assertEqual(second, [])
        run.assert_called_once()

    def test_template_preview_uses_only_shared_test_webhook(self):
        now = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)
        snapshot = {
            "symbol": "BTC",
            "price": 100.0,
            "change": 1.0,
            "sma20": 95.0,
            "sma50": 90.0,
            "rsi": 55.0,
            "high20": 110.0,
            "low20": 80.0,
        }
        environment = {
            "DISCORD_TEST_WEBHOOK_URL": "https://discord.invalid/test",
            "DISCORD_MACRO_ANALYSIS_WEBHOOK_URL": "https://discord.invalid/macro",
            "DISCORD_TECHNICAL_ANALYSIS_WEBHOOK_URL": "https://discord.invalid/technical",
        }
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(analysis_notifier, "collect_dashboard", return_value={"traditional": {}, "errors": {}}), \
             patch.object(analysis_notifier, "upcoming_events", return_value=([], None)), \
             patch.object(analysis_notifier, "technical_snapshot", side_effect=[snapshot, {**snapshot, "symbol": "ETH"}]), \
             patch.object(analysis_notifier, "send") as send:
            sent = analysis_notifier.run(now, test=True)

        self.assertEqual(sent, ["macro", "technical"])
        self.assertEqual(send.call_count, 2)
        self.assertTrue(all(call.args[0] == environment["DISCORD_TEST_WEBHOOK_URL"] for call in send.call_args_list))
        self.assertTrue(all(call.args[2]["title"].startswith("🧪 測試｜") for call in send.call_args_list))


if __name__ == "__main__":
    unittest.main()
