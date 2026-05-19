"""
Live On-Demand Case Search Engine.

When a PDF is uploaded, this module searches all sources RIGHT NOW
using the case's sections + AI-generated keywords as the query.

NO pre-harvesting needed. Everything is fetched fresh for each case.

Sources:
  ① Indian Kanoon API      — /search/?formInput=QUERY      (live, ranked)
  ② TaxGuru RSS search     — /income-tax/feed/?s=QUERY     (50 items)
  ③ itatonline search      — /?s=QUERY                     (~5-10 items, rich ratios)
  ④ CAclubindia search     — /judiciary/?q=QUERY&cat_id=3  (10 per page)
  ⑤ TaxGuru CBDT RSS       — /income-tax/feed/?cat=cbdt-circular&s=QUERY
  ⑥ Taxscan RSS + filter   — /income-tax/feed/ filtered by keywords

Returns:
  {
    "sc":    [case_dict, ...],
    "hc":    [case_dict, ...],
    "itat":  [case_dict, ...],
    "cbdt":  [case_dict, ...],
    "other": [case_dict, ...],
  }

Each case_dict:
  title, url, court_type, court, year, headline, source, section, query
"""

import re
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import requests
except ImportError:
    requests = None

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.71 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# Rotate through agents to avoid bot detection
_agent_idx = 0


def _get_headers() -> dict:
    """Return headers with a rotated User-Agent."""
    global _agent_idx
    import random
    ua = random.choice(_USER_AGENTS)
    _agent_idx = (_agent_idx + 1) % len(_USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }


# Keep old _HEADERS for compatibility (used in a few places)
_HEADERS = {"User-Agent": _USER_AGENTS[0]}
_DELAY = 0.8   # seconds between requests


def _get_with_retry(url: str, max_tries: int = 3, timeout: int = 15):
    """
    GET with automatic retry + exponential backoff + UA rotation.
    Returns requests.Response or None on failure.
    """
    if not requests:
        return None
    for attempt in range(max_tries):
        try:
            r = requests.get(url, headers=_get_headers(), timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 429):
                # Rate-limited: wait longer
                wait = 2 ** (attempt + 1)   # 2s, 4s, 8s
                time.sleep(wait)
                continue
            # Other error codes: try once more
            time.sleep(1)
        except requests.exceptions.Timeout:
            time.sleep(2 ** attempt)
        except requests.exceptions.ConnectionError:
            time.sleep(1)
        except Exception:
            break
    return None


# ── shared helpers ─────────────────────────────────────────────────────────────

