"""2026-11-22 週日下週行事曆漏列 11/25 PCE（pce-weekly-calendar-upcoming-source-gap-20261124）。

BLS 行事曆不含 BEA 的 PCE／GDP；週表只讀 BLS→BLS 月頁→公開行事曆，且公開行事曆別名缺 PCE。
修正後週表與 07:00 每日行事曆讀同一份 BEA／Census／Fed 官方排程，官方優先、同項同分鐘只列一次。
全部離線：來源以固定文字替身，不連網、不發送。
"""
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import next_week_calendar as nwc
import notifier
import slim_policy
import summary_notifier as summary
from macro_calendar import G17_URL

NOW = datetime(2026, 11, 22, 12, 5, tzinfo=timezone.utc)  # 台灣 11/22（日）20:05
PCE = '美國 PCE／核心 PCE 物價指數'
WARNING = '⚠️ 行事曆尚未完整確認'


def bea_page(*rows):
    """Rows as the official BEA schedule renders them: date, time, release type, title."""
    return '<table>' + ''.join(
        f'<tr><td>{day}</td><td>{clock}</td><td><span>N</span>ews</td><td><a>{title}</a></td><td>View</td></tr>'
        for day, clock, title in rows) + '</table>'


BEA_NOV = bea_page(
    ('November 25', '8:30 AM', 'GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026'),
    ('November 25', '8:30 AM', 'Personal Income and Outlays, October 2026'),
    ('December 23', '8:30 AM', 'Personal Income and Outlays, November 2026'),
)
CENSUS = ("Advance Monthly Sales for Retail and Food Services December 15, 2026 8:30 AM "
          "Advance Report on Durable Goods--Manufacturers' Shipments, Inventories, and Orders November 25, 2026 8:30 AM")
FED = '2026 FOMC Meetings July 28-29 December 8-9* 2025 FOMC Meetings'
G17 = 'monthly releases are issued at 9:15 a.m. 2026: November 17, December 16. Historical Release Dates'
BLS_ICS = ('BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:cpi-20261210\nSUMMARY:Consumer Price Index for November 2026\n'
           'DTSTART:20261210T083000\nEND:VEVENT\nEND:VCALENDAR\n')


def ff_rows(*extra):
    rows = [
        {'country': 'USD', 'title': 'FOMC Member Waller Speaks', 'date': '2026-11-23T10:00:00-05:00'},
        {'country': 'USD', 'title': 'Prelim GDP q/q', 'date': '2026-11-25T08:30:00-05:00'},
        {'country': 'USD', 'title': 'Unemployment Claims', 'date': '2026-11-25T08:30:00-05:00'},
        {'country': 'USD', 'title': 'Core Durable Goods Orders m/m', 'date': '2026-11-25T08:30:00-05:00'},
        {'country': 'USD', 'title': 'Personal Income m/m', 'date': '2026-11-25T08:30:00-05:00'},
        {'country': 'USD', 'title': 'Personal Spending m/m', 'date': '2026-11-25T08:30:00-05:00'},
    ]
    return rows + list(extra)


CORE_PCE_1125 = {'country': 'USD', 'title': 'Core PCE Price Index m/m', 'date': '2026-11-25T08:30:00-05:00'}
PCE_YOY_1125 = {'country': 'USD', 'title': 'PCE Price Index y/y', 'date': '2026-11-25T08:30:00-05:00'}


@contextmanager
def sources(bls=None, ff=None, bea=BEA_NOV, census=CENSUS, fed=FED, g17=G17):
    """None = that source answers 403/unreachable."""
    official = {notifier.EXTENDED_CALENDARS['BEA']: bea, notifier.EXTENDED_CALENDARS['CENSUS']: census,
                notifier.EXTENDED_CALENDARS['FED']: fed, G17_URL: g17}

    def bls_text(url, attempts=3):
        if bls is None:
            raise OSError('HTTP Error 403: Forbidden')
        return bls

    def official_text(url, attempts=3):
        if official.get(url) is None:
            raise OSError('HTTP Error 403: Forbidden')
        return official[url]

    def ff_json(url):
        if ff is None:
            raise OSError('unreachable')
        return ff if url.endswith('thisweek.json') else []

    with patch.object(summary, 'http_text', side_effect=bls_text), \
         patch.object(summary, 'http_json', side_effect=ff_json), \
         patch.object(notifier, 'http_text', side_effect=official_text), \
         patch.object(summary.time, 'sleep'):
        yield


def week_text(now=NOW, **kwargs):
    with sources(**kwargs):
        events, error = summary.upcoming_events(now, 9)
    card, _ = nwc.build_card(now, events, error)
    return events, card['description']


