import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import exchange_announcement_notifier as ann
import risk_notifier as risk
import slim_risk

SECURITY = next(c for c in ann.CATEGORIES if c["key"] == "security")
OUTAGE = next(c for c in ann.CATEGORIES if c["key"] == "outage")
CODE = "0729ad59cde74700b4eaa96c33441e71"


def api(**extra):
    base = dict(clean_source_text=risk.clean_source_text, translate_title=lambda _: "虛構安全事件公告")
    base.update(extra)
    return SimpleNamespace(**base)


def notice(**extra):
    item = {"id": "fixture", "exchange": "Binance", "title": "Fictional Security Incident Update",
            "summary": "Fictional Security Incident Update", "category": SECURITY,
            "url": "https://www.binance.com/en/support/announcement/" + CODE,
            "published": datetime(2026, 11, 12, 16, 0, tzinfo=timezone.utc), "published_is_official": False,
            "code": CODE}
    item.update(extra)
    return item


class OfficialNoticeCardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 12, 16, 59, tzinfo=timezone.utc)
        title = patch("crypto_news_notifier.translate_title", return_value="虛構安全事件公告")
        title.start()
        self.addCleanup(title.stop)

    def test_excerpt_never_ends_mid_sentence(self):
        item = notice(body="Fictional text.")
        with patch("crypto_news_notifier.translate_text", return_value="第一句完整。第二句被截"):
            card = slim_risk.notice_card(api(), item, self.now)
        self.assertTrue(card["description"].startswith("第一句完整。\n\n"))
        self.assertNotIn("第二句被截", card["description"])

    def text(self, card):
        return json.dumps(card, ensure_ascii=False)

    def test_title_only_notice_has_no_empty_incident_fields(self):
        text = self.text(slim_risk.notice_card(api(), notice(), self.now))
        for empty in ("未附事件說明", "未列更新時間", "官方事件狀態", "調查中", "狀態未確認"):
            self.assertNotIn(empty, text)
        self.assertIn("請先看交易所的處置", text)
        self.assertIn("本次查詢：2026/11/13 00:59", text)
        self.assertIn("官方公告｜Binance｜虛構安全事件公告", text)

    def test_official_time_and_body_are_shown_when_the_source_has_them(self):
        item = notice(body="A fictional incident affected some withdrawals.", published_is_official=True)
        with patch("crypto_news_notifier.translate_text", return_value="虛構事件影響部分提款。"):
            card = slim_risk.notice_card(api(), item, self.now)
        self.assertTrue(card["description"].startswith("虛構事件影響部分提款。"))
        self.assertIn("官方公告時間：2026/11/13 00:00", self.text(card))
        self.assertNotIn("本次查詢", self.text(card))

    def test_unofficial_time_is_never_called_official(self):
        text = self.text(slim_risk.notice_card(api(), notice(published_is_official=False), self.now))
        self.assertNotIn("官方公告時間", text)

    def test_outage_has_its_own_guidance(self):
        text = self.text(slim_risk.notice_card(api(), notice(category=OUTAGE), self.now))
        self.assertIn("服務中斷或異常", text)
        self.assertIn(OUTAGE["label"], text)

    def test_translation_failure_keeps_original_title(self):
        with patch("crypto_news_notifier.translate_title", side_effect=RuntimeError("down")):
            card = slim_risk.notice_card(api(), notice(), self.now)
        self.assertIn("Fictional Security Incident Update", card["title"])


class BinanceDetailTests(unittest.TestCase):
    def test_detail_extracts_publish_time_and_plain_body(self):
        body = {"node": "root", "child": [{"node": "element", "tag": "p", "child": [
            {"node": "text", "text": "Fellow Binancians,"}]}, {"node": "element", "tag": "p", "child": [
            {"node": "text", "text": "A fictional"}, {"node": "text", "text": " update."}]}]}
        payload = {"data": {"publishDate": 1794502450592, "body": json.dumps(body)}}
        with patch.object(ann, "text", return_value=json.dumps(payload)) as fetch:
            detail = ann.binance_article_detail(CODE)
        self.assertIn(CODE, fetch.call_args.args[0])
        self.assertTrue(detail["published_is_official"])
        self.assertEqual(detail["published"], datetime.fromtimestamp(1794502450.592, timezone.utc))
        self.assertEqual(detail["body"], "A fictional update.")

    def test_missing_fields_are_not_invented(self):
        with patch.object(ann, "text", return_value=json.dumps({"data": {"publishDate": None, "body": None}})):
            self.assertEqual(ann.binance_article_detail(CODE), {})

    def test_invalid_code_does_not_fetch(self):
        with patch.object(ann, "text") as fetch:
            self.assertEqual(ann.binance_article_detail("../x"), {})
        fetch.assert_not_called()

    def test_only_binance_notices_fetch_detail(self):
        self.assertEqual(risk.official_notice_detail({"exchange": "OKX", "code": CODE}), {})


class MonitorNoticePathTests(unittest.TestCase):
    def run_monitor(self, detail):
        state = {"baselines": {"CriticalNotices": True}, "exchange_events": {"CriticalNotices": {}}}
        send = Mock()
        fake = SimpleNamespace(load=lambda: state, save=Mock(), get_json=lambda *_: {"incidents": []},
                               STATUS_URL="https://example.invalid", bybit_incidents=lambda: [],
                               critical_official_notices=lambda: [notice()], official_notice_detail=detail,
                               send=send, clean_source_text=risk.clean_source_text,
                               translate_title=lambda _: "虛構安全事件公告")
        with patch.object(slim_risk, "price_sources", return_value={}):
            slim_risk.monitor(fake, "https://example.invalid/webhook",
                              now=datetime(2026, 11, 12, 16, 59, tzinfo=timezone.utc))
        return send

    def setUp(self):
        title = patch("crypto_news_notifier.translate_title", return_value="虛構安全事件公告")
        title.start()
        self.addCleanup(title.stop)

    def test_new_notice_uses_notice_card(self):
        send = self.run_monitor(lambda item: {})
        card = send.call_args.args[1]
        self.assertIn("官方公告｜Binance", card["title"])
        self.assertNotIn("官方事件狀態", json.dumps(card, ensure_ascii=False))

    def test_detail_failure_still_sends_meaningful_card(self):
        send = self.run_monitor(Mock(side_effect=OSError("down")))
        self.assertIn("請先看交易所的處置", send.call_args.args[1]["description"])


if __name__ == "__main__":
    unittest.main()
