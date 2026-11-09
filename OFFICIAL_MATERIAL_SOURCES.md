# 私人素材官方來源（2026-11-09）

只接到既有私人素材整理。未啟用獨立交易所公告、公開新聞新路由、IG自動發布或付費API。原有17個RSS保留，新增2個Claude官方feed與7個官方索引，共26個來源入口；不是26個互相獨立的消息機構，也不代表全網覆蓋。

| 新增入口 | 格式與範圍 | 正文及原始時間 |
| --- | --- | --- |
| Bitget News／Products／Listings | `api.bitget.com/api/v3/public/annoucements`，latest_news／product_updates／coin_listings | 官方support文章正文；API cTime逐值對上longCreateTime，再以showTime／unifiedDisplayTime一致的發布時間為準；不把建立時間當發布時間 |
| Binance News／Listings／Activities | 官網公開CMS，catalog 49／48／93 | CMS detail核對code、標題、publishDate與清單releaseDate；不採正文內活動日期或lastUpdateTime冒充發布時間 |
| TradingView Blog | `https://www.tradingview.com/blog/en/` | 官網article索引＋entry-content正文及article:published_time；RSS當次500，不採第三方轉製feed；dateModified不當新公告 |
| Claude Platform Updates | `https://platform.claude.com/docs/en/release-notes/feed.xml` | 官方release notes RSS及其pubDate、原始章節連結 |
| Claude Code Releases | `https://github.com/anthropics/claude-code/releases.atom` | 官方repo Atom，只接受該repo的releases/tag路徑；版本號前加產品名辨識，日期沿官方feed |

原有OpenAI、Google DeepMind／AI、Hugging Face、Microsoft Research、MIT與公開新聞原始RSS繼續保留。新入口讓產品、活動及工具細節進共同分享價值門檻，官方旗標不保送；每日答題領獎、測驗、交易競賽仍排除。Launchpool、IPO認購與代幣化權益仍須分清關係與資格，不由公司或代號推定合作或保證收益。

## 防補發與資源界線

- 索引來源第一次成功只建立各自基準，不抓正文、不補舊文；來源故障不建立成功基準、不重設既有紀錄。
- 後續新連結才抓正文；沿原24小時時效／跨源同事件去重與每輪最多2則。未改正式seen，不重開已送或送達不明的項目。RSS新增來源也有個別啟用基準。
- Bitget每類最多3頁、每頁10項；Binance每類首50項、TV首30個article。這是有界輪詢，並非保證不漏的全量歷史爬取。
- 每輪共最多6篇新正文，跨來源輪流分配；其餘排隊。正文失敗30分鐘後重試，仍在原24小時界線內；未讀取／失敗數量列入每日品質巡檢，不稱為空公告或健康。
- 只讀白名單公開HTTPS頁面／API；明確拒絕越界路徑、任意參數及越界重新導向。逾時12秒、單回應上限2MB、正文保留上限6000字元。沒有新增帳號、Secrets或付費依賴。
- 官方正文的實際條件可能在導言之後，分享價值判定讀取有界正文，不只看RSS短摘要；實質細節、用途／影響、日期與來源要求不放寬。中文與來源界線、五星優先度及內容切入點仍由既有模板呈現。
- 同連結的單純修改不自動冒稱新事件；日期或內容不明仍待核。一般微小修補、純上幣／調參或行銷不保證成為值得分享的素材。

## 唯讀驗證

`python material_inbox_check.py`：全部自有來源清單與每個新索引首篇正文／發布日期驗證。不讀正式state，不發送。

`python material_selection_check.py`：全部來源試篩；新索引正文採最多6篇診斷樣本，保留pending／錯誤數與diagnostic_sample_only標記，不能把樣本當全量驗收。不發送、不寫正式來源基準或seen。

測試fixture是虛構資料；歷史TV MCP文章只能驗證解析與條件判斷，不列為今天新內容或補發。合併及自然採版、未來自然新卡送達與內容品質分開記錄。

## Census完整驗收相容性修正

2026-11-09同址對照重現：原HTTP_HEADERS的Referer帶到Census零售頁時404，僅移除Referer後200且同篇官方標題／日期／季調數值可讀。Census首頁仍連至原sales.html，原文和官方PDF均有2026-10-15發布、2026/09本次+0.8%／2026/08修訂後+1.3%，不屬已確認網址遷移。外部證據不足以斷言Census內部邊緣伺服器原因。

`notifier.source_headers`只針對實際census.gov及其子網域移除Referer，文字與二進位讀取沿用；其他供應商標頭不變。沒有換代理／IP、登入、放寬404／500／403、替換零售原始網址或拿PDF補數。原macro_scope_check完整跑過才可合併，數字／日期／時效與季調驗證保持。
