import copy
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
import etf_followup as f
from etf_source_context import parse
from market_brief_v2 import etf_lines


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,28,0,tzinfo=timezone.utc)
        self.html='<tr><td>26 Oct 2026</td><td>10</td><td>(2)</td><td>8</td></tr><tr><td>27 Oct 2026</td><td>-</td><td>-</td><td>0.0</td></tr>'
        self.row=parse(self.html)
        self.ready=parse(self.html.replace('<td>-</td><td>-</td><td>0.0','<td>20</td><td>(5)</td><td>15'))
        self.ready['retrieved_at']=self.now.isoformat()
        self.state={}
        self.seed=self.now-timedelta(hours=1)
        f.remember(self.state,{'etf_status':f.capture({'etf':self.row,'eth_etf':self.row},self.seed)},self.seed)

    def test_latest_pending_kept_with_previous_explicitly_dated(self):
        text=etf_lines({'etf':self.row},False)
        for s in ('交易日：10/27','等候數據更新','前次完整資料','交易日 10/26','非本交易日'):self.assertIn(s,text)
        self.assertNotIn('淨流入0',text)

    def test_missing_total_and_invalid_components_never_zero(self):
        for value in ('-','N/A','NaN'):
            row=parse(self.html.replace('<td>0.0</td></tr>',f'<td>{value}</td></tr>'))
            self.assertIsNone(row['net_flow_musd'])
            self.assertFalse(f.ready(row))
        bad=parse(self.html.replace('<td>-</td><td>-</td><td>0.0','<td>100</td><td>20</td><td>0.0'))
        self.assertIn('不符',bad['source_issue'])
        self.assertFalse(f.ready(bad))

    def test_both_assets_complete_combined_once(self):
        send,persist=Mock(),Mock()
        self.assertTrue(f.check(self.state,self.now,lambda _:self.ready,send,persist))
        self.assertEqual(send.call_count,1)
        self.assertEqual(len(self.state['etf_completed']),2)
        self.assertFalse(f.check(self.state,self.now+timedelta(hours=1),lambda _:self.ready,send,persist))
        self.assertEqual(send.call_count,1)

    def test_separate_assets_each_complete_once_without_replaying_first(self):
        send,persist=Mock(),Mock()
        f.check(self.state,self.now,lambda s:self.ready if s=='BTC' else self.row,send,persist)
        self.assertEqual(len(self.state['etf_pending']),1)
        later=self.now+timedelta(minutes=16)
        ready=dict(self.ready,retrieved_at=later.isoformat())
        f.check(self.state,later,lambda _:ready,send,persist)
        self.assertEqual(send.call_count,2)
        self.assertNotIn('BTC ETF',send.call_args.args[0]['description'])

    def test_send_failure_does_not_consume_pending_or_mark_complete(self):
        original=copy.deepcopy(self.state)
        with self.assertRaises(OSError):
            f.check(self.state,self.now,lambda _:self.ready,Mock(side_effect=OSError('send failed')),Mock())
        self.assertEqual(self.state['etf_pending'],original['etf_pending'])
        self.assertFalse(self.state['etf_completed'])

    def test_missing_stale_other_day_and_fetch_failure_remain_pending(self):
        for row in (self.row,dict(self.ready,date='2026-10-26'),dict(self.ready,retrieved_at=(self.now-timedelta(hours=1)).isoformat())):
            state=copy.deepcopy(self.state);send=Mock()
            self.assertFalse(f.check(state,self.now,lambda _:row,send,Mock()))
            send.assert_not_called()
        state=copy.deepcopy(self.state);send=Mock()
        self.assertFalse(f.check(state,self.now,Mock(side_effect=OSError('403')),send,Mock()))
        send.assert_not_called()

    def test_no_old_state_seed_and_expired_tasks_do_not_send(self):
        send=Mock()
        self.assertFalse(f.check({},self.now,lambda _:self.ready,send,Mock()))
        self.assertFalse(f.check(self.state,self.now+timedelta(days=2),lambda _:self.ready,send,Mock()))
        send.assert_not_called()

    def test_complete_zero_is_valid_but_partial_nonzero_is_not_complete(self):
        zero=dict(self.ready,net_flow_musd=0)
        self.assertTrue(f.ready(zero))
        self.assertFalse(f.ready(dict(self.ready,unreported_components=1)))

    def test_ready_daily_brief_cancels_same_day_completion_task(self):
        f.remember(self.state,{'etf_status':{'BTC':{'date':'2026-10-27','pending':False}}},self.now)
        self.assertNotIn('BTC:2026-10-27',self.state['etf_pending'])
        self.assertIn('BTC:2026-10-27',self.state['etf_completed'])

    def test_source_failure_in_new_brief_waits_for_explicit_recovered_trade_date(self):
        state={};send=Mock()
        f.remember(state,{'etf_status':f.capture({},self.seed)},self.seed)
        self.assertEqual(len(state['etf_pending']),2)
        self.assertTrue(f.check(state,self.now,lambda _:self.ready,send,Mock()))
        self.assertEqual(send.call_count,1)
        self.assertIn('2026-10-27',send.call_args.args[0]['description'])
        self.assertFalse(state['etf_pending'])
