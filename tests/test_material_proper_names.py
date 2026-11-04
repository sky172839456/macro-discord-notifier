import copy
import unittest
from datetime import datetime, timezone
from notification_quality import checked_translation
from news_copy_terms import repair_translation
import material_inbox as inbox

NOTHING = 'Nothing teases a screen-free AI device ahead of launch next month'
CANTON = 'Canton Coin Gets SEC Nod as Wall Street Tokenization Heats Up'

class MaterialNames(unittest.TestCase):
    def test_nothing_brand_and_preview_do_not_become_nothing_or_mockery(self):
        result = checked_translation(NOTHING, '在下個月推出之前，沒有任何東西可以取笑免螢幕 AI 設備')
        self.assertEqual(result, 'Nothing 預告無螢幕 AI 裝置，預計下月推出')
        self.assertNotIn('已推出', result)

    def test_canton_name_and_tokenization_do_not_become_city_or_coins(self):
        result = checked_translation(CANTON, '隨著華爾街令牌化升溫，廣州硬幣獲得 SEC 點頭')
        self.assertIn('Canton Coin', result)
        self.assertIn('代幣化', result)
        self.assertNotIn('核准', result)
        self.assertNotIn('批准', result)

    def test_ordinary_nothing_places_and_changed_release_stage_are_untouched(self):
        for title in ('Nothing teases a screen-free AI device ahead of launch next week',
                      'Nothing denies a screen-free AI device launch next month',
                      'Canton Coin denied SEC nod as tokenization cools',
                      'Nothing happened in Canton today'):
            with self.subTest(title=title):
                self.assertEqual(repair_translation(title, '原有譯文'), '原有譯文')

    def test_cached_candidate_is_repaired_at_card_render_without_state_changes(self):
        now=datetime(2026,11,5,6,tzinfo=timezone.utc)
        row={'title':NOTHING,'title_zh':'在下個月推出之前，沒有任何東西可以取笑免螢幕 AI 設備',
             'material_topic':'ai','summary':NOTHING,'source':'The Verge','official':False,
             'published':now,'url':'https://www.theverge.com/ai/example','status':'queued'}
        old=copy.deepcopy(row)
        card=inbox.card(row,now)
        self.assertIn('Nothing 預告',card['title'])
        self.assertIn('製作優先度',card['description'])
        self.assertEqual(row,old)
