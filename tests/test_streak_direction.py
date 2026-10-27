import unittest
from news_auto_recovery import checked_copy
from news_streak_guard import TITLE


class StreakDirectionTests(unittest.TestCase):
    def test_actual_formal_reversal_is_repaired_before_guard(self):
        result=checked_copy(TITLE,'儘管週末下跌，但 Bitcoin ETF 卻連續兩週虧損')
        self.assertIn('結束連兩週頹勢',result)
        self.assertNotIn('連續兩週虧損',result)

    def test_other_streak_directions_cannot_pass_as_continuation(self):
        for source,copy in [('Bitcoin ETFs end three-week losing streak','比特幣ETF連三週虧損'),
                            ('Bitcoin ETFs end two-week winning streak','比特幣ETF結束連兩週跌勢'),
                            ('Bitcoin ETFs snap three-week losing streak','比特幣ETF結束連兩週跌勢')]:
            with self.subTest(source=source),self.assertRaises(ValueError):checked_copy(source,copy)

    def test_qualifications_and_failed_attempts_not_rewritten_as_success(self):
        for source,copy in [('Bitcoin ETFs may end three-week losing streak','比特幣ETF結束連三週跌勢'),
                            ('Bitcoin ETFs fail to end three-week losing streak','比特幣ETF結束連三週跌勢')]:
            with self.subTest(source=source),self.assertRaises(ValueError):checked_copy(source,copy)
        self.assertIn('可能',checked_copy('Bitcoin ETFs may end three-week losing streak','比特幣ETF可能結束連三週跌勢'))

    def test_continuation_and_non_financial_snap_are_unchanged(self):
        for source,copy in [('Bitcoin ETFs extend three-week losing streak','比特幣ETF延續連三週淨流出'),
                            ('Camera makers snap photos of Bitcoin miners','相機廠商拍攝比特幣礦工照片')]:
            self.assertEqual(checked_copy(source,copy),copy)
