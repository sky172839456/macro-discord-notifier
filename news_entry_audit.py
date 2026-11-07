"""Checked publisher excerpts; complementary facts stay attributed to each report."""
import re

GREECE_REPORTS = (
    ('Greece approves 10% tax on crypto gains starting in 2027',
     'Greece has approved a 10% tax on cryptocurrency gains starting in 2027, with an exemption for investors whose annual net gains do not exceed 500 euros.',
     'Cointelegraph報導：2027年起對加密資產收益課稅10%；年度淨收益不超過500歐元者豁免。'),
    ('Greece approves 10% tax on crypto gains and 15% levy on DeFi income',
     'Investors will have 12 months to declare past crypto gains without late-filing penalties, though questions remain over crypto-to-crypto swaps.',
     'CoinDesk報導：DeFi收入稅率15%，提供12個月補報期間免逾期申報罰款；加密資產互換的適用規則仍有疑問。'),
    ('Greece Passes Crypto Tax Law With 10% Gains Levy, 15% on Staking and DeFi',
     'Greece has approved a crypto tax framework with a €500 ($557) annual gains threshold and new rules for staking and DeFi income, but lawmakers left important questions about token swaps unresolved.',
     'Decrypt報導：收益稅率10%，質押及DeFi為15%；年度收益門檻500歐元（原文換算約557美元），代幣互換規則仍有待釐清。'),
)

def norm(value):
    return re.sub(r'\s+', ' ', str(value).replace('’', "'")).strip().casefold()

def checked_greece_report(row):
    pair = (norm(row.get('title', '')), norm(row.get('summary', '')))
    return next((i for i, (title, body, _) in enumerate(GREECE_REPORTS)
                 if pair == (norm(title), norm(body))), None)

def checked_reports(row):
    if checked_greece_report(row) is None:
        return {}
    rows = [row, *row.get('verified_greece_reports', [])]
    return {checked_greece_report(r): {'title': r['title'], 'summary': r['summary']}
            for r in rows if checked_greece_report(r) is not None}

def unverified_greece_variant(left, right):
    if (checked_greece_report(left) is None) == (checked_greece_report(right) is None):
        return False
    return all(re.search(r'\bgreece\b', str(r.get('title', '')), re.I)
               and re.search(r'\b(?:tax|levy)\b', str(r.get('title', '')), re.I)
               for r in (left, right))

def merge_greece_context(primary, secondary, merged):
    if checked_greece_report(primary) is None or checked_greece_report(secondary) is None:
        return
    reports = {**checked_reports(primary), **checked_reports(secondary)}
    merged['verified_greece_reports'] = list(reports.values())

def greece_context(row):
    reports = checked_reports(row)
    if len(reports) < 2:
        return None
    return ('同題補充｜依各媒體RSS', '\n'.join(GREECE_REPORTS[i][2] for i in sorted(reports)))
