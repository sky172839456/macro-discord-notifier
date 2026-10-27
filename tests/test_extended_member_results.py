import os,unittest
from datetime import datetime,timezone
from unittest.mock import patch
from macro_result_extensions import details,publication,enrich
from config import EVENT_RULES
import notifier as n
import slim_policy

GDP=('Real gross domestic product (GDP) increased at an annual rate of 2.2 percent in the second quarter of 2026, according to the third estimate. In the first quarter, real GDP increased 2.5 percent (revised). Real GDP was revised up 0.7 percentage point from the second estimate.')
DURABLE=('October 27, 2026 MONTHLY ADVANCE REPORT ON DURABLE GOODS September 2026. adjusted for seasonal variation but not for price changes. New orders for manufactured durable goods in September, up two of the last three months, increased $8.0 billion or 2.9 percent to $300 billion. This followed a 2.7 percent August decrease. Excluding transportation, new orders increased 0.4 percent.')
INDUSTRIAL=('Release Date: October 16, 2026 Industrial production (IP) increased 0.7 percent in September after edging up 0.1 percent in August. Manufacturing output rose 0.3 percent in September. Capacity utilization moved up to 76.9 percent in September. Seasonally adjusted.')
JOLTS=('JOB OPENINGS AND LABOR TURNOVER – AUGUST 2026. The number of job openings was little changed at 7.1 million in August. Hires were 5.2 million. seasonally adjusted.')

def item(key,summary,**kw):
    return {'id':'fixture','rule':next(r for r in EVENT_RULES if r['key']==key),
            'summary':summary,'title':'','url':'https://example.invalid/fixture','published':datetime(2026,10,27,12,30,tzinfo=timezone.utc),**kw}

class ExtendedResultTests(unittest.TestCase):
    def test_approved_four_keys_are_enabled(self):
        self.assertTrue({'gdp','durable','industrial','jolts'} <= slim_policy.RESULT_EVENTS)

    def test_gdp_does_not_take_revision_or_industry_number_as_current_or_prior(self):
        text,missing=details(item('gdp',GDP))
        self.assertFalse(missing)
        for value in ('2026年第2季','+2.2%','+2.5%','第三次估計'):self.assertIn(value,text)
        self.assertNotIn('0.7%',text)
        self.assertTrue(details(item('gdp','Nominal GDP increased 4 percent.'))[1])

    def test_gdp_unmatched_previous_quarter_is_missing(self):
        text,_=details(item('gdp',GDP.replace('first quarter','fourth quarter')))
        self.assertIn('前季值',text);self.assertIn('暫缺',text);self.assertNotIn('2.5%',text)

    def test_durable_anchors_headline_not_transportation_or_dollars(self):
        text,missing=details(item('durable',DURABLE))
        self.assertFalse(missing)
        for x in ('2026/09','+2.9%','-2.7%','未扣除價格變動'):self.assertIn(x,text)
        self.assertNotIn('0.4%',text)

    def test_durable_decline_and_missing_basis_period_rejected(self):
        text,_=details(item('durable',DURABLE.replace('increased $8.0','decreased $8.0')))
        self.assertIn('-2.9%',text)
        for bad in (DURABLE.replace('adjusted for seasonal variation','unadjusted'),DURABLE.replace('September 2026','September')):
            self.assertTrue(details(item('durable',bad))[1])

    def test_industrial_anchors_total_not_manufacturing_or_annual(self):
        text,missing=details(item('industrial',INDUSTRIAL))
        self.assertFalse(missing)
        for x in ('2026/09','+0.7%','+0.1%','76.9%'):self.assertIn(x,text)
        self.assertNotIn('0.3%',text)
        self.assertTrue(details(item('industrial',INDUSTRIAL.replace('Release Date: October 16, 2026','')))[1])

    def test_jolts_not_hires_as_prior_and_preserve_units(self):
        text,missing=details(item('jolts',JOLTS))
        self.assertFalse(missing);self.assertIn('710.0萬人',text);self.assertIn('前月值',text)
        self.assertNotIn('520.0',text)
        self.assertTrue(details(item('jolts',JOLTS.replace('seasonally adjusted','unadjusted')))[1])

    def test_jolts_api_reference_and_adjacent_prior(self):
        text,missing=details(item('jolts','Job openings were 7.100 million. previous value 7.300 million.',id='bls-api-jolts-2026-M08-x',reference_period='2026-M08'))
        self.assertFalse(missing)
        for x in ('2026/08','710.0','730.0'):self.assertIn(x,text)
        self.assertTrue(details(item('jolts','Job openings were 7.100 million.',id='bls-api-jolts-x'))[1])

    def test_missing_main_value_blocks_even_if_unrelated_numbers_present(self):
        with patch.dict(os.environ,{'SLIM_NOTIFICATIONS':'1'}):
            for key in ('gdp','industrial','durable','jolts'):
                with self.subTest(key=key):
                    self.assertTrue(n.release_critical_missing(item(key,'2026 report; secondary metric increased 5 percent.')))

    def test_rendered_cards_use_same_validated_metrics_as_gate(self):
        with patch.dict(os.environ,{'SLIM_NOTIFICATIONS':'1'}):
            for key,text in [('gdp',GDP),('durable',DURABLE),('industrial',INDUSTRIAL),('jolts',JOLTS)]:
                row=item(key,text);self.assertFalse(n.release_critical_missing(row))
                self.assertIn(details(row)[0],n.release_embed(row)['description'])

    def test_publication_dates_and_embargo_clock_are_not_detection_time(self):
        for key,text,h,m in [('durable',DURABLE,12,30),('industrial',INDUSTRIAL,13,15),('gdp','Current release: September 30, 2026 '+GDP,12,30)]:
            value=publication(text,key)
            self.assertEqual((value.hour,value.minute),(h,m))
            self.assertLessEqual(value,datetime(2026,10,27,13,tzinfo=timezone.utc))
        with self.assertRaises(ValueError):publication('Next release: October 29, 2026','gdp')

    def test_enrichment_same_official_domain_only_and_fetch_failure_defers(self):
        row=item('gdp','',url='https://www.bea.gov/news/current')
        self.assertFalse(details(enrich(row,lambda _:GDP))[1])
        self.assertIs(enrich(dict(row,url='https://example.com'),lambda _:GDP)['rule'],row['rule'])
        def fail(_):raise OSError('403')
        self.assertTrue(details(enrich(row,fail))[1])
