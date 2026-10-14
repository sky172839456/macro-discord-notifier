import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import cpi_release as cpi
import fed_speech_policy as fed
import market_brief_v2 as brief
import notifier
import slim_policy
from notification_format import apply_delivery_format


class MacroContextTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 13, 45, tzinfo=timezone.utc)
        self.env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def row(self):
        return {'title': 'Consumer Price Index - September 2026', 'summary': '',
                'reference_period': '2026-M09', 'published': self.now,
                'url': 'https://www.bls.gov/news.release/cpi.nr0.htm',
                'rule': {'key': 'cpi', 'name': '美國消費者物價指數（CPI）', 'source': 'https://www.bls.gov/cpi/'},
                'cpi_metrics': {'monthly': .6485, 'annual': 3.7377,
                    'previous_monthly': .39, 'previous_annual': 3.51,
                    'previous_period': '2026/08', 'monthly_seasonally_adjusted': True, 'annual_unadjusted': True}}

    def test_result_previous_and_percentage_point_change_use_display_precision(self):
        text, missing = cpi.details(self.row())
        self.assertEqual(missing, [])
        for token in ('2026/09', '前期 2026/08', '本次 **0.6%**｜前值 0.4%', '變化 +0.2 個百分點', '本次 **3.7%**｜前值 3.5%'):
            self.assertIn(token, text)
        self.assertNotIn('變化 +0.3 個百分點', text)

    def test_nonadjacent_previous_is_not_presented_as_a_comparison(self):
        row = self.row(); row['cpi_metrics']['previous_period'] = '2026/07'
        text, _ = cpi.details(row)
        self.assertIn('前值 暫缺', text)
        self.assertNotIn('變化', text)
        self.assertNotIn('前期 2026/07', text)

    def test_missing_current_preserves_confirmed_previous_without_computing_change(self):
        row = self.row(); row['cpi_metrics']['annual'] = None
        text, missing = cpi.details(row)
        self.assertIn('本次 暫缺｜前值 3.5%', text)
        self.assertEqual(missing, ['年增率'])

    def test_prose_does_not_take_core_or_nonadjacent_month_as_headline_previous(self):
        row = self.row(); row.pop('cpi_metrics')
        row['summary'] = 'The index increased 0.6 percent on a seasonally adjusted basis in September. The core index increased 0.2 percent after rising 0.3 percent in August.'
        text, _ = cpi.details(row)
        self.assertIn('前值 暫缺', text)
        self.assertNotIn('前值 0.3%', text)

    def test_unknown_previous_is_not_zero_and_does_not_invalidate_current(self):
        row = self.row(); row['cpi_metrics'].pop('previous_monthly'); row['cpi_metrics'].pop('previous_annual')
        text, missing = cpi.details(row)
        self.assertEqual(missing, [])
        self.assertIn('前值 暫缺', text)
        self.assertNotIn('0.0%', text)

    def test_adjacent_series_rates_and_year_rollover(self):
        monthly = [{'year':'2026','period':'M01','value':'102'}, {'year':'2025','period':'M12','value':'101'}, {'year':'2025','period':'M11','value':'100'}]
        annual = monthly + [{'year':'2025','period':'M01','value':'98'}, {'year':'2024','period':'M12','value':'97'}]
        metrics = cpi.index_metrics(monthly, annual, '2026-M01')
        self.assertEqual(metrics['previous_period'], '2025/12')
        self.assertAlmostEqual(metrics['previous_monthly'], 1)
        self.assertAlmostEqual(metrics['previous_annual'], (101/97-1)*100)
        monthly.pop()
        self.assertIsNone(cpi.index_metrics(monthly, annual, '2026-M01')['previous_monthly'])
        monthly.pop()
        self.assertIsNone(cpi.index_metrics(monthly, annual, '2026-M01'))

    def test_ppi_api_card_uses_same_clear_comparison_and_series_sources(self):
        row = self.row(); row['rule'] = {'key':'ppi','name':'美國生產者物價指數（PPI）','source':'https://www.bls.gov/ppi/'}
        row['price_metrics'] = row.pop('cpi_metrics'); row['url'] = 'https://api.bls.gov/publicAPI/v2/timeseries/data/WPUFD4'
        card = notifier.release_embed(row)
        self.assertIn('前值 0.4%', card['description'])
        self.assertIn('WPUFD4', json.dumps(card))
        self.assertNotIn('CUUR0000SA0', json.dumps(card))

    def test_empty_calendar_direct_builder_returns_no_card_even_when_sources_failed(self):
        for error in (None, '來源未確認'):
            self.assertEqual(slim_policy.calendar_cards([], self.now, error), [])
            self.assertIsNone(slim_policy.calendar_card([], self.now, error))

    def test_calendar_keeps_time_name_source_and_caveat(self):
        event = {'time':self.now+timedelta(minutes=30),'rule':self.row()['rule']}
        card = slim_policy.calendar_cards([event],self.now,'議程未確認')[0]
        for token in ('台灣時間','22:15','消費者物價指數','官方來源','未列出不代表今天沒有事件'):
            self.assertIn(token,card['description'])

    def test_sentiment_all_source_labels_are_chinese_and_unknown_not_guessed(self):
        labels = {'Extreme Fear':'極度恐懼','Fear':'恐懼','Neutral':'中性','Greed':'貪婪','Extreme Greed':'極度貪婪','Unknown':'分類暫缺'}
        for original, expected in labels.items():
            for weekly in (False, True):
                data = {('weekly_sentiment' if weekly else 'sentiment'):{'value':32,'timestamp':self.now.timestamp(),'classification':' '+original+' '}}
                text = brief.sentiment_lines(data,self.now,weekly)
                self.assertIn('恐慌貪婪指數 **32/100｜'+expected+'**',text)
                self.assertIn('Alternative.me',text)

    def test_uncovered_agenda_failure_is_not_claimed_filled_by_bls_backup(self):
        card = apply_delivery_format(notifier.source_health_embed(['聯準會主席議程：ValueError'],['BLS 官方 API 備援成功']),'bot_log')
        text = json.dumps(card,ensure_ascii=False)
        self.assertIn('其餘失敗項目仍未確認',text)
        self.assertNotIn('已由備援資料補足',text)


class AgendaStructureTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,14,13,45,tzinfo=timezone.utc)
        self.roster = '<h4>2026 Committee Members</h4><ul><li><a>Alex Example</a>, Board of Governors, Chairman</li></ul>'
        self.agenda = "<h4 class='col-md-12'>Speeches </h4><div class=\"col-xs-2\"><p>10:00 a.m.</p></div><div class=\"col-xs-7\"><p>Speech - Chairman Alex Example</p><p class='calendar__title'><em>Monetary Policy Outlook</em></p></div><div class=\"col-xs-3\"><p>14</p></div><h4 class='col-md-12'> Other Releases </h4>"
        self.event = {'id':'aux','time':self.now+timedelta(minutes=15),'title':'Fed Chair Example Speaks','rule':{'key':'fed_official'}}

    def fetch(self,url,attempts=1):
        return self.roster if url == fed.ROSTER_URL else self.agenda

    def test_real_heading_whitespace_attributes_and_next_section_are_supported(self):
        state = {}
        rows, statuses = fed.enrich([self.event],state,self.now,self.fetch)
        self.assertTrue(statuses[0][2])
        self.assertEqual(rows[0]['rule']['key'],'fed_chair_policy')
        self.assertNotIn('Other Releases',state['fed_policy_sources'][rows[0]['rule']['source']]['html'])

    def test_missing_heading_reports_agenda_stage_and_cannot_promote_event(self):
        self.agenda = '<h4>No agenda</h4>'
        rows, statuses = fed.enrich([self.event],{},self.now,self.fetch)
        self.assertFalse(statuses[0][2])
        self.assertIn('2026/10談話議程',statuses[0][1])
        self.assertEqual(rows[0]['rule']['key'],'fed_official')

    def test_unrecognized_rows_are_failure_not_empty_success(self):
        self.agenda = '<h4>Speeches </h4><div class="col-xs-7">changed structure</div><h4>Other</h4>'
        rows, statuses = fed.enrich([self.event],{},self.now,self.fetch)
        self.assertFalse(statuses[0][2])
        self.assertEqual(rows[0]['rule']['key'],'fed_official')


class OfficialMissingValueTests(unittest.TestCase):
    def test_old_api_missing_markers_do_not_break_current_comparison(self):
        rows = [{'year':'2026','period':'M09','value':'102'},
                {'year':'2026','period':'M08','value':'101'},
                {'year':'2026','period':'M07','value':'-'},
                {'year':'2025','period':'M09','value':'100'},
                {'year':'2025','period':'M08','value':'NaN'},
                {'year':'2025','period':'M13','value':'999'}]
        result = cpi.index_metrics(rows, rows, '2026-M09')
        self.assertAlmostEqual(result['annual'],2)
        self.assertIsNone(result['previous_monthly'])
        self.assertIsNone(result['previous_annual'])
