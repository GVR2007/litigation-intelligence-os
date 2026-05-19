"""
itatonline.org scraper — expert-curated ITAT/HC/SC cases.

Strategy:
  1. RSS feed  → recent 10 cases (https://itatonline.org/archives/feed/)
  2. HTML pages → /archives/page/N/ (10 cases each, ~312 pages total)

HTML structure confirmed:
  <div class="... section-269SS court-itat-delhi ...">
    <h2 class="entry-title post-title">
      <a href="https://itatonline.org/archives/SLUG/" ...>Title (Court)</a>
    </h2>
    <time datetime="2024-01-15T...">...</time>
    <div class="entry-content">
      <strong>S. 269SS: [Full ratio text]</strong>
    </div>
  </div>

Slug encodes: section, key ratio (everything after party names), court
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
_BASE   = "https://itatonline.org"
_RSS    = f"{_BASE}/archives/feed/"
_DELAY  = 1.0   # seconds between page requests


# ── Court normalisation ───────────────────────────────────────────────────────

def _court_type(court_str: str) -> str:
    s = court_str.lower()
    if "supreme" in s or " sc" in s:
        return "SC"
    if "high court" in s or any(c in s for c in [
        "bombay", "delhi", "madras", "calcutta", "allahabad",
        "gujarat", "karnataka", "punjab", "kerala", "rajasthan",
        "hyderabad", "patna", "gauhati", "orissa", "jharkhand",
    ]):
        return "HC"
    if "itat" in s or "appellate tribunal" in s or "tribunal" in s:
        return "ITAT"
    return "OTHER"


def _slug_to_ratio(slug: str, title: str) -> str:
    """
    URL slug contains the full key ratio embedded after party names.
    e.g. 'shiv-bhagwan-gupta-vs-acit-itat-patna-s-271aab-penalty-u-s-271aab-can-only...'
    Strip party part, capitalise, clean up.
    """
    # Remove domain prefix if present
    slug = slug.split("/archives/")[-1].rstrip("/")

    # Find '-s-' or '-section-' to locate the start of the ratio
    ratio_start = re.search(r'-s-\d|(?:section|sec)-\d|\bs\b', slug, re.IGNORECASE)
    if ratio_start:
        ratio_raw = slug[ratio_start.start():]
    else:
        # Try to cut off at 'vs' party names
        vs_idx = slug.find("-vs-")
        if vs_idx >= 0:
            # Find second major keyword after vs
            after_vs = slug[vs_idx+4:]
            court_idx = re.search(r'-(?:itat|high|hc|bombay|delhi|sc|supreme)', after_vs, re.IGNORECASE)
            ratio_raw = after_vs[court_idx.end():] if court_idx else after_vs
        else:
            ratio_raw = slug

    # Convert slug to readable text
    ratio = ratio_raw.replace("-", " ").strip()
    # Capitalise first char of each sentence
    ratio = re.sub(r'(?<=[.!?])\s+([a-z])', lambda m: ' ' + m.group(1).upper(), ratio)
    if ratio:
        ratio = ratio[0].upper() + ratio[1:]
    return ratio[:400]


def _extract_section_from_div_class(cls: str) -> str:
    """Extract section from div class like 'section-269SS section-273B'."""
    sections = re.findall(r'\bsection-([\w()]+)', cls, re.IGNORECASE)
    if sections:
        # Normalise: section-269SS → 269SS
        return sections[0].replace("-", "(").strip(")")  # crude but good enough
    return ""


def _extract_section_from_strong(strong_text: str) -> str:
    """Extract section from '<strong>S. 269SS:</strong>' text."""
    m = re.match(r"S\.\s*([\w\(\)/,]+)", strong_text.strip())
    return m.group(1) if m else ""


def _parse_year(datestr: str) -> int:
    m = re.search(r"\b(20\d{2}|19\d{2})\b", datestr or "")
    return int(m.group()) if m else 0


# ── RSS parser ────────────────────────────────────────────────────────────────

def _parse_rss(progress_cb=None) -> list[dict]:
    """Fetch latest 10 cases from itatonline RSS."""
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
            desc_m  = re.search(r"<description><!\[CDATA\[(.*?)\]\]>", item, re.DOTALL)

            title = (title_m.group(1) or title_m.group(2) or "").strip() if title_m else ""
            url   = (link_m.group(1) or "").strip() if link_m else ""
            date  = (date_m.group(1) or "").strip() if date_m else ""
            desc  = (desc_m.group(1) or "").strip() if desc_m else ""

            # Strip HTML from description
            desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()
            desc_clean = re.sub(r"\s{2,}", " ", desc_clean)[:500]

            # Extract section from title or desc
            sec_m = re.search(r"S\.\s*([\w\(\)/]+)", title + " " + desc_clean)
            section = sec_m.group(1) if sec_m else ""

            # Court type from title: "Shiv Bhagwan Gupta vs. ACIT (ITAT Patna)"
            court_m = re.search(r"\(([^)]+)\)\s*$", title)
            court_name = court_m.group(1) if court_m else ""
            court_type = _court_type(court_name)

            if title and url:
                results.append({
                    "title":       title,
                    "url":         url,
                    "date":        date,
                    "year":        _parse_year(date),
                    "section":     section,
                    "court_name":  court_name,
                    "court_type":  court_type,
                    "key_ratio":   desc_clean,
                    "source":      "itatonline",
                    "source_url":  url,
                })
        if progress_cb:
            progress_cb(f"  itatonline RSS: {len(results)} items")
        return results
    except Exception as e:
        if progress_cb:
            progress_cb(f"  itatonline RSS error: {e}")
        return []


# ── HTML page parser ──────────────────────────────────────────────────────────

def _parse_page(page_num: int, progress_cb=None) -> list[dict]:
    """
    Scrape one paginated archive page.
    Returns list of case dicts.
    """
    if not requests:
        return []
    url = f"{_BASE}/archives/page/{page_num}/"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            if progress_cb:
                progress_cb(f"  [page {page_num}] HTTP {r.status_code}")
            return []
        html = r.text
    except Exception as e:
        if progress_cb:
            progress_cb(f"  [page {page_num}] error: {e}")
        return []

    results = []
    seen = set()

    # Each case has a containing div with class info, then h2.entry-title
    # Strategy: find all h2.entry-title links (case title + URL), then
    # look backwards for the div class (section/court) and forwards for date + strong

    # Find all entry blocks: <h2 class="entry-title post-title"><a href="URL">Title</a></h2>
    case_links = re.findall(
        r'<h2[^>]+class=["\'][^"\']*entry-title[^"\']*["\'][^>]*>'
        r'\s*<a\s+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>',
        html
    )

    if not case_links:
        # Fallback: any itatonline.org/archives/PARTY-vs-PARTY link
        case_links = []
        for m in re.finditer(
            r'href=["\']('
            r'https://itatonline\.org/archives/[a-z0-9]+-vs-[a-z0-9][^"\']*'
            r')["\'][^>]*>([^<]{10,120})</a>',
            html
        ):
            case_links.append((m.group(1), m.group(2)))

    for url_c, title_raw in case_links:
        title = title_raw.strip()
        if not title or url_c in seen:
            continue

        # Skip navigation/category links
        if any(x in url_c for x in ["/court/", "/judges/", "/author/", "/category/", "/tag/", "/page/"]):
            continue

        seen.add(url_c)

        # Court from title parenthesis
        court_m = re.search(r"\(([^)]+)\)\s*$", title)
        court_name = court_m.group(1) if court_m else ""
        court_type = _court_type(court_name)

        # Section from URL slug class or slug itself
        slug = url_c.split("/archives/")[-1].rstrip("/")
        sec_slug = re.search(r"-s-([\d\w()]+)-", slug, re.IGNORECASE)
        section = sec_slug.group(1) if sec_slug else ""

        # If still no section, look for section numbers in slug
        if not section:
            num_m = re.search(r"-(\d{1,3}[a-z]{0,4})-", slug, re.IGNORECASE)
            section = num_m.group(1) if num_m else ""

        # Key ratio from slug
        key_ratio = _slug_to_ratio(url_c, title)

        # Date — search near this URL in HTML
        url_idx = html.find(url_c)
        near = html[max(0, url_idx-50):url_idx+2000]
        date_m = re.search(r'datetime=["\']([^"\']+)["\']', near)
        date_str = date_m.group(1) if date_m else ""

        # Strong tag for better ratio
        strong_m = re.search(r"<strong>(S\.[^<]{20,600})</strong>", near, re.DOTALL)
        if strong_m:
            strong_text = re.sub(r"<[^>]+>", " ", strong_m.group(1)).strip()
            if strong_text:
                # Extract section from strong
                s_m = re.match(r"S\.\s*([\w\(\)/,]+):", strong_text)
                if s_m and not section:
                    section = s_m.group(1)
                key_ratio = strong_text[:400]

        results.append({
            "title":      title,
            "url":        url_c,
            "date":       date_str,
            "year":       _parse_year(date_str),
            "section":    section.upper() if section else "",
            "court_name": court_name,
            "court_type": court_type,
            "key_ratio":  key_ratio,
            "source":     "itatonline",
            "source_url": url_c,
        })

    if progress_cb:
        progress_cb(f"  [itatonline page {page_num}] {len(results)} cases")
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def scrape(max_pages: int = 5, progress_cb=None) -> list[dict]:
    """
    Scrape itatonline.org.
    max_pages: how many archive pages to scrape (10 cases each).
               1 page = 10 cases, 10 pages = ~100 cases, 312 pages = ~3,100 cases.
    Always includes RSS feed (10 recent).
    Returns deduplicated list of case dicts.
    """
    if progress_cb:
        progress_cb(f"itatonline.org — RSS + {max_pages} archive pages")

    all_cases = {}

    # RSS first
    for c in _parse_rss(progress_cb):
        all_cases[c["url"]] = c

    # Archive pages
    for page in range(1, max_pages + 1):
        for c in _parse_page(page, progress_cb):
            if c["url"] not in all_cases:
                all_cases[c["url"]] = c
        time.sleep(_DELAY)

    results = list(all_cases.values())
    if progress_cb:
        progress_cb(f"itatonline total: {len(results)} cases")
    return results


if __name__ == "__main__":
    cases = scrape(max_pages=2, progress_cb=print)
    print(f"\n=== {len(cases)} cases scraped ===")
    for c in cases[:5]:
        print(f"\n  [{c['court_type']}] {c['title'][:60]}")
        print(f"  Section: {c['section']} | Year: {c['year']}")
        print(f"  Ratio: {c['key_ratio'][:120]}")
        print(f"  URL: {c['url'][:80]}")
