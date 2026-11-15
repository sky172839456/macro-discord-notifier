"""2026-11-15 本人選「推播文字與翻譯修正」：讀者看得懂的時間、標題與用語。"""
import unittest
from datetime import datetime, timedelta, timezone

from news_copy_terms import taiwan_terms
from notification_quality import elapsed_copy, time_copy


class DcTextFixes(unittest.TestCase):
    def test_elapsed_copy_uses_hours_and_days(self):
        self.assertEqual(elapsed_copy(45), '約45分鐘')
        self.assertEqual(elapsed_copy(1288), '約21小時')
        self.assertEqual(elapsed_copy(60 * 72), '約3天')

    def test_late_news_says_hours_not_thousands_of_minutes(self):
        published = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)
        text, late = time_copy(published, published + timedelta(minutes=1288))
        self.assertTrue(late)
        self.assertIn('約21小時', text)
        self.assertNotIn('1288分鐘', text)

    def test_scheduled_release_shows_group_post_time(self):
        scheduled = datetime(2026, 11, 13, 13, 30, tzinfo=timezone.utc)
        text, _ = time_copy(scheduled, scheduled + timedelta(minutes=4), scheduled=True)
        self.assertIn('本群發布', text)
        self.assertNotIn('機器人發現', text)

    def test_taiwan_terms(self):
        self.assertEqual(taiwan_terms('美聯儲考慮升息，人工智能與黑客'), '聯準會考慮升息，人工智慧與駭客')
        self.assertEqual(taiwan_terms('聯準會維持利率'), '聯準會維持利率')


if __name__ == '__main__':
    unittest.main()
