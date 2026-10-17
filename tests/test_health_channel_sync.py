import json
import os
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

import analysis_notifier
import realtime_health as health
from community_channels import CHANNEL_IDS, channel_ref
from notification_format import apply_delivery_format


class HealthChannelSyncTests(unittest.TestCase):
    now = datetime(2026, 10, 17, 23, 4, tzinfo=timezone.utc)

    def production_results(self):
        rows = {name: ('ok', '本輪執行完成') for name in health.MONITOR_LABELS}
        for name in ('上幣通知', '交易所公告', '衍生品'):
            rows[name] = ('disabled', '社群精簡版停用')
        rows['市場分析'] = ('merged', '已併入行情日週報，不另行發送')
        return rows

    def test_report_uses_live_channel_mentions_for_all_four_destinations(self):
        card = health.daily_health_embed(self.production_results(), {}, self.now)
        for key in ('macro', 'crypto', 'finance', 'market'):
            self.assertIn(channel_ref(key), card['description'])
        self.assertIn('共用新聞整理', card['description'])
        self.assertNotIn('全部正常', card['title'])
        self.assertIn('流程完成不代表來源全部正常', card['footer']['text'])

    def test_merged_analysis_and_disabled_alerts_are_not_successes(self):
        card = health.daily_health_embed(self.production_results(), {}, self.now)
        self.assertEqual(card['description'].count('✅'), 4)
        self.assertIn('已整併', card['description'])
        self.assertIn('已停用的獨立通知', card['description'])
        self.assertIn('獨立衍生品警報', card['description'])
        self.assertNotIn('異常', card['title'])

    def test_missing_failed_and_unconfigured_work_remain_visible(self):
        for status in ('missing', 'failed', 'skipped'):
            with self.subTest(status=status):
                rows = self.production_results()
                rows['市場摘要'] = (status, '本輪未完成')
                card = health.daily_health_embed(rows, {}, self.now)
                self.assertEqual(card['color'], 0xF1C40F)
                self.assertIn('本輪未完成', card['description'])
                self.assertNotIn('已啟用流程完成', card['title'])

    def test_empty_results_cannot_be_green(self):
        card = health.daily_health_embed({}, {}, self.now)
        self.assertIn('8 個流程異常', card['title'])
        self.assertEqual(card['description'].count('本輪沒有執行紀錄'), 8)

    def test_delivery_has_current_log_author_without_inferred_source_health(self):
        embed = health.daily_health_embed(self.production_results(), {}, self.now)
        with patch.object(health, 'urlopen') as opened:
            health.send_webhook('https://discord.invalid/webhook', embed)
        payload = json.loads(opened.call_args.args[0].data)
        card = payload['embeds'][0]
        self.assertEqual(card['author']['name'], '管家工作簿｜系統紀錄')
        self.assertNotIn('SYSTEM HEALTH', json.dumps(card))
        self.assertNotIn('機器人紀錄', json.dumps(card, ensure_ascii=False))
        self.assertFalse(any(f['name'] == '🩺 資料狀態' for f in card['fields']))
        self.assertIn('執行狀態', card['fields'][-1]['name'])
        self.assertEqual(payload['allowed_mentions'], {'parse': []})

    def test_actual_consolidated_analysis_does_no_independent_work(self):
        with patch.dict(os.environ, {'CONSOLIDATED_CHANNELS': '1'}), patch.object(analysis_notifier, 'run') as run:
            self.assertEqual(analysis_notifier.run_scheduled(self.now), [])
        run.assert_not_called()
        workflow = (Path(__file__).resolve().parents[1]/'.github/workflows/realtime-monitors.yml').read_text(encoding='utf-8')
        self.assertIn('if [ "$CONSOLIDATED_CHANNELS" = "1" ]; then', workflow)
        self.assertIn('%s|merged|已併入行情日週報，不另行發送', workflow)

    def test_delay_note_does_not_claim_retired_notification_backfill(self):
        card = health.delay_embed(self.now, self.now, 20)
        window = next(f['value'] for f in card['fields'] if f['name'] == '自動回補範圍')
        self.assertNotIn('上幣公告', window)
        self.assertNotIn('交易所公告', window)
        self.assertIn('不保證所有延遲內容都會補發', window)

    def test_log_author_is_shared_by_other_administrative_cards(self):
        card = apply_delivery_format({'title': '來源異常', 'fields': []}, 'bot_log', source_status='error')
        self.assertEqual(card['author']['name'], '管家工作簿｜系統紀錄')
        self.assertIn('所有來源失敗', card['fields'][0]['value'])


if __name__ == '__main__':
    unittest.main()
