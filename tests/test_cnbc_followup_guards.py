"""2026-11-26 CNBC／CoinDesk 舊卡補核：碼數、as 子句、署名分析、SEC 職稱、規則制定。"""
import os
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

import news_auto_recovery as auto
import slim_policy
from content_contract import article_issues, final_article_issues, protect, stamp
from news_copy_terms import copy_rate_steps, rate_sizes, repair_translation, semantic_repairs
from news_editorial import signed_analysis
from notification_quality import (as_clause_issue, checked_translation, office_title_issue,
                                  rate_step_issue, rulemaking_issue)

WALLER = "Fed’s Waller says central bank may need to ‘shock people’ with half-point rate hike"
WALLER_BAD = '聯準會的華勒表示，央行可能需要透過升息半碼來「震撼人心」'
WALLER_GOOD = '聯準會的華勒表示，央行可能需要透過升息半個百分點來「震撼人心」'
TRUMP = 'Trump bought Nvidia, Palantir, SpaceX in September as federal deals, White House ties grew'
TRUMP_BAD = '特朗普在九月購買了 Nvidia、Palantir、SpaceX 作為聯邦交易，白宮關係增強'
TRUMP_GOOD = '聯邦合約增加、與白宮關係加深之際，川普在九月買進 Nvidia、Palantir、SpaceX'
TRUMP_BODY = ('President Trump disclosed purchases of Nvidia stock, SpaceX debt and Tesla shares in September, '
              'alongside millions of dollars in other investments.')
TRUMP_BODY_BAD = '川普總統披露了他在九月份購入的 Nvidia 股票、SpaceX 債券以及 Tesla 股份，還有其他數百萬美元的投資。'
NVDA = 'Peterson: Nvidia’s leadership crisis tests the chipmaker’s role as the ‘central bank of AI’'
NVDA_BAD = '彼得森：輝達的領導層危機考驗了這家晶片製造商作為「AI 中央銀行」的角色'
WARSH = "Peterson: The Fed's chairman sees an AI revolution coming. Now he has to figure out what it means"
WARSH_BAD = '彼特森：聯準會主席認為人工智慧革命即將到來。現在他必須弄清楚這代表什麼意思。'
NVDA_BODY = ("The tech giant's web of ties to other companies is raising the possibility that it could do "
             "far-reaching economic and financial damage.")
NVDA_BODY_ZH = '這家科技巨頭與其他公司的關係網路正增加其可能造成深遠經濟與財務損害的可能性。'
SEC = "Trump's Democratic SEC pick suggests tokenization policy deserves full rule process"
SEC_BAD = '川普提名的民主黨籍 SEC 主席人選認為，代幣化政策應經過完整的立法程序'
CNBC_URL = 'https://www.cnbc.com/2026/11/11/nvidia-jensen-huang-ai-financial-system-risk.html'
NOW = datetime(2026, 11, 20, 12, 5, tzinfo=timezone.utc)


