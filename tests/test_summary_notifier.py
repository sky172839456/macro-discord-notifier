import unittest
from datetime import datetime, timezone

from summary_notifier import build_embed, event_lines, market_lines


class SummaryNotifierTests(unittest.TestCase):
    def test_market_lines_labels_direction(self):
        text = market_lines({"BTC": {"price": 100000, "change": 2.5}, "ETH": {"price": 3000, "change": -1.25}}, None)
        self.assertIn("🟢 **BTC**", text)
        self.assertIn("+2.50%", text)
        self.assertIn("🔴 **ETH**", text)
        self.assertIn("-1.25%", text)

    def test_source_failure_is_visible(self):
        embed = build_embed("daily", datetime(2026, 7, 13, tzinfo=timezone.utc), None, "來源失敗", [], "行事曆失敗")
        values = "\n".join(field["value"] for field in embed["fields"])
        self.assertIn("來源失敗", values)
        self.assertIn("行事曆失敗", values)

    def test_calendar_failure_uses_friendly_copy(self):
        text = event_lines([], "本次未取得符合條件的官方行事曆事件，系統將於下次排程自動更新。", "")
        self.assertIn("下次排程自動更新", text)
        self.assertNotIn("HTTPError", text)


if __name__ == "__main__":
    unittest.main()

