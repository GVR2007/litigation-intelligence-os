"""
TaxGuru.in scraper — 6,700+ pages of ITAT/HC/CBDT judgments.

Strategy (dual-mode):
  1. RSS feed  → https://taxguru.in/feed/ (100 items, filter by category)
  2. HTML pages → /income-tax/page/N/?cat=itat-judgments  (60 articles/page)

Category slugs confirmed:
  itat-judgments      : ITAT orders
  high-court-judgments: HC orders
  cbdt-circular       : CBDT circulars/notifications (bonus!)

HTML structure confirmed (page/1/?cat=itat-judgments):
  <h3 class="entry-title ...">
    <a href="https://taxguru.in/income-tax/SLUG.html">Title</a>
  </h3>

RSS structure:
  <category><![CDATA[ITAT Judgments]]></category>
  <title><![CDATA[ITAT ... section 269SS]]></title>
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
_BASE  = "https://taxguru.in"
_RSS   = f"{_BASE}/feed/"
_DELAY = 1.2

# Category → URL query param
_CATEGORIES = {
    "itat":        "?cat=itat-judgments",
    "high_court":  "?cat=high-court-judgments",
    "cbdt":        "?cat=cbdt-circular",
}

# RSS filter categories (in lowercase)
_RSS_LEGAL_CATS = {
    "itat judgments", "high court judgments", "supreme court judgments",
    "cbdt circular", "cbdt notification", "income tax",
    "section 263", "section 147", "section 148", "section 68",
    "section 269ss", "section 269t", "section 40a",
}


def _court_type(cats: list, title: str) -> str:
    cats_low = [c.lower() for c in cats]
    title_low = title.lower()
    if "supreme court" in cats_low or "supreme court" in title_low:
        return "SC"
    if "high court" in cats_low or any(
        hc in title_low for hc in ["high court", "hc:", " hc "]
    ):
        return "HC"
    if "itat" in cats_low or "itat" in title_low:
        return "ITAT"
    return "OTHER"


def _extract_section(title: str, url: str) -> str:
    """Extract IT Act section from title or URL."""
    # Clean HTML entities first
    title = re.sub(r"&#?\w+;", " ", title)
    # Title: "ITAT: Section 269SS ..." or "S. 269SS..."
    m = re.search(
        r"[Ss]ection\s+([\w()/]+)|[Ss]\.\s*([\w()/]+)|"
        r"\b(269SS|269T|269ST|271D|271E|68|69|40A|14A|153A|148|147|263|"
        r"56\(2\)|2\(22\)|50C|54[EFC]?|80P|92C|271\(1\)\(c\)|270A|44AD|43B|"
        r"36\(1\)|115BBE|80IB|10AA|195|194[CIJC]|192|132|144B|143)\b",
        title + " " + url,
        re.IGNORECASE
    )
    if not m:
        return ""
    result = (m.group(1) or m.group(2) or m.group(3) or "").upper().strip(".")
    # Sanity check: reject clearly invalid section numbers
    if result.upper() in ("HTML", "HTTP", "HTTPS", "THE", "AND", "OF", "IN", "TO"):
        return ""
    return result


def _parse_year(s: str) -> int:
    m = re.search(r"\b(20\d{2}|19\d{2})\b", s or "")
    return int(m.group()) if m else 0


def _clean(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).strip()


# ── RSS ───────────────────────────────────────────────────────────────────────

def _parse_rss(progress_cb=None) -> list[dict]:
    if not requests:
        return []
    try:
        r = requests.get(_RSS, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        items = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)
        results = []
        for item in items:
            title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]>|<title>(.*?)</title>", item)
            link_m  = re.search(r"<link>(.*?)</link>", item)
            date_m  = re.search(r"<pubDate>(.*?)</pubDate>", item)
            cats    = re.findall(r"<category><!\[CDATA\[(.*?)\]\]></category>", item)
            desc_m  = re.search(r"<description><!\[CDATA\[(.*?)\]\]>", item, re.DOTALL)

            title = _clean((title_m.group(1) or title_m.group(2) or "") if title_m else "")
            title = re.sub(r"&#\d+;", " ", title).strip()
            url   = (link_m.group(1) or "").strip() if link_m else ""
            date  = (date_m.group(1) or "").strip() if date_m else ""
            desc  = _clean(desc_m.group(1) or "" if desc_m else "")[:300]

            # Filter: only legal / judgment content
            cats_low = {c.lower() for c in cats}
            is_legal = bool(cats_low & _RSS_LEGAL_CATS) or any(
                kw in title.lower() for kw in ["itat", "high court", "section ", "s.", "cbdt"]
            )
            if not is_legal:
                continue

            if title and url:
                results.append({
                    "title":      title,
                    "url":        url,
                    "date":       date,
                    "year":       _parse_year(date),
                    "section":    _extract_section(title, url),
                    "court_name": " / ".join(cats[:2]),
                    "court_type": _court_type(cats, title),
                    "key_ratio":  desc,
                    "source":     "taxguru",
                    "source_url": url,
                    "categories": cats,
                })
        if progress_cb:
            progress_cb(f"  taxguru RSS: {len(results)} legal items")
        return results
    except Exception as e:
        if progress_cb:
            progress_cb(f"  taxguru RSS error: {e}")
        return []


# ── HTML page parser ──────────────────────────────────────────────────────────

def _parse_category_page(page_num: int, cat_param: str,
                          progress_cb=None) -> list[dict]:
    if not requests:
        return []
    url = f"{_BASE}/income-tax/page/{page_num}/{cat_param}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            return []
        html = r.text
    except Exception as e:
        if progress_cb:
            progress_cb(f"  [taxguru page {page_num}] error: {e}")
        return []

    results = []
    seen = set()

    # Match entry-title h2/h3 links
    # <h3 class="entry-title ..."><a href="URL">Title</a></h3>
    links = re.findall(
        r'<h[23][^>]*class=["\'][^"\']*entry-title[^"\']*["\'][^>]*>'
        r'\s*<a\s+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>',
        html
    )
    if not links:
        # Generic h2/h3 link fallback
        links = re.findall(
            r'<h[23][^>]*>\s*<a\s+href=["\']('
            r'https://taxguru\.in/income-tax/[^"\']+)["\'][^>]*>([^<]{10,150})</a>',
            html
        )

    for case_url, title_raw in links:
        title = re.sub(r"&#\d+;", " ", title_raw).strip()
        if not title or case_url in seen:
            continue
        seen.add(case_url)

        # Court from title / URL
        court_type = _court_type([], title)
        if "itat" in cat_param:
            court_type = "ITAT"
        elif "high" in cat_param:
            court_type = "HC"

        # Date near this link
        idx = html.find(case_url)
        near = html[max(0, idx-100):idx+500]
        date_m = re.search(r'datetime=["\']([^"\']+)["\']', near)
        date_str = date_m.group(1) if date_m else ""

        results.append({
            "title":      title,
            "url":        case_url,
            "date":       date_str,
            "year":       _parse_year(date_str),
            "section":    _extract_section(title, case_url),
            "court_name": "ITAT" if "itat" in cat_param else "High Court",
            "court_type": court_type,
            "key_ratio":  "",   # full content would need separate request
            "source":     "taxguru",
            "source_url": case_url,
        })

    if progress_cb:
        progress_cb(f"  [taxguru page {page_num} {cat_param}] {len(results)} cases")
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def scrape(max_pages: int = 3, progress_cb=None) -> list[dict]:
    """
    Scrape TaxGuru.in for ITAT + HC judgments.
    max_pages per category (ITAT + HC × max_pages pages each).
    Returns deduplicated list of case dicts.
    """
    if progress_cb:
        progress_cb(f"TaxGuru.in — RSS + ITAT pages 1-{max_pages} + HC pages 1-{max_pages}")

    all_cases = {}

    # RSS
    for c in _parse_rss(progress_cb):
        all_cases[c["url"]] = c

    # ITAT category pages
    for page in range(1, max_pages + 1):
        for c in _parse_category_page(page, _CATEGORIES["itat"], progress_cb):
            if c["url"] not in all_cases:
                all_cases[c["url"]] = c
        time.sleep(_DELAY)

    # HC category pages
    for page in range(1, max_pages + 1):
        for c in _parse_category_page(page, _CATEGORIES["high_court"], progress_cb):
            if c["url"] not in all_cases:
                all_cases[c["url"]] = c
        time.sleep(_DELAY)

    results = list(all_cases.values())
    if progress_cb:
        progress_cb(f"TaxGuru total: {len(results)} cases")
    return results


def scrape_itat_only(max_pages: int = 5, progress_cb=None) -> list[dict]:
    """Scrape TaxGuru ITAT judgments only (faster, higher volume)."""
    if progress_cb:
        progress_cb(f"TaxGuru ITAT — RSS + {max_pages} HTML pages")
    all_cases = {}
    for c in _parse_rss(progress_cb):
        if c.get("court_type") == "ITAT" or "itat" in " ".join(c.get("categories", [])).lower():
            c["source"] = "taxguru_itat"
            all_cases[c["url"]] = c
    for page in range(1, max_pages + 1):
        for c in _parse_category_page(page, _CATEGORIES["itat"], progress_cb):
            if c["url"] not in all_cases:
                c["source"] = "taxguru_itat"
                all_cases[c["url"]] = c
        time.sleep(_DELAY)
    return list(all_cases.values())


def scrape_hc_only(max_pages: int = 5, progress_cb=None) -> list[dict]:
    """Scrape TaxGuru High Court judgments only."""
    if progress_cb:
        progress_cb(f"TaxGuru HC — RSS + {max_pages} HTML pages")
    all_cases = {}
    for c in _parse_rss(progress_cb):
        if c.get("court_type") == "HC" or "high court" in " ".join(c.get("categories", [])).lower():
            c["source"] = "taxguru_hc"
            all_cases[c["url"]] = c
    for page in range(1, max_pages + 1):
        for c in _parse_category_page(page, _CATEGORIES["high_court"], progress_cb):
            if c["url"] not in all_cases:
                c["source"] = "taxguru_hc"
                all_cases[c["url"]] = c
        time.sleep(_DELAY)
    return list(all_cases.values())


if __name__ == "__main__":
    cases = scrape(max_pages=2, progress_cb=print)
    print(f"\n=== {len(cases)} cases ===")
    for c in cases[:5]:
        print(f"\n  [{c['court_type']}] {c['title'][:70]}")
        print(f"  Section: {c['section']} | Year: {c['year']}")
        print(f"  URL: {c['url'][:80]}")