class RateStepUnits(unittest.TestCase):
    def test_half_point_is_half_a_percentage_point_not_half_a_notch(self):
        result = auto.checked_copy(WALLER, WALLER_BAD)
        self.assertEqual(result, WALLER_GOOD)
        self.assertNotIn('半碼', result)
        self.assertIn('可能', result)
        self.assertEqual(auto.checked_copy(WALLER, result), result)

    def test_correct_notch_counts_are_kept(self):
        for source, copy_text in (
                ('Fed raises rates by a quarter point', '聯準會升息一碼'),
                ('Fed weighs a quarter-percentage-point cut', '聯準會考慮降息一碼'),
                (WALLER, '聯準會的華勒表示，央行可能需要升息兩碼來「震撼人心」'),
                ('ECB hikes by three-quarters of a percentage point', '歐洲央行升息三碼'),
                ('The Fed delivered a full-point cut', '聯準會降息四碼')):
            with self.subTest(source=source):
                self.assertIsNone(rate_step_issue(source, copy_text))
                self.assertEqual(checked_translation(source, copy_text), copy_text)

    def test_mis_scaled_or_invented_notches_are_rejected(self):
        for source, copy_text in (
                (WALLER, '央行可能需要升息一碼'),
                ('Fed raises rates by a quarter point', '聯準會升息半碼'),
                ('Fed raises rates by a quarter point', '聯準會升息兩碼'),
                ('ECB hikes by three-quarters of a percentage point', '歐洲央行升息一碼'),
                ('Fed raises interest rates again', '聯準會再升息一碼'),
                ('Candidate leads by half a point in polls', '候選人領先半碼')):
            with self.subTest(source=source, copy=copy_text):
                self.assertEqual(rate_step_issue(source, copy_text), 'rate step size changed')
                with self.assertRaisesRegex(ValueError, 'rate step size changed'):
                    checked_translation(source, copy_text)

    def test_quarter_of_a_notch_is_repaired_to_one_notch(self):
        self.assertEqual(checked_translation('Fed cuts rates by a quarter point', '聯準會降息四分之一碼'), '聯準會降息一碼')

    def test_basis_points_and_three_quarter_sizes(self):
        self.assertEqual(rate_sizes('a 50 basis point hike'), {50})
        self.assertEqual(rate_sizes('a 25bps cut'), {25})
        self.assertEqual(rate_sizes('a three-quarter-point hike'), {75})
        self.assertEqual(rate_sizes('0.5 percentage point'), {50})
        self.assertEqual(rate_sizes('Fed raises rates'), set())
        self.assertIsNone(rate_step_issue('a 50 basis point hike', '升息兩碼'))

    def test_other_words_with_ma_are_not_rate_steps(self):
        for copy_text in ('投資人加碼科技股', '基金減碼債券', '重設密碼', '籌碼面轉弱', '統一碼字元', '程式碼更新', '價碼提高', '一碼歸一碼'):
            with self.subTest(copy=copy_text):
                self.assertEqual(copy_rate_steps(copy_text), set())
                self.assertIsNone(rate_step_issue('Investors add to tech stocks', copy_text))

    def test_non_rate_half_point_is_not_rewritten(self):
        self.assertEqual(semantic_repairs('Candidate leads by half a point in polls', '領先半碼'), '領先半碼')


class AsClauseIsNotARole(unittest.TestCase):
    def test_trump_as_clause_cannot_become_acting_as_a_federal_trader(self):
        self.assertEqual(as_clause_issue(TRUMP, TRUMP_BAD), 'as-clause translated as a role')
        with self.assertRaisesRegex(ValueError, 'as-clause translated as a role'):
            auto.checked_copy(TRUMP, TRUMP_BAD)
        self.assertEqual(auto.checked_copy(TRUMP, TRUMP_GOOD), TRUMP_GOOD)

    def test_role_as_keeps_zuowei(self):
        self.assertIsNone(as_clause_issue(NVDA, NVDA_BAD))
        self.assertIsNone(as_clause_issue('Nvidia serves as the central bank of AI', 'Nvidia 作為 AI 的中央銀行'))

    def test_mixed_role_and_clause_allow_only_the_role_count(self):
        source = 'Nvidia serves as the central bank of AI as chip stocks fell'
        self.assertIsNone(as_clause_issue(source, '晶片股下跌之際，Nvidia 作為 AI 的中央銀行'))
        self.assertEqual(as_clause_issue(source, 'Nvidia 作為 AI 的中央銀行，作為晶片股下跌'), 'as-clause translated as a role')

    def test_multiword_as_phrases_and_other_connectives_are_ignored(self):
        for source in ('Banks such as JPMorgan rose', 'Gold as well as silver rallied', 'As of Monday, yields rose',
                       'Prices rose as expected', 'Bitcoin fell as much as 5%'):
            with self.subTest(source=source):
                self.assertIsNone(as_clause_issue(source, '作為測試'))
        self.assertIsNone(as_clause_issue('Housing is flashing warning signs just as the Fed weighs more interest rate hikes',
                                          '聯準會考慮進一步升息之際，房市浮現警訊'))

    def test_trump_transliteration_uses_taiwan_term(self):
        self.assertEqual(repair_translation('Trump said', '特朗普表示'), '川普表示')


