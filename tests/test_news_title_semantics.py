import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from notification_quality import checked_translation, fund_flow_price_issue, unverified_name_gloss
import news_copy_corrections_20261126 as fix

IBIT = "Bitcoin ETFs keep bleeding as BlackRock's IBIT shares gain nearly 5%"
IBIT_BAD = '隨著 BlackRock 的 IBIT 股份上漲近 5%，Bitcoin ETF 持續下跌'
IBIT_GOOD = 'Bitcoin ETF 資金持續流出，BlackRock 的 IBIT 股價仍漲近 5%'
MEGA = ('The U.S. has added Megaspeed and other companies to its trade blacklist '
        'over fears that advanced computing products could be diverted.')
MEGA_BAD = '由於擔心先進運算產品可能被轉移用途，美國已將兆芯 (Megaspeed) 及其他公司列入貿易黑名單。'
MEGA_GOOD = '由於擔心先進運算產品可能被轉移用途，美國已將 Megaspeed 及其他公司列入貿易黑名單。'


class FundFlowIsNotPrice(unittest.TestCase):
    def test_bleeding_outflow_headline_cannot_become_an_etf_price_drop(self):
        self.assertEqual(fund_flow_price_issue(IBIT, IBIT_BAD), 'fund flows translated as price decline')
        with self.assertRaisesRegex(ValueError, 'fund flows translated as price'):
            checked_translation(IBIT, IBIT_BAD)
        self.assertIsNone(fund_flow_price_issue(IBIT, IBIT_GOOD))
        self.assertEqual(checked_translation(IBIT, IBIT_GOOD), IBIT_GOOD)

    def test_flow_and_price_in_opposite_directions_keep_their_own_direction(self):
        outflow_up = 'Bitcoin ETFs post $500 million outflows even as fund shares rise 2%'
        self.assertIsNone(fund_flow_price_issue(outflow_up, 'Bitcoin ETF 流出5億美元，基金股價仍上漲2%'))
        self.assertEqual(fund_flow_price_issue(outflow_up, 'Bitcoin ETF 下跌'), 'fund flows translated as price decline')
        inflow_down = 'Ether ETFs log $200 million inflows while ETF shares fall 3%'
        self.assertIsNone(fund_flow_price_issue(inflow_down, '以太幣 ETF 流入2億美元，ETF 股價下跌3%'))
        self.assertEqual(fund_flow_price_issue(inflow_down, '以太幣 ETF 上漲'), 'fund flows translated as price rise')

    def test_real_etf_price_moves_are_untouched(self):
        for source, copy_text in (
                ('Bitcoin ETFs fall 4% as bitcoin slides', 'Bitcoin ETF 下跌4%'),
                ('DRAM ETF rises 8%, chip stocks gain more than 4%', 'DRAM ETF 上漲 8%'),
                ('Bitcoin ETFs fall 4% despite $100 million inflows', 'Bitcoin ETF 下跌4%，資金仍流入1億美元'),
                ('Despite outflows, Bitcoin ETF prices rose', '儘管資金流出，Bitcoin ETF 價格上漲'),
                ('Miners keep bleeding as hashprice falls', '礦工持續下跌')):
            with self.subTest(source=source):
                self.assertIsNone(fund_flow_price_issue(source, copy_text))

    def test_dollar_amount_after_shed_or_drop_is_a_flow_not_a_price(self):
        source = 'Bitcoin ETFs shed $261M as XRP funds reverse weekly outflow trend'
        self.assertEqual(fund_flow_price_issue(source, 'Bitcoin ETF 下跌 2.61億美元'), 'fund flows translated as price decline')
        self.assertIsNone(fund_flow_price_issue(source, 'Bitcoin ETF 流出 2.61億美元'))

    def test_negated_bleeding_still_cannot_become_a_price_statement(self):
        source = 'Bitcoin ETFs are not bleeding anymore as inflows return'
        self.assertEqual(fund_flow_price_issue(source, 'Bitcoin ETF 沒有再下跌'), 'fund flows translated as price decline')

    def test_headline_uses_summary_flow_context(self):
        title = 'Bitcoin, Ethereum and Solana ETFs All in the Red for October'
        summary = 'Bitcoin ETFs logged $386.3 million in net outflows in the first seven trading days of October.'
        bad = '10 月份 Bitcoin、Ethereum 和 Solana ETF 全部下跌'
        self.assertIsNone(fund_flow_price_issue(title, bad))
        self.assertEqual(fund_flow_price_issue(title + ' ' + summary, bad), 'fund flows translated as price decline')

    def test_enrich_drops_headline_that_turns_summary_flows_into_price(self):
        import news_auto_recovery as auto
        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
        item = {'title': 'Bitcoin, Ethereum and Solana ETFs All in the Red for October',
                'summary': 'Bitcoin ETFs logged $386.3 million in net outflows this month.',
                'url': 'https://decrypt.co/1/etfs-red', 'published': now}
        with patch.object(auto, 'checked_copy', side_effect=lambda source, copy_text: copy_text), \
                patch('crypto_news_notifier.translate_text', return_value='10 月份 Bitcoin、Ethereum 和 Solana ETF 全部下跌'):
            result = auto.enrich(item, {}, now)
        self.assertEqual(result['title_zh'], '')
        self.assertEqual(result['summary_zh_points'], [])