def _clean(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html or "")
    t = re.sub(r"&[a-z#0-9]+;", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _year(s: str) -> int:
    m = re.search(r"\b(19|20)\d{2}\b", s or "")
    return int(m.group()) if m else 0


def _court_type(docsource: str, title: str = "") -> str:
    s = (docsource + " " + title).lower()
    if "supreme court" in s or " sc " in s:
        return "SC"
    if ("high court" in s or any(hc in s for hc in [
        "bombay", "delhi", "madras", "calcutta", "allahabad",
        "gujarat", "karnataka", "punjab", "kerala", "rajasthan",
        "andhra", "telangana", "patna", "orissa", "madhya"
    ])):
        return "HC"
    if "itat" in s or "appellate tribunal" in s or "income tax appellate" in s:
        return "ITAT"
    if "cbdt" in s or "circular" in s or "notification" in s:
        return "CBDT"
    return "ITAT"   # default for income-tax content


def _extract_section(text: str) -> str:
    text = re.sub(r"&#?\w+;", " ", text)
    m = re.search(
        r"\b(269SS|269T|269ST|271D|271E|273B|68|69[AC]?|40A|14A|"
        r"153[AC]|148[A]?|147|263|56\(2\)|2\(22\)|50C|54[EFC]?|80P|92C|"
        r"271\(1\)\(c\)|270A|44AD|43B|36\(1\)|115BBE|80IB|10AA|"
        r"195|194[CIJCH]|192|132|144B|143)\b",
        text, re.IGNORECASE
    )
    return m.group().upper() if m else ""


def _make_entry(title: str, url: str, court_type: str, court: str,
                date: str, headline: str, source: str,
                query: str = "", section: str = "") -> dict:
    return {
        "title":      title[:120],
        "url":        url,
        "court_type": court_type,
        "court":      court[:80],
        "year":       _year(date),
        "date":       date,
        "headline":   headline[:300],
        "source":     source,
        "section":    section or _extract_section(title),
        "query":      query[:60],
    }


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE ① — Indian Kanoon API (live, ranked)
# ─────────────────────────────────────────────────────────────────────────────

def _build_ik_queries(ai_queries: list, sections: list) -> list:
    """
    Convert long AI-generated queries → short IK-compatible keyword phrases.

    IK is keyword search, NOT semantic search.
    Long sentences like "cash loan family member genuine 269SS penalty deleted ITAT
    273B reasonable cause" return 0 results because IK requires ALL words present.

    Strategy:
      1. Section numbers alone         → highest precision  e.g. "269SS"
      2. Section + legal outcome       → e.g. "269SS penalty deleted"
      3. Section + defence keyword     → e.g. "269SS reasonable cause"
      4. 2-3 meaningful words from AI  → e.g. "cash loan family"
    """
    ik = []

    # 1. Bare section numbers — IK indexes these directly
    for sec in sections[:5]:
        ik.append(sec)

    # 2. Section + common outcome / defence combos
    outcomes  = ["penalty deleted", "appeal allowed", "addition deleted",
                 "penalty cancelled", "penalty set aside"]
    defences  = ["reasonable cause", "genuine transaction", "bona fide"]
    for sec in sections[:3]:
        ik.append(f"{sec} {outcomes[0]}")          # e.g. "269SS penalty deleted"
        ik.append(f"{sec} {defences[0]}")          # e.g. "269SS reasonable cause"

    # 3. Short keyword phrases from AI queries (strip stop words, take 2-3 words)
    stop = {
        "the","and","or","of","in","to","for","a","an","is","are","was","were",
        "income","tax","itat","section","under","this","with","that","from","by",
        "on","at","it","its","not","but","have","has","been","their","they",
        "which","when","where","who","what","how","penalty","deleted","allowed",
    }
    for q in ai_queries[:5]:
        words = [w for w in re.findall(r"\b[a-zA-Z]{4,}\b", q)
                 if w.lower() not in stop]
        if len(words) >= 2:
            ik.append(" ".join(words[:3]))   # max 3 words — IK handles this well

    # Deduplicate preserving order, cap at 12 queries
    seen_q: set = set()
    result = []
    for q in ik:
        if q not in seen_q:
            seen_q.add(q)
            result.append(q)
    return result[:12]


def search_indian_kanoon(queries: list, sections: list,
                          progress_cb=None) -> list:
    """
    Live IK search — uses direct website scraping (no API key required).
    Replaced broken REST API with direct indiankanoon.org scraper.
    Returns flat list of case dicts. Caller buckets by court_type.
    """
    try:
        from ai.indian_kanoon import search_cases, clean_html
    except Exception:
        return []

    # Convert AI queries → short IK-compatible phrases + CBDT section queries
    ik_queries  = _build_ik_queries(queries, sections)
    cbdt_qs     = [f"CBDT circular {s}" for s in sections[:2]]
    all_queries = ik_queries + cbdt_qs

    if progress_cb:
        progress_cb(f"  📐 IK queries: {len(all_queries)} phrases → scraping indiankanoon.org directly...")

    seen  = set()
    items = []

    for q in all_queries[:10]:   # cap at 10 to respect rate limit
        if progress_cb:
            progress_cb(f"  🔍 IK: {q[:65]}...")
        try:
            raw  = search_cases(q)          # now uses scraper, not API
            docs = raw.get("docs", [])
            if not docs and progress_cb:
                progress_cb(f"    ↳ 0 results for '{q[:50]}'")
                continue

            for doc in docs[:8]:
                tid = str(doc.get("tid", ""))
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                title    = clean_html(doc.get("title", ""))
                src      = doc.get("docsource", "")
                date     = doc.get("publishdate", "")
                headline = clean_html(doc.get("headline", ""))
                ct       = _court_type(src, title)
                url      = f"https://indiankanoon.org/doc/{tid}/"
                items.append(_make_entry(title, url, ct, src, date,
                                         headline, "indian_kanoon", q))
            # Rate limit respected inside search_cases() already
        except Exception as e:
            if progress_cb:
                progress_cb(f"  ⚠️ IK error: {e}")

    if progress_cb:
        progress_cb(f"  ✅ IK direct scrape: {len(items)} results")
    return items


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE ② — TaxGuru RSS search (/income-tax/feed/?s=QUERY)
# ─────────────────────────────────────────────────────────────────────────────

def search_taxguru(queries: list, sections: list,
                   progress_cb=None) -> list:
    """
    Search TaxGuru via its RSS feed.
    Strategy: try /income-tax/feed/?s=QUERY first; if it times out or
    returns nothing, fall back to category RSS feeds and filter by keyword.
    """
    if not requests:
        return []

    seen  = set()
    items = []
    rss_queries = _build_rss_queries(queries, sections)

    # ── Try 1: RSS search endpoint ─────────────────────────────────────────
    search_success = False
    for q in rss_queries[:2]:
        rss_url = f"https://taxguru.in/income-tax/feed/?s={_urlencode(q)}"
        if progress_cb:
            progress_cb(f"  📰 TaxGuru RSS search: {q[:45]}...")
        r = _get_with_retry(rss_url, max_tries=3, timeout=12)
        if r and "<item>" in r.text:
            search_success = True
            _parse_taxguru_rss(r.text, seen, items, q)
        time.sleep(_DELAY)

    # ── Try 2: Category RSS feeds (fallback) — filter by keywords ──────────
    if not search_success or len(items) < 5:
        kw_set = {k.lower() for k in sections + rss_queries}
        fallback_feeds = [
            ("itat-judgments",          "?cat=itat-judgments"),
            ("high-court-judgments",    "?cat=high-court-judgments"),
            ("supreme-court-judgments", "?cat=supreme-court-judgments"),
        ]
        for feed_name, feed_param in fallback_feeds:
            url = f"https://taxguru.in/income-tax/feed/{feed_param}"
            r = _get_with_retry(url, max_tries=2, timeout=15)
            if r and "<item>" in r.text:
                count_before = len(items)
                _parse_taxguru_rss(r.text, seen, items, "",
                                   filter_kw=kw_set)
                if progress_cb and len(items) > count_before:
                    progress_cb(f"  📰 TaxGuru {feed_name}: "
                                f"+{len(items)-count_before} relevant")
            time.sleep(_DELAY)

    if progress_cb:
        progress_cb(f"  ✅ TaxGuru: {len(items)} results")
    return items


def _parse_taxguru_rss(xml_text: str, seen: set, items: list,
                        query: str = "", filter_kw: set = None):
    """Parse TaxGuru RSS XML into items list. Mutates seen + items."""
    for item in re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL):
        title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]>", item)
        link_m  = re.search(r"<link>(.*?)</link>", item)
        date_m  = re.search(r"<pubDate>(.*?)</pubDate>", item)
        desc_m  = re.search(r"<description><!\[CDATA\[(.*?)\]\]>", item, re.DOTALL)
        cats    = re.findall(r"<category><!\[CDATA\[(.*?)\]\]>", item)

        title = _clean((title_m.group(1) or "") if title_m else "")
        url   = (link_m.group(1) or "").strip() if link_m else ""
        date  = (date_m.group(1) or "").strip() if date_m else ""
        desc  = _clean(desc_m.group(1) or "" if desc_m else "")[:300]

        if not title or not url or url in seen:
            continue

        # Keyword filter when using fallback feeds
        if filter_kw:
            combined = (title + " " + desc).lower()
            if not any(k in combined for k in filter_kw):
                continue

        seen.add(url)
        cat_str = " ".join(cats).lower()
        ct = _court_type(cat_str, title)
        if "cbdt" in cat_str or "circular" in title.lower() or "notification" in title.lower():
            ct = "CBDT"

        items.append(_make_entry(title, url, ct,
                                  " / ".join(cats[:2]), date, desc,
                                  "taxguru", query))


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE ③ — itatonline.org search (/?s=QUERY)
# ─────────────────────────────────────────────────────────────────────────────

