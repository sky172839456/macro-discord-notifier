import copy
import json
import unittest
from datetime import datetime, timezone
from notification_layout import section_end, DIVIDER, readable_card
import material_inbox as inbox


class CompactServiceMaterial(unittest.TestCase):
    def test_old_boundary_compacts_without_touching_values(self):
        old = '本次 189,000 人\n前值 195,000 人\n\n'+DIVIDER+'\n\n\u200b'
        expected = '本次 189,000 人\n前值 195,000 人\n'+DIVIDER
        self.assertEqual(section_end(old), expected)
        self.assertEqual(section_end(expected), expected)

    def test_real_fields_keep_native_spacing_and_sources(self):
        row = {'description':'公告', 'fields':[
            {'name':'結果','value':'189,000 人'},
            {'name':'時間','value':'2026/11/05 21:34'},
            {'name':'來源','value':'https://example.com/a?x=1&y=2'}]}
        result = readable_card(copy.deepcopy(row))
        self.assertEqual(result['fields'][0]['value'],'189,000 人\n'+DIVIDER)
        self.assertEqual(result['fields'][-1]['value'],row['fields'][-1]['value'])

    def test_access_changes_are_candidates_without_assuming_policy(self):
        self.assertEqual(inbox.topic({'title':'Bitfinex registration unavailable for Taiwanese nationals'}),'business')
        self.assertEqual(inbox.topic({'title':'Bitget restricts account registration under new regulatory rules'}),'policy')
        self.assertEqual(inbox.topic({'title':'Binance resumes account verification'}),'business')
        for title in ('Bitfinex signup discount', 'Bitget registration guide', 'A website restricts accounts'):
            self.assertFalse(inbox.exchange_access_notice(title))

    def test_card_keeps_uncertainty_stars_and_access_scope(self):
        now=datetime(2026,11,7,tzinfo=timezone.utc)
        row={'title':'Bitfinex registration unavailable for Taiwanese nationals','material_topic':'business',
             'published':now,'official':False,'source':'Media','url':'https://example.com/story'}
        text=json.dumps(inbox.card(row,now),ensure_ascii=False)
        for value in ('國籍／居住地','新戶／既有帳戶','不建議搶註冊','媒體報導候選','製作優先度'):
            self.assertIn(value,text)

    def test_major_ai_tools_remain_nonfinancial_candidates(self):
        self.assertEqual(inbox.topic({'title':'AI company unveils a new video generation system'}),'ai')
