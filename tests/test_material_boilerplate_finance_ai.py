"""Material cards: exchange boilerplate is not content; an AI company name is not an AI release."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import material_inbox as material
from material_source_copy import excerpt_parts

LEAD = ('This is a general announcement. '
        'Products and services referred to here may not be available in your region. ')
EVENT = ('Fellow Binancians, Binance will launch US stock options on Anthropic (NASDAQ: ANT) '
         'at 2026-11-23 14:30 (UTC), when the US market opens for regular trading.')
ELIGIBLE = 'Eligible users will be able to trade ANT options on Binance Stock Options.'
DETAILS = ('Key Details: Trading hours 09:30 - 16:00 ET, Monday to Friday, excluding US market holidays. '
           'Settlement is physical delivery of the underlying shares.')
FOOTER = (' There may be discrepancies between this original content in English and any translated versions. '
          'Thank you for your support! Binance Team 2026-11-23 '
          'Disclaimer: Stock Options are contracts that give you the right, but not the obligation, to buy or sell. '
          'You may lose the entire Premium paid. Binance may receive payment for order flow.')
BODY = LEAD + EVENT + ' ' + ELIGIBLE + ' ' + DETAILS + FOOTER
TITLE = 'Binance Will Launch Stock Options on Anthropic (ANT)'


def row(**kw):
    value = {'title': TITLE, 'summary': BODY, 'source': 'Binance Listings', 'official': True,
             'url': 'https://www.binance.com/en/support/announcement/b3eb06ad744b4398911a103d94d288c6',
             'published': datetime(2026, 11, 23, 14, 17, tzinfo=timezone.utc)}
    value.update(kw)
    return value


class BoilerplateSelectionTests(unittest.TestCase):
    def test_strict_selection_skips_lead_boilerplate_and_keeps_eligibility_with_claim(self):
        with patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '1'}):
            parts = excerpt_parts(row())
        self.assertEqual(parts, [EVENT+' '+ELIGIBLE, DETAILS.split(' Settlement')[0]])
        for part in parts:
            self.assertNotIn('general announcement', part)
            self.assertNotIn('may not be available in your region', part)

    def test_non_strict_selection_also_skips_lead_boilerplate(self):
        with patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '0'}):
            self.assertEqual(excerpt_parts(row()), [EVENT, ELIGIBLE])

    def test_boilerplate_or_disclaimer_only_body_yields_no_excerpt(self):
        only = LEAD + 'Thank you for your support! Binance Team 2026-11-23 Disclaimer: You may lose the entire Premium paid. Past performance is not a reliable predictor.'
        with patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '1'}):
            self.assertEqual(excerpt_parts(row(summary=only)), [])
            self.assertEqual(excerpt_parts(row(summary=LEAD.strip())), [])

    def test_content_without_boilerplate_is_selected_unchanged(self):
        text = EVENT + ' ' + DETAILS
        with patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '1'}):
            self.assertEqual(excerpt_parts(row(summary=text)), [EVENT, DETAILS.split(' Settlement')[0]])
            release = {'source': 'Claude Code Releases', 'summary_parts': ['Added auto mode.', 'Fixed a crash.', 'Changed docs.']}
            self.assertEqual(excerpt_parts(release), ['Added auto mode.', 'Fixed a crash.'])

    def test_boilerplate_words_inside_a_real_sentence_are_not_dropped(self):
        text = LEAD + 'This is a general announcement of new trading hours for ANT options starting 2026-11-24.'
        with patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '1'}):
            self.assertEqual(excerpt_parts(row(summary=text)),
                             ['This is a general announcement of new trading hours for ANT options starting 2026-11-24.'])

    def test_card_shows_event_not_disclaimer_and_finance_label(self):
        now = datetime(2026, 11, 23, 14, 20, tzinfo=timezone.utc)
        item = row(material_topic=material.topic(row()))
        with patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '1'}):
            rendered = material.card(item, now)
        facts = next(f['value'] for f in rendered['fields'] if f['name'].startswith('📌 來源內容'))
        self.assertIn('will launch US stock options on Anthropic', facts)
        self.assertNotIn('general announcement', facts)
        self.assertNotIn('may not be available in your region', facts)
        self.assertIn('分類：企業／交易所進展', rendered['description'])
        self.assertNotIn('AI／新工具', rendered['description'])


class FinanceAiClassificationTests(unittest.TestCase):
    def test_options_and_tokenized_shares_named_after_ai_company_are_not_ai(self):
        for title, source in ((TITLE, 'Binance Listings'),
                              ('Anthropic xStock (ANTx) Now Available for Spot Trading', 'Binance Listings'),
                              ('Trade Anthropic bStocks and Share Rewards', 'Binance Activities'),
                              ('Bitget Will List OpenAI Tokenized Shares (OPENAIx)', 'Bitget News'),
                              ('Anthropic Stock Options Now Live', 'Example News')):
            with self.subTest(title=title):
                self.assertEqual(material.topic({'title': title, 'summary': '', 'source': source, 'official': True}), 'business')

    def test_real_ai_items_stay_ai(self):
        for item in ({'title': 'Anthropic releases Claude Opus 5 for long-running agents', 'source': 'Example News'},
                     {'title': 'OpenAI shares new research on model safety evaluations', 'source': 'Example News'},
                     {'title': 'Binance launches AI assistant that summarizes announcements', 'source': 'Binance News'},
                     {'title': 'Claude Code v2.1.331', 'source': 'Claude Code Releases', 'material_ai': True},
                     {'title': 'Anthropic stock options explainer for the new Claude API', 'source': 'Claude Platform Updates', 'material_ai': True}):
            with self.subTest(title=item['title']):
                self.assertEqual(material.topic(dict(item, summary='')), 'ai')

    def test_unsent_queued_card_is_recomputed_and_delivered_card_is_not_reopened(self):
        now = datetime(2026, 11, 23, 14, 30, tzinfo=timezone.utc)
        old_zh = ['這是公告事項。', '此處提及的產品與服務可能未於您所在地區提供。']
        queued = row(status='queued', material_topic='ai', material_key='queued-key', material_copy_version=4,
                     title_zh='幣安將推出 Anthropic（ANT）股票選擇權', summary_zh_points=old_zh,
                     published=(now-timedelta(minutes=13)).isoformat(), collected_at=(now-timedelta(minutes=10)).isoformat())
        delivered = dict(queued, url='https://www.binance.com/en/support/announcement/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                         status='notified', material_key='delivered-key', message_id='1574429288533590069')
        state = {'material_inbox_v1': {'started_at': (now-timedelta(hours=2)).isoformat(), 'items': [queued, delivered]}}
        translations = {}
        def translate(value):
            translations[value] = True
            return queued['title_zh'] if value == TITLE else '（譯文）' + value
        with patch.dict(os.environ, {'MATERIAL_INBOX_ENABLED': '1', 'DISCORD_MATERIAL_WEBHOOK_URL': 'test', 'CONTENT_PREFLIGHT_STRICT': '0'}), \
             patch('material_quality.selection', return_value=None), \
             patch('news_auto_recovery.checked_copy', side_effect=lambda source, zh: zh):
            send = Mock(return_value='999')
            material.run([], state, now, fetch=Mock(side_effect=OSError()), send=send, persist=Mock(), verify=Mock(), enrich=translate)
        self.assertEqual(send.call_count, 1)
        sent = send.call_args[0][1]
        facts = next(f['value'] for f in sent['fields'] if f['name'].startswith('📌 來源內容'))
        self.assertIn(EVENT, facts)
        self.assertNotIn('這是公告事項', facts)
        self.assertNotIn('general announcement', ' '.join(translations))
        self.assertEqual(queued['material_topic'], 'business')
        self.assertEqual(delivered['summary_zh_points'], old_zh)
        self.assertEqual(delivered['status'], 'notified')
        self.assertEqual(delivered['message_id'], '1574429288533590069')


if __name__ == '__main__':
    unittest.main()
