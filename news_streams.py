"""Shared event ledger, separate daily budgets; no duplicate cross-channel sends."""
from __future__ import annotations

import os
import re
from datetime import timedelta

FINANCE_SOURCES = (
    {'name': 'CNBC經濟', 'url': 'https://www.cnbc.com/id/20910258/device/rss/rss.html', 'official': False, 'stream': 'finance'},
    {'name': 'CNBC金融', 'url': 'https://www.cnbc.com/id/10000664/device/rss/rss.html', 'official': False, 'stream': 'finance'},
    {'name': 'CNBC科技', 'url': 'https://www.cnbc.com/id/19854910/device/rss/rss.html', 'official': False, 'stream': 'finance'},
    {'name': '聯準會', 'url': 'https://www.federalreserve.gov/feeds/press_all.xml', 'official': True, 'stream': 'finance'},
)
CRYPTO = r'\b(?:bitcoin|btc|ethereum|ether|crypto\w*|stablecoin\w*|tether|usdt|usdc|blockchain|coinbase|binance|bitget|okx|solana|digital assets?)\b'
TOPICS = (
    ('policy', '🏛️', '政策／利率', r'\b(?:federal reserve|fed|ecb|bank of japan|boj|central bank|treasury|trump|white house|tariffs?|sanctions?|interest rates?|capital controls?)\b',
     r'\b(?:announces?|imposes?|raises?|cuts?|holds?|approves?|signs?|bans?|orders?|enacts?|expands?|hikes?|warns?|signals?|rates?|tariffs?|sanctions?|liquidity)\b',
     '觀察關聯｜利率、政策與流動性可能影響加密市場的資金成本及風險偏好；不代表價格必然同向變動。'),
    ('banking', '🏦', '銀行／資金', r'\b(?:blackrock|fidelity|jpmorgan|goldman sachs|banks?|credit|financial system|bond market)\b',
     r'\b(?:liquidity|crisis|collapse|bankrupt\w*|rescue|bailout|default\w*|withdrawals?|custody|settlement|launch\w*|stress|funding)\b',
     '觀察關聯｜銀行信用與資金供應變化可能傳導至市場流動性及避險需求。'),
    ('technology', '💻', '科技／企業', r'\b(?:nvidia|microsoft|alphabet|google|amazon|meta|tsmc|taiwan semiconductor|tesla|musk|strategy)\b',
     r'\b(?:export (?:ban|controls?|restrictions?)|capital expenditure|capex|spending|investment|debt|financing|acquisition|tariffs?|sanctions?|bitcoin|crypto|digital assets?)\b',
     '觀察關聯｜重大科技投資或政策限制可能影響整體風險偏好；與加密市場的關聯屬間接傳導。'),
    ('energy', '🛢️', '能源／地緣', r'\b(?:oil|opec|energy supply|strait of hormuz|shipping route)\b',
     r'\b(?:supply cut|cuts? output|production cut|disruption|blockade|sanctions?|war|ceasefire|attack)\b',
     '觀察關聯｜能源供應事件可能改變通膨與利率預期，間接影響風險資產。'),
)


def finance_topic(item):
    title = str(item.get('title', ''))
    body = title + ' ' + str(item.get('summary', ''))
    # Existing macro notifications own release results and standard FOMC cards.
    if re.search(r'\b(?:consumer price index|producer price index|nonfarm payrolls?|jobless claims|personal consumption expenditures|FOMC statement)\b', title, re.I):
        return None
    if re.search(r'\b(?:live updates?|opinion|price prediction|what to watch|stocks? to buy|sponsored|recap|roundup)\b|^(?:why|how|what|can)\b|^(?:analysis|economists):', title, re.I):
        return None
    if re.search(CRYPTO, title, re.I):
        import crypto_news_notifier as news
        category = news.category_for(body)
        if category:
            return {'category': category, 'copy': ''}
    for key, icon, label, actor, action, copy in TOPICS:
        if re.search(actor, title, re.I) and re.search(action, body, re.I):
            if key == 'policy' and not re.search(r'\b(?:rates?|liquidity|tariffs?|sanctions?|capital controls?|balance sheet|monetary policy|quantitative|bond purchases?|repo)\b', body, re.I):
                continue
            if key == 'banking' and re.search(r'\b(?:world bank|imf|international monetary fund)\b', title, re.I):
                continue
            return {'category': {'key': 'finance_' + key, 'icon': icon, 'label': label, 'priority': 'normal', 'keywords': ()}, 'copy': copy}
    return None


