"""Direction checks for terminating a streak; never infer asset returns from flows."""
import re

TITLE = 'Bitcoin ETFs Snap Two-Week Losing Streak Despite Late-Week Slide'
COPY = '儘管週末前資金流出，比特幣 ETF 仍結束連兩週頹勢'


def validate(source, translated):
    action = re.search(r'\b(?:snap(?:s|ped)?|end(?:s|ed)?|break(?:s)?|broke)\s+(?:an?\s+)?(?:[\w-]+\s+){0,3}(losing|winning)\s+streak\b', source, re.I)
    if not action:
        return
    # Negated/conditional attempts stay under existing qualification checks.
    prefix = source[max(0, action.start()-35):action.start()]
    if re.search(r'\b(?:not|never|failed? to|fails? to)\b', prefix, re.I):
        if not re.search(r'未|不|無|沒', translated):
            raise ValueError('translation lost failure/negation of streak termination')
        return
    end = r'結束|終結|終止|打破|中止'
    target = r'頹勢|跌勢|虧損|淨流出|連敗' if action[1].lower() == 'losing' else r'漲勢|淨流入|連勝'
    if not re.search(end, translated) or not re.search(target, translated):
        raise ValueError('translation lost streak termination/direction')
    weeks = re.search(r'\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)[- ]week', source, re.I)
    if weeks:
        values = {'one':('1','一'),'two':('2','二','兩'),'three':('3','三'),'four':('4','四'),
                  'five':('5','五'),'six':('6','六'),'seven':('7','七'),'eight':('8','八'),
                  'nine':('9','九'),'ten':('10','十')}
        choices = values.get(weeks[1].lower(), (weeks[1],))
        if not any(re.search(re.escape(v)+r'\s*(?:週|周)',translated) for v in choices):
            raise ValueError('translation lost streak duration')
