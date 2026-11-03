import unittest
from unittest.mock import patch
import os
from datetime import datetime, timezone
import crypto_news_notifier as news
import news_editorial as editorial
import news_auto_recovery as auto
import notification_quality as quality
import slim_policy


class LaunchAuditTests(unittest.TestCase):
    def row(self, title, summary='BTC ETF outflows followed the earlier Binance hack.'):
        return {'title': title, 'summary': summary}

    def test_commentary_is_not_a_new_security_alert(self):
        titles = [
            'Morning Minute: Tom Lee Calls the Binance Hack Bullish for Ethereum',
            'CZ warns of more AI-driven hacks following Binance\'s historic $6.4 billion heist',
            'South Korea asks its biggest banks how a major crypto hack would hit them',
        ]
        for title in titles:
            row = self.row(title)
            with self.subTest(title=title), patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
                self.assertFalse(editorial.safety_candidate(row))
                self.assertFalse(auto.material_news(row))
                self.assertEqual(slim_policy.category(editorial.text(row), news.CATEGORIES)['priority'], 'normal')

    def test_concrete_new_safety_updates_survive_commentary(self):
        for summary in ['A new exchange hack was confirmed today.',
                        'Losses revised to $7 billion.',
                        'Withdrawals resumed after the review.',
                        'Police opened an investigation.',
                        'Authorities recovered funds for victims.']:
            row = self.row('Morning Minute: Tom Lee Calls the Binance Hack Bullish for Ethereum', summary)
            with self.subTest(summary=summary):
                self.assertFalse(editorial.commentary_only(row))
                self.assertTrue(auto.material_news(row))

    def test_plural_treasury_companies_and_rankings(self):
        source = 'Strive added 124 Bitcoin for $10 million, ranking third among treasury companies.'
        copy = quality.checked_translation(source, 'Strive增加124個Bitcoin，金額1000萬美元，在財政部公司排名第三。')
        self.assertIn('資產儲備公司', copy)
        self.assertNotIn('財政部', copy)
        self.assertEqual(quality.checked_translation('U.S. Treasury ranks banks', '美國財政部對銀行排名'), '美國財政部對銀行排名')

    def test_flows_are_not_customer_losses(self):
        source = 'Spot ETFs shed $399 million while Binance customers saw net outflows of $4.72 billion.'
        result = quality.checked_translation(source, '現貨ETF虧損3.99億美元，幣安客戶淨虧損47.2億美元。')
        self.assertNotIn('虧損', result)
        self.assertIn('流出3.99億', result)
        self.assertIn('流出47.2億', result)
        loss = 'Binance customers recorded trading losses of $10 million.'
        self.assertIn('虧損', quality.checked_translation(loss, '幣安客戶交易虧損1000萬美元。'))

    def test_numeric_guards_still_reject_changed_amounts(self):
        with self.assertRaises(ValueError):
            quality.checked_translation('ETFs shed $399 million', 'ETF虧損4億美元')

    def test_same_url_different_amount_is_not_merged_even_for_commentary(self):
        title = "CZ warns of more AI-driven hacks following Binance's historic $6.4 billion heist"
        row = dict(self.row(title), url='https://example.com/article', published='2026-11-03T14:22:00+00:00')
        self.assertFalse(auto.same_article(row, {**row, 'title': title.replace('6.4', '6.3')}))
        self.assertTrue(auto.same_article(row, {**row, 'title': title.replace('historic', 'historical')}))

    def test_changed_article_is_labelled_as_source_update(self):
        now = datetime(2026, 11, 4, tzinfo=timezone.utc)
        row = dict(self.row('Bitcoin exchange hack loss revised to $6.3 billion'),
                   title_zh='比特幣交易所駭客事件損失修正為63億美元',
                   summary='', summary_zh_points=[], source_update=True,
                   source='Fixture', official=False, published=now, url='https://example.com/article',
                   category={'key':'security','label':'資安事件'}, auto_copy_version=2)
        card = slim_policy.news_card(row, now=now)
        self.assertIn('來源更新｜', card['title'])
        self.assertIn('本次內容有變動', card['description'])
        self.assertIn('來源更新', slim_policy.digest_card([row], now)['description'])

    def test_route_marks_update_without_changing_delivered_history(self):
        now = datetime(2026, 11, 4, tzinfo=timezone.utc)
        title = 'Binance hack losses revised to $6.3 billion'
        row = dict(self.row(title, ''), id='new', title_zh='幣安駭客事件損失修正為63億美元',
                   summary_zh_points=['幣安駭客事件損失修正為63億美元。'],
                   url='https://example.com/cz', published=now, official=False, source='Fixture',
                   category={'key':'market','label':'市場觀點'}, auto_copy_version=2)
        previous = {**row, 'title': title.replace('6.3', '6.4'), 'date':now.isoformat(),
                    'published': now.isoformat()}
        state = {'seen':{'previous':'2026-11-04'},'headline_history':[previous]}
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1'}), \
                patch.object(news, 'add_translated_title', side_effect=lambda item, *_: item), \
                patch.object(news, 'save_state'):
            ready = auto.route([row], state, now)
        self.assertEqual(len(ready), 1)
        self.assertTrue(ready[0]['source_update'])
        self.assertEqual(state['seen'], {'previous':'2026-11-04'})
        self.assertEqual(state['headline_history'], [previous])
