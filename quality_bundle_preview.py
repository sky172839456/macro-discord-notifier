"""Synthetic private preview fixtures. Never executes a monitor or sends messages."""
import argparse
import json
import os
from datetime import datetime, timezone

import news_editorial as editorial
import slim_policy as policy
from notification_format import apply_delivery_format


def cards():
    now=datetime(2026,10,16,0,tzinfo=timezone.utc)
    base={'published':now,'official':False,'source':'虛構來源示例','url':'https://example.com/quality-preview',
          'category':{'key':'market','priority':'normal'},'id':'preview'}
    retrospective={**base,'title':'Q3 crypto hacks report totals $1.2 billion in industry losses',
                   'summary':'The Q3 report totals $1.2 billion in industry losses.',
                   'title_zh':'第三季加密資安回顧：產業損失12億$',
                   'summary_zh_points':['原報告彙整第三季產業損失12億美元。']}
    future={**base,'title':'Russia will ban peer-to-peer Bitcoin trading',
            'summary':'Rules take effect on July 1, 2027.',
            'title_zh':'俄羅斯點對點比特幣交易政策時程',
            'summary_zh_points':['規則將於2027年7月1日開始適用。']}
    flow={**base,'title':'Bitcoin ETFs record $261 million in net outflows',
          'summary':'Bitcoin ETFs recorded $261 million in net outflows.',
          'title_zh':'比特幣ETF淨流出2.61億$',
          'summary_zh_points':['比特幣ETF錄得2.61億美元淨流出。']}
    security={**base,'id':'safety','title':'Ledger reports new wallet exploits','summary':'Ledger reports new wallet exploits.',
              'review_reason':'媒體資安候選，尚未由直接官方來源核對'}
    missing={**base,'id':'copy','title':'SEC approves spot Bitcoin ETF','summary':'SEC approves spot Bitcoin ETF.',
             'review_reason':'中文摘要未確認；已保留佇列，未送成員'}
    rows=[('回顧改為一般彙整','crypto_news',policy.digest_card([retrospective],now)),
          ('政策列明日期與媒體歸屬','crypto_news',policy.news_card(future,now=now)),
          ('資金流量與金額單位','crypto_news',policy.digest_card([flow],now)),
          ('新資安與摘要缺少留管理區','bot_log',editorial.review_card([security,missing],now)),
          ('來源原因與最後成功','bot_log',{'title':'⚠️ Bybit服務狀態來源暫缺',
            'description':'本輪原因：HTTP 403\n最後成功讀取：2026/10/16 07:10（台灣）\n本輪未取得官方狀態，不能據此認定服務正常。此為虛構失敗情境，非來源現況。',
            'fields':[{'name':'🩺 資料狀態','value':'⚠️ 部分來源暫缺｜本平台狀態未確認，其他來源獨立檢查。','inline':False}]}),
          ('備援範圍與日期','bot_log',{'title':'🟡 BLS排程備援核對示例',
            'description':'限已核對的7項今年剩餘日期｜核對日2026/10/16｜有效31天。\n備援可用不等於主來源恢復；到期不繼續使用過期排程。',
            'fields':[{'name':'🩺 資料狀態','value':'🟡 僅部分項目使用備援｜未確認主來源恢復，也不是完整日程。','inline':False}]})]
    output=[]
    for key,channel,card in rows:
        card=dict(card)
        card['description']='**虛構版面測試，未送正式頻道。**\n\n'+card.get('description','')
        card=apply_delivery_format(card,channel)
        import re
        card['title']=re.sub(r'^(【[^】]+】)', r'\1 🧪 私人示例｜', card['title'])
        assert len(card['title'])<=256
        assert len(card.get('description',''))<=4096
        assert sum(len(str(card.get(k,''))) for k in ('title','description'))+sum(len(f['name'])+len(f['value']) for f in card.get('fields',[]))<=6000
        output.append({'key':key,'embed':card})
    return output


if __name__=='__main__':
    os.environ['SLIM_NOTIFICATIONS']='1'
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    data=json.dumps(cards(),ensure_ascii=False,indent=2)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(data,encoding='utf-8')
        print('私人示例6張已建立；沒有傳送或修改正式狀態。')
    else:
        print(data)
