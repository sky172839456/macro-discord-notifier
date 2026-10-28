"""Presentation-only spacing; source text and Discord limits take precedence."""
from __future__ import annotations
import re

SPACER = "\n\n\u200b"


def text_size(card):
    return (len(str(card.get("title") or "")) + len(str(card.get("description") or ""))
            + len(str((card.get("author") or {}).get("name") or ""))
            + len(str((card.get("footer") or {}).get("text") or ""))
            + sum(len(str(f.get("name") or "")) + len(str(f.get("value") or ""))
                  for f in card.get("fields") or []))


def paragraphs(text):
    # Do not interpret source code, URLs, sentence punctuation or numeric signs.
    if chr(96)*3 in text:
        return text
    lines = []
    for line in text.split("\n"):
        heading = bool(re.fullmatch(r"\s*(?:#{1,3} .+|\*\*[^*]+\*\*)\s*", line))
        bullet = bool(re.match(r"^\s*• ", line))
        if (heading or bullet) and lines and lines[-1].strip():
            lines.append("")
        if line or not lines or lines[-1]:
            lines.append(line)
        if heading:
            lines.append("")
    return "\n".join(lines).rstrip("\n")


def readable_card(card):
    """Add whitespace only, without truncating facts or adding spacer fields."""
    def update(target, key, candidate, limit):
        old = str(target.get(key) or "")
        if len(candidate) <= limit and text_size(card) + len(candidate) - len(old) <= 5900:
            target[key] = candidate

    fields = card.get("fields") or []
    description = str(card.get("description") or "")
    if description:
        update(card, "description", paragraphs(description), 4096)
        if fields and not str(card["description"]).endswith(SPACER):
            update(card, "description", str(card["description"]) + SPACER, 4096)
    for i, field in enumerate(fields):
        field["inline"] = False
        value = str(field.get("value") or "")
        if not value:
            continue
        update(field, "value", paragraphs(value), 1024)
        if i < len(fields)-1 and not str(field["value"]).endswith(SPACER):
            update(field, "value", str(field["value"]) + SPACER, 1024)
    return card

