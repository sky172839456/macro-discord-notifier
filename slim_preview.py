"""Private-only examples rendered with the same builders used in production."""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from notification_format import apply_delivery_format
import slim_policy as policy
import slim_risk
import notifier
import risk_notifier


def cards(now):
    event = {"id": "preview-cpi", "time": now + timedelta(minutes=15),
             "rule": {"key": "cpi", "name": "美國消費者物價指數（CPI）", "source": "https://www.bls.gov/cpi/"}}
    dashboard = {"crypto": {"BTC": {"price": 80000., "change_24h": 1.2}, "ETH": {"price": 2500., "change_24h": -.8}},
                 "etf": {"date": now, "net_flow_musd": 120.}, "errors": {}}
    news = {"id": "sample", "title": "Example exchange confirms withdrawals halted after security incident",
            "title_zh": "示例平台確認安全事件，暫停部分提款", "summary": "Withdrawals halted after a security incident.",
            "summary_zh_points": ["示例平台公告部分提款暫停，其他服務影響仍待確認。"],
            "source": "示例來源", "url": "https://example.invalid/notice", "published": now,
            "official": True, "category": {"key": "security", "priority": "critical"}}
    general = [{**news, "title": "Example company adds 250 Bitcoin", "title_zh": "示例公司新增持有 250 枚 BTC",
                "summary": "Example company adds 250 Bitcoin.", "summary_zh_points": ["本則為測試資料；未對實際公司作出陳述。"], "official": False}]
    return [
        ("daily_market", policy.summary_card("daily", now, None, None, [event], None, dashboard)),
        ("macro_alerts", notifier.pre_embed(event, minutes_until=15)),
        ("macro_alerts", notifier.release_embed({"published": now, "url": event["rule"]["source"], "rule": event["rule"], "summary": "The Consumer Price Index increased 0.2 percent in the month and 2.7 percent over the last 12 months."})),
        ("crypto_news", policy.digest_card(general, now)),
        ("breaking_news", policy.news_card(news)),
        ("market_risk", slim_risk.price_card("USDC", {"CoinGecko": .992, "Kraken": .993}, "warning", now)),
        ("market_risk", slim_risk.price_card("USDC", {"CoinGecko": .999, "Kraken": 1.}, "recovered", now)),
    ]


def run(dry_run=False):
    os.environ["SLIM_NOTIFICATIONS"] = "1"
    target = os.getenv("DISCORD_TEST_WEBHOOK_URL")
    if not target and not dry_run:
        raise RuntimeError("私人測試 Webhook 未設定；禁止改送正式頻道")
    now = datetime.now(timezone.utc)
    output = []
    for key, card in cards(now):
        card["title"] = "🧪 精簡版預覽｜" + card["title"]
        card["description"] = "**以下皆為虛構測試資料。**\n" + card.get("description", "")
        output.append(apply_delivery_format(card, key))
    if dry_run:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return
    for card in output:
        payload = {"username": "WM Viewture｜精簡版測試", "embeds": [card], "allowed_mentions": {"parse": []}}
        req = Request(target + ("&" if "?" in target else "?") + "wait=true", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "macro-discord-notifier/slim-preview-1.0"}, method="POST")
        with urlopen(req, timeout=30):
            pass
    print(f"已送出 {len(output)} 張私人預覽卡；未讀取正式推播 Webhook。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    run(parser.parse_args().dry_run)
