"""Source-scoped repairs: protect unrelated meanings, figures and qualifications."""
import os
import unittest
from unittest.mock import patch
import news_auto_recovery as auto
import news_copy_terms as terms
import crypto_news_notifier as news
import notification_quality as quality

class SourceCopyRepairTests(unittest.TestCase):
    def test_release_is_not_delete_and_guarded_by_backport_context(self):
        source='Developers backport fixes and cut releases immediately for easily discovered flaws.'
        self.assertIn('立即發布修正版', auto.checked_copy(source, '開發者回溯修復並立即刪除版本。'))
        for source in ('Developers delete obsolete releases.', 'The Fed cuts interest rates.',
                       'The company releases seized assets.'):
            self.assertEqual(terms.repair_translation(source,'原文刪除版本'), '原文刪除版本')

    def test_ipo_withdrawal_and_cloud_context(self):
        source='AI buildout stalls as neoclouds struggle and Solidigm pulls IPO'
        copy=auto.checked_copy(source,'新雲承壓，Solidigm 拉動 IPO，AI 的構建受挫。')
        for expected in ('撤回 IPO','新興雲端服務商','AI 基建擴張'):
            self.assertIn(expected,copy)
        self.assertIn('IPO 撤回',auto.checked_copy('Stock slumps and pulled IPOs.', '股市下跌和IPO 拉動。'))
        self.assertEqual(terms.repair_translation('Solidigm IPO pulls investors into the market.','拉動 IPO'),'拉動 IPO')

    def test_election_stakes_is_not_equity_or_staking(self):
        source='SpaceX and Tesla face high election stakes'
        self.assertIn('選舉利害關係',auto.checked_copy(source,'SpaceX和Tesla的選舉權益很高。'))
        for source in ('Tesla buys an equity stake.', 'Solana election decides validator stake.',
                       'SpaceX faces election stakes.'):
            self.assertEqual(terms.repair_translation(source,'選舉權益'),'選舉權益')

    def test_btc_cost_basis_and_daily_losses_keep_numbers(self):
        source='Bitcoin circles $81.5K ETF cost basis as stocks fall'
        copy=auto.checked_copy(source,'Bitcoin圈為81,500美元ETF成本基礎，股市下跌。')
        self.assertIn('比特幣徘徊在81,500美元',copy)
        self.assertIn('成本基準',copy)
        self.assertIn('單日跌幅擴大至3%',auto.checked_copy(
            'Bitcoin extended daily losses to 3%.','Bitcoin每日損失延長至3%。'))
        with self.assertRaises(ValueError):
            auto.checked_copy(source,'Bitcoin圈為82,500美元ETF成本基礎。')

    def test_solana_completed_not_future_and_name_preserved(self):
        source="Solana Alpenglow Goes Live in 'Most Ambitious' Upgrade Since Ethereum's Merge"
        copy=auto.checked_copy(source,'索拉娜將進行阿爾卑斯光升級。')
        self.assertIn('Solana',copy);self.assertIn('Alpenglow',copy)
        self.assertNotIn('將進行',copy)
        self.assertEqual(terms.repair_translation('Solana plans Alpenglow upgrade.','Solana將進行升級。'),'Solana將進行升級。')
        with self.assertRaises(ValueError):
            auto.checked_copy('Solana Alpenglow may go live.','Solana已上線。')

    def test_cached_cards_use_same_scoped_repairs_without_mutating_source(self):
        row={'title':'Solidigm pulls IPO','title_zh':'Solidigm拉動IPO',
             'summary':'Stock slumps and pulled IPOs.','summary_zh_points':['IPO 拉動。']}
        with patch.dict(os.environ, {'NEWS_AUTO_RECOVERY':'1'}):
            self.assertIn('撤回IPO',quality.headline(row))
            self.assertIn('IPO 撤回',str(quality.chinese_points(row)))
        self.assertEqual(row['title_zh'],'Solidigm拉動IPO')

if __name__=='__main__':unittest.main()
