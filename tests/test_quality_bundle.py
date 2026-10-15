import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import crypto_news_notifier as news
import news_editorial as editorial
import news_policy_context as context
import notification_quality as quality
import notifier
import risk_notifier as risk
import slim_policy as policy
import slim_risk
from source_diagnostics import error_label, remember


class QualityBundleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,16,0,tzinfo=timezone.utc)
        env=patch.dict(os.environ, {'SLIM_NOTIFICATIONS':'1','DISCORD_CRYPTO_NEWS_WEBHOOK_URL':'https://member.invalid','DISCORD_LOG_WEBHOOK_URL':'https://admin.invalid'})
        env.start(); self.addCleanup(env.stop)

    def row(self, title, summary=None, official=False, key='a'):
        return {'id':key,'title':title,'summary':summary or title,'title_zh':'來源發布新消息',
                'summary_zh_points':['來源發布新消息。'],'source':'測試來源','url':'https://example.invalid/'+key,
                'published':self.now,'official':official,'category':{'key':'market','priority':'normal'}}

    def run_news(self, rows, state=None, fail=False):
        state=state if state is not None else {'initialized':True,'seen':{},'pending':[]}
        def send(destination,*_):
            if fail and destination=='https://member.invalid': raise RuntimeError('member send failed')
        with patch.object(news,'load_state',return_value=state),patch.object(news,'save_state'),patch.object(news,'fetch_all',return_value=(rows,[('mock',len(rows),None)])),patch.object(news,'add_translated_title',side_effect=lambda row,*_:dict(row)),patch.object(news,'send_discord',side_effect=send) as sent:
            news.run(self.now)
        return state,sent

    def test_plural_incidents_use_shared_safety_gate(self):
        for title in ('Bitget reports wallet exploits','Ledger reports wallet hacks','Ethereum confirms wallet breaches','USDC depegs reported'):
            row=self.row(title)
            self.assertTrue(editorial.safety_candidate(row),title)
            self.assertTrue(policy.material_news(row),title)
            self.assertIsNotNone(editorial.review_reason(row))

    def test_quarterly_industry_total_not_new_exchange_attack(self):
        row=self.row('Bitget, Liquid exploits push crypto hacks near $1.2B in Q3','Hacken quarterly report totals industry losses.')
        self.assertEqual(editorial.event_kind(row),'retrospective')
        self.assertFalse(policy.material_news(row))
        self.assertFalse(editorial.safety_candidate(row))

    def test_annual_review_background_not_immediate(self):
        for title in ('Annual crypto hack losses report','Crypto hacks quarterly review','Ledger wallet theft retrospective'):
            self.assertFalse(policy.material_news(self.row(title)))

    def test_report_with_new_ongoing_attack_stays_in_safety_inbox(self):
        row=self.row('Quarterly crypto hacks report warns of new ongoing Ledger wallet exploit')
        self.assertTrue(editorial.safety_candidate(row))
        state,sent=self.run_news([row]);self.assertEqual(sent.call_args.args[0],'https://admin.invalid')
        self.assertEqual(state['seen'],{})

    def test_background_attack_cannot_make_policy_urgent(self):
        row=self.row('Crypto tax proposal discussed in France','Officials discussed old wallet exploits in background.')
        self.assertFalse(policy.material_news(row))

    def test_urgent_without_summary_never_bypasses_quality_gate(self):
        row=self.row('SEC approves spot Bitcoin ETF',official=True);row['summary_zh_points']=[]
        state,sent=self.run_news([row]);self.assertEqual(sent.call_args.args[0],'https://admin.invalid')
        self.assertEqual(state['seen'],{});self.assertNotIn('digest_progress',state)

    def test_urgent_bad_title_and_numbers_go_to_review(self):
        row=self.row('SEC approves spot Bitcoin ETF',official=True);row['title_zh']='核准1000檔ETF'
        state,sent=self.run_news([row]);self.assertEqual(sent.call_args.args[0],'https://admin.invalid')
        self.assertEqual(state['pending'],[])

    def test_urgent_overflow_without_copy_cannot_enter_digest(self):
        rows=[self.row('SEC approves spot Bitcoin ETF',official=True,key=str(i)) for i in range(6)]
        for row in rows: row['summary_zh_points']=[]
        state,sent=self.run_news(rows)
        self.assertTrue(all(call.args[0]=='https://admin.invalid' for call in sent.call_args_list))
        self.assertFalse(state['seen']);self.assertFalse(state['pending'])

    def test_legacy_pending_bad_urgent_migrates_to_review(self):
        row=self.row('SEC approves spot Bitcoin ETF',official=True);row.update(published=self.now.isoformat(),category='etf',summary_zh_points=[])
        state,sent=self.run_news([] ,{'initialized':True,'seen':{},'pending':[row]})
        self.assertEqual(sent.call_args.args[0],'https://admin.invalid');self.assertEqual(state['pending'],[])

    def test_review_not_repeated_and_corrected_item_can_deliver(self):
        row=self.row('SEC approves spot Bitcoin ETF',official=True);row['summary_zh_points']=[]
        state,_=self.run_news([row]);_,sent=self.run_news([row],state);sent.assert_not_called()
        row['summary_zh_points']=['官方核准比特幣ETF。']
        _,sent=self.run_news([row],state);self.assertEqual(sent.call_args.args[0],'https://member.invalid')
        self.assertIn(row['id'],state['seen'])

    def test_failed_member_delivery_does_not_mark_seen(self):
        row=self.row('SEC approves spot Bitcoin ETF',official=True);state={'initialized':True,'seen':{},'pending':[]}
        with self.assertRaises(RuntimeError):self.run_news([row],state,fail=True)
        self.assertFalse(state['seen'])

    def test_policy_without_effective_date_is_not_member_ready(self):
        row=self.row('Russia will soon ban peer-to-peer Bitcoin trading','The central bank confirmed new rules.')
        self.assertIn('日期',quality.digest_exclusion_reason(row))
        _,sent=self.run_news([row]);self.assertEqual(sent.call_args.args[0],'https://admin.invalid')

    def test_policy_complete_date_shown_as_source_claim_not_publication(self):
        row=self.row('Russia will ban peer-to-peer Bitcoin trading','Rules take effect on July 1, 2027.')
        self.assertIsNone(quality.digest_exclusion_reason(row))
        self.assertIn('2027/07/01',policy.news_card(row,now=self.now)['description'])
        self.assertIn('媒體原文所述',policy.news_card(row,now=self.now)['description'])
        self.assertFalse(policy.material_news(row))

    def test_spelled_out_source_date_can_be_chinese_without_changing_date(self):
        row=self.row('Russia will ban crypto','Rules take effect on July 1, 2027.')
        row['summary_zh_points']=['規則將於2027年7月1日開始適用。']
        self.assertIsNone(quality.digest_exclusion_reason(row))
        self.assertNotIn('來源未提供',policy.news_card(row,now=self.now)['description'])
        with self.assertRaises(ValueError):quality.checked_translation(row['summary'],'規則將於2027年1月7日開始適用。')

    def test_review_and_failure_previews_never_receive_automatic_green_status(self):
        from quality_bundle_preview import cards
        rendered={row['key']:json.dumps(row['embed'],ensure_ascii=False) for row in cards()}
        for key in ('新資安與摘要缺少留管理區','來源原因與最後成功','備援範圍與日期'):
            self.assertNotIn('正常取得',rendered[key])
        self.assertNotIn('來源未提供',rendered['政策列明日期與媒體歸屬'])

    def test_deadline_not_mislabelled_effective_start(self):
        row=self.row('Russia bans peer-to-peer crypto trades','Residents can trade until July 1, 2027.')
        self.assertIn('截止日期',context.policy_context(row)['copy'])

    def test_conflicting_dates_unknown_scope_and_invalid_dates_wait(self):
        for title,summary in (
            ('Russia bans crypto','Rules from July 1, 2027 until July 1, 2028.'),
            ('Regulator bans crypto','Rules from July 1, 2027.'),
            ('Russia bans crypto','Rules from February 30, 2027.'),
        ):
            self.assertIsNotNone(context.policy_context(self.row(title,summary))['reason'])

    def test_policy_announcement_date_not_guessed_as_effective_date(self):
        row=self.row('Russia bans crypto','FAQ published October 12, 2026.')
        self.assertNotIn('date',context.policy_context(row))

    def test_money_suffix_and_prefix_normalized_without_changing_amounts(self):
        for translated in ('損失12億$','損失$12億','損失12億$美元'):
            result=quality.checked_translation('Losses total $1.2 billion',translated)
            self.assertIn('12億美元',result);self.assertNotIn('$',result)

    def test_other_currency_not_relabelled_as_us_dollars(self):
        with self.assertRaises(ValueError):quality.checked_translation('Losses C$1.2 billion','損失12億$')
        self.assertEqual(quality.checked_translation('Losses C$1.2 billion','損失12億加幣'),'損失12億加幣')

    def test_outflow_price_mistranslation_blocked_but_flow_allowed(self):
        source='Bitcoin ETFs shed $261M as XRP funds buck weekly outflow trend'
        with self.assertRaises(ValueError):quality.checked_translation(source,'比特幣ETF下跌2.61億美元')
        self.assertIn('淨流出',quality.checked_translation(source,'比特幣ETF淨流出2.61億美元'))

    def test_ambiguous_exploit_translation_waits_for_review(self):
        with self.assertRaises(ValueError):quality.checked_translation('Crypto exploits push hacks losses','加密利用推高駭客損失')

    def test_snapshot_expiry_future_date_and_dst(self):
        events,verified=notifier.validated_bls_snapshot(self.now)
        self.assertEqual(verified,'2026-10-16');self.assertEqual(len(events),7)
        self.assertIn('2026-11-10T13:30:00+00:00',[e['time'].isoformat() for e in events])
        with self.assertRaisesRegex(ValueError,'31天'):notifier.validated_bls_snapshot(self.now+timedelta(days=33))
        with self.assertRaises(ValueError):notifier.validated_bls_snapshot(self.now-timedelta(days=2))

    def test_bls_html_abbreviated_month_and_explicit_next_year(self):
        html='<table><tr><td>October 2026</td><td>Nov. 10, 2026</td><td>08:30 AM</td></tr><tr><td>December 2026</td><td>Jan. 13, 2027</td><td>08:30 AM</td></tr></table>'
        with patch.object(notifier,'http_text',return_value=html),patch.object(notifier,'BLS_HTML_SCHEDULES',{'cpi':'https://example.invalid'}):
            rows=notifier.fetch_bls_html_calendar(self.now)
        self.assertEqual([r['time'].year for r in rows],[2026,2027])

    def test_bybit_missing_list_cannot_be_healthy_empty(self):
        for payload in ({'retCode':0,'result':{}},{'retCode':0,'result':{'list':None}}):
            with patch.object(risk,'get_json',return_value=payload),self.assertRaises(ValueError):risk.bybit_incidents()
        with patch.object(risk,'get_json',return_value={'retCode':0,'result':{'list':[]}}):self.assertEqual(risk.bybit_incidents(),[])

    def test_public_error_label_never_includes_exception_secret(self):
        exc=HTTPError('https://example.invalid/?token=secret',403,'secret',{},None)
        self.assertEqual(error_label(exc),'HTTP 403')

    def test_http403_not_retried_or_rerouted(self):
        exc=HTTPError('https://api.bybit.com/v5/system/status',403,'Forbidden',{},None)
        with patch.object(risk,'urlopen',side_effect=exc) as request,self.assertRaises(HTTPError):risk.get_json(risk.BYBIT_STATUS_URL)
        request.assert_called_once()

    def test_transient_http_failure_retries_same_endpoint(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False);response.read.return_value=b'{"ok": true}'
        with patch.object(risk,'urlopen',side_effect=[HTTPError('https://example.invalid',503,'busy',{},None),response]) as request,patch('time.sleep'):
            self.assertTrue(risk.get_json('https://example.invalid')['ok']);self.assertEqual(request.call_count,2)

    def test_last_success_kept_when_source_fails_without_claiming_recovery(self):
        health={};remember(health,'Bybit',True,self.now,count=0)
        failed=remember(health,'Bybit',False,self.now+timedelta(minutes=5),'HTTP 403')
        self.assertEqual(failed['last_success'],self.now.isoformat());self.assertFalse(failed['ok']);self.assertEqual(failed['reason'],'HTTP 403')

    def test_legacy_success_timestamp_migrates_on_first_failure(self):
        health={'Bybit':{'ok':True,'checked':self.now.isoformat(),'count':0}}
        failed=remember(health,'Bybit',False,self.now+timedelta(minutes=5),'HTTP 403')
        self.assertEqual(failed['last_success'],self.now.isoformat())

    def test_missing_coinbase_envelope_is_not_a_healthy_empty_feed(self):
        state={};api=SimpleNamespace(load=lambda:state,save=Mock(),get_json=lambda *_:{'error':'unavailable'},STATUS_URL='https://example.invalid',bybit_incidents=lambda:[],critical_official_notices=lambda:[],send=Mock())
        with patch.object(slim_risk,'price_sources',return_value={coin:{'CoinGecko':1,'Kraken':1} for coin in slim_risk.COINS}),patch('notifier.send_discord'):
            slim_risk.monitor(api,'https://member.invalid',self.now)
        self.assertFalse(state['slim_service_sources']['Coinbase']['ok']);api.send.assert_not_called()

    def test_price_stale_wide_spread_and_nan_not_used(self):
        def get(url):
            if 'coingecko' in url:return {'tether':{'usd':float('nan'),'last_updated_at':self.now.timestamp()},'usd-coin':{'usd':1,'last_updated_at':self.now.timestamp()-601},'dai':{'usd':1,'last_updated_at':self.now.timestamp()}}
            return {'error':[],'result':{'DAIUSD':{'a':['1.02'],'b':['.98']},'USDCUSD':{'a':['1.0'],'b':['.999']}}}
        details={};prices=slim_risk.price_sources(SimpleNamespace(get_json=get),self.now,details)
        self.assertNotIn('CoinGecko',prices['USDT']);self.assertNotIn('CoinGecko',prices['USDC']);self.assertNotIn('Kraken',prices['DAI'])
        self.assertIn('10分鐘',details['USDC:CoinGecko']['reason']);self.assertIn('0.5%',details['DAI:Kraken']['reason'])

    def test_kraken_bulk_error_isolated_by_pair_without_double_counting(self):
        def get(url):
            if 'coingecko' in url:return {key:{'usd':1,'last_updated_at':self.now.timestamp()} for key in slim_risk.COINS.values()}
            if ',' in url:return {'error':['unknown pair'],'result':{}}
            coin=next(coin for coin in slim_risk.COINS if f'pair={coin}USD' in url)
            return {'error':[],'result':{coin+'USD':{'a':['1.0'],'b':['.999']}}}
        prices=slim_risk.price_sources(SimpleNamespace(get_json=get),self.now)
        self.assertTrue(all(set(row)=={'CoinGecko','Kraken'} for row in prices.values()))


if __name__=='__main__':unittest.main()
