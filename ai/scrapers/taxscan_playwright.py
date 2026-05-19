"""
Taxscan scraper — pure requests + HTML parsing.

IMPORTANT: Playwright was removed because sync_playwright() calls
asyncio.create_subprocess_exec internally, which raises NotImplementedError
on Windows when Streamlit's SelectorEventLoop is active.

This module uses requests to fetch Taxscan search and RSS pages directly.
No subprocess, no async loop — fully compatible with Streamlit.
"""

import re
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def scrape_taxscan_full(query: str,
                        max_results: int = 12,
                        sections: list = None,
                        progress_cb=None) -> list[dict]:
    """
    Scrape Taxscan search results using requests (no Playwright, no subprocess).

    Strategy:
      1. Fetch https://taxscan.in/?s=<query> and parse article cards from HTML
      2. Fall back to RSS feeds if HTML parse yields nothing

    Args:
        query       — search query string
        max_results — max results to return
        sections    — IT Act sections for relevance filtering (optional)
        progress_cb — optional progress callback

    Returns list of dicts: title, url, headline, court_type, source
    """
    sections = sections or []

    results = _scrape_search_page(query, sections, max_results, progress_cb)
    if not results:
        results = _scrape_taxscan_rss(query, sections, max_results)

    if progress_cb and results:
        progress_cb(f"  ✅ Taxscan: {len(results)} results")

    return results


def _scrape_search_page(query: str, sections: list,
                         max_results: int, progress_cb) -> list[dict]:
    """Fetch Taxscan search page and parse article listings from HTML."""
    import requests
    from urllib.parse import quote_plus

    url = f"https://taxscan.in/?s={quote_plus(query)}"
    if progress_cb:
        progress_cb(f"  🔍 Taxscan search: {query[:60]}...")

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []

        html = resp.text
        return _parse_articles(html, query, sections, max_results, source="taxscan")

    except Exception:
        return []


def _parse_articles(html: str, query: str, sections: list,
                    max_results: int, source: str) -> list[dict]:
    """Parse article cards from Taxscan HTML using regex (no lxml/BS4 required)."""
    results = []
    seen_urls: set[str] = set()

    # Match <article ...>...</article> blocks
    article_blocks = re.findall(
        r"<article[^>]*>(.*?)</article>",
        html, re.DOTALL | re.IGNORECASE
    )

    # Fallback: match h2/h3 title+link pairs
    if not article_blocks:
        article_blocks = re.findall(
            r"<h[23][^>]*class=\"[^\"]*entry-title[^\"]*\"[^>]*>(.*?)</h[23]>",
            html, re.DOTALL | re.IGNORECASE
        )

    kw_set = {s.lower() for s in sections}

    for block in article_blocks:
        if len(results) >= max_results:
            break

        # Extract URL + title from first <a> tag with href
        link_m = re.search(
            r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            block, re.DOTALL | re.IGNORECASE
        )
        if not link_m:
            continue

        url   = link_m.group(1).strip()
        title = _clean(link_m.group(2))

        if not title or len(title) < 10 or url in seen_urls:
            continue

        # Only include taxscan.in URLs
        if "taxscan.in" not in url and not url.startswith("/"):
            continue

        # Extract snippet from paragraph / excerpt
        snippet_m = re.search(
            r'class="[^"]*(?:entry-summary|post-excerpt|entry-content)[^"]*"[^>]*>(.*?)</(?:div|p)>',
            block, re.DOTALL | re.IGNORECASE
        )
        snippet = _clean(snippet_m.group(1))[:300] if snippet_m else ""

        # Date extraction
        date_m = re.search(r'datetime="([^"]+)"', block)
        date   = date_m.group(1) if date_m else ""

        # Relevance filter
        if kw_set:
            combined = (title + " " + snippet).lower()
            if not any(k in combined for k in kw_set):
                continue

        seen_urls.add(url)
        results.append({
            "title":      title[:120],
            "url":        url,
            "court_type": _court_type(title),
            "court":      "Taxscan.in",
            "year":       _year(date),
            "date":       date,
            "headline":   snippet,
            "source":     source,
            "section":    _extract_section(title + " " + snippet),
            "query":      query[:60],
        })

    return results


