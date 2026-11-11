import copy
import json
import unittest
from datetime import datetime, timezone
from material_inbox import card, source_links
from material_quality import card_issues


class CompactMaterialCard(unittest.TestCase):
    now = datetime(2026, 11, 11, 6, tzinfo=timezone.utc)

    def row(self):
        return dict(title='Editor adds MCP support', title_zh='編輯器新增MCP支援',
                    summary='MCP connects files and tasks in a limited preview.',
                    summary_zh_points=['MCP在有限預覽中連接檔案與任務。'],
                    material_topic='ai', published=self.now, source='Cointelegraph',
                    url='https://cointelegraph.com/news/article')

    def test_compact_card_preserves_source_facts_stars_and_verification_without_advice(self):
        row = self.row(); before = copy.deepcopy(row)
        rendered = card(row, self.now); text = json.dumps(rendered, ensure_ascii=False)
        self.assertEqual(row, before)
        self.assertIn('MCP在有限預覽中連接檔案與任務。', text)
        self.assertIn('製作優先度', text)
        self.assertIn('非查證評等', text)
        self.assertIn('尚未以直接官方資料完成獨立核實', text)
        self.assertIn('2026/11/11 14:00', text)
        self.assertEqual(card_issues(row, rendered), [])
        for unwanted in ('為什麼值得做', '本則初評理由', '初步內容構思', '切入問題', '內容骨架', '建議形式', '原文標題：'):
            self.assertNotIn(unwanted, text)

    def test_same_publisher_is_one_label_but_each_distinct_report_remains_linked(self):
        row = self.row()
        row['related_sources'] = [dict(source='Cointelegraph', url='https://cointelegraph.com/news/follow-up')]
        links = source_links(row)
        self.assertEqual(links.count('Cointelegraph'), 1)
        self.assertIn('[主文]('+row['url']+')', links)
        self.assertIn('[相關報導 1](https://cointelegraph.com/news/follow-up)', links)

    def test_duplicate_and_tracking_only_links_do_not_consume_other_source_slots(self):
        row = self.row()
        row['related_sources'] = [dict(source='Cointelegraph', url=row['url']+'/?utm_source=rss#top'),
                                  dict(source='CoinDesk', url='https://www.coindesk.com/story'),
                                  dict(source='Official', url='https://example.com/notice')]
        links = source_links(row)
        self.assertEqual(links.count('Cointelegraph'), 1)
        self.assertNotIn('utm_source', links)
        self.assertIn('CoinDesk', links)
        self.assertIn('Official', links)

    def test_distinct_article_parameters_and_source_urls_are_not_overmerged(self):
        row = self.row(); row['url'] = 'https://example.com/article?id=1'
        row['related_sources'] = [dict(source='COINTELEGRAPH', url='https://example.com/article?id=2')]
        links = source_links(row)
        self.assertIn('?id=1', links); self.assertIn('?id=2', links)
        self.assertNotIn('COINTELEGRAPH', links)

    def test_compact_health_check_still_requires_source_content_and_verification(self):
        row = self.row(); rendered = card(row, self.now)
        rendered['fields'] = [f for f in rendered['fields'] if not f['name'].startswith('📌')]
        self.assertIn('source_content_missing', card_issues(row, rendered))
        rendered = card(row, self.now)
        rendered['fields'] = [f for f in rendered['fields'] if f['name'] != '🔎 查證狀態']
        self.assertIn('verification_status_missing', card_issues(row, rendered))

    def test_unverified_chinese_keeps_original_excerpt_and_pending_label(self):
        row = self.row(); row.pop('title_zh'); row.pop('summary_zh_points')
        rendered = card(row, self.now); text = json.dumps(rendered, ensure_ascii=False)
        self.assertIn('原文標題待中文核對', text)
        self.assertIn('中文未完整核對', text)
        self.assertIn(row['summary'], text)
        self.assertIn('translation_pending', card_issues(row, rendered))
