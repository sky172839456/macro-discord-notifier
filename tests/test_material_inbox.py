import copy
import gzip
import io
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import material_inbox as inbox


class MaterialInboxTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, 10, tzinfo=timezone.utc)
        self.env = patch.dict(os.environ, {'MATERIAL_INBOX_ENABLED': '1', 'SLIM_NOTIFICATIONS': '1',
                                         'NEWS_AUTO_RECOVERY': '1', 'DISCORD_MATERIAL_WEBHOOK_URL': 'https://discord.com/api/webhooks/123/TEST'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.state = {'seen': {'existing': '2026-11-03'}, 'pending': [], 'initialized': True,
                      'material_inbox_v1': {'started_at': (self.now-timedelta(hours=1)).isoformat(), 'items': []}}
        self.send, self.persist, self.verify = Mock(return_value='12345'), Mock(), Mock()

    def row(self, title='Binance partners with Mastercard to launch crypto payments', **extra):
        return {'id': title, 'title': title, 'summary': title+'. The companies announced the partnership.',
                'source': 'CoinDesk', 'official': False, 'url': 'https://www.coindesk.com/news/'+str(len(title)),
                'published': self.now-timedelta(minutes=10), 'category': {'key': 'exchange'}, **extra}

    def run_box(self, rows, **kwargs):
        args = dict(fetch=Mock(side_effect=OSError('source unavailable')), send=self.send, persist=self.persist, verify=self.verify)
        args.update(kwargs)
        return inbox.run(rows, self.state, self.now, **args)

    def test_initial_activation_does_not_replay_old_feed_or_touch_member_seen(self):
        self.state.pop('material_inbox_v1')
        old = copy.deepcopy(self.state['seen'])
        self.assertEqual(self.run_box([self.row()]), 0)
        self.assertEqual(self.state['material_inbox_v1']['started_at'], self.now.isoformat())
        self.assertEqual(self.state['seen'], old)
        self.send.assert_not_called()

    def test_missing_private_secret_never_falls_back_to_member_or_log(self):
        with patch.dict(os.environ, {'DISCORD_MATERIAL_WEBHOOK_URL': '', 'DISCORD_LOG_WEBHOOK_URL': 'https://example.invalid/LOG'}):
            self.assertEqual(self.run_box([self.row()]), 0)
        self.send.assert_not_called()

    def test_wrong_destination_blocks_send_and_preserves_queue(self):
        with self.assertRaises(ValueError):
            self.run_box([self.row()], verify=Mock(side_effect=ValueError('wrong channel')))
        self.send.assert_not_called()
        self.assertEqual(self.state['material_inbox_v1']['items'][0]['status'], 'queued')

    def test_private_card_has_specific_purpose_fact_status_time_and_formats(self):
        old = copy.deepcopy(self.state['seen'])
        self.assertEqual(self.run_box([self.row()]), 1)
        card = self.send.call_args.args[1]
        text = json.dumps(card, ensure_ascii=False)
        for value in ('原文標題', '來源內容', '為什麼值得做', '建議形式', '查證狀態', '媒體報導候選', '貼文整理雙方', 'coindesk.com', '2026/11/03 17:50'):
            self.assertIn(value, text)
        self.assertNotIn('來源正常', text)
        self.assertEqual(self.state['seen'], old)
        self.assertEqual(self.state['material_inbox_v1']['items'][0]['message_id'], '12345')

    def test_same_event_from_two_sources_not_sent_twice_across_runs(self):
        a = self.row()
        b = {**a, 'id': 'other', 'source': 'Decrypt', 'url': 'https://decrypt.co/other'}
        self.assertEqual(self.run_box([a, b]), 1)
        self.assertEqual(self.run_box([b]), 0)
        self.assertEqual(len(self.state['material_inbox_v1']['items']), 1)
        self.assertEqual(len(self.state['material_inbox_v1']['items'][0]['related_sources']), 1)

    def test_changed_stage_is_new_candidate_not_silently_merged(self):
        a = self.row('Coinbase announces acquisition of Deribit for $2.9 billion')
        b = self.row('Coinbase completes acquisition of Deribit for $2.9 billion', url='https://www.coindesk.com/completed')
        self.run_box([a, b])
        self.assertEqual(len(self.state['material_inbox_v1']['items']), 2)

    def test_general_daily_budget_three_but_material_security_still_alerts(self):
        box = self.state['material_inbox_v1']['items']
        for i in range(3):
            row = self.row('Company '+str(i)+' launches product', url='https://example.com/'+str(i))
            row.update(published=row['published'].isoformat(), material_topic='business', status='notified', notified_at=self.now.isoformat())
            box.append(row)
        security = self.row('Binance confirms new hack and pauses withdrawals', url='https://www.coindesk.com/security')
        self.assertEqual(self.run_box([self.row(), security]), 1)
        self.assertIn('資安', json.dumps(self.send.call_args.args[1], ensure_ascii=False))
        self.assertTrue(any(r['status'] == 'queued' for r in self.state['material_inbox_v1']['items']))

    def test_failed_second_send_does_not_replay_confirmed_first(self):
        a = self.row('OpenAI introduces model Alpha', material_ai=True, url='https://openai.com/a')
        b = self.row('Google DeepMind releases study Beta', material_ai=True, url='https://deepmind.google/b')
        self.send.side_effect = ['111', RuntimeError('rejected')]
        with self.assertRaises(RuntimeError): self.run_box([a,b])
        self.send.side_effect = None
        self.assertEqual(self.run_box([a,b]), 1)
        self.assertEqual(sum(r['status']=='notified' for r in self.state['material_inbox_v1']['items']), 2)

    def test_uncertain_transport_delivery_not_auto_replayed(self):
        self.send.side_effect = inbox.DeliveryUncertain('unknown')
        self.assertEqual(self.run_box([self.row()]), 0)
        self.assertEqual(self.run_box([self.row()]), 0)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.state['material_inbox_v1']['items'][0]['status'], 'delivery_unknown')

    def test_stale_future_naive_and_pre_activation_items_are_not_sent(self):
        for date in (self.now-timedelta(days=2), self.now+timedelta(hours=1), self.now.replace(tzinfo=None), self.now-timedelta(hours=2)):
            self.run_box([self.row(published=date)])
        self.send.assert_not_called()

    def test_bad_ledger_is_not_reset_and_old_notifications_not_replayed(self):
        self.state['material_inbox_v1']['items'] = 'broken'
        with self.assertRaises(ValueError): self.run_box([self.row()])
        self.send.assert_not_called()
        self.assertEqual(self.state['material_inbox_v1']['items'], 'broken')

    def test_official_feed_gzip_decoded_before_xml_without_lossy_repair(self):
        xml = '<rss><channel><title>AI研究</title></channel></rss>'
        with patch.object(inbox, 'urlopen', return_value=io.BytesIO(gzip.compress(xml.encode()))):
            self.assertEqual(inbox.fetch_feed(inbox.AI_SOURCES[1][1]), xml)
        with patch.object(inbox, 'urlopen', return_value=io.BytesIO(gzip.compress(b'x'*4000001))):
            with self.assertRaises(ValueError): inbox.fetch_feed(inbox.AI_SOURCES[1][1])

    def test_ai_feed_accepts_official_domain_dates_and_rejects_spoof(self):
        xml = '''<rss><channel><item><title><![CDATA[Introducing model Alpha]]></title><description>Research findings</description><link>https://openai.com/news/alpha</link><pubDate>Tue, 03 Nov 2026 09:30:00 GMT</pubDate></item><item><title>Wrong</title><link>https://openai.com.evil.test/x</link><pubDate>Tue, 03 Nov 2026 09:30:00 GMT</pubDate></item></channel></rss>'''
        rows = inbox.parse_ai_feed(xml, 'OpenAI News', 'openai.com')
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['official'])
        self.assertEqual(inbox.topic(rows[0]), 'ai')

    def test_destination_metadata_rejects_public_channel_or_other_guild(self):
        for meta in ({'channel_id': 'public', 'guild_id': inbox.GUILD}, {'channel_id': inbox.CHANNEL, 'guild_id': 'other'}):
            with patch.object(inbox, 'urlopen', return_value=io.BytesIO(json.dumps(meta).encode())):
                with self.assertRaises(ValueError):
                    inbox.verify_destination('https://discord.com/api/webhooks/123/TEST')

    def test_official_ai_claims_are_not_called_independently_verified(self):
        row = self.row('OpenAI introduces Alpha', material_topic='ai', official=True)
        text = json.dumps(inbox.card(row, self.now), ensure_ascii=False)
        self.assertIn('官方自行公布', text)
        self.assertIn('不等於獨立實測', text)

    def test_translation_cannot_introduce_numbers(self):
        self.run_box([self.row()], enrich=Mock(return_value='幣安宣布投資999億美元'))
        text = json.dumps(self.send.call_args.args[1], ensure_ascii=False)
        self.assertNotIn('999', text)
        self.assertIn('待中文核對', text)

    def test_actual_sender_never_mentions_members_and_keeps_private_format(self):
        row = self.row(material_topic='business')
        card = inbox.card(row, self.now)
        with patch.object(inbox, 'urlopen', return_value=io.BytesIO(json.dumps({'id':'123','channel_id':inbox.CHANNEL}).encode())) as post:
            self.assertEqual(inbox.send_card('https://discord.com/api/webhooks/123/TEST', card, 'WV素材整理'), '123')
        payload = json.loads(post.call_args.args[0].data)
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertIn('素材候選', payload['embeds'][0]['title'])
        self.assertIn('不會自動發布IG', payload['embeds'][0]['footer']['text'])
        self.assertNotIn('來源正常', json.dumps(payload, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