class SourceNamesStayVerified(unittest.TestCase):
    def test_unverified_chinese_gloss_for_a_source_name_is_rejected(self):
        self.assertEqual(unverified_name_gloss(MEGA, MEGA_BAD), 'Megaspeed')
        with self.assertRaisesRegex(ValueError, 'unverified Chinese name'):
            checked_translation(MEGA, MEGA_BAD)
        self.assertIsNone(unverified_name_gloss(MEGA, MEGA_GOOD))

    def test_verified_names_people_acronyms_and_other_names_are_untouched(self):
        for source, copy_text in (
                ('Bitcoin fell with Nvidia', 'Bitcoin 與輝達 (Nvidia) 同步下跌'),
                ('The Winklevoss twins donated', '溫克沃斯兄弟 (Winklevoss) 捐款'),
                ('Citi said', '花旗集團 (Citi) 表示'),
                ('Fed governor Christopher Waller said', '聯準會理事克里斯多福·沃勒 (Christopher Waller) 表示'),
                ('John Williams said rates may rise', '約翰·威廉斯 (John Williams) 表示'),
                ('The IPO priced', '首次公開發行 (IPO) 定價'),
                ('The CFTC approved', '商品期貨交易委員會 (CFTC) 核准'),
                ('Megaspeed was added', '美國將 Megaspeed 列入名單')):
            with self.subTest(copy=copy_text):
                self.assertIsNone(unverified_name_gloss(source, copy_text))

    def test_known_name_with_a_different_chinese_name_is_rejected(self):
        self.assertEqual(unverified_name_gloss('Nvidia shares fell', '兆芯 (Nvidia) 股價下跌'), 'Nvidia')


def live_message(mid):
    descriptions = {
        '1574757663424909334': ('**01｜隨著 BlackRock 的 IBIT 股份上漲近 5%，Bitcoin ETF 持續下跌**\n\nETF／機構\n'
                                '媒體報導｜儘管 Bitcoin ETF 的提款持續，使得十一月的淨流出達到 47.1億美元，BlackRock 的 IBIT 股份在週一仍上漲了 4.85% 。\n'
                                '🔗 [Cointelegraph](https://cointelegraph.com/markets/bitcoin-etfs-bleed-ibit-shares-gain)\n📅 原文發布：11/24 15:41\n\n'
                                '──────────────\n\n**02｜Ethereum 基金會擴大團隊**'),
        '1574757664569827369': ('**01｜在 Nvidia 爭議事件中，美國基於出口管制方面的疑慮，將 Megaspeed 列入貿易黑名單。**\n\n科技／企業\n'
                                '媒體報導｜由於擔心先進運算產品可能被轉移用途，美國已將兆芯 (Megaspeed) 及其他六家公司列入貿易黑名單。\n'
                                '🔗 [CNBC科技](https://www.cnbc.com/2026/11/24/us-adds-megaspeed-to-trade-blacklist-over-export-control-concerns-.html)\n📅 原文發布：11/24 09:56'),
    }
    return {'id': mid, 'channel_id': fix.TARGETS[mid]['channel'], 'embeds': [{
        'title': '【新聞】', 'description': descriptions[mid], 'color': 0x647FB5, 'timestamp': '2026-11-24T12:04:44Z',
        'fields': [{'name': '閱讀提示', 'value': '原有提示'}], 'footer': {'text': '台灣時間｜不構成投資建議'}}]}


