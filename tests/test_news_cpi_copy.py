import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import cpi_release
import crypto_news_notifier as news
import notification_quality as quality
import notifier
from notification_format import apply_delivery_format


class NewsCpiCopyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        self.env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS':'1','DISCORD_CRYPTO_NEWS_WEBHOOK_URL':'https://discord.invalid'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def article(self, key='a'):
        return {'id':key,'title':'Bitcoin price holds steady','title_zh':'比特幣價格維持穩定',
                'summary':'Bitcoin price holds steady.','summary_zh_points':['比特幣價格維持穩定。'],
                'published':self.now,'url':'https://example.invalid/'+key,'source':'示例來源','official':False,
                'category':{'key':'market','priority':'normal'}}

    def run_news(self, rows, state, now=None):
        with patch.object(news,'load_state',return_value=state), patch.object(news,'save_state'), \
             patch.object(news,'fetch_all',return_value=(rows,[('mock',len(rows),None)])), \
             patch.object(news,'add_translated_title',side_effect=lambda row,*_:dict(row)), patch.object(news,'send_discord') as send:
            news.run(now or self.now)
        return send

    def test_bad_high_ranked_news_does_not_displace_readable_news_or_consume_quota(self):
        bad = [self.article('bad'+str(i)) for i in range(5)]
        titles=['Regulator publishes final stablecoin redemption policy', 'Agency issues new crypto custody regulation',
                'Court reviews market transparency policy', 'Government announces digital asset reporting regulation',
                'Authority changes exchange licensing policy']
        for row,title in zip(bad,titles):
            row.update(title=title, title_zh='', official=True)
        good = self.article('good')
        state={'initialized':True,'seen':{},'pending':[]}
        send=self.run_news(bad+[good],state)
        send.assert_called_once()
        self.assertEqual(set(state['seen']),{'good'})
        self.assertEqual(len(state['pending']),5)
        self.assertEqual(len(state['digest_progress']['ids']),1)
        self.assertEqual(len(state['digest_quality']['excluded']),5)
        self.assertNotIn('待確認',json.dumps(send.call_args.args[1],ensure_ascii=False))

    def test_no_qualified_news_keeps_slot_available_for_later_good_news(self):
        bad=self.article('bad');bad['summary_zh_points']=[]
        state={'initialized':True,'seen':{},'pending':[]}
        self.run_news([bad],state).assert_not_called()
        self.assertNotIn('last_digest_slot',state)
        self.assertNotIn('bad',state['seen'])
        self.run_news([bad,self.article('good')],state,self.now+timedelta(minutes=5)).assert_called_once()

    def test_urgent_untranslated_incident_keeps_conservative_fast_path(self):
        row=self.article();row.update(title='Exchange confirms withdrawals halted after security breach',title_zh='',summary_zh_points=[])
        state={'initialized':True,'seen':{},'pending':[]}
        send=self.run_news([row],state,self.now-timedelta(hours=1))
        send.assert_called_once()
        self.assertIn('a',state['seen'])
        self.assertIn('中文標題待確認',json.dumps(send.call_args.args,ensure_ascii=False))

    def test_placeholder_and_day_ahead_teaser_not_qualified(self):
        row=self.article();row['summary_zh_points']=['中文摘要待確認，請閱讀原文。']
        self.assertIsNotNone(quality.digest_exclusion_reason(row))
        row.update(summary='Your day-ahead look for Oct. 14, 2026',summary_zh_points=['你的2026年10月14日導讀。'])
        self.assertEqual(quality.digest_exclusion_reason(row),'摘要僅為導讀')

    def test_corporate_treasury_corrected_without_changing_facts(self):
        source='Strive holds 32,773 BTC as it expands its treasury through equity financing.'
        rendered=quality.checked_translation(source,'Strive持有32,773 BTC，透過股權融資擴大其財政部。')
        self.assertIn('資產儲備',rendered)
        self.assertEqual(quality.numeric_values(rendered),quality.numeric_values(source))

    def test_government_treasury_not_replaced_and_mixed_context_rejected(self):
        self.assertEqual(quality.checked_translation('U.S. Treasury issues bonds','美國財政部發債'),'美國財政部發債')
        with self.assertRaises(ValueError):
            quality.checked_translation('A company expands its treasury after a U.S. Treasury notice','財政部發布消息，公司擴大財政部。')

    def test_currency_warrants_and_duplicate_acronym_keep_units(self):
        source='SEC: Strive reports $208 million in warrant exercises as Bitcoin holdings jump 11%.'
        translated='SEC(SEC)：Strive報告認股權證活動達$ 2.08 億，Bitcoin持有量增加11 %。'
        rendered=quality.checked_translation(source,translated)
        self.assertIn('認股權證行使金額',rendered)
        self.assertIn('2.08億美元',rendered)
        self.assertNotIn('SEC(SEC)',rendered)
        self.assertEqual(quality.numeric_values(source),quality.numeric_values(rendered))
        self.assertNotIn('美元',quality.checked_translation('Company raises C$2 million','公司籌得C$200萬'))

    def cpi(self):
        return {'title':'Consumer Price Index - September 2026','summary':'','reference_period':'2026-M09',
                'rule':{'key':'cpi','name':'美國消費者物價指數（CPI）','source':'https://www.bls.gov/cpi/'},
                'published':self.now,'url':'https://www.bls.gov/news.release/cpi.nr0.htm',
                'cpi_metrics':{'monthly':.6,'annual':3.7,'monthly_seasonally_adjusted':True,'annual_unadjusted':True}}

    def test_complete_cpi_without_consensus_is_not_partial(self):
        row=self.cpi();before=copy.deepcopy(row)
        card=apply_delivery_format(notifier.release_embed(row,self.now,detected_at=self.now+timedelta(minutes=4)),'macro_alerts')
        text=json.dumps(card,ensure_ascii=False)
        for value in ('2026/09','月增率（季調）','年增率（未季調）','0.6%','3.7%','主數據與口徑完整','市場預期未納入'):
            self.assertIn(value,text)
        self.assertNotIn('部分資料缺少',text)
        self.assertEqual(row,before)
        self.assertEqual(sum(f['name']=='🩺 資料狀態' for f in card['fields']),1)

    def test_cpi_missing_annual_value_is_explicit_without_inventing_zero(self):
        row=self.cpi();row['cpi_metrics']['annual']=None
        card=apply_delivery_format(notifier.release_embed(row),'macro_alerts')
        text=json.dumps(card,ensure_ascii=False)
        self.assertIn('尚未確認：年增率',text)
        self.assertNotIn('0.0%',text)
        self.assertIn('0.6%',text)

    def test_cpi_month_never_inferred_from_publication_date(self):
        row=self.cpi();row.pop('reference_period');row['title']='Consumer Price Index'
        copy_text,missing=cpi_release.details(row)
        self.assertIn('資料月份',missing)
        self.assertNotIn('2026/10',copy_text)

    def test_actual_bls_intro_uses_annual_value_not_previous_month(self):
        row=self.cpi();row.pop('cpi_metrics');row.pop('reference_period')
        row['summary']='The Consumer Price Index for All Urban Consumers (CPI-U) increased 0.6 percent on a seasonally adjusted basis in September after rising 0.4 percent in August. Over the last 12 months, the all items index increased 3.7 percent before seasonal adjustment.'
        text,missing=cpi_release.details(row)
        self.assertEqual(missing,[])
        self.assertIn('0.6%',text);self.assertIn('3.7%',text);self.assertIn('前值 0.4%',text)

    def test_negative_cpi_change_and_unadjusted_basis_are_preserved(self):
        row=self.cpi();row.pop('cpi_metrics')
        row['summary']='The index fell 0.2 percent not seasonally adjusted. The all items index increased 2.7 percent over the last 12 months before seasonal adjustment.'
        text,missing=cpi_release.details(row)
        self.assertIn('月增率（未季調）',text)
        self.assertIn('-0.2%',text)
        self.assertIn('2.7%',text)
        self.assertEqual(missing,[])

    def test_cpi_does_not_borrow_monthly_basis_from_annual_sentence(self):
        row=self.cpi();row.pop('cpi_metrics')
        row['summary']='The index increased 0.6 percent in September. Over the last 12 months, the all items index increased 3.7 percent before seasonal adjustment.'
        text,missing=cpi_release.details(row)
        self.assertIn('月增率（口徑未確認）',text)
        self.assertIn('年增率（未季調）',text)
        self.assertEqual(missing,['月增率季調口徑'])

    def test_cpi_api_retains_reference_period_and_direct_data_sources(self):
        series=[]
        for key in notifier.BLS_API_GROUPS['cpi']:
            series.append({'seriesID':key,'data':[{'year':'2026','period':'M09','value':'103.7'},
                          {'year':'2026','period':'M08','value':'103.1'},{'year':'2025','period':'M09','value':'100'}]})
        payload={'status':'REQUEST_SUCCEEDED','Results':{'series':series}}
        with patch.object(notifier,'http_json_post',return_value=payload):
            rows=notifier.fetch_bls_api_releases(self.now,{'bls_api':{'cpi':{'signature':'old'}}})
        self.assertEqual(rows[0]['reference_period'],'2026-M09')
        self.assertEqual(rows[0]['cpi_metrics']['annual_unadjusted'],True)
        card=notifier.release_embed(rows[0])
        self.assertIn('CUSR0000SA0',json.dumps(card))
        self.assertIn('CUUR0000SA0',json.dumps(card))
        series[0]['data'][1]['period']='M07'
        with patch.object(notifier,'http_json_post',return_value=payload):
            self.assertEqual(notifier.fetch_bls_api_releases(self.now,{'bls_api':{'cpi':{'signature':'old'}}}),[])
        series[0]['data'][1]['period']='M08'
        series[1]['data'][0]['period']='M08'
        with patch.object(notifier,'http_json_post',return_value=payload):
            self.assertEqual(notifier.fetch_bls_api_releases(self.now,{'bls_api':{'cpi':{'signature':'old'}}}),[])

    def test_late_cpi_still_separates_schedule_and_detection(self):
        card=notifier.release_embed(self.cpi(),self.now,detected_at=self.now+timedelta(minutes=25))
        self.assertIn('補發',card['title'])
        self.assertIn('官方排定時間',json.dumps(card,ensure_ascii=False))
        self.assertIn('機器人發現',json.dumps(card,ensure_ascii=False))
