"""Official, free data sources and event mappings."""

OFFICIAL_FEEDS = (
    ("BLS", "https://www.bls.gov/feed/bls_latest.rss"),
    ("BEA", "https://apps.bea.gov/rss/rss.xml"),
    ("FED_POLICY", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("FED_SPEECH", "https://www.federalreserve.gov/feeds/speeches.xml"),
)

BLS_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/bls.ics"

EVENT_RULES = (
    {"key": "cpi", "keywords": ("consumer price index",), "name": "美國消費者物價指數（CPI）", "source": "https://www.bls.gov/cpi/", "priority": "highest"},
    {"key": "ppi", "keywords": ("producer price index",), "name": "美國生產者物價指數（PPI）", "source": "https://www.bls.gov/ppi/"},
    {"key": "jobs", "keywords": ("employment situation",), "name": "美國非農就業與失業率", "source": "https://www.bls.gov/news.release/empsit.htm", "priority": "highest"},
    {"key": "jolts", "keywords": ("job openings and labor turnover", "jolts"), "name": "美國 JOLTS 職位空缺", "source": "https://www.bls.gov/news.release/jolts.nr0.htm"},
    {"key": "claims", "keywords": ("unemployment insurance weekly claims", "initial jobless claims", "unemployment claims"), "name": "美國初領失業救濟金人數", "source": "https://www.dol.gov/ui/data.pdf"},
    {"key": "pce", "keywords": ("personal income and outlays", "personal consumption expenditures"), "name": "美國 PCE／核心 PCE 物價指數", "source": "https://www.bea.gov/data/personal-consumption-expenditures-price-index", "priority": "highest"},
    {"key": "retail", "keywords": ("advance monthly retail", "advance retail and food services sales", "retail sales"), "name": "美國零售銷售", "source": "https://www.census.gov/retail/sales.html"},
    {"key": "durable", "keywords": ("advance new orders for manufactured durable goods", "durable goods"), "name": "美國耐久財訂單", "source": "https://www.census.gov/manufacturing/m3/adv/current/index.html"},
    {"key": "gdp", "keywords": ("gross domestic product", "gdp (", "gdp:"), "name": "美國國內生產毛額（GDP）", "source": "https://www.bea.gov/data/gdp/gross-domestic-product", "priority": "highest"},
    {"key": "fomc", "keywords": ("federal open market committee", "fomc", "monetary policy statement"), "name": "美國聯準會 FOMC 公告", "source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "priority": "highest"},
    {"key": "powell", "keywords": ("jerome h. powell", "chair powell", "governor powell", "powell"), "name": "Jerome Powell 談話", "source": "https://www.federalreserve.gov/newsevents/calendar.htm"},
    {"key": "fed_official", "keywords": ("chairman ", "chair ", "vice chair", "governor "), "name": "聯準會重要官員談話", "source": "https://www.federalreserve.gov/newsevents/speeches-testimony.htm"},
)

TAIPEI_ZONE = "Asia/Taipei"
PRE_ALERT_MINUTES = 15
PRE_ALERT_WINDOW_MINUTES = 12
DAY_BEFORE_MINUTES = 24 * 60

MARKET_INTERPRETATIONS = {
    "cpi": "若通膨低於市場預期，可能提高降息期待，通常有利美股與加密資產；若高於預期，則可能增加利率維持高檔的壓力。",
    "ppi": "若生產端通膨低於預期，通常有助緩解通膨疑慮；若高於預期，市場可能擔心成本壓力向消費端傳導。",
    "jobs": "若就業明顯降溫，可能提高降息期待，但過度疲弱也可能引發衰退疑慮；若就業過熱，利率可能維持高檔更久。",
    "gdp": "若經濟成長優於預期，通常反映經濟韌性，但也可能降低短期降息機率；若明顯低於預期，須留意衰退風險。",
    "fomc": "措辭偏寬鬆或暗示降息，通常有利風險資產；措辭偏鷹或暗示利率維持高檔，可能使美股與加密資產承壓。",
    "powell": "市場將聚焦 Powell 對通膨、就業與利率路徑的表態；偏寬鬆訊號通常有利風險資產，偏鷹訊號則可能帶來壓力。請以活動當下的官方職稱與完整上下文為準。",
    "fed_official": "市場將聚焦官員對通膨、就業、利率路徑與金融穩定的表態；請依官方當下職稱、完整講稿與市場原先預期綜合判讀。",
    "pce": "PCE 是聯準會重要通膨指標；核心 PCE 降溫通常有利降息預期，反之可能使利率維持高檔。",
    "claims": "初領失業金上升反映就業降溫，但過度惡化也可能引發衰退擔憂。",
    "jolts": "職位空缺下降通常表示勞動需求降溫；需同時觀察聘僱、離職與解僱。",
    "retail": "零售銷售反映消費需求；過強可能支撐成長也增加通膨韌性，過弱則要留意經濟降溫。",
    "durable": "耐久財訂單波動較大，應同時觀察扣除運輸與核心資本財指標。",
}
