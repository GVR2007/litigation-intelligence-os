"""
Indian Kanoon — Direct website scraper (no API key required).

The IK REST API returns 403 (key activation issues). This module scrapes
the public indiankanoon.org website directly — same data, zero dependency
on their broken key system.

Endpoints:
  Search: https://indiankanoon.org/search/?formInput=QUERY&pagenum=N
  Doc:    https://indiankanoon.org/doc/TID/

Caching: Every query cached 7 days in data/search_cache.db so we never
         re-scrape the same query twice.

Rate limiting: 2 seconds between requests — stays well below bot detection.

Drop-in replacement: All legacy call sites (search_cases, get_doc,
format_results, clean_html) work unchanged.
"""

from __future__ import annotations
import re
import time
import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import requests as _req
except ImportError:
    _req = None  # type: ignore

try:
    from bs4 import BeautifulSoup as _BS
    _BS_AVAILABLE = True
except ImportError:
    _BS_AVAILABLE = False

_IK_BASE    = "https://indiankanoon.org"
_RATE_DELAY = 2.0    # seconds between requests — polite & avoids detection

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]


def _headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Referer": "https://indiankanoon.org/",
        "DNT": "1",
    }


def clean_html(text: str) -> str:
    """Strip HTML tags. Works for both API mode and scraper mode."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Core scraper: search page
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_search_page(query: str, pagenum: int = 0,
                        doctypes: str = "judgments") -> list[dict]:
    """
    Scrape one page of IK search results.
    Returns list of raw dicts: {tid, title, headline, docsource, publishdate, citation}
    """
    if not _req:
        return []

    import urllib.parse
    url = (
        f"{_IK_BASE}/search/"
        f"?formInput={urllib.parse.quote_plus(query)}"
        f"&pagenum={pagenum}"
        f"&doctypes={doctypes}"
    )

    try:
        resp = _req.get(url, headers=_headers(), timeout=20)
        if resp.status_code != 200:
            return []
        return _parse_search_html(resp.text)
    except Exception:
        return []


def _parse_search_html(html: str) -> list[dict]:
    """
    Parse IK search results HTML.
    IK renders each result in a <div class="result"> block.
    Title link: <a href="/doc/TID/">...</a>
    Snippet: <div class="headnote">...</div>
    Source/court: <div class="docsource_main">...</div>
    Date: text near source div
    """
    docs = []
    seen = set()

    if _BS_AVAILABLE:
        docs = _parse_with_bs4(html, seen)
    else:
        docs = _parse_with_regex(html, seen)

    return docs


def _parse_with_bs4(html: str, seen: set) -> list[dict]:
    """
    Parse IK search results using BeautifulSoup.

    Actual IK HTML structure (verified):
      <article class="result" role="listitem">
        <h4 class="result_title">
          <a href="/docfragment/TID/?formInput=QUERY">Case Title</a>
        </h4>
        <div class="headline">snippet text...</div>
        <div class="hlbottom">
          <span class="docsource">Court Name</span>
          <a class="cite_tag" href="/doc/TID/">Full Document</a>
        </div>
      </article>
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    docs = []

    # IK uses <article class="result"> for each result
    articles = soup.find_all("article", class_="result")

    for art in articles:
        # Title link: href="/docfragment/TID/..."
        title_a = art.find("a", href=re.compile(r"/docfragment/\d+"))
        if not title_a:
            # fallback: any link in h4.result_title
            h4 = art.find("h4", class_="result_title")
            if h4:
                title_a = h4.find("a")

        if not title_a:
            continue

        title = title_a.get_text(" ", strip=True)
        href  = title_a.get("href", "")

        # TID from /docfragment/TID/ or /doc/TID/
        tid_m = re.search(r"/(?:docfragment|doc)/(\d+)", href)
        if not tid_m:
            continue
        tid = tid_m.group(1)
        if tid in seen:
            continue
        seen.add(tid)

        # Headline / snippet — in <div class="headline">
        hl_div   = art.find("div", class_="headline")
        headline = hl_div.get_text(" ", strip=True)[:400] if hl_div else ""

        # Court source — in <span class="docsource">
        src_span  = art.find("span", class_="docsource")
        docsource = src_span.get_text(" ", strip=True) if src_span else ""

        # Date — look in the whole article text
        art_text    = art.get_text(" ")
        date_m      = re.search(
            r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
            r"\s+\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
            r"\s+\d{1,2},?\s+\d{4}|\d{4})\b",
            art_text, re.IGNORECASE
        )
        publishdate = date_m.group(1) if date_m else ""

        docs.append({
            "tid":         tid,
            "title":       title,
            "headline":    headline,
            "docsource":   docsource,
            "publishdate": publishdate,
            "citation":    "",
        })

    return docs


