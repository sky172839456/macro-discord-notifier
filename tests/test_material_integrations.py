import json
import unittest
from datetime import datetime, timezone

import material_inbox as inbox


class IntegrationMaterialTests(unittest.TestCase):
    # Synthetic examples verify selection; none assert a real product release.
    def test_existing_product_mcp_updates_are_selected(self):
        for title in ('A charting platform now supports MCP',
                      'Existing product releases an MCP server',
                      'Design software adds Model Context Protocol',
                      'A notes app connects to an MCP client'):
            with self.subTest(title=title):
                self.assertEqual(inbox.topic({'title': title}), 'ai')

    def test_other_integrations_do_not_require_ai_or_a_new_product(self):
        for title in ('An existing editor adds new connectors',
                      'A notes app enables automated workflows',
                      'A charting platform now connects to spreadsheet software',
                      'A browser adds extensions for local automation'):
            with self.subTest(title=title):
                self.assertEqual(inbox.topic({'title': title}), 'innovation')

    def test_mcp_keyword_without_development_and_ads_not_selected(self):
        for title in ('MCP is a hot topic', 'MCP server explained',
                      'MCP shares rise after product launch',
                      'Sponsored: Platform adds MCP support',
                      'Weekly recap: Editor adds connectors'):
            with self.subTest(title=title):
                self.assertIsNone(inbox.topic({'title': title}))

    def test_security_and_policy_still_keep_priority(self):
        self.assertEqual(inbox.topic({'title': 'MCP server hacked; platform pauses connections'}), 'security')
        self.assertEqual(inbox.topic({'title': 'New regulation limits platform MCP integration',
                                     'category': {'key': 'regulation'}}), 'policy')

    def test_card_explains_update_angle_without_claiming_verified_access(self):
        now = datetime(2026, 11, 5, 2, tzinfo=timezone.utc)
        row = dict(title='An existing editor adds new connectors',
                   summary='The publisher announces a limited preview.',
                   material_topic='innovation', source='Example', official=False,
                   url='https://example.com/story', published=now)
        text = json.dumps(inbox.card(row, now), ensure_ascii=False)
        for value in ('limited preview', '媒體報導候選', '製作優先度', '來源與時間'):
            self.assertIn(value, text)