def stream_for(item):
    # Direct digital-asset events take one destination even on a finance feed.
    return 'crypto' if re.search(CRYPTO, str(item.get('title', '')), re.I) else item.get('stream', 'crypto')


def categories():
    import crypto_news_notifier as news
    rows = {r['key']: r for r in news.CATEGORIES}
    for key, icon, label, *_ in TOPICS:
        rows['finance_' + key] = {'key': 'finance_' + key, 'icon': icon, 'label': label, 'priority': 'normal', 'keywords': ()}
    return rows


def fetch_finance():
    import crypto_news_notifier as news
    rows, statuses = [], []
    for cfg in FINANCE_SOURCES:
        try:
            found = news.parse_feed(news.http_text(cfg['url'], attempts=1), cfg)
            rows.extend(found)
            statuses.append((cfg['name'], len(found), None))
        except Exception as error:
            statuses.append((cfg['name'], -1, type(error).__name__))
    return rows, statuses


def restore(row):
    from notification_quality import published_time
    row = dict(row)
    row['published'] = published_time(row['published'])
    if isinstance(row.get('category'), str):
        row['category'] = categories()[row['category']]
    return row


def run(now):
    import crypto_news_notifier as news
    import news_auto_recovery as auto
    import slim_policy
    from notification_quality import rank_news, published_time
    from news_editorial import member_ids, history_row
    from market_brief_v2 import remember_news
    destinations = {'crypto': os.getenv('DISCORD_CRYPTO_NEWS_WEBHOOK_URL'),
                    'finance': os.getenv('DISCORD_FINANCE_NEWS_WEBHOOK_URL')}
    if not all(destinations.values()):
        raise RuntimeError('兩類新聞目的地尚未完整設定；未改送其他頻道')
    state = news.load_state()
    rows, statuses = news.fetch_all()
    financial, finance_status = fetch_finance()
    state['finance_source_status'] = [{'source': n, 'count': c, 'error': e} for n, c, e in finance_status]
    if not any(c >= 0 for _, c, _ in finance_status):
        print('警告：本輪金融新聞來源皆暫缺；不宣稱沒有金融事件。')
        if state.get('finance_outage_day') != now.date().isoformat() and os.getenv('DISCORD_LOG_WEBHOOK_URL'):
            try:
                news.send_discord(os.environ['DISCORD_LOG_WEBHOOK_URL'], {
                    'title': '【系統紀錄】 金融新聞來源暫缺',
                    'description': '本輪金融來源皆未成功讀取，系統會自然重試；不能據此認定沒有金融事件。加密與其他通知獨立處理。',
                    'color': 0x7566A5, 'timestamp': now.isoformat()}, '新聞系統｜服務紀錄')
            except Exception:
                pass
            else:
                state['finance_outage_day'] = now.date().isoformat()
    seen = state.setdefault('seen', {})
    # First enablement establishes only the new feed baseline, never replaying it.
    if not state.get('finance_initialized') and any(c >= 0 for _, c, _ in finance_status):
        old_urls = {news.canonical_url(r['url']) for r in rows}
        for row in financial:
            if news.canonical_url(row['url']) not in old_urls:
                seen[row['id']] = now.date().isoformat()
        state['finance_initialized'] = True
    all_rows = rows + financial
    if not any(c >= 0 for _, c, _ in statuses + finance_status):
        raise RuntimeError('新聞來源皆無法讀取')
    if not state.get('initialized'):
        seen.update({r['id']: now.date().isoformat() for r in all_rows})
        state['initialized'] = True
        news.save_state(state)
        return len(all_rows), 0
    history = [r for r in state.get('headline_history', []) if published_time(r['date']) >= now - timedelta(hours=24)]
    state['headline_history'] = history
    pending = [restore(r) for r in state.get('pending', []) if r['id'] not in seen]
    candidates = [r for r in all_rows + pending if r['id'] not in seen and r['published'] >= now - timedelta(hours=24)]
    ready = rank_news(auto.route(slim_policy.merge_pending(candidates), state, now))
    # Recovery can remove a retry row. Persist the ready outbox before any send
    # so a Discord failure never loses the only cached copy of that article.
    state['pending'] = [news.serialize_pending(r) for r in ready]
    news.save_state(state)
    sent, immediate_count = 0, 0
    retained = []

    def delivered(group):
        for row in group:
            for identifier in member_ids(row):
                seen[identifier] = now.date().isoformat()
            history.append(history_row(row, now))
            remember_news(state, row, now)

    for row in ready:
        if any(news.same_news_event(row, restore({**h, 'category': row['category']})) for h in history):
            for identifier in member_ids(row):
                seen[identifier] = now.date().isoformat()
            continue
        stream = stream_for(row)
        # Finance headlines need an explicit policy/service decision to be urgent.
        urgent = slim_policy.material_news(row) and (stream == 'crypto' or bool(re.search(
            r'\b(?:imposes? tariffs?|enacts?|announces? emergency|bank collapse|capital controls?|halts? withdrawals?)\b', row['title'], re.I)))
        if urgent and immediate_count < news.MAX_IMMEDIATE_PER_RUN:
            card = slim_policy.news_card(row, now=now)
            card['title'] = ('【金融快訊】 ' if stream == 'finance' else '【重大快訊】 ') + card['title']
            if stream == 'finance' and row.get('transmission'):
                card['description'] += '\n\n' + row['transmission']
            news.send_discord(destinations[stream], card, '金融風向' if stream == 'finance' else '幣圈有事')
            delivered([row]); immediate_count += 1; sent += 1
            state['pending'] = [news.serialize_pending(r) for r in ready if r['id'] not in seen]
            news.save_state(state)
        else:
            retained.append(row)
    state['pending'] = [news.serialize_pending(r) for r in retained if r['id'] not in seen]
    local = now.astimezone(news.TAIPEI)
    if local.hour >= 20:
        slot = f'daily:{local:%Y-%m-%d}'
        slots = state.setdefault('stream_digest_progress', {})
        # Keep any existing same-day crypto quota on migration.
        if 'crypto' not in slots and (state.get('digest_progress') or {}).get('slot') == slot:
            slots['crypto'] = dict(state['digest_progress'])
        for stream in ('crypto', 'finance'):
            progress = slots.setdefault(stream, {'slot': slot, 'ids': [], 'closed': False})
            if progress['slot'] != slot:
                progress = {'slot': slot, 'ids': [], 'closed': False}; slots[stream] = progress
            if stream == 'crypto' and state.get('last_digest_slot') == slot:
                progress['closed'] = True
            if progress['closed']:
                continue
            selected = [r for r in retained if r['id'] not in seen and stream_for(r) == stream][:max(0, 5-len(progress['ids']))]
            for group in slim_policy.digest_groups(selected, now):
                card = slim_policy.digest_card(group, now)
                card['title'] = ('【金融新聞】 🌐 金融風向' if stream == 'finance' else '【加密新聞】 🪙 幣圈有事') + f'｜{local:%m/%d}'
                if stream == 'finance':
                    # One concise transmission note per selected event.
                    notes = '\n'.join(f"{i+1:02d}｜{r['transmission']}" for i, r in enumerate(group) if r.get('transmission'))
                    if notes:
                        card.setdefault('fields', []).append({'name': '與加密市場的關聯', 'value': notes[:1024], 'inline': False})
                news.send_discord(destinations[stream], card, '金融風向' if stream == 'finance' else '幣圈有事')
                delivered(group)
                progress['ids'].extend(r['id'] for r in group)
                state['pending'] = [news.serialize_pending(r) for r in retained if r['id'] not in seen]
                news.save_state(state); sent += 1
            if selected:
                progress['closed'] = True
                news.save_state(state)
    cutoff = (now - timedelta(days=14)).date().isoformat()
    state['seen'] = {k: d for k, d in seen.items() if d >= cutoff}
    translation_cutoff = (now-timedelta(days=30)).date().isoformat()
    state['translation_cache'] = {k: v for k, v in state.get('translation_cache', {}).items() if v.get('date', '') >= translation_cutoff}
    news.save_state(state)
    return len(all_rows), sent
