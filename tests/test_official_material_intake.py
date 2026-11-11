"""Synthetic publisher fixtures; not evidence of any real product launch."""
import copy
import json
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
import official_material_sources as o
import material_inbox as m
from material_quality import selection, inspect
from material_editorial import review


class OfficialIntake(unittest.TestCase):
    now=datetime(2026,11,9,4,tzinfo=timezone.utc)
    tv=o.SOURCES[-1]
    bg=o.SOURCES[0]
    bn=next(s for s in o.SOURCES if s['kind']=='binance')
    title='TradingView adds an MCP server for Claude'
    url='https://www.tradingview.com/blog/en/new-mcp-123/'
    body='Essential and other paid plans can query market data and manage watchlists and alerts through MCP in beta, with read-only OAuth permissions.'
    def index(self,url=None,title=None):
        return '<article><a rel="bookmark" href="'+(url or self.url)+'"></a><h3>'+(title or self.title)+'</h3></article>'
    def detail(self,date=None,title=None,body=None,modified='2026-11-09T04:00:00Z'):
        return '<meta property="article:published_time" content="'+(date or self.now.isoformat())+'"><meta property="article:modified_time" content="'+modified+'"><h1>'+(title or self.title)+'</h1><div class="entry-content"><p>'+(body or self.body)+'</p></div><footer>noise maximum fees Nov 10</footer>'
    def state(self):
        return {self.tv['name']:{'started_at':(self.now-timedelta(hours=1)).isoformat(),'known':[],'pending':[],'cache':[]}}
    def test_new_source_baselines_without_detail_fetch_or_backfill(self):
        fetch=Mock(return_value=self.index());state={}
        rows,status=o.collect(self.now,state,fetch=fetch,sources=[self.tv])
        self.assertEqual(rows,[]);fetch.assert_called_once()
        self.assertTrue(status[0]['baseline']);self.assertEqual(state[self.tv['name']]['known'],[self.url])
    def test_new_update_is_cached_with_original_timestamp_and_retained_stars_angle(self):
        state=self.state();fetch=Mock(side_effect=lambda url,**k:self.index() if url==self.tv['url'] else self.detail())
        rows,status=o.collect(self.now,state,fetch=fetch,sources=[self.tv])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['published'],self.now)
        self.assertTrue(rows[0]['official']);self.assertNotIn('noise',rows[0]['summary'])
        rows[0]['material_topic']=m.topic(rows[0]);self.assertIsNone(selection(rows[0],self.now))
        text=json.dumps(m.card(rows[0],self.now),ensure_ascii=False)
        self.assertIn('製作優先度',text);self.assertIn('來源內容',text);self.assertIn(self.body,text)
        fetch.reset_mock();o.collect(self.now+timedelta(minutes=5),state,fetch=fetch,sources=[self.tv]);fetch.assert_called_once()
    def test_old_article_modification_does_not_become_new_publication(self):
        fetch=Mock(side_effect=lambda url,**k:self.index() if url==self.tv['url'] else self.detail(date=(self.now-timedelta(days=30)).isoformat()))
        rows,_=o.collect(self.now,self.state(),fetch=fetch,sources=[self.tv]);self.assertEqual(rows,[])
    def test_future_publication_stays_pending_instead_of_becoming_current_or_lost(self):
        future=self.now+timedelta(hours=1)
        fetch=Mock(side_effect=lambda url,**k:self.index() if url==self.tv['url'] else self.detail(date=future.isoformat()))
        state=self.state();rows,status=o.collect(self.now,state,fetch=fetch,sources=[self.tv]);self.assertEqual(rows,[])
        self.assertFalse(status[0]['readable']);self.assertEqual(status[0]['detail_pending'],1)
        rows,status=o.collect(future,state,fetch=fetch,sources=[self.tv]);self.assertEqual(len(rows),1)
    def test_detail_failure_is_pending_and_visible_with_backoff(self):
        def fetch(url,**kwargs):
            if url==self.tv['url']:return self.index()
            raise OSError('fixture outage')
        state=self.state();rows,status=o.collect(self.now,state,fetch=fetch,sources=[self.tv]);self.assertEqual(rows,[])
        self.assertFalse(status[0]['readable']);self.assertEqual(status[0]['detail_pending'],1)
        retry=Mock(side_effect=fetch);o.collect(self.now+timedelta(minutes=5),state,fetch=retry,sources=[self.tv]);retry.assert_called_once()
        recovered=Mock(side_effect=lambda url,**k:self.index() if url==self.tv['url'] else self.detail())
        rows,status=o.collect(self.now+timedelta(minutes=31),state,fetch=recovered,sources=[self.tv]);self.assertEqual(len(rows),1)
        self.assertEqual(status[0]['detail_pending'],0)
    def test_index_failure_does_not_reset_or_rebaseline_source(self):
        state=self.state();before=copy.deepcopy(state)
        rows,status=o.collect(self.now,state,fetch=Mock(side_effect=OSError()),sources=[self.tv])
        self.assertFalse(status[0]['readable']);self.assertEqual(state,before)
    def test_bounded_details_keep_remaining_pending(self):
        extra='https://www.tradingview.com/blog/en/second-update-456/'
        fetch=Mock(side_effect=lambda url,**k:self.index()+self.index(extra) if url==self.tv['url'] else self.detail())
        rows,status=o.collect(self.now,self.state(),fetch=fetch,sources=[self.tv],max_details=1)
        self.assertEqual(len(rows),1);self.assertEqual(status[0]['detail_pending'],1);self.assertEqual(fetch.call_count,2)
    def test_busy_sources_cannot_permanently_starve_the_last_source(self):
        sources=[dict(self.tv,name='Source '+str(i)) for i in range(7)]
        ledger={s['name']:{'started_at':(self.now-timedelta(hours=1)).isoformat(),'known':[], 'pending':[], 'cache':[]} for s in sources}
        fetch=Mock(side_effect=lambda url,**k:self.index()+self.index('https://www.tradingview.com/blog/en/another-456/') if url==self.tv['url'] else self.detail())
        _,first=o.collect(self.now,ledger,fetch=fetch,sources=sources)
        self.assertEqual(first[-1]['cached'],0)
        _,second=o.collect(self.now+timedelta(minutes=5),ledger,fetch=fetch,sources=sources)
        self.assertEqual(second[-1]['cached'],1)
    def test_promotional_game_does_not_use_new_announcement_detail_budget(self):
        fetch=Mock(return_value=self.index(title='Word of the Day: Choose Your Binance AI'))
        rows,status=o.collect(self.now,self.state(),fetch=fetch,sources=[self.tv])
        self.assertEqual(rows,[]);fetch.assert_called_once();self.assertEqual(status[0]['excluded_promotions'],1)
        self.assertEqual(status[0]['detail_pending'],0)
    def test_empty_login_wrong_title_missing_date_and_date_modified_fail_closed(self):
        item={'url':self.url,'title':self.title,'published':None}
        for raw in (self.detail(title='Sign in'),self.detail().replace('article:published_time','article:modified_time'),'<h1>'+self.title+'</h1>',self.detail(body='tiny')):
            with self.subTest(raw=raw[:70]),self.assertRaises(ValueError):o.parse_detail(raw,item,self.tv)
    def test_urls_cannot_escape_official_paths_or_redirect_to_other_hosts(self):
        for url in ('https://evil.com/blog/en/new-mcp-123/','http://www.tradingview.com/blog/en/new-mcp-123/',
                    'https://www.tradingview.com@127.0.0.1/x','https://www.tradingview.com/blog/en/new-123/?next=http://localhost',
                    'https://api.bitget.com/api/v3/public/annoucements?x=1','https://www.binance.com/account'):
            self.assertFalse(o.allowed(url))
        with self.assertRaises(ValueError):o.SafeRedirect().redirect_request(None,None,302,'',{},'https://evil.com/x')
    def bg_case(self,show,created=None,content='123',unified=None):
        ms=int(self.now.timestamp()*1000)
        api=json.dumps({'code':'00000','data':[{'annTitle':'Bitget Launchpool introduces Example','annUrl':'https://www.bitget.com/en/support/articles/123','cTime':str(ms)}]})
        item=o.parse_index(api,self.bg)[0]
        raw=('<h1>'+item['title']+'</h1><div data-article-content="true">'+self.body+'</div><script>{"contentId":"'+content+'",'
             '"longCreateTime":"'+str(ms+(created or 0))+'","showTime":"'+str(ms+show)+'","unifiedDisplayTime":"'+str(ms+(show if unified is None else unified))+'"}</script>')
        return raw,item
    def test_bitget_index_ctime_is_display_publication_not_draft_creation(self):
        _,item=self.bg_case(0);self.assertIsNone(item['published'])
        # Real shapes seen 2026-11-12: identical, 1 ms rounding, scheduled draft (created 1h42m earlier), re-saved (created 9 min later).
        for show,created in ((0,0),(1,0),(0,-6106037),(0,538516)):
            with self.subTest(show=show,created=created):
                raw,item=self.bg_case(show,created)
                row=o.parse_detail(raw,item,self.bg)
                self.assertEqual(row['published'],(self.now+timedelta(milliseconds=show)).isoformat())
    def test_bitget_publication_identity_and_conflicts_still_fail_closed(self):
        for kwargs in ({'show':120000},{'show':-120000},{'show':1001},{'show':0,'content':'999'},{'show':0,'unified':2}):
            with self.subTest(**kwargs):
                raw,item=self.bg_case(**kwargs)
                with self.assertRaises(ValueError):o.parse_detail(raw,item,self.bg)
        raw,item=self.bg_case(0)
        with self.assertRaises(ValueError):o.parse_detail(raw.replace('"showTime"','"x"').replace('"unifiedDisplayTime"','"y"'),item,self.bg)
    def test_binance_validates_code_title_and_publication_date(self):
        ms=int(self.now.timestamp()*1000);code='a'*32
        raw=json.dumps({'code':'000000','data':{'catalogs':[{'articles':[{'title':'Binance introduces Example Launchpool','code':code,'releaseDate':ms}]}]}})
        item=o.parse_index(raw,self.bn)[0]
        data={'code':code,'title':item['title'],'publishDate':ms,'body':json.dumps({'node':'root','child':[{'node':'text','text':self.body}]})}
        payload={'code':'000000','data':data};self.assertIn('watchlists',o.parse_detail(json.dumps(payload),item,self.bn)['summary'])
        for k,v in (('code','b'*32),('title','wrong'),('publishDate',ms-1)):
            wrong=copy.deepcopy(payload);wrong['data'][k]=v
            with self.assertRaises(ValueError):o.parse_detail(json.dumps(wrong),item,self.bn)
    def test_official_activity_reads_conditions_beyond_feed_lead_without_loosening(self):
        row={'title':'Bitget Launchpool introduces Example: stake BGB','summary':'The product overview describes the underlying token and its mechanics. '*19+'Eligible users who complete KYC can stake BGB from Nov. 10 to Nov. 17, with a minimum of 10 BGB and redemption over 7 days.', 'material_topic':'business'}
        self.assertIsNone(selection(row,self.now))
        row['summary']='A groundbreaking new product will change everything for everyone. '*10
        self.assertIsNotNone(selection(row,self.now))
    def test_claude_releases_only_trust_official_repository(self):
        def xml(url):return '<rss><channel><item><title>v1.2.3</title><description>'+self.body+'</description><link>'+url+'</link><pubDate>Mon, 09 Nov 2026 04:00:00 GMT</pubDate></item></channel></rss>'
        self.assertEqual(m.parse_source_feed(xml('https://github.com/attacker/repo/releases/tag/x'),'Claude Code Releases','github.com'),[])
        row=m.parse_source_feed(xml('https://github.com/anthropics/claude-code/releases/tag/v1.2.3'),'Claude Code Releases','github.com')[0]
        self.assertTrue(row['official']);self.assertEqual(m.topic(row),'ai');self.assertIn('Claude Code',row['title'])
    def test_new_official_and_media_same_event_still_deduplicate(self):
        row={'title':self.title,'url':self.url,'summary':self.body,'published':self.now}
        media=dict(row,url='https://example.com/report',source='Media')
        self.assertTrue(m.equivalent(row,media))
    def test_official_quiz_with_ai_and_legal_footer_does_not_become_tool_update(self):
        for title in ('Word of the Day: Choose Your Binance AI to Unlock BNB Rewards!',
                      'Binance Quiz: learn about a new AI tool and earn rewards',
                      'Bitget trading competition: launch a new AI bot'):
            self.assertIsNone(m.topic({'title':title,'summary':self.body,'source':'Binance Activities','official':True}))
        self.assertEqual(m.topic({'title':'TradingView portfolios now support exporting reports','source':'TradingView Blog'}),'innovation')

