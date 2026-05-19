"""
TaxGuru.in — CBDT Circulars + Notifications scraper.

Two separate category feeds:
  - Circulars:     /income-tax/feed/?cat=cbdt-circular       (100 items)
  - Notifications: /income-tax/feed/?cat=cbdt-notification   (100 items)

CBDT circulars/notifications are authoritative for:
  - Tax-free transaction limits (269SS/269T thresholds)
  - Relaxation notifications (COVID, natural disasters)
  - Compliance due dates
  - Penalty waiver notifications (273B reasonable cause)
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
_BASE = "https://taxguru.in"

_FEEDS = {
    "cbdt_circular":      f"{_BASE}/income-tax/feed/?cat=cbdt-circular",
    "cbdt_notification":  f"{_BASE}/income-tax/feed/?cat=cbdt-notification",
}

_CAT_PAGES = {
    "cbdt_circular":     f"{_BASE}/income-tax/page/{{page}}/?cat=cbdt-circular",
    "cbdt_notification": f"{_BASE}/income-tax/page/{{page}}/?cat=cbdt-notification",
}

_DELAY = 1.2


def _extract_section(text: str) -> str:
    text = re.sub(r"&#?\w+;", " ", text)
    m = re.search(
        r"[Ss]ection\s+([\w()/]+)|[Ss]\.\s+([\w()/]+)|"
        r"\b(269SS|269T|269ST|271D|271E|68|69|40A|14A|153[AC]|"
        r"148A?|147|263|56\(2\)|2\(22\)|50C|54|80P|92C|"
        r"271\(1\)\(c\)|270A|44AD|43B|36\(1\)|115BBE|80IB|10AA|"
        r"195|194[CIJC]|192|132|144B|143)\b",
        text, re.IGNORECASE
    )
    if not m:
        return ""
    r_ = (m.group(1) or m.group(2) or m.group(3) or "").upper().strip(".")
    return r_ if r_ not in ("HTML", "HTTP", "THE", "AND") else ""


def _parse_year(s: str) -> int:
    m = re.search(r"\b(20\d{2}|19\d{2})\b", s or "")
    return int(m.group()) if m else 0


def _clean(html_text: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html_text)
    t = re.sub(r"&#\d+;", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _parse_rss(feed_key: str, progress_cb=None) -> list[dict]:
    """Fetch one TaxGuru CBDT RSS feed (100 items)."""
    if not requests:
        return []
    feed_url = _FEEDS[feed_key]
    source_name = feed_key   # "cbdt_circular" or "cbdt_notification"
    try:
        r = requests.get(feed_url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        items = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)
        results = []
        for item in items:
            title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]>", item)
            link_m  = re.search(r"<link>(.*?)</link>", item)
            date_m  = re.search(r"<pubDate>(.*?)</pubDate>", item)
            desc_m  = re.search(r"<description><!\[CDATA\[(.*?)\]\]>", item, re.DOTALL)

            title = _clean((title_m.group(1) or "") if title_m else "")
            title = re.sub(r"&#\d+;", " ", title).strip()
            url   = (link_m.group(1) or "").strip() if link_m else ""
            date  = (date_m.group(1) or "").strip() if date_m else ""
            desc  = _clean(desc_m.group(1) or "" if desc_m else "")[:300]

            if not title or not url:
                continue

            # Detect circular/notification number
            circ_m = re.search(r"(?:Circular|Notification)\s+(?:No\.?\s*)?(\d+/\d{4}|\d+\s+of\s+\d{4})", title, re.IGNORECASE)
            circ_num = circ_m.group(0) if circ_m else ""

            results.append({
                "title":        title,
                "url":          url,
                "date":         date,
                "year":         _parse_year(date),
                "section":      _extract_section(title + " " + desc),
                "court_name":   "CBDT",
                "court_type":   "OTHER",
                "key_ratio":    (circ_num + " — " + desc if circ_num else desc),
                "source":       source_name,
                "source_url":   url,
                "cbdt_number":  circ_num,
            })
        if progress_cb:
            progress_cb(f"  {source_name} RSS: {len(results)} items")
        return results
    except Exception as e:
        if progress_cb:
            progress_cb(f"  {source_name} RSS error: {e}")
        return []


def _parse_page(page_num: int, feed_key: str, progress_cb=None) -> list[dict]:
    """Scrape one HTML listing page for a CBDT category."""
    if not requests:
        return []
    url = _CAT_PAGES[feed_key].format(page=page_num)
    source_name = feed_key
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        html = r.text
    except Exception as e:
        if progress_cb:
            progress_cb(f"  [{source_name} page {page_num}] error: {e}")
        return []

    results = []
    seen = set()
    links = re.findall(
        r'<h[23][^>]*class=["\'][^"\']*entry-title[^"\']*["\'][^>]*>'
        r'\s*<a\s+href=["\'](https?://taxguru\.in/[^"\']+)["\'][^>]*>([^<]+)</a>',
        html
    )
    if not links:
        links = re.findall(
            r'href=["\'](https://taxguru\.in/income-tax/[^"\']+)["\'][^>]*>'
            r'([^<]{10,150})</a>', html
        )

    # Noise tokens that are navigation/UI elements, not case titles
    _NAV_NOISE = {"last", "next", "previous", "first", "»", "«", "›", "‹",
                  "...", "page", "home", "more", "load"}

    for case_url, title_raw in links:
        title = re.sub(r"&#?\w+;", " ", title_raw).strip()
        title = re.sub(r"\s{2,}", " ", title)
        # Skip navigation elements and very short titles
        if not title or len(title) < 10:
            continue
        if title.lower() in _NAV_NOISE or title.lower().startswith("page "):
            continue
        if case_url in seen:
            continue
        seen.add(case_url)

        idx = html.find(case_url)
        near = html[max(0, idx-100):idx+400]
        date_m = re.search(r'datetime=["\'](.*?)["\']', near)

        results.append({
            "title":      title,
            "url":        case_url,
            "date":       date_m.group(1) if date_m else "",
            "year":       _parse_year(date_m.group(1) if date_m else ""),
            "section":    _extract_section(title),
            "court_name": "CBDT",
            "court_type": "OTHER",
            "key_ratio":  "",
            "source":     source_name,
            "source_url": case_url,
        })

    if progress_cb:
        progress_cb(f"  [{source_name} page {page_num}] {len(results)} items")
    return results


def scrape(max_pages: int = 2, progress_cb=None) -> list[dict]:
    """
    Scrape TaxGuru CBDT Circulars + Notifications.
    Returns combined list — both types in a single pass.
    max_pages: number of HTML pages per category (in addition to RSS).
    """
    if progress_cb:
        progress_cb(f"TaxGuru CBDT — Circulars + Notifications ({max_pages} pages each)")

    all_cases = {}

    for key in _FEEDS:
        # RSS first
        for c in _parse_rss(key, progress_cb):
            all_cases[c["url"]] = c
        time.sleep(_DELAY)

        # HTML pages
        for page in range(1, max_pages + 1):
            for c in _parse_page(page, key, progress_cb):
                if c["url"] not in all_cases:
                    all_cases[c["url"]] = c
            time.sleep(_DELAY)

    results = list(all_cases.values())
    if progress_cb:
        progress_cb(f"TaxGuru CBDT total: {len(results)} items (circulars + notifications)")
    return results


if __name__ == "__main__":
    cases = scrape(max_pages=1, progress_cb=print)
    print(f"\n=== {len(cases)} CBDT items ===")
    for c in cases[:5]:
        print(f"  [{c['source']}] §{c['section']} — {c['title'][:70]}")
        print(f"  ratio: {c['key_ratio'][:100]}")
        print(f"  url: {c['url'][:80]}")
