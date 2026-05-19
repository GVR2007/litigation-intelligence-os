"""
Web Search Layer — DuckDuckGo (free, zero-key) + optional paid upgrades.

PRIMARY: ddgs library (pip install ddgs) — completely free, no API key,
         uses DuckDuckGo's real search index. Covers every tax law site:
         indiankanoon.org, itatonline.org, taxguru.in, incometax.gov.in,
         abcaus.in, taxscan.in, High Court / ITAT official portals.

OPTIONAL upgrades (add to .env for extra volume):
  GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID   — 100 free/day, $5/1000 after
  BING_SEARCH_API_KEY                  — 1,000 free/month (Azure free tier)

If paid keys are absent, DDG handles everything at zero cost.

Similarity scoring (applied to all sources):
  ① Section number found in title/body/url  → +5 per section
  ② Query-term overlap                      → +1 per term
  ③ Court level  SC / HC / ITAT             → +3 / +2 / +1
  ④ Positive outcome keywords               → +1
  ⑤ Recency  ≥2020 / ≥2015                 → +2 / +1
  ⑥ Authoritative domain                   → +2
"""

from __future__ import annotations
import re
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import requests as _requests
except ImportError:
    _requests = None

_AUTHORITY_DOMAINS = [
    "indiankanoon.org", "itatonline.org", "incometax.gov.in",
    "cbdt.gov.in", "itat.gov.in", "abcaus.in",
]

_POSITIVE_OUTCOMES = [
    "deleted", "quashed", "allowed", "dismissed by revenue",
    "penalty deleted", "addition deleted", "set aside",
    "accepted", "favour of assessee", "relief granted",
    "penalty cancelled", "appeal allowed", "restored",
]

_SC_MARKERS   = ["supreme court", " sc ", "(sc)", "hon'ble supreme"]
_HC_MARKERS   = ["high court", "hc ", "(hc)", "bombay hc", "delhi hc",
                 "madras hc", "calcutta hc", "allahabad hc",
                 "gujarat hc", "karnataka hc", "kerala hc", "rajasthan hc"]
_ITAT_MARKERS = ["itat", "income tax appellate tribunal",
                 "appellate tribunal", "tribunal held", "bench held"]


# ─────────────────────────────────────────────────────────────────────────────
# Similarity scorer
# ─────────────────────────────────────────────────────────────────────────────

def score_result(title: str, body: str, url: str,
                 query: str, sections: list[str]) -> float:
    """Return relevance score — higher is more relevant to this case."""
    text  = (title + " " + body + " " + url).lower()
    score = 0.0

    # ① Section match
    for sec in sections:
        sec_pat = re.escape(sec.lower())
        if re.search(rf"\b{sec_pat}\b", text):
            score += 5.0

    # ② Query-term overlap
    stop = {"the", "and", "or", "of", "in", "to", "for", "a", "an",
            "is", "are", "was", "income", "tax", "itat", "section",
            "under", "with", "that", "from", "by", "on", "it", "this"}
    terms = [t for t in re.findall(r"[a-z]{4,}", query.lower()) if t not in stop]
    score += sum(1.0 for t in terms if t in text)

    # ③ Court-level bonus
    if any(m in text for m in _SC_MARKERS):
        score += 3.0
    elif any(m in text for m in _HC_MARKERS):
        score += 2.0
    elif any(m in text for m in _ITAT_MARKERS):
        score += 1.0

    # ④ Positive outcome
    if any(kw in text for kw in _POSITIVE_OUTCOMES):
        score += 1.0

    # ⑤ Recency
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    if years:
        score += 2.0 if max(years) >= 2020 else 1.0

    # ⑥ Authoritative domain
    if any(d in url.lower() for d in _AUTHORITY_DOMAINS):
        score += 2.0

    return round(score, 2)


def _infer_court(title: str, body: str, url: str) -> str:
    combined = (title + " " + body + " " + url).lower()
    if any(m in combined for m in _SC_MARKERS):
        return "SC"
    if any(m in combined for m in _HC_MARKERS):
        return "HC"
    if "cbdt" in combined or "circular" in combined or "notification" in combined:
        return "CBDT"
    return "ITAT"


def _extract_year(text: str) -> int:
    m = re.search(r"\b(20\d{2}|19\d{2})\b", text)
    return int(m.group()) if m else 0


