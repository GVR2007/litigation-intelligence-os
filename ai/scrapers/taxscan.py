"""
Taxscan.in scraper — ITAT Weekly Roundup + live RSS feed.

Strategy:
  1. RSS feed → https://www.taxscan.in/feed/ (latest 13+ items)
     - Includes "ITAT Weekly Roundup" which lists ~27 cases each
  2. ITAT Weekly Roundup article parsing:
     - Each roundup article at https://www.taxscan.in/top-stories/itat-weekly-roundup-...
     - Contains 20-30 case summaries with section, parties, ratio, outcome
  3. Direct income-tax pages for individual case articles

RSS structure confirmed:
  <item>
    <title><![CDATA[ITAT Weekly Roundup]]></title>
    <link>https://www.taxscan.in/top-stories/itat-weekly-roundup-1446147</link>
    <pubDate>Sun, 17 May 2026 05:14:30 GMT</pubDate>
  </item>

Weekly Roundup article structure (typical):
  <h3>Case 1: Party A vs. Party B</h3>
  <p>Section 269SS | ITAT Delhi | [date]</p>
  <p>[Ratio / outcome text]</p>
"""

import re
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

try:
    import requests
except ImportError:
    requests = None

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    )
}
_BASE          = "https://www.taxscan.in"
_RSS_GENERAL   = f"{_BASE}/feed/"
_RSS_INCOMETAX = f"{_BASE}/income-tax/feed/"    # ITAT/income-tax specific feed
_DELAY         = 1.2


def _court_type(text: str) -> str:
    t = text.lower()
    if "supreme court" in t or " sc " in t:
        return "SC"
    if "high court" in t or any(c in t for c in [
        "bombay", "delhi hc", "madras", "calcutta", "allahabad",
        "gujarat hc", "karnataka", "punjab and haryana", "kerala",
        "rajasthan", "hyderabad", "patna hc", "gauhati",
    ]):
        return "HC"
    if "itat" in t or "income tax appellate" in t:
        return "ITAT"
    return "OTHER"


def _extract_section(text: str) -> str:
    m = re.search(
        r"[Ss]ection\s+([\w()/]+)|[Ss]\.\s+([\w()/]+)|"
        r"\b(269SS|269T|269ST|271D|271E|68|69A?|69C|40A|14A|153[AC]|"
        r"148A?|147|263|56\(2\)|2\(22\)|50C|54[EF]?|80P|92C|"
        r"271\(1\)\(c\)|270A|44AD|43B|36\(1\)|115BBE|80IB|10AA|"
        r"195|194[CIJC]|192|132|144B|143)\b",
        text,
        re.IGNORECASE
    )
    if m:
        return (m.group(1) or m.group(2) or m.group(3) or "").upper().strip(".")
    return ""


def _parse_year(s: str) -> int:
    m = re.search(r"\b(20\d{2}|19\d{2})\b", s or "")
    return int(m.group()) if m else 0


def _clean(html_text: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html_text)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


# ── Weekly Roundup parser ─────────────────────────────────────────────────────

