import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import crypto_news_notifier as news
import news_editorial as editorial
import slim_policy as policy


class NewsEditorialTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
        self.env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1',
            'DISCORD_CRYPTO_NEWS_WEBHOOK_URL': 'https://member.invalid',
            'DISCORD_LOG_WEBHOOK_URL': 'https://admin.invalid'})
        self.env.start(); self.addCleanup(self.env.stop)

    def row(self, title, key='a', summary='', official=False):
        return {'id': key, 'title': title, 'summary': summary or title,
                'title_zh': '來源發布新消息', 'summary_zh_points': ['來源發布新消息。'],
                'source': '官方' if official else '媒體', 'official': official,
                'url': 'https://example.invalid/'+key, 'published': self.now,
                'category': {'key': 'market', 'priority': 'normal'}}

    def run_news(self, rows, state, now=None, effect=None):
        with patch.object(news, 'load_state', return_value=state), patch.object(news, 'save_state'), \
             patch.object(news, 'fetch_all', return_value=(rows, [('mock', len(rows), None)])), \
             patch.object(news, 'add_translated_title', side_effect=lambda row,*_:dict(row)), \
             patch.object(news, 'send_discord', side_effect=effect) as send:
            news.run(now or self.now)
        return send

    def state(self):
        return {'initialized': True, 'seen': {}, 'pending': []}

    def test_ledger_protected_before_relevance_and_generic_exclusion(self):
        title = 'Ledger asks resellers to pull devices after suspected $86M drain'
        summary = 'Customers reported finding implants; officials say the issue could affect devices.'
        self.assertTrue(editorial.safety_candidate(self.row(title, summary=summary)))
        self.assertTrue(news.is_relevant(title+' '+summary))
        self.assertTrue(policy.material_news(self.row(title, summary=summary)))
        rss = f'<rss><channel><item><title>{title}</title><description>{summary}</description><link>https://example.invalid/a</link><pubDate>Thu, 15 Oct 2026 11:00:00 GMT</pubDate></item></channel></rss>'
        rows = news.parse_feed(rss, {'name':'媒體', 'official':False})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['category']['key'], 'security')

    def test_explainer_sentencing_and_future_predictions_not_safety(self):
        for title in ('How crypto users can avoid hardware wallet implants',
                      'Can crypto users trust the supply chain behind hardware wallets?',
                      'Ledger hacker sentenced after attack years ago',
                      'Bitcoin price prediction could reach $100K'):
            self.assertFalse(editorial.safety_candidate(self.row(title)), title)

    def test_whole_word_context_does_not_match_alleged_stock_ledger(self):
        self.assertFalse(editorial.safety_candidate(self.row('Printer firmware implant found at stationery shop')))
        self.assertFalse(editorial.safety_candidate(self.row('Stockledger computer breach reported')))

    def test_unconfirmed_media_admin_only_once_and_no_quota(self):
        row = self.row('Ledger pulls devices after suspected drain')
        state = self.state()
        send = self.run_news([row], state)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], 'https://admin.invalid')
        self.assertIn('待核對', send.call_args.args[1]['title'])
        self.assertEqual(state['seen'], {})
        self.assertEqual(state['pending'], [])
        self.assertNotIn('digest_progress', state)
        self.run_news([row], state, self.now+timedelta(minutes=5)).assert_not_called()

    def test_untranslated_safety_retained_even_with_no_admin_webhook(self):
        row = self.row('Bitget withdrawals halted after breach'); row['title_zh'] = ''
        state = self.state()
        with patch.dict(os.environ, {'DISCORD_LOG_WEBHOOK_URL': ''}):
            self.run_news([row], state).assert_not_called()
        self.assertEqual(len(state['safety_review']), 1)
        self.assertNotIn('notified_at', state['safety_review'][0])

    def test_admin_failure_retries_without_sending_to_members(self):
        state = self.state(); row = self.row('Trezor confirms firmware implant')
        self.run_news([row], state, effect=RuntimeError('fail'))
        self.assertFalse(state['safety_review'][0].get('notified_at'))
        self.assertEqual(self.run_news([row], state).call_args.args[0], 'https://admin.invalid')

    def test_official_confirmed_readable_safety_can_send_before_digest(self):
        row = self.row('Ethereum confirms wallet exploit and issues fix', official=True)
        state = self.state()
        send = self.run_news([row], state, self.now-timedelta(hours=1))
        self.assertEqual(send.call_args.args[0], 'https://member.invalid')
        self.assertIn(row['id'], state['seen'])

    def test_official_suspected_or_untranslated_is_not_promoted(self):
        for row in (self.row('Ethereum reports suspected wallet exploit', official=True),
                    self.row('Ethereum confirms wallet exploit', official=True)):
            if 'suspected' not in row['title']: row['summary_zh_points'] = []
            state = self.state()
            self.assertEqual(self.run_news([row], state).call_args.args[0], 'https://admin.invalid')
            self.assertEqual(state['seen'], {})

    def test_existing_pending_safety_migrates_without_member_leak(self):
        row = self.row('Ledger reports suspected wallet drain')
        row.update(published=self.now.isoformat(), category='security')
        state = self.state(); state['pending'] = [row]
        send = self.run_news([], state)
        self.assertEqual(send.call_args.args[0], 'https://admin.invalid')
        self.assertEqual(state['pending'], [])

    def test_same_bank_deal_aliases_and_complementary_timeline_merge(self):
        rows = [self.row('Kraken parent Payward to become first crypto firm to buy a EU bank', 'a',
                         'Payward agreed to buy Lithuania’s Saldo Bank, which holds $190 million in total assets.'),
                self.row("Kraken Owner Payward to Buy Lithuania's Saldo Bank in EU Push", 'b'),
                self.row('Kraken parent to buy Lithuanian Saldo Bank amid expansion', 'c',
                         'Payward expects to close the acquisition in 2027, subject to regulatory approval.')]
        merged = policy.merge_pending(rows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(set(editorial.member_ids(merged[0])), {'a','b','c'})
        self.assertEqual(len(merged[0]['related_sources']), 2)
        card = policy.digest_card(merged, self.now)
        self.assertIn('2027', card['description'])
        self.assertIn('監管條件', card['description'])
        self.assertTrue(all(row['url'] in card['description'] for row in rows))

    def test_changed_targets_dates_amounts_conditions_stages_stay_separate(self):
        original = self.row('Payward to buy Saldo Bank', summary='Payward expects to close in 2027 subject to regulatory approval')
        updates = [self.row('Payward to buy Other Bank', 'b'),
                   self.row('Payward completes acquisition of Saldo Bank', 'c'),
                   self.row('Payward to buy Saldo Bank', 'd', 'Payward expects to close in 2028 subject to regulatory approval'),
                   self.row('Payward to buy Saldo Bank for $200 million', 'e', original['summary']),
                   self.row('Payward to buy Saldo Bank', 'f', 'Payward expects to close in 2027 if approved')]
        # Different wording of the same conditional term may conservatively remain new.
        for update in updates[:4]:
            self.assertFalse(news.same_news_event(original, update), update['title'])
        self.assertFalse(news.same_news_event(original, {**original, 'published':self.now+timedelta(hours=25)}))

    def test_security_new_loss_scope_recovery_not_swallowed(self):
        original = self.row('Ledger reports suspected $10 million device drain')
        for title in ('Ledger reports suspected $20 million device drain',
                      'Ledger confirms $10 million stolen after device drain',
                      'Ledger resumes sales after $10 million device drain',
                      'Ledger reports device drain affecting new firmware'):
            self.assertFalse(news.same_news_event(original, self.row(title)), title)

    def test_cross_run_duplicate_suppressed_but_new_progress_released(self):
        first = self.row('Payward to buy Saldo Bank', 'a')
        second = self.row("Kraken Owner Payward to Buy Lithuania's Saldo Bank", 'b')
        state = self.state()
        self.run_news([first], state).assert_called_once()
        self.run_news([second], state, self.now+timedelta(minutes=5)).assert_not_called()
        self.assertIn('b', state['seen'])
        update = self.row('Payward completes acquisition of Saldo Bank', 'c')
        self.run_news([update], state, self.now+timedelta(days=1)).assert_called_once()
        self.assertIn('c', state['seen'])

    def test_scope_and_summary_deal_price_changes_are_not_suppressed(self):
        for a,b in (
            ('Bitget halts BTC withdrawals', 'Bitget halts ETH withdrawals'),
            ('Ledger reports suspected device drain affecting 100 users', 'Ledger reports suspected device drain affecting 200 users'),
            ('Ledger reports suspected device drain', 'Ledger reports suspected device drain spreads to Europe'),
        ):
            self.assertFalse(news.same_news_event(self.row(a),self.row(b)),b)
        a=self.row('Payward to buy Saldo Bank', summary='The acquisition price is $100 million.')
        b=self.row('Payward to buy Saldo Bank', summary='The acquisition price is $200 million.')
        self.assertFalse(news.same_news_event(a,b))

    def test_subject_uses_first_entity_not_another_company_in_title(self):
        row=self.row('Trezor cuts resellers after Ledger finds implant')
        self.assertEqual(editorial.event_key(row)[1],'trezor')

    def test_trading_launch_duplicates_merge_but_custody_and_regions_do_not(self):
        a=self.row('Standard Chartered unlocks direct bitcoin and ether trading for UAE clients')
        b=self.row('Standard Chartered opens Bitcoin and Ethereum trading to UAE clients')
        self.assertTrue(news.same_news_event(a,b))
        self.assertFalse(news.same_news_event(a,self.row('Standard Chartered opens Bitcoin and Ethereum trading to UK clients')))
        self.assertFalse(news.same_news_event(a,self.row('Standard Chartered holds RLUSD stablecoin for UAE clients')))

    def test_physical_crypto_theft_enters_review_without_becoming_confirmed(self):
        row=self.row('UK crypto trader says $800,000 lost in knife assault',summary='The trader claimed intruders stole crypto at knifepoint.')
        self.assertTrue(editorial.safety_candidate(row))
        self.assertIsNotNone(editorial.review_reason(row))

    def test_background_security_in_tax_proposal_is_not_new_incident(self):
        row=self.row('Crypto backlash over French proposal to report wallets',summary='The proposal follows a wave of wrench attacks in France.')
        self.assertFalse(editorial.safety_candidate(row))

    def test_similar_words_from_distinct_authorities_or_unknown_companies_are_not_one_event(self):
        for a,b in (
            ('SEC approves spot Bitcoin ETF following court decision','CFTC approves spot Bitcoin ETF following court decision'),
            ('Acme confirms wallet exploit after funds stolen','Other confirms wallet exploit after funds stolen'),
        ):
            self.assertFalse(news.same_news_event(self.row(a),self.row(b)))

    def test_merged_alias_ids_marked_only_after_successful_member_send(self):
        rows = [self.row('Payward to buy Saldo Bank','a'),self.row('Kraken to buy Saldo Bank','b')]
        state = self.state()
        self.run_news(policy.merge_pending(rows),state)
        self.assertEqual(set(state['seen']), {'a','b'})
        self.assertEqual(len(state['digest_progress']['ids']), 1)
        state = self.state()
        with self.assertRaises(RuntimeError):
            self.run_news(policy.merge_pending(rows),state,effect=RuntimeError('fail'))
        self.assertEqual(state['seen'], {})

    def test_aum_context_is_not_buy_signal_and_small_news_no_filler(self):
        row = self.row('BlackRock crypto ETF assets surge 63%', summary='ETF assets under management increase 63%.')
        row.update(title_zh='BlackRock加密ETF資產增加63%', summary_zh_points=['ETF資產管理規模增加63%。'])
        before = copy.deepcopy(row)
        card = policy.digest_card([row], self.now)
        self.assertIn('不能直接當作新增淨流入',card['description'])
        self.assertNotIn('看漲',card['description'])
        self.assertEqual(row,before)
        self.assertIsNone(editorial.short_context(self.row('Bitcoin trades steadily')))

    def test_research_context_retains_method_warning(self):
        row=self.row('Chainalysis research studies crypto payment adoption')
        self.assertIn('資料期間',editorial.short_context(row)[1])

    def test_completed_acquisition_does_not_show_pending_closing_warning(self):
        self.assertIsNone(editorial.short_context(self.row('Payward completes acquisition of Saldo Bank')))

    def test_historical_security_and_explainers_never_reenter_urgent_fallback(self):
        for title in ('Ledger recovers funds stolen last year', 'How crypto wallet exploit works'):
            self.assertFalse(policy.material_news(self.row(title)))

    def test_media_outage_and_depeg_are_review_candidates(self):
        for title in ('Binance suffers major outage', 'USDC depeg reported'):
            row=self.row(title)
            self.assertTrue(editorial.safety_candidate(row))
            self.assertIsNotNone(editorial.review_reason(row))

    def test_review_card_is_bounded_and_cannot_claim_confirmation(self):
        rows=[]
        for i in range(4):
            row=self.row('Ledger suspects wallet drain',str(i));row['review_reason']=editorial.review_reason(row)
            rows.append(row)
        card=editorial.review_card(rows,self.now)
        self.assertLess(len(card['description']),3500)
        self.assertIn('未送成員',card['footer']['text'])


if __name__ == '__main__':
    unittest.main()
