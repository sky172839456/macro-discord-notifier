"""Source-scoped terminology repairs, shared by cached and newly rendered copy."""
from __future__ import annotations

import re
from decimal import Decimal


def repair_translation(source, translated):
    # 已核對的 CFTC／CME 原文：perps 是永續合約，may 與未證明均須保留。
    normalized = re.sub(r'\s+', ' ', source.replace('’', "'").replace('‘', "'").strip()).casefold()
    cftc_title = ('U.S. CFTC rebuffs CME legal stance in consequential fight '
                  'over perpetual futures')
    cftc_summary = ("The future of perps in the U.S. may be at stake as the CFTC argues "
                    "that CME hasn't shown the new policy is hurting it after the "
                    "agency OK'd its first bitcoin perp.")
    if normalized == cftc_title.casefold():
        translated = '在關鍵永續期貨爭議中，美國 CFTC 反駁 CME 的法律立場'
    elif normalized == cftc_summary.casefold():
        translated = ('美國永續合約的未來可能受到影響；CFTC 主張，該機關核准首個比特幣永續合約後，'
                      'CME 並未證明新政策對其造成損害。')
    # 軟體發布與IPO撤回的狹義語境；不改寫一般cut/pull/release。
    if re.search(r'\bbackport fixes\b.*\bcut releases immediately\b', source, re.I):
        translated = translated.replace('立即刪除版本', '立即發布修正版').replace('刪除版本', '發布修正版')
        translated = translated.replace('回溯修復', '回溯套用修補')
    if re.search(r'\bSolidigm pulls IPO\b|\bpulled IPOs\b', source, re.I):
        translated = translated.replace('拉動 IPO', '撤回 IPO').replace('拉動IPO', '撤回IPO')
        translated = translated.replace('IPO 拉動', 'IPO 撤回').replace('IPO拉動', 'IPO撤回')
    if re.search(r'\bAI buildout\b', source, re.I):
        translated = translated.replace('AI 的構建', 'AI 基建擴張').replace('AI的構建', 'AI基建擴張')
    if re.search(r'\bneoclouds\b', source, re.I):
        translated = translated.replace('新雲', '新興雲端服務商')
    if re.search(r'\bSpaceX\b', source, re.I) and re.search(r'\bTesla\b', source, re.I) and re.search(r'\belection stakes\b', source, re.I):
        translated = translated.replace('選舉權益', '選舉利害關係')
    if re.search(r'\bBitcoin circles\b.*\bETF cost basis\b', source, re.I):
        translated = translated.replace('Bitcoin圈為', '比特幣徘徊在').replace('Bitcoin 圈為', '比特幣徘徊在')
        translated = translated.replace('成本基礎', '成本基準')
    if re.search(r'\bBitcoin\b', source, re.I) and re.search(r'\bextended (?:its )?daily losses to\b', source, re.I):
        translated = translated.replace('每日損失延長至', '單日跌幅擴大至').replace('延長每日損失至', '單日跌幅擴大至')
    if re.search(r'\bSolana\b.*\bAlpenglow\b', source, re.I):
        translated = translated.replace('阿爾卑斯光', 'Alpenglow').replace('索拉娜', 'Solana')
        if normalized == "solana alpenglow goes live in 'most ambitious' upgrade since ethereum's merge":
            translated = translated.replace('將進行', '已完成').replace('將上線', '已上線')

    # 已核對的完整來源定稿；日期、語氣、角色及資格一變，不套固定譯文。
    exact_copy = {
        'Qubic restarts blockchain, opens recovery claims after $1.4M hack':
            'Qubic 在140萬美元駭客攻擊後重啟區塊鏈，開放資產追回申請',
        'Crypto rises with Asian tech stocks, zcash extends gain after setting upgrade date':
            '加密資產隨亞洲科技股上漲，Zcash 確定升級日期後延續漲勢',
        'Housing is flashing warning signs just as the Fed weighs more interest rate hikes':
            '聯準會考慮進一步升息之際，房市浮現警訊',
        ('Lloyds drew the most complaints despite having no published policy restricting crypto '
         'transfers, according to a Stand With Crypto report.'):
            '根據 Stand With Crypto 報告，Lloyds 收到的投訴最多，儘管該行未公布限制加密資產轉帳的政策。',
        'Bitcoin is rejected at $83K as US bond yields reverse higher with equities':
            '比特幣在8.3萬美元受阻，美國公債殖利率轉升、股市走高',
        "Market participants weigh in on SEC's proposed crypto regulations":
            '市場參與者就 SEC 擬議的加密資產規則發表意見',
        ("The financial agency is scheduled to close public comments on its "
         "'Regulation Crypto Assets' proposed in August."):
            '該監管機關預定結束對八月提出的《Regulation Crypto Assets》提案公開徵詢意見。',
        ("Nine other crypto platforms voluntarily restricted app access in Kazakhstan, "
         "prompting the regulator to withdraw its claims against them."):
            '另外九個加密平台已自願限制在哈薩克的應用程式存取，因此監管機關撤回對這些平台的相關法律請求。',
    }
    for original, copy in exact_copy.items():
        if normalized == original.casefold():
            translated = copy
            break
    # 稅務提案不得混成商品出口稅，也不把研議中的提案寫成已生效。
    if re.fullmatch(r'France advances stablecoin tax, eyes self-custodial wallets and exit tax proposals[.!]?', source.strip(), re.I):
        translated = '法國推進穩定幣稅制，研議自託管錢包與離境稅提案'
    if re.search(r'\bexit tax(?:es)?\b', source, re.I) and '出口稅' in translated:
        if re.search(r'\bexport tax(?:es)?\b', source, re.I):
            raise ValueError('mixed exit and export tax meanings require another translation')
        translated = translated.replace('出口稅', '離境稅')
    if re.search(r'\bself-custodial wallets?\b', source, re.I):
        translated = translated.replace('自我保管錢包', '自託管錢包')
    if re.search(r'\bcertain stablecoin swaps\b', source, re.I) and not re.search(r'\bswap contracts?\b', source, re.I):
        translated = translated.replace('穩定幣掉期', '穩定幣兌換')

    # DeFi 策略管理者與美術館策展人不同；混合語境不做全域取代。
    if (re.search(r'\bcurators?(?:-managed)?\b', source, re.I)
            and re.search(r'\b(?:lending strategies|defi vaults?|crypto vaults?)\b', source, re.I)
            and '策展人' in translated):
        if re.search(r'\b(?:museum|exhibition|art gallery)\b', source, re.I):
            raise ValueError('mixed curator meanings require another translation')
        translated = translated.replace('策展人', '策略管理人')
    if re.search(r'\bcrypto vault deposits\b', source, re.I):
        translated = translated.replace('加密保管庫', '加密資產金庫')

    # USD1 是幣種名稱；僅在原文明確連結發行方與此幣時補回專名。
    if re.search(r'\bWorld Liberty(?: Financial)?[’\']s USD1 stablecoin\b', source, re.I) and not re.search(r'\bUSD1\b', translated):
        translated, restored = re.subn(
            r'(World\s+Liberty(?:\s+Financial)?\s*的?\s*)(?:美元|美金)穩定幣',
            r'\1USD1 穩定幣', translated, flags=re.I)
        if not restored:
            raise ValueError('USD1 stablecoin identity not preserved')

    # 完整原標題已明確提供主體、停鏈、被盜錢包數及弱種子語境。
    # 僅處理這種完整句型，不能將預計／否認停鏈或凍結資金改成停鏈。
    wallet_incident = re.fullmatch(
        r'([A-Za-z][A-Za-z0-9-]{1,30}) freezes chain after attacker drains '
        r'(\d+(?:\.\d+)?K) wallets with weak seeds[.!]?', source.strip(), re.I)
    if wallet_incident:
        subject, count = wallet_incident.groups()
        wallets = Decimal(count[:-1]) * 1000
        if wallets != wallets.to_integral_value():
            raise ValueError('wallet count must be a whole number')
        translated = (f'{subject} 暫停區塊鏈運作，攻擊者盜取'
                      f'{int(wallets):,}個使用弱種子金鑰的錢包內資產')

    # 法院與招攬、收益分成與削減不能只靠英文字面判斷。
    if (re.search(r'\b(?:circle|usdc|stablecoins?)\b', source, re.I)
            and re.search(r'\bpartners?\b', source, re.I)
            and re.search(r'\bbigger cut\b', source, re.I)
            and not re.search(r'\b(?:cuts? (?:in|to)|job cuts?|rate cuts?)\b', source, re.I)):
        translated = re.sub(r'更大(?:的)?削減', '更高的收益分成', translated)
        if re.search(r'削減|削减', translated):
            raise ValueError('ambiguous revenue share translation')
    if re.search(r'\bUSDC economics\b', source, re.I):
        translated = re.sub(r'USDC\s*(?:經濟學|经济学)', 'USDC 商業模式', translated)

    network = bool(re.search(r'\b(?:solana|blockchain|validators?|mainnet|staking)\b', source, re.I))
    if network and re.search(r'\bstake\b', source, re.I):
        if re.search(r'\b(?:equity|shareholding|ownership stake)\b', source, re.I):
            if '股權' in translated:
                raise ValueError('mixed stake meanings require another translation')
        else:
            translated = translated.replace('股權', '質押').replace('股权', '質押')
    if network and re.search(r'\bhosting\b', source, re.I):
        if re.search(r'\b(?:custody|custodial)\b', source, re.I):
            if '託管' in translated:
                raise ValueError('mixed hosting and custody require another translation')
        else:
            translated = translated.replace('託管', '主機服務').replace('托管', '主機服務')
    if re.search(r'\boperational systems\b', source, re.I) and not re.search(r'\boperating systems?\b', source, re.I):
        translated = translated.replace('操作系統', '營運系統')

    # 只在公司與資產儲備語境修正 Strategy；一般策略照常保留。
    if re.search(r'\bStrategy\b', source) and re.search(r'\b(?:bitcoin|btc|treasury)\b', source, re.I):
        translated = re.sub(r'(公司|巨頭|巨头)\s*策略', r'\1 Strategy', translated)
        if 'Strategy' not in translated:
            raise ValueError('Strategy company name not preserved')
    if re.search(r'\beyes Asia\b', source, re.I):
        translated = re.sub(r'\beyes\s+Asia\b', '瞄準亞洲', translated, flags=re.I)

    # 此已知事故的代幣數量不改成美元；數字等值另由共同檢查器驗證。
    if re.search(r'\bunauthori[sz]ed\s+mint\b', source, re.I):
        for number in re.findall(r'(?<![\w$€£])(\d+(?:\.\d+)?)M\s+CYS\b', source, re.I):
            if not re.search(r'\bCYS\b', translated, re.I):
                raise ValueError('minted token denomination not preserved')
            if not re.search(r'[$€£]|\b(?:USD|dollars?)\b', source, re.I) and re.search(r'美元|美金|[$€£]', translated):
                raise ValueError('minted token count translated as money')
            amount = Decimal(number) * 100
            display = format(amount, 'f').rstrip('0').rstrip('.') if '.' in format(amount, 'f') else str(amount)
            translated = re.sub(r'\b' + re.escape(number) + r'M\s+CYS\b', display + '萬枚 CYS', translated, flags=re.I)
    return translated
