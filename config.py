"""Official, free data sources and event mappings."""

OFFICIAL_FEEDS = (
    ("BLS", "https://www.bls.gov/feed/bls_latest.rss"),
    ("BEA", "https://apps.bea.gov/rss/rss.xml"),
    ("FED_POLICY", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("FED_SPEECH", "https://www.federalreserve.gov/feeds/speeches.xml"),
)

BLS_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/bls.ics"

EVENT_RULES = (
    {"key": "cpi", "keywords": ("consumer price index",), "name": "美國消費者物價指數（CPI）", "source": "https://www.bls.gov/cpi/"},
    {"key": "ppi", "keywords": ("producer price index",), "name": "美國生產者物價指數（PPI）", "source": "https://www.bls.gov/ppi/"},
    {"key": "jobs", "keywords": ("employment situation",), "name": "美國非農就業與失業率", "source": "https://www.bls.gov/news.release/empsit.htm"},
    {"key": "gdp", "keywords": ("gross domestic product", "gdp (", "gdp:"), "name": "美國國內生產毛額（GDP）", "source": "https://www.bea.gov/data/gdp/gross-domestic-product"},
    {"key": "fomc", "keywords": ("federal open market committee", "fomc", "monetary policy statement"), "name": "美國聯準會 FOMC 公告", "source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"key": "powell", "keywords": ("jerome h. powell", "chair powell", "powell"), "name": "聯準會主席 Powell 談話", "source": "https://www.federalreserve.gov/newsevents/calendar.htm"},
)

TAIPEI_ZONE = "Asia/Taipei"
PRE_ALERT_MINUTES = 15
PRE_ALERT_WINDOW_MINUTES = 12

MARKET_INTERPRETATIONS = {
    "cpi": "若通膨低於市場預期，可能提高降息期待，通常有利美股與加密資產；若高於預期，則可能增加利率維持高檔的壓力。",
    "ppi": "若生產端通膨低於預期，通常有助緩解通膨疑慮；若高於預期，市場可能擔心成本壓力向消費端傳導。",
    "jobs": "若就業明顯降溫，可能提高降息期待，但過度疲弱也可能引發衰退疑慮；若就業過熱，利率可能維持高檔更久。",
    "gdp": "若經濟成長優於預期，通常反映經濟韌性，但也可能降低短期降息機率；若明顯低於預期，須留意衰退風險。",
    "fomc": "措辭偏寬鬆或暗示降息，通常有利風險資產；措辭偏鷹或暗示利率維持高檔，可能使美股與加密資產承壓。",
    "powell": "市場將聚焦 Powell 對通膨、就業與利率路徑的表態；偏寬鬆訊號通常有利風險資產，偏鷹訊號則可能帶來壓力。",
}