def _parse_weekly_roundup(url: str, pub_date: str,
                           progress_cb=None) -> list[dict]:
    """
    Fetch and parse one ITAT Weekly Roundup article.
    Taxscan uses PMPro paywall — full content not accessible without subscription.
    We extract what we can from JSON-LD structured data (300-500 chars snippet)
    which contains case titles.
    """
    import json as _json
    if not requests:
        return []
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            return []
        html = r.text
    except Exception as e:
        if progress_cb:
            progress_cb(f"  roundup fetch error: {e}")
        return []

    results = []

    # Extract JSON-LD article body (best available without subscription)
    ld_scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )
    article_body = ""
    for s in ld_scripts:
        try:
            d = _json.loads(s.strip())
            if d.get("articleBody"):
                article_body += " " + d["articleBody"]
        except Exception:
            pass

    if not article_body:
        if progress_cb:
            progress_cb(f"  roundup: no article body (paywall)")
        return []

    # Clean up the text
    article_body = re.sub(r"\s+", " ", article_body).strip()

    # Split into case blocks by pattern "title : parties CITATION"
    # Pattern observed: "Title Text: Party vs Party CITATION :..."
    blocks = re.split(r"(?=\b[A-Z][^a-z]{0,5}[A-Z].*?(?:vs?\.? |ITAT|CITATION))", article_body)

    if progress_cb:
        progress_cb(f"  roundup snippet ({len(article_body)} chars) → {len(blocks)} blocks")

    for block in blocks:
        block = block.strip()
        if len(block) < 30:
            continue

        # Must look like a real case:
        has_vs    = bool(re.search(r"\bvs?\.?\s+[A-Z]", block, re.IGNORECASE))
        has_party = bool(re.search(
            r"\b(?:Ltd|Pvt|Private|Industries|Services|Corporation|"
            r"Enterprises|Associates|Company|Income Tax|Revenue|Assessee)\b",
            block
        ))

        # Exclude boilerplate intro/outro text
        is_intro = any(x in block.lower() for x in [
            "encapsulates", "reported at taxscan", "round-up of",
            "citation :...", "this weekly",
        ])

        if is_intro or not (has_vs or has_party):
            continue

        # Extract parties from "X vs Y" or before "CITATION"
        vs_m = re.search(
            r"([A-Z][A-Za-z .&()]{4,80}?)\s+vs?\.?\s+([A-Z][A-Za-z .&()]{4,80}?)(?:\s+CITATION|\s*$)",
            block, re.IGNORECASE
        )
        if vs_m:
            party1 = vs_m.group(1).strip().rstrip(",- ")
            party2 = vs_m.group(2).strip().rstrip(",- ")
            title = f"{party1} vs. {party2}"
        else:
            # Use heading text as title (before CITATION or newline)
            title = re.split(r"\s+CITATION|\s{2,}", block)[0][:150]

        title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 15:
            continue

        section = _extract_section(block)
        court   = _court_type(block)

        results.append({
            "title":      title[:200],
            "url":        url,
            "date":       pub_date,
            "year":       _parse_year(pub_date),
            "section":    section,
            "court_name": "ITAT",
            "court_type": court or "ITAT",
            "key_ratio":  block[:400],
            "source":     "taxscan_roundup",
            "source_url": url,
        })

    if progress_cb:
        progress_cb(f"  roundup '{url[-40:]}': {len(results)} cases extracted")
    return results


# ── RSS parser ────────────────────────────────────────────────────────────────

def _fetch_article_body(url: str) -> str:
    """
    Fetch full article body from JSON-LD structured data.
    Taxscan embeds articleBody in JSON-LD even for free users.
    Returns the text body (~2000-3000 chars for regular articles).
    """
    import json as _json
    if not requests:
        return ""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return ""
        ld_scripts = re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            r.text, re.DOTALL | re.IGNORECASE
        )
        best = ""
        for s in ld_scripts:
            try:
                d = _json.loads(s.strip())
                body = d.get("articleBody", "")
                if len(body) > len(best):
                    best = body
            except Exception:
                pass
        return re.sub(r"\s+", " ", best).strip()
    except Exception:
        return ""


def _parse_rss(max_roundups: int = 4, progress_cb=None) -> list[dict]:
    """
    Fetch Taxscan income-tax RSS feed (ITAT-specific).
    Fetches full article bodies via JSON-LD for individual case articles.
    Parses ITAT Weekly Roundup for case snippets.
    """
    if not requests:
        return []

    # Use the income-tax specific feed first, fall back to general
    items = []
    for feed_url in [_RSS_INCOMETAX, _RSS_GENERAL]:
        try:
            r = requests.get(feed_url, headers=_HEADERS, timeout=15)
            if r.status_code == 200:
                found = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)
                items.extend(found)
                if progress_cb:
                    progress_cb(f"  taxscan feed {feed_url[-30:]}: {len(found)} items")
        except Exception as e:
            if progress_cb:
                progress_cb(f"  taxscan feed error: {e}")

    # Deduplicate items by link
    seen_links = set()
    unique_items = []
    for item in items:
        link_m = re.search(r"<link>(.*?)</link>", item)
        link = (link_m.group(1) or "").strip() if link_m else ""
        if link and link not in seen_links:
            seen_links.add(link)
            unique_items.append(item)
    items = unique_items

    results = []
    roundup_count = 0

    for item in items:
        title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]>|<title>(.*?)</title>", item)
        link_m  = re.search(r"<link>(.*?)</link>", item)
        date_m  = re.search(r"<pubDate>(.*?)</pubDate>", item)
        desc_m  = re.search(r"<description><!\[CDATA\[(.*?)\]\]>", item, re.DOTALL)

        title = _clean(
            (title_m.group(1) or title_m.group(2) or "") if title_m else ""
        )
        url   = (link_m.group(1) or "").strip() if link_m else ""
        date  = (date_m.group(1) or "").strip() if date_m else ""
        desc  = _clean(desc_m.group(1) or "" if desc_m else "")[:400]

        if not title or not url:
            continue

        # ITAT Weekly Roundup → deep parse (limited due to paywall)
        if "itat weekly roundup" in title.lower() and roundup_count < max_roundups:
            roundup_count += 1
            if progress_cb:
                progress_cb(f"  Parsing roundup: {title[:60]}")
            cases = _parse_weekly_roundup(url, date, progress_cb)
            results.extend(cases)
            time.sleep(_DELAY)
            continue

        # Fetch full article body for individual case articles
        body = ""
        if len(title) > 20:
            body = _fetch_article_body(url)
            time.sleep(0.5)  # rate limit

        full_text = title + " " + desc + " " + body

        results.append({
            "title":      title,
            "url":        url,
            "date":       date,
            "year":       _parse_year(date),
            "section":    _extract_section(full_text),
            "court_name": "",
            "court_type": _court_type(full_text),
            "key_ratio":  (body or desc)[:500],
            "source":     "taxscan",
            "source_url": url,
        })

    if progress_cb:
        progress_cb(f"  taxscan RSS total: {len(results)} items")
    return results


