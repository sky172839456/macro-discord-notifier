"""Exercise the scheduled run, rather than the unused legacy entry point."""
import os
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import notifier


class MacroCalendarDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 0, tzinfo=timezone.utc)  # 08:00 Taiwan
        self.state = {}
        self.calendar = []
        self.releases = []
        self.sources_down = False
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "SLIM_NOTIFICATIONS": "1",
            "DISCORD_WEBHOOK_URL": "https://member.invalid",
            "DISCORD_LOG_WEBHOOK_URL": "https://admin.invalid",
        }, clear=True))
        mocks = {
            "load_state": {"return_value": self.state},
            "save_state": {},
            "http_text": {"return_value": "mocked"},
            "parse_bls_calendar": {"side_effect": self.read_calendar},
            "fetch_bls_html_calendar": {"side_effect": self.read_calendar},
            "load_bls_schedule_snapshot": {"side_effect": RuntimeError("offline")},
            "fetch_public_calendar": {"side_effect": lambda: ([], not self.sources_down)},
            "fetch_extended_calendar": {"side_effect": lambda _: ([], [("extended", not self.sources_down, "mocked")])},
            "parse_feed": {"return_value": []},
            "fetch_official_page_releases": {"side_effect": lambda *_: (self.releases, [], [])},
        }
        for name, kwargs in mocks.items():
            self.stack.enter_context(patch.object(notifier, name, **kwargs))
        self.send = self.stack.enter_context(patch.object(notifier, "send_discord"))

    def read_calendar(self, *_):
        if self.sources_down:
            raise RuntimeError("offline")
        return list(self.calendar)

    def event(self, key, minutes):
        return {
            "id": f"{key}-{minutes}",
            "time": self.now + timedelta(minutes=minutes),
            "rule": next(rule for rule in notifier.EVENT_RULES if rule["key"] == key),
        }

    def member_calls(self):
        return [c for c in self.send.call_args_list if c.args[0] == "https://member.invalid"]

    def admin_calls(self):
        return [c for c in self.send.call_args_list if c.args[0] == "https://admin.invalid"]

    def test_skips_empty_and_non_today_calendars_without_consuming_daily_key(self):
        for calendar in ([], [self.event("cpi", 24 * 60)],
                         [self.event("fed_official", 120)]):
            with self.subTest(calendar=calendar):
                self.calendar = calendar
                notifier.run(self.now)
                self.assertEqual(self.member_calls(), [])
                self.assertEqual(self.state["digests"], [])

    def test_source_failure_still_alerts_admin_and_allows_recovery(self):
        self.sources_down = True
        notifier.run(self.now)
        self.assertEqual(self.member_calls(), [])
        self.assertTrue(self.admin_calls())
        self.assertTrue(self.state["health_alerts"])
        self.assertEqual(self.state["digests"], [])
        self.sources_down = False
        self.calendar = [self.event("cpi", 120)]
        notifier.run(self.now + timedelta(minutes=5))
        self.assertEqual(len(self.member_calls()), 1)
        self.assertIn("消費者物價", self.member_calls()[0].args[1]["description"])

    def test_late_arriving_event_sends_once_after_empty_morning(self):
        self.calendar = [self.event("cpi", 24 * 60)]
        notifier.run(self.now)
        self.calendar = [self.event("cpi", 120)]
        notifier.run(self.now + timedelta(minutes=5))
        notifier.run(self.now + timedelta(minutes=10))
        self.assertEqual(len(self.member_calls()), 1)
        self.assertEqual(self.state["digests"], ["2026-10-14"])

    def test_empty_calendar_does_not_block_official_release(self):
        rule = next(r for r in notifier.EVENT_RULES if r["key"] == "cpi")
        self.releases = [{"id": "new-cpi", "published": self.now,
                          "rule": rule, "summary": "", "url": rule["source"],
                          "reference_period": "2026-M09", "cpi_metrics": {
                              "monthly": .6, "annual": 3.7,
                              "monthly_seasonally_adjusted": True, "annual_unadjusted": True}}]
        with patch.object(notifier, "release_embed", return_value={"title": "release"}):
            notifier.run(self.now)
            notifier.run(self.now + timedelta(minutes=5))
        self.assertEqual([c.args[1] for c in self.member_calls()], [{"title": "release"}])
        self.assertIn("release-event:cpi:2026-10-14", self.state["sent"])

    def test_core_reminders_are_consolidated_into_daily_calendar(self):
        self.calendar = [self.event("cpi", 15)]
        with patch.object(notifier, "pre_embed", return_value={"title": "reminder"}):
            notifier.run(self.now)
            notifier.run(self.now + timedelta(minutes=5))
        self.assertEqual(sum(c.args[1]["title"] == "reminder" for c in self.member_calls()), 0)
        self.assertEqual(len(self.member_calls()), 1)  # only the daily timetable

    def test_forcing_an_empty_digest_does_not_send_blank_card(self):
        notifier.run(self.now, force_digest=True)
        self.assertEqual(self.member_calls(), [])
        self.assertEqual(self.state["digests"], [])

    def test_non_slim_delivery_retains_existing_behavior(self):
        with patch.dict(os.environ, {"SLIM_NOTIFICATIONS": "0"}):
            notifier.run(self.now)
        self.assertEqual(len(self.member_calls()), 1)
        self.assertEqual(self.state["digests"], ["2026-10-14"])

    def test_before_seven_waits_for_delivery_window(self):
        self.calendar = [self.event("cpi", 120)]
        notifier.run(self.now - timedelta(hours=2))
        self.assertEqual(self.member_calls(), [])
        self.assertEqual(self.state["digests"], [])

    def test_paginated_delivery_retries_only_unsent_pages(self):
        self.calendar = [self.event('cpi', 120)]
        cards = [{'title': 'page1', 'description': 'first'}, {'title': 'page2', 'description': 'second'}]
        failures = []

        def send(webhook, card, *_):
            if webhook == 'https://member.invalid' and card['title'] == 'page2' and not failures:
                failures.append(True)
                raise RuntimeError('temporary delivery failure')

        self.send.side_effect = send
        with patch.object(notifier.slim_policy, 'calendar_cards', return_value=cards):
            with self.assertRaises(RuntimeError):
                notifier.run(self.now)
            self.assertEqual(self.state['digests'], [])
            notifier.run(self.now + timedelta(minutes=5))
        titles = [c.args[1]['title'] for c in self.member_calls()]
        self.assertEqual(titles, ['page1', 'page2', 'page2'])
        self.assertEqual(self.state['digests'], ['2026-10-14'])


    def test_early_event_is_listed_without_claiming_result_published(self):
        self.calendar = [self.event("fomc", -360)]
        notifier.run(self.now)
        card = self.member_calls()[0].args[1]
        self.assertIn("02:00", card["description"])
        self.assertIn("已過排定時間；結果另見正式公告", card["description"])
        self.assertNotIn("已公布", card["description"])
        self.assertEqual(self.state["digests"], ["2026-10-14"])

    def test_all_tracked_types_share_one_sorted_table_and_no_later_alert(self):
        keys = sorted(notifier.slim_policy.CALENDAR_EVENTS - {"fed_chair_policy"})
        self.calendar = [self.event(key, 120+i) for i,key in enumerate(keys)]
        self.calendar.append(dict(self.calendar[0]))
        notifier.run(self.now)
        notifier.run(self.now+timedelta(minutes=110))
        self.assertEqual(len(self.member_calls()), 1)
        card = self.member_calls()[0].args[1]
        self.assertIn("共11項", card["title"])
        self.assertIn("本群追蹤項目", card["description"])
        self.assertIn("不另發逐項公布前提醒", card["footer"]["text"])
        for key in keys:
            rule = next(r for r in notifier.EVENT_RULES if r["key"] == key)
            self.assertEqual(card["description"].count(rule["name"]), 1)
        self.assertFalse(any(k.startswith("pre:") for k in self.state["sent"]))

    def test_already_sent_daily_key_prevents_midday_resend(self):
        self.state["digests"] = ["2026-10-14"]
        self.calendar = [self.event("cpi", 15)]
        notifier.run(self.now)
        self.assertEqual(self.member_calls(), [])

    def test_releases_still_deliver_after_table_once_without_reminders(self):
        rule = next(r for r in notifier.EVENT_RULES if r["key"] == "cpi")
        self.calendar = [self.event("cpi", 15)]
        self.releases = [{"id":"valid-cpi", "published":self.now, "rule":rule,
            "url":rule["source"], "summary":"", "reference_period":"2026-M09",
            "cpi_metrics":{"monthly":.6,"annual":3.7,"monthly_seasonally_adjusted":True,"annual_unadjusted":True}}]
        with patch.object(notifier, "release_embed", return_value={"title":"result"}):
            notifier.run(self.now)
            notifier.run(self.now+timedelta(minutes=5))
        self.assertEqual(len(self.member_calls()), 2)
        self.assertEqual(sum(c.args[1]["title"]=="result" for c in self.member_calls()), 1)
        self.assertIn("release-event:cpi:2026-10-14", self.state["sent"])

    def test_default_upcoming_selection_still_excludes_elapsed_events(self):
        past = self.event("fomc", -360)
        future = self.event("claims", 120)
        self.assertEqual(notifier.slim_policy.today_events([past,future],self.now), [future])
        self.assertEqual(notifier.slim_policy.today_events([past,future],self.now,include_elapsed=True), [past,future])

    def test_no_individual_chair_policy_reminder(self):
        self.calendar = [{"id":"chair","time":self.now+timedelta(minutes=15),
            "rule":{"key":"fed_chair_policy","name":"已核對主席政策談話","source":"https://www.federalreserve.gov/"},
            "speaker":"Chair", "title":"Policy speech"}]
        # Enrichment is tested elsewhere; use an already verified calendar row.
        with patch.object(notifier.fed_speech_policy,"enrich",side_effect=lambda rows,*_: (rows,[])):
            notifier.run(self.now)
            notifier.run(self.now+timedelta(minutes=5))
        self.assertEqual(len(self.member_calls()), 1)
        self.assertNotIn("pre:chair",self.state["sent"])


if __name__ == "__main__":
    unittest.main()
