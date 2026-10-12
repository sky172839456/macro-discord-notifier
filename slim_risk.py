"""Material service incidents and persistent, cross-source stablecoin deviations."""
from datetime import datetime, timezone
import math
from slim_policy import TAIPEI

COINS = {"USDT": "tether", "USDC": "usd-coin", "DAI": "dai"}


def price_sources(api, now):
    result = {coin: {} for coin in COINS}
    try:
        data = api.get_json("https://api.coingecko.com/api/v3/simple/price?ids=tether,usd-coin,dai&vs_currencies=usd&include_last_updated_at=true")
        for coin, key in COINS.items():
            row = data.get(key, {})
            value, updated = row.get("usd"), row.get("last_updated_at", 0)
            if value and 0 <= now.timestamp() - updated <= 600:
                result[coin]["CoinGecko"] = float(value)
    except Exception:
        print("警告：穩定幣 CoinGecko 來源暫缺，未視為正常。")
    try:
        data = api.get_json("https://api.kraken.com/0/public/Ticker?pair=USDTUSD,USDCUSD,DAIUSD")
        if data.get("error"):
            raise ValueError("Kraken ticker unavailable")
        for pair, row in data.get("result", {}).items():
            for coin in COINS:
                if pair.startswith(coin) and (pair.endswith("USD") or pair.endswith("ZUSD")):
                    bid, ask = float(row["b"][0]), float(row["a"][0])
                    if 0 < bid <= ask and (ask-bid) / bid <= .005:
                        result[coin]["Kraken"] = (bid + ask) / 2
    except Exception:
        print("警告：穩定幣 Kraken 來源暫缺，未視為正常。")
    return result


def confirmed_level(prices):
    values = list(prices.values())
    if len(values) < 2 or any(not math.isfinite(p) or p <= 0 for p in values):
        return None
    deviations = [p-1 for p in values]
    if all(abs(d) < .003 for d in deviations):
        return "normal"
    if not (all(d <= -.005 for d in deviations) or all(d >= .005 for d in deviations)):
        return None
    return "danger" if all(abs(d) >= .01 for d in deviations) else "warning"


def price_transition(record, prices, now):
    """Two confirmations separated by >=5 min; gaps >20 min restart confirmation."""
    level = confirmed_level(prices)
    if level is None:
        record.pop("candidate", None)
        return None
    previous = record.get("candidate", {})
    started = datetime.fromisoformat(previous["since"]) if previous.get("since") else now
    last = datetime.fromisoformat(previous["last"]) if previous.get("last") else now
    if previous.get("level") != level or (now-last).total_seconds() > 1200:
        started = now
    record["candidate"] = {"level": level, "since": started.isoformat(), "last": now.isoformat()}
    if (now-started).total_seconds() < 300:
        return None
    active = record.get("active", "normal")
    if level == "normal":
        record["active"] = "normal"
        return "recovered" if active != "normal" else None
    if level == active or (active == "danger" and level == "warning"):
        return None
    record["active"] = level
    return level


def price_card(coin, prices, transition, now):
    recovered = transition == "recovered"
    return {
        "title": f"{'✅ 價格偏離已收斂' if recovered else '🚨 穩定幣價格持續偏離'}｜{coin}",
        "description": "至少兩個公開來源、間隔五分鐘以上的連續查詢符合門檻。價格偏離不等同發行商儲備或償付能力出現問題。",
        "fields": [
            {"name": "查詢價格（美元）", "value": "\n".join(f"{source}：${price:.4f}（{(price-1)*100:+.2f}%）" for source, price in prices.items()), "inline": False},
            {"name": "需要留意", "value": "恢復僅指價格回到監測範圍，服務狀態仍須另外確認。" if recovered else "確認自己的交易平台報價、價差及充提狀態；不要將單一價格異常當成買賣指令。", "inline": False},
            {"name": "來源", "value": "[CoinGecko](https://www.coingecko.com/) · [Kraken](https://pro.kraken.com/)", "inline": False},
        ], "color": 0x2ECC71 if recovered else 0xE74C3C,
        "footer": {"text": "跨來源價格查詢｜不構成投資建議"}, "timestamp": now.isoformat(),
    }


def incident_material(item):
    status = str(item.get("status") or item.get("state") or "").lower()
    text = str(item.get("name") or item.get("title") or "").lower()
    if status in {"scheduled", "in_progress", "completed"} or "maintenance" in text:
        return False
    impact = str(item.get("impact", "")).lower()
    return impact in {"major", "critical"} or any(word in text for word in (
        "all withdrawals", "withdrawals unavailable", "withdrawals halted", "withdrawals suspended",
        "major outage", "hacked", "exploit", "security breach",
    ))


