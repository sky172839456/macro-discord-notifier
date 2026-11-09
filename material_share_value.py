"""Private editorial usefulness gate. Evidence hints, never a truth or trading signal."""
import re
from material_editorial import _text, editorial_angle


def has(pattern, text):
    return bool(re.search(pattern, text, re.I))


def activity_kind(title):
    if not has(r'\b(?:Bitget|Binance|BG)\b|幣安', title):
        return None
    if has(r'\b(?:Launchpool|PoolX|Launchpad)\b', title):
        return 'pool'
    if has(r'\b(?:IPO|rTokens?|tokenized stocks?|subscription)\b|認購|代幣化股票', title):
        return 'subscription'
    return None


DETAILS = {
    '具體任務': r'\b(?:read|quer\w*|search\w*|connect\w*|extract\w*|manage\w*|generat\w*|export\w*|screen\w*|automat\w*)\b.{0,65}\b(?:market data|watchlists?|alerts?|files?|tasks?|PDFs?|tables?|CSV|charts?|candidates?|reports?|diagrams?)\b|(?:讀取|查詢|搜尋|管理|產生|匯出|串接).{0,30}(?:行情|觀察清單|提醒|檔案|任務|圖表|報告)',
    '開放階段': r'\b(?:beta|preview|prototype|pilot|enacted|effective|suspended|paused|patch(?:ed)?)\b|測試版|預覽版|原型|已生效|已暫停|已修補',
    '適用範圍': r'\b(?:Essential|paid plans?|Pro plan|new users?|eligible users?|residents?|retail customers?|European|Taiwan|Spain|France|Poland|EU users?|affected accounts?)\b|新用戶|適用地區|台灣|合資格|付費方案|受影響帳戶',
    '時間期間': r'\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|(?:Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)\.? \d{1,2}|\d+ (?:days?|weeks?|hours?|minutes?)|\d{1,2}:\d{2}|UTC)\b|\d+(?:天|週|小時|分鐘)|截止|生效日',
    '量測數據': r'\b\d[\d,.]*\s*(?:million|billion|users?|samples?|participants?|seconds?|meters?|kilometers?)\b|\d[\d,.]*\s*%|\d+(?:名|人|樣本|公尺|秒)',
    '費用資金條件': r'\b(?:fees? of|costs? of|free tier|free access|read.only|read.write|minimum|maximum|cap of|locked|lock.up|redemption|KYC|withdrawal fee)\b|最低|上限|鎖倉|解鎖|贖回|手續費|唯讀|讀寫權限|身分驗證',
    '方法機制': r'\b(?:MCP|Model Context Protocol|API|servers?|benchmark|sample|controlled experiment|randomized|solar|offline|zero.knowledge|hardware wallet|card numbers?|home address|private keys?)\b|連接協定|基準測試|對照實驗|樣本|離線|太陽能|私鑰|卡號|住址',
    '具體結果反差': r'\b(?:reduc\w*|increas\w*|improv\w*|outperform\w*|measur\w*)\b.{0,45}\d|\b(?:saved|helped|works)\b.{0,80}\bbut\b.{0,60}\b(?:failed|ruined|wrong)\b|降低.{0,20}\d|提高.{0,20}\d|成功.{0,50}(?:失敗|出錯)',
    '影響處置': r'\b(?:withdrawals?|registrations?|exposed|leaked|compromised|rotate keys|disable API keys|targeted scams|patch released|public disclosure)\b|提款|註冊|洩漏|輪替金鑰|停用API|針對性詐騙|修補已發布',
}
TASK_NAMES = ((r'\bwatchlists?\b','觀察清單'), (r'\balerts?\b','提醒'),
              (r'\bmarket data\b','行情資料'), (r'\bfiles?\b','檔案'),
              (r'\bPDFs?\b','PDF'), (r'\bCSV\b','CSV'), (r'\bcandidates?\b','候選人篩選'))


