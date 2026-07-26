import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import derivatives_notifier
import risk_notifier
import summary_notifier


class ReliabilityMonitorTests(unittest.TestCase):
    def test_derivatives_card_uses_actual_observation_interval(self):
        item = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "open_interest_usd": 1_000_000.0,
            "funding_rate": 0.01,
            "next_funding": 0,
        }
        card = derivatives_notifier.alert_embed(
            item, 3.2, 8.5, "warning", interval_minutes=137
        )
        self.assertIn("約 137 分鐘變化", card["description"])

    def test_risk_monitor_danger_alerts_on_first_observation(self):
        state = {"counts": {}, "active": {}, "incidents": {"baseline": "ok"}}
        prices = {"USDT-USD": 0.98, "USDC-USD": 1.0, "DAI-USD": 1.0}

        def fake_json(url):
            if url == risk_notifier.STATUS_URL:
                return {"incidents": []}
            pair = url.split("/products/")[1].split("/ticker")[0]
            return {"price": str(prices[pair])}

        with patch.object(risk_notifier, "load", return_value=state), \
             patch.object(risk_notifier, "save"), \
             patch.object(risk_notifier, "get_json", side_effect=fake_json), \
             patch.object(risk_notifier, "send") as send:
            risk_notifier.monitor("https://discord.invalid")
        send.assert_called_once()
        self.assertTrue(state["active"]["USDT"])

    def test_production_monitors_do_not_fall_back_to_test_webhook(self):
        source = Path(risk_notifier.__file__).read_text(encoding="utf-8")
        self.assertIn("DISCORD_RISK_WEBHOOK_URL", source)
        source = Path(derivatives_notifier.__file__).read_text(encoding="utf-8")
        self.assertIn("DISCORD_DERIVATIVES_WEBHOOK_URL", source)

    def test_only_one_high_frequency_schedule_remains(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        realtime = (workflows / "realtime-monitors.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "6,11,16,21,26,31,36,41,46,51,56 * * * *"', realtime)
        for name in (
            "macro.yml", "bybit-monitor.yml", "exchange-announcements.yml",
            "crypto-news.yml", "risk-monitor.yml", "derivatives-test.yml",
            "market-summaries.yml",
        ):
            self.assertNotIn("cron:", (workflows / name).read_text(encoding="utf-8"))

    def test_summary_scheduler_baselines_without_duplicate_then_sends_next_day(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "summaries.json"
            with patch.object(summary_notifier, "SCHEDULE_STATE", state_file), \
                 patch.object(summary_notifier, "run") as send:
                first = summary_notifier.run_scheduled(
                    datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc)
                )
                second = summary_notifier.run_scheduled(
                    datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
                )
            self.assertEqual(first, [])
            self.assertEqual(second, ["daily", "weekly"])
            self.assertEqual(send.call_count, 2)


if __name__ == "__main__":
    unittest.main()
