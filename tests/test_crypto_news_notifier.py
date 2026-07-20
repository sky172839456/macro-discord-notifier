import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crypto_news_notifier import (SOURCES, canonical_url, category_for, connectivity_embed,
                                  deduplicate, is_relevant, news_embed, normalize_zh_title,
                                  parse_feed, send_discord, similar_title)


class CryptoNewsTests(unittest.TestCase):
    def test_sources_include_media_and_official(self):
        self.assertGreaterEqual(sum(not source["official"] for source in SOURCES), 3)
        self.assertTrue(any(source["official"] for source in SOURCES))

    def test_filters_predictions_and_keeps_material_news(self):
        self.assertTrue(is_relevant("SEC approves a spot Bitcoin ETF"))
        self.assertFalse(is_relevant("Bitcoin price prediction could reach a new high"))

    def test_security_has_highest_priority(self):
        category = category_for("Exchange hacked after wallet exploit")
        self.assertEqual(category["key"], "security")
        self.assertEqual(category["priority"], "critical")

    def test_tracking_parameters_are_removed(self):
        self.assertEqual(canonical_url("https://EXAMPLE.com/a/?utm_source=x&id=1"), "https://example.com/a?id=1")

    def test_similar_headlines_are_deduplicated(self):
        self.assertTrue(similar_title(
            "SEC approves spot Bitcoin ETF after court decision",
            "SEC approves a spot Bitcoin ETF following court decision",
        ))
        now = datetime.now(timezone.utc)
        category = category_for("SEC regulation of crypto")
        rows = [
            {"id": "media", "title": "SEC approves spot Bitcoin ETF after court decision", "published": now,
             "official": False, "category": category},
            {"id": "official", "title": "SEC approves a spot Bitcoin ETF following court decision", "published": now,
             "official": True, "category": category},
        ]
        self.assertEqual(deduplicate(rows)[0]["id"], "official")

    def test_rss_parser_keeps_original_title_and_category(self):
        rss = """<rss><channel><item><title>SEC approves spot Bitcoin ETF</title>
        <description>Regulator approves a digital asset exchange-traded fund.</description>
        <link>https://example.com/story?utm_source=rss</link>
        <pubDate>Mon, 20 Jul 2026 12:00:00 GMT</pubDate></item></channel></rss>"""
        source = {"name": "Test", "url": "https://example.com/feed", "official": False}
        item = parse_feed(rss, source)[0]
        self.assertEqual(item["title"], "SEC approves spot Bitcoin ETF")
        self.assertEqual(item["category"]["key"], "regulation")
        self.assertEqual(item["url"], "https://example.com/story")

    def test_embed_distinguishes_fact_and_impact(self):
        now = datetime.now(timezone.utc)
        item = {"id": "x", "title": "Exchange confirms wallet exploit", "summary": "Official update.",
                "url": "https://example.com/x", "published": now, "source": "Official", "official": True,
                "category": category_for("wallet exploit hacked")}
        embed = news_embed(item)
        self.assertIn("繁體中文重點", embed["description"])
        self.assertIn("可能影響", embed["description"])
        self.assertEqual(embed["fields"][0]["value"], "✅ 官方確認")

    def test_embed_shows_chinese_and_original_headlines(self):
        now = datetime.now(timezone.utc)
        item = {"id": "x", "title": "SEC approves spot Bitcoin ETF", "title_zh": "SEC 核准現貨 Bitcoin ETF",
                "summary": "Official update.", "url": "https://example.com/x", "published": now,
                "source": "Official", "official": True, "category": category_for("SEC regulation crypto")}
        embed = news_embed(item)
        self.assertIn("### SEC 核准現貨 Bitcoin ETF", embed["description"])
        self.assertIn("英文原標題：SEC approves spot Bitcoin ETF", embed["description"])

    def test_translation_normalizes_common_crypto_names(self):
        self.assertEqual(normalize_zh_title("美國證券交易委員會批准比特幣交易所交易基金"),
                         "SEC 批准 Bitcoin ETF")

    def test_connectivity_card_cannot_be_mistaken_for_news(self):
        embed = connectivity_embed(42, [("CoinDesk", 10, None)], datetime.now(timezone.utc))
        self.assertIn("正式連線成功", embed["title"])
        self.assertIn("不會把舊文章洗進正式頻道", embed["description"])
        self.assertIn("這不是新聞公告", embed["footer"]["text"])

    def test_discord_post_uses_accepted_request_format(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False

        with patch("crypto_news_notifier.urlopen", return_value=Response()) as mocked:
            send_discord("https://discord.com/api/webhooks/test/token", {"title": "test"})
        request = mocked.call_args.args[0]
        self.assertTrue(request.full_url.endswith("?wait=true"))
        self.assertEqual(request.get_header("User-agent"), "macro-discord-notifier/2.0")


if __name__ == "__main__":
    unittest.main()
