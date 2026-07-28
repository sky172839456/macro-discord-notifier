"""Send normalized previews for every production notification channel."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from notification_format import standard_fields

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
        "original_title": "Consumer Price Index – July 2026",
        "event_status": "已公布｜實際值與前值均已取得",
        "timing": "官方發布：08/12 20:30｜機器人發現：08/12 20:31",
        "source": "BLS 官方資料（範例）",
        "source_status": "ok",
    },
    {
        "key": "exchange_listings",
        "channel": "上幣通知",
        "icon": "🟢",
        "color": 0x2ECC71,
        "summary": "Bitget｜現貨上幣",
        "details": "交易對：`EXAMPLE/USDT`｜開放交易：07/29 18:00",
        "original_title": "Bitget Will List EXAMPLE (EXAMPLE) for Spot Trading",
        "event_status": "🟢 現貨上幣｜交易時間待官方頁面為準",
        "timing": "官網標示：07/29 17:00｜機器人發現：07/29 17:02",
        "source": "交易所官方公告（範例）",
        "source_status": "ok",
    },
    {
        "key": "breaking_news",
        "channel": "重大快訊",
        "icon": "🚨",
        "color": 0xE74C3C,
        "summary": "大型交易所暫停部分提領服務",
        "details": "事件仍在調查中；通知只整理已確認事實，不加入價格推測。",
        "original_title": "Major Exchange Temporarily Pauses Some Withdrawals",
        "event_status": "🚨 調查中｜尚未宣布完整恢復時間",
        "timing": "官方更新：07/29 14:20｜機器人發現：07/29 14:22",
        "source": "官方公告與可信新聞來源（範例）",
        "source_status": "backup",
        "source_detail": "官方頁面回應較慢，已由可信備援來源交叉確認",
    },
    {
        "key": "market_risk",
        "channel": "市場風險",
        "icon": "⚠️",
        "color": 0xF1C40F,
        "summary": "USDT 短暫偏離美元錨定",
        "details": "目前價格 `$0.9920`｜警戒門檻 `$0.9950`｜狀態：持續監控",
        "original_title": "Stablecoin Price Deviation Alert",
        "event_status": "⚠️ 警戒中｜尚未恢復至正常範圍",
        "timing": "監測時間：07/29 14:25｜更新頻率：約 5 分鐘",
        "source": "公開行情及交易所官方狀態（範例）",
        "source_status": "partial",
        "source_detail": "價格正常取得；其中一個交易所狀態來源暫時缺少",
    },
    {
        "key": "derivatives",
        "channel": "衍生品警報",
        "icon": "📈",
        "color": 0xE67E22,
        "summary": "BTC 未平倉量快速增加",
        "details": "價格 `+2.1%`｜OI `+11.8%`｜資金費率 `+0.0120%`",
        "original_title": "BTC Open Interest Expansion Alert",
        "event_status": "🟠 中度異常｜尚未達最高警戒門檻",
        "timing": "觀察區間：最近 60 分鐘｜發現時間：07/29 14:30",
        "source": "OKX 公開市場資料（範例）",
        "source_status": "ok",
    },
    {
        "key": "crypto_news",
        "channel": "加密新聞",
        "icon": "📰",
        "color": 0x3498DB,
        "summary": "機構宣布擴大數位資產服務",
        "details": "• 已確認：服務範圍擴大\n• 待確認：實際上線地區\n• 市場意義：可能提高合規資金參與度",
        "original_title": "Institution Announces Expansion of Digital Asset Services",
        "event_status": "一般重要新聞｜不屬於重大快訊或監管 ETF",
        "timing": "原文發布：07/29 13:00｜機器人發現：07/29 13:04",
        "source": "原始報導與官方資料（範例）",
        "source_status": "ok",
    },
    {
        "key": "exchange_announcements",
        "channel": "交易所公告",
        "icon": "🛠️",
        "color": 0x3498DB,
        "summary": "OKX｜錢包維護與充提調整",
        "details": "影響範圍：範例網路｜預計恢復：官方確認後另行通知",
        "original_title": "Wallet Maintenance and Deposit/Withdrawal Adjustment",
        "event_status": "🛠️ 維護中｜未列入上幣通知",
        "timing": "官網標示：07/29 12:00｜機器人發現：07/29 12:03",
        "source": "交易所官方公告（範例）",
        "source_status": "ok",
    },
    {
        "key": "regulation_etf",
        "channel": "監管與etf",
        "icon": "🏛️",
        "color": 0x9B59B6,
        "summary": "監管機關公布數位資產 ETF 文件更新",
        "details": "類型：ETF／監管｜進度：文件更新｜尚不代表已正式核准",
        "original_title": "Digital Asset ETF Filing Update",
        "event_status": "🏛️ 文件更新｜尚未正式核准",
        "timing": "文件日期：07/29｜機器人發現：07/29 11:15",
        "source": "監管機關、ETF 發行商或交易所文件（範例）",
        "source_status": "ok",
    },
    {
        "key": "macro_analysis",
        "channel": "總體經濟",
        "icon": "🌐",
        "color": 0x3498DB,
        "summary": "每日傳統市場與未來三日事件",
        "details": "DXY `+0.20%`｜美債 10Y `-3.0 bp`｜Nasdaq `+0.80%`",
        "event_status": "每日觀察｜不是單一事件警報",
        "timing": "每日更新：08:00 後｜時區：Asia/Taipei",
        "source": "官方行事曆與公開市場資料（範例）",
        "source_status": "backup",
        "source_detail": "市場資料正常；行事曆由備援來源補足一項事件",
    },
    {
        "key": "technical_analysis",
        "channel": "技術分析",
        "icon": "📊",
        "color": 0x5865F2,
        "summary": "BTC／ETH 每日技術狀態",
        "details": "BTC：價格位於 SMA20 上方，RSI `58.4`\nETH：區間整理，RSI `49.7`",
        "event_status": "中性偏多｜不是自動買賣訊號",
        "timing": "每日更新：08:00 後｜K 線週期：日線",
        "source": "OKX 公開 K 線資料（範例）",
        "source_status": "ok",
    },
    {
        "key": "daily_market",
        "channel": "每日市場重點",
        "icon": "🗓️",
        "color": 0x9B59B6,
        "summary": "價格、衍生品、ETF、總經與風險摘要",
        "details": "BTC `+1.2%`｜ETF 淨流入 `$120M`｜24h 清算 `$85M`",
        "event_status": "每日彙整｜專屬頻道事件不在此重複逐則發送",
        "timing": "每日固定摘要｜資料截止：07/29 07:30",
        "source": "多個免費公開來源彙整（範例）",
        "source_status": "partial",
        "source_detail": "主要數據正常；其中一項市場廣度資料暫時缺少",
    },
    {
        "key": "weekly_market",
        "channel": "每週市場摘要",
        "icon": "📅",
        "color": 0x9B59B6,
        "summary": "本週市場表現與下週風險展望",
        "details": "BTC `+4.5%`｜ETH `+2.8%`｜本週 ETF 淨流入 `$430M`",
        "event_status": "每週彙整｜統計週期已完成",
        "timing": "每週一更新｜統計最近七日及五個 ETF 交易日",
        "source": "多個免費公開來源彙整（範例）",
        "source_status": "error",
        "source_detail": "錯誤狀態版面範例：來源恢復前不顯示推測數值",
    },
)


def preview_embed(item: dict[str, Any], now: datetime) -> dict[str, Any]:
    local = now.astimezone(TAIPEI)
    return {
        "author": {"name": "NOTIFICATION QA｜全頻道通知驗收"},
        "title": f"🧪 測試｜{item['icon']} #{item['channel']}",
        "description": "第二版統一格式；所有事件、時間與數值均為測試資料。",
        "color": item["color"],
        "fields": standard_fields(
            summary=item["summary"],
            details=item["details"],
            original_title=item.get("original_title"),
            event_status=item["event_status"],
            timing=item["timing"],
            source=item["source"],
            source_status=item["source_status"],
            source_detail=item.get("source_detail"),
            test=True,
        ),
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
                f"🧪 **全頻道通知第二版驗收（{batch_number}/{total}）**\n"
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