class PublicCalendarAliasTests(unittest.TestCase):
    def test_core_pce_title_maps_to_pce_like_daily_calendar(self):
        events = summary.parse_fair_economy_calendar([CORE_PCE_1125, PCE_YOY_1125])
        self.assertEqual([e['rule']['key'] for e in events], ['pce', 'pce'])
        self.assertEqual(events[0]['time'], datetime(2026, 11, 25, 13, 30, tzinfo=timezone.utc))
        self.assertTrue(all(e['calendar_source'] == summary.AUXILIARY_SOURCE for e in events))

    def test_income_or_spending_rows_are_not_turned_into_pce(self):
        rows = [{'country': 'USD', 'title': t, 'date': '2026-11-25T08:30:00-05:00'}
                for t in ('Personal Income m/m', 'Personal Spending m/m')]
        rows.append(dict(CORE_PCE_1125, country='CAD'))
        self.assertEqual(summary.parse_fair_economy_calendar(rows), [])


class WeekCalendarOfficialPceTests(unittest.TestCase):
    def test_1122_path_bls_blocked_lists_official_pce_once(self):
        # 11/22 實際路徑：BLS ICS 與月頁 403 → 公開行事曆；BEA 官方排程可讀。
        events, text = week_text(ff=ff_rows(CORE_PCE_1125, PCE_YOY_1125))
        self.assertEqual(text.count(PCE), 1)
        self.assertIn('**11/25（週三）**', text)
        self.assertIn(f'21:30｜{PCE}', text)
        # GDP 與 PCE 同分鐘公布，彼此不互吃；初領、耐久財與官員談話照舊。
        for line in ('21:30｜美國國內生產毛額（GDP）', '21:30｜美國初領失業救濟金人數', '21:30｜美國耐久財訂單', '聯準會官員談話'):
            self.assertEqual(text.count(line), 1, line)
        self.assertNotIn('12/23', text)
        pce = [e for e in events if e['rule']['key'] == 'pce']
        self.assertEqual(len(pce), 1)
        self.assertEqual(pce[0]['calendar_source'], 'BEA 官方排程')  # 官方優先
        self.assertEqual(next(e for e in events if e['rule']['key'] == 'durable')['calendar_source'], 'Census 官方排程')

    def test_healthy_bls_path_also_lists_official_pce(self):
        # BLS 正常時舊碼只剩 BLS 事件；官方 BEA／Census 列仍要合併。
        events, text = week_text(bls=BLS_ICS, ff=None)
        self.assertIn(f'21:30｜{PCE}', text)
        self.assertIn('21:30｜美國國內生產毛額（GDP）', text)
        self.assertEqual(text.count(PCE), 1)
        self.assertNotIn('消費者物價指數', text)  # 12/10 CPI 不在下週

    def test_not_listed_when_bea_has_no_pce_that_week(self):
        bea = bea_page(('November 25', '8:30 AM', 'GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026'),
                       ('December 23', '8:30 AM', 'Personal Income and Outlays, November 2026'))
        _, text = week_text(ff=ff_rows(), bea=bea)
        self.assertNotIn(PCE, text)
        self.assertIn('21:30｜美國國內生產毛額（GDP）', text)
        self.assertNotIn(WARNING, text)

    def test_rescheduled_out_of_week_drops_stale_public_date(self):
        bea = bea_page(('November 25', '8:30 AM', 'GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026'),
                       ('December 4', '8:30 AM', 'Personal Income and Outlays, October 2026'))
        _, text = week_text(ff=ff_rows(CORE_PCE_1125), bea=bea)
        self.assertNotIn(PCE, text)

    def test_rescheduled_within_week_uses_official_time_only(self):
        bea = bea_page(('November 25', '8:30 AM', 'GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026'),
                       ('November 27', '10:00 AM', 'Personal Income and Outlays, October 2026'))
        events, text = week_text(ff=ff_rows(CORE_PCE_1125), bea=bea)
        self.assertEqual(text.count(PCE), 1)
        self.assertIn(f'**11/27（週五）**\n23:00｜{PCE}', text)
        self.assertNotIn(f'21:30｜{PCE}', text)
        self.assertEqual([e['time'] for e in events if e['rule']['key'] == 'pce'],
                         [datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)])

    def test_official_bea_down_keeps_public_pce_once_and_reports_incomplete(self):
        statuses = []
        with sources(ff=ff_rows(CORE_PCE_1125, PCE_YOY_1125), bea=None):
            events, error = summary.upcoming_events(NOW, 9, statuses)
        self.assertIsNone(error)  # 每日／週報摘要的錯誤語意不變
        self.assertFalse(dict((name, ok) for name, ok, _ in statuses)['BEA 官方排程'])
        self.assertEqual(sum(e['rule']['key'] == 'pce' for e in events), 1)

    def test_summer_time_and_taiwan_day_crossing(self):
        now = datetime(2026, 7, 26, 12, 5, tzinfo=timezone.utc)  # 台灣 7/26（日）20:05，美東夏令
        bea = bea_page(('July 30', '8:30 AM', 'GDP (Advance Estimate), 2nd Quarter 2026'),
                       ('July 30', '8:30 AM', 'Personal Income and Outlays, June 2026'))
        _, text = week_text(now=now, bls=BLS_ICS, bea=bea, g17='monthly releases are issued at 9:15 a.m. 2026: July 17, August 18.')
        self.assertIn('**07/30（週四）**\n02:00｜美國聯準會 FOMC 公告', text)  # 7/29 14:00 EDT
        self.assertIn(f'20:30｜{PCE}', text)
        self.assertEqual(text.count(PCE), 1)

    def test_base_calendar_down_still_sends_nothing(self):
        statuses = []
        with sources(ff=None):
            events, error = summary.upcoming_events(NOW, 9, statuses)
        self.assertEqual(events, [])
        self.assertTrue(error)
        self.assertEqual(statuses, [])


