"""One-time correction of six checked messages; never send, delete or touch state."""
import copy
import hashlib
import json
import os
import re
from urllib.request import Request, urlopen

CHANNEL = '1524973208745279660'
MARK = 'WV更正20261107'
TARGETS = {
    '1567872306389458985': 'bitcoin-shrugs-off-midterms-as-experts-say-democratic-sweep-was-priced-in',
    '1567509935271706676': '1inch-lawyer-sees-agencies-driving-us-crypto-regulation-as-midterms-unfold',
    '1567912549494689873': 'gate-ceo-says-crypto-exchanges-must-prove-they-can-survive-a-hack-like-binance-s',
    '1567996863322263565': 'mercado-bitcoin-hack-contained-blockchain-data',
    '1568234677670776896': 'greece-approves-10-tax-crypto-gains-2027',
    '1568583218159026229': 'trm-labs-binance-hack-interview',
}

def editable(card):
    return {k: copy.deepcopy(card[k]) for k in ('title','description','url','color','fields','footer','author','timestamp') if k in card}

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()

def corrected(message):
    mid = message['id']
    if mid not in TARGETS or message.get('channel_id') != CHANNEL or len(message.get('embeds', [])) != 1:
        raise ValueError('Unexpected message target or layout')
    card = editable(message['embeds'][0])
    if TARGETS[mid] not in json.dumps(card):
        raise ValueError('Checked source link missing')
    if MARK in card.get('footer', {}).get('text', ''):
        return card
    if mid == '1567872306389458985':
        card['description'] = re.sub(r'\*\*03｜[^\n]*?\*\*', '**03｜比特幣淡化期中選舉影響；專家稱民主黨全面勝選已反映於價格**', card['description'], count=1)
        card['description'] = card['description'].replace('民主黨的掃蕩', '民主黨全面勝選').replace('是定價的', '已反映於價格')
    elif mid == '1567509935271706676':
        card['description'] = re.sub(r'\*\*02｜[^\n]*?\*\*', '**02｜期中選舉進行之際，1inch律師認為監管機關將主導美國加密規則制定**', card['description'], count=1)
    elif mid == '1567912549494689873':
        card['title'] = '【市場觀點】媒體訪談｜Gate執行長：交易所應證明能承受類似幣安的駭客攻擊'
        card['description'] = '媒體報導｜Lin Han表示，即使熱錢包遭清空，Gate的冷錢包儲備仍足以覆蓋客戶餘額，獨立稽核正在進行。這是受訪者對交易所防護的主張，並非新駭侵通報。'
    elif mid == '1568583218159026229':
        card['title'] = '【市場觀點】媒體訪談｜TRM Labs高管稱幣安駭侵是「網路戰」'
        card['description'] = '媒體報導｜TRM Labs高管Ari Redbord在63億美元幣安盜竊案後，呼籲政府對北韓駭客採取攻勢。這是訪談中的政策主張，並非本次推播時新發生的攻擊。'
    elif mid == '1567996863322263565':
        card['title'] = '【資安事件】媒體報導｜Mercado Bitcoin稱駭侵已受控制，鏈上數據顯示不同情況'
        card['description'] = '媒體報導｜最新鏈上鑑識追蹤了跨11條區塊鏈的4860萬美元資金，發現巴西交易所稱週一已控制入侵後數小時，仍有數千個客戶入金地址的資金遭轉走。'
    else:
        parts = re.findall(r'(?ms)\*\*\d{2}｜.*?(?=\*\*\d{2}｜|\Z)', card.get('description',''))
        if len(parts) != 5 or not all(link in card['description'] for link in (
            'bitcoin-holds-ai-regulation-fears-kospi-halted',
            'greece-approves-10-tax-on-crypto-gains-and-15-levy-on-defi-income',
            'bitcoin-erases-election-rally-ai-stocks-plunge-428-million-crypto-longs',
            'zcash-s-landmark-nu7-upgrade-goes-live-speeding-up-private-payments')):
            raise ValueError('Original five-item digest differs; no write')
        clean = lambda p: re.sub(r'(?:\n[ \t\u200b]*)?─{3,}[\s\u200b]*$', '', p).strip()
        first = clean(parts[0]).replace('Bitcoin 得到了整合', '比特幣呈現盤整').replace('Bitcoin 持有 75,000 美元', '比特幣守住75,000美元')
        greek = ('**02｜希臘加密稅制：兩家媒體同題報導**\n監管／政策\n'
                 'Cointelegraph報導：2027年起對加密收益課稅10%，年度淨收益不超過500歐元者豁免。\n'
                 'CoinDesk報導：DeFi收入稅15%，提供12個月補報期間免逾期申報罰款；加密資產互換規則仍有疑問。\n'
                 '🔗 [Cointelegraph](https://cointelegraph.com/news/greece-approves-10-tax-crypto-gains-2027) · '
                 '[CoinDesk](https://www.coindesk.com/policy/2026/11/06/greece-approves-10-tax-on-crypto-gains-and-15-levy-on-defi-income)\n'
                 '📅 原文發布：11/06 19:05／16:47（台灣時間）')
        third = clean(parts[3]).replace('**04｜','**03｜').replace('中期勝利','期中選舉勝選').replace('空頭補償','空頭回補').replace('加密多頭被消滅','加密多頭部位遭清算')
        fourth = clean(parts[4]).replace('**05｜','**04｜')
        card['description'] = '\n\n──────────────\n\n'.join((first,greek,third,fourth))
    for field in card.get('fields', []):
        field['value'] = field['value'].replace('機器人發現：','原推播紀錄：')
    card['color'] = 0x647FB5 if mid in ('1567912549494689873','1568583218159026229') else card.get('color',0x647FB5)
    card.setdefault('footer', {})['text'] = card.get('footer', {}).get('text','') + '｜'+MARK+'：用詞／分類或同題整理已更正，原來源與時點保留'
    return card

