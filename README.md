# Discord 美國總經通知（官方免費版）

免費追蹤 CPI、PPI、非農、失業率、GDP、FOMC 與 Powell 談話。只使用 BLS、BEA、Federal Reserve 官方來源，不需要 TradingEconomics 或 AI API Key。

## 通知內容

- 每日上午 07:00 後：當日 BLS 重要事件摘要
- BLS 公布前約 15 分鐘：事前提醒
- BLS、BEA、Federal Reserve 官方 RSS 更新後：Discord 通知
- 繁體中文事件名稱、台灣時間、官方原始網址
- 官方摘要含數值時擷取主要數值

官方機構不提供市場共識預期值，因此本版本不顯示「預期值」。Fed／BEA 未提供統一完整的即時行事曆介面，因此 GDP、FOMC 與 Powell 以官方發布後通知為主。

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
python notifier.py --dry-run --digest
python -m unittest discover -s tests -v
```

程式僅使用 Python 標準函式庫。GitHub Actions 每 10 分鐘執行一次；免費排程可能延遲數分鐘，不適合秒級交易。
