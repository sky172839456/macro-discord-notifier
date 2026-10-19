import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import crypto_news_notifier as news
import news_auto_recovery as auto
import notification_quality as quality
import slim_policy
from news_copy_terms import repair_translation


SOURCE = 'Qubic freezes chain after attacker drains 1.4K wallets with weak seeds'
DELIVERED = '攻擊者耗盡弱種子的 1.4K 錢包後， Qubic 凍結了鏈條'
BODY = ('Qubic says 87.1% of the stolen funds remain onchain and the rest were '
        'frozen at crypto exchange MEXC, as network validators prepare to vote on a recovery plan.')
BODY_ZH = ('Qubic 表示，87.1%的被盜資金仍在鏈上，其餘資金在加密資產交易所 MEXC '
           '被凍結，網路驗證者正準備就恢復計畫進行投票。')


class WalletSecurityCopyTests(unittest.TestCase):
    def test_observed_headline_preserves_wallet_count_and_subject(self):
        result = auto.checked_copy(SOURCE, DELIVERED)
        self.assertEqual(result, 'Qubic 暫停區塊鏈運作，攻擊者盜取1,400個使用弱種子金鑰的錢包內資產')
        self.assertEqual(quality.numeric_values(result), quality.numeric_values(SOURCE))

    def test_cached_headline_and_production_card_use_same_repair(self):
        row = dict(title=SOURCE, title_zh=DELIVERED, summary=BODY,
                   summary_zh_points=[BODY_ZH], source='Cointelegraph', official=False,
                   url='https://cointelegraph.com/news/qubic-freezes-chain-after-attacker-drains-14k-wallets-with-weak-seeds',
                   published=datetime(2026, 10, 19, 1, 3, 27, tzinfo=timezone.utc),
                   category=next(c for c in news.CATEGORIES if c['key'] == 'security'),
                   auto_copy_version=1)
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1'}):
            self.assertIn('弱種子金鑰', quality.headline(row))
            card = slim_policy.news_card(row)
        self.assertIn('1,400個', card['title'])
        self.assertIn('資安事件', card['title'])
        self.assertIn('媒體報導', card['title'])

    def test_original_summary_attribution_percentage_and_pending_vote_survive(self):
        result = auto.checked_copy(BODY, BODY_ZH)
        self.assertEqual(result, BODY_ZH)

    def test_incorrect_missing_and_url_slug_counts_still_rejected(self):
        for translated in (DELIVERED.replace('1.4K', '14K'), DELIVERED.replace('1.4K', ''),
                           DELIVERED.replace('1.4K', '14000')):
            with self.subTest(translated=translated), self.assertRaises(ValueError):
                auto.checked_copy(SOURCE, translated)

    def test_planned_qualified_and_denied_chain_halts_not_rewritten(self):
        for source, translated in (
            (SOURCE.replace('freezes', 'plans to freeze'), 'Qubic 計畫暫停區塊鏈，1,400個錢包遭盜'),
            (SOURCE.replace('freezes', 'may freeze'), 'Qubic 可能暫停區塊鏈，1,400個錢包遭盜'),
            (SOURCE.replace('freezes', 'denies freezing'), 'Qubic 否認暫停區塊鏈，1,400個錢包遭盜')):
            with self.subTest(source=source):
                self.assertEqual(auto.checked_copy(source, translated), translated)

    def test_lost_qualification_remains_rejected(self):
        with self.assertRaises(ValueError):
            auto.checked_copy(SOURCE.replace('freezes', 'may freeze'), DELIVERED)

    def test_money_freeze_and_different_seed_facts_not_rewritten(self):
        for source in (SOURCE.replace('freezes chain', 'freezes funds'),
                       SOURCE.replace('weak seeds', 'leaked private keys'),
                       SOURCE.replace('weak seeds', 'strong seeds'),
                       SOURCE + ' but withdrawals remain open'):
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, DELIVERED), DELIVERED)

    def test_other_wallet_and_gardening_uses_unchanged(self):
        for source, translated in (
            ('Wallet recovery with seed phrases', '使用種子片語恢復錢包'),
            ('Weak seeds reduce crop yields', '弱種子影響作物收成'),
            ('A retail chain drains wallet spending', '連鎖商店消耗錢包預算')):
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, translated), translated)

    def test_same_sentence_supports_another_explicit_count(self):
        source = SOURCE.replace('1.4K', '2K')
        result = auto.checked_copy(source, DELIVERED.replace('1.4K', '2K'))
        self.assertIn('2,000個', result)


if __name__ == '__main__':
    unittest.main()
