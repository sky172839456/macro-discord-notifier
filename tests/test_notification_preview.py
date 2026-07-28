import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import notification_preview


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