def search_itatonline(queries: list, sections: list,
                       progress_cb=None) -> list:
    """
    Search itatonline.org using its WordPress search.
    Returns ~5-10 items per query with rich section/ratio data from URL slugs.
    """
    if not requests:
        return []

    seen  = set()
    items = []

    # Build 2-3 targeted queries
    ito_queries = _build_rss_queries(queries, sections)[:3]

    for q in ito_queries:
        url = f"https://itatonline.org/?s={_urlencode(q)}"
        if progress_cb:
            progress_cb(f"  ⚖️ itatonline: {q[:50]}...")
        try:
            r = _get_with_retry(url, max_tries=3, timeout=15)
            if not r:
                continue

            html = r.text
            # itatonline uses entry-title class
            links = re.findall(
                r'<h[123][^>]*class=["\'][^"\']*entry-title[^"\']*["\'][^>]*>'
                r'\s*<a\s+href=["\']([^"\']+/archives/[^"\']+)["\'][^>]*>([^<]+)</a>',
                html
            )
            if not links:
                # fallback: any /archives/ link
                links = re.findall(
                    r'href=["\']([^"\']*itatonline\.org/archives/[^"\']+)["\'][^>]*>'
                    r'([^<]{15,150})</a>',
                    html
                )

            for case_url, title_raw in links:
                title = _clean(title_raw)
                if not title or case_url in seen:
                    continue
                seen.add(case_url)

                # Extract ratio from URL slug (itatonline encodes it)
                slug = case_url.rstrip("/").split("/")[-1]
                ratio = _slug_to_ratio(slug)

                # Look for date near this link
                idx   = html.find(case_url)
                near  = html[max(0, idx-200):idx+400]
                date_m = re.search(r'datetime=["\']([^"\']+)["\']', near)
                date  = date_m.group(1) if date_m else ""

                # Determine court from title/slug
                ct = "ITAT"
                if "high-court" in case_url.lower() or "hc" in slug[:10]:
                    ct = "HC"
                elif "supreme" in case_url.lower() or " sc " in title.lower():
                    ct = "SC"

                items.append(_make_entry(title, case_url, ct, "ITAT/HC/SC",
                                          date, ratio, "itatonline", q))
            time.sleep(_DELAY)
        except Exception as e:
            if progress_cb:
                progress_cb(f"  ⚠️ itatonline error: {e}")

    if progress_cb:
        progress_cb(f"  ✅ itatonline: {len(items)} results")
    return items


