"""Second 2026-11-26 one-time correction: only listed text changes, idempotent, no write on surprises."""
import copy
import unittest

import news_copy_corrections_20261126b as fix


def live(mid):
    target = fix.TARGETS[mid]
    title = target['title'][0] if target.get('title') else '【金融新聞】 🌐 全球錢線｜11/24'
    description = '\n\n'.join(['**00｜其他新聞**', *[old for old, _ in target.get('description', ())], '🔗 [來源](' + target['link'] + ')'])
    return {'id': mid, 'channel_id': target['where'][0], 'embeds': [{
        'title': title, 'description': description, 'color': 0xB95A65, 'timestamp': '2026-11-24T13:49:53Z',
        'fields': [{'name': '🔗 原文與時間', 'value': '媒體報導｜[來源](' + target['link'] + ')\n📅 來源發布時間：2026/11/24 21:46'}],
        'footer': {'text': '台灣時間｜不構成投資建議'}}]}


class SecondRoundCorrections(unittest.TestCase):
    def test_every_target_changes_only_the_listed_text_and_is_idempotent(self):
        for mid, target in fix.TARGETS.items():
            with self.subTest(mid=mid):
                row = live(mid)
                old = copy.deepcopy(row)
                card = fix.corrected(row)
                self.assertEqual(row, old)
                for before, after in target.get('description', ()):
                    self.assertNotIn(before, card['description'])
                    self.assertEqual(card['description'].count(after), 1)
                if target.get('title'):
                    self.assertEqual(card['title'], target['title'][1])
                self.assertEqual(card['color'], target.get('color', 0xB95A65))
                self.assertEqual(card['fields'], old['embeds'][0]['fields'])
                self.assertEqual(card['timestamp'], old['embeds'][0]['timestamp'])
                self.assertEqual(card['footer']['text'], '台灣時間｜不構成投資建議' + fix.footer_note(target))
                self.assertTrue(card['description'].startswith('**00｜其他新聞**'))
                self.assertEqual(fix.corrected({**row, 'embeds': [card]}), card)

    def test_certik_is_no_longer_a_breaking_security_card(self):
        card = fix.corrected(live('1574784124563230731'))
        self.assertNotIn('重大快訊', card['title'])
        self.assertNotIn('資安事件', card['title'])
        self.assertNotIn('wv_risk', card['title'])
        self.assertIn('並非本次推播時新發生', card['description'])
        self.assertEqual(card['color'], fix.NON_ALERT_COLOR)

    def test_surprises_are_not_written(self):
        for mid, target in fix.TARGETS.items():
            good = live(mid)
            wrong_channel = copy.deepcopy(good)
            wrong_channel['channel_id'] = '0'
            no_link = copy.deepcopy(good)
            for part in no_link['embeds'][0]['fields']:
                part['value'] = part['value'].replace(target['link'], 'https://other.invalid')
            no_link['embeds'][0]['description'] = no_link['embeds'][0]['description'].replace(target['link'], 'https://other.invalid')
            changed = copy.deepcopy(good)
            key, old = ('title', target['title'][0]) if target.get('title') else ('description', target['description'][0][0])
            changed['embeds'][0][key] = changed['embeds'][0][key].replace(old, old[:-2] + '改')
            doubled = copy.deepcopy(good)
            doubled['embeds'][0]['description'] += '\n' + (target['description'][0][0] if target.get('description') else '')
            marked_but_old = copy.deepcopy(good)
            marked_but_old['embeds'][0]['footer']['text'] += fix.footer_note(target)
            two_embeds = copy.deepcopy(good)
            two_embeds['embeds'].append({})
            for row in ({**good, 'id': 'other'}, wrong_channel, no_link, changed, doubled, marked_but_old, two_embeds):
                with self.subTest(mid=mid, case=row.get('channel_id')):
                    with self.assertRaises(ValueError):
                        fix.corrected(row)

    def test_requests_are_limited_to_reading_and_patching_targets(self):
        for method, suffix in (('DELETE', '/messages/1574784124563230731'), ('POST', ''),
                               ('PATCH', '/messages/1574757663424909334'), ('PATCH', '')):
            with self.subTest(method=method, suffix=suffix):
                with self.assertRaises(ValueError):
                    fix.checked_request('https://example.invalid', method, suffix, opener=lambda *a, **k: None)


if __name__ == '__main__':
    unittest.main()
