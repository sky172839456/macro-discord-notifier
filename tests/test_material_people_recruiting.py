import copy
import json
import unittest
from datetime import datetime, timezone
import material_inbox as m
from material_editorial import editorial_angle, review
from notification_quality import checked_translation
from news_copy_terms import repair_translation

PEOPLE='Meta chief strategy officer Dave Wehner leaves to join AI infrastructure startup Fireworks as CFO'
RECRUIT='AI is speeding up recruitment — and putting agency fees under pressure'

class PeopleRecruiting(unittest.TestCase):
    def row(self,title):
        return dict(title=title,title_zh='原有中文',summary='',material_topic='ai',source='Media',official=False,
                    published=datetime(2026,11,8,tzinfo=timezone.utc),url='https://example.com/story')

    def test_people_move_beats_ai_keyword_but_not_tool_roles(self):
        self.assertEqual(m.topic(self.row(PEOPLE)),'business')
        self.assertEqual(m.topic(self.row('Company appoints a new CFO')),'business')
        self.assertIsNone(editorial_angle('AI agent becomes CFO in a simulation'))
        self.assertIsNone(editorial_angle('CEO introduces an AI tool'))
        self.assertEqual(m.topic(self.row('CEO introduces an AI tool')),'ai')
        self.assertIsNone(m.topic(self.row('Sponsored: '+PEOPLE)))

    def test_people_plan_and_cached_card_are_source_bounded(self):
        row=self.row(PEOPLE);before=copy.deepcopy(row)
        card=m.card(row,row['published']);text=json.dumps(card,ensure_ascii=False)
        for x in ('企業／交易所進展','來源內容','查證狀態','製作優先度','來源與時間'):
            self.assertIn(x,text)
        self.assertNotIn('這次AI更新',text)
        self.assertEqual(row,before)

    def test_recruiting_has_workflow_and_fee_angle_without_claiming_replacement(self):
        row=self.row(RECRUIT)
        self.assertEqual(m.topic(row),'ai')
        plan=review(row,row['published'])
        for x in ('招募的哪一步','服務費','當事人觀點'):
            self.assertIn(x,plan['concept'])
        self.assertNotIn('這次AI更新',plan['concept'])
        self.assertEqual(len(plan['display']),5)

    def test_exact_translation_keeps_names_and_changed_events_fall_back(self):
        self.assertIn('Fireworks 財務長',checked_translation(PEOPLE,'Meta高層加入AI公司'))
        self.assertIn('招募服務費',checked_translation(RECRUIT,'AI招聘導致代理費壓力'))
        self.assertEqual(repair_translation(PEOPLE.replace('leaves','denies plans to leave'),'原有中文'),'原有中文')
