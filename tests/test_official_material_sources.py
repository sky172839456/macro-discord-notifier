import json
import unittest
from datetime import datetime, timezone
import material_inbox as m


class OfficialMaterialSources(unittest.TestCase):
    def xml(self, host, title='Clearing up a robot memory', url=None):
        return f'<rss><channel><item><title>{title}</title><description>Researchers describe a new method and its limitations.</description><link>{url or "https://"+host+"/research/story"}</link><pubDate>Sat, 07 Nov 2026 03:00:00 GMT</pubDate></item></channel></rss>'

    def test_official_research_is_not_blanket_ai_tool(self):
        for name, url, host in m.RESEARCH_SOURCES:
            row=m.parse_source_feed(self.xml(host), name, host)[0]
            self.assertTrue(row['official'])
            self.assertFalse(row['material_ai'])
            self.assertEqual(m.topic(row),'research')
            self.assertIn(name,m.NEW_SOURCE_NAMES)

    def test_source_host_and_dates_are_required(self):
        for name, url, host in m.RESEARCH_SOURCES:
            self.assertEqual(m.parse_source_feed(self.xml(host,url='https://example.com/claim'),name,host),[])
            self.assertEqual(m.parse_source_feed(self.xml(host).replace('Sat, 07 Nov 2026 03:00:00 GMT','invalid'),name,host),[])

    def test_existing_categories_and_exclusions_take_precedence(self):
        name,url,host=m.RESEARCH_SOURCES[0]
        for title,expected in [('AI tool adds a coding workflow','ai'),('Engineers test a new battery','innovation'),('Sponsored: AI tool','IGNORE'),('Podcast: AI research','IGNORE')]:
            row=m.parse_source_feed(self.xml(host,title),name,host)[0]
            self.assertEqual(m.topic(row),None if expected=='IGNORE' else expected)

    def test_official_card_retains_priority_concept_time_and_caveat(self):
        now=datetime(2026,11,7,4,tzinfo=timezone.utc)
        name,url,host=m.RESEARCH_SOURCES[0]
        row=m.parse_source_feed(self.xml(host),name,host)[0]
        row['material_topic']=m.topic(row)
        text=json.dumps(m.card(row,now),ensure_ascii=False)
        for value in ('製作優先度','初步內容構思','來源與時間','官方來源候選','方法','樣本'):
            self.assertIn(value,text)
        self.assertNotIn('已獨立驗證',text)
