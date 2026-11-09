"""Source-scoped request compatibility; errors and content checks stay strict."""
from email.message import Message
from io import BytesIO
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import notifier as n


class Response(BytesIO):
    headers = Message()


class CensusSourceHeaders(unittest.TestCase):
    url = 'https://www.census.gov/retail/sales.html'
    def test_census_text_and_binary_requests_omit_referrer(self):
        original=dict(n.HTTP_HEADERS)
        for read,url,body in ((n.http_text,self.url,b'dated retail release'),
                              (n.http_bytes,'https://www.census.gov/retail/marts/www/marts_current.pdf',b'%PDF-test')):
            def opened(request,timeout):
                self.assertEqual(request.full_url,url)
                self.assertFalse(request.has_header('Referer'))
                self.assertEqual(request.get_header('User-agent'),original['User-Agent'])
                return Response(body)
            with patch.object(n,'urlopen',side_effect=opened):
                self.assertEqual(read(url,attempts=1),body.decode() if read is n.http_text else body)
        self.assertEqual(n.HTTP_HEADERS,original)
    def test_other_providers_and_lookalike_hosts_retain_existing_headers(self):
        for url in ('https://www.bls.gov/news.release/cpi.htm','https://www.bea.gov/news',
                    'https://www.federalreserve.gov/releases/g17/',
                    'https://census.gov.attacker.example/retail',
                    'https://www.census.gov@attacker.example/retail'):
            self.assertEqual(n.source_headers(url),n.HTTP_HEADERS)
        for url in ('https://census.gov/retail','https://www2.census.gov/retail'):
            self.assertNotIn('Referer',n.source_headers(url))
    def test_404_500_and_403_are_not_reported_as_empty_success(self):
        for code in (404,500,403):
            with patch.object(n,'urlopen',side_effect=HTTPError(self.url,code,'fixture failure',{},None)):
                for read in (n.http_text,n.http_bytes):
                    with self.assertRaises(HTTPError):read(self.url,attempts=1)
    def test_existing_retail_checker_still_rejects_missing_date_and_values(self):
        from macro_results import retail_details
        self.assertTrue(retail_details({'summary':'Advance Monthly Sales for Retail and Food Services'})[1])

