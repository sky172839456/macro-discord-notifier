"""Synthetic headlines modelled on the 2026-11-11 digest (FARO reported by three outlets)."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import crypto_news_notifier as news


def row(title, summary, source, hours=0):
    return {'id': source + title[:8], 'title': title, 'summary': summary, 'source': source, 'official': False,
            'url': 'https://example.com/' + source, 'category': {'key': 'stablecoin', 'label': '穩定幣'},
            'published': datetime(2026, 11, 11, 2, tzinfo=timezone.utc) + timedelta(hours=hours)}


class NamedAmountDedup(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'})
        patcher.start(); self.addCleanup(patcher.stop)

    def test_one_project_and_amount_from_three_outlets_is_one_item(self):
        rows = [row('Global banks commit $270M to stablecoin venture set to launch in 2027',
                    'Project FARO, backed by Goldman Sachs, Citigroup and BBVA, has secured funding.', 'Cointelegraph', 5),
                row('Goldman, Citi and global banks commit $270 million to challenge crypto stablecoin giants',
                    'The money backs a US-registered issuer code-named Project FARO.', 'Decrypt', 1),
                row('Goldman Sachs, Citi among banks putting $270 million into stablecoin joint venture',
                    'The venture, called Project Faro, plans a dollar-denominated stablecoin.', 'CoinDesk', 0)]
        self.assertEqual(len(news.deduplicate(rows)), 1)

    def test_same_name_different_amount_or_entity_stays_separate(self):
        a = row('Strategy buys $82 million of Bitcoin', 'Strategy added BTC to its treasury.', 'Decrypt')
        b = row('Strategy buys $150 million of Bitcoin', 'Strategy added BTC to its treasury.', 'CoinDesk', 2)
        c = row('Metaplanet buys $82 million of Bitcoin', 'Metaplanet added BTC to its treasury.', 'CoinDesk', 2)
        self.assertFalse(news.same_named_amount_event(a, b))
        self.assertFalse(news.same_named_amount_event(a, c))

    def test_later_stage_of_same_incident_is_not_swallowed(self):
        first = row('Mercado Bitcoin reopens after $49 million hack, no withdrawal timeline',
                    'Customers can view balances as access returns in phases.', 'Cointelegraph')
        later = row('Mercado Bitcoin resumes cash withdrawals after $49 million hack',
                    'Customers can withdraw via Pix starting next week.', 'Cointelegraph', 20)
        self.assertFalse(news.same_named_amount_event(first, later))

    def test_more_than_a_day_apart_is_not_merged(self):
        a = row('FARO raises $270M', 'Project FARO stablecoin.', 'Decrypt')
        b = row('FARO raises $270M', 'Project FARO stablecoin.', 'CoinDesk', 30)
        self.assertFalse(news.same_named_amount_event(a, b))

    def test_money_units_normalise(self):
        self.assertEqual(news.money_amounts('$270M'), news.money_amounts('$270 million'))
        self.assertEqual(news.money_amounts('$2.85 billion'), news.money_amounts('$2850M'))


if __name__ == '__main__':
    unittest.main()