def _slug_to_ratio(slug: str) -> str:
    """Convert itatonline URL slug to readable ratio text."""
    # Slug format: name-vs-name-court-s-SECTION-ratio-words-here
    # Remove party names (before court identifier)
    slug = re.sub(r"[a-z]{3,}-\d{4}$", "", slug)   # strip year suffix
    # Find section marker
    sec_m = re.search(r"-s-(\w+)-(.+)", slug)
    if sec_m:
        section = sec_m.group(1).upper()
        ratio   = sec_m.group(2).replace("-", " ").strip()
        return f"§{section}: {ratio.capitalize()}"
    # Fallback: clean entire slug
    return slug.replace("-", " ").strip().capitalize()


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE ④ — CAclubindia judiciary search (/judiciary/?q=QUERY&cat_id=3)
# ─────────────────────────────────────────────────────────────────────────────

def search_caclubindia(queries: list, sections: list,
                        progress_cb=None, max_pages: int = 2) -> list:
    """
    Search CAclubindia Income Tax judgments using ?q=QUERY.
    Returns 10 per page × max_pages.
    """
    if not requests:
        return []

    seen  = set()
    items = []

    # Use section numbers directly + first keyword query
    search_terms = [f"{s}" for s in sections[:3]] + _build_rss_queries(queries, [])[:2]

    for term in search_terms[:4]:
        for page in range(1, max_pages + 1):
            offset = (page - 1) * 10
            url = (
                f"https://www.caclubindia.com/judiciary/"
                f"?q={_urlencode(term)}&cat_id=3&offset={offset}"
            )
            if progress_cb and page == 1:
                progress_cb(f"  🎯 CAclubindia: {term[:40]}...")
            try:
                r = _get_with_retry(url, max_tries=2, timeout=15)
                if not r:
                    break

                html  = r.text
                links = re.findall(
                    r'href=["\'](/judiciary/([a-z][a-z0-9-]+-\d+\.asp))["\'][^>]*>'
                    r'\s*([^<]{10,200})\s*</a>',
                    html
                )

                added_this_page = 0
                for rel_url, slug, title_raw in links:
                    title = _clean(title_raw)
                    full_url = f"https://www.caclubindia.com{rel_url}"
                    if not title or full_url in seen:
                        continue
                    seen.add(full_url)
                    added_this_page += 1

                    # Infer court from title
                    ct = _court_type("", title)

                    # Try to get description from near the link
                    idx  = html.find(rel_url)
                    near = html[max(0, idx-50):idx+400]
                    desc_m = re.search(r'<p[^>]*>([^<]{20,200})</p>', near)
                    headline = _clean(desc_m.group(1)) if desc_m else ""

                    items.append(_make_entry(title, full_url, ct,
                                              "Income Tax Judgment", "",
                                              headline, "caclubindia", term))

                if added_this_page == 0:
                    break  # No more results
                time.sleep(_DELAY)

            except Exception as e:
                if progress_cb:
                    progress_cb(f"  ⚠️ CAclubindia error: {e}")
                break

    if progress_cb:
        progress_cb(f"  ✅ CAclubindia: {len(items)} results")
    return items


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE ⑤ — TaxGuru CBDT (category RSS for circulars + notifications)
# ─────────────────────────────────────────────────────────────────────────────