# Fixtures carry no content_contract evidence; production strict mode is covered by content_preflight_check.
@patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '0'})
class SignedAnalysisLabel(unittest.TestCase):
    def row(self, title=NVDA, title_zh='Peterson：輝達的領導層危機考驗了這家晶片製造商作為「AI 中央銀行」的角色', url=CNBC_URL):
        row = {'id': 'a1', 'title': title, 'title_zh': title_zh, 'summary': NVDA_BODY, 'summary_zh_points': [NVDA_BODY_ZH],
               'url': url, 'source': 'CNBC經濟', 'official': False, 'published': datetime(2026, 11, 19, 20, 21, tzinfo=timezone.utc),
               'category': {'key': 'finance_banking', 'label': '銀行／資金'}, 'auto_copy_version': 2, 'summary_basis': 'rss'}
        return stamp(row, [{'source': NVDA_BODY, 'zh': NVDA_BODY_ZH}])

    def test_only_checked_cnbc_bylines_are_signed_analysis(self):
        self.assertEqual(signed_analysis({'title': NVDA, 'url': CNBC_URL}), 'Peterson')
        self.assertEqual(signed_analysis({'title': 'Liesman: Nvidia whiplash tests Kevin Warsh', 'url': 'https://www.cnbc.com/x.html'}), 'Liesman')
        for item in ({'title': NVDA, 'url': 'https://example.com/peterson'},
                     {'title': 'Powell: rates will stay high', 'url': CNBC_URL},
                     {'title': 'Peterson says Nvidia is fine', 'url': CNBC_URL},
                     {'title': 'Peterson Institute warns on debt', 'url': CNBC_URL}):
            with self.subTest(item=item):
                self.assertIsNone(signed_analysis(item))

    def test_byline_transliterations_become_the_author_name(self):
        self.assertEqual(checked_translation(NVDA, NVDA_BAD), 'Peterson：輝達的領導層危機考驗了這家晶片製造商作為「AI 中央銀行」的角色')
        self.assertTrue(checked_translation(WARSH, WARSH_BAD).startswith('Peterson：聯準會主席'))
        with self.assertRaisesRegex(ValueError, 'byline not preserved'):
            checked_translation(NVDA, '輝達的領導層危機考驗了這家晶片製造商作為「AI 中央銀行」的角色')
        self.assertEqual(repair_translation('Peterson Institute warns on debt', '彼得森研究所警告債務'), '彼得森研究所警告債務')

    def test_byline_is_protected_from_translation(self):
        request, mapping = protect(NVDA)
        self.assertNotIn('Peterson', request)
        self.assertIn('Peterson', mapping.values())
        self.assertEqual(protect('Powell: rates stay high')[1], {})

    def test_digest_labels_analysis_and_keeps_verified_title(self):
        row = self.row()
        card = slim_policy.digest_card([row], NOW)
        self.assertIn('**01｜分析｜Peterson：輝達', card['description'])
        self.assertIn('分析／專欄｜' + NVDA_BODY_ZH, card['description'])
        self.assertNotIn('媒體報導', card['description'])
        self.assertEqual(final_article_issues([row], card, NOW), [])

    def test_ordinary_cnbc_news_keeps_media_label(self):
        row = self.row(title=WALLER, title_zh=WALLER_GOOD, url='https://www.cnbc.com/2026/11/18/federal-reserve-governor-christopher-waller.html')
        card = slim_policy.digest_card([row], NOW)
        self.assertIn('媒體報導｜', card['description'])
        self.assertNotIn('分析', card['description'])

    def test_single_card_labels_analysis(self):
        card = slim_policy.news_card(self.row(), now=NOW)
        self.assertIn('分析／專欄｜Peterson：', card['title'])
        self.assertTrue(card['fields'][0]['value'].startswith('分析／專欄｜[CNBC經濟]'))


