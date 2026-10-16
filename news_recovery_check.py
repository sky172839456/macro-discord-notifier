"""Public synthetic provider checks; no Discord credentials, state or sends."""
import json
from urllib.parse import urlencode
import crypto_news_notifier as news
import news_auto_recovery as auto


def run():
    source = 'SEC approves Bitcoin ETF'
    rows = []
    for provider in ('MyMemory', 'Bing'):
        try:
            if provider == 'MyMemory':
                raw = json.loads(news.http_text(news.TRANSLATION_URL+'?'+urlencode({'q':source,'langpair':'en|zh-TW','mt':'1'}), attempts=1))
                if str(raw.get('responseStatus',200)) != '200' or raw.get('quotaFinished'):
                    raise ValueError('provider quota/status')
                translated = raw['responseData']['translatedText']
            else:
                translated = auto.translate_bing(source)
            translated = auto.checked_copy(source, news.normalize_zh_title(news.clean_text(translated)))
            rows.append({'provider':provider, 'ok':True, 'translated':translated})
        except Exception as exc:
            # Never emit the public form token, cookies or raw error response.
            rows.append({'provider':provider, 'ok':False, 'error':type(exc).__name__})
    print(json.dumps({'synthetic_test':True,'source':source,'providers':rows,'discord_sent':False}, ensure_ascii=False))
    return 0 if any(row['ok'] for row in rows) else 1


if __name__ == '__main__': raise SystemExit(run())
