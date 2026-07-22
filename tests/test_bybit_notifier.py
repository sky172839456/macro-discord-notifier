import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import bybit_notifier
from bybit_notifier import (TEST_WEBHOOK_ENV, PRODUCTION_WEBHOOK_ENV,
                            SOURCES, announcement_kind, clean_title, embed,
                            page_items)


class ExchangeListingTests(unittest.TestCase):
    def test_production_and_test_webhooks_are_separate(self):
        self.assertNotEqual(PRODUCTION_WEBHOOK_ENV, TEST_WEBHOOK_ENV)

    def test_bybit_card_suffix_is_removed(self):
        title = "New listing: XLEUSDT Perpetual Contract, with up to 20x leverage lg ... Jul 15, 2026"
        self.assertEqual(
            clean_title(title),
            "New listing: XLEUSDT Perpetual Contract, with up to 20x leverage",
        )

    def test_production_connectivity_test_uses_production_webhook(self):
        with patch.dict(bybit_notifier.os.environ, {PRODUCTION_WEBHOOK_ENV: "https://example.invalid/formal"}, clear=True), \
             patch.object(bybit_notifier, "send") as send:
            bybit_notifier.run(production_test=True)
        self.assertEqual(send.call_args.args[0], "https://example.invalid/formal")
        self.assertIn("正式頻道連線測試", send.call_args.args[1]["title"])

    def test_balanced_exchange_set_is_enabled(self):
        self.assertEqual(
            set(SOURCES) | {"Coinbase"},
            {"Binance", "OKX", "Bybit", "Bitget", "Coinbase", "Kraken", "KuCoin", "BingX"},
        )

    def test_announcement_categories(self):
        cases = {
            "Binance Will List ABC for Spot Trading": "spot",
            "New listing: ABCUSDT Perpetual Contract": "perpetual",
            "Bitget pre-market trading: ABC is set to launch": "premarket",
            "OKX to delist ABC spot trading pairs": "delist",
            "BingX Will Support the ABC Token Swap and Rebrand": "migration",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(announcement_kind(title), expected)

    def test_embed_uses_explicit_category(self):
        item = {"exchange": "OKX", "title": "OKX to list ABC for spot trading", "url": "https://example.com"}
        self.assertIn("🟢 OKX 現貨上幣", embed(item)["title"])

    def test_generic_page_parser_keeps_official_links(self):
        body = '<a href="/support/articles/123">[Initial listing] Bitget to list ABC in spot trading</a>'
        with patch.object(bybit_notifier, "text", return_value=body):
            items = page_items("Bitget", SOURCES["Bitget"])
        self.assertEqual(items[0]["exchange"], "Bitget")
        self.assertEqual(items[0]["url"], "https://www.bitget.com/zh-TC/support/articles/123")

    def test_section_pages_are_not_treated_as_articles(self):
        body = (
            '<a href="/help/section/announcements-new-listings">New listings spot trading</a>'
            '<a href="/help/okx-to-list-abc">OKX to list ABC for spot trading</a>'
        )
        with patch.object(bybit_notifier, "text", return_value=body):
            items = page_items("OKX", SOURCES["OKX"])
        self.assertEqual([item["url"] for item in items], ["https://www.okx.com/help/okx-to-list-abc"])

    def test_binance_uses_official_announcement_articles(self):
        payload = {"data": {"articles": [
            {"code": "abc123", "title": "Binance Will List ABC for Spot Trading"},
            {"code": "promo", "title": "Trade ABC to Share Rewards"},
        ]}}
        with patch.object(bybit_notifier, "text", return_value=json.dumps(payload)):
            items = bybit_notifier.binance_announcement_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://www.binance.com/en/support/announcement/abc123")
        self.assertEqual(items[0]["source_type"], "announcement")

    def test_bingx_announcement_keeps_publish_time_and_direct_link(self):
        payload = {"code": 0, "data": [{
            "title": "ABC Coin Gets Listed on BingX Spot",
            "releaseTime": "2026-07-22T10:00:00+08:00",
            "url": "https://bingx.com/en-us/support/articles/123",
        }]}
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch.object(bybit_notifier, "urlopen", return_value=response):
            items = bybit_notifier.bingx_announcement_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published"], datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(items[0]["url"], "https://bingx.com/en-us/support/articles/123")

    def test_embed_shows_official_and_discovery_times(self):
        item = {
            "exchange": "BingX", "title": "ABC Coin Gets Listed on BingX Spot",
            "url": "https://example.com", "published": datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc),
            "discovered": datetime(2026, 7, 22, 2, 5, tzinfo=timezone.utc),
        }
        fields = {field["name"]: field["value"] for field in embed(item)["fields"]}
        self.assertEqual(fields["官方公告時間（台灣）"], "07/22 10:00")
        self.assertEqual(fields["機器人發現時間（台灣）"], "07/22 10:05")


if __name__ == "__main__":
    unittest.main()
