# 2026-11-10 素材語意與新聞事件核對

本輪處理每日驗收的自然新卡缺口，沒有改寫或重發已送訊息。

- Claude Code／Claude Fable及CLI命令保留產品識別；版本號、數值、命令參數與否定條件須通過檢查。只修已定位的翻譯，不拿中文慣用語代替產品名稱。
- 官方發布紀錄保留完整HTML條列與命令文字。選取最多兩個符合既有免費翻譯長度限制的完整句子，不再把430／190字的截斷當摘要。無完整短段落的發布候選暫留；卡片保留星等、切入點、原文及來源時間。
- 版本更新的切入點區分新模型／設定與修補；提及MCP的安全修補不能宣稱新增串接。星等與原分享價值門檻不降低。
- 數量後的NEAR是資產單位；pre-hack balances是遭駭前餘額。已核對的Binance洗錢者標題保留行為主詞，Musk主題圖案不等於本人涉案。
- 本輪人工核對Coinbase最終OCC許可、Elliptic六個NEAR池各三篇RSS報導。只有URL、完整標題／摘要指紋和原發布時間全數相符才共用事件；換數字、階段、內容或日期仍回到原嚴格規則。這是九筆來源觀察的狹義核對，不代表所有相似新聞已獲語意確認。
- Gnosis Pay不同曝光細節保留公開新進展；週報可歸同事件，保留其他來源連結，不改原journal、seen或歷史。
- 只重新整理尚未送出候選的摘要；notified／delivery_unknown不重開。原路由、頻率、每輪兩則、24小時、免費來源與發送狀態保留。

核對來源：

- [Claude Code原發布](https://github.com/anthropics/claude-code/releases/tag/v2.1.321)
- [Elliptic原分析](https://www.elliptic.co/insights/north-korea-meme-coins-binance-hack/)
- [Coinbase最終許可媒體報導](https://decrypt.co/382816/coinbase-joins-circle-ripple-with-final-occ-approval-for-federal-trust-bank-charter)：仍標示媒體報導，不冒稱已讀到OCC正式決定文件。
- [Gnosis曝光細節](https://www.coindesk.com/business/2026/11/07/gnosis-pay-breach-exposes-card-numbers-home-addresses-and-linked-crypto-wallets)

909項本機回歸通過，Windows略過1項既有平台測試。合併前仍須同head完整audit_only雲端檢查及兩個Send skipped；自然採版、實際新卡與完整內容品質另行驗收。不得為驗收補舊文、清seen或觸發正式測試。
