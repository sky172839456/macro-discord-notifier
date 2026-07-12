"""Monitor Bybit official listing announcements."""
import argparse, hashlib, html, json, os, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL="https://announcements.bybit.com/en/?category=new_crypto"
STATE=Path(".state/bybit-announcements.json")
def fetch():
    req=Request(URL,headers={"User-Agent":"Mozilla/5.0 crypto-announcement-monitor/1.0"})
    with urlopen(req,timeout=30) as r: text=r.read().decode("utf-8","replace")
    found=[]
    for path,title in re.findall(r'href=["\'](/en/article/[^"\']+)["\'][^>]*>(.*?)</a>',text,re.S|re.I):
        clean=re.sub(r"<[^>]+>"," ",html.unescape(title)); clean=re.sub(r"\s+"," ",clean).strip()
        if clean and any(k in clean.lower() for k in ("list","perpetual","delist","migration","upgrade")):
            found.append({"id":hashlib.sha256(path.encode()).hexdigest()[:20],"title":clean,"url":"https://announcements.bybit.com"+path})
    unique={x["id"]:x for x in found}; return list(unique.values())[:20]
def embed(item,test=False):
    t=item["title"]; low=t.lower(); kind="下架／調整" if "delist" in low else "永續合約" if "perpetual" in low else "新幣上架"
    zh=f"Bybit 發布{kind}公告，請開啟官方原文確認交易對、開放時間與適用地區。"
    return {"title":f"{'🧪 測試｜' if test else ''}🟢 Bybit {kind}","description":f"### {t}\n\n**繁體中文摘要**\n{zh}","color":0xF7A600,
            "fields":[{"name":"公告類型","value":kind,"inline":True},{"name":"官方原始資料","value":item["url"],"inline":False}],
            "footer":{"text":"Bybit 官方公告｜請以原文為準｜不構成投資建議"},"timestamp":datetime.now(timezone.utc).isoformat()}
def send(webhook,e):
    data=json.dumps({"username":"交易所上幣通知","embeds":[e],"allowed_mentions":{"parse":[]}}).encode()
    req=Request(webhook+("&" if "?" in webhook else "?")+"wait=true",data=data,headers={"Content-Type":"application/json","User-Agent":"bybit-monitor/1.0"},method="POST")
    with urlopen(req,timeout=30): pass
def main():
    p=argparse.ArgumentParser(); p.add_argument("--test",action="store_true"); a=p.parse_args(); w=os.environ.get("DISCORD_TEST_WEBHOOK_URL")
    if not w: raise RuntimeError("缺少 DISCORD_TEST_WEBHOOK_URL")
    if a.test: send(w,embed({"title":"New Listing: ABC/USDT on Spot","url":URL},True)); return
    items=fetch(); old=set(json.loads(STATE.read_text()) if STATE.exists() else []); current={x["id"] for x in items}
    if old:
        for x in reversed(items):
            if x["id"] not in old: send(w,embed(x))
    STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(list(current)),encoding="utf-8")
if __name__=="__main__": main()
