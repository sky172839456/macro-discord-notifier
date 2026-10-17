import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import crypto_news_notifier as news
import news_auto_recovery as auto
import notification_quality as quality
import slim_policy


class AutoNewsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 11, tzinfo=timezone.utc)
        env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1',
            'DISCORD_CRYPTO_NEWS_WEBHOOK_URL': 'https://member.invalid',
            'DISCORD_LOG_WEBHOOK_URL': 'https://admin.invalid'})
        env.start(); self.addCleanup(env.stop)

    def row(self, key='a', title='SEC approves Bitcoin ETF', summary='The SEC approved a Bitcoin ETF.', **kwargs):
        return {'id': key, 'title': title, 'summary': summary,
                'published': self.now, 'url': 'https://example.invalid/'+key,
                'source': '媒體', 'official': False, 'category': news.CATEGORIES[1], **kwargs}

    def ready(self, **kwargs):
        values = dict(title_zh='SEC 核准 Bitcoin ETF', summary_zh_points=['SEC 核准 Bitcoin ETF。'], auto_copy_version=2)
        values.update(kwargs)
        return self.row(**values)

    def route(self, rows, state, now=None):
        with patch.object(news, 'save_state'), patch.object(news, 'send_discord') as send:
            result = auto.route(rows, state, now or self.now)
        return result, send

    def test_old_future_low_value_skip_before_translation(self):
        rows = [self.row('old', published=self.now-timedelta(hours=25)),
                self.row('future', published=self.now+timedelta(minutes=10)),
                self.row('price', title='Live updates: Bitcoin falls to $82,000'),
                self.row('opinion', title='Why Bitcoin could reach $100K'),
                self.row('q3', title='Crypto Q3 report: $500M lost in hacks')]
        state = {}
        with patch.object(news, 'add_translated_title') as translate:
            ready, send = self.route(rows, state)
        self.assertEqual(ready, []); translate.assert_not_called(); send.assert_not_called()
        self.assertEqual(len(state['news_auto_ignored']), 5)
        self.assertEqual(state.get('seen', {}), {})

    def test_fresh_media_safety_publishes_as_media_not_official(self):
        row = self.ready(title='Bitget withdrawals halted after suspected breach',
            summary='Bitget halted withdrawals after a suspected breach.',
            title_zh='Bitget 疑似遭入侵後暫停提款',
            summary_zh_points=['Bitget 因疑似入侵暫停提款。'])
        result, send = self.route([row], {})
        self.assertEqual(len(result), 1); send.assert_not_called()
        card = slim_policy.news_card(result[0], now=self.now)
        self.assertIn('媒體報導', card['title']); self.assertIn('疑似', card['description'])

    def test_translation_qualifications_numbers_and_direction(self):
        for source, wrong in [('Ledger suspected breach', 'Ledger 已確認遭入侵'),
                              ('Bitcoin may rise', 'Bitcoin 將上漲'),
                              ('SEC did not approve ETF', 'SEC 核准 ETF'),
                              ('Company plans acquisition', '公司完成收購'),
                              ('ETF outflows $5 million', 'ETF 淨流入500萬美元'),
                              ('Company holds 473 million XRP', '公司持有 XRP')]:
            with self.assertRaises(ValueError, msg=source): auto.checked_copy(source, wrong)
        self.assertIn('疑似', auto.checked_copy('Ledger suspected breach', 'Ledger 疑似遭入侵'))
        self.assertIn('500萬', auto.checked_copy('ETF outflows $5 million', 'ETF 淨流出500萬美元'))

    def test_provider_invalid_primary_recovers_exact_segment_alternative(self):
        payload = {'responseStatus': 200, 'responseData': {'translatedText': 'SEC approved ETF'},
                   'matches': [{'segment':'SEC approves ETF', 'translation':'SEC 核准 ETF'}]}
        with patch.object(news, 'http_text', return_value=json.dumps(payload)):
            self.assertEqual(news.translate_text('SEC approves ETF'), 'SEC 核准 ETF')

    def test_provider_quota_or_unrelated_alternative_never_used(self):
        for payload in ({'responseStatus': 429, 'responseData': {'translatedText':'請稍後再試'}},
                        {'responseStatus':200, 'responseData':{'translatedText':'bad'},
                         'matches':[{'segment':'other story','translation':'公司核准上市'}]}):
            with patch.object(news, 'http_text', return_value=json.dumps(payload)), patch.object(auto, 'translate_bing', side_effect=ValueError('unavailable')):
                with self.assertRaises(ValueError): news.translate_text('SEC approves ETF')

    def test_overlong_sentence_not_silently_truncated(self):
        with patch.object(news, 'http_text') as request:
            with self.assertRaises(ValueError): news.translate_text('A'*451)
        request.assert_not_called()

    def test_primary_failure_uses_independent_bing_fallback(self):
        with patch.object(news, 'http_text', side_effect=OSError('down')), \
             patch.object(auto, 'translate_bing', return_value='SEC 核准 Bitcoin ETF') as fallback:
            self.assertIn('核准', news.translate_text('SEC approves Bitcoin ETF'))
        fallback.assert_called_once()

    def test_secondary_bad_facts_still_rejected(self):
        with patch.object(news, 'http_text', side_effect=OSError('down')), \
             patch.object(auto, 'translate_bing', return_value='ETF 淨流入500萬美元'):
            with self.assertRaises(ValueError): news.translate_text('ETF outflows $5 million')

    def test_product_and_roundup_are_not_security_alerts(self):
        product = self.row(title='Ledger answer to wallet tampering costs $849 and ships next year',
                           summary='Ledger new wallet will ship as the company investigates tampered wallets.')
        self.assertFalse(slim_policy.material_news(product))
        self.assertIsNotNone(auto.selection_reason(product, self.now))
        roundup = self.row(title='Scammer loses $4.8M stored on tampered Ledgers: Asia Express')
        self.assertIsNotNone(auto.selection_reason(roundup, self.now))

    def test_trading_window_is_permission_and_ledger_proper_name_preserved(self):
        value = auto.checked_copy('Russians have until July 1, 2027 to buy and sell crypto.',
                                  '俄羅斯人必須在2027年7月1日之前買賣加密資產。')
        self.assertIn('仍可', value); self.assertNotIn('必須', value)
        self.assertIn('Ledger', auto.checked_copy('Tampered Ledgers affected crypto wallets', '被篡改的分類帳影響加密錢包'))

    def test_bad_cached_copy_refreshes_and_reuses_success(self):
        source = 'SEC approves Bitcoin ETF'
        import hashlib
        key = 'auto-v2-'+hashlib.sha256(source.encode()).hexdigest()[:24]
        state = {'translation_cache': {key:{'source':source,'translated':'bad'}}}
        with patch.object(news, 'translate_text', return_value='SEC 核准 Bitcoin ETF') as translate:
            item = auto.enrich(self.row(summary=''), state, self.now)
            again = news.add_translated_title(item, state, self.now)
        self.assertEqual(translate.call_count, 1)
        self.assertEqual(again['summary_basis'], 'headline')
        self.assertIsNone(quality.digest_exclusion_reason(again))
        self.assertIn('依原文標題', slim_policy.news_card(again, now=self.now)['description'])

    def test_summary_failure_recovers_headline_facts_without_invention(self):
        with patch.object(news, 'translate_text', side_effect=['SEC 核准 Bitcoin ETF', ValueError('down')]):
            item = auto.enrich(self.row(), {}, self.now)
        self.assertEqual(item['summary_zh_points'], [item['title_zh']])
        self.assertEqual(item['summary_check_source'], item['title'])
        self.assertIsNone(quality.digest_exclusion_reason(item))

    def test_retry_backoff_expiry_and_no_per_article_admin_ping(self):
        state = {}
        with patch.object(news, 'translate_text', side_effect=ValueError('down')) as translate:
            first, send = self.route([self.row()], state)
            self.assertEqual(first, []); send.assert_not_called()
            self.route([self.row()], state, self.now+timedelta(minutes=5))
            self.assertEqual(translate.call_count, 1)
            self.route([], state, self.now+timedelta(hours=25))
        self.assertFalse(state['news_auto_retry']); self.assertEqual(state.get('seen', {}), {})

    def test_legacy_queue_migrates_without_replaying_delivered(self):
        row = self.ready(); old = copy.deepcopy(row)
        old['published'] = self.now.isoformat(); old['category']='regulation'; old['status']='pending_review'
        state = {'safety_review':[old], 'seen':{'a':'2026-10-16'}}
        ready, send = self.route([], state)
        self.assertFalse(ready); send.assert_not_called()
        self.assertEqual(old['status'], 'auto_processing')

    def test_same_url_price_edit_merges_but_material_progress_survives(self):
        a = self.row(title='Live updates: Bitcoin falls to $82,000')
        b = self.row(title='Live updates: Bitcoin falls to $81,000 as Kospi drops 8%')
        self.assertTrue(news.same_news_event(a, b))
        pairs = [('Bitget pauses withdrawals after breach','Bitget resumes withdrawals after breach'),
                 ('Ledger confirms $5M stolen','Ledger confirms $10M stolen'),
                 ('Strategy buys 100 BTC','Strategy buys 200 BTC')]
        for x, y in pairs:
            self.assertFalse(news.same_news_event(self.row(title=x), self.row(title=y)), (x,y))
        self.assertFalse(auto.same_article(a, {**b,'url':'https://different.invalid/story'}))

    def test_incomplete_policy_dates_use_explicit_caveat_not_admin_queue(self):
        row = self.ready(title='Russia bans crypto trading', title_zh='俄羅斯禁止加密資產交易',
                         summary='Russia bans crypto trading.', summary_zh_points=['俄羅斯禁止加密資產交易。'])
        ready, send = self.route([row], {})
        self.assertEqual(len(ready), 1); send.assert_not_called()
        self.assertIn('未', slim_policy.news_card(ready[0], now=self.now)['description'])

    def test_sustained_translation_outage_aggregate_once_per_day(self):
        state = {}
        rows = [self.row(str(n), title=f'SEC approves crypto ETF {n}') for n in range(3)]
        with patch.object(news, 'translate_text', side_effect=ValueError('down')):
            self.route(rows, state)
            _, send = self.route(rows, state, self.now+timedelta(minutes=16))
            self.assertEqual(send.call_count, 1)
            self.assertIn('服務持續異常', send.call_args.args[1]['title'])
            _, send = self.route(rows, state, self.now+timedelta(minutes=50))
            send.assert_not_called()

    def test_translation_budget_does_not_starve_ready_pending(self):
        rows = [self.ready(key=str(n), title=f'SEC approves Bitcoin ETF {n}',
                title_zh=f'SEC 核准 Bitcoin ETF {n}', summary=f'SEC approves Bitcoin ETF {n}',
                summary_zh_points=[f'SEC 核准 Bitcoin ETF {n}']) for n in range(6)]
        result, send = self.route(rows, {})
        self.assertEqual(len(result), 6); send.assert_not_called()

    def run_news(self, rows, state, now=None, error=None):
        with patch.object(news, 'load_state', return_value=state), patch.object(news, 'save_state'), \
             patch.object(news, 'fetch_all', return_value=(rows, [('mock', len(rows), None)])), \
             patch.object(news, 'send_discord', side_effect=error) as send:
            news.run(now or self.now)
        return send

    def test_production_path_media_safety_sends_member_only_once(self):
        row = self.ready(title='Bitget halts withdrawals after suspected breach',
                         title_zh='Bitget 因疑似入侵暫停提款', summary='Bitget halts withdrawals after suspected breach',
                         summary_zh_points=['Bitget 因疑似入侵暫停提款'])
        state = {'initialized':True, 'seen':{}, 'pending':[]}
        send = self.run_news([row], state)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], 'https://member.invalid')
        self.assertEqual(set(state['seen']), {'a'})
        self.run_news([row], state).assert_not_called()

    def test_production_send_failure_does_not_mark_delivery(self):
        state = {'initialized':True, 'seen':{}, 'pending':[]}
        with self.assertRaises(RuntimeError):
            self.run_news([self.ready()], state, error=RuntimeError('send failed'))
        self.assertEqual(state['seen'], {})
        self.assertEqual(state.get('headline_history', []), [])

    def test_daily_five_cap_and_no_duplicate_digest_after_success(self):
        rows = [self.ready(key=str(n), title=f'BlackRock Bitcoin ETF assets rise {n}%',
                title_zh=f'BlackRock Bitcoin ETF 資產增加{n}%',
                summary=f'BlackRock Bitcoin ETF assets rise {n}%',
                summary_zh_points=[f'BlackRock Bitcoin ETF 資產增加{n}%']) for n in range(1,7)]
        state = {'initialized':True, 'seen':{}, 'pending':[]}
        now = self.now+timedelta(hours=1)
        self.run_news(rows, state, now)
        self.assertEqual(len(state['digest_progress']['ids']), 5)
        self.assertEqual(len(state['seen']), 5)
        self.run_news(rows, state, now+timedelta(minutes=5)).assert_not_called()

    def retry_state(self, rows):
        state = {'initialized':True, 'seen':{}, 'pending':[], 'news_auto_retry':{}}
        for row in rows:
            stored = dict(row)
            stored['published'] = row['published'].isoformat()
            state['news_auto_retry'][row['id']] = {'item':stored, 'attempts':1,
                                                  'next_at':self.now.isoformat()}
        # Match the real cross-workflow JSON cache, not just in-memory objects.
        return json.loads(json.dumps(state))

    def ordinary(self, n=1):
        return self.ready(key=f'normal-{n}', title=f'BlackRock Bitcoin ETF assets rise {n}%',
                          title_zh=f'BlackRock Bitcoin ETF 資產增加{n}%',
                          summary=f'BlackRock Bitcoin ETF assets rise {n}%',
                          summary_zh_points=[f'BlackRock Bitcoin ETF 資產增加{n}%'])

    def test_json_retry_route_restores_datetime_without_mutating_source(self):
        state = self.retry_state([self.ordinary()])
        original = state['news_auto_retry']['normal-1']['item']
        result, send = self.route([], state)
        self.assertIsInstance(result[0]['published'], datetime)
        self.assertIsNotNone(result[0]['published'].tzinfo)
        self.assertIsInstance(original['published'], str)
        send.assert_not_called()

    def test_json_retry_enters_pending_before_digest_without_error(self):
        state = self.retry_state([self.ordinary()])
        self.run_news([], state).assert_not_called()
        self.assertEqual(len(state['pending']), 1)
        self.assertEqual(state['pending'][0]['published'], self.now.isoformat())
        self.assertEqual(state['seen'], {})
        json.dumps(state)  # Recovered runtime datetimes must not leak to storage.

    def test_json_retry_mixed_pending_survives_next_round_and_daily_cap(self):
        state = self.retry_state([self.ordinary(n) for n in range(2,7)])
        pending = self.ordinary(1)
        state['pending'] = [{**pending, 'published':self.now.isoformat(), 'category':'regulation'}]
        self.run_news([], state).assert_not_called()
        state = json.loads(json.dumps(state))
        self.run_news([], state, self.now+timedelta(hours=1))
        self.assertEqual(len(state['seen']), 5)
        self.assertEqual(len(state['digest_progress']['ids']), 5)
        self.assertEqual(len(state['pending']), 1)
        state = json.loads(json.dumps(state))
        self.run_news([], state, self.now+timedelta(hours=1, minutes=5)).assert_not_called()

    def test_json_retry_urgent_send_uses_restored_date_and_only_marks_success(self):
        state = self.retry_state([self.ready()])
        send = self.run_news([], state)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], 'https://member.invalid')
        self.assertEqual(set(state['seen']), {'a'})
        self.assertEqual(state['headline_history'][0]['published'], self.now.isoformat())
        json.dumps(state)

    def test_json_retry_urgent_failure_never_marks_delivery(self):
        state = self.retry_state([self.ready()])
        with self.assertRaisesRegex(RuntimeError, 'send failed'):
            self.run_news([], state, error=RuntimeError('send failed'))
        self.assertEqual(state['seen'], {})
        self.assertEqual(state.get('headline_history', []), [])


if __name__ == '__main__': unittest.main()
