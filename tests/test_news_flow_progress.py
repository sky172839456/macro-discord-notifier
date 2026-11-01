import os
import unittest
from unittest.mock import patch

import news_auto_recovery as auto
import news_editorial as editorial

FLOW = 'Wall Street’s Fast Money Fled Bitcoin ETFs, Sovereign Funds Stepped In'
RECOVERY = "Binance hack: Investigators in a 'cat and mouse game' to recover $6.3 billion in stolen funds"


class NewsFlowProgressTests(unittest.TestCase):
    def setUp(self):
        ctx = patch.dict(os.environ, {'NEWS_AUTO_RECOVERY': '1', 'SLIM_NOTIFICATIONS': '1'})
        ctx.start()
        self.addCleanup(ctx.stop)

    def test_actual_etf_headline_repairs_cached_wrong_direction(self):
        result = auto.checked_copy(FLOW, '華爾街短線資金流入比特幣ETF，主權基金進場')
        self.assertIn('撤出', result)
        self.assertIn('主權基金', result)
        self.assertNotIn('短線資金流入', result)

    def test_fled_from_is_not_inflow_but_fled_into_is_not_reversed(self):
        with self.assertRaises(ValueError):
            auto.checked_copy('Fast money fled from Bitcoin ETFs.', '短線資金流入比特幣ETF。')
        result = auto.checked_copy('Investors fled into Bitcoin ETFs.', '投資人湧入比特幣ETF。')
        self.assertIn('湧入', result)

    def test_recovery_race_cannot_be_rendered_as_completed(self):
        for wrong in ('幣安遭駭：調查人員追回63億美元遭竊資金',
                      '幣安遭駭：調查人員已追回63億美元遭竊資金'):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                auto.checked_copy(RECOVERY, wrong)
        self.assertIn('試圖', auto.checked_copy(RECOVERY, '幣安遭駭：調查人員與駭客鬥智，試圖追回63億美元遭竊資金'))

    def test_completed_partial_and_negated_recovery_keep_distinct_stages(self):
        completed = 'Binance investigators recovered $6 million in stolen funds'
        self.assertIn('已追回', auto.checked_copy(completed, '幣安調查人員已追回600萬美元遭竊資金'))
        self.assertNotEqual(editorial.stage('Binance funds not recovered'), editorial.stage(completed))
        self.assertNotEqual(editorial.stage('Binance investigators race to recover funds'), editorial.stage(completed))

    def test_commentary_and_price_reactions_are_not_major_incidents(self):
        for title in ('Binance hack exposes centralized custody risks, analyst says',
                      'Bitcoin price falls after Binance hack',
                      'Binance hack is a buying opportunity, Wall Street analysts say',
                      'Binance hack raises questions about centralized custody',
                      'Binance hack: What it means for Bitcoin investors'):
            with self.subTest(title=title):
                self.assertFalse(auto.material_news({'title': title, 'summary': 'Commentary on the previously reported crypto incident.'}))

    def test_true_same_article_progress_survives_commentary_title(self):
        title = 'Binance hack raises questions about centralized custody'
        for summary in ('Losses revised to $7 billion.', 'Additional victims report losses.',
                        'Authorities froze $3 billion in stolen funds.',
                        'Investigators recovered $12 million.',
                        'The FBI begins an investigation.', 'Withdrawals resume today.',
                        'The loss estimate increased to $7 billion.',
                        'The victim count rises to 500.', '500 customer accounts are affected.',
                        '$12 million in stolen funds have now been recovered.',
                        'The assets are frozen.', 'The exchange confirms a breach.',
                        'Funds have been returned to users.',
                        'A new exploit drains wallets today.'):
            with self.subTest(summary=summary):
                self.assertTrue(auto.material_news({'title': title, 'summary': summary}))


if __name__ == '__main__':
    unittest.main()
