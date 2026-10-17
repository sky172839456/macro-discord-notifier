"""Stable Discord channel references; mentions follow server-side renames."""

CHANNEL_IDS = {
    "macro": "1524973145780654091",
    "crypto": "1524973208745279660",
    "finance": "1560822835826532432",
    "market": "1526037827115028622",
    "log": "1524973428296257616",
}


def channel_ref(key: str) -> str:
    return f"<#{CHANNEL_IDS[key]}>"


# Workflow keys stay stable across channel renames; no routes change here.
MONITOR_DISPLAY = {
    "總經數據": f"{channel_ref('macro')}｜總經掃描",
    "加密新聞": f"{channel_ref('crypto')}、{channel_ref('finance')}｜共用新聞整理",
    "市場風險": f"{channel_ref('crypto')}｜市場與服務風險",
    "市場分析": f"{channel_ref('market')}｜獨立總經／技術分析",
    "市場摘要": f"{channel_ref('market')}｜日／週報排程檢查",
    "上幣通知": "獨立上幣通知",
    "交易所公告": "獨立交易所公告",
    "衍生品": "獨立衍生品警報",
}
