"""2026-11-18 本人選「推播卡片用 WV 表情」＋「動態表情（低調版）」。"""
import os
import re
import unittest
from unittest import mock

import wv_emoji as w


def delivered(title, channel, **extra):
    with mock.patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
        from notification_format import apply_delivery_format
        return apply_delivery_format({'title': title, 'description': '測試內容', 'fields': [], **extra}, channel)


class WvEmojiTitleTests(unittest.TestCase):
    def test_every_card_type_gets_the_agreed_emoji(self):
        cases = [
            ('【價格快訊】 📈 ETH 24小時 +5.02%', 'daily_market', '<a:wv_up_a:'),
            ('【價格快訊】 📉 BTC 1小時 -3.10%', 'daily_market', '<a:wv_down_a:'),
            ('📊 市場情報｜11/18（週三）', 'daily_market', '<a:wv_coffee_a:'),
            ('🧭 本週導航｜11/16（週一）', 'weekly_market', '<a:wv_logo_a:'),
            ('🔴 美國工業生產與產能利用率｜最新數據', 'macro_alerts', '<:wv_note:'),
            ('【數據公布】⏳ 補發｜美國CPI｜最新數據', 'macro_alerts', '<:wv_note:'),
            ('🗓️ 今日總經行事曆｜11/17｜共2項', 'macro_alerts', '<:wv_eyes:'),
            ('【下週行事曆】 🗓️ 11/16～11/22', 'macro_alerts', '<:wv_eyes:'),
            ('⏰ 公布前提醒｜美國CPI', 'macro_alerts', '<:wv_eyes:'),
            ('📆 明日重要事件提醒｜美國CPI', 'macro_alerts', '<:wv_eyes:'),
            ('【官員談話】⏰ 政策談話前提醒｜鮑爾', 'macro_alerts', '<:wv_eyes:'),
            ('【重大快訊】 🚨 快訊｜資安事件｜X', 'crypto_news', '<:wv_risk:'),
            ('【市場新聞】 ⏳ 延後整理｜資安事件｜Y', 'crypto_news', '<:wv_note:'),
            ('【金融快訊】 🚨 快訊｜Z', 'finance_news', '<:wv_risk:'),
            ('✅ 服務已恢復｜Bybit', 'market_risk', '<:wv_got:'),
        ]
        for title, channel, expected in cases:
            with self.subTest(title=title):
                out = delivered(title, channel)['title']
                self.assertTrue(out.startswith('【'), out)
                self.assertIn(expected, out)
                # 文字內容不變：拿掉表情後，跟原本拿掉圖示的標題一致
                rest = re.sub(r'<a?:wv_\w+:\d+>', '', out).split('】', 1)[1].strip()
                self.assertTrue(title.endswith(rest), (title, rest))

    def test_channel_icons_and_mixed_direction_stay(self):
        for title, channel in (('【加密新聞】 🪙 幣圈有事｜11/17', 'crypto_news'),
                               ('【金融新聞】 🌐 全球錢線｜11/17', 'finance_news'),
                               ('【價格快訊】 ↕️ BTC／ETH', 'daily_market')):
            with self.subTest(title=title):
                self.assertEqual(delivered(title, channel)['title'], title)

    def test_test_channel_preview_shows_the_same_emoji(self):
        out = delivered('🧪 精簡版預覽｜📊 市場情報｜11/18（週三）', 'daily_market')['title']
        self.assertTrue(out.startswith('【每日行情】 🧪 精簡版預覽｜<a:wv_coffee_a:'), out)
        self.assertTrue(out.endswith('> 市場情報｜11/18（週三）'), out)

    def test_admin_log_is_untouched(self):
        with mock.patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            from notification_format import apply_delivery_format
            card = apply_delivery_format({'title': '🚨 來源異常', 'fields': []}, 'bot_log')
        self.assertNotIn('wv_', card['title'])

    def test_keeps_plain_icon_when_limit_would_be_exceeded(self):
        title = '【重大快訊】 🚨 快訊｜' + '甲' * 230  # 原本 245 字，換上表情會超過 256
        self.assertLessEqual(len(title), 256)
        card = w.brand_title({'title': title, 'description': 'x'})
        self.assertEqual(card['title'], title)
        short = w.brand_title({'title': '【重大快訊】 🚨 快訊｜短', 'description': 'x'})
        self.assertIn('<:wv_risk:', short['title'])

    def test_ids_and_names_are_well_formed(self):
        self.assertEqual(len(w.STATIC), 16)
        self.assertEqual(len(w.ANIMATED), 16)
        self.assertEqual({k + '_a' for k in w.STATIC}, set(w.ANIMATED))
        ids = list(w.STATIC.values()) + list(w.ANIMATED.values())
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(re.fullmatch(r'\d{17,20}', i) for i in ids))
        for mapping in w.TITLE_ICONS.values():
            for name in mapping.values():
                w.markup(name)  # 每個用到的名字都有 ID
        self.assertTrue(w.markup('wv_up_a').startswith('<a:'))
        self.assertTrue(w.markup('wv_note').startswith('<:'))


if __name__ == '__main__':
    unittest.main()
