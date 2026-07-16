import unittest

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


if __name__ == "__main__":
    unittest.main()
