"""WV 品牌表情：會員頻道卡片標題的圖示換成 WV 金色表情。

2026-11-18 本人在 DC 功能細節選了「推播卡片用 WV 表情」與「動態表情（低調版）」，
表情已上傳到 W Viewture 伺服器（靜態 16 個、動態 16 個 `_a`）。

- 只換標題【分類】後面的第一個圖示；欄位小標、內文與管家工作簿不動。
- 表情 ID 不是密鑰。伺服器裡的表情被刪掉或重傳時 ID 會變，這裡要一起改，
  否則卡片標題會顯示成 `:wv_xxx:` 文字。
- 換上表情後若超過 Discord 字數上限，就保留原本的一般表情，不刪改任何文字。
"""
from __future__ import annotations

import re

# 名稱 → ID（2026-11-18 從伺服器設定「表情符號」頁讀回）
STATIC = {
    'wv_logo': '1572485965556224000',
    'wv_up': '1572475907061579847',
    'wv_down': '1572475936337563720',
    'wv_got': '1572475966083571713',
    'wv_ask': '1572475995200430080',
    'wv_note': '1572476024652963960',
    'wv_risk': '1572476054231056485',
    'wv_coffee': '1572476074049146910',
    'wv_like': '1572482406684827668',
    'wv_heart': '1572482421717467167',
    'wv_heartbreak': '1572482440948097024',
    'wv_wow': '1572482471696539668',
    'wv_plus1': '1572482488066904164',
    'wv_thanks': '1572484214044098583',
    'wv_eyes': '1572484233602015282',
    'wv_fire': '1572484253222969345',
}
ANIMATED = {
    'wv_logo_a': '1572492042737680384',
    'wv_up_a': '1572491987762942053',
    'wv_down_a': '1572492059334672404',
    'wv_got_a': '1572492076074016888',
    'wv_ask_a': '1572492092578603129',
    'wv_note_a': '1572492108823134298',
    'wv_risk_a': '1572492125277265950',
    'wv_coffee_a': '1572492142620975114',
    'wv_like_a': '1572492159746318476',
    'wv_heart_a': '1572492176917532742',
    'wv_heartbreak_a': '1572492194101723186',
    'wv_wow_a': '1572492210799255602',
    'wv_plus1_a': '1572492227224014929',
    'wv_thanks_a': '1572492243858620426',
    'wv_eyes_a': '1572492260442906624',
    'wv_fire_a': '1572492277761187980',
}

# 【分類】→ {原本圖示: WV 表情}。動態只用在價格快訊與每日／每週行情（本人選低調版）。
# 沒列到的分類或圖示（例如 🪙 幣圈有事、🌐 全球錢線跟頻道名稱同一個圖示、漲跌混合的 ↕️）維持原樣。
TITLE_ICONS = {
    '價格快訊': {'📈': 'wv_up_a', '📉': 'wv_down_a'},
    '每日行情': {'📊': 'wv_coffee_a'},
    '每週行情': {'🧭': 'wv_logo_a'},
    '數據公布': {'🔴': 'wv_note', '⏳': 'wv_note'},
    '今日行事曆': {'🗓': 'wv_eyes'},
    '下週行事曆': {'🗓': 'wv_eyes'},
    '數據提醒': {'⏰': 'wv_eyes'},
    '官員談話': {'⏰': 'wv_eyes'},
    '總經數據': {'📆': 'wv_eyes', '⏰': 'wv_eyes'},
    '重大快訊': {'🚨': 'wv_risk'},
    '金融快訊': {'🚨': 'wv_risk'},
    '風險警報': {'🚨': 'wv_risk'},
    '市場新聞': {'⏳': 'wv_note', '📰': 'wv_note'},
    '金融新聞': {'⏳': 'wv_note', '📰': 'wv_note'},
    '新聞彙整': {'📰': 'wv_note'},
    '恢復通知': {'✅': 'wv_got'},
}

# 測試頻道的預覽卡標題前面多一段「🧪 精簡版預覽｜」，跳過它，讓預覽看到的跟正式卡一樣。
_HEAD = re.compile(r'^(【([^】]{1,12})】)([ \t]*)((?:🧪 (?:精簡版預覽|測試)｜\s*)*)(\S)(️?)')


def markup(name: str) -> str:
    """Discord 自訂表情寫法；動態表情前面加 a。"""
    if name in ANIMATED:
        return f'<a:{name}:{ANIMATED[name]}>'
    if name in STATIC:
        return f'<:{name}:{STATIC[name]}>'
    raise KeyError(name)


def title_with_wv(title: str) -> str:
    match = _HEAD.match(title or '')
    if not match:
        return title
    name = TITLE_ICONS.get(match.group(2), {}).get(match.group(5))
    if not name:
        return title
    return match.group(1) + (match.group(3) or ' ') + match.group(4) + markup(name) + title[match.end():]


def brand_title(card: dict) -> dict:
    """換上 WV 表情；會讓卡片超過 Discord 上限時保留原本圖示。"""
    title = str(card.get('title') or '')
    branded = title_with_wv(title)
    if branded == title:
        return card
    from content_contract import payload_issues
    candidate = {**card, 'title': branded}
    if payload_issues([candidate]):
        return card
    return candidate
