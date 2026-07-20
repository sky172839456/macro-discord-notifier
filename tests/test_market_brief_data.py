import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import market_brief_data
from market_brief_data import collect_dashboard, parse_farside_latest
from summary_notifier import build_embed, flow_lines, risk_summary


class MarketBriefDataTests(unittest.TestCase):
    def test_parses_latest_farside_total_and_parentheses(self):
        source = """
        <table>
          <tr><td>16 Jul 2026</td><td>33.4</td><td>79.1</td></tr>
          <tr><td>17 Jul 2026</td><td>136.5</td><td>(132.3)</td></tr>
          <tr><td>Total</td><td>51,405</td></tr>
        </table>
        """
        result = parse_farside_latest(source)
        self.assertEqual(result["date"].date().isoformat(), "2026-07-17")
        self.assertEqual(result["net_flow_musd"], -132.3)

    def test_partial_source_failure_does_not_abort_dashboard(self):
        with patch.object(market_brief_data, "crypto_snapshot", return_value=({"BTC": {}}, {"USDT": 1})), \
             patch.object(market_brief_data, "global_snapshot", side_effect=RuntimeError("blocked")), \
             patch.object(market_brief_data, "derivatives_snapshot", return_value={}), \
             patch.object(market_brief_data, "fear_greed_snapshot", return_value={}), \
             patch.object(market_brief_data, "traditional_snapshot", return_value={}), \
             patch.object(market_brief_data, "etf_flow_snapshot", return_value={}), \
             patch.object(market_brief_data, "liquidation_snapshot", return_value={}), \
             patch.object(market_brief_data, "exchange_risk_snapshot", return_value={}):
            result = collect_dashboard(datetime(2026, 7, 20, tzinfo=timezone.utc))
        self.assertIsNotNone(result["crypto"])
        self.assertIsNone(result["global"])
        self.assertEqual(result["errors"]["global"], "RuntimeError")

    def test_flow_copy_states_okx_scope_and_etf_date(self):
        dashboard = {
            "errors": {},
            "etf": {"date": datetime(2026, 7, 17, tzinfo=timezone.utc), "net_flow_musd": 132.3},
            "eth_etf": {"date": datetime(2026, 7, 17, tzinfo=timezone.utc), "net_flow_musd": -36.7},
            "liquidations": {"scope": "OKX BTC／ETH USDT 永續", "total_usd": 3_000_000,
                             "long": 2_000_000, "short": 1_000_000},
        }
        text = flow_lines(dashboard)
        self.assertIn("07/17", text)
        self.assertIn("淨流入", text)
        self.assertIn("ETH ETF", text)
        self.assertIn("淨流出", text)
        self.assertIn("OKX BTC／ETH USDT 永續", text)

    def test_risk_summary_is_deterministic_and_flags_extremes(self):
        dashboard = {
            "errors": {},
            "sentiment": {"value": 20},
            "derivatives": {"BTC": {"funding_rate": 0.08}},
            "stablecoins": {"USDT": 0.99, "USDC": 1.0},
            "exchange_risk": {"active_count": 1},
        }
        text = risk_summary(dashboard, [], None)
        self.assertIn("極度恐慌", text)
        self.assertIn("資金費率偏高", text)
        self.assertIn("USDT", text)

    def test_rich_embed_contains_requested_sections(self):
        dashboard = {
            "errors": {"traditional": "TimeoutError"},
            "crypto": {symbol: {"price": 1, "change_24h": 1, "high_24h": 2, "low_24h": 0.5,
                                "volume_24h": 10} for symbol in ("BTC", "ETH")},
            "stablecoins": {"USDT": 1, "USDC": 1},
            "global": {"market_cap": 100, "volume_24h": 10, "btc_dominance": 50,
                       "market_cap_change_24h": 1},
            "derivatives": {symbol: {"oi_usd": 100, "funding_rate": 0.01,
                                      "next_funding": 1784563200000} for symbol in ("BTC", "ETH")},
            "sentiment": {"value": 50, "classification": "Neutral"},
            "traditional": None,
            "etf": {"date": datetime(2026, 7, 17, tzinfo=timezone.utc), "net_flow_musd": 10},
            "eth_etf": {"date": datetime(2026, 7, 17, tzinfo=timezone.utc), "net_flow_musd": -5},
            "liquidations": {"scope": "OKX BTC／ETH USDT 永續", "total_usd": 3, "long": 2, "short": 1},
            "exchange_risk": {"active_count": 0, "names": []},
        }
        embed = build_embed("daily", datetime(2026, 7, 20, tzinfo=timezone.utc), None, None, [], None, dashboard)
        names = "\n".join(field["name"] for field in embed["fields"])
        self.assertIn("未來三日重要總經事件", names)
        for expected in ("價格與成交", "衍生品", "市場廣度", "傳統市場", "穩定幣", "ETF", "風險摘要"):
            self.assertIn(expected, names)
        self.assertLessEqual(len(embed["fields"]), 25)
        self.assertTrue(all(len(field["name"]) <= 256 for field in embed["fields"]))
        self.assertTrue(all(len(field["value"]) <= 1024 for field in embed["fields"]))
        total_chars = len(embed["title"]) + len(embed["description"])
        total_chars += sum(len(field["name"]) + len(field["value"]) for field in embed["fields"])
        self.assertLessEqual(total_chars, 6000)


if __name__ == "__main__":
    unittest.main()
