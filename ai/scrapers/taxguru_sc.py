"""
TaxGuru.in — Supreme Court tax judgments scraper.

TaxGuru has a dedicated category for Supreme Court judgments with:
  - RSS feed: https://taxguru.in/income-tax/feed/?cat=supreme-court-judgments
    (100 items per fetch, WordPress RSS)
  - HTML pages: /income-tax/page/N/?cat=supreme-court-judgments

SC judgments are the highest-authority citations — most useful for
arguing against Revenue in ITAT/HC proceedings.
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
_BASE     = "https://taxguru.in"
_RSS      = f"{_BASE}/income-tax/feed/?cat=supreme-court-judgments"
_CAT_PAGE = f"{_BASE}/income-tax/page/{{page}}/?cat=supreme-court-judgments"
_DELAY    = 1.2


def _extract_section(text: str) -> str:
    text = re.sub(r"&#?\w+;", " ", text)
    m = re.search(
        r"[Ss]ection\s+([\w()/]+)|[Ss]\.\s+([\w()/]+)|"
        r"\b(269SS|269T|269ST|271D|271E|68|69A?C?|40A|14A|153[AC]|"
        r"148A?|147|263|56\(2\)|2\(22\)|50C|54[EFC]?|80P|92C|"
        r"271\(1\)\(c\)|270A|44AD|43B|36\(1\)|115BBE|80IB|10AA|"
        r"195|194[CIJC]|192|132|144B|143\(3\))\b",
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


def _parse_rss(progress_cb=None) -> list[dict]:
    """Fetch TaxGuru Supreme Court RSS (100 items)."""
    if not requests:
        return []
    try:
        r = requests.get(_RSS, headers=_HEADERS, timeout=15)
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

            results.append({
                "title":      title,
                "url":        url,
                "date":       date,
                "year":       _parse_year(date),
                "section":    _extract_section(title + " " + desc),
                "court_name": "Supreme Court of India",
                "court_type": "SC",
                "key_ratio":  desc,
                "source":     "taxguru_sc",
                "source_url": url,
            })
        if progress_cb:
            progress_cb(f"  taxguru_sc RSS: {len(results)} SC judgments")
        return results
    except Exception as e:
        if progress_cb:
            progress_cb(f"  taxguru_sc RSS error: {e}")
        return []


def _parse_page(page_num: int, progress_cb=None) -> list[dict]:
    """Scrape one page of Supreme Court judgments."""
    if not requests:
        return []
    url = _CAT_PAGE.format(page=page_num)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        html = r.text
    except Exception as e:
        if progress_cb:
            progress_cb(f"  [taxguru_sc page {page_num}] error: {e}")
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
            r'([^<]{15,150})</a>', html
        )

    for case_url, title_raw in links:
        title = re.sub(r"&#\d+;", " ", title_raw).strip()
        if not title or case_url in seen:
            continue
        seen.add(case_url)

        idx = html.find(case_url)
        near = html[max(0, idx-100):idx+400]
        date_m = re.search(r'datetime=["\'](.*?)["\']', near)
        date_str = date_m.group(1) if date_m else ""

        results.append({
            "title":      title,
            "url":        case_url,
            "date":       date_str,
            "year":       _parse_year(date_str),
            "section":    _extract_section(title),
            "court_name": "Supreme Court of India",
            "court_type": "SC",
            "key_ratio":  "",
            "source":     "taxguru_sc",
            "source_url": case_url,
        })

    if progress_cb:
        progress_cb(f"  [taxguru_sc page {page_num}] {len(results)} cases")
    return results


def scrape(max_pages: int = 3, progress_cb=None) -> list[dict]:
    """
    Scrape TaxGuru Supreme Court income tax judgments.
    Returns list of case dicts (court_type always 'SC').
    """
    if progress_cb:
        progress_cb(f"TaxGuru SC — RSS + {max_pages} HTML pages")

    all_cases = {}

    for c in _parse_rss(progress_cb):
        all_cases[c["url"]] = c

    for page in range(1, max_pages + 1):
        for c in _parse_page(page, progress_cb):
            if c["url"] not in all_cases:
                all_cases[c["url"]] = c
        time.sleep(_DELAY)

    results = list(all_cases.values())
    if progress_cb:
        progress_cb(f"TaxGuru SC total: {len(results)} Supreme Court cases")
    return results


if __name__ == "__main__":
    cases = scrape(max_pages=1, progress_cb=print)
    print(f"\n=== {len(cases)} SC cases ===")
    for c in cases[:5]:
        print(f"  §{c['section']} — {c['title'][:70]}")
        print(f"  {c['url'][:80]}")
