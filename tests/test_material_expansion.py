import os,copy,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch
import material_inbox as m
from notification_layout import readable_card,DIVIDER,text_size

class MaterialExpansion(unittest.TestCase):
    def test_atom_uses_article_not_self_feed_and_keeps_media_status(self):
        xml='<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A robot learns to cook</title><link rel="self" href="https://www.theverge.com/rss/index.xml"/><link rel="alternate" href="https://www.theverge.com/robots/story"/><published>2026-11-04T08:00:00Z</published><summary>A cooking experiment.</summary></entry></feed>'
        row=m.parse_ai_feed(xml,'The Verge','theverge.com',ai=False,official=False)[0]
        self.assertTrue(row['url'].endswith('/robots/story'))
        self.assertFalse(row['official']);self.assertFalse(row['material_ai'])
        self.assertEqual(m.topic(row),'interesting')

    def test_ai_tools_selected_but_ads_still_rejected(self):
        for title in ('A new AI tool turns sketches into animation','An agentic assistant organizes files','Copilot adds a coding workflow'):
            self.assertEqual(m.topic({'title':title}),'ai')
        for title in ('Sponsored: A new AI tool','Bitcoin giveaway with AI','AI price prediction for BTC'):
            self.assertIsNone(m.topic({'title':title}))

    def test_new_sources_do_not_replay_old_articles(self):
        now=datetime(2026,11,4,8,tzinfo=timezone.utc)
        state={'seen':{'public':'kept'},'material_inbox_v1':{'started_at':(now-timedelta(days=1)).isoformat(),'items':[]}}
        def feed(url,attempts=1):
            host=next(h for n,u,h in m.MATERIAL_SOURCES if u==url)
            return '<rss><channel><item><title>AI drawing tool</title><description>Draws pictures.</description><link>https://'+host+'/one</link><pubDate>Wed, 04 Nov 2026 07:50:00 GMT</pubDate></item></channel></rss>'
        with patch.dict(os.environ,{'MATERIAL_INBOX_ENABLED':'1','DISCORD_MATERIAL_WEBHOOK_URL':'https://discord.com/api/webhooks/123/TEST'}):
            m.run([],state,now,fetch=feed,send=Mock(return_value='123'),persist=Mock(),verify=Mock())
        self.assertEqual(set(state['material_inbox_v1']['source_started_at']),m.NEW_SOURCE_NAMES)
        self.assertFalse(any(r['source'] in m.NEW_SOURCE_NAMES for r in state['material_inbox_v1']['items']))
        self.assertEqual(state['seen'],{'public':'kept'})

    def test_dividers_idempotent_keep_all_data(self):
        card={'description':'Intro','fields':[{'name':'Value','value':'本次 +0.3%\n前值 +0.2%'},{'name':'Source','value':'https://example.com/source'}]}
        first=readable_card(copy.deepcopy(card))
        self.assertIn(DIVIDER,first['fields'][0]['value'])
        self.assertEqual(readable_card(copy.deepcopy(first)),first)
        self.assertIn('https://example.com/source',first['fields'][1]['value'])
        self.assertLess(text_size(first),6000)

    def test_digest_items_separated(self):
        card=readable_card({'description':'**01｜第一件**\n來源A\n\n**02｜第二件**\n來源B'})
        self.assertIn(DIVIDER,card['description'])
        self.assertIn('來源A',card['description']);self.assertIn('來源B',card['description'])