# ── HTML page parser ──────────────────────────────────────────────────────────

def _parse_page(page_num: int, progress_cb=None) -> list[dict]:
    """Scrape taxscan income-tax listing page."""
    if not requests:
        return []
    url = f"{_BASE}/income-tax/page/{page_num}/"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            return []
        html = r.text
    except Exception as e:
        if progress_cb:
            progress_cb(f"  [taxscan page {page_num}] error: {e}")
        return []

    results = []
    seen = set()

    # Links to individual case articles (taxscan.in/top-stories/...)
    links = re.findall(
        r'href=["\'](' + re.escape(_BASE) + r'/top-stories/[^"\']+)["\'][^>]*>'
        r'([^<]{15,200})</a>',
        html
    )
    # Also match relative /top-stories/ links
    rel_links = re.findall(
        r'href=["\'](/top-stories/[^"\']+)["\'][^>]*>([^<]{15,200})</a>',
        html
    )
    for path, title in rel_links:
        links.append((_BASE + path, title))

    for case_url, title_raw in links:
        title = _clean(title_raw).strip()
        if not title or case_url in seen:
            continue
        if len(title) < 15:
            continue
        seen.add(case_url)

        # Date
        idx = html.find(case_url.replace(_BASE, ""))
        near = html[max(0, idx-100):idx+400]
        date_m = re.search(r'datetime=["\']([^"\']+)["\']', near)
        date_str = date_m.group(1) if date_m else ""

        results.append({
            "title":      title,
            "url":        case_url,
            "date":       date_str,
            "year":       _parse_year(date_str),
            "section":    _extract_section(title),
            "court_name": "",
            "court_type": _court_type(title),
            "key_ratio":  "",
            "source":     "taxscan",
            "source_url": case_url,
        })

    if progress_cb:
        progress_cb(f"  [taxscan page {page_num}] {len(results)} cases")
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def scrape(max_pages: int = 2, progress_cb=None) -> list[dict]:
    """
    Scrape Taxscan.in.
    max_pages: how many income-tax pages to scrape in addition to RSS + roundups.
    """
    if progress_cb:
        progress_cb(f"Taxscan.in — RSS (with roundup parsing) + {max_pages} pages")

    all_cases = {}

    # RSS + roundups
    for c in _parse_rss(max_roundups=max_pages, progress_cb=progress_cb):
        key = f"{c['title'][:50]}|{c['url']}"
        all_cases[key] = c

    # HTML pages
    for page in range(1, max_pages + 1):
        for c in _parse_page(page, progress_cb):
            key = f"{c['title'][:50]}|{c['url']}"
            if key not in all_cases:
                all_cases[key] = c
        time.sleep(_DELAY)

    results = list(all_cases.values())
    if progress_cb:
        progress_cb(f"Taxscan total: {len(results)} cases")
    return results


if __name__ == "__main__":
    cases = scrape(max_pages=2, progress_cb=print)
    print(f"\n=== {len(cases)} cases ===")
    for c in cases[:5]:
        print(f"\n  [{c['court_type']}] {c['title'][:70]}")
        print(f"  Section: {c['section']} | Year: {c['year']}")
        print(f"  Ratio: {c['key_ratio'][:120]}")
