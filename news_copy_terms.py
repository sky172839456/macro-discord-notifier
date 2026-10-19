"""Source-scoped terminology repairs, shared by cached and newly rendered copy."""
from __future__ import annotations

import re
from decimal import Decimal


def repair_translation(source, translated):
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