class AgencyTitlesAndRulemaking(unittest.TestCase):
    def test_sec_pick_is_not_chair_and_rule_process_is_not_legislation(self):
        result = auto.checked_copy(SEC, SEC_BAD)
        self.assertEqual(result, '川普提名的民主黨籍 SEC 人選認為，代幣化政策應經過完整的規則制定程序')
        self.assertEqual(auto.checked_copy(SEC, result), result)
        self.assertEqual(checked_translation('Trump picks SEC commissioner nominee', '川普的 SEC 主席人選'), '川普的 SEC 委員人選')

    def test_unsupported_chair_titles_are_rejected(self):
        self.assertEqual(office_title_issue('Fed’s Waller says rates may rise', '聯準會主席華勒表示可能升息'), 'translation added a chair title')
        with self.assertRaisesRegex(ValueError, 'chair title'):
            checked_translation('SEC commissioner Peirce says tokens need clarity', 'SEC 主席 Peirce 表示代幣需要明確規範')

    def test_supported_chair_and_other_presidents_are_kept(self):
        for source, copy_text in ((WARSH, 'Peterson：聯準會主席認為人工智慧革命即將到來'),
                                  ('SEC Chair Atkins backs tokenization', 'SEC 主席 Atkins 支持代幣化'),
                                  ('Chinese President Xi meets Trump', '中國國家主席習近平與川普會面'),
                                  ('Fed’s Waller says rates may rise', '聯準會理事華勒表示利率可能上升')):
            with self.subTest(copy=copy_text):
                self.assertIsNone(office_title_issue(source, copy_text))

    def test_rulemaking_cannot_become_legislation(self):
        source = 'The SEC proposed rules for tokenized stocks'
        self.assertEqual(rulemaking_issue(source, 'SEC 提出代幣化股票立法'), 'agency rulemaking translated as legislation')
        with self.assertRaisesRegex(ValueError, 'rulemaking translated as legislation'):
            checked_translation(source, 'SEC 提出代幣化股票立法')
        self.assertEqual(checked_translation('She wants a formal rulemaking with notice-and-comment', '她希望經過立法程序並公開徵詢意見'),
                         '她希望經過規則制定程序並公開徵詢意見')

    def test_real_legislation_keeps_lifa(self):
        for source in ('Congress advances stablecoin legislation after proposed rules stall',
                       'OCC final rules implement the GENIUS Act', 'Lawmakers debate the rule process bill'):
            with self.subTest(source=source):
                self.assertIsNone(rulemaking_issue(source, '立法程序'))
                self.assertEqual(semantic_repairs(source, '立法程序'), '立法程序')


# Fixtures carry no content_contract evidence; production strict mode is covered by content_preflight_check.
@patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '0'})
class DebtAndStaleCopy(unittest.TestCase):
    def test_listed_company_debt_is_not_narrowed_to_bonds(self):
        result = auto.checked_copy(TRUMP_BODY, TRUMP_BODY_BAD)
        self.assertIn('SpaceX 債務工具', result)
        self.assertIn('Nvidia 股票', result)
        self.assertIn('Tesla 股份', result)
        for source in ('Trump disclosed purchases of Nvidia stock and SpaceX bonds', 'The debt market rallied'):
            with self.subTest(source=source):
                self.assertEqual(semantic_repairs(source, '債券'), '債券')

    def test_queued_copy_from_before_the_fix_is_retranslated_not_sent(self):
        row = {'id': 'w1', 'title': WALLER, 'title_zh': WALLER_BAD, 'summary': TRUMP_BODY,
               'summary_zh_points': [TRUMP_BODY_BAD], 'url': 'https://www.cnbc.com/w.html', 'source': 'CNBC金融',
               'official': False, 'published': datetime(2026, 11, 18, 12, 50, tzinfo=timezone.utc)}
        stamp(row, [{'source': TRUMP_BODY, 'zh': TRUMP_BODY_BAD}])
        issues = article_issues(row)
        self.assertIn('title_translation_stale', issues)
        self.assertIn('segment_translation_stale', issues)
        fixed = dict(row, title_zh=WALLER_GOOD, summary_zh_points=[auto.checked_copy(TRUMP_BODY, TRUMP_BODY_BAD)])
        stamp(fixed, [{'source': TRUMP_BODY, 'zh': fixed['summary_zh_points'][0]}])
        self.assertEqual(article_issues(fixed), [])

    def test_repairs_are_idempotent(self):
        for source, copy_text in ((WALLER, WALLER_BAD), (SEC, SEC_BAD), (NVDA, NVDA_BAD), (WARSH, WARSH_BAD), (TRUMP_BODY, TRUMP_BODY_BAD)):
            with self.subTest(source=source):
                once = semantic_repairs(source, copy_text)
                self.assertEqual(semantic_repairs(source, once), once)


if __name__ == '__main__':
    unittest.main()
