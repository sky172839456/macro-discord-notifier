import unittest
from datetime import datetime, timezone

from summary_notifier import build_embed, event_lines, market_lines, parse_bls_month_page, parse_fair_economy_calendar


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
        text = event_lines([], "官方行事曆目前未完成同步，系統將於下次排程自動重試。", "")
        self.assertIn("下次排程自動重試", text)
        self.assertNotIn("HTTPError", text)

    def test_monthly_official_page_fallback(self):
        html = """<table><tr><td>Consumer Price Index for June 2026</td>
        <td>Tuesday, July 14, 2026</td><td>08:30 AM</td></tr></table>"""
        events = parse_bls_month_page(html)
        self.assertEqual(events[0]["rule"]["key"], "cpi")
        self.assertEqual(events[0]["time"].hour, 12)

    def test_public_calendar_fallback_filters_us_events(self):
        events = parse_fair_economy_calendar([
            {"title": "CPI m/m", "country": "USD", "date": "2026-07-14T08:30:00-04:00"},
            {"title": "CPI m/m", "country": "CAD", "date": "2026-07-14T08:30:00-04:00"},
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rule"]["key"], "cpi")


if __name__ == "__main__":
    unittest.main()

