import unittest
import io
from urllib.error import HTTPError
from member_copy_corrections import corrected, checked_request, CHANNEL, MARK

class CheckedCopyMaintenanceTests(unittest.TestCase):
    def test_rate_limit_waits_as_instructed_and_never_retries_auth_failure(self):
        from unittest.mock import Mock
        response = io.StringIO('{"ok":true}')
        response.headers = {'X-RateLimit-Remaining':'0','X-RateLimit-Reset-After':'0.5'}
        opener = Mock(side_effect=[HTTPError('redacted',429,'limit',{'Retry-After':'0.25'},io.BytesIO(b'{"retry_after":0.25}')), response])
        sleeps = []
        self.assertEqual(checked_request('https://example.invalid','GET',opener=opener,sleeper=sleeps.append),{'ok':True})
        self.assertEqual(sleeps,[0.35,0.6]); self.assertEqual(opener.call_count,2)
        opener = Mock(side_effect=HTTPError('redacted',403,'forbidden',{},None))
        with self.assertRaises(HTTPError): checked_request('https://example.invalid','GET',opener=opener,sleeper=sleeps.append)
        self.assertEqual(opener.call_count,1)

    def test_rejects_unknown_targets_and_unexpected_source(self):
        for row in ({'id':'other','channel_id':CHANNEL,'embeds':[{}]},
                    {'id':'1567912549494689873','channel_id':CHANNEL,'embeds':[{'title':'unrelated'}]}):
            with self.assertRaises(ValueError): corrected(row)

    def test_original_timing_is_preserved_and_correction_is_idempotent(self):
        row={'id':'1568583218159026229','channel_id':CHANNEL,'embeds':[{
            'title':'old title','description':'old text','url':'https://cointelegraph.com/interview/trm-labs-binance-hack-interview',
            'timestamp':'2026-11-07T11:09:00Z','footer':{'text':'資訊參考'},
            'fields':[{'name':'原文與時間','value':'來源發布時間：2026/11/07 04:36\n機器人發現：2026/11/07 19:09'}]}]}
        card=corrected(row)
        self.assertIn('市場觀點',card['title']);self.assertNotIn('重大快訊',card['title'])
        self.assertIn('63億',card['description']);self.assertIn(MARK,card['footer']['text'])
        self.assertEqual(card['timestamp'],row['embeds'][0]['timestamp'])
        self.assertIn('04:36',card['fields'][0]['value']);self.assertIn('19:09',card['fields'][0]['value'])
        self.assertEqual(corrected({**row,'embeds':[card]}),card)
