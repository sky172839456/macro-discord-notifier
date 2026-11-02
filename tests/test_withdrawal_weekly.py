import os,copy,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import crypto_news_notifier as news
import news_editorial as editorial
import market_brief_v2 as brief

ROWS=[
 ('Binance opens crypto withdrawals in phases starting with bitcoin following $6.3 billion hack',
  'Binance reopens customer withdrawals following a record $6.3 billion exploit. Bitcoin leads the first phase.'),
 ('Binance says phase one of withdrawals opens after $6.3B hack',
  'The crypto exchange said it has begun phased withdrawals after the record hack the FBI has blamed on North Korea.')]

class WithdrawalWeeklyTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,2,tzinfo=timezone.utc)
  self.env=patch.dict(os.environ,{'SLIM_NOTIFICATIONS':'1','NEWS_AUTO_RECOVERY':'1'})
  self.env.start();self.addCleanup(self.env.stop)
 def row(self,index=0,**changes):
  title,summary=ROWS[index]
  return dict(id='fixture-'+str(index),title=title,summary=summary,title_zh='幣安啟動第一階段提款',
   summary_zh_points=['幣安啟動第一階段提款。'],url='https://example.invalid/'+str(index),
   published=self.now-timedelta(hours=2+index),source='Fixture'+str(index),official=False,**changes)
 def review(self,rows):
  with tempfile.TemporaryDirectory() as folder:
   target=Path(folder)/'isolated.json'
   target.write_text(json.dumps({'weekly_journal':rows},default=lambda v:v.isoformat()),encoding='utf-8')
   return brief.news_review(target,self.now)['items']
 def test_verified_same_withdrawal_phase_merges_with_both_links_and_context(self):
  a,b=self.row(),self.row(1)
  before=copy.deepcopy([a,b])
  result=news.deduplicate([a,b])
  self.assertEqual(len(result),1)
  self.assertEqual(set([result[0]['id'],*result[0]['merged_ids']]),{'fixture-0','fixture-1'})
  self.assertEqual(len(result[0]['related_sources']),1)
  self.assertTrue(any('FBI' in s for s in [result[0]['summary'],*result[0]['event_context']]))
  self.assertEqual([a,b],before)
 def test_weekly_uses_same_full_evidence_rule(self):
  self.assertEqual(len(self.review([self.row(),self.row(1)])),1)
 def test_any_new_details_or_changed_phase_exit_source_pair_exception(self):
  for update in ('Losses revised to $6.4 billion.','Additional victims reported losses.',
                 'Investigators recovered $12 million.','New withdrawals halted.',
                 'A second phase now includes ETH withdrawals.','FBI announces new arrests.'):
   with self.subTest(update=update):
    a,b=self.row(),self.row(1);b['summary']+=' '+update
    self.assertFalse(editorial.equivalent(a,b))
    self.assertEqual(len(self.review([a,b])),2)
 def test_new_net_outflows_story_remains_separate(self):
  a,b=self.row(),self.row(1)
  b.update(title='Binance net outflows surge to $5.8B as withdrawals resume after record hack',
           summary='The outflows represent a fraction of roughly $171 billion in customer assets.')
  self.assertFalse(news.same_news_event(a,b));self.assertEqual(len(self.review([a,b])),2)
 def test_same_url_material_loss_revision_is_not_hidden_by_weekly_url_set(self):
  a,b=self.row(),self.row(1)
  b.update(url=a['url'],title=a['title'],summary=a['summary']+' Losses revised to $6.4 billion.')
  self.assertEqual(len(self.review([a,b])),2)
 def test_different_time_window_not_collapsed(self):
  a,b=self.row(),self.row(1);b['published']-=timedelta(days=2)
  self.assertFalse(editorial.equivalent(a,b))

if __name__=='__main__':unittest.main()
