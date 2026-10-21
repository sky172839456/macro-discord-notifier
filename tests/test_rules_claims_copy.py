import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import crypto_news_notifier as news
import news_auto_recovery as auto
import notification_quality as quality
import slim_policy
from news_copy_terms import repair_translation

QUBIC = 'Qubic restarts blockchain, opens recovery claims after $1.4M hack'
QBODY = 'The network’s validators approved a recovery plan and opened claims until May 1, 2027.'
GAIN = 'Crypto rises with Asian tech stocks, zcash extends gain after setting upgrade date'
FED = 'Housing is flashing warning signs just as the Fed weighs more interest rate hikes'
LLOYDS = ('Lloyds drew the most complaints despite having no published policy restricting crypto '
          'transfers, according to a Stand With Crypto report.')
OCC = 'OCC Finalizes GENIUS Act Stablecoin Rules Ahead of January Deadline'
OBODY = ('The rule sets reserve, redemption and risk standards for issuers, but the OCC has yet '
         'to say when it will begin accepting applications.')


class RulesClaimsCopyTests(unittest.TestCase):
    def test_recovery_claims_are_applications_not_statements_or_paid_funds(self):
        fixed = auto.checked_copy(QUBIC, 'Qubic 重啟區塊鏈，在140萬美元駭客攻擊後開啟恢復聲明')
        self.assertIn('140萬美元', fixed)
        self.assertIn('資產追回申請', fixed)
        self.assertNotIn('聲明', fixed)
        self.assertNotIn('已賠償', fixed)

    def test_date_with_may_is_still_deferred_by_existing_safety_guard(self):
        # 此已知摘要限制另列待核，本輪不放寬安全閘來恢復全文。
        with self.assertRaises(ValueError):
            auto.checked_copy(QBODY, '該網路驗證者已通過復原計畫，並開放申請至2027年5月1日。')
        self.assertEqual(repair_translation(QBODY, '原摘要'), '原摘要')

    def test_changed_recovery_amount_stage_and_deadline_are_not_overwritten(self):
        for source in (QUBIC.replace('$1.4M', '$2.4M'), QUBIC.replace('restarts', 'may restart'),
                       QBODY.replace('May 1', 'June 1'), QBODY.replace('approved', 'rejected'),
                       QBODY+' Applications may be rejected.'):
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, '待原文譯文'), '待原文譯文')

    def test_cached_recovery_render_keeps_deadline_and_does_not_mutate_cache(self):
        row = dict(title=QUBIC, title_zh='Qubic 開啟恢復聲明140萬美元',
                   summary=QBODY, summary_zh_points=['通過恢復計畫2027年5月1日'])
        self.assertIn('資產追回申請', quality.headline(row))
        self.assertEqual(row['summary_zh_points'], ['通過恢復計畫2027年5月1日'])

    def test_price_gain_means_rally_not_income(self):
        fixed = auto.checked_copy(GAIN, '加密資產隨亞洲科技股上漲，zcash設定升級日期後延長收益')
        self.assertIn('Zcash', fixed)
        self.assertIn('延續漲勢', fixed)
        self.assertNotIn('收益', fixed)

    def test_changed_gain_direction_or_hypothetical_stage_not_overwritten(self):
        for source in (GAIN.replace('rises', 'falls'), GAIN.replace('extends gain', 'pares losses'),
                       GAIN.replace('setting', 'delaying'), GAIN+' This may change.'):
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, '原譯文'), '原譯文')

    def test_financial_income_and_capital_gains_are_not_globally_changed(self):
        for source in ('The fund extends income payments.', 'France increases capital gains tax.'):
            self.assertEqual(repair_translation(source, '資本利得與收益'), '資本利得與收益')

    def test_fed_consideration_is_not_an_executed_hike(self):
        fixed = auto.checked_copy(FED, '就在聯準會升息之際，房地產閃爍警告信號')
        self.assertIn('考慮進一步升息', fixed)
        self.assertNotIn('已升息', fixed)

    def test_actual_hike_cut_or_future_qualification_not_overwritten(self):
        for source in (FED.replace('weighs more interest rate hikes', 'raises interest rates'),
                       FED.replace('hikes', 'cuts'), FED+' It may hold rates instead.'):
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, '原譯文'), '原譯文')

    def test_lloyds_receives_complaints_and_report_attribution_remains(self):
        fixed = auto.checked_copy(LLOYDS, '根據Stand With Crypto報告，Lloyds提出最多投訴，沒有公布限制政策。')
        self.assertIn('Lloyds 收到的投訴最多', fixed)
        self.assertIn('Stand With Crypto 報告', fixed)
        self.assertIn('未公布限制', fixed)
        self.assertNotIn('提出最多', fixed)

    def test_actual_complaint_filing_is_not_changed(self):
        source = 'Lloyds filed complaints against a crypto exchange.'
        self.assertEqual(repair_translation(source, 'Lloyds 提出投訴'), 'Lloyds 提出投訴')
        self.assertEqual(repair_translation(LLOYDS.replace('no published policy', 'a published policy'),
                                            '原譯文'), '原譯文')

    def test_occ_rules_category_beats_reserve_etf_keyword(self):
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            result = news.category_for(OCC+' '+OBODY)
        self.assertEqual(result['key'], 'regulation')
        self.assertEqual(result['priority'], 'critical' if slim_policy.material_news({'title': OCC+' '+OBODY}) else 'normal')

    def test_occ_source_summary_keeps_applications_not_yet_open(self):
        fixed = auto.checked_copy(OBODY, '該規則為發行人設定準備金、贖回與風險標準，但OCC尚未說明何時開始接受申請。')
        self.assertIn('尚未', fixed)
        self.assertIn('接受申請', fixed)

    def test_occ_rss_parse_preserves_complete_source_link_and_time(self):
        feed = ('<rss><channel><item><title>'+OCC+'</title><description>'+OBODY+
                '</description><link>https://decrypt.co/381502/rules</link>'
                '<pubDate>Wed, 21 Oct 2026 11:52:23 +0000</pubDate></item></channel></rss>')
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            rows = news.parse_feed(feed, {'name': 'Decrypt', 'official': False})
        self.assertEqual(rows[0]['category']['key'], 'regulation')
        self.assertEqual(rows[0]['summary'], OBODY)
        self.assertEqual(rows[0]['url'], 'https://decrypt.co/381502/rules')
        self.assertEqual(rows[0]['published'], datetime(2026, 10, 21, 11, 52, 23, tzinfo=timezone.utc))

    def test_occ_new_security_or_etf_detail_is_not_fixed_to_regulation(self):
        for source, key in ((OCC+' '+OBODY+' A new hack was confirmed.', 'security'),
                            (OCC+' '+OBODY+' A spot ETF launched.', 'etf'),
                            ('OCC Bank holds bitcoin ETF reserves.', 'etf')):
            with self.subTest(source=source):
                self.assertEqual(slim_policy.category(source, news.CATEGORIES)['key'], key)

    def test_numeric_date_and_uncertainty_safety_guards_unchanged(self):
        with self.assertRaises(ValueError):
            quality.checked_translation(QUBIC.replace('$1.4M', '$2.4M'), '駭客攻擊140萬美元')
        with self.assertRaises(ValueError):
            quality.checked_translation(QBODY.replace('May 1', 'June 1'), '申請至2027年5月1日')
        with self.assertRaises(ValueError):
            auto.checked_copy(QUBIC+' This may change.', 'Qubic開放申請140萬美元')

    def test_whitespace_and_repeat_render_are_stable(self):
        result = auto.checked_copy(QUBIC.replace(' ', '  '), 'Qubic開放聲明140萬美元')
        self.assertEqual(auto.checked_copy(QUBIC, result), result)
        self.assertEqual(slim_policy.category((OCC+' '+OBODY).replace(' ', '  '), news.CATEGORIES)['key'], 'regulation')
