"""Free official exchange listing monitor: Bybit, OKX and Coinbase."""
import argparse, hashlib, html, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

STATE=Path(".state/exchange-listings.json")
SOURCES={"Bybit":"https://announcements.bybit.com/en/?category=new_crypto","OKX":"https://www.okx.com/help/section/announcements-new-listings"}
def text(url):
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0 exchange-listing-monitor/2.0"}),timeout=30) as r:return r.read().decode("utf-8","replace")
def page_items(name,url):
    body=text(url); patterns={"Bybit":r'href=["\'](/en/article/[^"\']+)["\'][^>]*>(.*?)</a>',"OKX":r'href=["\'](/help/[^"\']+)["\'][^>]*>(.*?)</a>'}
    out=[]
    for path,title in re.findall(patterns[name],body,re.S|re.I):
        clean=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html.unescape(title))).strip(); low=clean.lower()
        if clean and any(k in low for k in ("list","perpetual","delist","migration","upgrade")):
            link=("https://announcements.bybit.com" if name=="Bybit" else "https://www.okx.com")+path
            out.append({"id":hashlib.sha256((name+link).encode()).hexdigest()[:24],"exchange":name,"title":clean,"url":link})
    return list({x["id"]:x for x in out}.values())[:30]
def coinbase_items():
    data=json.loads(text("https://api.exchange.coinbase.com/products")); out=[]
    for p in data:
        if p.get("status")=="online":
            pid=p["id"]; out.append({"id":hashlib.sha256(("Coinbase"+pid).encode()).hexdigest()[:24],"exchange":"Coinbase","title":f"Coinbase market available: {pid}","url":f"https://exchange.coinbase.com/trade/{pid}"})
    return out
def embed(x,test=False):
    low=x["title"].lower(); kind="下架／調整" if "delist" in low else "永續合約" if "perpetual" in low else "新市場／上架"
    return {"title":f"{'🧪 測試｜' if test else ''}🟢 {x['exchange']} {kind}","description":f"### {x['title']}\n\n**繁體中文摘要**\n{x['exchange']} 發布{kind}資訊，請開啟官方原文確認交易時間、交易對與適用地區。","color":0x2ECC71,
            "fields":[{"name":"交易所","value":x["exchange"],"inline":True},{"name":"官方原始資料","value":x["url"],"inline":False}],"footer":{"text":"交易所官方資料｜請以原文為準｜不構成投資建議"},"timestamp":datetime.now(timezone.utc).isoformat()}
def send(w,e):
    data=json.dumps({"username":"交易所上幣通知","embeds":[e],"allowed_mentions":{"parse":[]}}).encode(); req=Request(w+("&" if "?" in w else "?")+"wait=true",data=data,headers={"Content-Type":"application/json","User-Agent":"exchange-monitor/2.0"},method="POST")
    with urlopen(req,timeout=30):pass
def main():
    p=argparse.ArgumentParser();p.add_argument("--test",action="store_true");a=p.parse_args();w=os.environ.get("DISCORD_TEST_WEBHOOK_URL")
    if not w:raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL")
    if a.test:
        for n in ("Bybit","OKX","Coinbase"):send(w,embed({"exchange":n,"title":"New Listing: ABC/USDT on Spot","url":SOURCES.get(n,"https://exchange.coinbase.com/")},True))
        return
    state=json.loads(STATE.read_text()) if STATE.exists() else {}; fresh={}
    funcs={"Bybit":lambda:page_items("Bybit",SOURCES["Bybit"]),"OKX":lambda:page_items("OKX",SOURCES["OKX"]),"Coinbase":coinbase_items}
    for name,fn in funcs.items():
        try:items=fn()
        except Exception as exc:print(f"警告：{name} 讀取失敗：{exc}",file=sys.stderr);continue
        old=set(state.get(name,[]));fresh[name]=[x["id"] for x in items]
        if old:
            for x in reversed(items):
                if x["id"] not in old:send(w,embed(x))
    state.update(fresh);STATE.parent.mkdir(parents=True,exist_ok=True);STATE.write_text(json.dumps(state),encoding="utf-8")
if __name__=="__main__":main()
