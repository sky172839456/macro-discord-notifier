"""Display names only. Resolve delivery routes before applying branding."""
NAMES = {
    "macro_alerts": "WV｜總經數據",
    "daily_market": "WV｜市場情報",
    "weekly_market": "WV｜市場情報",
    "crypto_news": "WV｜幣圈新聞",
    "finance_news": "WV｜全球錢線",
    "breaking_news": "WV｜重大快訊",
    "market_risk": "WV｜風險快訊",
    "regulation_etf": "WV｜監管與ETF",
    "macro_analysis": "WV｜總經觀察",
    "technical_analysis": "WV｜技術分析",
    "material_inbox": "WV｜素材整理",
    "bot_log": "WV｜系統紀錄",
    "exchange_listings": "WV｜上幣通知",
    "exchange_announcements": "WV｜交易所公告",
    "derivatives": "WV｜衍生品資訊",
    "preview": "WV｜通知預覽",
}


def sender_name(channel_key):
    return NAMES[channel_key]
