import sys
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import exchange_announcement_notifier as module
from exchange_announcement_notifier import (PAGE_SOURCES, STATUS_SOURCES, embed,
                                             operational_kind, page_items, sample)


class ExchangeAnnouncementTests(unittest.TestCase):
    def test_all_eight_exchanges_are_covered(self):
        self.assertEqual(set(PAGE_SOURCES) | set(STATUS_SOURCES),
                         {"Binance", "OKX", "Bybit", "Bitget", "Coinbase", "Kraken", "KuCoin", "BingX"})

    def test_categories_cover_operational_risks(self):
        cases = {
            "Exchange confirms security incident and wallet exploit": "security",
            "Emergency outage causes service unavailable": "outage",
            "Service discontinued in restricted region due to regulatory changes": "regional",
            "Wallet maintenance for network upgrade": "maintenance",
            "Risk limit and leverage adjustment": "rules",
            "Exchange publishes proof of reserves report": "reserves",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(operational_kind(title)["key"], expected)

    def test_listing_and_marketing_are_excluded(self):
        self.assertIsNone(operational_kind("Binance will list ABC for spot trading"))
        self.assertIsNone(operational_kind("Trade to win from a 100,000 USDT reward pool"))

    def test_page_parser_keeps_only_operational_notices(self):
        body = ('<a href="/en/article/1">Bybit to support network upgrade</a>'
                '<a href="/en/article/2">New listing ABCUSDT perpetual</a>')
        with patch.object(module, "text", return_value=body):
            items = page_items("Bybit", PAGE_SOURCES["Bybit"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"]["key"], "maintenance")

    def test_okx_uses_fixed_locale_fallbacks_and_deduplicates(self):
        body = '<a href="/en-us/help/notice">OKX Spot API Maintenance Notice</a>'
        with patch.object(module, "text", side_effect=[OSError("region blocked"), body, body]):
            items = module.okx_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"]["key"], "maintenance")

    def test_okx_raises_only_when_every_source_errors(self):
        with patch.object(module, "text", side_effect=OSError("blocked")):
            with self.assertRaises(OSError):
                module.okx_items()

    def test_binance_json_parser_filters_listing_content(self):
        payload = {"data": {"articles": [
            {"code": "maint", "title": "Binance Spot API Maintenance Notice"},
            {"code": "listing", "title": "Binance Will List ABC for Spot Trading"},
        ]}}
        with patch.object(module, "text", return_value=json.dumps(payload)):
            items = module.binance_items()
        self.assertEqual({item["url"].rsplit("/", 1)[-1] for item in items}, {"maint"})

    def test_bingx_api_parser_uses_official_operational_categories(self):
        payload = {"code": 0, "data": {"list": [
            {"title": "BingX Spot System Upgrade", "content": "Scheduled maintenance",
             "time": "2026-07-21 01:00:00", "link": "https://bingx.com/en/support/articles/123"},
            {"title": "BingX Will List ABC for Spot Trading", "content": "New listing",
             "time": "2026-07-21 02:00:00", "link": "https://bingx.com/en/support/articles/456"},
        ]}}
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch.object(module, "urlopen", return_value=response) as mocked:
            items = module.bingx_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"]["key"], "maintenance")
        self.assertEqual(mocked.call_count, 3)
        request = mocked.call_args.args[0]
        self.assertEqual(request.headers["X-source-key"], "BX-AI-SKILL")

    def test_bingx_api_accepts_live_list_shape(self):
        payload = {"code": 0, "data": [{
            "contentType": "SystemMaintenance", "title": "BingX System Upgrade",
            "content": "<p>Scheduled maintenance</p>",
            "releaseTime": "2026-05-07T12:12:10.000+08:00",
            "url": "https://bingx.com/en-us/support/articles/16040479784975",
        }]}
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch.object(module, "urlopen", return_value=response):
            items = module.bingx_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published"].isoformat(), "2026-05-07T04:12:10+00:00")

    def test_zero_count_is_visibly_degraded(self):
        card = module.connectivity_embed(2, [("BingX", 0, None)], datetime.now(timezone.utc))
        self.assertIn("⚠️", card["description"])
        self.assertEqual(card["color"], 0xF1C40F)

    def test_card_has_chinese_points_and_official_link(self):
        message = embed(sample(datetime.now(timezone.utc)))
        self.assertIn("繁體中文重點", message["description"])
        self.assertGreaterEqual(message["description"].count("\n• "), 3)
        self.assertEqual(message["fields"][-1]["name"], "官方原始資料")

    def test_production_connectivity_uses_independent_webhook(self):
        with patch.dict(module.os.environ, {module.PRODUCTION_WEBHOOK_ENV: "https://example.invalid/formal"}, clear=True), \
             patch.object(module, "initialize", return_value=(10, [("Bybit", 10, None)])), \
             patch.object(module, "send") as mocked:
            self.assertEqual(module.main.__name__, "main")
            module.send("https://example.invalid/formal", module.connectivity_embed(10, [("Bybit", 10, None)], datetime.now(timezone.utc)))
        self.assertEqual(mocked.call_args.args[0], "https://example.invalid/formal")


if __name__ == "__main__":
    unittest.main()