class WeekCalendarScheduledTests(unittest.TestCase):
    def run_sunday(self, **kwargs):
        sent = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_text(json.dumps({'daily': '2026-11-22', 'weekly': '2026-W47'}), encoding='utf-8')
            with patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'DISCORD_WEBHOOK_URL': 'https://discord.invalid/api/webhooks/1/x'}), \
                 patch.object(summary, 'SCHEDULE_STATE', path), \
                 patch('etf_followup.check', return_value=False), \
                 patch('price_move_alert.check', return_value=False), \
                 patch('fed_speech_policy.enrich', side_effect=lambda events, *_: (events, [])), \
                 patch.object(summary, 'send_macro', side_effect=lambda _url, card: sent.append(card)), \
                 sources(**kwargs):
                result = summary.run_scheduled(NOW)
            state = json.loads(path.read_text(encoding='utf-8'))
        return result, sent, state

    def test_sunday_card_lists_pce_without_warning_when_official_sources_answer(self):
        result, sent, state = self.run_sunday(ff=ff_rows(CORE_PCE_1125))
        self.assertEqual(result, ['next_week_calendar'])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['description'].count(f'21:30｜{PCE}'), 1)
        self.assertNotIn(WARNING, sent[0]['description'])
        self.assertEqual(state['next_week_calendar'], '2026-W48')

    def test_sunday_card_marks_incomplete_when_official_schedule_fails(self):
        _, sent, _ = self.run_sunday(ff=ff_rows(CORE_PCE_1125), bea=None)
        self.assertEqual(sent[0]['description'].count(PCE), 1)  # 公開行事曆時間僅作備援
        self.assertIn(WARNING, sent[0]['description'])

    def test_completeness_every_official_row_of_the_week_is_on_the_card(self):
        _, sent, _ = self.run_sunday(ff=ff_rows(CORE_PCE_1125))
        with sources():
            official, _ = notifier.fetch_extended_calendar(NOW)
        _, start, end = nwc.target_week(NOW)
        expected = {(e['time'].astimezone(nwc.TZ).strftime('%H:%M'), e['rule']['name'])
                    for e in official if start <= e['time'].astimezone(nwc.TZ) < end}
        self.assertTrue(expected)
        for clock, name in expected:
            self.assertIn(f'{clock}｜{name}', sent[0]['description'])


class DailyCalendarConsistencyTests(unittest.TestCase):
    def test_week_and_daily_calendar_show_the_same_single_pce_row(self):
        rows = ff_rows(CORE_PCE_1125, PCE_YOY_1125)
        with sources(ff=rows):
            week_events, _ = summary.upcoming_events(NOW, 9)
            with patch.object(notifier, 'PUBLIC_CALENDARS', ('https://calendar.invalid',)), \
                 patch.object(notifier, 'http_json_get', return_value=rows):
                auxiliary, ok = notifier.fetch_public_calendar()
            extended, _ = notifier.fetch_extended_calendar(NOW)
        self.assertTrue(ok)
        daily = notifier.merge_calendar_events(auxiliary, extended)  # notifier.run 在 BLS 403 時的合併
        morning = datetime(2026, 11, 24, 23, 4, tzinfo=timezone.utc)  # 台灣 11/25（三）07:04
        daily_text = '\n'.join(card['description'] for card in slim_policy.calendar_cards(daily, morning))
        self.assertEqual(daily_text.count(PCE), 1)
        self.assertIn(f'**21:30｜{PCE}**', daily_text)
        week_card, _ = nwc.build_card(NOW, week_events)
        self.assertEqual(week_card['description'].count(PCE), 1)
        self.assertIn(f'21:30｜{PCE}', week_card['description'])
        self.assertEqual([e['time'] for e in week_events if e['rule']['key'] == 'pce'],
                         [e['time'] for e in daily if e['rule']['key'] == 'pce' and e['time'].date() == date(2026, 11, 25)])


if __name__ == '__main__':
    unittest.main()
