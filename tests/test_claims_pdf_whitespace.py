"""DOL PDF whitespace regression; all delivery/fetch tests use local mocks."""
import copy
import os
from pathlib import Path
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch
import notifier as n

# Source: https://oui.doleta.gov/press/2026/102226.pdf
# SHA256: 6bc739a9ccf4035720b6f09b6108c9800bb3d35bedb358938eaefa009ab974f8
FIXTURE = (Path(__file__).parent / "fixtures" / "claims_20261022_wrapped.txt").read_text(encoding="utf-8")
PUBLISHED = datetime(2026, 10, 22, 12, 30, tzinfo=timezone.utc)

class ClaimsPdfWhitespaceTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SLIM_NOTIFICATIONS": "1"}, clear=False)
        env.start()
        self.addCleanup(env.stop)

    def row(self, summary=FIXTURE):
        rule = next(r for r in n.EVENT_RULES if r["key"] == "claims")
        return {"id": "fixture-only", "summary": summary, "rule": rule,
                "title": rule["name"], "published": PUBLISHED,
                "url": "https://oui.doleta.gov/press/2026/102226.pdf",
                "time_label": "官方公布時間"}

    def test_official_wrapped_actual_is_not_missing(self):
        self.assertEqual(n.release_critical_missing(self.row()), [])

    def test_current_previous_direction_and_average_are_not_confused(self):
        text = n.format_metrics(FIXTURE, "claims")
        for expected in ("初領失業金**　194,000 人", "前值修正**　199,000 → 200,000 人",
                         "較前週變化**　減少 6,000 人", "四週移動平均**　197,750 人"):
            self.assertIn(expected, text)
        self.assertNotIn("增加 6,000", text)

    def test_initial_claims_was_whitespace_variants_share_gate_and_display(self):
        for whitespace in ("\n", "\r\n", "\t", "\u00a0", "   "):
            with self.subTest(whitespace=repr(whitespace)):
                summary = ("initial" + whitespace + "claims" + whitespace + "was" +
                           whitespace + "194,000.")
                self.assertEqual(n.release_critical_missing(self.row(summary)), [])
                self.assertIn("194,000 人", n.format_metrics(summary, "claims"))

    def test_source_string_and_period_are_not_mutated(self):
        item = self.row()
        before = copy.deepcopy(item)
        card = n.release_embed(item, detected_at=PUBLISHED)
        self.assertEqual(item, before)
        self.assertIn("194,000 人", card["description"])
        self.assertIn("week ending October 17", item["summary"])

    def test_only_previous_revision_is_not_current(self):
        summary = "The previous week's level was revised up by 1,000 from 199,000 to 200,000."
        self.assertEqual(n.release_critical_missing(self.row(summary)), ["本次初領失業金人數"])

    def test_missing_actual_continuing_and_unadjusted_sections_stay_blocked(self):
        summaries = (
            "seasonally adjusted initial claims was unavailable. The 4-week moving average was 197,750.",
            "The advance number for seasonally adjusted insured unemployment was 1,800,000.",
            "UNADJUSTED DATA\nThe advance number of actual initial claims under state programs, "
            "unadjusted, totaled 190,000 in the week ending October 17.",
        )
        for summary in summaries:
            with self.subTest(summary=summary):
                self.assertEqual(n.release_critical_missing(self.row(summary)), ["本次初領失業金人數"])

    def test_later_unadjusted_and_continuing_values_do_not_replace_actual(self):
        summary = FIXTURE + "\nUNADJUSTED DATA\nActual initial claims totaled 190,000. " \
                           "Insured unemployment was 1,800,000."
        text = n.format_metrics(summary, "claims")
        self.assertIn("初領失業金**　194,000 人", text)
        self.assertNotIn("初領失業金**　190,000", text)
        self.assertNotIn("初領失業金**　1,800,000", text)

    def test_release_older_than_existing_48h_window_is_not_backfilled(self):
        from test_macro_calendar_delivery import MacroCalendarDeliveryTests
        fixture = MacroCalendarDeliveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.now = PUBLISHED + timedelta(hours=49)
        fixture.releases = [self.row()]
        n.run(fixture.now)
        self.assertEqual(fixture.member_calls(), [])
        self.assertFalse(any(k.startswith("release-event:claims:") for k in fixture.state["sent"]))

    def test_valid_current_release_keeps_existing_event_deduplication(self):
        from test_macro_calendar_delivery import MacroCalendarDeliveryTests
        fixture = MacroCalendarDeliveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.now = PUBLISHED + timedelta(minutes=5)
        fixture.releases = [self.row()]
        n.run(fixture.now)
        n.run(fixture.now)
        self.assertEqual(len(fixture.member_calls()), 1)
        self.assertEqual(len([k for k in fixture.state["sent"] if k.startswith("release-event:claims:")]), 1)

    def test_before_embargo_does_not_release_or_consume_signature(self):
        state = {"official_pages": {"claims": "older-fixture"}}
        before = copy.deepcopy(state)
        release_date = PUBLISHED.astimezone(n.NY).replace(hour=0, minute=0)
        page = SimpleNamespace(extract_text=lambda: "UNEMPLOYMENT INSURANCE WEEKLY CLAIMS\n" + FIXTURE)
        with patch.object(n, "latest_claims_pdf", return_value=(release_date, self.row()["url"], b"%PDF-fixture")), \
             patch.object(n, "PdfReader", return_value=SimpleNamespace(pages=[page])):
            self.assertIsNone(n.fetch_claims_pdf_release(PUBLISHED.replace(minute=29), state))
        self.assertEqual(state, before)

    def test_pdf_to_gate_and_member_card_use_mocked_delivery_only(self):
        state = {"official_pages": {"claims": "older-fixture"}}
        release_date = PUBLISHED.astimezone(n.NY).replace(hour=0, minute=0)
        page = SimpleNamespace(extract_text=lambda: "UNEMPLOYMENT INSURANCE WEEKLY CLAIMS\n" + FIXTURE)
        with patch.object(n, "latest_claims_pdf", return_value=(release_date, self.row()["url"], b"%PDF-fixture")), \
             patch.object(n, "PdfReader", return_value=SimpleNamespace(pages=[page])), \
             patch.object(n, "send_discord") as send:
            row = n.fetch_claims_pdf_release(PUBLISHED, state)
            self.assertIsNotNone(row)
            self.assertEqual(row["published"], PUBLISHED)
            self.assertTrue(n.deliver_release("https://member.invalid", row, None, None, PUBLISHED, False, {}))
            send.assert_called_once()
            self.assertIn("初領失業金**　194,000 人", send.call_args.args[1]["description"])

if __name__ == "__main__":
    unittest.main()