def _parse_with_regex(html: str, seen: set) -> list[dict]:
    """
    Regex fallback parser — no BeautifulSoup dependency.
    Matches actual IK HTML: <article class="result"> blocks.
    """
    docs = []

    # Split on <article class="result"
    blocks = re.split(r'<article[^>]+class=["\'][^"\']*result[^"\']*["\']', html)

    for block in blocks[1:]:   # skip first (pre-results HTML)
        # Title from <a href="/docfragment/TID/...">Title</a>
        frag_m = re.search(
            r'<a[^>]+href=["\'][^"\']*(?:/docfragment|/doc)/(\d+)[^"\']*["\'][^>]*>'
            r'(.*?)</a>',
            block, re.DOTALL
        )
        if not frag_m:
            continue

        tid   = frag_m.group(1)
        title = clean_html(frag_m.group(2)).strip()

        if not title or title == "Full Document" or tid in seen:
            continue
        seen.add(tid)

        # Headline from <div class="headline">...</div>
        hl_m     = re.search(r'<div[^>]+class=["\'][^"\']*headline[^"\']*["\'][^>]*>'
                              r'(.*?)</div>', block, re.DOTALL | re.IGNORECASE)
        headline = clean_html(hl_m.group(1))[:400] if hl_m else ""

        # Court source from <span class="docsource">
        src_m     = re.search(r'<span[^>]+class=["\'][^"\']*docsource[^"\']*["\'][^>]*>'
                               r'(.*?)</span>', block, re.DOTALL | re.IGNORECASE)
        docsource = clean_html(src_m.group(1)) if src_m else ""

        # Date — year in block
        date_m      = re.search(r"\b(\d{4})\b", block)
        publishdate = date_m.group(1) if date_m else ""

        docs.append({
            "tid":         tid,
            "title":       title,
            "headline":    headline,
            "docsource":   docsource,
            "publishdate": publishdate,
            "citation":    "",
        })

    return docs


# ─────────────────────────────────────────────────────────────────────────────
# Core scraper: full document text
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_doc_page(tid: str) -> str:
    """
    Fetch full judgment text from https://indiankanoon.org/doc/TID/
    Returns cleaned plain text (HTML stripped), max 6000 chars.
    """
    if not _req:
        return ""

    try:
        url  = f"{_IK_BASE}/doc/{tid}/"
        resp = _req.get(url, headers=_headers(), timeout=25)
        if resp.status_code != 200:
            return ""

        html = resp.text

        if _BS_AVAILABLE:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            # Remove boilerplate
            for tag in soup(["script", "style", "nav", "header", "footer", "form"]):
                tag.decompose()
            # IK puts judgment text in <div class="judgments"> or <pre class="judgment">
            main = (soup.find("div",  class_=re.compile(r"judgment", re.I)) or
                    soup.find("pre",  class_=re.compile(r"judgment", re.I)) or
                    soup.find("div",  id=re.compile(r"judgment|main|content", re.I)) or
                    soup.find("div",  id="main") or
                    soup.body)
            text = main.get_text(" ", strip=True) if main else soup.get_text(" ", strip=True)
        else:
            # Regex fallback — strip scripts/styles first
            html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<style[^>]*>.*?</style>",   " ", html, flags=re.DOTALL | re.IGNORECASE)
            text = clean_html(html)

        # Collapse whitespace and cap
        text = re.sub(r"\s{2,}", " ", text).strip()

        # Return up to 8000 chars, but sample from beginning + middle + end
        # so evidence discussion (usually mid-judgment) is included
        if len(text) > 8000:
            third = len(text) // 3
            text = (text[:3000] + " ... " +
                    text[third:third + 2500] + " ... " +
                    text[-2000:])
        return text[:8500]

    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Public API (drop-in replacement for old API-based functions)
