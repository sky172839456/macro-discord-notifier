import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notifier import HTTP_HEADERS, classify, daily_embed, extract_numbers, fetch_bls_api_releases, parse_bls_calendar, parse_feed, source_health_embed


class OfficialSourceTests(unittest.TestCase):
    def test_official_requests_use_browser_headers(self):
        self.assertIn("Mozilla/5.0", HTTP_HEADERS["User-Agent"])
        self.assertEqual(HTTP_HEADERS["Referer"], "https://www.bls.gov/")

    def test_bls_ics(self):
        source = """BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:cpi-1\nDTSTART:20260714T083000\nSUMMARY:Consumer Price Index\nEND:VEVENT\nEND:VCALENDAR"""
        events = parse_bls_calendar(source)
        self.assertEqual(events[0]["rule"]["key"], "cpi")
        self.assertEqual(events[0]["time"].isoformat(), "2026-07-14T12:30:00+00:00")

    def test_calendar_failure_is_not_reported_as_no_events(self):
        from datetime import datetime, timezone
        message = daily_embed([], datetime(2026, 7, 16, tzinfo=timezone.utc), "HTTP 403")
        self.assertIn("無法確認", message["description"])
        self.assertNotIn("今日暫無", message["description"])

    def test_health_log_shows_successful_fallback_and_limit(self):
        message = source_health_embed(
            ["BLS 行事曆：HTTPError / HTTP Error 403"],
            ["BLS 官方 API 正常（CPI／PPI／就業數據）"],
        )
        self.assertIn("備援正常", message["title"])
        self.assertIn("✅ 備援成功", message["description"])
        self.assertIn("不能完全取代發布行事曆", message["description"])

    def test_health_log_marks_missing_fallback(self):
        message = source_health_embed(["BLS 行事曆：HTTP 403"], [])
        self.assertIn("備援未確認", message["title"])
        self.assertIn("❌", message["description"])

    def test_classify(self):
        self.assertEqual(classify("Employment Situation")["key"], "jobs")
        self.assertEqual(classify("Chair Powell speaks")["key"], "powell")

    def test_extract_numbers(self):
        self.assertEqual(extract_numbers("GDP increased 3.0 percent and prices rose 2.1%."), "3.0 percent、2.1%")

    def test_rss_keeps_original_url(self):
        rss = """<rss><channel><item><title>Gross Domestic Product</title><description>GDP increased 3.0 percent.</description><link>https://www.bea.gov/news/1</link><pubDate>Thu, 30 Jul 2026 12:30:00 GMT</pubDate></item></channel></rss>"""
        items = parse_feed(rss, "https://www.bea.gov/", "BEA")
        self.assertEqual(items[0]["url"], "https://www.bea.gov/news/1")
        self.assertEqual(items[0]["rule"]["key"], "gdp")

    def test_bls_api_baseline_then_change(self):
        import notifier
        from datetime import datetime, timezone
        from unittest.mock import patch

        first = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
            {"seriesID": series_id, "data": [
                {"year": "2026", "period": "M05", "value": "100"},
                {"year": "2026", "period": "M04", "value": "99"},
                {"year": "2025", "period": "M05", "value": "96"},
                {"year": "2025", "period": "M06", "value": "97"},
            ]}
            for series_id in ("CUSR0000SA0", "CUUR0000SA0", "WPSFD4", "WPUFD4", "CES0000000001", "LNS14000000")
        ]}}
        state = {}
        now = datetime(2026, 7, 11, tzinfo=timezone.utc)
        with patch.object(notifier, "http_json_post", return_value=first):
            self.assertEqual(fetch_bls_api_releases(now, state), [])
        first["Results"]["series"][0]["data"].insert(0, {"year": "2026", "period": "M06", "value": "101"})
        first["Results"]["series"][1]["data"].insert(0, {"year": "2026", "period": "M06", "value": "101"})
        with patch.object(notifier, "http_json_post", return_value=first):
            releases = fetch_bls_api_releases(now, state)
        self.assertEqual([item["rule"]["key"] for item in releases], ["cpi"])


if __name__ == "__main__":
    unittest.main()
