import hashlib
import os
import re
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
import news_auto_recovery as auto
import news_editorial as editorial
import news_copy_terms as terms
import notification_quality as quality
import crypto_news_notifier as news
import slim_policy

META='Meta outlook revised downward by S&P on cash flow and capex concerns'
ETF='Bitcoin ETF Investors Head for the Exits After Record Binance Hack'
SYNTHETIC='Fictional ETF fund-flow follow-up after the previously reported incident.'


class VerifiedMetaETFTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'SLIM_NOTIFICATIONS':'1','NEWS_AUTO_RECOVERY':'1'})
        self.env.start();self.addCleanup(self.env.stop)
    def fixture_guard(self):
        value=re.sub(r'\s+',' ',ETF+' '+SYNTHETIC).strip().casefold()
        return patch.object(editorial,'VERIFIED_ETF_FLOW_FINGERPRINT',hashlib.sha256(value.encode()).hexdigest())
    def test_meta_company_name_and_direction(self):
        repaired=auto.checked_copy(META,'標準普爾將現金流量和資本支出問題的元前景修訂為負面')
        self.assertIn('Meta',repaired);self.assertIn('下調',repaired)
        self.assertNotIn('元前景',repaired);self.assertNotIn('評等降級',repaired)
    def test_etf_departure_is_clear(self):
        self.assertIn('撤資',auto.checked_copy(ETF,'Bitcoin ETF 投資者在創紀錄的 Binance 黑客攻擊後離開'))
    def test_changed_company_direction_or_qualification_not_overwritten(self):
        for source in (META.replace('downward','upward'),META.replace('revised downward','may be revised downward'),META.replace('Meta','Microsoft')):
            with self.subTest(source=source):
                self.assertEqual(terms.repair_translation(source,'保留原待核譯文'),'保留原待核譯文')
    def test_cached_bad_copy_is_rendered_without_mutation(self):
        row={'title':META,'title_zh':'元前景修訂為負面','summary':''};before=dict(row)
        self.assertIn('Meta',quality.headline(row));self.assertEqual(row,before)
    def test_exact_source_pair_routes_to_etf_without_breaking_alert(self):
        row={'title':ETF,'summary':SYNTHETIC}
        with self.fixture_guard():
            self.assertFalse(editorial.safety_candidate(row))
            self.assertFalse(auto.material_news(row))
            category=news.category_for(ETF+' '+SYNTHETIC)
        self.assertEqual(category['key'],'etf');self.assertEqual(category['priority'],'normal')
    def test_changed_summary_keeps_new_loss_victim_recovery_and_official_progress(self):
        for progress in ('Losses revised to $7 billion.','Additional victims report losses.',
                         'Authorities froze $3 billion in stolen funds.',
                         'Investigators recovered $12 million.','The FBI begins an investigation.',
                         'A new exploit drains wallets today.'):
            with self.subTest(progress=progress),self.fixture_guard():
                row={'title':ETF,'summary':SYNTHETIC+' '+progress}
                self.assertTrue(editorial.safety_candidate(row));self.assertTrue(auto.material_news(row))
    def test_full_feed_entry_uses_same_guard(self):
        xml=f'<rss><channel><item><title>{ETF}</title><description>{SYNTHETIC}</description><link>https://example.invalid/fixture</link><pubDate>Sun, 01 Nov 2026 16:01:02 +0000</pubDate></item></channel></rss>'
        with self.fixture_guard():
            rows=news.parse_feed(xml,{'name':'Fixture','official':False})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['category']['key'],'etf')
    def test_unsent_cached_ready_copy_is_reclassified_without_mutation(self):
        now=datetime(2026,11,1,16,1,tzinfo=timezone.utc)
        row={'id':'fictional-unsent','title':ETF,'summary':SYNTHETIC,
             'title_zh':'比特幣ETF投資人撤資','summary_zh_points':['ETF資金動向變化。'],
             'auto_copy_version':2,'source':'Fixture','published':now,
             'url':'https://example.invalid/fixture','official':False,
             'category':next(c for c in news.CATEGORIES if c['key']=='security')}
        with self.fixture_guard(),patch.object(auto,'enrich',side_effect=AssertionError('cached ready copy must not need a provider')):
            result=news.add_translated_title(row,{},now)
        self.assertEqual(result['category']['key'],'etf')
        self.assertEqual(row['category']['key'],'security')
        self.assertEqual(result['id'],row['id'])


if __name__=='__main__':
    unittest.main()
