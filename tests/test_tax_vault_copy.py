import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from xml.sax.saxutils import escape

import crypto_news_notifier as news
import news_auto_recovery as auto
import notification_quality as quality
import slim_policy

FRANCE = 'France advances stablecoin tax, eyes self-custodial wallets and exit tax proposals'
FRANCE_BODY = ('France’s National Assembly adopted a crypto tax amendment targeting certain stablecoin swaps, '
               'while separate proposals on exit taxes and self-custodial wallet reporting remain under consideration.')
FRANCE_ZH = ('法國國民議會通過了一項針對某些穩定幣掉期的加密稅修正案，而關於出口稅和自我保管錢包報告的獨立提案仍在考慮中。')
VAULT = 'Crypto vault deposits top $10 billion as lending risks draw regulatory scrutiny'
VAULT_BODY = ('Curator-managed lending strategies are attracting institutional capital, while exposing depositors '
              'to collateral, liquidity and smart-contract risks.')
USD1 = 'World Liberty’s USD1 stablecoin sheds $400M in market cap in two weeks'
USD1_ZH = 'World Liberty 的美元穩定幣在兩週內市值縮水 4億美元'


class TaxVaultCopyTests(unittest.TestCase):
    def setUp(self):
        context = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1'})
        context.start()
        self.addCleanup(context.stop)

    def test_actual_tax_headline_preserves_proposal_stage(self):
        title = auto.checked_copy(FRANCE, '法國推出穩定幣稅、自我保管錢包和出口稅提案')
        self.assertEqual(title, '法國推進穩定幣稅制，研議自託管錢包與離境稅提案')

    def test_summary_keeps_adopted_amendment_separate_from_pending_proposals(self):
        result = auto.checked_copy(FRANCE_BODY, FRANCE_ZH)
        self.assertIn('國民議會通過', result)
        self.assertIn('穩定幣兌換', result)
        self.assertIn('離境稅和自託管錢包', result)
        self.assertIn('獨立提案仍在考慮中', result)
        self.assertNotIn('出口稅', result)

    def test_tax_article_parses_as_policy_not_stablecoin(self):
        xml = (f'<rss><channel><item><title>{escape(FRANCE)}</title>'
               f'<description>{escape(FRANCE_BODY)}</description><link>https://example.invalid/tax</link>'
               '<pubDate>Mon, 19 Oct 2026 10:22:30 GMT</pubDate></item></channel></rss>')
        row = news.parse_feed(xml, {'name': '媒體', 'official': False})[0]
        self.assertEqual(row['category']['key'], 'regulation')
        self.assertEqual(row['category']['priority'], 'normal')

    def test_security_tax_story_retains_security_precedence(self):
        self.assertEqual(news.category_for('Crypto tax proposal site hacked after attack')['key'], 'security')

    def test_stablecoin_business_and_tax_software_do_not_become_policy(self):
        for source in ('Circle stablecoin market cap grows',
                       'Stablecoin tax software startup raises capital',
                       'Stablecoin tax-reporting software adds features'):
            with self.subTest(source=source):
                self.assertEqual(news.category_for(source)['key'], 'stablecoin')

    def test_genuine_export_tax_unchanged_and_mixed_meanings_rejected(self):
        self.assertEqual(auto.checked_copy('France considers export taxes', '法國考慮出口稅'), '法國考慮出口稅')
        with self.assertRaises(ValueError):
            auto.checked_copy('France weighs exit taxes and export taxes', '法國考慮離境稅和出口稅')

    def test_qualified_or_denied_proposals_not_rewritten_as_actual_progress(self):
        for source, translated in (
            (FRANCE.replace('advances', 'may advance'), '法國可能推進穩定幣稅與離境稅提案'),
            (FRANCE.replace('advances', 'denies advancing'), '法國否認推進穩定幣稅與離境稅提案')):
            with self.subTest(source=source):
                self.assertEqual(auto.checked_copy(source, translated), translated)
        with self.assertRaises(ValueError):
            auto.checked_copy(FRANCE.replace('advances', 'may advance'), '法國推進穩定幣稅與離境稅提案')

    def test_defi_curator_and_vault_terms(self):
        title = auto.checked_copy(VAULT, '加密保管庫存款高達 100億美元，因為貸款風險受到監管機構的審查')
        body = auto.checked_copy(VAULT_BODY, '策展人管理的貸款策略正在吸引機構資本，同時使存款人面臨抵押品、流動性和智能合約風險。')
        self.assertIn('加密資產金庫', title)
        self.assertIn('策略管理人管理的貸款策略', body)
        self.assertIn('抵押品、流動性和智能合約風險', body)
        self.assertEqual(quality.numeric_values(title), quality.numeric_values(VAULT))

    def test_art_curator_and_mixed_curators_not_blindly_replaced(self):
        self.assertEqual(auto.checked_copy('Museum curator oversees a new exhibition', '博物館策展人負責新展覽'), '博物館策展人負責新展覽')
        with self.assertRaises(ValueError):
            auto.checked_copy('Museum curators discuss curator-managed lending strategies', '博物館策展人討論策展人管理的貸款策略')

    def test_usd1_ticker_restored_without_turning_market_cap_into_flows(self):
        result = auto.checked_copy(USD1, USD1_ZH)
        self.assertIn('USD1 穩定幣', result)
        self.assertIn('市值縮水', result)
        self.assertNotIn('淨流出', result)
        self.assertEqual(quality.numeric_values(result), quality.numeric_values(USD1))

    def test_usd1_identity_guard_does_not_touch_other_stablecoins(self):
        self.assertEqual(auto.checked_copy('World Liberty’s USDC stablecoin market cap', 'World Liberty 的 USDC 穩定幣市值'), 'World Liberty 的 USDC 穩定幣市值')
        correct = 'World Liberty 的 USD1 穩定幣在兩週內市值縮水4億美元'
        self.assertEqual(auto.checked_copy(USD1, correct), correct)
        with self.assertRaises(ValueError):
            auto.checked_copy(USD1, 'USDC 穩定幣在兩週內市值縮水4億美元')

    def test_numeric_guard_still_rejects_wrong_market_cap(self):
        with self.assertRaises(ValueError):
            auto.checked_copy(USD1, USD1_ZH.replace('4億', '40億'))

    def test_cached_digest_renders_repaired_copy_and_policy_category(self):
        row = dict(title=FRANCE, title_zh='法國推出穩定幣稅、自我保管錢包和出口稅提案',
                   summary=FRANCE_BODY, summary_zh_points=[FRANCE_ZH],
                   category=news.category_for(FRANCE + ' ' + FRANCE_BODY), auto_copy_version=1,
                   source='媒體', official=False, url='https://example.invalid/tax',
                   published=datetime(2026, 10, 19, 10, 22, 30, tzinfo=timezone.utc))
        result = slim_policy.digest_card([row], datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
        self.assertIn('監管／政策', result['description'])
        self.assertIn('離境稅', result['description'])
        self.assertNotIn('出口稅', result['description'])
        self.assertIn('媒體報導', result['description'])


if __name__ == '__main__':
    unittest.main()
