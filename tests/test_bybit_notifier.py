import unittest
from unittest.mock import patch

import bybit_notifier
from bybit_notifier import TEST_WEBHOOK_ENV, PRODUCTION_WEBHOOK_ENV, clean_title


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


if __name__ == "__main__":
    unittest.main()
