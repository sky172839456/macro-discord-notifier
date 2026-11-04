import json
import unittest
from datetime import datetime, timezone

import material_inbox as inbox


class BroadMaterialTopics(unittest.TestCase):
    def test_technology_does_not_require_finance_or_a_specific_person(self):
        for title in (
            'Company unveils a flying car prototype',
            'A new battery can recharge in ten minutes',
            'Startup demonstrates a wearable for silent communication',
            'Engineers test a new system for cleaning ocean waste',
            'An open-source app launches a local file search tool',
            'Researchers unveil a telescope',  # General research keeps its own category.
        ):
            with self.subTest(title=title):
                expected = 'research' if title.startswith('Researchers') else 'innovation'
                self.assertEqual(inbox.topic({'title': title}), expected)

    def test_all_existing_topics_still_work(self):
        samples = {
            'security': 'Binance confirms hack and pauses withdrawals',
            'policy': 'New regulation sets rules for exchanges',
            'ai': 'An AI tool generates animated diagrams',
            'business': 'Binance partners with Mastercard for payments',
            'research': 'Researchers study quantum cryptography methods',
            'interesting': 'Solo miner wins Bitcoin block reward',
        }
        for expected, title in samples.items():
            with self.subTest(topic=expected):
                self.assertEqual(inbox.topic({'title': title}), expected)
        self.assertEqual(inbox.ANGLES['ai'][0], 'AI／新工具')
        self.assertEqual(inbox.ANGLES['innovation'][0], '科技／新發明')

    def test_nonfinancial_fun_stories_have_concrete_hooks(self):
        for title in ('A museum opens an unusual experiment',
                      'An artist sets a world record',
                      'A video game reveals a surprising discovery',
                      'A robot learns to cook'):
            self.assertEqual(inbox.topic({'title': title}), 'interesting')

    def test_company_name_and_hype_do_not_imply_invention(self):
        for title in ('Tesla shares rise after a robot demonstration',
                      'Tesla stock price surges',
                      'A robot is trending online',
                      'Sponsored: Startup unveils flying car',
                      'Giveaway: New device launches today',
                      'Weekly recap: Company unveils new system'):
            with self.subTest(title=title):
                self.assertIsNone(inbox.topic({'title': title}))

    def test_prototype_card_preserves_claim_and_requests_stage_check(self):
        row = dict(title='Company unveils a flying car prototype',
                   summary='The company says it is testing a prototype.',
                   material_topic='innovation', official=False,
                   url='https://www.theverge.com/transport/story', source='The Verge',
                   published=datetime(2026, 11, 4, 8, tzinfo=timezone.utc))
        result = inbox.card(row, row['published'])
        text = json.dumps(result, ensure_ascii=False)
        for value in ('科技／新發明', '構想／展示／原型／測試／開賣',
                      'prototype', '媒體報導候選', '獨立實測'):
            self.assertIn(value, text)
        self.assertFalse(inbox.urgent(row))