class TwoCardCorrection(unittest.TestCase):
    def test_only_checked_sentences_change_and_correction_is_idempotent(self):
        for mid in fix.TARGETS:
            with self.subTest(mid=mid):
                row = live_message(mid)
                old = copy.deepcopy(row)
                card = fix.corrected(row)
                self.assertEqual(row, old)
                for before, after in fix.TARGETS[mid]['replace']:
                    self.assertNotIn(before, card['description'])
                    self.assertEqual(card['description'].count(after), 1)
                self.assertEqual(card['timestamp'], old['embeds'][0]['timestamp'])
                self.assertEqual(card['fields'], old['embeds'][0]['fields'])
                self.assertEqual(card['footer']['text'], '台灣時間｜不構成投資建議' + fix.FOOTER_NOTE)
                rest = lambda text: [line for line in text.split('\n') if not any(b in line or a in line for b, a in fix.TARGETS[mid]['replace'])]
                self.assertEqual(rest(card['description']), rest(old['embeds'][0]['description']))
                self.assertEqual(fix.corrected({**row, 'embeds': [card]}), card)

    def test_corrected_copy_passes_the_new_guards(self):
        card = fix.corrected(live_message('1574757663424909334'))
        self.assertIsNone(fund_flow_price_issue(IBIT + " despite continued Bitcoin ETF withdrawals that pushed November's net outflows to $4.71 billion", card['description']))
        card = fix.corrected(live_message('1574757664569827369'))
        self.assertIsNone(unverified_name_gloss(MEGA, card['description']))
        self.assertNotIn('兆芯', card['description'])

    def test_unexpected_targets_layouts_and_changed_text_are_not_written(self):
        good = live_message('1574757663424909334')
        wrong_channel = copy.deepcopy(good); wrong_channel['channel_id'] = '1560822835826532432'
        no_link = copy.deepcopy(good); no_link['embeds'][0]['description'] = no_link['embeds'][0]['description'].replace('bitcoin-etfs-bleed-ibit-shares-gain', 'other')
        changed = copy.deepcopy(good); changed['embeds'][0]['description'] = changed['embeds'][0]['description'].replace('47.1億', '47.2億')
        doubled = copy.deepcopy(good); doubled['embeds'][0]['description'] += '\n' + fix.TARGETS[good['id']]['replace'][0][0]
        two_embeds = copy.deepcopy(good); two_embeds['embeds'].append({})
        marked_but_old = copy.deepcopy(good); marked_but_old['embeds'][0]['footer']['text'] += fix.FOOTER_NOTE
        for row in ({**good, 'id': 'other'}, wrong_channel, no_link, changed, doubled, two_embeds, marked_but_old):
            with self.subTest(row=row['id']):
                with self.assertRaises(ValueError):
                    fix.corrected(row)

    def test_requests_are_limited_to_reading_and_patching_the_two_targets(self):
        for method, suffix in (('DELETE', '/messages/1574757663424909334'), ('POST', ''),
                               ('PATCH', '/messages/1567872306389458985'), ('PATCH', '')):
            with self.subTest(method=method, suffix=suffix):
                with self.assertRaises(ValueError):
                    fix.checked_request('https://example.invalid', method, suffix, opener=lambda *a, **k: None)


if __name__ == '__main__':
    unittest.main()
