"""Keep publisher-marked CLI literals through release intake and translation."""
import json
import os
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import content_contract as contract
import crypto_news_notifier as news
import news_auto_recovery as auto
from material_inbox import parse_source_feed
from material_source_copy import display_points, excerpt_parts, release_parts


OFFICIAL_FIRST = (
    "Added sign-in to organizations managed in Anthropic's Enterprise Admin Console: "
    "after <code>claude auth login</code>, Claude Code applies the organization's settings "
    "and uses its cloud provider or gateway"
)
GOOD_FIRST = (
    '\u65b0\u589e\u767b\u5165 Anthropic Enterprise Admin Console \u7ba1\u7406\u7684\u7d44\u7e54\uff1a'
    '\u5728 `claude auth login` \u4e4b\u5f8c\uff0cClaude Code \u6703\u5957\u7528\u7d44\u7e54\u8a2d\u5b9a\uff0c'
    '\u4e26\u4f7f\u7528\u5176\u96f2\u7aef\u4f9b\u61c9\u5546\u6216\u9598\u9053\u3002'
)


class MaterialCliLiteralTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'CONTENT_PREFLIGHT_STRICT': '1'})
        env.start()
        self.addCleanup(env.stop)

    def test_real_release_command_cannot_be_translated_into_prose(self):
        source, = release_parts('<ul><li>'+OFFICIAL_FIRST+'</li></ul>')
        self.assertIn('`claude auth login`', source)
        self.assertIn('claude auth login', auto.checked_copy(source, GOOD_FIRST))
        bad_copies = (GOOD_FIRST.replace('`claude auth login`', 'claude \u8eab\u5206\u9a57\u8b49\u767b\u5165'),
                      GOOD_FIRST.replace('auth login', 'auth logout'))
        for bad in bad_copies:
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'code_identifier_missing'):
                auto.checked_copy(source, bad)

    def test_atom_intake_preserves_command_and_excerpt_provenance(self):
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>v2.1.330</title>'
               '<link href="https://github.com/anthropics/claude-code/releases/tag/v2.1.330"/>'
               '<published>2026-11-20T22:32:56Z</published><content type="html"><![CDATA['
               '<ul><li>'+OFFICIAL_FIRST+'</li></ul>]]></content></entry></feed>')
        row, = parse_source_feed(xml, 'Claude Code Releases', 'github.com')
        source, = excerpt_parts(row)
        self.assertIn('`claude auth login`', source)
        masked, mapping = contract.protect(source)
        masked_copy = GOOD_FIRST
        for label, literal in mapping.items():
            self.assertIn(literal, masked_copy)
            masked_copy = masked_copy.replace(literal, label)
        def response(url, **kwargs):
            self.assertEqual(parse_qs(urlsplit(url).query)['q'][0], masked)
            return json.dumps({'responseStatus': 200, 'responseData': {'translatedText': masked_copy}})
        with patch.object(news, 'http_text', side_effect=response), \
             patch.object(auto, 'translate_bing', side_effect=AssertionError('no fallback needed')):
            translated = auto.translate(source)
        row.update(material_topic='ai', title_zh='Claude Code \u7248\u672c\u66f4\u65b0 v2.1.330',
                   summary_zh_points=[translated])
        contract.stamp(row, [{'source': source, 'zh': translated}])
        self.assertEqual(contract.article_issues(row, required=True), [])
        self.assertIn('`claude auth login`', display_points(row['summary_zh_points']))

    def test_arbitrary_new_command_is_masked_and_restored_before_validation(self):
        source, = release_parts('<li>Use <code>atlas auth enroll</code>.</li>')
        def response(url, **kwargs):
            query = parse_qs(urlsplit(url).query)['q'][0]
            self.assertNotIn('atlas auth enroll', query)
            return json.dumps({'responseStatus': 200, 'responseData': {
                'translatedText': '\u8acb\u4f7f\u7528 '+query.removeprefix('Use ')}})
        with patch.object(news, 'http_text', side_effect=response), \
             patch.object(auto, 'translate_bing', side_effect=AssertionError('no fallback needed')):
            translated = auto.translate(source)
        self.assertIn('`atlas auth enroll`', translated)

    def test_source_metavariables_and_multiple_inline_literals_survive(self):
        source, = release_parts('<li>Use <code>atlas sync &lt;workspace&gt;</code> with <code>--limit 10</code>.</li>')
        self.assertIn('`atlas sync \u3008workspace\u3009`', source)
        self.assertIn('`--limit 10`', source)
        masked, mapping = contract.protect(source)
        self.assertNotIn('atlas sync', masked)
        self.assertEqual(contract.restore(masked, mapping), source)
        with self.assertRaises(ValueError):
            contract.restore(masked.replace(next(iter(mapping)), ''), mapping)

    def test_markdown_link_html_escape_and_semicolon_remain_valid(self):
        source, = release_parts('<li>Use <code>atlas sync &lt;workspace&gt;</code>; '
                                'see [the guide](https://example.com/guide?a=one&amp;b=two).</li>')
        good = ('\u8acb\u4f7f\u7528 `atlas sync \u3008workspace\u3009`\uff1b'
                '\u8acb\u53c3\u95b1[\u4f7f\u7528\u8aaa\u660e](https://example.com/guide?a=one&b=two)\u3002')
        self.assertIn('`atlas sync \u3008workspace\u3009`;', source)
        self.assertIn('?a=one&b=two', source)
        self.assertEqual(auto.checked_copy(source, good), good)

    def test_plain_prose_is_not_rewritten_as_code(self):
        plain = 'Added a warning when managed hooks fail to load.'
        self.assertEqual(release_parts('<li>'+plain+'</li>'), [plain])

    def test_existing_number_and_eligibility_gates_stay_strict(self):
        source, = release_parts('<li>Use <code>atlas sync</code> for $5. Only eligible users can join.</li>')
        good = '\u50c5\u7b26\u5408\u8cc7\u683c\u7684\u4f7f\u7528\u8005\u53ef\u4ee5\u652f\u4ed8 5 \u7f8e\u5143\u4f7f\u7528 `atlas sync`\u3002'
        auto.checked_copy(source, good)
        for bad in (good.replace('5 ', '50 '), good.replace('\u50c5\u7b26\u5408\u8cc7\u683c\u7684', '\u6240\u6709')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                auto.checked_copy(source, bad)

    def test_new_code_boundaries_invalidate_old_source_evidence(self):
        old = {'title': 'Claude Code v2.1.330', 'summary_parts': ['Use atlas auth enroll.']}
        new = dict(old, summary_parts=release_parts('<li>Use <code>atlas auth enroll</code>.</li>'))
        self.assertNotEqual(contract.source_hash(old), contract.source_hash(new))


if __name__ == '__main__':
    unittest.main()
