import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import crypto_news_notifier as news
import news_editorial as editorial


CT = "FINMA approves Switzerland’s first Bitcoin ETF for retail investors"
DECRYPT = "Swiss Regulator Approves First Retail Fund That Holds Bitcoin Directly"
CT_SUMMARY = ("The Swiss regulator cited a growing appetite for cryptocurrency investments "
              "and said that multiple fund providers have submitted Bitcoin ETF applications.")
DECRYPT_SUMMARY = ("FINMA waived the diversification rules for the fund but leaned hard on "
                   "custody and investor-protection safeguards.")


class SwissFirstRetailApprovalTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, SLIM_NOTIFICATIONS='1', NEWS_AUTO_RECOVERY='1')
        self.env.start()
        self.addCleanup(self.env.stop)

    def row(self, title, summary, source='CT', hours=0):
        return dict(id=source, title=title, summary=summary, source=source, official=False,
                    url='https://example.invalid/'+source,
                    published=datetime(2026, 10, 20, 13, 4, tzinfo=timezone.utc)+timedelta(hours=hours))

    def pair(self):
        return (self.row(CT, CT_SUMMARY),
                self.row(DECRYPT, DECRYPT_SUMMARY, 'Decrypt', 6.45))

    def test_public_reports_are_same_event_both_directions(self):
        a, b = self.pair()
        self.assertTrue(news.same_news_event(a, b))
        self.assertTrue(news.same_news_event(b, a))

    def test_same_batch_preserves_both_source_links_and_ids(self):
        a, b = self.pair()
        kept = news.deduplicate([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(set(editorial.member_ids(kept[0])), {a['id'], b['id']})
        self.assertEqual({kept[0]['url'], *[r['url'] for r in kept[0]['related_sources']]},
                         {a['url'], b['url']})

    def test_preexisting_sent_history_is_recomputed_without_migration(self):
        from news_streams import restore
        a, b = self.pair()
        saved = editorial.history_row(a, b['published'])
        self.assertIsInstance(saved['published'], str)
        self.assertTrue(news.same_news_event(b, restore(saved)))
        self.assertEqual(saved['title'], a['title'])

    def test_different_titles_are_not_entity_only_duplicates(self):
        a, _ = self.pair()
        titles = [
            DECRYPT.replace('Bitcoin', 'Ether'),
            DECRYPT.replace('Swiss', 'German'),
            DECRYPT.replace('First', 'Second'),
            DECRYPT.replace('Retail', 'Institutional'),
            DECRYPT.replace('Approves', 'Rejects'),
            'FINMA approves another retail Bitcoin ETF',
            'First Swiss retail Bitcoin ETF begins trading',
            'BlackRock first retail Bitcoin ETF approved by FINMA',
            'FINMA approves BlackRock Bitcoin ETF for retail investors',
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(news.same_news_event(a, self.row(title, DECRYPT_SUMMARY, 'other', 7)))

    def test_new_summary_milestones_and_conditions_are_preserved(self):
        a, b = self.pair()
        updates = [
            'The fund begins trading today.', 'The launch date is January 2027.',
            'FINMA added new custody safeguards.', 'Approval is conditional on a custody change.',
            'The decision is subject to further review.', 'The issuer is BlackRock.',
            'The fund is issued by blackrock.', 'BlackRock manages the fund.',
            'New applications include additional assets.', 'FINMA revised the diversification exemption.',
            'FINMA revoked the exemption.', 'FINMA imposed tighter restrictions.',
        ]
        for summary in updates:
            with self.subTest(summary=summary):
                self.assertFalse(news.same_news_event(a, {**b, 'summary': summary}))

    def test_existing_number_and_date_guards_remain(self):
        a, b = self.pair()
        for extra in (' Fees are 0.5%.', ' The decision applies from January 2027.'):
            with self.subTest(extra=extra):
                self.assertFalse(news.same_news_event(a, {**b, 'summary': b['summary']+extra}))

    def test_more_than_24_hours_remains_a_separate_event(self):
        a, b = self.pair()
        self.assertFalse(news.same_news_event(a, {**b, 'published': a['published']+timedelta(hours=25)}))

    def test_first_approval_wording_without_switzerland_does_not_match(self):
        self.assertIsNone(editorial.event_key(self.row(
            'Regulator approves first Bitcoin ETF for retail investors', CT_SUMMARY)))
