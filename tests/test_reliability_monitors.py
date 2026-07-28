import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import derivatives_notifier
import bybit_notifier
import crypto_news_notifier
import notifier
import realtime_health
import risk_notifier
import summary_notifier


class ReliabilityMonitorTests(unittest.TestCase):
    def test_heartbeat_warns_after_more_than_ten_minutes_of_extra_delay(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "health.json"
            first = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)
            delayed = datetime(2026, 7, 29, 0, 16, tzinfo=timezone.utc)
            with patch.object(realtime_health, "send_webhook") as send:
                self.assertIsNone(realtime_health.begin(first, "https://discord.invalid", state_file))
                self.assertEqual(
                    realtime_health.begin(delayed, "https://discord.invalid", state_file),
                    16,
                )
            send.assert_called_once()
            self.assertIn("排程間隔異常", send.call_args.args[1]["title"])
            self.assertIn("加長回補視窗", send.call_args.args[1]["description"])

    def test_daily_execution_health_reports_once_and_lists_every_monitor(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "health.json"
            now = datetime(2026, 7, 29, 0, 5, tzinfo=timezone.utc)
            results = {
                name: ("ok", "本輪執行完成")
                for name in realtime_health.MONITOR_LABELS
            }
            with patch.object(realtime_health, "send_webhook") as send:
                self.assertTrue(
                    realtime_health.finish(now, results, "https://discord.invalid", state_file)
                )
                self.assertFalse(
                    realtime_health.finish(now, results, "https://discord.invalid", state_file)
                )
            send.assert_called_once()
            card = send.call_args.args[1]
            self.assertIn("全部正常", card["title"])
            for name in realtime_health.MONITOR_LABELS:
                self.assertIn(name, card["description"])

    def test_daily_health_never_labels_skipped_monitor_as_normal(self):
        results = {
            name: ("ok", "本輪執行完成")
            for name in realtime_health.MONITOR_LABELS
        }
        results["衍生品"] = ("skipped", "Webhook 未設定")
        card = realtime_health.daily_health_embed(
            results,
            {"last_gap_minutes": 5},
            datetime(2026, 7, 29, 0, 5, tzinfo=timezone.utc),
        )
        self.assertIn("1 個監控未設定", card["title"])
        self.assertNotIn("全部正常", card["title"])
        self.assertIn("未執行項目不會被標示為正常", card["fields"][-1]["value"])

    def test_recovery_windows_cover_multi_hour_github_delays(self):
        self.assertEqual(notifier.RELEASE_BACKFILL_MINUTES, 48 * 60)
        self.assertEqual(crypto_news_notifier.RECENT_HOURS, 48)
        self.assertEqual(bybit_notifier.LISTING_BACKFILL_HOURS, 72)

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
        state = {
            "counts": {}, "active": {}, "incidents": {"baseline": "ok"},
            "exchange_events": {
                "BybitStatus": {"baseline": "ok"},
                "CriticalNotices": {"baseline": "ok"},
            },
        }
        prices = {"USDT-USD": 0.98, "USDC-USD": 1.0, "DAI-USD": 1.0}

        def fake_json(url):
            if url == risk_notifier.STATUS_URL:
                return {"incidents": []}
            pair = url.split("/products/")[1].split("/ticker")[0]
            return {"price": str(prices[pair])}

        with patch.object(risk_notifier, "load", return_value=state), \
             patch.object(risk_notifier, "save"), \
             patch.object(risk_notifier, "get_json", side_effect=fake_json), \
             patch.object(risk_notifier, "bybit_incidents", return_value=[]), \
             patch.object(risk_notifier, "critical_official_notices", return_value=[]), \
             patch.object(risk_notifier, "send") as send:
            risk_notifier.monitor("https://discord.invalid")
        send.assert_called_once()
        self.assertTrue(state["active"]["USDT"])

    def test_exchange_incident_embed_has_traditional_chinese_and_original(self):
        card = risk_notifier.exchange_incident_embed("Coinbase", {
            "name": "Degraded Performance - Transactions",
            "status": "resolved",
            "incident_updates": [{"body": "This incident has been resolved."}],
            "shortlink": "https://status.coinbase.com/",
        })
        self.assertIn("交易服務", card["title"])
        self.assertIn("繁中重點", card["description"])
        self.assertIn("This incident has been resolved.", card["description"])
        self.assertEqual(card["fields"][0]["value"], "已恢復（resolved）")

    def test_bybit_status_parser_normalizes_official_events(self):
        with patch.object(risk_notifier, "get_json", return_value={
            "retCode": 0,
            "result": {"list": [{
                "id": "42",
                "title": "System Maintenance",
                "state": "scheduled",
                "beginTime": "2026-07-28T01:00:00Z",
            }]},
        }):
            items = risk_notifier.bybit_incidents()
        self.assertEqual(items[0]["id"], "42")
        self.assertEqual(items[0]["state"], "scheduled")
        self.assertIn("bybit.com", items[0]["url"])

    def test_critical_notice_filter_includes_bitget_and_excludes_maintenance(self):
        critical = {"key": "outage", "label": "服務中斷／異常", "icon": "🔴"}
        maintenance = {"key": "maintenance", "label": "維護", "icon": "🛠️"}

        def fake_items(exchange, _url):
            category = critical if exchange == "Bitget" else maintenance
            return [{
                "id": exchange, "exchange": exchange, "title": "Official notice",
                "url": f"https://{exchange}.invalid", "category": category,
            }]

        with patch("exchange_announcement_notifier.page_items", side_effect=fake_items):
            items = risk_notifier.critical_official_notices()
        self.assertEqual([item["exchange"] for item in items], ["Bitget"])

    def test_empty_initial_baseline_does_not_hide_next_new_exchange_event(self):
        state = {"counts": {}, "active": {}, "incidents": {}, "exchange_events": {}}
        normal_prices = {"price": "1.0"}
        notice = {
            "id": "new-risk", "exchange": "Bitget",
            "title": "Official service outage",
            "url": "https://www.bitget.com/support/articles/new-risk",
            "category": {"key": "outage", "label": "服務中斷／異常", "icon": "🔴"},
        }
        with patch.object(risk_notifier, "load", return_value=state), \
             patch.object(risk_notifier, "save"), \
             patch.object(risk_notifier, "get_json", return_value=normal_prices), \
             patch.object(risk_notifier, "bybit_incidents", return_value=[]), \
             patch.object(risk_notifier, "critical_official_notices", side_effect=[[], [notice]]), \
             patch.object(risk_notifier, "send") as send:
            risk_notifier.monitor("https://discord.invalid")
            risk_notifier.monitor("https://discord.invalid")
        send.assert_called_once()
        self.assertIn("Bitget", send.call_args.args[1]["title"])

    def test_production_monitors_do_not_fall_back_to_test_webhook(self):
        source = Path(risk_notifier.__file__).read_text(encoding="utf-8")
        self.assertIn("DISCORD_RISK_WEBHOOK_URL", source)
        source = Path(derivatives_notifier.__file__).read_text(encoding="utf-8")
        self.assertIn("DISCORD_DERIVATIVES_WEBHOOK_URL", source)

    def test_macro_test_health_preview_stays_on_test_webhook(self):
        source = Path(__file__).resolve().parents[1].joinpath("notifier.py").read_text(encoding="utf-8")
        test_branch = source.split("if args.test_notification:", 1)[1]
        self.assertIn('webhook = os.environ.get("DISCORD_TEST_WEBHOOK_URL")', test_branch)
        self.assertIn("send_discord(webhook, health_embed(", test_branch)
        self.assertNotIn("send_discord(log_webhook, health_embed(", test_branch)

    def test_only_one_high_frequency_schedule_remains(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        realtime = (workflows / "realtime-monitors.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "6,11,16,21,26,31,36,41,46,51,56 * * * *"', realtime)
        self.assertIn("python realtime_health.py --begin", realtime)
        self.assertIn("python realtime_health.py --finish", realtime)
        self.assertIn(".state/realtime-health.json", realtime)
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
