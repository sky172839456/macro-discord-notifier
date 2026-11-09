"""Complete private-source excerpts, never a character-cut release/CLI fragment."""
from html.parser import HTMLParser
import html
import re

VERSION = 3
RELEASE_SOURCES = {'Claude Code Releases', 'Claude Platform Updates'}


class ReleaseList(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []
        self.current = []
        self.feed(value)
    def handle_starttag(self, tag, attrs):
        if tag == 'li':
            if self.depth == 0:
                self.current = []
            self.depth += 1
        elif self.depth and tag in ('p', 'br'):
            self.current.append(' ')
    def handle_endtag(self, tag):
        if tag == 'li' and self.depth:
            self.depth -= 1
            if not self.depth:
                # CLI metavariables are text, not HTML tags or member mentions.
                text = ''.join(self.current).replace('<', '〈').replace('>', '〉')
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    self.parts.append(text)
    def handle_data(self, value):
        if self.depth:
            self.current.append(value)


def release_parts(value):
    return ReleaseList(value).parts[:12]


def release_title(row):
    title = str(row.get('title') or '')
    match = re.fullmatch(r'Claude Code\s+(v\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*)',title)
    if row.get('source')=='Claude Code Releases' and match:
        return 'Claude Code 版本更新 '+match[1]
    return None


def excerpt_parts(row):
    from news_auto_recovery import source_sentences
    parts = row.get('summary_parts')
    if not isinstance(parts, list):
        parts = [str(row.get('summary') or '')]
    selected = []
    for part in parts:
        # The provider limit is in UTF-8 bytes. Split only at whole sentences;
        # never trim a negation, unit, command or another release bullet.
        for sentence in source_sentences(str(part)):
            if sentence and len(sentence.encode('utf-8')) <= 450:
                selected.append(sentence)
                if len(selected) == 2:
                    return selected
    return selected


def display_points(points, budget=900):
    rows = []
    for value in points[:2]:
        value = re.sub(r'\s+', ' ', html.unescape(str(value))).strip()
        # Preserve CLI syntax safely in Discord without treating it as HTML.
        value = value.replace('<', '〈').replace('>', '〉')
        part = '• '+value
        if len('\n'.join(rows+[part])) <= budget:
            rows.append(part)
    return '\n'.join(rows) or '來源段落較長，尚無可完整呈現的短摘要；請開啟原文核對。'


def release_features(row):
    if row.get('source') not in RELEASE_SOURCES:
        return None
    parts = row.get('summary_parts') or [str(row.get('summary') or '')]
    value = ' '.join(parts)
    return {
        'model': bool(re.search(r'\bAdded\b.{0,45}\bClaude\b|default .{0,20}model',value,re.I)),
        'settings': bool(re.search(r'Added\s+--settings\b',value,re.I)),
        'fixes': bool(re.search(r'\bFixed\b',value)),
    }


def new_connection(title, summary):
    """An incident/patch mentioning MCP is not a newly added connection."""
    def claim(value):
        if re.search(r'\b(?:fixed|fixes|patched|repair|vulnerabilit\w*|breach|leak\w*)\b',value,re.I):
            return False
        return bool(re.search(r'\b(?:MCP|Model Context Protocol|connectors?|plugins?|plug-ins?|automated workflows?|automation|integrat\w*)\b',value,re.I))
    if claim(title):
        return True
    from news_auto_recovery import source_sentences
    return any(claim(part) for part in source_sentences(summary))
