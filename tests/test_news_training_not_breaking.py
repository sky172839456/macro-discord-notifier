"""2026-11-24 CertiK 培訓國際刑警組織被當成【重大快訊】資安事件。

培訓、研討會、合作或活動公告只是在談資安，不是新事故；真正的新駭侵、凍結、扣押、追回照舊走重大快訊。
門檻與每日額度不變，也不把所有教育題材一律排除。
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import crypto_news_notifier as news
import news_auto_recovery as auto
import news_editorial as editorial
import slim_policy

CERTIK_TITLE = 'CertiK Trains Interpol Investigators to Trace and Freeze Stolen Crypto'
CERTIK_SUMMARY = ('The blockchain security firm walked officers from across Asia and the South Pacific '
                  'through a real wallet-theft case at a workshop in Hanoi.')

NOT_BREAKING = (
    # 本次實例（Decrypt 2026-11-24 13:46 UTC）
    (CERTIK_TITLE, CERTIK_SUMMARY),
    # 教學重演舊攻擊
    ('Chainalysis workshop walks police through Ronin bridge hack',
     'Investigators retraced how attackers drained $600 million in crypto from the bridge three years ago in a training exercise.'),
    ('Elliptic workshop re-enacts Ronin bridge crypto hack for police',
     'Officers followed how hackers stole $600 million and how exchanges froze $30 million of it.'),
    # 合作／活動公告
    ('Binance partners with Interpol to fight crypto hacks and theft',
     'The exchange will share threat intelligence and fund training for officers investigating stolen funds.'),
    ('TRM Labs hosts summit on tracing hacked crypto for law enforcement',
     'Officers from 30 countries attended sessions on tracking stolen funds across bridges.'),
    # 標題借用 trace／freeze 字眼的培訓
    ('Elliptic teaches police to trace and freeze stolen crypto',
     'The course covers wallet clustering, exchange freeze requests and how hackers launder funds.'),
)

STILL_BREAKING = (
    # 真正的新駭侵
    ('DeFi lender Acme drained of $40 million in exploit',
     'Attackers stole $40 million from the protocol on Tuesday and withdrawals are paused.'),
    ('Bitget halts withdrawals after suspected breach',
     'Bitget halted withdrawals after a suspected breach.'),
    # 標題剛好有 training 字眼，但同篇是新事故
    ('Exchange Acme hacked after staff opened fake training invite',
     'Acme confirmed a breach on Monday and said hackers drained $8 million from a hot wallet.'),
    # 真正的新凍結／扣押／追回
    ('Tether freezes $12 million in USDT linked to Bybit hack',
     'Tether froze the stolen funds after investigators traced them to wallets tied to the attackers.'),
    ('Police seize $5 million in stolen crypto from phishing gang',
     'Authorities said the stolen bitcoin was recovered from wallets controlled by the suspects.'),
    ('Authorities recover $3 million stolen in exchange hack',
     'Police returned the stolen crypto to the exchange on Wednesday.'),
    # 合作字眼＋同篇有具體凍結金額
    ('Tether teams up with TRON and TRM Labs to freeze $12 million in stolen USDT',
     'The T3 Financial Crime Unit froze $12 million tied to a phishing scam this week.'),
)


class TrainingIsNotBreakingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 13, 49, tzinfo=timezone.utc)  # 台灣 11/24（二）21:49
        env = patch.dict(os.environ, {'SLIM_NOTIFICATIONS': '1', 'NEWS_AUTO_RECOVERY': '1', 'NEWS_SPLIT_STREAMS': '1',
            'DISCORD_CRYPTO_NEWS_WEBHOOK_URL': 'https://crypto.invalid',
            'DISCORD_FINANCE_NEWS_WEBHOOK_URL': 'https://finance.invalid',
            'DISCORD_LOG_WEBHOOK_URL': 'https://admin.invalid'})
        env.start(); self.addCleanup(env.stop)

    def row(self, title, summary, key='a', **extra):
        text = title + ' ' + summary
        return {'id': key, 'title': title, 'summary': summary, 'published': self.now - timedelta(minutes=3),
                'url': 'https://example.invalid/' + key, 'source': 'Decrypt', 'official': False,
                'category': news.category_for(text), **extra}

    def test_training_workshop_partnership_not_breaking_in_both_modes(self):
        for mode in ('1', '0'):
            with patch.dict(os.environ, {'NEWS_AUTO_RECOVERY': mode}):
                for title, summary in NOT_BREAKING:
                    with self.subTest(mode=mode, title=title):
                        row = self.row(title, summary)
                        self.assertTrue(editorial.training_or_event_only(row))
                        self.assertFalse(editorial.safety_candidate(row))
                        self.assertNotEqual(editorial.event_kind(row), 'safety')
                        self.assertFalse(slim_policy.material_news(row))
                        self.assertNotEqual(row['category']['priority'], 'critical')
                        self.assertNotIn('🚨', slim_policy.news_card(
                            {**row, 'title_zh': '來源發布新消息', 'summary_zh_points': ['來源發布新消息。']}, now=self.now)['title'])

    def test_real_new_hack_freeze_seizure_recovery_still_breaking_in_both_modes(self):
        for mode in ('1', '0'):
            with patch.dict(os.environ, {'NEWS_AUTO_RECOVERY': mode}):
                for title, summary in STILL_BREAKING:
                    with self.subTest(mode=mode, title=title):
                        row = self.row(title, summary)
                        self.assertFalse(editorial.training_or_event_only(row))
                        self.assertTrue(editorial.safety_candidate(row))
                        self.assertEqual(editorial.event_kind(row), 'safety')
                        self.assertTrue(slim_policy.material_news(row))
                        self.assertEqual(row['category']['key'], 'security')
                        self.assertEqual(row['category']['priority'], 'critical')

    def test_certik_feed_row_keeps_normal_priority_and_is_screened_by_existing_score(self):
        rss = ('<rss><channel><item><title>' + CERTIK_TITLE + '</title><description>' + CERTIK_SUMMARY +
               '</description><link>https://decrypt.co/383857/certik-trains-interpol-investigators-to-trace-and-freeze-stolen-crypto</link>'
               '<pubDate>Tue, 24 Nov 2026 13:46:03 +0000</pubDate></item></channel></rss>')
        rows = news.parse_feed(rss, {'name': 'Decrypt', 'official': False})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['category']['priority'], 'normal')
        # 不再是重大快訊後，照既有一般新聞分數（20 < 40）不進成員頻道；門檻沒有改。
        self.assertEqual(auto.selection_reason(rows[0], self.now), '缺少重要事件進展')

    def test_production_path_certik_not_sent_but_new_incident_still_breaking(self):
        def run(rows, state):
            with patch.object(news, 'load_state', return_value=state), patch.object(news, 'save_state'), \
                 patch.object(news, 'fetch_all', return_value=(rows, [('mock', len(rows), None)])), \
                 patch('news_streams.fetch_finance', return_value=([], [('finance', 0, None)])), \
                 patch.object(news, 'send_discord') as send:
                news.run(self.now)
            return send

        state = {'initialized': True, 'finance_initialized': True, 'seen': {}, 'pending': []}
        certik = self.row(CERTIK_TITLE, CERTIK_SUMMARY, key='certik',
                          title_zh='CertiK 培訓國際刑警組織調查人員追蹤並凍結被盜加密資產',
                          summary_zh_points=['這家區塊鏈安全公司在河內舉辦的研討會上，向來自亞洲和南太平洋的執法人員講解了一個真實的錢包盜竊案例。'],
                          auto_copy_version=2)
        run([certik], state).assert_not_called()
        self.assertEqual(state['news_auto_ignored']['certik']['reason'], '缺少重要事件進展')
        self.assertNotIn('certik', state['seen'])

        state = {'initialized': True, 'finance_initialized': True, 'seen': {}, 'pending': []}
        hack = self.row('Bitget halts withdrawals after suspected breach', 'Bitget halts withdrawals after suspected breach',
                        key='hack', title_zh='Bitget 因疑似入侵暫停提款', summary_zh_points=['Bitget 因疑似入侵暫停提款'],
                        auto_copy_version=2)
        send = run([hack], state)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], 'https://crypto.invalid')
        self.assertTrue(send.call_args.args[1]['title'].startswith('【重大快訊】 🚨 快訊｜'))


if __name__ == '__main__':
    unittest.main()
