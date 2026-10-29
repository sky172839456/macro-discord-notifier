"""Isolated regression for all eleven member results; never sends to Discord."""
import copy,os,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import notifier as n
import slim_policy
from macro_result_integrity import details,enrich,fomc
import durable_release as durable

FIX=Path(__file__).parent/'fixtures'
NOW=datetime(2026,10,29,0,tzinfo=timezone.utc)


def row(key,text='',**kw):
    return {'id':'fixture','rule':next(x for x in n.EVENT_RULES if x['key']==key),
            'title':'','summary':text,'url':'https://example.invalid',
            'published':NOW,**kw}


class ResultIntegrityTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{'SLIM_NOTIFICATIONS':'1'})
        env.start();self.addCleanup(env.stop)
        self.fed=(FIX/'fomc_20261028.txt').read_text(encoding='utf-8')
        self.pce=(FIX/'pce_20260930.txt').read_text(encoding='utf-8')
        self.table=(FIX/'durable_20261027_table1a.txt').read_text(encoding='utf-8')
        self.page=(FIX/'durable_20261027.html').read_text(encoding='utf-8')

    def test_every_enabled_result_blocks_headline_and_unrelated_number(self):
        self.assertEqual(len(slim_policy.RESULT_EVENTS),11)
        for key in slim_policy.RESULT_EVENTS:
            for text in ('Federal Reserve issues FOMC statement','Report says inflation target2percent,2026.',''):
                with self.subTest(key=key,text=text):
                    item=row(key,text)
                    self.assertTrue(n.release_critical_missing(item))
                    with patch.object(n,'send_discord') as send:
                        self.assertFalse(n.deliver_release('https://member.invalid',item,None,None,NOW,False,{}))
                    send.assert_not_called()

    def test_live_fomc_maintain_range_vote_and_minorities(self):
        text,missing=details(row('fomc',self.fed))
        self.assertFalse(missing)
        for value in ('維持利率不變','3.75%～4.00%','0 基點','10票贊成、2票反對','偏好升息25基點','不是本次通過'):
            self.assertIn(value,text)
        self.assertIn('通膨仍偏高',text)

    def test_fraction_raise_lower_are_actions_not_inflation_targets(self):
        for action,word in [('raise','升息'),('lower','降息')]:
            text,missing=fomc(row('fomc',f'The Committee decided to {action} the target range for the federal funds rate by 1/4 percentage point to 3-1/2 to 3-3/4 percent. Inflation goal2percent.'))
            self.assertFalse(missing);self.assertIn(word,text);self.assertIn('25 基點',text);self.assertIn('3.50%～3.75%',text)
        self.assertTrue(fomc(row('fomc','Voting against the action were members who preferred to raise the target range for the federal funds rate by 1/4 percentage point to 4 to 4-1/4 percent.'))[1])

    def test_fomc_invalid_or_amountless_decision_is_blocked(self):
        for text in ('The Committee decided to maintain the target range for the federal funds rate at 4 to 3 percent.',
                     'The Committee decided to raise the target range for the federal funds rate to 4 to 4-1/4 percent.',
                     'Inflation remains elevated at2percent. Federal Reserve issues FOMC statement.'):
            self.assertTrue(details(row('fomc',text))[1])

    def test_live_pce_anchors_price_indexes_not_income_spending_or_saving(self):
        text,missing=details(row('pce',self.pce))
        self.assertFalse(missing)
        for value in ('2026/08','PCE月增率**\n本次 **+0.3%**','核心PCE月增率**\n本次 **+0.2%**','PCE年增率**\n本次 **+3.4%**','核心PCE年增率**\n本次 **+3.0%**'):
            self.assertIn(value,text)
        for value in ('+0.9%','+4.1%','年增率**　+0.6%'):
            self.assertNotIn(value,text)

    def test_pce_requires_all_four_metrics_and_same_period(self):
        for bad in (self.pce.replace('From the same month one year ago','Annual note,'),
                    self.pce.replace('the PCE price index for August','the PCE price index for September'),
                    'Personal Income and Outlays, August2026. Income increased0.2percent, PCE increased0.9percent.'):
            self.assertTrue(details(row('pce',bad))[1])

    def test_second_official_pce_release_with_also_preserves_core_index(self):
        source=(FIX/'pce_20260826.txt').read_text(encoding='utf-8')
        text,missing=details(row('pce',source))
        self.assertFalse(missing)
        for value in ('2026/07','核心PCE月增率**\n本次 **+0.2%**','PCE年增率**\n本次 **+3.7%**','核心PCE年增率**\n本次 **+3.3%**'):
            self.assertIn(value,text)

    def test_pce_direction_is_preserved(self):
        text,missing=details(row('pce',self.pce.replace('PCE price index for August increased','PCE price index for August decreased').replace('PCE price index 0.1 0.3','PCE price index 0.1 -0.3')))
        self.assertFalse(missing);self.assertIn('-0.3%',text);self.assertIn('-3.4%',text)

    def test_jobs_api_source_metadata_and_units(self):
        item=row('jobs','Payroll employment changed +100 thousand; unemployment rate was4.1percent.',
                 id='bls-api-jobs-2026-M09-x',reference_period='2026-M09',
                 jobs_metrics={'payroll':100000,'unemployment':4.1,'previous_payroll':120000,'previous_unemployment':4.0})
        text,missing=details(item)
        self.assertFalse(missing)
        for value in ('2026/09','+10.0 萬人','4.1%','+12.0 萬人'):self.assertIn(value,text)
        bad=copy.deepcopy(item);bad['jobs_metrics']['unemployment']=float('nan')
        self.assertTrue(details(bad)[1])
        self.assertTrue(details(dict(item,id='rss-jobs'))[1])

    def test_jobs_api_mismatched_and_nonadjacent_months_do_not_form_result(self):
        def data(year,period,value):return {'year':str(year),'period':period,'value':str(value)}
        good={'CES0000000001':[data(2026,'M09',159000),data(2026,'M08',158900),data(2026,'M07',158800)],
              'LNS14000000':[data(2026,'M09',4.1),data(2026,'M08',4.0)]}
        def run(values,state):
            response={'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':k,'data':v} for k,v in values.items()]}}
            with patch.object(n,'http_json_post',return_value=response):
                return n.fetch_bls_api_releases(NOW,state)
        state={'bls_api':{'jobs':{'reference':'2026-M08','signature':'old'}}}
        rows=run(good,copy.deepcopy(state))
        job=next(x for x in rows if x['rule']['key']=='jobs')
        self.assertEqual(details(job)[1],[])
        self.assertIn('+10.0 萬人',details(job)[0])
        for series,index,period in [('LNS14000000',0,'M08'),('CES0000000001',1,'M07')]:
            bad=copy.deepcopy(good);bad[series][index]['period']=period
            self.assertFalse(run(bad,copy.deepcopy(state)))
        repeated={'bls_api':{'jobs':{'reference':'2026-M09','signature':'old'}}}
        self.assertFalse(run(good,repeated))

    def test_jobs_raw_release_requires_both_headline_values_period_and_basis(self):
        text='THE EMPLOYMENT SITUATION – SEPTEMBER2026. Total nonfarm payroll employment increased by 100,000 in September. The unemployment rate was4.1 percent. All data in this release are seasonally adjusted.'
        text=text.replace('SEPTEMBER2026','SEPTEMBER 2026').replace('was4.1','was 4.1')
        self.assertFalse(details(row('jobs',text))[1])
        for bad in (text.replace('in September','in August'),text.replace('All data in this release are seasonally adjusted.',''),text.replace('100,000','unavailable')):
            self.assertTrue(details(row('jobs',bad))[1])

    def test_claims_actual_week_and_source_date_are_required(self):
        item=row('claims',(FIX/'claims_20261022_wrapped.txt').read_text(encoding='utf-8'),
                 url='https://oui.doleta.gov/press/2026/102226.pdf',
                 published=datetime(2026,10,22,12,30,tzinfo=timezone.utc))
        text,missing=details(item)
        self.assertFalse(missing)
        for value in ('2026/10/17','194,000 人','199,000 → 200,000'):self.assertIn(value,text)
        for bad in (dict(item,summary='initial claims was194,000.'),dict(item,url='https://example.invalid/102226.pdf'),
                    dict(item,summary=item['summary'].replace('October 17','January 17'))):
            self.assertTrue(details(bad)[1])

    def test_durable_official_table_does_not_select_unadjusted_or_ex_transport(self):
        table=durable.table_metrics(self.table)
        self.assertEqual((table['year'],table['month'],table['current'],table['previous']),(2026,9,1.8,0.1))
        item=row('durable',url='https://www.census.gov/manufacturing/m3/adv/current/index.html')
        result=enrich(item,lambda _:self.page,lambda _:(FIX/'durable_20261027_table1a.pdf').read_bytes())
        self.assertFalse(details(result)[1])
        for value in ('2026/09','+1.8%','+0.1%','季調、未扣除價格變動'):self.assertIn(value,details(result)[0])
        self.assertEqual(item['summary'],'')
        self.assertTrue(details(dict(result,summary=result['summary'].replace('1.8 percent','2.8 percent')))[1])

    def test_durable_invalid_table_basis_levels_date_and_missing_attachment_block(self):
        for bad in (self.table.replace('Seasonally Adjusted Not Seasonally Adjusted','Not Seasonally Adjusted Seasonally Adjusted'),
                    self.table.replace('345,371','999,371'),
                    self.table.replace('October 27, 2026','October 27, 2025'),
                    self.table.replace('Estimates are not adjusted for price changes','')):
            with self.assertRaises(ValueError):durable.table_metrics(bad)
        item=row('durable',self.page,url='https://www.census.gov/manufacturing/m3/adv/current/index.html')
        result=enrich(item,lambda _:self.page,lambda _:b'not a PDF')
        self.assertTrue(details(result)[1])
        self.assertTrue(details(enrich(item,lambda _:self.page.replace('table1a.pdf','missing.pdf'),lambda _:b''))[1])

    def test_enrich_same_official_release_only_failure_never_claims_recovery(self):
        item=row('fomc','Federal Reserve issues FOMC statement',url='https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm')
        before=copy.deepcopy(item)
        self.assertFalse(details(enrich(item,lambda _:self.fed,lambda _:b''))[1])
        self.assertEqual(item,before)
        def fail(_):raise OSError('fixture source unavailable')
        self.assertEqual(enrich(item,fail,fail),item)
        with patch('builtins.print'):
            external=dict(item,url='https://example.invalid/release')
            self.assertEqual(enrich(external,fail,fail),external)

    def test_gate_and_render_agree_on_validated_result(self):
        for key,text in [('fomc',self.fed),('pce',self.pce)]:
            item=row(key,text)
            self.assertFalse(n.release_critical_missing(item))
            self.assertIn(details(item)[0],n.release_embed(item)['description'])
            with patch.object(n,'send_discord') as send:
                self.assertTrue(n.deliver_release('https://member.invalid',item,None,None,NOW,False,{}))
            send.assert_called_once()

    def test_zero_pce_and_basis_point_fomc_have_real_meaning(self):
        text=self.pce.replace('PCE price index for August increased 0.3 percent','PCE price index for August was unchanged').replace('PCE price index 0.1 0.3','PCE price index 0.1 0.0')
        rendered,missing=details(row('pce',text))
        self.assertFalse(missing);self.assertIn('PCE月增率**\n本次 **+0.0%**',rendered)
        text='The Committee decided to lower the target range for the federal funds rate by 25 basis points to 3.5 to 3.75 percent.'
        rendered,missing=details(row('fomc',text))
        self.assertFalse(missing);self.assertIn('降息',rendered);self.assertIn('25 基點',rendered)

    def test_jolts_unadjusted_text_is_not_seasonally_adjusted(self):
        for basis in ('not seasonally adjusted','unseasonally adjusted'):
            item=row('jolts','JOB OPENINGS AND LABOR TURNOVER – AUGUST 2026. Job openings were 7.1 million. '+basis)
            self.assertTrue(details(item)[1])

    def test_all_eleven_have_a_validated_main_value_path(self):
        from test_extended_member_results import GDP,DURABLE,INDUSTRIAL,JOLTS
        from test_macro_scope_expansion import RETAIL
        examples={'fomc':row('fomc',self.fed),'pce':row('pce',self.pce),
                  'gdp':row('gdp',GDP),'durable':row('durable',DURABLE),
                  'industrial':row('industrial',INDUSTRIAL),'jolts':row('jolts',JOLTS),
                  'retail':row('retail',RETAIL),
                  'jobs':row('jobs',id='bls-api-jobs-2026-M09-x',reference_period='2026-M09',
                             jobs_metrics={'payroll':100000,'unemployment':4.1}),
                  'claims':row('claims',(FIX/'claims_20261022_wrapped.txt').read_text(encoding='utf-8'),
                               url='https://oui.doleta.gov/press/2026/102226.pdf',
                               published=datetime(2026,10,22,12,30,tzinfo=timezone.utc))}
        for key in ('cpi','ppi'):
            examples[key]=row(key,reference_period='2026-M09',price_metrics={'monthly':0.2,'annual':3.0,
                                'monthly_seasonally_adjusted':True,'annual_unadjusted':True})
        self.assertEqual(set(examples),slim_policy.RESULT_EVENTS)
        for key,item in examples.items():
            with self.subTest(key=key):
                self.assertFalse(n.release_critical_missing(item))
                self.assertTrue(details(item)[0])
                self.assertIn(details(item)[0],n.release_embed(item)['description'])


if __name__=='__main__':unittest.main()
