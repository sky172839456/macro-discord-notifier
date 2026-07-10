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
