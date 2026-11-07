import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import crypto_news_notifier as news
import news_auto_recovery as auto
import news_editorial as editorial
import notification_quality as quality
import slim_policy


class EntryAuditNewsTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1'})
        env.start(); self.addCleanup(env.stop)
        self.rows = json.loads((Path(__file__).parent/'fixtures/entry_audit_20261107.json').read_text(encoding='utf-8'))
        for r in self.rows:
            r['published'] = datetime.fromisoformat(r['published'])

    def find(self, part):
        return next(r for r in self.rows if part in r['title'])

    def test_same_tax_approval_retains_three_publishers_and_complementary_facts(self):
        rows = [r for r in self.rows if r['title'].startswith('Greece')]
        result = slim_policy.merge_pending(rows)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(len({row['source'], *[s['source'] for s in row['related_sources']]}), 3)
        self.assertEqual(len({row['id'], *row['merged_ids']}), 3)
        context = editorial.short_context(row)
        for fact in ('2027', '10%', '15%', '500', '557', '12個月', '仍有'):
            self.assertIn(fact, context[1])
        self.assertIn('依各媒體RSS', context[0])

    def test_tax_policy_not_market_structure_and_security_stays_first(self):
        for row in [r for r in self.rows if r['title'].startswith('Greece')]:
            self.assertEqual(news.category_for(editorial.text(row))['key'], 'regulation')
        self.assertEqual(news.category_for('Greece crypto tax site hacked after a new breach')['key'], 'security')

    def test_changed_tax_rate_date_and_proposal_are_not_swallowed(self):
        row = self.find('starting in 2027')
        for changed in ({**row, 'title': row['title'].replace('10%', '11%')},
                        {**row, 'title': row['title'].replace('2027', '2028')},
                        {**row, 'title': row['title'].replace('approves', 'proposes')},
                        {**row, 'summary': row['summary'].replace('500', '600')}):
            self.assertFalse(news.same_news_event(row, changed), changed)
        self.assertFalse(news.same_news_event(row, {**self.find('15% levy'), 'published': row['published']+timedelta(hours=25)}))

    def test_commentary_is_not_a_fresh_hack_but_new_progress_is_preserved(self):
        for part in ('Gate CEO', 'cyber war'):
            row = self.find(part)
            self.assertFalse(auto.material_news(row))
            self.assertFalse(editorial.safety_candidate(row))
            self.assertTrue(auto.material_news({**row, 'summary': 'A new exchange hack was confirmed today. Losses revised to $7 billion.'}))
        self.assertTrue(auto.material_news(self.find('Mercado Bitcoin')))

    def test_financial_consolidation_is_not_corporate_integration(self):
        source = self.find('Bitcoin holds $75K')['summary']
        result = quality.checked_translation(source, '由於對美國人工智能監管的擔憂蔓延到亞洲，導致韓國宣布平息股市波動的措施，Bitcoin 得到了整合。')
        self.assertIn('盤整', result)
        self.assertNotIn('整合', result)
        self.assertEqual(quality.checked_translation('Bitcoin Holdings consolidated its subsidiaries', 'Bitcoin Holdings整合了子公司'), 'Bitcoin Holdings整合了子公司')

    def test_midterms_and_short_covering_keep_the_source_context(self):
        source = self.find('Bitcoin Erases Election')['summary']
        result = auto.checked_copy(source, 'Bitcoin下跌近5%，民主黨的中期勝利引發新政策問題，強制清算抹去部分由空頭補償帶動的週三反彈。')
        self.assertIn('期中選舉勝選', result)
        self.assertIn('空頭回補', result)
        self.assertEqual(quality.checked_translation('Students prepare for midterm exams', '學生準備期中考試'), '學生準備期中考試')
        title = '1inch lawyer sees agencies driving US crypto regulation as midterms unfold'
        self.assertIn('期中選舉', auto.checked_copy(title, '隨著期中考試的展開，1 英寸律師認為機構推動美國加密監管'))
        self.assertNotIn('英寸', auto.checked_copy(title, '隨著期中考試的展開，1 英寸律師認為機構推動美國加密監管'))

    def test_hack_and_drained_addresses_are_not_a_hacker_or_data_leak(self):
        row = self.find('Mercado Bitcoin')
        title = auto.checked_copy(row['title'], 'Mercado Bitcoin表示其黑客被封鎖，但區塊鏈數據講述不同故事')
        body = auto.checked_copy(row['summary'], '最新鑑識追蹤11條區塊鏈的4860萬美元，發現數千個客戶地址被洩漏。')
        self.assertIn('駭侵事件已受控制', title)
        self.assertIn('資金遭轉走', body)
        self.assertEqual(quality.numeric_values(body), quality.numeric_values(row['summary']))
        with self.assertRaises(ValueError):
            auto.checked_copy(row['summary'], '交易所損失486億美元')

    def test_delayed_safety_update_keeps_urgency_without_claiming_it_is_fresh(self):
        row = self.find('Mercado Bitcoin')
        row.update(title_zh='Mercado Bitcoin稱駭侵已受控制，鏈上數據顯示不同情況',
                   summary_zh_points=[], auto_copy_version=2)
        card = slim_policy.news_card(row, now=row['published']+timedelta(hours=2))
        self.assertIn('延後整理', card['title'])
        self.assertNotIn('快訊', card['title'])
        self.assertIn('本次整理時間', card['fields'][0]['value'])
        self.assertIn('來源發布時間', card['fields'][0]['value'])
        self.assertTrue(auto.material_news(row))
        self.assertIn('快訊', slim_policy.news_card(row, now=row['published']+timedelta(minutes=3))['title'])
