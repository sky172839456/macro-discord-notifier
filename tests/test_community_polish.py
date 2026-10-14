import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, Mock

import risk_notifier as risk
import slim_risk
import crypto_news_notifier as news
from notification_format import apply_delivery_format, WM_COLORS


class CommunityPolishTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 10, tzinfo=timezone.utc)

    def test_brand_style_preserves_links_time_and_category(self):
        row = {'title': '📊 示例數據｜最新數據', 'description': '已確認資料', 'url': 'https://www.bls.gov/cpi/',
               'fields': [{'name': '來源', 'value': '[官方](https://www.bls.gov/cpi/)', 'inline': False}], 'timestamp': self.now.isoformat()}
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
            card = apply_delivery_format(row, 'macro_alerts')
        self.assertTrue(card['title'].startswith('【數據公布】'))
        self.assertEqual(card['author']['name'], 'W先生｜WM Viewture')
        self.assertEqual(card['color'], WM_COLORS['purple'])
        self.assertEqual(card['url'], row['url'])
        self.assertEqual(card['timestamp'], row['timestamp'])
        self.assertEqual(row['fields'][0]['name'], '來源')
        self.assertEqual(card['fields'][0]['name'], '🔗 資料來源')

    def test_functional_color_and_text_categories_match(self):
        for title, channel, color in [('【恢復通知】✅ 服務已恢復', 'market_risk', 'green'),
                                      ('【官員談話】主席政策談話', 'macro_alerts', 'amber'),
                                      ('【重大快訊】服務中斷', 'crypto_news', 'red'),
                                      ('【新聞彙整】今日新聞', 'crypto_news', 'blue'),
                                      ('【每週行情】市場導航', 'weekly_market', 'purple')]:
            with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'}):
                card = apply_delivery_format({'title': title, 'fields': []}, channel)
            self.assertEqual(card['color'], WM_COLORS[color])
            self.assertEqual(card['title'], title)

    def bybit(self, state='ongoing', kind=3, env=1, **extra):
        item = {'id': 'event', 'title': 'Service incident', 'state': state, 'maintainType': kind,
                'env': env, 'begin': '1791972000000', 'end': '1791979200000', **extra}
        with patch.object(risk, 'get_json', return_value={'retCode': 0, 'result': {'list': [item]}}):
            return risk.bybit_incidents()

    def test_bybit_unplanned_production_incident_is_material(self):
        row = self.bybit()[0]
        self.assertEqual(row['status'], 'investigating')
        self.assertTrue(slim_risk.incident_material(row))
        self.assertIsNone(row['updated_at'])

    def test_bybit_planned_or_temporary_maintenance_not_member_alert(self):
        for kind in (1, 2):
            row = self.bybit(kind=kind)[0]
            self.assertFalse(slim_risk.incident_material(row))

    def test_bybit_demo_canceled_and_unknown_state_excluded(self):
        self.assertEqual(self.bybit(env=2), [])
        self.assertEqual(self.bybit(state='canceled'), [])
        self.assertEqual(self.bybit(state='unexpected'), [])

    def test_bybit_actual_href_preserved_and_expected_end_not_publication(self):
        row = self.bybit(href='https://announcements.bybit.com/article/example')[0]
        self.assertEqual(row['url'], 'https://announcements.bybit.com/article/example')
        self.assertIsNone(row.get('updated_at'))

    def test_bybit_completion_requires_previous_alert_before_recovery(self):
        row = self.bybit(state='completed')[0]
        self.assertFalse(slim_risk.incident_transition({}, row))
        self.assertTrue(slim_risk.incident_transition({'alerted': True, 'resolved': False}, row))

    def test_bad_numeric_translation_not_shown_as_incident_fact(self):
        api = SimpleNamespace(clean_source_text=lambda s, _: s, translate_title=lambda s: '暫停提款1000分鐘', translate_status=lambda s: '調查中')
        with patch.object(news, 'translate_text', return_value='提款暫停1000分鐘'):
            card = slim_risk.incident_card(api, 'Bybit', {'name': 'Withdrawals paused 5 minutes', 'body': 'Withdrawals paused 5 minutes', 'status': 'investigating', 'url': 'https://announcements.bybit.com/'}, self.now)
        self.assertNotIn('1000', json.dumps(card, ensure_ascii=False))
        self.assertIn('服務事件更新', card['title'])
        self.assertIn('中文摘要暫缺', card['description'])

    def test_source_outage_visible_to_admin_once_per_day_not_members(self):
        state = {}
        api = SimpleNamespace(load=lambda: state, save=Mock(), get_json=lambda *_: {'incidents': []}, STATUS_URL='https://status.coinbase.com/',
                              bybit_incidents=Mock(side_effect=OSError('source down')), critical_official_notices=lambda: [], send=Mock())
        prices = {coin: {'CoinGecko': 1.0, 'Kraken': 1.0} for coin in slim_risk.COINS}
        with patch.dict(os.environ, {'DISCORD_LOG_WEBHOOK_URL': 'https://discord.invalid'}), patch.object(slim_risk, 'price_sources', return_value=prices), patch('notifier.send_discord') as log:
            slim_risk.monitor(api, 'https://discord.invalid/member', self.now)
            slim_risk.monitor(api, 'https://discord.invalid/member', self.now+timedelta(minutes=5))
        log.assert_called_once()
        api.send.assert_not_called()
        self.assertFalse(state['slim_service_sources']['Bybit']['ok'])
        self.assertTrue(state['slim_service_sources']['Coinbase']['ok'])

    def test_empty_successful_service_feed_not_source_failure(self):
        state = {}
        api = SimpleNamespace(load=lambda: state, save=Mock(), get_json=lambda *_: {'incidents': []}, STATUS_URL='https://status.coinbase.com/',
                              bybit_incidents=lambda: [], critical_official_notices=lambda: [], send=Mock())
        prices = {coin: {'CoinGecko': 1.0, 'Kraken': 1.0} for coin in slim_risk.COINS}
        with patch.object(slim_risk, 'price_sources', return_value=prices):
            slim_risk.monitor(api, 'https://discord.invalid/member', self.now)
        self.assertTrue(state['slim_service_sources']['Bybit']['ok'])
        self.assertEqual(state['slim_service_sources']['Bybit']['count'], 0)


if __name__ == '__main__':
    unittest.main()