def incident_transition(record, item):
    status = str(item.get("status") or item.get("state") or "investigating").lower()
    name = str(item.get("name") or item.get("title") or "")
    components = tuple(sorted(str(c.get("id", "")) + ":" + str(c.get("status", "")) for c in item.get("components", [])))
    signature = [name, str(item.get("impact", "")), list(components)]
    resolved = status in {"resolved", "completed"}
    was_active = record.get("alerted", False) and not record.get("resolved", False)
    publish = (was_active if resolved else incident_material(item) and (
        not record.get("alerted") or record.get("signature") != signature))
    record.update(signature=signature, status=status)
    if publish:
        record.update(alerted=True, resolved=resolved)
    return publish


def incident_card(api, exchange, item, now):
    status = str(item.get("status") or item.get("state") or "investigating").lower()
    resolved = status in {"resolved", "completed"}
    title = str(item.get("name") or item.get("title") or "服務異常")
    body = str(item.get("body") or (item.get("incident_updates") or [{}])[0].get("body", ""))
    excerpt = api.clean_source_text(body, 500)
    if excerpt:
        try:
            from crypto_news_notifier import translate_text
            excerpt = translate_text(excerpt)
        except Exception:
            excerpt = "中文翻譯暫缺，以下保留官方原文：\n" + excerpt
    source = item.get("shortlink") or item.get("url") or "https://status.coinbase.com/"
    return {"title": f"{'✅ 服務已恢復' if resolved else '🚨 服務風險'}｜{exchange}｜{api.translate_title(title)}"[:240],
            "description": excerpt or "官方未提供詳細影響範圍，請閱讀原公告。",
            "fields": [{"name": "官方狀態", "value": api.translate_status(status), "inline": False},
                       {"name": "需要留意", "value": "恢復範圍以官方公告為準。" if resolved else "確認公告列出的平台與服務是否影響你的操作；不推測資產損失或恢復時間。", "inline": False},
                       {"name": "官方來源與更新時間", "value": f"[閱讀公告]({source})\n{item.get('updated_at') or item.get('endTime') or '官方未提供時間'}", "inline": False}],
            "color": 0x2ECC71 if resolved else 0xE74C3C,
            "footer": {"text": "官方原文摘錄｜不構成投資建議"}, "timestamp": now.isoformat()}


def monitor(api, webhook, now=None):
    now = now or datetime.now(timezone.utc)
    state = api.load()
    prices_state = state.setdefault("slim_prices", {})
    sources = price_sources(api, now)
    confirmed = [coin for coin, prices in sources.items() if len(prices) >= 2]
    for coin, prices in sources.items():
        transition = price_transition(prices_state.setdefault(coin, {}), prices, now)
        if transition:
            api.send(webhook, price_card(coin, prices, transition, now))
    incomplete = [coin for coin in COINS if coin not in confirmed]
    if incomplete:
        print("警告：跨來源報價不足：" + "、".join(incomplete) + "；不發布正常／恢復結論。")
        log = __import__("os").getenv("DISCORD_LOG_WEBHOOK_URL")
        day = now.astimezone(TAIPEI).date().isoformat()
        if log and state.get("slim_source_warning") != day:
            from notifier import send_discord
            send_discord(log, {"title": "⚠️ 風險監控部分來源暫缺", "description": "缺少兩個可比對價格來源：" + "、".join(incomplete) + "。未將來源缺失視為價格正常，亦未發布恢復通知。"}, False, "bot_log")
            state["slim_source_warning"] = day
    records = state.setdefault("slim_incidents", {})
    for exchange, collector in (("Coinbase", lambda: api.get_json(api.STATUS_URL).get("incidents", [])[:20]), ("Bybit", api.bybit_incidents)):
        try:
            items = collector()
        except Exception:
            print(f"警告：{exchange} 官方服務狀態暫缺。")
            continue
        for item in items:
            key = exchange + ":" + str(item.get("id") or item.get("title") or item.get("name"))
            row = records.setdefault(key, {})
            if incident_transition(row, item):
                api.send(webhook, incident_card(api, exchange, item, now))
    known = state.setdefault("exchange_events", {}).setdefault("CriticalNotices", {})
    notices = api.critical_official_notices()
    initialized = state.get("baselines", {}).get("CriticalNotices", False)
    for item in notices:
        key = f"{item['exchange']}:{item['id']}"
        if key not in known and initialized:
            api.send(webhook, incident_card(api, item["exchange"], {**item, "name": item["title"], "status": "investigating"}, now))
        known[key] = now.isoformat()
    if notices:
        state.setdefault("baselines", {})["CriticalNotices"] = True
    state["slim_incidents"] = dict(list(records.items())[-300:])
    state["exchange_events"]["CriticalNotices"] = dict(list(known.items())[-300:])
    api.save(state)
