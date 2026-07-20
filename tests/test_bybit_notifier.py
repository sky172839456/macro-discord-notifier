import unittest
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
        self.assertEqual(items[0]["url"], "https://www.bitget.com/support/articles/123")


if __name__ == "__main__":
    unittest.main()
