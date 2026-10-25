"""Narrow verified news contexts; material changes remain independent events."""
import re
from datetime import timedelta
from notification_quality import numeric_values, published_time

CORE_TITLES = (
    "Bitcoin Core changes security policy as AI makes bugs easier to find",
    "Bitcoin Core Rewrites Its Security Policy for a World Where AI Finds Bugs in One Prompt",
)
SOLANA_PATH = "/tech/2026/10/22/solana-completes-alpenglow-upgrade-here-s-what-it-means-for-users"
SWISS_PATH = "/news/switzerland-approves-first-spot-bitcoin-etf-for-retail-investors"

def norm(value):
    return re.sub(r"\s+", " ", str(value).replace("’", "'").strip()).casefold()

def core_policy_text(value):
    text = norm(value)
    return (any(text.startswith(norm(title)) for title in CORE_TITLES)
            and not re.search(r"\b(?:new vulnerabilit(?:y|ies)|new exploits?|active exploits?|ongoing attack|additional victims|losses (?:rise|revised)|funds recovered|withdrawals halted|not (?:adopted|implemented|approved)|revoked|reject(?:s|ed)|denies|denied|withdrawn|cancelled)\b", text))

def verified_key(row):
    title = norm(row.get("title", ""))
    body = norm(row.get("summary", ""))
    text = title + " " + body
    if title in {norm(t) for t in CORE_TITLES} and core_policy_text(text):
        return "bitcoin-core-easy-discovery-policy"
    # These are reports of the same completed activation, not plans or testnet.
    activation = (
        re.fullmatch(r"solana alpenglow goes live in 'most ambitious' upgrade since ethereum's merge", title)
        or re.fullmatch(r"solana completes alpenglow upgrade[.!]? here's what it means for users", title)
        or (SOLANA_PATH in str(row.get("url", "")) and
            title == norm("Solana's biggest network change since 2020 is live. Here's how users benefit"))
    )
    if activation:
        if re.search(r"\b(?:testnet|plans?|proposes?|delayed|denies?|denied|not|never|new exploits?|attacks?|breach|outage|halted|quantumglow|rotor|revised|fees|losses|victims|recovered)\b", text):
            return None
        # Verified numbers are complementary context, never arbitrary mismatches.
        if numeric_values(text) - numeric_values("2020 150"):
            return None
        if not re.search(r"\b(?:mainnet|voting system|consensus protocol|towerbft)\b", body):
            return None
        return "solana-alpenglow-mainnet-activation"
    return None

def same_verified_event(left, right):
    key = verified_key(left)
    if not key or key != verified_key(right):
        return False
    if abs(published_time(left["published"]) - published_time(right["published"])) > timedelta(hours=24):
        return False
    if key == "bitcoin-core-easy-discovery-policy":
        from news_editorial import measures, dated_terms, progress_terms, stage
        a = left.get("title", "") + " " + left.get("summary", "")
        b = right.get("title", "") + " " + right.get("summary", "")
        return all(extract(a) == extract(b) for extract in (measures, dated_terms, progress_terms, stage))
    return True

def same_swiss_launch_version(left, right):
    from crypto_news_notifier import canonical_url
    a, b = canonical_url(left.get("url", "")), canonical_url(right.get("url", ""))
    if not a or a != b or SWISS_PATH not in a:
        return False
    if published_time(left["published"]) != published_time(right["published"]):
        return False
    summary = norm(left.get("summary", ""))
    if not summary or summary != norm(right.get("summary", "")):
        return False
    if not all(term in summary for term in ("bit asset management", "six swiss exchange", "november", "switzerland")):
        return False
    def title_ok(row):
        title = norm(row.get("title", ""))
        return bool(re.fullmatch(
            r"switzerland(?:'s first retail spot bitcoin etf targets november launch| approves (?:the )?first spot bitcoin etf (?:for|aimed at) retail investors)[.!]?", title))
    return title_ok(left) and title_ok(right)

def keep_history(row, now):
    age = now - published_time(row["date"])
    # Generic history and source freshness retain their existing 24-hour limit.
    return age <= timedelta(hours=24) or (verified_key(row) is not None and age <= timedelta(hours=48))
