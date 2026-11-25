"""Third 2026-11-26 one-time correction (罷工 mistranslations): only listed text, every embed kept, idempotent."""
import copy
import unittest

import news_copy_corrections_20261126c as fix


def live(mid):
    count, changes = fix.TARGETS[mid]
    embeds = [{'title': f'📰 每小時摘要 {i}', 'description': f'其他新聞 {i}', 'color': 15965202, 'type': 'rich',
               'timestamp': '2026-10-09T11:14:45+00:00', 'footer': {'text': '僅供資訊參考｜台灣時間'},
               'author': {'name': '加密新聞雷達'}, 'fields': [{'name': '🔗 原文連結', 'value': 'https://example.invalid/other'}]}
              for i in range(count)]
    for index, link, old, _ in changes:
        embeds[index]['description'] += '\n' + old
        embeds[index]['fields'] = [{'name': '🔗 原文連結', 'value': 'https://www.coindesk.com/x/' + link}]
    return {'id': mid, 'channel_id': fix.CHANNEL, 'embeds': embeds}


class StrikeCorrections(unittest.TestCase):
    def test_every_target_changes_only_listed_text_and_is_idempotent(self):
        for mid, (count, changes) in fix.TARGETS.items():
            with self.subTest(mid=mid):
                row = live(mid)
                old = copy.deepcopy(row)
                cards = fix.corrected(row)
                self.assertEqual(row, old)
                self.assertEqual(len(cards), count)
                changed = {index for index, *_ in changes}
                for index, card in enumerate(cards):
                    before = fix.editable(old['embeds'])[index]
                    if index not in changed:
                        self.assertEqual(card, before)
                        continue
                    self.assertNotIn('罷工', card['description'])
                    self.assertTrue(card['description'].startswith(f'其他新聞 {index}'))
                    self.assertEqual(card['footer']['text'], '僅供資訊參考｜台灣時間' + fix.NOTE)
                    self.assertEqual(card['fields'], before['fields'])
                    self.assertEqual(card['timestamp'], before['timestamp'])
                for index, _, old_text, new_text in changes:
                    self.assertNotIn(old_text, cards[index]['description'])
                    self.assertEqual(cards[index]['description'].count(new_text), 1)
                self.assertEqual(fix.corrected({**row, 'embeds': cards}), cards)

    def test_numbers_in_corrected_lines_are_unchanged(self):
        import re
        for mid, (_, changes) in fix.TARGETS.items():
            for _, _, old_text, new_text in changes:
                with self.subTest(mid=mid, old=old_text):
                    self.assertEqual(re.findall(r'\d[\d,.]*', old_text), re.findall(r'\d[\d,.]*', new_text))

    def test_surprises_are_not_written(self):
        for mid, (count, changes) in fix.TARGETS.items():
            good = live(mid)
            index, link, old_text, _ = changes[0]
            wrong_channel = copy.deepcopy(good); wrong_channel['channel_id'] = '0'
            wrong_layout = copy.deepcopy(good); wrong_layout['embeds'].append({})
            no_link = copy.deepcopy(good); no_link['embeds'][index]['fields'] = []
            changed = copy.deepcopy(good)
            changed['embeds'][index]['description'] = changed['embeds'][index]['description'].replace(old_text, old_text[:-1] + '改')
            doubled = copy.deepcopy(good); doubled['embeds'][index]['description'] += '\n' + old_text
            leftover = copy.deepcopy(good); leftover['embeds'][index]['description'] += '\n另有一句伊朗罷工'
            marked_but_old = copy.deepcopy(good); marked_but_old['embeds'][index]['footer']['text'] += fix.NOTE
            for case, row in (('id', {**good, 'id': 'other'}), ('channel', wrong_channel), ('layout', wrong_layout),
                              ('link', no_link), ('changed', changed), ('doubled', doubled),
                              ('leftover', leftover), ('marked', marked_but_old)):
                with self.subTest(mid=mid, case=case):
                    with self.assertRaises(ValueError):
                        fix.corrected(row)

    def test_requests_are_limited_to_reading_and_patching_targets(self):
        for method, suffix in (('DELETE', '/messages/1558075245024251935'), ('POST', ''),
                               ('PATCH', '/messages/1574784124563230731'), ('PATCH', '')):
            with self.subTest(method=method, suffix=suffix):
                with self.assertRaises(ValueError):
                    fix.checked_request('https://example.invalid', method, suffix, opener=lambda *a, **k: None)


if __name__ == '__main__':
    unittest.main()
