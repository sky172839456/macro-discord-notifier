"""2026-11-26：strike 不是只有罷工（軍事打擊、選擇權履約價、Strike 公司），真的罷工照舊。

英文原文取自 7～10 月幣圈又有事被誤譯成「罷工」的實際卡片。
"""
import unittest

from content_contract import article_issues
from news_copy_terms import repair_translation, semantic_repairs, strike_meaning
from notification_quality import checked_translation


MILITARY = (
    ('Bitcoin steadies near $82,500 after Trump rules out Iran strike before midterms',
     '特朗普排除伊朗罷工後，Bitcoin 穩定在 82,500 美元附近'),
    ('Bitcoin rebounds to $82,000 as Trump rules out Iran strikes, oil drops',
     'Bitcoin 反彈至 82,000 美元，因為特朗普排除伊朗罷工，油價下跌'),
    ('Bitcoin drops 2.2% as Ukraine, Iran strikes send oil toward one-month high',
     'Bitcoin 下跌 2.2%，因為烏克蘭，伊朗罷工將石油推向一個月高點'),
    ('Bitcoin price eyes $66K as US stocks rise on Iran-strike pause',
     '隨著美國股市因伊朗罷工暫停而上漲，Bitcoin 價格關注 66K 美元'),
    ('Solana, ether, xrp lead majors slide as Iran strikes drive a broad risk selloff',
     '隨著伊朗罷工推動廣泛的風險拋售，Solana、ether、xrp 領跌'),
    ('U.S. strikes on Iran fail to stir bitcoin, on track for best month since November 2024',
     '美國對伊朗的罷工未能攪動 Bitcoin，有望創 2024 年 11 月以來最佳月份'),
)


class StrikeMeaningTests(unittest.TestCase):
    def test_military_strikes_become_military_strikes(self):
        for source, bad in MILITARY:
            with self.subTest(source=source):
                fixed = strike_meaning(source, bad)
                self.assertNotIn('罷工', fixed)
                self.assertIn('軍事打擊', fixed)
                self.assertEqual(strike_meaning(source, fixed), fixed)

    def test_full_repair_chain_also_uses_taiwan_terms(self):
        source, bad = MILITARY[0]
        fixed = repair_translation(source, bad)
        self.assertEqual(fixed, '川普排除伊朗軍事打擊後，Bitcoin 穩定在 82,500 美元附近')
        self.assertEqual(checked_translation(source, bad), fixed)

    def test_options_strike_is_strike_price(self):
        source = ("Deribit's strike-by-strike data shows a book stacked with calls, and one price level "
                  'drawing hedging pressure from both sides at once.')
        self.assertIn('履約價', strike_meaning(source, '德裏比特（Deribit）的罷工數據顯示，一本書堆滿了呼籲'))
        self.assertIn('履約價', strike_meaning('$15.6 billion bitcoin options expire Friday, max pain at the 80,000 strike',
                                               '156億美元比特幣期權週五到期，最大痛點在 80,000 罷工'))

    def test_strike_company_keeps_its_name(self):
        fixed = strike_meaning('Tether-backed Twenty One, Strike merger plan scrapped: Bloomberg',
                               'Tether 支持的 Twenty One，罷工合併計劃被取消：彭博社')
        self.assertEqual(fixed, 'Tether 支持的 Twenty One，Strike合併計劃被取消：彭博社')
        self.assertIn('Strike', strike_meaning('Jack Mallers says Strike app adds bitcoin loans', 'Jack Mallers 表示罷工應用新增比特幣貸款'))

    def test_real_labor_strikes_are_untouched(self):
        for source, copy_text in (('Dockworkers go on strike at major US ports', '美國主要港口碼頭工人罷工'),
                                  ('Samsung union strike halts chip lines', '三星工會罷工導致晶片產線停擺'),
                                  ('Coinbase customer support staff walkout enters second week', '罷工進入第二週')):
            with self.subTest(source=source):
                self.assertEqual(strike_meaning(source, copy_text), copy_text)

    def test_unresolved_or_mixed_meanings_are_rejected(self):
        for source, copy_text in (('Traders strike back after selloff', '交易員在拋售後罷工'),
                                  ('Workers strike as Iran missile attacks hit refineries', '工人罷工，伊朗飛彈攻擊煉油廠'),
                                  ('Options traders hedge as Iran strikes lift oil', '期權交易員避險，伊朗罷工推高油價')):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    strike_meaning(source, copy_text)

    def test_untouched_when_no_strike_word_or_no_bad_copy(self):
        self.assertEqual(strike_meaning('Bitcoin rises as oil falls', '比特幣上漲，油價下跌'), '比特幣上漲，油價下跌')
        self.assertEqual(strike_meaning('Trump rules out Iran strike', '川普排除對伊朗的軍事打擊'), '川普排除對伊朗的軍事打擊')
        self.assertEqual(semantic_repairs('Trump rules out Iran strike', '川普排除對伊朗的軍事打擊'), '川普排除對伊朗的軍事打擊')

    def test_queued_copy_with_old_strike_translation_is_retranslated_not_sent(self):
        from content_contract import stamp
        source, bad = MILITARY[1]
        row = stamp({'title': source, 'title_zh': bad, 'summary': source, 'summary_zh_points': [bad],
                     'url': 'https://www.coindesk.com/x'}, [{'source': source, 'zh': bad}])
        issues = article_issues(row, required=False)
        self.assertIn('title_translation_stale', issues)
        self.assertIn('segment_translation_stale', issues)


if __name__ == '__main__':
    unittest.main()
