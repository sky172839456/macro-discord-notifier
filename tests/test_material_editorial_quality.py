import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from notification_quality import checked_translation
from news_copy_terms import repair_translation
from material_editorial import review
import material_inbox as m
import news_streams

MARKET='AI Chip Stocks Bounce After Global Rout—But Is the Bubble Starting to Burst?'
REPORT='Why a new report on Anthropic automating AI development is alarming researchers'


class EditorialQuality(unittest.TestCase):
    def row(self,title,summary=''):
        return dict(title=title,summary=summary,title_zh='原有譯文',material_topic='ai',
                    published=datetime(2026,11,8,tzinfo=timezone.utc),source='Media',official=False,url='https://example.com/story')

    def test_market_research_and_interview_do_not_become_new_tools(self):
        cases=[(MARKET,'','research'),(REPORT,'Researchers investigated model development.','research'),
               ('AI broke the cybersecurity world. What’s next?','Talking with an expert in this episode.','research'),
               ('NYT Cooking’s AI assistant saved my weeknight chicken, but almost ruined my cake','','interesting')]
        for title,summary,expected in cases:
            self.assertEqual(m.topic(self.row(title,summary)),expected)
        self.assertEqual(m.topic(self.row('OpenAI launches a new AI coding tool')),'ai')
        self.assertEqual(m.topic(self.row('AI exploit hacked a crypto exchange today','A new attack confirmed today.')),'security')

    def test_plans_follow_evidence_and_remain_questions(self):
        cases=[(MARKET,'','股價反彈'),(REPORT,'','量到了什麼'),
               ('AI broke the cybersecurity world. What’s next?','Talking with an expert in this episode.','攻防環節'),
               ('NYT Cooking’s AI assistant saved my weeknight chicken, but almost ruined my cake','','晚餐')]
        for title,summary,anchor in cases:
            row=self.row(title,summary)
            before=copy.deepcopy(row)
            result=review(row,row['published'])
            self.assertIn(anchor,result['concept'])
            self.assertNotIn('這次AI更新',result['concept'])
            self.assertIn('高星不代表已完成查證',result['basis'])
            self.assertEqual(row,before)

    def test_cached_card_reclassifies_without_mutating_history_or_priority_fields(self):
        row=self.row(MARKET)
        before=copy.deepcopy(row)
        card=m.card(row,row['published'])
        self.assertIn('研究／市場知識',card['description'])
        self.assertIn('製作優先度',card['description'])
        self.assertIn('來源內容',json.dumps(card,ensure_ascii=False))
        self.assertNotIn('初步內容構思',json.dumps(card,ensure_ascii=False))
        self.assertEqual(row,before)

    def test_entities_decode_before_sanitizing_mentions_and_markup(self):
        self.assertEqual(m.clean('AT&amp;T &#8230; &amp;#8230;',100),'AT&T … …')
        self.assertNotIn('script',m.clean('&lt;script&gt;x&lt;/script&gt;',100))
        self.assertNotIn('@',m.clean('&commat;everyone',100))
        self.assertEqual(m.clean('16% -0.2 1,000 https://example.com?a=1&amp;b=2',200),
                         '16% -0.2 1,000 https://example.com?a=1&b=2')

    def test_translation_fixes_are_exact_and_preserve_questions(self):
        self.assertIn('Anthropic',checked_translation(REPORT,'為什麼人類的AI報告讓研究者震驚'))
        self.assertIn('全球市場',checked_translation(MARKET,'AI晶片股票在全球經濟潰敗後反彈，但泡沫開始破裂了嗎？'))
        for title in (REPORT+' Not confirmed.',MARKET.replace('Bounce','Fall')):
            self.assertEqual(repair_translation(title,'原有譯文'),'原有譯文')

    def test_new_finance_digest_title_is_unified(self):
        import inspect
        source=inspect.getsource(news_streams)
        self.assertIn('【金融新聞】 🌐 全球錢線',source)
        self.assertNotIn('【金融新聞】 🌐 金融風向',source)
