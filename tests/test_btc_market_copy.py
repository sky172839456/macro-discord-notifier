import os
import unittest
from unittest.mock import patch

import crypto_news_notifier as news
import news_auto_recovery as auto
import notification_quality as quality
import slim_policy
from news_copy_terms import repair_translation

REJECTED = 'Bitcoin is rejected at $83K as US bond yields reverse higher with equities'
BAD = '比特幣在8.3萬美元被拒絕，美國公債殖利率轉升、股市走高'
TITLE = ('Bitcoin drops to $81,400 as Asian chip stocks tumble, '
         'options traders seek downside protection')
BODY = ("Bitcoin slipped 0.5% to around $81,400 even after the biggest daily spot ETF "
        "inflow in nearly a month as South Korea's Kospi index fell 3.7% on AI worries.")


class BtcMarketCopyTests(unittest.TestCase):
    def test_price_resistance_copy_preserves_directions_and_amount(self):
        result = auto.checked_copy(REJECTED, BAD)
        self.assertIn('8.3萬美元受阻', result)
        self.assertIn('殖利率轉升', result)
        self.assertIn('股市走高', result)
        self.assertNotIn('被拒絕', result)

    def test_cached_headline_render_is_repaired_without_mutating_input(self):
        row = dict(title=REJECTED, title_zh=BAD, summary='', category={'key': 'market'})
        self.assertIn('受阻', quality.headline(row))
        self.assertEqual(row['title_zh'], BAD)

    def test_changed_price_and_direction_are_not_overwritten(self):
        for source in (REJECTED.replace('$83K', '$84K'),
                       REJECTED.replace('higher', 'lower'),
                       REJECTED.replace('is rejected', 'breaks out'),
                       REJECTED+' This may change.'):
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, BAD), BAD)

    def test_regulatory_rejection_remains_a_rejection(self):
        source = 'The SEC rejected a Bitcoin ETF application.'
        copy = 'SEC 拒絕一項比特幣 ETF 申請。'
        self.assertEqual(repair_translation(source, copy), copy)

    def test_numeric_and_uncertainty_guards_still_reject_bad_copy(self):
        with self.assertRaises(ValueError):
            quality.checked_translation(REJECTED.replace('$83K', '$84K'), BAD)
        with self.assertRaises(ValueError):
            auto.checked_copy(REJECTED+' This may change.', BAD)

    def test_price_options_headline_with_etf_background_is_market(self):
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            result = news.category_for(TITLE+' '+BODY)
        self.assertEqual(result['key'], 'market')
        self.assertEqual(result['priority'], 'normal')

    def test_parse_feed_preserves_full_source_and_market_category(self):
        feed = ('<rss><channel><item><title>'+TITLE+'</title><description>'+BODY+
                '</description><link>https://example.com/btc-market</link>'
                '<pubDate>Tue, 20 Oct 2026 10:22:55 +0000</pubDate>'
                '</item></channel></rss>')
        config = {'name': 'Market fixture', 'official': False, 'stream': 'crypto'}
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            rows = news.parse_feed(feed, config)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['category']['key'], 'market')
        self.assertEqual(rows[0]['title'], TITLE)
        self.assertEqual(rows[0]['summary'], BODY)
        self.assertEqual(rows[0]['url'], 'https://example.com/btc-market')
        self.assertEqual(rows[0]['published'].isoformat(), '2026-10-20T10:22:55+00:00')

    def test_real_etf_and_new_safety_or_policy_developments_keep_priority(self):
        cases = [
            ('Bitcoin ETF records its biggest daily inflow in a month.', 'etf'),
            (TITLE+' '+BODY+' The SEC approved a new ETF.', 'regulation'),
            (TITLE+' '+BODY+' A new exchange hack was confirmed.', 'security'),
            (TITLE+' '+BODY+' Another ETF attracted inflows.', 'etf'),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(slim_policy.category(source, news.CATEGORIES)['key'], expected)

    def test_modified_source_details_do_not_use_fixed_market_exception(self):
        for source in ((TITLE+' '+BODY).replace('0.5%', '1.5%'),
                       (TITLE+' '+BODY).replace('fell 3.7%', 'rose 3.7%'),
                       (TITLE+' '+BODY).replace('inflow', 'outflow')):
            with self.subTest(source=source):
                self.assertEqual(slim_policy.category(source, news.CATEGORIES)['key'], 'etf')

    def test_whitespace_and_repeat_render_are_stable(self):
        result = auto.checked_copy('  '+REJECTED.replace(' ', '  ')+'  ', BAD)
        self.assertEqual(auto.checked_copy(REJECTED, result), result)
        spaced = (TITLE+' '+BODY).replace(' ', '  ')
        self.assertEqual(slim_policy.category(spaced, news.CATEGORIES)['key'], 'market')
