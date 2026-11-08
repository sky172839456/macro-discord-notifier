import unittest
from unittest.mock import patch
import news_streams as s
import crypto_news_notifier as n
import material_inbox as m

class MaterialEntry(unittest.TestCase):
    def test_checked_service_and_policy_titles_are_candidates(self):
        self.assertEqual(m.topic({'title':'Binance users in some European countries told to pull crypto before fees kick in, with accounts closing by year end'}),'business')
        self.assertEqual(m.topic({'title':'U.S. Treasury moves to cut off crypto exchange MEXC over $16 billion in alleged illicit flows'}),'policy')
        self.assertIsNone(m.topic({'title':'Binance account signup discount'}))

    def test_private_ai_topics_reuse_fetch_but_do_not_enter_member_rows(self):
        xml='<rss><channel><item><title>AI is speeding up recruitment</title><description>Agency fees are under pressure.</description><link>https://www.cnbc.com/ai-story</link><pubDate>Sun, 08 Nov 2026 06:00:01 GMT</pubDate></item></channel></rss>'
        cfg={'name':'CNBC科技','url':'https://www.cnbc.com/feed','official':False,'stream':'finance'}
        private=[]
        with patch.object(s,'FINANCE_SOURCES',(cfg,)),patch.object(n,'http_text',return_value=xml) as fetch,patch.object(n,'parse_feed',return_value=[]):
            public,status=s.fetch_finance(material_rows=private)
        self.assertEqual(public,[])
        self.assertEqual(len(private),1)
        self.assertEqual(m.topic(private[0]),'ai')
        fetch.assert_called_once()
        self.assertFalse(private[0]['official'])
