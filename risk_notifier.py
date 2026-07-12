"""Stablecoin depeg and Coinbase incident monitor (free public sources)."""
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

STATE_FILE = Path(".state/risk-monitor.json")
PAIRS = {"USDT": "USDT-USD", "USDC": "USDC-USD", "DAI": "DAI-USD"}
STATUS_URL = "https://status.coinbase.com/api/v2/incidents.json"

def get_json(url):
    req = Request(url, headers={"User-Agent": "crypto-risk-monitor/1.0"})
    with urlopen(req, timeout=25) as r: return json.loads(r.read().decode())

def send(webhook, embed):
    body = json.dumps({"username":"加密市場風險監控","embeds":[embed],"allowed_mentions":{"parse":[]}}).encode()
    req = Request(webhook + ("&" if "?" in webhook else "?") + "wait=true", data=body,
                  headers={"Content-Type":"application/json"}, method="POST")
    with urlopen(req, timeout=25): pass

def load():
    try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError): return {"counts":{},"incidents":{}}

def save(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def depeg_embed(coin, price, level, test=False):
    danger = level == "danger"; prefix = "🧪 測試｜" if test else ""
    return {"title":f"{prefix}{'🔴 危險' if danger else '🟡 注意'}｜{coin} 穩定幣價格偏離",
            "description":f"### 現價　`${price:.4f}`\n**偏離 1 美元**　{(price-1)*100:+.2f}%\n\n已連續兩次偵測到異常，請留意流動性、充提與相關 DeFi 風險。",
            "color":0xE74C3C if danger else 0xF1C40F,
            "fields":[{"name":"🔗 官方價格來源","value":f"https://exchange.coinbase.com/trade/{PAIRS.get(coin,'USDT-USD')}","inline":False}],
            "footer":{"text":"Coinbase 公開行情｜僅供資訊參考，不構成投資建議"},"timestamp":datetime.now(timezone.utc).isoformat()}

def incident_embed(item, test=False):
    status = item.get("status","investigating"); resolved = status == "resolved"
    prefix = "🧪 測試｜" if test else ""; latest=(item.get("incident_updates") or [{}])[0].get("body","")
    return {"title":f"{prefix}{'✅ 已恢復' if resolved else '🚨 交易所服務異常'}｜{item.get('name','Coinbase 事件')}",
            "description":latest[:2500] or "Coinbase 官方狀態頁發布服務事件更新。",
            "color":0x2ECC71 if resolved else 0xE74C3C,
            "fields":[{"name":"狀態","value":status,"inline":True},{"name":"官方來源","value":item.get("shortlink") or "https://status.coinbase.com/","inline":False}],
            "footer":{"text":"Coinbase 官方狀態頁｜原文保留，不構成投資建議"},"timestamp":datetime.now(timezone.utc).isoformat()}

def monitor(webhook):
    state=load(); counts=state.setdefault("counts",{}); known=state.setdefault("incidents",{}); first=not known
    for coin,pair in PAIRS.items():
        try: price=float(get_json(f"https://api.exchange.coinbase.com/products/{pair}/ticker")["price"])
        except Exception as exc: print(f"警告：{coin} 價格無法取得：{exc}"); continue
        level="danger" if price < .99 or price > 1.01 else "warning" if price < .995 or price > 1.005 else "normal"
        counts[coin] = counts.get(coin,0)+1 if level != "normal" else 0
        if counts[coin] == 2: send(webhook, depeg_embed(coin,price,level))
    for item in get_json(STATUS_URL).get("incidents",[])[:20]:
        key=item["id"]; marker=item.get("updated_at","") + item.get("status","")
        if not first and known.get(key) != marker: send(webhook, incident_embed(item))
        known[key]=marker
    save(state)

def tests(webhook):
    send(webhook,depeg_embed("USDC",.993,"warning",True)); send(webhook,depeg_embed("USDT",.986,"danger",True))
    send(webhook,incident_embed({"name":"Coinbase API 延遲","status":"investigating","shortlink":"https://status.coinbase.com/","incident_updates":[{"body":"模擬官方狀態：部分使用者可能遇到 API 延遲，團隊正在調查。"}]},True))

def main():
    p=argparse.ArgumentParser(); p.add_argument("--test-templates",action="store_true"); a=p.parse_args()
    webhook=os.environ.get("DISCORD_TEST_WEBHOOK_URL")
    if not webhook: raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL")
    tests(webhook) if a.test_templates else monitor(webhook)
    print("完成：風險監控已執行")
if __name__ == "__main__": main()