def assess(row):
    title, summary = _text(row.get('title'),400), _text(row.get('summary'),1000)
    body = title+' '+summary
    kind = row.get('material_topic')
    details = [name for name, pattern in DETAILS.items() if has(pattern, summary)]
    result = {'eligible':False, 'reason':'no_reader_value', 'details':details,
              'tasks':[name for pattern,name in TASK_NAMES if has(pattern, summary)], 'route':None}
    if len(summary)<60 or summary.casefold()==title.casefold():
        result['reason']='thin_source'
        return result
    if len(details)<2:
        result['reason']='insufficient_shareable_detail'
        return result
    angle = editorial_angle(title,summary)
    activity = activity_kind(title)
    route = None
    if activity:
        if (has(r'\b(?:stake|staking|deposit|subscribe|subscription|BGB|USDT|USDGO|token allocation)\b|質押|認購|配發', body)
                and len(set(details)&{'適用範圍','時間期間','費用資金條件','量測數據'})>=3):
            route='activity'
    elif kind=='security':
        # A security category alone is not an editorial-value exception.
        if '影響處置' in details and set(details)&{'方法機制','量測數據','適用範圍','時間期間'}:
            route='impact'
    elif kind=='policy' or has(r'\b(?:restrict\w*|accounts? clos\w*|withdrawal fees?|registration rules?)\b|服務限制',title):
        if (has(r'\b(?:approv\w*|enact\w*|propos\w*|ban\w*|restrict\w*|clos\w*|suspend\w*|fees?|rules?|regulation)\b|通過|提案|限制|關閉|規則',body)
                and '適用範圍' in details and set(details)&{'開放階段','時間期間','費用資金條件'}):
            route='impact'
    elif kind in ('ai','innovation','business'):
        if ('具體任務' in details and set(details)&{'方法機制','開放階段','適用範圍','費用資金條件'}
                and has(r'\b(?:add\w*|support\w*|connect\w*|integrat\w*|introduc\w*|launch\w*|releas\w*|unveil\w*|enable\w*|now|can|recruitment)\b|新增|支援|開放|推出|串接',body)):
            route='capability'
        elif kind=='innovation' and has(r'\b(?:prototype|experiment|demonstrat\w*|test\w*|develop\w*)\b|原型|實驗|展示',body) and '量測數據' in details and set(details)&{'時間期間','方法機制','開放階段'}:
            route='explanation'
        elif has(r'\b(?:payments?|withdrawals?|registrations?)\b|支付|提款|註冊',body) and '適用範圍' in details and set(details)&{'費用資金條件','時間期間'}:
            route='impact'
    elif kind=='research':
        if ('具體結果反差' in details and set(details)&{'方法機制','量測數據'}
                and has(r'\b(?:study|research|experiment|benchmark|report)\b|研究|實驗|報告',body)):
            route='explanation'
    elif kind=='interesting':
        if ('具體結果反差' in details and set(details)&{'方法機制','時間期間','量測數據'}):
            route='explanation'
        elif has(r'\b(?:museum|robot|invention|discovery|experiment)\b|博物館|機器人|發明|實驗',title) and '時間期間' in details and has(r'\b(?:interactive|solar|offline|mechanism|explains?|learns?|cooks?)\b|互動|太陽能|離線|原理',summary):
            route='explanation'
    if route:
        result.update(eligible=True,reason=None,route=route)
    return result


def value_copy(result):
    labels={'activity':'活動標的與參與條件，可拆解資格、時程及資金限制',
            'capability':'具體新增操作，可比較使用前後能完成的任務',
            'impact':'讀者使用服務或面對風險的實際影響',
            'explanation':'有方法與結果可拆解的知識點或反差'}
    if not result['eligible']:
        return '現有原文細節不足，先留待核，不應僅靠標題製作。'
    return labels[result['route']]+'。原文可展開：'+'、'.join(result['details'])+'；仍須回查來源與適用限制。'
