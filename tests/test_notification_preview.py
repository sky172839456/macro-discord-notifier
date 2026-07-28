import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import notification_preview
from notification_format import apply_delivery_format, source_status_text


class NotificationPreviewTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)

    def test_all_twelve_channels_have_unique_previews(self):
        keys = [item["key"] for item in notification_preview.CHANNEL_PREVIEWS]
        channels = [item["channel"] for item in notification_preview.CHANNEL_PREVIEWS]
        self.assertEqual(len(keys), 12)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(channels), len(set(channels)))
        self.assertIn("重大快訊", channels)
        self.assertIn("監管與etf", channels)

    def test_every_card_is_clearly_labelled_as_test(self):
        for embed in notification_preview.preview_embeds(self.now):
            self.assertTrue(embed["title"].startswith("🧪 測試｜"))
            self.assertIn("測試資料", embed["description"])
            self.assertIn("只送 #測試通知", embed["footer"]["text"])
            self.assertEqual(embed["fields"][-1]["name"], "✅ 測試狀態")
            field_names = [field["name"] for field in embed["fields"]]
            self.assertIn("📌 繁中標題", field_names)
            self.assertIn("📝 繁中重點", field_names)
            self.assertIn("📍 數據／事件狀態", field_names)
            self.assertIn("🕒 時間資訊（台灣）", field_names)
            self.assertIn("🔗 官方原始資料", field_names)
            self.assertIn("🩺 資料狀態", field_names)

    def test_original_english_title_is_kept_when_available(self):
        previews = {
            item["channel"]: embed
            for item, embed in zip(
                notification_preview.CHANNEL_PREVIEWS,
                notification_preview.preview_embeds(self.now),
            )
        }
        for channel in ("總經通知", "上幣通知", "重大快訊", "加密新聞", "交易所公告", "監管與etf"):
            names = [field["name"] for field in previews[channel]["fields"]]
            self.assertIn("🌐 英文原標題", names)

    def test_all_four_source_health_states_have_clear_copy(self):
        values = [source_status_text(status) for status in ("ok", "backup", "partial", "error")]
        self.assertIn("✅ 正常取得", values[0])
        self.assertIn("🟡 使用備援來源", values[1])
        self.assertIn("⚠️ 部分資料缺少", values[2])
        self.assertIn("❌ 所有來源失敗", values[3])

    def test_delivery_formatter_preserves_original_content(self):
        original = {
            "title": "繁中標題",
            "description": "英文原標題：Original English Headline",
            "fields": [{"name": "官方來源", "value": "https://example.com"}],
        }
        card = apply_delivery_format(original, "crypto_news")
        self.assertEqual(card["title"], original["title"])
        self.assertEqual(card["description"], original["description"])
        self.assertEqual(card["author"]["name"], "CRYPTO NEWS RADAR｜加密新聞")
        self.assertEqual(card["fields"][-1]["name"], "🩺 資料狀態")
        self.assertIn("✅ 正常取得", card["fields"][-1]["value"])
        self.assertNotIn("author", original)

    def test_delivery_formatter_marks_visible_source_failure(self):
        card = apply_delivery_format(
            {"title": "資料更新", "description": "官方來源暫時無法確認"},
            "macro_analysis",
        )
        self.assertIn("❌ 所有來源失敗", card["fields"][-1]["value"])

    def test_all_production_delivery_wrappers_use_shared_formatter(self):
        root = Path(__file__).resolve().parents[1]
        files = (
            "notifier.py",
            "bybit_notifier.py",
            "crypto_news_notifier.py",
            "risk_notifier.py",
            "derivatives_notifier.py",
            "summary_notifier.py",
            "analysis_notifier.py",
        )
        for name in files:
            self.assertIn("apply_delivery_format", (root / name).read_text(encoding="utf-8"), name)
        exchange_source = (root / "exchange_announcement_notifier.py").read_text(encoding="utf-8")
        self.assertIn('channel_key="exchange_announcements"', exchange_source)

    def test_discord_limit_splits_twelve_cards_into_two_batches(self):
        batches = notification_preview.payload_batches(self.now)
        self.assertEqual([len(item["embeds"]) for item in batches], [10, 2])
        self.assertTrue(all(len(item["embeds"]) <= 10 for item in batches))
        self.assertTrue(all(item["allowed_mentions"] == {"parse": []} for item in batches))

    def test_run_uses_only_the_test_webhook(self):
        environment = {
            "DISCORD_TEST_WEBHOOK_URL": "https://discord.invalid/test",
            "DISCORD_WEBHOOK_URL": "https://discord.invalid/production",
            "DISCORD_BREAKING_NEWS_WEBHOOK_URL": "https://discord.invalid/breaking",
        }
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(notification_preview, "send_payload") as send:
            count = notification_preview.run(self.now)

        self.assertEqual(count, 12)
        self.assertEqual(send.call_count, 2)
        self.assertTrue(all(call.args[0] == environment["DISCORD_TEST_WEBHOOK_URL"] for call in send.call_args_list))

    def test_missing_test_webhook_never_falls_back_to_production(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.invalid/production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "禁止改送正式頻道"):
                notification_preview.run(self.now)

    def test_workflow_exposes_only_test_webhook(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "all-channel-preview.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("DISCORD_TEST_WEBHOOK_URL", workflow)
        self.assertNotIn("DISCORD_WEBHOOK_URL:", workflow)
        self.assertNotIn("DISCORD_BREAKING_NEWS_WEBHOOK_URL", workflow)


if __name__ == "__main__":
    unittest.main()
