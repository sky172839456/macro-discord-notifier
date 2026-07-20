# Discord 美國總經雷達（官方免費版）

免費追蹤 CPI、PPI、PCE／核心 PCE、非農、失業率、初領失業金、JOLTS、零售銷售、耐久財、GDP、FOMC 與聯準會官員談話。正式數據與原文使用 BLS、BEA、DOL、Census 與 Federal Reserve 官方來源，不需要付費資料或 AI API Key。

## 通知內容

- 每日上午 07:00 後：當日重要事件摘要
- 最高重要事件：公布前一天提醒
- 所有追蹤事件：公布前約 15 分鐘提醒
- BLS、BEA、DOL、Census、Federal Reserve 官方來源更新後：Discord 通知
- 發布卡片顯示可取得的前值、變動與修正資訊
- 紀錄頻道每天顯示全部來源的健康狀態，正常與異常都會列出
- 繁體中文事件名稱、台灣時間、官方原始網址
- 官方摘要含數值時擷取主要數值

官方機構不提供市場共識預期值，因此不把第三方預測冒充官方數據。系統使用公開輔助行事曆補足部分提醒時間；正式公布值、前值／修正與原文連結仍以政府官方來源為準。

## GitHub 設定

1. 在 Discord 頻道「編輯頻道 → 整合 → Webhook」建立 Webhook。
2. 到 GitHub repository 的 `Settings → Secrets and variables → Actions`。
3. 新增 repository secret：

```text
名稱：DISCORD_WEBHOOK_URL
內容：Discord Webhook 完整網址
```

4. 到 `Actions → Discord Macro Alerts → Run workflow` 手動測試。

Webhook 是敏感資料，請勿貼在 README、Issue 或 commit。

## 本機測試

```powershell
$env:DISCORD_WEBHOOK_URL = "你的 Discord Webhook"

交易所上幣通知使用獨立的正式 Webhook：

- `DISCORD_EXCHANGE_LISTING_WEBHOOK_URL`：正式 `#上幣通知` 頻道
- `DISCORD_TEST_WEBHOOK_URL`：僅供手動測試；測試訊息會標示「🧪 測試」

目前監控 Binance、OKX、Bybit、Bitget、Coinbase、Kraken、KuCoin 與 BingX。
公告會明確分成「🟢 現貨上幣、🔵 永續合約、🟡 預上市／盤前交易、🔴 下架、🔄 代幣遷移／更名」。
Binance 與 BingX 的公告首頁為動態載入，因此另用官方公開現貨市場 API 建立新交易對基準；首次啟用只建立基準，不會把既有市場洗進通知頻道。

GitHub Actions 的排程會使用正式 Webhook，手動執行 `Exchange Listing Monitor`
則只會使用測試 Webhook，避免測試資料進入正式頻道。
python notifier.py --dry-run --digest
python -m unittest discover -s tests -v
```

程式僅使用 Python 標準函式庫。GitHub Actions 每 10 分鐘執行一次；免費排程可能延遲數分鐘，不適合秒級交易。