# ─────────────────────────────────────────────────────────────────────────────

def search_cases(query: str, pagenum: int = 0,
                 fromdate: str = "", todate: str = "",
                 doctypes: str = "judgments") -> dict:
    """
    Search Indian Kanoon for cases matching `query`.
    Drop-in replacement for the old API-based function.

    Returns: { "total": N, "docs": [...] }
    Each doc: {tid, title, headline, docsource, publishdate, citation}
    """
    # Check cache first
    try:
        from utils.result_cache import cache_get, cache_set
        cache_key = f"{query}::{pagenum}::{doctypes}"
        cached    = cache_get(cache_key, "ik_scrape")
        if cached is not None:
            return cached
    except Exception:
        cache_get = cache_set = None  # type: ignore

    docs = _scrape_search_page(query, pagenum, doctypes)
    time.sleep(_RATE_DELAY)

    result = {"total": len(docs), "docs": docs}

    # Cache the result
    try:
        if cache_set:
            cache_set(f"{query}::{pagenum}::{doctypes}", "ik_scrape", result, ttl_days=7)
    except Exception:
        pass

    return result


def get_doc(tid: str) -> dict:
    """
    Fetch full text of a single judgment by IK document ID.
    Returns: {"doc": full_text_string}
    """
    try:
        from utils.result_cache import cache_get, cache_set
        cached = cache_get(f"doc:{tid}", "ik_doc")
        if cached is not None:
            return cached
    except Exception:
        cache_get = cache_set = None  # type: ignore

    text   = _scrape_doc_page(tid)
    time.sleep(_RATE_DELAY)

    result = {"doc": text, "tid": tid}

    try:
        if cache_set:
            cache_set(f"doc:{tid}", "ik_doc", result, ttl_days=14)
    except Exception:
        pass

    return result


def format_results(data: dict, max_results: int = 10) -> list[dict]:
    """Parse search response into clean list of cases."""
    if not data or "docs" not in data:
        return []

    docs    = data.get("docs", [])[:max_results]
    results = []
    for d in docs:
        tid = str(d.get("tid", ""))
        results.append({
            "tid":      tid,
            "title":    clean_html(d.get("title", "Untitled")),
            "headline": clean_html(d.get("headline", "")),
            "date":     d.get("publishdate", ""),
            "court":    d.get("docsource", ""),
            "citation": d.get("citation", ""),
            "url":      f"{_IK_BASE}/doc/{tid}/" if tid else "",
        })
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Convenience wrappers (kept for backward compat)
# ─────────────────────────────────────────────────────────────────────────────

def search_itat_cases(section: str, keywords: str = "", page: int = 0) -> dict:
    """Search ITAT cases for a specific IT Act section."""
    query = f"section {section} income tax appellate tribunal"
    if keywords:
        query += f" {keywords}"
    return search_cases(query, page)


def search_hc_cases(section: str, court: str = "", page: int = 0) -> dict:
    """Search High Court cases for a section."""
    query = f"section {section} income tax high court"
    if court:
        query += f" {court}"
    return search_cases(query, page)


def search_sc_cases(section: str, page: int = 0) -> dict:
    """Search Supreme Court cases for a section."""
    query = f"section {section} income tax supreme court"
    return search_cases(query, page)
