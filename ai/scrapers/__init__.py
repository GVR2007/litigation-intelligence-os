"""
Multi-source scraper package for Litigation Intelligence OS.

8 integrated sources:
  1. itatonline.org        — Expert-curated ITAT/HC/SC with full legal ratios (3,100+)
  2. TaxGuru ITAT          — ITAT judgments category (6,700+ pages, 60/page)
  3. TaxGuru HC            — High Court income tax judgments
  4. Taxscan.in            — ITAT Weekly Roundup + live income-tax RSS
  5. CAclubindia.com       — Income Tax judgments (2,820+ via offset pagination)
  6. TaxGuru SC            — Supreme Court income tax judgments (100+ per RSS)
  7. TaxGuru CBDT Circulars     — CBDT circulars (100 per RSS)
  8. TaxGuru CBDT Notifications — CBDT notifications (100 per RSS)

Usage:
    from ai.scrapers import scrape_all, scrape_source, SOURCE_REGISTRY
    results = scrape_all(max_pages=5, progress_cb=print)
    results = scrape_source("caclubindia", max_pages=3)
"""

from ai.scrapers.itatonline   import scrape as scrape_itatonline
from ai.scrapers.taxguru      import (
    scrape_itat_only as scrape_taxguru_itat,
    scrape_hc_only   as scrape_taxguru_hc,
)
from ai.scrapers.taxscan      import scrape as scrape_taxscan
from ai.scrapers.caclubindia  import scrape as scrape_caclubindia
from ai.scrapers.taxguru_sc   import scrape as scrape_taxguru_sc
from ai.scrapers.taxguru_cbdt import scrape as _scrape_taxguru_cbdt


def _scrape_cbdt_circulars(max_pages=2, progress_cb=None):
    """Wrapper: only fetch CBDT circulars."""
    from ai.scrapers.taxguru_cbdt import _parse_rss, _parse_page, _DELAY
    import time
    if progress_cb:
        progress_cb("TaxGuru CBDT Circulars — RSS + HTML pages")
    all_c = {}
    for c in _parse_rss("cbdt_circular", progress_cb):
        all_c[c["url"]] = c
    for page in range(1, max_pages + 1):
        for c in _parse_page(page, "cbdt_circular", progress_cb):
            if c["url"] not in all_c:
                all_c[c["url"]] = c
        time.sleep(_DELAY)
    return list(all_c.values())


def _scrape_cbdt_notifications(max_pages=2, progress_cb=None):
    """Wrapper: only fetch CBDT notifications."""
    from ai.scrapers.taxguru_cbdt import _parse_rss, _parse_page, _DELAY
    import time
    if progress_cb:
        progress_cb("TaxGuru CBDT Notifications — RSS + HTML pages")
    all_c = {}
    for c in _parse_rss("cbdt_notification", progress_cb):
        all_c[c["url"]] = c
    for page in range(1, max_pages + 1):
        for c in _parse_page(page, "cbdt_notification", progress_cb):
            if c["url"] not in all_c:
                all_c[c["url"]] = c
        time.sleep(_DELAY)
    return list(all_c.values())


SOURCE_REGISTRY = {
    # ── Core judgment sources ─────────────────────────────────────────────────
    "itatonline": {
        "name":              "itatonline.org",
        "fn":                scrape_itatonline,
        "description":       "Expert-curated ITAT/HC/SC cases with full legal ratios",
        "max_pages_default": 5,
        "approx_per_page":   10,
        "icon":              "⚖️",
        "category":          "judgments",
    },
    "taxguru_itat": {
        "name":              "TaxGuru.in — ITAT Judgments",
        "fn":                scrape_taxguru_itat,
        "description":       "ITAT judgments — 6,700+ pages, 60 articles each",
        "max_pages_default": 5,
        "approx_per_page":   60,
        "icon":              "📋",
        "category":          "judgments",
    },
    "taxguru_hc": {
        "name":              "TaxGuru.in — High Court",
        "fn":                scrape_taxguru_hc,
        "description":       "High Court income tax judgments from TaxGuru",
        "max_pages_default": 3,
        "approx_per_page":   60,
        "icon":              "🏛️",
        "category":          "judgments",
    },
    "taxscan": {
        "name":              "Taxscan.in",
        "fn":                scrape_taxscan,
        "description":       "ITAT Weekly Roundup (27 cases/issue) + live income-tax RSS",
        "max_pages_default": 2,
        "approx_per_page":   27,
        "icon":              "📰",
        "category":          "judgments",
    },
    "caclubindia": {
        "name":              "CAclubindia.com",
        "fn":                scrape_caclubindia,
        "description":       "Income Tax judgments — 2,820+ cases (offset pagination)",
        "max_pages_default": 5,
        "approx_per_page":   10,
        "icon":              "🎯",
        "category":          "judgments",
    },
    "taxguru_sc": {
        "name":              "TaxGuru.in — Supreme Court",
        "fn":                scrape_taxguru_sc,
        "description":       "Supreme Court income tax judgments — highest authority",
        "max_pages_default": 2,
        "approx_per_page":   100,
        "icon":              "🏛️",
        "category":          "judgments",
    },
    # ── CBDT sources ──────────────────────────────────────────────────────────
    "taxguru_cbdt_circular": {
        "name":              "TaxGuru.in — CBDT Circulars",
        "fn":                _scrape_cbdt_circulars,
        "description":       "CBDT circulars — reasonable-cause defence, threshold limits",
        "max_pages_default": 2,
        "approx_per_page":   100,
        "icon":              "📜",
        "category":          "cbdt",
    },
    "taxguru_cbdt_notif": {
        "name":              "TaxGuru.in — CBDT Notifications",
        "fn":                _scrape_cbdt_notifications,
        "description":       "CBDT notifications — compliance extensions, exemptions",
        "max_pages_default": 2,
        "approx_per_page":   100,
        "icon":              "📣",
        "category":          "cbdt",
    },
}


def scrape_source(source_key: str, max_pages: int = None,
                  progress_cb=None) -> list[dict]:
    """Scrape one source. Returns list of case dicts."""
    info = SOURCE_REGISTRY.get(source_key)
    if not info:
        raise ValueError(
            f"Unknown source: {source_key!r}. "
            f"Choose from: {list(SOURCE_REGISTRY)}"
        )
    pages = max_pages or info["max_pages_default"]
    return info["fn"](max_pages=pages, progress_cb=progress_cb)


def scrape_all(max_pages: int = 3, progress_cb=None) -> dict:
    """
    Scrape all 8 sources and return combined results.
    Returns {source_key: [case_dict, ...], 'total': N}
    """
    all_results = {}
    total = 0
    for key, info in SOURCE_REGISTRY.items():
        if progress_cb:
            progress_cb(f"\n[{key}] {info['icon']} {info['name']}...")
        try:
            cases = info["fn"](max_pages=max_pages, progress_cb=progress_cb)
            all_results[key] = cases
            total += len(cases)
            if progress_cb:
                progress_cb(f"  ✅ {info['name']}: {len(cases)} items")
        except Exception as e:
            if progress_cb:
                progress_cb(f"  ❌ {info['name']} error: {e}")
            all_results[key] = []
    all_results["total"] = total
    return all_results