def search_cbdt(sections: list, keywords: list,
                progress_cb=None) -> list:
    """
    Fetch CBDT circulars and notifications from TaxGuru RSS,
    filtered to the sections/keywords of this case.
    """
    if not requests:
        return []

    cbdt_feeds = [
        ("cbdt_circular",     "https://taxguru.in/income-tax/feed/?cat=cbdt-circular"),
        ("cbdt_notification", "https://taxguru.in/income-tax/feed/?cat=cbdt-notification"),
    ]

    seen  = set()
    items = []
    kw_set = {k.lower() for k in (keywords or []) + sections}

    for feed_key, feed_url in cbdt_feeds:
        if progress_cb:
            progress_cb(f"  📜 CBDT {feed_key}: fetching RSS...")
        try:
            r = _get_with_retry(feed_url, max_tries=3, timeout=15)
            if not r:
                continue

            for item in re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL):
                title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]>", item)
                link_m  = re.search(r"<link>(.*?)</link>", item)
                date_m  = re.search(r"<pubDate>(.*?)</pubDate>", item)
                desc_m  = re.search(r"<description><!\[CDATA\[(.*?)\]\]>", item, re.DOTALL)

                title = _clean((title_m.group(1) or "") if title_m else "")
                url   = (link_m.group(1) or "").strip() if link_m else ""
                date  = (date_m.group(1) or "").strip() if date_m else ""
                desc  = _clean(desc_m.group(1) or "" if desc_m else "")[:250]

                if not title or not url or url in seen:
                    continue

                # Only include if relevant to this case's sections/keywords
                combined = (title + " " + desc).lower()
                if not any(kw in combined for kw in kw_set):
                    continue

                seen.add(url)
                items.append(_make_entry(title, url, "CBDT", "CBDT",
                                          date, desc, feed_key))
            time.sleep(_DELAY)

        except Exception as e:
            if progress_cb:
                progress_cb(f"  ⚠️ CBDT {feed_key} error: {e}")

    if progress_cb:
        progress_cb(f"  ✅ CBDT: {len(items)} relevant circulars/notifications")
    return items


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE ⑥ — Taxscan RSS (income-tax feed, filtered by keywords)
# ─────────────────────────────────────────────────────────────────────────────

