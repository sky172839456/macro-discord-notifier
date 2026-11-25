"""Claude Code v2.1.328: "sessions with no permission mode start in it" = start in auto mode."""
import os
import unittest
from unittest.mock import patch

import news_auto_recovery as auto
from material_source_copy import excerpt_parts, release_parts
from news_copy_terms import repair_translation

BULLET = ("Added auto mode for Claude Opus 4.6 and Sonnet 4.6 on Amazon Bedrock, Google Cloud's Agent Platform, "
          "Microsoft Foundry and Claude apps gateway; interactive sessions with no permission mode start in it")
HEAD = ('新增 Amazon Bedrock、Google Cloud 的 Agent Platform、Microsoft Foundry 和 Claude 應用程式閘道上 '
        'Claude Opus 4.6 和 Sonnet 4.6 的自動模式；')
GOOD = HEAD + '未指定權限模式的互動式工作階段會以自動模式啟動'


class PermissionModeCopyTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '1'})
        env.start()
        self.addCleanup(env.stop)

    def test_release_bullet_reaches_copy_check_whole(self):
        row = {'source': 'Claude Code Releases', 'summary_parts': release_parts('<ul><li>'+BULLET+'</li></ul>')}
        self.assertEqual(excerpt_parts(row), [BULLET])

    def test_correct_copy_is_kept(self):
        self.assertEqual(auto.checked_copy(BULLET, GOOD), GOOD)

    def test_noun_and_pronoun_are_repaired_to_unspecified_mode_starting_in_auto_mode(self):
        for bad in (HEAD+'無權限模式的互動式工作階段會在其中啟動',
                    HEAD+'沒有權限模式的互動式工作階段以此模式啟動',
                    HEAD+'無權限模式的互動式工作階段會從它開始'):
            with self.subTest(bad=bad):
                copy = auto.checked_copy(BULLET, bad)
                self.assertNotIn('無權限模式', copy)
                self.assertNotIn('沒有權限模式', copy)
                self.assertRegex(copy, r'未指定權限模式的互動式工作階段(?:會)?以自動模式(?:啟動|開始)')

    def test_wrong_antecedent_or_approval_free_mode_is_rejected(self):
        for bad in (HEAD+'互動式工作階段會以無權限模式啟動',           # sessions start in an invented mode
                    HEAD+'未指定權限模式的互動式工作階段會從那裡啟動',   # "it" left unresolved
                    HEAD+'互動式工作階段在沒有權限時會自動執行',         # relation lost entirely
                    HEAD+'無權限模式的互動式工作階段在其中啟動，免審核執行操作'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                auto.checked_copy(BULLET, bad)

    def test_unrelated_permission_and_negation_sources_are_untouched(self):
        cases = (
            ("Self-hosted runner: Added a start-up warning when the host's settings.json sets a default permission mode that sessions ignore",
             '自架執行器：主機的 settings.json 設定了工作階段會忽略的預設權限模式時，新增啟動警告'),
            ('Fixed a crash when a user has no permission to read the file', '修正使用者沒有權限讀取檔案時的當機問題'),
            ('Sessions with no network access start offline', '沒有網路存取的工作階段會離線啟動'),
        )
        for source, copy in cases:
            with self.subTest(source=source):
                self.assertEqual(repair_translation(source, copy), copy)


if __name__ == '__main__':
    unittest.main()
