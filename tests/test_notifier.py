import sys
import unittest
import inspect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notifier import (HTTP_HEADERS, classify, daily_embed, extract_numbers,
                      fetch_bls_api_releases, fetch_extended_calendar, format_metrics,
                      full_source_health_embed, merge_calendar_events,
                      load_bls_schedule_snapshot,
                      macro_overview_embed, overview_snapshot,
                      overview_update_embed, parse_bls_calendar, parse_feed,
                      pre_embed, revision_lines,
                      source_health_embed, supplement_dynamic_bls_calendar)


class OfficialSourceTests(unittest.TestCase):
    def test_run_supports_forced_production_overview(self):
        import notifier
        self.assertIn("force_overview", inspect.signature(notifier.run).parameters)

    def test_official_requests_use_browser_headers(self):
        self.assertIn("Mozilla/5.0", HTTP_HEADERS["User-Agent"])
        self.assertEqual(HTTP_HEADERS["Referer"], "https://www.bls.gov/")

    def test_bls_ics(self):
        source = """BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:cpi-1\nDTSTART:20260714T083000\nSUMMARY:Consumer Price Index\nEND:VEVENT\nEND:VCALENDAR"""
        events = parse_bls_calendar(source)
        self.assertEqual(events[0]["rule"]["key"], "cpi")
        self.assertEqual(events[0]["time"].isoformat(), "2026-07-14T12:30:00+00:00")

    def test_bls_snapshot_has_confirmed_next_cpi_and_ppi_times(self):
        events, verified_at = load_bls_schedule_snapshot()
        future = {event["rule"]["key"]: event for event in events if event["time"].isoformat() in {
            "2026-08-12T12:30:00+00:00", "2026-08-13T12:30:00+00:00"
        }}
        self.assertEqual(verified_at, "2026-07-20")
        self.assertEqual(future["cpi"]["time"].isoformat(), "2026-08-12T12:30:00+00:00")
        self.assertEqual(future["ppi"]["time"].isoformat(), "2026-08-13T12:30:00+00:00")

    def test_bls_snapshot_overview_confirms_all_four_tracked_rows(self):
        from datetime import datetime, timezone
        events, _ = load_bls_schedule_snapshot()
        message = macro_overview_embed(events, datetime(2026, 7, 20, tzinfo=timezone.utc))
        self.assertIn("非農就業／失業率**｜下次公布：08/07 20:30", message["description"])
        self.assertIn("JOLTS 職位空缺**｜下次公布：08/04 22:00", message["description"])
        self.assertNotIn("非農就業／失業率**｜下次公布：待官方確認", message["description"])
        self.assertNotIn("JOLTS 職位空缺**｜下次公布：待官方確認", message["description"])

    def test_dynamic_bls_schedule_overrides_snapshot_for_same_series(self):
        from datetime import datetime, timezone
        now = datetime(2026, 7, 20, tzinfo=timezone.utc)
        snapshot, _ = load_bls_schedule_snapshot()
        rule = classify("Consumer Price Index")
        corrected = {"id": "corrected", "time": datetime(2026, 8, 12, 13, 30, tzinfo=timezone.utc), "rule": rule}
        merged = supplement_dynamic_bls_calendar([corrected], snapshot, now)
        future_cpi = [event for event in merged if event["rule"]["key"] == "cpi" and event["time"] >= now]
        self.assertEqual(future_cpi, [corrected])

    def test_calendar_failure_is_not_reported_as_no_events(self):
        from datetime import datetime, timezone
        message = daily_embed([], datetime(2026, 7, 16, tzinfo=timezone.utc), "HTTP 403")
        self.assertIn("無法確認", message["description"])
        self.assertNotIn("今日暫無", message["description"])

    def test_daily_digest_shows_only_next_three_days(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 7, 20, tzinfo=timezone.utc)
        rule = classify("Consumer Price Index")
        events = [
            {"id": "soon", "time": now + timedelta(days=2), "rule": rule},
            {"id": "late", "time": now + timedelta(days=4), "rule": rule},
        ]
        message = daily_embed(events, now)
        self.assertIn("07/22", message["description"])
        self.assertNotIn("07/24", message["description"])
        self.assertIn("未來三日", message["title"])

    def test_overview_uses_next_future_event_not_expired_event(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 7, 20, tzinfo=timezone.utc)
        rule = classify("Consumer Price Index")
        events = [
            {"id": "old", "time": now - timedelta(days=1), "rule": rule},
            {"id": "next", "time": now + timedelta(days=2), "rule": rule},
        ]
        message = macro_overview_embed(events, now)
        self.assertIn("07/22 08:00", message["description"])
        self.assertNotIn("07/19", message["description"])

    def test_overview_snapshot_detects_pending_to_confirmed(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 7, 20, tzinfo=timezone.utc)
        rule = classify("Consumer Price Index")
        pending = overview_snapshot([], now)
        confirmed = overview_snapshot([{"id": "cpi", "time": now + timedelta(days=2), "rule": rule}], now)
        self.assertIsNone(pending["cpi"])
        self.assertNotEqual(pending["cpi"], confirmed["cpi"])

    def test_overview_update_card_contains_only_changed_time(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 7, 20, tzinfo=timezone.utc)
        value = (now + timedelta(days=2)).isoformat()
        message = overview_update_embed([(("cpi",), "🔴", "CPI", value)], now)
        self.assertIn("總經監控總覽更新", message["title"])
        self.assertIn("07/22 08:00", message["description"])

    def test_overview_distinguishes_unconfirmed_from_source_failure(self):
        from datetime import datetime, timezone
        now = datetime(2026, 7, 20, tzinfo=timezone.utc)
        unconfirmed = macro_overview_embed([], now)
        failed = macro_overview_embed([], now, "calendar unavailable")
        self.assertIn("待官方確認", unconfirmed["description"])
        self.assertIn("來源暫時無法確認", failed["description"])

    def test_extended_official_schedules(self):
        from datetime import datetime, timezone
        from unittest.mock import patch
        import notifier

        pages = {
            notifier.EXTENDED_CALENDARS["BEA"]: (
                "July 30 8:30 AM N ews GDP (Advance Estimate), 2nd Quarter 2026 "
                "July 30 8:30 AM N ews Personal Income and Outlays, June 2026"
            ),
            notifier.EXTENDED_CALENDARS["CENSUS"]: (
                "Advance Monthly Sales for Retail and Food Services August 14, 2026 8:30 AM "
                "Advance Report on Durable Goods--Manufacturers' Shipments, Inventories, and Orders "
                "August 26, 2026 8:30 AM"
            ),
            notifier.EXTENDED_CALENDARS["FED"]: (
                "2026 FOMC Meetings July 28-29 Minutes: (Released August 19, 2026) "
                "September 15-16* 2025 FOMC Meetings"
            ),
        }
        with patch.object(notifier, "http_text", side_effect=lambda url: pages[url]):
            events, statuses = fetch_extended_calendar(datetime(2026, 7, 20, tzinfo=timezone.utc))
        self.assertEqual({event["rule"]["key"] for event in events}, {"gdp", "pce", "retail", "durable", "fomc"})
        self.assertEqual(sum(event["rule"]["key"] == "fomc" for event in events), 2)
        self.assertTrue(all(healthy for _, healthy, _ in statuses))

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
        self.assertEqual(classify("Personal Income and Outlays")["key"], "pce")
        self.assertEqual(classify("Unemployment Claims")["key"], "claims")
        self.assertEqual(classify("JOLTS Job Openings")["key"], "jolts")
        self.assertEqual(classify("Advance Retail Sales")["key"], "retail")
        self.assertEqual(classify("Durable Goods Orders")["key"], "durable")

    def test_day_before_reminder_copy(self):
        from datetime import datetime, timezone
        event = {"time": datetime(2026, 8, 12, 12, 30, tzinfo=timezone.utc),
                 "rule": classify("Personal Income and Outlays")}
        message = pre_embed(event, day_before=True)
        self.assertIn("明日", message["title"])

    def test_full_health_always_shows_successes(self):
        message = full_source_health_embed([
            ("BLS 官方動態", "正常", True),
            ("DOL 官方動態", "HTTP 403", False),
        ])
        self.assertIn("1 個來源異常", message["title"])
        self.assertIn("✅ **BLS 官方動態**", message["description"])
        self.assertIn("❌ **DOL 官方動態**", message["description"])

    def test_previous_and_revision_copy(self):
        summary = "Retail sales rose 0.6 percent. The prior value was revised from 0.2 percent to 0.3 percent."
        self.assertIn("前期數值", format_metrics(summary, "retail"))
        self.assertIn("revised", revision_lines(summary))

    def test_calendar_merge_deduplicates_same_release(self):
        from datetime import datetime, timezone
        event_time = datetime(2026, 8, 12, 12, 30, tzinfo=timezone.utc)
        rule = classify("Consumer Price Index")
        merged = merge_calendar_events(
            [{"id": "official", "time": event_time, "rule": rule}],
            [{"id": "auxiliary", "time": event_time, "rule": rule}],
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["id"], "official")

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
