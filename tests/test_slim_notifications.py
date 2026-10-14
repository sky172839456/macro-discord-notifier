import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import slim_policy as policy
import slim_risk as risk
import crypto_news_notifier as news
import summary_notifier as summary
import notifier
import slim_preview
import realtime_health


class SlimNotificationsTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"SLIM_NOTIFICATIONS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)  # 20:00 Taiwan

    def article(self, title="Bitcoin holds steady ahead of CPI", identifier="1"):
        return {"id": identifier, "title": title, "title_zh": "比特幣在 CPI 公布前持平", "summary": title,
                "summary_zh_points": ["比特幣市場動態更新。"], "source": "Media", "url": "https://example.invalid/"+identifier,
                "published": self.now, "official": False, "category": news.category_for(title)}

    def test_generic_asset_name_does_not_imply_protocol_upgrade(self):
        category = news.category_for("Bitcoin price holds steady ahead of CPI")
        self.assertEqual(category["key"], "market")
        self.assertEqual(category["priority"], "normal")

    def test_treasury_purchase_is_not_urgent(self):
        self.assertFalse(policy.material_news(self.article("Strategy adds 250 Bitcoin")))
        self.assertFalse(policy.material_news(self.article("Bitcoin ETF traders debate safer custody")))
        self.assertTrue(policy.material_news(self.article("Exchange confirms withdrawals halted after breach")))
        self.assertTrue(policy.material_news(self.article("SEC approves spot Bitcoin ETF")))

    def test_same_purchase_different_media_but_changed_size_remains_new(self):
        self.assertTrue(news.similar_title("Strategy adds 250 Bitcoin as holdings reach 848250 BTC", "Strategy scoops up $21.5M in Bitcoin and buys back STRC"))
        self.assertFalse(policy.same_event("Strategy adds 250 Bitcoin", "Strategy buys 500 Bitcoin"))

    def test_digest_preserves_multiple_sources_without_repeating_event(self):
        rows = policy.merge_pending([self.article("Strategy adds 250 Bitcoin", "a"), self.article("Strategy scoops up $21.5M in Bitcoin", "b")])
        self.assertEqual(len(rows), 1)
        card = policy.digest_card(rows, self.now)
        self.assertIn("/a", card["description"])
        self.assertIn("/b", card["description"])

    def test_daily_news_queues_until_20_and_sends_only_one_card_once(self):
        state = {"initialized": True, "seen": {}, "pending": [], "translation_cache": {}}
        items = [self.article("Strategy adds 250 Bitcoin", "a"), self.article("Bitcoin holds steady ahead of CPI", "b")]
        with patch.dict(os.environ, {"DISCORD_CRYPTO_NEWS_WEBHOOK_URL": "https://discord.invalid"}), patch.object(news, "load_state", return_value=state), patch.object(news, "save_state"), patch.object(news, "fetch_all", return_value=(items, [("source", 2, None)])), patch.object(news, "add_translated_title", side_effect=lambda row, *_: dict(row)), patch.object(news, "send_discord") as send:
            news.run(self.now - timedelta(minutes=10))
            send.assert_not_called()
            self.assertEqual(len(state["pending"]), 2)
            news.run(self.now)
            send.assert_called_once()
            self.assertEqual(len(send.call_args.args[1]), 1)
            news.run(self.now + timedelta(minutes=10))
            send.assert_called_once()

    def test_scheduled_monday_replaces_daily_with_weekly_and_retains_dedupe(self):
        monday = datetime(2026, 10, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.json"
            path.write_text(json.dumps({"daily": "2026-10-11", "weekly": "2026-W41"}))
            with patch.object(summary, "SCHEDULE_STATE", path), patch.object(summary, "run") as send:
                self.assertEqual(summary.run_scheduled(monday), ["weekly"])
                self.assertEqual(summary.run_scheduled(monday+timedelta(minutes=5)), [])
                self.assertEqual(send.call_args.args[0], "weekly")

    def test_summary_has_six_readable_sections_without_technical_table(self):
        card = summary.build_embed("daily", self.now, {"BTC": {"price": 80000, "change": 2}}, None, [], None, {})
        self.assertEqual(len(card["fields"]), 6)
        self.assertNotIn("SMA", json.dumps(card))

    def test_calendar_excludes_routine_speeches_and_tomorrow(self):
        def event(key, offset):
            return {"time": self.now+timedelta(hours=offset), "rule": {"key": key, "name": key, "source": "https://example.invalid"}}
        self.assertEqual([e["rule"]["key"] for e in policy.today_events([event("fed_official", 1), event("cpi", 1), event("jobs", 8)], self.now)], ["cpi"])

    def test_reminders_never_send_three_hours_early_or_after_release(self):
        for minutes, expected in ((176, False), (28, False), (27, True), (15, True), (1, True), (0, False), (-5, False)):
            event = {"rule": {"key": "cpi"}, "time": self.now+timedelta(minutes=minutes)}
            self.assertEqual(policy.reminder_due(event, self.now), expected)
        self.assertFalse(policy.reminder_due({"rule": {"key": "fed_official"}, "time": self.now+timedelta(minutes=15)}, self.now))

    def test_single_source_or_disagreement_cannot_trigger_or_recover(self):
        self.assertIsNone(risk.confirmed_level({"a": .98}))
        self.assertIsNone(risk.confirmed_level({"a": .98, "b": 1.}))
        self.assertIsNone(risk.confirmed_level({"a": float('nan'), "b": .98}))
        self.assertIsNone(risk.confirmed_level({"a": .99, "b": 1.01}))

    def test_persistent_deviation_upgrade_recovery_and_repeat_suppression(self):
        state = {}
        warning = {"a": .993, "b": .992}
        danger = {"a": .98, "b": .981}
        normal = {"a": 1., "b": .999}
        self.assertIsNone(risk.price_transition(state, warning, self.now))
        self.assertIsNone(risk.price_transition(state, warning, self.now+timedelta(seconds=1)))
        self.assertEqual(risk.price_transition(state, warning, self.now+timedelta(minutes=5)), "warning")
        self.assertIsNone(risk.price_transition(state, warning, self.now+timedelta(minutes=10)))
        self.assertIsNone(risk.price_transition(state, danger, self.now+timedelta(minutes=15)))
        self.assertEqual(risk.price_transition(state, danger, self.now+timedelta(minutes=20)), "danger")
        self.assertIsNone(risk.price_transition(state, {}, self.now+timedelta(minutes=25)))
        self.assertEqual(state["active"], "danger")
        self.assertIsNone(risk.price_transition(state, normal, self.now+timedelta(minutes=30)))
        self.assertEqual(risk.price_transition(state, normal, self.now+timedelta(minutes=35)), "recovered")
        self.assertIsNone(risk.price_transition(state, normal, self.now+timedelta(minutes=40)))

    def test_long_gap_restarts_confirmation(self):
        state = {}
        risk.price_transition(state, {"a": .98, "b": .98}, self.now)
        self.assertIsNone(risk.price_transition(state, {"a": .98, "b": .98}, self.now+timedelta(hours=1)))

    def test_planned_maintenance_is_not_a_risk_alert(self):
        self.assertFalse(risk.incident_material({"name": "Withdrawal system maintenance", "status": "scheduled", "impact": "major"}))

    def test_incident_only_first_material_change_and_recovery(self):
        row = {}
        incident = {"name": "ETH withdrawals unavailable", "status": "investigating", "impact": "major"}
        self.assertTrue(risk.incident_transition(row, incident))
        self.assertFalse(risk.incident_transition(row, {**incident, "updated_at": "later"}))
        self.assertFalse(risk.incident_transition(row, {**incident, "status": "identified"}))
        self.assertTrue(risk.incident_transition(row, {**incident, "status": "resolved"}))
        self.assertFalse(risk.incident_transition(row, {**incident, "status": "resolved"}))
        self.assertFalse(risk.incident_transition({}, {**incident, "status": "resolved"}))

    def test_preview_has_no_production_fallback_and_cards_fit(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.invalid"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "禁止改送正式頻道"):
                slim_preview.run()
        for _, card in slim_preview.cards(self.now):
            self.assertLessEqual(len(card["title"]), 256)
            self.assertLess(len(json.dumps(card, ensure_ascii=False)), 6000)

    def test_disabled_modules_are_not_reported_as_failed(self):
        rows = {label: ("ok", "done") for label in realtime_health.MONITOR_LABELS}
        rows["衍生品"] = ("disabled", "已停用")
        card = realtime_health.daily_health_embed(rows, {}, self.now)
        self.assertNotIn("異常", card["title"])
        self.assertIn("已停用", card["description"])

    def test_production_workflow_routes_risk_to_news_and_does_not_load_dead_webhooks(self):
        text = (Path(__file__).resolve().parents[1]/".github/workflows/realtime-monitors.yml").read_text(encoding="utf-8")
        self.assertIn("DISCORD_RISK_WEBHOOK_URL: ${{ secrets.DISCORD_CRYPTO_NEWS_WEBHOOK_URL }}", text)
        self.assertNotIn("secrets.DISCORD_DERIVATIVES_WEBHOOK_URL", text)
        self.assertNotIn("secrets.DISCORD_EXCHANGE_LISTING_WEBHOOK_URL", text)
        self.assertNotIn("secrets.DISCORD_EXCHANGE_ANNOUNCEMENT_WEBHOOK_URL", text)


if __name__ == "__main__":
    unittest.main()