def search_taxscan(sections: list, keywords: list,
                   progress_cb=None) -> list:
    """
    Fetch Taxscan income-tax RSS and filter to case-relevant items.
    """
    if not requests:
        return []

    kw_set = {k.lower() for k in (keywords or []) + sections}
    seen   = set()
    items  = []

    feeds = [
        "https://www.taxscan.in/income-tax/feed/",
        "https://www.taxscan.in/feed/",
    ]

    for feed_url in feeds:
        try:
            r = _get_with_retry(feed_url, max_tries=2, timeout=15)
            if not r:
                continue

            for item in re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL):
                title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]>|<title>(.*?)</title>", item)
                link_m  = re.search(r"<link>(.*?)</link>", item)
                date_m  = re.search(r"<pubDate>(.*?)</pubDate>", item)
                desc_m  = re.search(r"<description><!\[CDATA\[(.*?)\]\]>", item, re.DOTALL)

                title = _clean((title_m.group(1) or title_m.group(2) or "") if title_m else "")
                url   = (link_m.group(1) or "").strip() if link_m else ""
                date  = (date_m.group(1) or "").strip() if date_m else ""
                desc  = _clean(desc_m.group(1) or "" if desc_m else "")[:250]

                if not title or not url or url in seen:
                    continue

                combined = (title + " " + desc).lower()
                if not any(kw in combined for kw in kw_set):
                    continue

                seen.add(url)
                ct = _court_type("", title)
                items.append(_make_entry(title, url, ct, "Taxscan.in",
                                          date, desc, "taxscan"))
            break  # first feed that returns results is enough
        except Exception:
            continue

    if progress_cb and items:
        progress_cb(f"  ✅ Taxscan: {len(items)} relevant results")
    return items


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _urlencode(s: str) -> str:
    """Simple URL encoding for query strings."""
    import urllib.parse
    return urllib.parse.quote_plus(s)


def _build_rss_queries(ai_queries: list, sections: list) -> list:
    """
    Build 3-4 clean search strings from AI queries + sections.
    Uses section numbers first (highest signal), then key phrases from AI queries.
    """
    result = []

    # Section-only queries (short, high precision)
    for s in sections[:2]:
        result.append(s)

    # Extract 2-4 word phrases from AI queries
    for q in ai_queries[:4]:
        # Take meaningful 3-word chunks
        words = [w for w in q.split()
                 if len(w) > 3 and w.lower() not in {
                     "the", "and", "for", "with", "from", "that", "this",
                     "income", "section", "under"
                 }]
        if words:
            chunk = " ".join(words[:4])
            if chunk not in result:
                result.append(chunk)

    return result[:5]


# ─────────────────────────────────────────────────────────────────────────────
# MASTER: run_live_search()
# ─────────────────────────────────────────────────────────────────────────────

