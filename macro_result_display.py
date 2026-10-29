"""Member-facing comparisons. Formatting never supplies missing observations."""
import math


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def comparison(label, current, previous=None, *, unit="%", decimals=1, signed=False,
               change_unit="個百分點", current_period="", previous_period="", comparable=True):
    def value(x, sign=False):
        if not finite(x):
            return "暫缺"
        return format(x, ("+" if sign else "") + f",.{decimals}f") + unit
    lines = [f"**{label}**",
             "本次 " + ("**"+value(current, signed)+"**" if finite(current) else "暫缺") + (f"（{current_period}）" if current_period else ""),
             "前值 " + value(previous, signed) + (f"（{previous_period}）" if previous_period else "")]
    if comparable and finite(current) and finite(previous):
        # Compare the displayed observations, not undisplayed extra precision.
        delta = round(round(current, decimals)-round(previous, decimals), decimals)
        if delta == 0: delta = 0.0
        lines.append("變化 " + format(delta, f"+,.{decimals}f") + " " + change_unit)
    return "\n".join(lines)

