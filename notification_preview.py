"""Send normalized previews for every production notification channel."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
MAX_EMBEDS_PER_MESSAGE = 10

CHANNEL_PREVIEWS: tuple[dict[str, Any], ...] = (
    {
        "key": "macro_alerts",
        "channel": "總經通知",
        "icon": "🔴",
        "color": 0xE74C3C,
        "summary": "美國 CPI 公布結果",
        "details": "實際值 `2.7%`｜前值 `2.9%`｜前值修正 `2.8%`",
        "timing": "官方發布：08/12 20:30｜機器人發現：08/12 20:31",
        "source": "BLS 官方資料（範例）",
    },
    {
        "key": "exchange_listings",
        "channel": "上幣通知",
        "icon": "🟢",
        "color": 0x2ECC71,
        "summary": "Bitget｜現貨上幣",
        "details": "交易對：`EXAMPLE/USDT`｜開放交易：07/29 18:00",
        "timing": "官網標示：07/29 17:00｜機器人發現：07/29 17:02",
        "source": "交易所官方公告（範例）",
    },
    {
        "key": "breaking_news",
        "channel": "重大快訊",
        "icon": "🚨",
        "color": 0xE74C3C,
        "summary": "大型交易所暫停部分提領服務",
        "details": "事件仍在調查中；通知只整理已確認事實，不加入價格推測。",
        "timing": "官方更新：07/29 14:20｜機器人發現：07/29 14:22",
        "source": "官方公告與可信新聞來源（範例）",
    },
    {
        "key": "market_risk",
        "channel": "市場風險",
        "icon": "⚠️",
        "color": 0xF1C40F,
        "summary": "USDT 短暫偏離美元錨定",
        "details": "目前價格 `$0.9920`｜警戒門檻 `$0.9950`｜狀態：持續監控",
        "timing": "監測時間：07/29 14:25｜更新頻率：約 5 分鐘",
        "source": "公開行情及交易所官方狀態（範例）",
    },
    {
        "key": "derivatives",
        "channel": "衍生品警報",
        "icon": "📈",
        "color": 0xE67E22,
        "summary": "BTC 未平倉量快速增加",
        "details": "價格 `+2.1%`｜OI `+11.8%`｜資金費率 `+0.0120%`",
        "timing": "觀察區間：最近 60 分鐘｜發現時間：07/29 14:30",
        "source": "OKX 公開市場資料（範例）",
    },
    {
        "key": "crypto_news",
        "channel": "加密新聞",
        "icon": "📰",
        "color": 0x3498DB,
        "summary": "機構宣布擴大數位資產服務",
        "details": "• 已確認：服務範圍擴大\n• 待確認：實際上線地區\n• 市場意義：可能提高合規資金參與度",
        "timing": "原文發布：07/29 13:00｜機器人發現：07/29 13:04",
        "source": "原始報導與官方資料（範例）",
    },
    {
        "key": "exchange_announcements",
        "channel": "交易所公告",
        "icon": "🛠️",
        "color": 0x3498DB,
        "summary": "OKX｜錢包維護與充提調整",
        "details": "影響範圍：範例網路｜預計恢復：官方確認後另行通知",
        "timing": "官網標示：07/29 12:00｜機器人發現：07/29 12:03",
        "source": "交易所官方公告（範例）",
    },
    {
        "key": "regulation_etf",
        "channel": "監管與etf",
        "icon": "🏛️",
        "color": 0x9B59B6,
        "summary": "監管機關公布數位資產 ETF 文件更新",
        "details": "類型：ETF／監管｜進度：文件更新｜尚不代表已正式核准",
        "timing": "文件日期：07/29｜機器人發現：07/29 11:15",
        "source": "監管機關、ETF 發行商或交易所文件（範例）",
    },
    {
        "key": "macro_analysis",
        "channel": "總體經濟",
        "icon": "🌐",
        "color": 0x3498DB,
        "summary": "每日傳統市場與未來三日事件",
        "details": "DXY `+0.20%`｜美債 10Y `-3.0 bp`｜Nasdaq `+0.80%`",
        "timing": "每日更新：08:00 後｜時區：Asia/Taipei",
        "source": "官方行事曆與公開市場資料（範例）",
    },
    {
        "key": "technical_analysis",
        "channel": "技術分析",
        "icon": "📊",
        "color": 0x5865F2,
        "summary": "BTC／ETH 每日技術狀態",
        "details": "BTC：價格位於 SMA20 上方，RSI `58.4`\nETH：區間整理，RSI `49.7`",
        "timing": "每日更新：08:00 後｜K 線週期：日線",
        "source": "OKX 公開 K 線資料（範例）",
    },
    {
        "key": "daily_market",
        "channel": "每日市場重點",
        "icon": "🗓️",
        "color": 0x9B59B6,
        "summary": "價格、衍生品、ETF、總經與風險摘要",
        "details": "BTC `+1.2%`｜ETF 淨流入 `$120M`｜24h 清算 `$85M`",
        "timing": "每日固定摘要｜資料截止：07/29 07:30",
        "source": "多個免費公開來源彙整（範例）",
    },
    {
        "key": "weekly_market",
        "channel": "每週市場摘要",
        "icon": "📅",
        "color": 0x9B59B6,
        "summary": "本週市場表現與下週風險展望",
        "details": "BTC `+4.5%`｜ETH `+2.8%`｜本週 ETF 淨流入 `$430M`",
        "timing": "每週一更新｜統計最近七日及五個 ETF 交易日",
        "source": "多個免費公開來源彙整（範例）",
    },
)


def preview_embed(item: dict[str, Any], now: datetime) -> dict[str, Any]:
    local = now.astimezone(TAIPEI)
    return {
        "author": {"name": "NOTIFICATION QA｜全頻道通知驗收"},
        "title": f"🧪 測試｜{item['icon']} #{item['channel']}",
        "description": "這是統一版面範例，所有事件、時間與數值均為測試資料。",
        "color": item["color"],
        "fields": [
            {"name": "📌 通知重點", "value": f"**{item['summary']}**\n{item['details']}", "inline": False},
            {"name": "🕒 時間資訊（台灣）", "value": item["timing"], "inline": False},
            {"name": "🔗 資料來源", "value": item["source"], "inline": False},
            {"name": "✅ 測試狀態", "value": "版面預覽成功｜未送往正式頻道", "inline": False},
        ],
        "footer": {
            "text": f"測試通知｜只送 #測試通知｜產生時間 {local:%Y/%m/%d %H:%M}｜不構成投資建議"
        },
        "timestamp": now.isoformat(),
    }


def preview_embeds(now: datetime) -> list[dict[str, Any]]:
    return [preview_embed(item, now) for item in CHANNEL_PREVIEWS]


def payload_batches(now: datetime) -> list[dict[str, Any]]:
    embeds = preview_embeds(now)
    batches = []
    total = (len(embeds) + MAX_EMBEDS_PER_MESSAGE - 1) // MAX_EMBEDS_PER_MESSAGE
    for index in range(0, len(embeds), MAX_EMBEDS_PER_MESSAGE):
        batch_number = index // MAX_EMBEDS_PER_MESSAGE + 1
        batches.append({
            "username": "通知格式驗收",
            "content": (
                f"🧪 **全頻道通知版面驗收（{batch_number}/{total}）**\n"
                "以下均為測試資料，不代表真實市場事件。"
            ),
            "embeds": embeds[index:index + MAX_EMBEDS_PER_MESSAGE],
            "allowed_mentions": {"parse": []},
        })
    return batches


def send_payload(webhook: str, payload: dict[str, Any]) -> None:
    request = Request(
        webhook + ("&" if "?" in webhook else "?") + "wait=true",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "notification-preview/1.0"},
        method="POST",
    )
    with urlopen(request, timeout=25):
        pass


def run(now: datetime | None = None) -> int:
    webhook = os.environ.get("DISCORD_TEST_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL；全頻道預覽禁止改送正式頻道")
    current = now or datetime.now(timezone.utc)
    batches = payload_batches(current)
    for payload in batches:
        send_payload(webhook, payload)
    return len(CHANNEL_PREVIEWS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Validate templates without sending")
    args = parser.parse_args()
    if args.dry_run:
        batches = payload_batches(datetime.now(timezone.utc))
        print(f"validated {sum(len(batch['embeds']) for batch in batches)} previews in {len(batches)} batches")
        return
    print(f"sent {run()} previews to the configured test channel")


if __name__ == "__main__":
    main()
