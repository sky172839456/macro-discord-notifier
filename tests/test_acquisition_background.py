import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from xml.sax.saxutils import escape

import crypto_news_notifier as news
import news_auto_recovery as auto
import news_editorial as editorial

TITLE = 'Bitget plans Thai crypto exchange acquisition weeks after $388M hack'
BODY = ('The proposed acquisition would give Bitget a route into Thailand’s crypto market '
        'through a locally licensed operator.')


class AcquisitionBackgroundTests(unittest.TestCase):
    def setUp(self):
        context = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1'})
        context.start()
        self.addCleanup(context.stop)

    def row(self, title=TITLE, summary=BODY):
        return {'title': title, 'summary': summary}

    def test_actual_rss_background_is_not_safety(self):
        self.assertFalse(editorial.safety_candidate(self.row()))
        self.assertEqual(editorial.event_kind(self.row()), 'ordinary')
        self.assertFalse(auto.material_news(self.row()))

    def test_actual_feed_routes_to_exchange_normal(self):
        xml = (f'<rss><channel><item><title>{escape(TITLE)}</title>'
               f'<description>{escape(BODY)}</description><link>https://example.invalid/deal</link>'
               '<pubDate>Tue, 20 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>')
        rows = news.parse_feed(xml, {'name': 'Cointelegraph', 'official': False})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['category']['key'], 'exchange')
        self.assertEqual(rows[0]['category']['priority'], 'normal')
        self.assertFalse(auto.material_news(rows[0]))

    def test_proposed_deal_still_obeys_existing_importance_gate(self):
        row = {**self.row(), 'published': datetime(2026, 10, 20, 10, tzinfo=timezone.utc)}
        self.assertEqual(auto.selection_reason(row, datetime(2026, 10, 20, 10, 10, tzinfo=timezone.utc)), '缺少重要事件進展')

    def test_age_variants_are_background(self):
        for tail in ('two weeks after a $388 million hack', 'months following the $388M breach',
                     'several years after a crypto exploit'):
            with self.subTest(tail=tail):
                row = self.row('Bitget plans Thai crypto exchange acquisition ' + tail)
                self.assertFalse(auto.material_news(row))
                self.assertEqual(news.category_for(editorial.text(row))['key'], 'exchange')

    def test_new_incident_in_title_is_not_suppressed(self):
        row = self.row(TITLE + '; new exploit drains crypto wallets today')
        self.assertTrue(editorial.safety_candidate(row))
        self.assertTrue(auto.material_news(row))
        self.assertEqual(news.category_for(editorial.text(row))['key'], 'security')

    def test_new_incident_in_summary_is_not_suppressed(self):
        row = self.row(summary=BODY + ' A new exploit drains wallets today.')
        self.assertTrue(editorial.safety_candidate(row))
        self.assertTrue(auto.material_news(row))
        self.assertEqual(news.category_for(editorial.text(row))['key'], 'security')

    def test_service_actions_keep_safety(self):
        for action in ('halts withdrawals', 'suspends withdrawals', 'resumes withdrawals'):
            with self.subTest(action=action):
                self.assertTrue(auto.material_news(self.row(TITLE + ' and ' + action)))

    def test_active_hack_without_old_context_keeps_safety(self):
        row = self.row('Bitget acquisition platform confirms new $388M hack today')
        self.assertTrue(editorial.safety_candidate(row))
        self.assertTrue(auto.material_news(row))

    def test_timing_alone_does_not_mute_incidents(self):
        for title in ('Crypto exchange suffers $388M hack weeks after acquisition',
                      'Crypto exchange confirms $388M hack after acquisition',
                      'Crypto exchange halts withdrawals weeks after $388M hack'):
            with self.subTest(title=title):
                self.assertTrue(editorial.safety_candidate(self.row(title)))
                self.assertTrue(auto.material_news(self.row(title)))

    def test_new_approval_still_uses_decision_urgency(self):
        row = self.row('Regulator approves Bitget crypto exchange acquisition weeks after $388M hack')
        self.assertFalse(editorial.safety_candidate(row))
        self.assertEqual(editorial.event_kind(row), 'decision')
        self.assertTrue(auto.material_news(row))
        self.assertEqual(news.category_for(editorial.text(row))['key'], 'exchange')

    def test_loss_revisions_keep_existing_safety_checks(self):
        for summary in ('Losses rise to $400M today.',
                        'Losses revised to $400 million.',
                        'The loss estimate increased to $400M.',
                        'The exchange lost another $12M.',
                        'Updated damage estimates reach $400M.'):
            with self.subTest(summary=summary):
                row = self.row(summary=BODY + ' ' + summary)
                self.assertTrue(editorial.safety_candidate(row))
                self.assertTrue(auto.material_news(row))
                self.assertEqual(news.category_for(editorial.text(row))['key'], 'security')

    def test_new_victims_or_affected_accounts_keep_safety(self):
        for summary in ('Additional victims submitted claims.',
                        'More users report missing assets.',
                        '500 customer accounts are affected.',
                        'The number of impacted wallets increased.',
                        'Additional customers submitted reports.'):
            with self.subTest(summary=summary):
                self.assertTrue(auto.material_news(self.row(summary=summary)))

    def test_recovery_and_compensation_are_not_muted(self):
        for summary in ('Investigators recovered $12M.',
                        'The exchange is recovering funds.',
                        'Users were compensated.',
                        'Victims will be reimbursed.',
                        'Refunds are being processed.',
                        'Funds were returned today.',
                        'Authorities returned the funds.',
                        'Restitution proceedings begin.',
                        'Authorities repatriated the assets.'):
            with self.subTest(summary=summary):
                self.assertTrue(auto.material_news(self.row(summary=summary)))

    def test_passive_returns_and_frozen_or_seized_assets_keep_safety(self):
        for summary in ('Funds have been returned to users.',
                        'Assets have now been returned.',
                        'Funds are being returned.',
                        'Authorities froze $10M in assets.',
                        'The remaining assets are frozen.',
                        'Investigators seized the funds.',
                        'Investigators are seizing assets.',
                        'The exchange is unfreezing funds.'):
            with self.subTest(summary=summary):
                row = self.row(summary=summary)
                self.assertTrue(editorial.safety_candidate(row))
                self.assertTrue(auto.material_news(row))
                self.assertEqual(news.category_for(editorial.text(row))['key'], 'security')

    def test_current_security_developments_keep_safety(self):
        for summary in ('A new vulnerability was disclosed.',
                        'An ongoing attack is under investigation.',
                        'An active attack continues.',
                        'A new incident was reported.'):
            with self.subTest(summary=summary):
                self.assertTrue(auto.material_news(self.row(summary=summary)))

    def test_uncertain_new_harm_still_enters_safety_checks(self):
        row = self.row(summary='There may be additional victims; losses are unconfirmed.')
        self.assertTrue(editorial.safety_candidate(row))
        self.assertTrue(auto.material_news(row))

    def test_loss_update_feed_keeps_security_critical_routing(self):
        summary = BODY + ' Losses rise to $400M today.'
        xml = (f'<rss><channel><item><title>{escape(TITLE)}</title>'
               f'<description>{escape(summary)}</description><link>https://example.invalid/update</link>'
               '<pubDate>Tue, 20 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>')
        rows = news.parse_feed(xml, {'name': 'Cointelegraph', 'official': False})
        self.assertEqual(rows[0]['category']['key'], 'security')
        self.assertEqual(rows[0]['category']['priority'], 'critical')
        self.assertTrue(auto.material_news(rows[0]))

    def test_numeric_and_uncertainty_guards_are_not_relaxed(self):
        with self.assertRaises(ValueError):
            auto.checked_copy('Losses rise to $400M today.', '今天損失上升至5億美元。')
        with self.assertRaises(ValueError):
            auto.checked_copy('There may be additional victims.', '有新增受害者。')

    def test_old_article_still_excluded(self):
        row = {**self.row(), 'published': datetime(2026, 10, 18, 10, tzinfo=timezone.utc)}
        self.assertEqual(auto.selection_reason(row, datetime(2026, 10, 20, 10, tzinfo=timezone.utc)), '舊文')

    def test_copy_still_preserves_plan_amount_and_weeks(self):
        result = auto.checked_copy(TITLE, 'Bitget 計劃在3.88億美元黑客入侵數週後收購泰國加密資產交易所')
        self.assertIn('計劃', result)
        self.assertIn('3.88億', result)
        self.assertIn('數週', result)


if __name__ == '__main__':
    unittest.main()