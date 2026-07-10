import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notifier import classify, extract_numbers, parse_bls_calendar, parse_feed


class OfficialSourceTests(unittest.TestCase):
    def test_bls_ics(self):
        source = """BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:cpi-1\nDTSTART:20260714T083000\nSUMMARY:Consumer Price Index\nEND:VEVENT\nEND:VCALENDAR"""
        events = parse_bls_calendar(source)
        self.assertEqual(events[0]["rule"]["key"], "cpi")
        self.assertEqual(events[0]["time"].isoformat(), "2026-07-14T12:30:00+00:00")

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


if __name__ == "__main__":
    unittest.main()
