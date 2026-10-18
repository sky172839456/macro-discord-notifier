import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import crypto_news_notifier as news
import news_auto_recovery as auto
import news_editorial as editorial
import notification_quality as quality
import slim_policy


CYSIC = 'Cysic crypto bridge halted after unauthorized mint of 10M CYS'
CYSIC_BODY = 'Cysic said the incident was limited to bridge message processing and minting and did not affect the mainnet or other operational systems.'
SOLANA = 'Solana shows resilience, but some areas need continued observation, Fidelity says'
SOLANA_BODY = 'Solana has had no reported mainnet outages in two years, but concentrations in stake, hosting and client software should be monitored, according to a report.'
CIRCLE = 'Circle defends USDC economics as stablecoin rivals court its partners with bigger cut'
CIRCLE_BODY = 'Coinbase, Circle’s largest USDC partner, also backs Open USD, a rival network that passes reserve income to partners after a management fee.'
REGIONS = 'Demand is rising in Southeast Asia, Latin America, Africa and the Middle East.'


class NewsSmallFixTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1'})
        env.start()
        self.addCleanup(env.stop)

    def row(self, title, summary='', **values):
        return dict(title=title, summary=summary, published=datetime(2026, 10, 18, 12, tzinfo=timezone.utc), **values)

    def test_three_delivered_articles_follow_topic(self):
        for title, body, expected in ((CYSIC, CYSIC_BODY, 'security'),
                                      (SOLANA, SOLANA_BODY, 'network'),
                                      (CIRCLE, CIRCLE_BODY, 'stablecoin')):
            with self.subTest(title=title):
                from xml.sax.saxutils import escape
                xml = f'<rss><channel><item><title>{escape(title)}</title><description>{escape(body)}</description><link>https://example.invalid/news</link><pubDate>Sun, 18 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'
                rows = news.parse_feed(xml, {'name': '媒體', 'official': False})
                self.assertEqual(rows[0]['category']['key'], expected)

    def test_actual_legal_events_keep_regulation(self):
        for title in ('Court orders Circle to freeze USDC',
                      'Circle courts partners after federal court ruling',
                      'Circle courts partners as court rejects USDC lawsuit',
                      'SEC approves Fidelity spot Solana ETF'):
            with self.subTest(title=title):
                self.assertEqual(news.category_for(title)['key'], 'regulation')

    def test_real_etf_topic_not_hidden_by_network_terms(self):
        self.assertEqual(news.category_for('Fidelity Solana ETF report discusses mainnet outages')['key'], 'etf')

    def test_new_unauthorized_mint_is_security(self):
        row = self.row(CYSIC, CYSIC_BODY)
        self.assertTrue(editorial.safety_candidate(row))
        self.assertTrue(auto.material_news(row))

    def test_historical_or_legitimate_mint_is_not_new_security(self):
        for title in ('Cysic crypto bridge halted after authorized mint of 10M CYS',
                      'Annual crypto review: unauthorized mint losses last year',
                      'Printer mint halted after unauthorized issuance'):
            with self.subTest(title=title):
                self.assertFalse(editorial.safety_candidate(self.row(title)))

    def test_revenue_share_and_business_model_copy(self):
        result = auto.checked_copy(CIRCLE, 'Circle 為 USDC 經濟學進行辯護，因為穩定幣的競爭對手以更大的削減來吸引其合作夥伴')
        self.assertIn('更高的收益分成', result)
        self.assertIn('USDC 商業模式', result)
        self.assertNotIn('削減', result)

    def test_stake_and_hosting_are_network_terms(self):
        result = auto.checked_copy(SOLANA_BODY, '根據一份報告，Solana 在兩年內沒有主網中斷的報告，但應該監控股權、託管和客戶端軟體的集中度。')
        self.assertIn('質押、主機服務', result)
        self.assertNotIn('股權', result)

    def test_financial_stake_and_real_custody_unchanged(self):
        self.assertEqual(auto.checked_copy('Fidelity buys an equity stake in a custody company', 'Fidelity 購買託管公司的股權'), 'Fidelity 購買託管公司的股權')

    def test_mixed_meanings_do_not_blindly_replace(self):
        for source, translated in (('Solana stake and equity ownership stake', 'Solana 股權及股權持有'),
                                   ('Solana hosting and custody providers', 'Solana 託管及託管提供商')):
            with self.subTest(source=source), self.assertRaises(ValueError):
                auto.checked_copy(source, translated)

    def test_rate_cuts_unchanged(self):
        self.assertEqual(auto.checked_copy('A bigger cut in interest rates', '利率更大的削減'), '利率更大的削減')

    def test_strategy_company_and_eyes_asia(self):
        self.assertIn('巨頭 Strategy', auto.checked_copy('Bitcoin treasury giant Strategy faces index removal', 'Bitcoin 資產儲備巨頭策略面臨指數移除'))
        self.assertEqual(auto.checked_copy('Deutsche Bank eyes Asia crypto custody market', '德意志銀行 EYES Asia 加密託管市場'), '德意志銀行 瞄準亞洲 加密託管市場')

    def test_generic_strategy_is_not_a_company(self):
        self.assertEqual(auto.checked_copy('A Bitcoin investment strategy', 'Bitcoin 投資策略'), 'Bitcoin 投資策略')

    def test_missing_company_subject_is_rejected(self):
        with self.assertRaises(ValueError):
            quality.checked_translation('Strategy adds 250 Bitcoin', 'Bitcoin 在 CPI 公布前持平')

    def test_token_scale_preserves_count_without_dollars(self):
        result = auto.checked_copy(CYSIC, 'Cysic 加密橋在未經授權鑄造 10M CYS 後停止')
        self.assertIn('1000萬枚 CYS', result)
        self.assertNotIn('美元', result)
        self.assertEqual(quality.numeric_values(result), quality.numeric_values(CYSIC))

    def test_qualification_and_numeric_guards_still_apply(self):
        for source, translated in (('Cysic may halt after unauthorized mint of 10M CYS', 'Cysic 未經授權鑄造 10M CYS 後停止'),
                                   (CYSIC, 'Cysic 未經授權鑄造 20M CYS 後停止')):
            with self.subTest(source=source), self.assertRaises(ValueError):
                auto.checked_copy(source, translated)

    def test_token_count_must_not_become_dollar_loss(self):
        for translated in ('Cysic 未授權鑄造1000萬美元後停止',
                           'Cysic 未授權鑄造1000萬美元 CYS 後停止'):
            with self.subTest(translated=translated), self.assertRaises(ValueError):
                auto.checked_copy(CYSIC, translated)

    def test_operational_systems_not_operating_system(self):
        self.assertIn('營運系統', auto.checked_copy(CYSIC_BODY, 'Cysic 表示事件不影響主網或其他操作系統。'))
        self.assertEqual(auto.checked_copy('The Linux operating system', 'Linux 操作系統'), 'Linux 操作系統')

    def test_existing_cached_copy_is_repaired_at_render(self):
        row = self.row(CIRCLE, CIRCLE_BODY, title_zh='Circle 為 USDC 經濟學進行辯護，穩定幣競爭對手以更大的削減吸引合作夥伴',
                       summary_zh_points=['Circle 最大的 USDC 合作夥伴 Coinbase 支持 Open USD，該網路扣管理費後將儲備收入分給合作夥伴。'])
        self.assertIn('收益分成', quality.headline(row))
        self.assertIn('收益分成', slim_policy.news_card({**row, 'source': '媒體', 'official': False, 'url': 'https://example.invalid', 'category': news.CATEGORIES[3]})['title'])

    def expansion(self, title, regions=REGIONS):
        return self.row(title, 'Circle plans to enter 40 emerging and developing markets. ' + regions)

    def test_same_circle_plan_across_sources_merges(self):
        a = self.expansion('Circle’s Allaire says stablecoin issuer looking to enter 40 developing markets: report')
        b = self.expansion('Circle plans push into 40 emerging markets as stablecoins go mainstream, CEO says')
        self.assertTrue(editorial.equivalent(a, b))

    def test_circle_dedup_preserves_both_source_links_and_ids(self):
        a = self.expansion('Circle’s Allaire says stablecoin issuer looking to enter 40 developing markets: report')
        b = self.expansion('Circle plans push into 40 emerging markets as stablecoins go mainstream, CEO says')
        a.update(id='circle-a', url='https://example.invalid/first', source='媒體A', official=False)
        b.update(id='circle-b', url='https://example.invalid/second', source='媒體B', official=False)
        rows = news.deduplicate([a, b])
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(editorial.member_ids(rows[0])), {'circle-a', 'circle-b'})
        self.assertEqual({rows[0]['url'], *[r['url'] for r in rows[0]['related_sources']]}, {a['url'], b['url']})

    def test_different_circle_plan_scope_or_progress_is_preserved(self):
        a = self.expansion('Circle looking to enter 40 developing markets')
        cases = [self.expansion('Circle plans push into 60 emerging markets'),
                 self.expansion('Circle plans push into 40 emerging markets', 'Demand is rising in Japan.'),
                 self.expansion('Circle launches in 40 emerging markets'),
                 self.expansion('Circle plans push into 40 emerging markets after license approval was secured'),
                 self.expansion('Circle plans push into 40 emerging markets', REGIONS + ' Additional US retail clients are included.'),
                 self.row(CIRCLE, CIRCLE_BODY)]
        for b in cases:
            with self.subTest(title=b['title'], summary=b['summary']):
                self.assertFalse(editorial.equivalent(a, b))


if __name__ == '__main__':
    unittest.main()
