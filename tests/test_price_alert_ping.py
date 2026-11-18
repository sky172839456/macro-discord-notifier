"""2026-11-18 本人選 DC 功能細節 #10：價格快訊只 @ 成員自己領的「🔔 價格快訊」身分組。"""
import inspect
import json
import os
import unittest
from unittest import mock

import price_move_alert
import summary_notifier

CARD = {'title': '【價格快訊】 📈 ETH 24小時 +5.02%', 'description': '**ETH** 1,808.90 USDT｜24小時 **+5.02%**', 'fields': []}


def captured(**kwargs):
    sent = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data.decode('utf-8')))
        return Response()

    with mock.patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}), mock.patch.object(summary_notifier, 'urlopen', fake_urlopen):
        summary_notifier.send('https://discord.invalid/api/webhooks/1/x', dict(CARD), False, **kwargs)
    return sent[0]


class PriceAlertPingTests(unittest.TestCase):
    def test_price_alert_pings_only_the_opt_in_role(self):
        payload = captured(ping_role=price_move_alert.PING_ROLE)
        self.assertEqual(payload['content'], f'<@&{price_move_alert.PING_ROLE}>')
        self.assertEqual(payload['allowed_mentions'], {'parse': [], 'roles': [price_move_alert.PING_ROLE]})

    def test_other_cards_still_ping_nobody(self):
        payload = captured()
        self.assertNotIn('content', payload)
        self.assertEqual(payload['allowed_mentions'], {'parse': []})

    def test_role_id_must_look_like_a_discord_id(self):
        self.assertRegex(price_move_alert.PING_ROLE, r'^\d{17,20}$')
        with self.assertRaises(ValueError):
            captured(ping_role='@everyone')

    def test_card_is_plain_information_and_says_not_realtime(self):
        # 2026-11-18 本人：快訊卡保持純訊息，課程連結、風險提醒句放在其他該在的地方；只註明不是即時。
        from datetime import datetime, timezone
        now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        quotes = {'ETH': {'price': 1808.9, 'change_24h': 5.02, 'quote_currency': 'USDT'}}
        found = [{'kind': '24h', 'symbol': 'ETH', 'direction': 'up', 'level': 5.0, 'change': 5.02}]
        card = price_move_alert.build_card(now, quotes, found, {})
        text = card['description']
        self.assertIn('大約 5 分鐘檢查一次，不是即時', text)
        self.assertIn('不推論原因、不預測走勢', text)
        for extra in ('wviewture.com', '](http', '🧭', '止損', 'TradingView'):
            self.assertNotIn(extra, text)
        with mock.patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            from notification_format import apply_delivery_format
            out = apply_delivery_format(card, 'daily_market')
        self.assertIn('不是即時', out['description'])
        self.assertNotIn('wviewture.com', out['description'])

    def test_only_the_price_alert_sender_passes_the_role(self):
        source = inspect.getsource(summary_notifier)
        self.assertEqual(source.count('ping_role=price_move_alert.PING_ROLE'), 1)


if __name__ == '__main__':
    unittest.main()
