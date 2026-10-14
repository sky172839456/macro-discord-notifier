import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import crypto_news_notifier as news
import fed_speech_policy as fed
import market_brief_data as data
import notification_quality as quality
import notifier
import slim_policy as policy
import slim_risk
from notification_format import apply_delivery_format


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        self.env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def event(self, key='cpi', minutes=60, name=None):
        return {'id': f'{key}-{minutes}', 'time': self.now + timedelta(minutes=minutes),
                'rule': {'key': key, 'name': name or key, 'source': 'https://www.bls.gov/cpi/'}}

    def article(self, title='Bitcoin market update', identifier='a', official=False):
        return {'id': identifier, 'title': title, 'title_zh': '比特幣市場消息', 'summary': title,
                'summary_zh_points': ['比特幣市場動態更新。'], 'source': 'Official' if official else 'Media',
                'official': official, 'published': self.now - timedelta(minutes=20),
                'url': 'https://example.invalid/' + identifier, 'category': {'key': 'market', 'priority': 'normal'}}

    def test_calendar_keeps_more_than_five_and_merges_same_release(self):
        events = [self.event(key, i + 1) for i, key in enumerate(['cpi', 'jobs', 'pce', 'fomc', 'ppi', 'gdp', 'claims'])]
        events.append(copy.deepcopy(events[0]))
        cards = policy.calendar_cards(events, self.now)
        rendered = json.dumps(cards, ensure_ascii=False)
        self.assertIn('共7項', rendered)
        for e in events[:7]:
            self.assertIn(e['rule']['name'], rendered)
        self.assertEqual(len(policy.today_events(events, self.now)), 7)

    def test_large_calendar_paginates_without_losing_rows(self):
        events = [self.event('cpi', i + 1, f'事件{i:03d}' + '測試名稱' * 12) for i in range(110)]
        cards = policy.calendar_cards(events, self.now)
        self.assertGreater(len(cards), 1)
        self.assertTrue(all(len(c['description']) <= 3500 for c in cards))
        all_text = '\n'.join(c['description'] for c in cards)
        for i in range(110):
            self.assertEqual(all_text.count(f'事件{i:03d}'), 1)

    def test_calendar_time_order_and_day_boundary_remain_correct(self):
        events = [self.event('cpi', 120), self.event('jobs', 1), self.event('pce', 300)]
        selected = policy.today_events(events, self.now)
        self.assertEqual([r['rule']['key'] for r in selected], ['jobs', 'cpi'])

    def test_press_conference_is_not_a_rate_decision(self):
        self.assertEqual(notifier.classify('FOMC Press Conference')['key'], 'fed_official')
        self.assertEqual(notifier.classify('FOMC monetary policy statement')['key'], 'fomc')

    def test_same_time_speakers_are_not_merged(self):
        a, b = self.event('fed_official'), self.event('fed_official')
        a['title'], b['title'] = 'Governor A speaks', 'Governor B speaks'
        self.assertEqual(len(notifier.merge_calendar_events([a, b])), 2)

    def test_chair_reminder_uses_single_window_and_never_runs_after_start(self):
        event = self.event('fed_chair_policy', 15, '聯準會主席 Alex Example｜貨幣政策')
        self.assertTrue(policy.reminder_due(event, self.now))
        self.assertFalse(policy.reminder_due(event, self.now + timedelta(minutes=16)))
        self.assertFalse(policy.reminder_due(self.event('fed_official', 15), self.now))
        card = apply_delivery_format(notifier.pre_embed(event, minutes_until=15), 'macro_alerts')
        self.assertTrue(card['title'].startswith('【官員談話】'))
        self.assertIn('Alex Example', card['title'])
        self.assertIn('不代表已經發表', card['description'])

    def test_late_release_separates_schedule_and_detection_time(self):
        item = {'rule': {'key': 'cpi', 'name': 'CPI', 'source': 'https://www.bls.gov/cpi/'},
                'published': self.now, 'summary': 'Prices increased 0.2 percent and 2.7 percent.', 'url': ''}
        card = notifier.release_embed(item, self.now - timedelta(minutes=22), detected_at=self.now)
        self.assertIn('補發', card['title'])
        text = json.dumps(card, ensure_ascii=False)
        self.assertIn('官方排定時間', text)
        self.assertIn('機器人發現', text)
        self.assertNotIn('MoM', text)
        self.assertNotIn('YoY', text)

    def test_unknown_official_time_does_not_invent_delay(self):
        item = {'rule': {'key': 'cpi', 'name': 'CPI', 'source': 'https://www.bls.gov/cpi/'},
                'published': self.now, 'summary': '', 'url': ''}
        card = notifier.release_embed(item, detected_at=self.now)
        self.assertNotIn('補發', card['title'])
        self.assertIn('不將發現時間當成公布時間', json.dumps(card, ensure_ascii=False))

    def test_news_time_marks_late_original_without_claiming_official(self):
        item = self.article('Exchange confirms withdrawals halted after breach')
        card = policy.news_card(item, now=self.now)
        self.assertIn('補發', card['title'])
        self.assertIn('媒體報導', card['fields'][0]['value'])
        self.assertIn('來源發布時間', card['fields'][0]['value'])

    def test_untranslated_news_does_not_dump_english_or_lose_original(self):
        item = self.article()
        item['title_zh'] = item['title']
        item['summary_zh_points'] = ['The complete English report is unavailable.']
        card = policy.news_card(item, now=self.now)
        self.assertIn('中文標題待確認', card['title'])
        self.assertNotIn('complete English', card['description'])
        self.assertEqual(card['url'], item['url'])

    def test_numeric_guard_accepts_unit_conversion_and_rejects_invention(self):
        self.assertIn('4.73億', quality.checked_translation('Company holds 473 million XRP', '公司持有約4.73億枚XRP'))
        with self.assertRaises(ValueError):
            quality.checked_translation('Company holds 473 million XRP', '公司持有約4.73萬枚XRP')
        with self.assertRaises(ValueError):
            quality.checked_translation('Rate is 2.7 percent', '利率為3.7%')

    def test_chad_stock_name_is_not_translated_as_country(self):
        self.assertEqual(quality.checked_translation('CHAD preferred stock', '乍得優先股'), 'CHAD優先股')

    def test_invalid_cached_translation_is_not_trusted(self):
        import hashlib
        item = self.article('Company holds 473 million XRP')
        key = hashlib.sha256(item['title'].encode()).hexdigest()[:20]
        state = {'translation_cache': {key: {'source': item['title'], 'translated': '公司持有4.73萬枚XRP'}}}
        with patch.object(news, 'summary_points', return_value=[]):
            enriched = news.add_translated_title(item, state, self.now)
        self.assertEqual(enriched['title_zh'], '')

    def test_material_policy_ranks_before_generic_price_and_opinion(self):
        ordinary = self.article('Bitcoin price holds steady', 'a')
        important = self.article('Regulator publishes final stablecoin redemption policy', 'b', True)
        opinion = self.article('Opinion: why you could buy Bitcoin', 'c')
        self.assertEqual([r['id'] for r in quality.rank_news([ordinary, opinion, important])], ['b', 'a', 'c'])

    def test_unselected_news_remains_pending_and_not_marked_delivered(self):
        rows = [self.article(f'Bitcoin price change {i}', str(i)) for i in range(5)]
        important = self.article('Regulator publishes final stablecoin redemption policy 9', 'policy', True)
        rows.append(important)
        state = {'initialized': True, 'seen': {}, 'pending': [], 'translation_cache': {}}
        with patch.dict(os.environ, {'DISCORD_CRYPTO_NEWS_WEBHOOK_URL': 'https://discord.invalid'}), \
             patch.object(news, 'load_state', return_value=state), patch.object(news, 'save_state'), \
             patch.object(news, 'fetch_all', return_value=(rows, [('mock', 6, None)])), \
             patch.object(news, 'add_translated_title', side_effect=lambda row, *_: dict(row)), \
             patch.object(news, 'send_discord') as send:
            news.run(self.now)
            self.assertIn('policy', state['seen'])
            self.assertEqual(len(state['seen']), 5)
            self.assertEqual(len(state['pending']), 1)
            self.assertNotIn(state['pending'][0]['id'], state['seen'])
            self.assertEqual(send.call_count, 1)
            news.run(self.now + timedelta(minutes=10))
            self.assertEqual(send.call_count, 1)
            with patch.object(news, 'fetch_all', return_value=([], [('mock', 0, None)])):
                news.run(self.now + timedelta(days=1))
            self.assertEqual(send.call_count, 2)
            self.assertEqual(state['pending'], [])

    def test_partial_digest_retry_does_not_exceed_five_or_repeat_sent_pages(self):
        rows = [self.article(f'Bitcoin price change {i}', str(i)) for i in range(7)]
        for row in rows:
            row['url'] += 'x' * 1100
        state = {'initialized': True, 'seen': {}, 'pending': [], 'translation_cache': {}}
        successes, attempts = [], []

        def send(_webhook, cards, *_):
            attempts.append(cards)
            if len(attempts) == 2:
                raise RuntimeError('temporary failure')
            successes.append(cards)

        with patch.dict(os.environ, {'DISCORD_CRYPTO_NEWS_WEBHOOK_URL': 'https://discord.invalid'}), \
             patch.object(news, 'load_state', return_value=state), patch.object(news, 'save_state'), \
             patch.object(news, 'fetch_all', return_value=(rows, [('mock', 7, None)])), \
             patch.object(news, 'add_translated_title', side_effect=lambda row, *_: dict(row)), \
             patch.object(news, 'send_discord', side_effect=send):
            with self.assertRaises(RuntimeError):
                news.run(self.now)
            self.assertGreater(len(state['digest_progress']['ids']), 0)
            first_success = json.dumps(successes[0])
            news.run(self.now + timedelta(minutes=5))
        self.assertEqual(len(state['seen']), 5)
        self.assertEqual(len(state['digest_progress']['ids']), 5)
        self.assertEqual(len(state['pending']), 2)
        for row in rows:
            if row['url'] in first_success:
                self.assertFalse(any(row['url'] in json.dumps(c) for c in successes[1:]))

    def test_official_primary_preserves_both_original_links(self):
        a = self.article('Strategy adds 250 Bitcoin', 'a')
        b = self.article('Strategy buys 250 Bitcoin', 'b', True)
        rows = policy.merge_pending([a, b])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], b['url'])
        self.assertEqual(rows[0]['related_sources'][0]['url'], a['url'])
        text = policy.digest_card(rows, self.now)['description']
        self.assertIn(a['url'], text)
        self.assertIn(b['url'], text)

    def test_long_news_links_paginate_with_primary_links_preserved(self):
        rows = [self.article(identifier=str(i)) for i in range(5)]
        for row in rows:
            row['url'] += 'x' * 1100
        cards = policy.digest_cards(rows, self.now)
        self.assertGreater(len(cards), 1)
        self.assertTrue(all(len(c['description']) <= 3500 for c in cards))
        text = json.dumps(cards)
        for row in rows:
            self.assertIn(row['url'], text)

    def test_zero_missing_and_small_etf_flow_are_distinct(self):
        row = lambda value: '<tr><td>14 Oct 2026</td><td>' + value + '</td></tr>'
        with self.assertRaises(ValueError):
            data.parse_farside_latest(row('10').replace('14 Oct', '13 Oct') + row('-'))
        self.assertEqual(data.parse_farside_latest(row('0'))['net_flow_musd'], 0)
        self.assertIn('100.00美元', quality.money_musd(.0001))
        self.assertNotIn('流入', quality.money_musd(0))

    def test_weekly_etf_cannot_treat_unfilled_day_as_zero(self):
        with self.assertRaises(ValueError):
            data.parse_farside_week('<tr><td>14 Oct 2026</td><td>N/A</td></tr>')

    def test_revision_copy_does_not_dump_raw_english(self):
        item = {'rule': {'key': 'cpi', 'name': 'CPI', 'source': 'https://www.bls.gov/cpi/'},
                'published': self.now, 'summary': 'The prior value was revised from 0.2 percent to 0.3 percent.', 'url': ''}
        card = notifier.release_embed(item, detected_at=self.now)
        self.assertNotIn('was revised', json.dumps(card, ensure_ascii=False))

    def test_risk_translation_failure_is_short_and_preserves_official_link(self):
        from types import SimpleNamespace
        api = SimpleNamespace(clean_source_text=lambda s, _: s, translate_title=lambda s: s,
                              translate_status=lambda s: '調查中')
        incident = {'name': 'Withdrawal Service Unavailable', 'body': 'English source paragraph.',
                    'status': 'investigating', 'updated_at': (self.now-timedelta(minutes=20)).isoformat(),
                    'shortlink': 'https://status.coinbase.com/'}
        with patch.object(news, 'translate_text', side_effect=ValueError('no translation')):
            card = slim_risk.incident_card(api, 'Coinbase', incident, self.now)
        self.assertNotIn('English source paragraph', card['description'])
        self.assertIn('中文摘要暫缺', card['description'])
        self.assertIn('補發', card['title'])
        self.assertIn(incident['shortlink'], json.dumps(card))


class FedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 13, 45, tzinfo=timezone.utc)
        self.chair = 'Alex Example'
        self.roster = '<h4>2026 Committee Members</h4><ul><li><a href="/bio">Alex Example</a>, Board of Governors, Chairman</li><li><a>Jerome H. Powell</a>, Board of Governors</li></ul>'
        self.agenda = self.month('Chairman Alex Example', 'Monetary Policy Outlook')
        self.event = {'id': 'auxiliary-1', 'title': 'Fed Chair Example Speaks', 'time': self.now + timedelta(minutes=15),
                      'rule': {'key': 'fed_official', 'name': '聯準會官員', 'source': fed.ROSTER_URL}}

    def month(self, identity, topic, clock='10:00 a.m.'):
        return '<h4>Speeches</h4><div class="col-xs-2"><h6>Time:</h6></div>' + \
            f'<div class="col-xs-2"><p>{clock}</p></div><div class="col-xs-7"><p>Speech - {identity}</p><p class="calendar__title"><em>{topic}</em></p></div><div class="col-xs-3"><p>14</p></div><h4>Beige Book</h4>'

    def fetch(self, url, attempts=1):
        return self.roster if url == fed.ROSTER_URL else self.agenda

    def test_dynamic_chair_identity_topic_and_time_require_agreement(self):
        rows, statuses = fed.enrich([self.event], {}, self.now, self.fetch)
        self.assertEqual(rows[0]['rule']['key'], 'fed_chair_policy')
        self.assertIn('Alex Example', rows[0]['rule']['name'])
        self.assertIn('貨幣政策', rows[0]['rule']['name'])
        self.assertTrue(statuses[0][2])

    def test_clock_mismatch_is_not_guessed(self):
        self.agenda = self.month('Chairman Alex Example', 'Monetary Policy', '11:00 a.m.')
        rows, _ = fed.enrich([self.event], {}, self.now, self.fetch)
        self.assertEqual(rows[0]['rule']['key'], 'fed_official')

    def test_former_chair_or_unknown_speaker_is_not_promoted(self):
        for identity in ['Governor Jerome H. Powell', 'Chairman Unknown Person']:
            self.agenda = self.month(identity, 'Monetary Policy')
            rows, _ = fed.enrich([self.event], {}, self.now, self.fetch)
            self.assertEqual(rows[0]['rule']['key'], 'fed_official')

    def test_chair_routine_remarks_and_other_governors_are_excluded(self):
        for identity, topic in [('Chairman Alex Example', 'Opening Remarks on Inflation'),
                                ('Governor Alex Example', 'Monetary Policy')]:
            self.agenda = self.month(identity, topic)
            rows, _ = fed.enrich([self.event], {}, self.now, self.fetch)
            self.assertEqual(rows[0]['rule']['key'], 'fed_official')

    def test_official_source_failure_does_not_use_stale_identity(self):
        def broken(*_, **__):
            raise RuntimeError('offline')
        rows, statuses = fed.enrich([self.event], {}, self.now, broken)
        self.assertEqual(rows[0]['rule']['key'], 'fed_official')
        self.assertFalse(statuses[0][2])

    def test_cache_limits_requests_and_refreshes_expired_official_data(self):
        state = {}
        with patch.object(self, 'fetch', wraps=self.fetch) as fetch:
            fed.enrich([self.event], state, self.now, fetch)
            fed.enrich([self.event], state, self.now + timedelta(minutes=1), fetch)
            self.assertEqual(fetch.call_count, 2)
            later = {**self.event, 'time': self.now + timedelta(hours=2)}
            fed.enrich([later], state, self.now + timedelta(minutes=61), fetch)
            self.assertEqual(fetch.call_count, 4)

    def test_same_named_chair_is_not_assumed_in_different_roster_year(self):
        with self.assertRaises(ValueError):
            fed.parse_chair(self.roster, 2027)


if __name__ == '__main__':
    unittest.main()
