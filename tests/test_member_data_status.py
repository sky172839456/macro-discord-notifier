import copy
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import notifier
from notification_format import CHANNEL_AUTHORS, apply_delivery_format, infer_source_status
import test_macro_calendar_delivery as calendar_tests


def complete(now):
    return {'id': 'bls-api-cpi-current', 'published': now,
            'title': 'Consumer Price Index - September 2026',
            'summary': '', 'reference_period': '2026-M09',
            'url': 'https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0',
            'rule': {'key': 'cpi', 'name': '美國消費者物價指數（CPI）', 'source': 'https://www.bls.gov/cpi/'},
            'cpi_metrics': {'monthly': .6, 'annual': 3.7,
                'monthly_seasonally_adjusted': True, 'annual_unadjusted': True}}


class MemberStatusTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 12, 35, tzinfo=timezone.utc)
        env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'DISCORD_LOG_WEBHOOK_URL': 'https://admin.invalid'})
        env.start(); self.addCleanup(env.stop)

    def test_no_member_channel_contains_auto_or_existing_status_field(self):
        original = {'title': '通知', 'description': '前值暫缺；本次 0.6%',
                    'fields': [{'name':'🩺 資料狀態','value':'⚠️ 部分資料缺少'},
                               {'name':'🔗 官方來源','value':'https://www.bls.gov/cpi/'}]}
        for slim in ('0', '1'):
            for channel in CHANNEL_AUTHORS:
                if channel == 'bot_log': continue
                with self.subTest(slim=slim,channel=channel), patch.dict(os.environ, {'SLIM_NOTIFICATIONS':slim}):
                    card = apply_delivery_format(original, channel, source_status='partial')
                    text = json.dumps(card,ensure_ascii=False)
                    self.assertNotIn('資料狀態',text)
                    self.assertIn('前值暫缺',text)
                    self.assertIn('https://www.bls.gov/cpi/',text)
        self.assertEqual(len(original['fields']),2)

    def test_forecast_disclaimer_is_not_a_source_outage(self):
        self.assertEqual(infer_source_status({'description':'市場預期值不屬於官方資料；未提供。'}),'ok')

    def test_admin_retains_diagnostic_and_no_false_green_on_failed_member_source(self):
        card = apply_delivery_format({'title':'來源異常'},'bot_log',source_status='partial')
        self.assertIn('部分資料缺少',json.dumps(card,ensure_ascii=False))
        with patch.dict(os.environ, {'SLIM_NOTIFICATIONS':'0'}):
            member = apply_delivery_format({'title':'通知'},'macro_alerts',source_status='error')
            self.assertNotIn('來源正常',member['footer']['text'])

    def test_service_risk_and_inline_caveats_survive(self):
        text = '⚠️ 官方暫停提款；USDT 脫鉤 1.5%；前值暫缺。'
        card = apply_delivery_format({'title':'【風險警報】提款暫停','description':text},'market_risk')
        self.assertEqual(card['description'],text)

    def test_missing_previous_is_optional_and_kept_next_to_current(self):
        row = complete(self.now)
        self.assertEqual(notifier.release_critical_missing(row),[])
        card = apply_delivery_format(notifier.release_embed(row,detected_at=self.now),'macro_alerts')
        self.assertIn('前值 暫缺',card['description'])
        self.assertNotIn('資料狀態',json.dumps(card,ensure_ascii=False))

    def test_critical_data_logs_once_and_later_recovers(self):
        row = complete(self.now); row['cpi_metrics']['annual'] = None
        alerts = {}
        with patch.object(notifier,'send_discord') as send:
            for _ in range(2):
                self.assertFalse(notifier.deliver_release('https://member.invalid',row,None,None,self.now,False,alerts))
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0],'https://admin.invalid')
            row['cpi_metrics']['annual'] = 3.7
            self.assertTrue(notifier.deliver_release('https://member.invalid',row,None,None,self.now,False,alerts))
            self.assertEqual(send.call_args.args[0],'https://member.invalid')

    def test_unknown_period_and_basis_block_but_real_zero_is_valid(self):
        row = complete(self.now); row['cpi_metrics']['monthly'] = 0
        self.assertEqual(notifier.release_critical_missing(row),[])
        row.pop('reference_period'); row['title'] = 'CPI update'
        self.assertIn('資料月份',notifier.release_critical_missing(row))
        row['cpi_metrics'].pop('annual_unadjusted')
        self.assertIn('年增率季調口徑',notifier.release_critical_missing(row))

    def test_private_log_failure_never_unblocks_result_or_marks_logged(self):
        row = complete(self.now); row['cpi_metrics']['monthly'] = None
        alerts = {}
        with patch.object(notifier,'send_discord',side_effect=RuntimeError('offline')) as send:
            self.assertFalse(notifier.deliver_release('https://member.invalid',row,None,None,self.now,False,alerts))
            self.assertEqual(send.call_count,1)
        self.assertEqual(alerts,{})


class ScheduledReleaseGateTests(unittest.TestCase):
    setUp = calendar_tests.MacroCalendarDeliveryTests.setUp
    read_calendar = calendar_tests.MacroCalendarDeliveryTests.read_calendar
    member_calls = calendar_tests.MacroCalendarDeliveryTests.member_calls
    admin_calls = calendar_tests.MacroCalendarDeliveryTests.admin_calls

    def test_blocked_result_retries_without_consuming_source_or_delivery_keys(self):
        old = {'signature':'old'}
        self.state['bls_api'] = {'cpi':old}
        self.state['official_pages'] = {'cpi':'old-page'}
        row = complete(self.now); row['cpi_metrics']['annual'] = None
        self.releases = [row]
        def fetch(*_):
            self.state['bls_api']['cpi'] = {'signature':'new'}
            self.state['official_pages']['cpi'] = 'new-page'
            return self.releases,[],[]
        with patch.object(notifier,'fetch_official_page_releases',side_effect=fetch):
            notifier.run(self.now)
            self.assertEqual(self.member_calls(),[])
            self.assertFalse(any(k.startswith('release') for k in self.state['sent']))
            self.assertEqual(self.state['bls_api']['cpi'],old)
            self.assertEqual(self.state['official_pages']['cpi'],'old-page')
            self.releases = [complete(self.now)]
            notifier.run(self.now)
            notifier.run(self.now)
        self.assertEqual(len(self.member_calls()),1)
        self.assertIn('release-event:cpi:2026-10-14',self.state['sent'])

    def test_complete_api_candidate_wins_over_incomplete_richer_rss(self):
        good = complete(self.now)
        bad = copy.deepcopy(good); bad['id']='rss'; bad['cpi_metrics']['annual']=None
        bad['summary'] = 'Official detailed release prose. ' * 30
        self.releases = [bad,good]
        notifier.run(self.now)
        self.assertEqual(len(self.member_calls()),1)
        self.assertIn('本次 **3.7%**',self.member_calls()[0].args[1]['description'])


if __name__ == '__main__': unittest.main()
