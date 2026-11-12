"""Real 2026-11 machine translations seen in member channels; synthetic English sources."""
import unittest

from notification_quality import polish_chinese


class TaiwanTerms(unittest.TestCase):
    def test_one_card_uses_one_fed_name_and_taiwan_terms(self):
        text = polish_chinese('Fed officials weigh hikes as AI hackers target networks',
                              '美聯儲與聯儲局官員考慮加息，人工智能黑客攻擊網絡與數據中心')
        self.assertEqual(text, '聯準會與聯準會官員考慮升息，人工智慧駭客攻擊網路與資料中心')

    def test_proper_names_are_restored_only_when_source_names_them(self):
        self.assertIn('Securitize', polish_chinese('Securitize agrees to buy River One', '證券化同意購買 River One'))
        self.assertIn('證券化', polish_chinese('Banks expand mortgage securitization', '銀行擴大房貸證券化'))
        self.assertIn('Elliptic', polish_chinese('North Korean hackers create memecoins: Elliptic', '朝鮮黑客創建 memecoins：橢圓形'))
        self.assertIn('Meta 前景', polish_chinese('S&P revises Meta outlook to negative', '標準普爾將現金流量問題的元前景修訂為負面'))
        self.assertIn('逢低買進', polish_chinese('Stock ETF buyers slam the dip as Bitcoin funds bleed', '股票 ETF 買家猛烈抨擊 DIP'))
        self.assertIn('BlackRock Bitcoin', polish_chinese('BlackRock Bitcoin ETF outflows hit $1.66B', 'BlackRockBitcoin ETF 流出'))

    def test_numbers_are_untouched(self):
        self.assertIn('2.7億美元', polish_chinese('Banks commit $270M', '銀行承諾2.7億美元，美聯儲'))


if __name__ == '__main__':
    unittest.main()
