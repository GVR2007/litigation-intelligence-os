"""
CAclubindia.com Income Tax scraper.

Structure confirmed:
  Base URL: https://www.caclubindia.com/judiciary/browse.asp?cat_id=3
  Pagination: &offset=N  (10 cases per page, offset goes up to ~282)
  Case URL:  /judiciary/SLUG-ID.asp
  Content:   Full article in <p> tags after <h1>,
             JSON-LD headline + description (meta)

Total: ~2,820+ Income Tax judgments (282 pages × 10 each)

Case structure:
  - Title: summary judgment statement (not always "party vs party")
  - Court: mentioned in first paragraph (Supreme Court/HC/ITAT)
  - Section: from IT Act sections mentioned in title/content
  - Ratio: meta description + first paragraph
  - URL: direct link to case article
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
_BASE    = "https://www.caclubindia.com"
_LIST    = f"{_BASE}/judiciary/browse.asp?cat_id=3"
_DELAY   = 1.0


def _court_type(text: str) -> str:
    t = text.lower()
    if "supreme court" in t:
        return "SC"
    if "high court" in t or any(c in t for c in [
        "bombay hc", "delhi hc", "madras hc", "calcutta hc",
        "allahabad hc", "gujarat hc", "karnataka hc", "punjab hc",
        "kerala hc", "rajasthan hc", "hon'ble high court",
    ]):
        return "HC"
    if "itat" in t or "income tax appellate tribunal" in t or "tribunal" in t:
        return "ITAT"
    return "OTHER"


def _extract_section(text: str) -> str:
    # Clean HTML entities first
    text = re.sub(r"&#?\w+;", " ", text)
    m = re.search(
        r"[Ss]ection\s+([\w()/]+)|[Ss]\.\s+([\w()/]+)|"
        r"\b(269SS|269T|269ST|271D|271E|68|69A?C?|40A|14A|153[AC]|"
        r"148A?|147|263|56\(2\)|2\(22\)|50C|54[EFC]?|80P|92C|"
        r"271\(1\)\(c\)|270A|44AD|43B|36\(1\)|115BBE|80IB|10AA|"
        r"195|194[CIJC]|192|132|144B|143\(3\))\b",
        text,
        re.IGNORECASE
    )
    if not m:
        return ""
    result = (m.group(1) or m.group(2) or m.group(3) or "").upper().strip(".")
    if result in ("HTML", "HTTP", "THE", "AND", "OF"):
        return ""
    return result


def _parse_year(text: str) -> int:
    m = re.search(r"\b(20\d{2}|19\d{2})\b", text or "")
    return int(m.group()) if m else 0


def _clean(html_text: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html_text)
    t = re.sub(r"&#\d+;", " ", t)
    t = re.sub(r"&[a-z]+;", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _fetch_article(url: str) -> dict:
    """
    Fetch a single case article and extract:
    - headline / title
    - meta description (key ratio)
    - court type
    - section
    - full paragraph text
    - date
    """
    if not requests:
        return {}
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return {}
        html = r.text
    except Exception:
        return {}

    import json as _json

    # JSON-LD structured data
    ld_scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )
    headline = ""
    date_str  = ""
    for s in ld_scripts:
        try:
            d = _json.loads(s.strip())
            if d.get("@type") in ("NewsArticle", "Article") and d.get("headline"):
                headline = d.get("headline", "")
                date_str = d.get("datePublished", "")
                break
        except Exception:
            pass

    # Meta description → key ratio
    meta_m = re.search(
        r'<meta\s+name=["\']description["\'][^>]*content=["\']([^"\']{20,400})["\']',
        html, re.IGNORECASE
    )
    meta_desc = _clean(meta_m.group(1)) if meta_m else ""

    # Paragraphs after h1 → full content
    h1_idx = html.find("<h1")
    body_html = html[h1_idx:h1_idx + 15000] if h1_idx > 0 else html[:15000]
    paras = re.findall(r"<p[^>]*>(.{20,}?)</p>", body_html, re.DOTALL)
    body_text = " ".join(_clean(p) for p in paras[:8])[:600]

    # Merge for section and court detection
    full_text = headline + " " + meta_desc + " " + body_text

    return {
        "headline":  headline[:200],
        "meta_desc": meta_desc[:300],
        "body":      body_text,
        "section":   _extract_section(full_text),
        "court":     _court_type(full_text),
        "date":      date_str,
        "year":      _parse_year(date_str),
    }


def _parse_listing_page(offset: int, progress_cb=None) -> list[dict]:
    """
    Scrape one listing page of CAclubindia Income Tax judgments.
    Returns case dicts (lightweight — title + URL, no article fetch).
    """
    if not requests:
        return []
    url = f"{_LIST}&offset={offset}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            if progress_cb:
                progress_cb(f"  [caclubindia offset={offset}] HTTP {r.status_code}")
            return []
        html = r.text
    except Exception as e:
        if progress_cb:
            progress_cb(f"  [caclubindia offset={offset}] error: {e}")
        return []

    results = []
    # Case links: /judiciary/SLUG-ID.asp with title text
    links = re.findall(
        r'href=["\'](/judiciary/([a-z][a-z0-9-]+-\d+\.asp))["\'][^>]*>'
        r'\s*([^<]{10,200})\s*</a>',
        html
    )

    for path, slug, title_raw in links:
        title = re.sub(r"&#\d+;", "", title_raw).strip()
        title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 10:
            continue

        # Quick court/section from title only (no article fetch for listing pass)
        section = _extract_section(title)
        court   = _court_type(title)

        # Date from near the link
        idx = html.find(path)
        near = html[max(0, idx-100):idx+500]
        date_m = re.search(r'(\d{2}[-/]\d{2}[-/]\d{4}|\d{4}-\d{2}-\d{2})', near)
        date_str = date_m.group(1) if date_m else ""

        results.append({
            "title":      title[:200],
            "url":        _BASE + path,
            "date":       date_str,
            "year":       _parse_year(date_str),
            "section":    section,
            "court_name": "",
            "court_type": court,
            "key_ratio":  "",   # filled on deep-fetch
            "source":     "caclubindia",
            "source_url": _BASE + path,
        })

    if progress_cb:
        progress_cb(f"  [caclubindia offset={offset}] {len(results)} cases")
    return results


def _deep_fetch_articles(cases: list[dict], max_articles: int = 20,
                          progress_cb=None) -> list[dict]:
    """
    For the top N cases in the list, fetch full article content
    to get key_ratio, accurate section, court type, and date.
    """
    enriched = []
    for i, case in enumerate(cases):
        if i >= max_articles:
            # Return remaining without enrichment
            enriched.extend(cases[i:])
            break
        detail = _fetch_article(case["url"])
        if detail:
            case = case.copy()
            if detail.get("meta_desc"):
                case["key_ratio"] = detail["meta_desc"]
            if detail.get("body"):
                case["key_ratio"] = (case["key_ratio"] + " " + detail["body"])[:500]
            if detail.get("section") and not case["section"]:
                case["section"] = detail["section"]
            if detail.get("court") and case["court_type"] == "OTHER":
                case["court_type"] = detail["court"]
            if detail.get("year") and not case["year"]:
                case["year"] = detail["year"]
            if detail.get("date") and not case["date"]:
                case["date"] = detail["date"]
            # Use JSON-LD headline if better
            if detail.get("headline") and len(detail["headline"]) > len(case["title"]):
                case["title"] = detail["headline"]
        enriched.append(case)
        time.sleep(0.4)   # rate limit

    return enriched


def scrape(max_pages: int = 5, progress_cb=None,
           deep_fetch: bool = True) -> list[dict]:
    """
    Scrape CAclubindia Income Tax judgments.

    max_pages:   Number of listing pages (10 cases each = 10 × max_pages cases).
    deep_fetch:  Whether to fetch individual article pages for full content.
                 Set False for fast/bulk mode (listing only).

    CAclubindia has ~282 pages = 2,820+ IT cases total.
    """
    if progress_cb:
        progress_cb(f"CAclubindia.com — Income Tax ({max_pages} pages × 10 cases)")

    all_cases = {}

    for page in range(max_pages):
        offset = page  # offset=0,1,2,3,... (the site uses offset as page number)
        cases = _parse_listing_page(offset, progress_cb)
        for c in cases:
            if c["url"] not in all_cases:
                all_cases[c["url"]] = c
        time.sleep(_DELAY)

    raw = list(all_cases.values())

    if deep_fetch and raw:
        if progress_cb:
            progress_cb(f"  Deep-fetching top {min(len(raw), 30)} articles for ratios...")
        raw = _deep_fetch_articles(raw, max_articles=30, progress_cb=progress_cb)

    if progress_cb:
        progress_cb(f"CAclubindia total: {len(raw)} cases")
    return raw


if __name__ == "__main__":
    cases = scrape(max_pages=2, deep_fetch=True, progress_cb=print)
    print(f"\n=== {len(cases)} cases ===")
    for c in cases[:5]:
        print(f"\n  [{c['court_type']}] §{c['section']} — {c['title'][:70]}")
        print(f"  Ratio: {c['key_ratio'][:120]}")
        print(f"  URL: {c['url'][:80]}")