def _scrape_taxscan_rss(query: str, sections: list,
                         max_results: int) -> list[dict]:
    """RSS feed fallback — no JS required."""
    import requests

    kw_set = {s.lower() for s in sections} | {
        w.lower() for w in query.split() if len(w) > 3
    }
    results = []
    seen: set[str] = set()

    feeds = [
        "https://www.taxscan.in/income-tax/feed/",
        "https://www.taxscan.in/itat/feed/",
        "https://www.taxscan.in/feed/",
    ]

    for feed_url in feeds:
        if len(results) >= max_results:
            break
        try:
            r = requests.get(feed_url, headers=_HEADERS, timeout=15)
            if r.status_code != 200:
                continue

            for item in re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL):
                title_m = re.search(
                    r"<title><!\[CDATA\[(.*?)\]\]>|<title>(.*?)</title>", item
                )
                link_m = re.search(r"<link>(.*?)</link>", item)
                desc_m = re.search(
                    r"<description><!\[CDATA\[(.*?)\]\]>", item, re.DOTALL
                )
                date_m = re.search(r"<pubDate>(.*?)</pubDate>", item)

                title = _clean(
                    (title_m.group(1) or title_m.group(2) or "") if title_m else ""
                )
                url   = (link_m.group(1) or "").strip() if link_m else ""
                desc  = _clean(desc_m.group(1) or "" if desc_m else "")[:300]
                date  = (date_m.group(1) or "").strip() if date_m else ""

                if not title or not url or url in seen:
                    continue

                combined = (title + " " + desc).lower()
                if kw_set and not any(k in combined for k in kw_set):
                    continue

                seen.add(url)
                results.append({
                    "title":      title[:120],
                    "url":        url,
                    "court_type": _court_type(title),
                    "court":      "Taxscan.in",
                    "year":       _year(date),
                    "date":       date,
                    "headline":   desc,
                    "source":     "taxscan",
                    "section":    _extract_section(title + " " + desc),
                    "query":      query[:60],
                })

                if len(results) >= max_results:
                    break

        except Exception:
            continue

    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html or "")
    t = re.sub(r"&[a-z#0-9]+;", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _year(s: str) -> int:
    m = re.search(r"\b(19|20)\d{2}\b", s or "")
    return int(m.group()) if m else 0


def _court_type(title: str) -> str:
    t = title.lower()
    if "supreme court" in t or " sc " in t:
        return "SC"
    if "high court" in t or any(
        x in t for x in ["bombay", "delhi", "madras", "calcutta",
                          "gujarat", "karnataka", "allahabad"]
    ):
        return "HC"
    return "ITAT"


def _extract_section(text: str) -> str:
    m = re.search(
        r"\b(269SS|269T|269ST|271D|271E|273B|68|69[AC]?|40A|14A|"
        r"153[AC]|148[A]?|147|263|56\(2\)|270A|271\(1\)\(c\))\b",
        text, re.IGNORECASE,
    )
    return m.group().upper() if m else ""


# ── Drop-in for live_search.py ────────────────────────────────────────────────

def search_taxscan_playwright(queries: list, sections: list,
                               progress_cb=None) -> list[dict]:
    """
    Drop-in replacement for search_taxscan() in live_search.py.
    Name kept for import compatibility; no Playwright used.
    """
    if not queries and not sections:
        return []

    search_terms = (queries[:2] if queries else []) + [
        f"section {s}" for s in sections[:2]
    ]
    all_results = []
    seen_urls: set[str] = set()

    for term in search_terms[:3]:
        for r in scrape_taxscan_full(
            term,
            max_results=8,
            sections=sections,
            progress_cb=progress_cb,
        ):
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)
        time.sleep(0.4)

    return all_results