def run_live_search(queries: list, sections: list,
                    cbdt_keywords: list = None,
                    progress_cb=None) -> dict:
    """
    Run all live sources in sequence and return grouped results.

    queries   — AI-generated search queries from the uploaded case
    sections  — violated IT Act sections (e.g. ['269SS','271D'])
    cbdt_keywords — keywords for CBDT filtering (from case intelligence)

    Returns:
      { "sc": [...], "hc": [...], "itat": [...], "cbdt": [...], "other": [...] }
    """
    def _cb(msg):
        if progress_cb:
            progress_cb(msg)

    grouped = {"sc": [], "hc": [], "itat": [], "cbdt": [], "other": []}
    seen_urls = set()

    def _add(items: list):
        for item in items:
            url = item.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            ct = item.get("court_type", "ITAT")
            if ct == "SC":
                grouped["sc"].append(item)
            elif ct == "HC":
                grouped["hc"].append(item)
            elif ct == "CBDT":
                grouped["cbdt"].append(item)
            elif ct == "ITAT":
                grouped["itat"].append(item)
            else:
                grouped["itat"].append(item)

    # ── ① Indian Kanoon ──────────────────────────────────────────────────────
    _cb("\n① Searching Indian Kanoon (live API)...")
    _add(search_indian_kanoon(queries, sections, progress_cb=_cb))

    # ── ② TaxGuru RSS search ─────────────────────────────────────────────────
    _cb("\n② Searching TaxGuru via RSS search...")
    _add(search_taxguru(queries, sections, progress_cb=_cb))

    # ── ③ itatonline search ──────────────────────────────────────────────────
    _cb("\n③ Searching itatonline.org...")
    _add(search_itatonline(queries, sections, progress_cb=_cb))

    # ── ④ CAclubindia judiciary search ───────────────────────────────────────
    _cb("\n④ Searching CAclubindia judiciary...")
    _add(search_caclubindia(queries, sections, progress_cb=_cb))

    # ── ⑤ CBDT circulars (TaxGuru category RSS, filtered) ───────────────────
    _cb("\n⑤ Fetching CBDT circulars & notifications...")
    _add(search_cbdt(sections, cbdt_keywords or sections, progress_cb=_cb))

    # ── ⑥ Taxscan RSS (filtered) ─────────────────────────────────────────────
    _cb("\n⑥ Checking Taxscan.in (RSS + Playwright)...")
    # Try Playwright first (full content), RSS as fallback (handled internally)
    try:
        from ai.scrapers.taxscan_playwright import search_taxscan_playwright
        ts_results = search_taxscan_playwright(queries, sections, progress_cb=_cb)
        if ts_results:
            _add(ts_results)
        else:
            _add(search_taxscan(sections, cbdt_keywords or queries[:3], progress_cb=_cb))
    except Exception:
        _add(search_taxscan(sections, cbdt_keywords or queries[:3], progress_cb=_cb))

    # ── ⑦ Web Search (Google CSE + Bing) — ranked by similarity ─────────────
    _cb("\n⑦ Web search (Google/Bing) — ranked by relevance...")
    try:
        from utils.web_search import run_web_search, web_results_to_entries
        web_results = run_web_search(queries, sections, top_k=20, progress_cb=_cb)
        if web_results:
            _add(web_results_to_entries(web_results))
    except Exception as e:
        _cb(f"  ⚠️ Web search error: {e}")

    # Sort each group: newest first, then by web_score if available
    for k in grouped:
        grouped[k].sort(
            key=lambda x: (x.get("web_score", 0), x.get("year", 0)),
            reverse=True,
        )

    total = sum(len(v) for v in grouped.values())
    _cb(f"\n✅ Live search complete — {total} results "
        f"(SC:{len(grouped['sc'])} HC:{len(grouped['hc'])} "
        f"ITAT:{len(grouped['itat'])} CBDT:{len(grouped['cbdt'])})")

    return grouped
