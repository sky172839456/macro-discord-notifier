import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from material_editorial import review
import material_inbox as inbox


class EditorialReviewTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 5, 2, tzinfo=timezone.utc)

    def row(self, **extra):
        return dict(title='Existing editor adds new MCP support',
                    summary='Its MCP server connects files and tasks in a limited preview, replacing manual workflow steps.',
                    material_topic='ai', published=self.now-timedelta(hours=1),
                    url='https://example.com/update', source='Example', official=False, **extra)

    def test_specific_useful_update_outscores_generic_announcement(self):
        detailed = review(self.row(), self.now)
        generic = review({**self.row(), 'title': 'Company update', 'summary': 'More details later.'}, self.now)
        self.assertEqual(detailed['stars'], 5)
        self.assertGreater(detailed['stars'], generic['stars'])
        for value in ('MCP support', '切入問題', '內容骨架', '表現方式'):
            self.assertIn(value, detailed['concept'])

    def test_official_flag_does_not_boost_editorial_stars(self):
        row = self.row()
        self.assertEqual(review(row, self.now), review({**row, 'official': True}, self.now))
        self.assertIn('高星不代表已完成查證', review(row, self.now)['basis'])

    def test_financial_percent_detail_is_recognized_without_inventing_change(self):
        row = {**self.row(), 'material_topic': 'policy',
               'title': 'New policy approves fee schedule',
               'summary': 'Users now pay 0.5%.'}
        result = review(row, self.now)
        self.assertIn('摘要有具體數字', result['reason'])
        self.assertEqual(row['summary'], 'Users now pay 0.5%.')
        self.assertNotIn('調降', result['concept'])

    def test_rich_interesting_story_can_get_five_without_finance_or_ai(self):
        row = {**self.row(), 'material_topic': 'interesting',
               'title': 'Museum unveils unexpected experiment',
               'summary': 'The unexpected experiment lasted 40 days and visitors can use its interactive exhibit.'}
        result = review(row, self.now)
        self.assertEqual(result['stars'], 5)
        self.assertIn('有趣之外', result['concept'])

    def test_missing_dates_and_content_remain_bounded_without_invented_facts(self):
        for published in (None, 'bad-date', self.now.replace(tzinfo=None), self.now+timedelta(hours=2)):
            row = {'material_topic': 'research', 'title': 'Update', 'published': published}
            result = review(row, self.now)
            self.assertIn(result['stars'], range(1, 6))
            self.assertEqual(len(result['display']), 5)
            self.assertNotIn('近六小時', result['reason'])

    def test_review_is_pure_and_reading_plan_does_not_change_source(self):
        row = self.row()
        before = copy.deepcopy(row)
        result = review(row, self.now)
        self.assertEqual(row, before)
        self.assertIn('依標題／摘要', result['basis'])
        self.assertNotIn('已實測成功', result['concept'])

    def test_all_categories_have_stars_plan_source_and_separate_verification(self):
        for topic in inbox.ANGLES:
            row = {**self.row(), 'material_topic': topic}
            result = inbox.card(row, self.now)
            text = json.dumps(result, ensure_ascii=False)
            for value in ('製作優先度', '來源內容', '查證狀態', '非查證評等',
                          'https://example.com/update', '媒體報導候選'):
                self.assertIn(value, text)
            self.assertLess(sum(len(f['name'])+len(f['value']) for f in result['fields'])+len(result['description']), 5500)

