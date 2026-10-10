"""Read-only webhook destination audit; never print webhook URLs or tokens."""
import json
import os
from urllib.request import Request, urlopen

EXPECTED = {
    "DISCORD_WEBHOOK_URL": "1524973145780654091",
    "DISCORD_LOG_WEBHOOK_URL": "1524973428296257616",
    "DISCORD_TEST_WEBHOOK_URL": "1524973451306340494",
    "DISCORD_EXCHANGE_LISTING_WEBHOOK_URL": "1524973167179993288",
    "DISCORD_CRYPTO_NEWS_WEBHOOK_URL": "1524973208745279660",
    "DISCORD_BREAKING_NEWS_WEBHOOK_URL": "1524973208745279660",
    "DISCORD_REGULATION_ETF_WEBHOOK_URL": "1524973208745279660",
    "DISCORD_EXCHANGE_ANNOUNCEMENT_WEBHOOK_URL": "1524973229804880045",
    "DISCORD_RISK_WEBHOOK_URL": "1524973229804880045",
    "DISCORD_DERIVATIVES_WEBHOOK_URL": "1524973229804880045",
    "DISCORD_DAILY_SUMMARY_WEBHOOK_URL": "1526037827115028622",
    "DISCORD_WEEKLY_SUMMARY_WEBHOOK_URL": "1526037827115028622",
    "DISCORD_MACRO_ANALYSIS_WEBHOOK_URL": "1526037827115028622",
    "DISCORD_TECHNICAL_ANALYSIS_WEBHOOK_URL": "1526037827115028622",
}


def audit(environ=None):
    environ = os.environ if environ is None else environ
    results = []
    for name, expected in EXPECTED.items():
        webhook = environ.get(name)
        if not webhook:
            results.append({"secret": name, "status": "missing"})
            continue
        try:
            request = Request(webhook, headers={"User-Agent": "WM-Viewture-routing-audit/1.0"})
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
            actual = str(payload.get("channel_id", ""))
            results.append({"secret": name, "status": "ok" if actual == expected else "wrong_channel", "channel_id": actual, "expected": expected})
        except Exception as exc:
            results.append({"secret": name, "status": "unverified", "error_type": type(exc).__name__})
    return results


if __name__ == "__main__":
    results = audit()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(row["status"] == "ok" for row in results if row["secret"] != "DISCORD_TEST_WEBHOOK_URL") else 1)