# ─────────────────────────────────────────────────────────────────────────────
# PRIMARY: DuckDuckGo via ddgs library — completely free, no key needed
# ─────────────────────────────────────────────────────────────────────────────

def search_duckduckgo(queries: list[str],
                      sections: list[str],
                      max_per_query: int = 10,
                      progress_cb=None) -> list[dict]:
    """
    Search DuckDuckGo using the ddgs library — free, no API key.
    Install: pip install ddgs

    Strategy:
      Pass 1 — site-scoped to authoritative tax domains (high precision)
      Pass 2 — site:indiankanoon.org directly (bypasses IK API issue)
      Pass 3 — open web query (high recall for outlier cases)

    All results scored and returned sorted by relevance.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        if progress_cb:
            progress_cb("  ⚠️ DDG: 'ddgs' not installed — run: pip install ddgs")
        return []

    sec_suffix   = " ".join(sections[:3])
    seen         = set()
    results      = []

    # ── Pass 1: site-scoped to tax law domains ────────────────────────────────
    site_filter = (
        "site:indiankanoon.org OR site:itatonline.org OR "
        "site:taxguru.in OR site:taxscan.in OR site:abcaus.in OR "
        "site:incometax.gov.in OR site:caclubindia.com"
    )

    enriched: list[str] = []
    for q in queries[:3]:
        base = q if any(s in q for s in sections) else f"{q} {sec_suffix}"
        enriched.append(f"{base} {site_filter}")

    # ── Pass 2: direct site:indiankanoon.org (replaces broken IK API) ─────────
    for sec in sections[:2]:
        enriched.append(f"site:indiankanoon.org {sec} penalty deleted evidence")
        enriched.append(f"site:indiankanoon.org {sec} ITAT judgment documents accepted")

    # ── Pass 3: open query for recall ─────────────────────────────────────────
    if queries:
        enriched.append(f"{queries[0]} income tax ITAT judgment {sec_suffix}")

    for q in enriched:
        short = q.split("site:")[0].strip()[:60] or q[:60]
        if progress_cb:
            progress_cb(f"  🦆 DDG: {short}...")
        try:
            with DDGS() as ddgs:
                hits = list(ddgs.text(q, max_results=max_per_query))

            for r in hits:
                url   = r.get("href", "").strip()
                title = r.get("title", "").strip()
                body  = r.get("body", "").strip()

                if not url or url in seen:
                    continue
                seen.add(url)

                relevance = score_result(title, body, url, q, sections)
                ct        = _infer_court(title, body, url)
                year      = _extract_year(title + " " + body)

                results.append({
                    "title":      title[:120],
                    "url":        url,
                    "snippet":    body[:300],
                    "court_type": ct,
                    "year":       year,
                    "source":     "duckduckgo",
                    "score":      relevance,
                    "query":      q[:80],
                })

            time.sleep(0.8)   # polite delay — DDG rate limits at ~1 req/s

        except Exception as e:
            if progress_cb:
                progress_cb(f"  ⚠️ DDG error: {e}")
            time.sleep(2.0)   # back off on error
            continue

    results.sort(key=lambda x: x["score"], reverse=True)

    if progress_cb:
        if results:
            progress_cb(
                f"  ✅ DDG: {len(results)} results | "
                f"top [{results[0]['court_type']}] "
                f"{results[0]['title'][:50]}... (score {results[0]['score']:.1f})"
            )
        else:
            progress_cb("  ⚠️ DDG: 0 results")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL: Google CSE (100 free/day — add key to .env to activate)
# ─────────────────────────────────────────────────────────────────────────────

def _search_google_cse(queries: list[str], sections: list[str],
                       progress_cb=None) -> list[dict]:
    try:
        import config
        api_key = getattr(config, "GOOGLE_CSE_API_KEY", "") or os.getenv("GOOGLE_CSE_API_KEY", "")
        cx      = getattr(config, "GOOGLE_CSE_ID", "")      or os.getenv("GOOGLE_CSE_ID", "")
    except Exception:
        api_key = os.getenv("GOOGLE_CSE_API_KEY", "")
        cx      = os.getenv("GOOGLE_CSE_ID", "")

    if not api_key or not cx or not _requests:
        return []

    seen    = set()
    results = []
    sfx     = " ".join(sections[:3]) + " income tax ITAT"

    for q in queries[:3]:
        eq = q if any(s in q for s in sections) else f"{q} {sfx}"
        if progress_cb:
            progress_cb(f"  🌐 Google CSE: {eq[:60]}...")
        try:
            resp = _requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": api_key, "cx": cx, "q": eq[:200], "num": 10},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            for item in resp.json().get("items", []):
                url   = item.get("link", "").strip()
                title = item.get("title", "").strip()
                body  = item.get("snippet", "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append({
                    "title":      title[:120],
                    "url":        url,
                    "snippet":    body[:300],
                    "court_type": _infer_court(title, body, url),
                    "year":       _extract_year(title + " " + body),
                    "source":     "google_cse",
                    "score":      score_result(title, body, url, q, sections),
                    "query":      eq[:60],
                })
            time.sleep(0.3)
        except Exception as e:
            if progress_cb:
                progress_cb(f"  ⚠️ Google CSE: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL: Bing (1,000 free/month — add key to .env to activate)
# ─────────────────────────────────────────────────────────────────────────────

def _search_bing(queries: list[str], sections: list[str],
                 progress_cb=None) -> list[dict]:
    try:
        import config
        api_key = getattr(config, "BING_SEARCH_API_KEY", "") or os.getenv("BING_SEARCH_API_KEY", "")
    except Exception:
        api_key = os.getenv("BING_SEARCH_API_KEY", "")

    if not api_key or not _requests:
        return []

    seen    = set()
    results = []
    sfx     = " ".join(sections[:3]) + " income tax ITAT"

    for q in queries[:3]:
        eq = q if any(s in q for s in sections) else f"{q} {sfx}"
        if progress_cb:
            progress_cb(f"  🔎 Bing: {eq[:60]}...")
        try:
            resp = _requests.get(
                "https://api.bing.microsoft.com/v7.0/search",
                headers={"Ocp-Apim-Subscription-Key": api_key},
                params={"q": eq[:200], "count": 10, "mkt": "en-IN"},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            for page in resp.json().get("webPages", {}).get("value", []):
                url   = page.get("url", "").strip()
                title = page.get("name", "").strip()
                body  = page.get("snippet", "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append({
                    "title":      title[:120],
                    "url":        url,
                    "snippet":    body[:300],
                    "court_type": _infer_court(title, body, url),
                    "year":       _extract_year(title + " " + body),
                    "source":     "bing_search",
                    "score":      score_result(title, body, url, q, sections),
                    "query":      eq[:60],
                })
            time.sleep(0.3)
        except Exception as e:
            if progress_cb:
                progress_cb(f"  ⚠️ Bing: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Master: run_web_search()
# ─────────────────────────────────────────────────────────────────────────────

def run_web_search(queries: list[str],
                   sections: list[str],
                   top_k: int = 20,
                   progress_cb=None) -> list[dict]:
    """
    1. DDG (always — free, zero config)
    2. Google CSE (if GOOGLE_CSE_API_KEY configured)
    3. Bing (if BING_SEARCH_API_KEY configured)
    Merge all → deduplicate → re-rank → return top_k.
    """
    all_results: list[dict] = []

    all_results.extend(search_duckduckgo(queries, sections, progress_cb=progress_cb))
    all_results.extend(_search_google_cse(queries, sections, progress_cb=progress_cb))
    all_results.extend(_search_bing(queries, sections, progress_cb=progress_cb))

    # Deduplicate by URL — keep highest-scoring entry per URL
    best: dict[str, dict] = {}
    for item in all_results:
        url = item.get("url", "")
        if url and (url not in best or item["score"] > best[url]["score"]):
            best[url] = item

    merged = sorted(best.values(), key=lambda x: x["score"], reverse=True)

    if progress_cb and merged:
        sources = set(r["source"] for r in merged)
        progress_cb(
            f"\n  🏆 Web: {len(merged)} unique results from {', '.join(sources)} "
            f"→ top {min(top_k, len(merged))} "
            f"(score {merged[-1]['score']:.1f}–{merged[0]['score']:.1f})"
        )

    return merged[:top_k]


def web_results_to_entries(results: list[dict]) -> list[dict]:
    """Convert to the standard live_search dict shape for the UI."""
    return [
        {
            "title":      r["title"],
            "url":        r["url"],
            "court_type": r["court_type"],
            "court":      r["court_type"],
            "year":       r["year"],
            "date":       str(r["year"]) if r["year"] else "",
            "headline":   r.get("snippet", ""),
            "source":     r["source"],
            "section":    "",
            "query":      r.get("query", ""),
            "web_score":  r["score"],
        }
        for r in results
    ]