def main():
    base = os.environ['DISCORD_CRYPTO_NEWS_WEBHOOK_URL'].rstrip('/')
    if not re.fullmatch(r'https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[\w.-]+', base):
        raise ValueError('Unexpected configured webhook endpoint')
    def request(method, suffix='', body=None):
        if method not in ('GET','PATCH') or (method == 'PATCH' and suffix.split('/')[-1] not in TARGETS):
            raise ValueError('Only original target reads/patches are allowed')
        req = Request(base+suffix, method=method, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type':'application/json','User-Agent':'WV-checked-copy-correction/1.0'})
        with urlopen(req,timeout=20) as response:
            return json.load(response)
    meta = request('GET')
    if meta.get('channel_id') != CHANNEL or meta.get('guild_id') != '1524947809499877486':
        raise ValueError('Configured webhook has wrong destination')
    plans = []
    for mid in TARGETS:
        old = request('GET','/messages/'+mid)
        if old.get('webhook_id') != meta['id'] or old.get('author',{}).get('id') != meta['id']:
            raise ValueError('Message belongs to another sender')
        before = editable(old['embeds'][0]); after = corrected(old)
        plans.append({'id':mid,'before':digest(before),'after':digest(after),'card':after})
    plan_hash = digest([{k:v for k,v in p.items() if k!='card'} for p in plans])
    if os.getenv('APPLY_CHECKED_COPY') == 'true':
        if os.getenv('EXPECTED_COPY_PLAN_HASH') != plan_hash:
            raise ValueError('Reviewed plan hash does not match live messages')
        for p in plans:
            if p['before'] != p['after']:
                request('PATCH','/messages/'+p['id'],{'embeds':[p['card']],'allowed_mentions':{'parse':[]}})
                if digest(editable(request('GET','/messages/'+p['id'])['embeds'][0])) != p['after']:
                    raise ValueError('Message readback differs')
    print(json.dumps({'plan_hash':plan_hash,'applied':os.getenv('APPLY_CHECKED_COPY')=='true',
                      'messages':[{k:v for k,v in p.items() if k!='card'} for p in plans],
                      'new_messages':0,'deleted_messages':0,'state_access':False},ensure_ascii=False))

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'status':getattr(exc,'code',None)}))
        raise SystemExit(1)
