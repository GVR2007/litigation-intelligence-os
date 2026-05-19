"""
Multi-Source Harvester — saves scraped web cases into the SQLite citation DB.

Bridges the scraper layer (itatonline, taxguru, taxscan) with the
existing itat_precedents table used by citation_harvester.py.

Each scraped case gets:
  verified = 2   (scrape-verified, not IK-API verified)
  ik_url   = source URL (taxguru/itatonline/taxscan page)
  ik_tid   = ""  (no IK tid for web-scraped cases)
  court_type, section, year, key_ratio — from scraper

Consumers (citation_db.py, AI prompts) treat verified ∈ {1,2} as trustworthy.
"""

import sys
import os
import re
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from database.init_db import get_connection
from ai.scrapers import scrape_all, scrape_source, SOURCE_REGISTRY


# ── Column migration (ensures source_name, source_url columns exist) ──────────

def _ensure_columns():
    """Add source_name, source_url to itat_precedents if not present."""
    conn = get_connection()
    cur  = conn.cursor()
    extras = [
        ("source_name", "TEXT DEFAULT ''"),
        ("source_url",  "TEXT DEFAULT ''"),
    ]
    for col, col_type in extras:
        try:
            cur.execute(f"ALTER TABLE itat_precedents ADD COLUMN {col} {col_type}")
        except Exception:
            pass
    conn.commit()
    conn.close()


# ── Save one scraped case ─────────────────────────────────────────────────────

def _save_scraped_case(cur, case: dict) -> bool:
    """
    Insert a scraped case into itat_precedents.
    Returns True if a new row was inserted.

    verified=2 means "web-scrape verified" (URL exists, not IK API verified).
    """
    title       = (case.get("title") or "").strip()
    url         = (case.get("url") or case.get("source_url") or "").strip()
    section     = (case.get("section") or "").strip()
    court_name  = (case.get("court_name") or "").strip()
    court_type  = (case.get("court_type") or "OTHER").strip()
    year        = case.get("year") or 0
    key_ratio   = (case.get("key_ratio") or "").strip()
    date_str    = (case.get("date") or "").strip()
    source_name = (case.get("source") or "web").strip()
    source_url  = url
    outcome     = (case.get("outcome") or "").strip()

    if not title or not url:
        return False

    # Build a citation string similar to IK style
    court_short = court_name[:40] if court_name else court_type
    citation = f"{title[:180]} ({court_short}, {year})" if year else f"{title[:180]} ({court_short})"

    # Truncate if needed
    if len(citation) > 250:
        citation = citation[:247] + "..."

    # Dedup: skip if citation already exists OR if source_url already exists
    cur.execute(
        "SELECT id FROM itat_precedents WHERE case_citation = ? OR ik_url = ?",
        (citation, url)
    )
    if cur.fetchone():
        return False

    try:
        cur.execute("""
            INSERT INTO itat_precedents
            (case_citation, section, bench, year, outcome, key_ratio,
             facts_summary, win_for_assessee, relevance_score,
             ik_tid, ik_url, court_type, verified,
             sections_json, harvested_at,
             source_name, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, ?, CURRENT_TIMESTAMP, ?, ?)
        """, (
            citation,
            section,
            court_name[:100],
            year,
            outcome or "See full text at source",
            key_ratio[:500] if key_ratio else "See full text at source",
            key_ratio[:300] if key_ratio else "",
            1,    # default assessee-friendly
            0.65, # slightly lower than IK-API verified (0.7)
            "",   # no ik_tid
            url,
            court_type,
            f'["{section}"]' if section else "[]",
            source_name,
            source_url,
        ))
        return cur.rowcount > 0
    except Exception:
        return False


# ── Main harvest functions ─────────────────────────────────────────────────────

def harvest_source(source_key: str, max_pages: int = 5,
                   progress_cb=None) -> dict:
    """
    Scrape one source and save to DB.
    Returns {"added": N, "skipped": M, "source": source_key}
    """
    _ensure_columns()

    if progress_cb:
        info = SOURCE_REGISTRY.get(source_key, {})
        progress_cb(f"[{source_key}] Scraping {info.get('name', source_key)} ({max_pages} pages)...")

    try:
        cases = scrape_source(source_key, max_pages=max_pages,
                              progress_cb=progress_cb)
    except Exception as e:
        if progress_cb:
            progress_cb(f"  ❌ Scrape error: {e}")
        return {"added": 0, "skipped": 0, "source": source_key, "error": str(e)}

    conn = get_connection()
    cur  = conn.cursor()
    added   = 0
    skipped = 0

    for case in cases:
        if _save_scraped_case(cur, case):
            added += 1
        else:
            skipped += 1

    conn.commit()
    conn.close()

    if progress_cb:
        progress_cb(f"  ✅ {source_key}: +{added} new, {skipped} skipped/duplicate")
    return {"added": added, "skipped": skipped, "source": source_key}


def harvest_all_sources(max_pages: int = 3, progress_cb=None,
                        sources: list = None) -> dict:
    """
    Scrape ALL 8 sources and save to DB.
    sources: optional subset list of source keys to run.
    Returns summary dict with per-source counts.
    """
    _ensure_columns()

    if progress_cb:
        progress_cb("Starting multi-source harvest...")

    summary  = {}
    total    = 0
    run_keys = sources if sources else list(SOURCE_REGISTRY.keys())

    for i, key in enumerate(run_keys):
        if progress_cb:
            progress_cb(f"\n[{i+1}/{len(run_keys)}] {key}")
        result = harvest_source(key, max_pages=max_pages,
                                progress_cb=progress_cb)
        summary[key] = result
        total += result.get("added", 0)

    summary["total_added"] = total
    if progress_cb:
        progress_cb(f"\n✅ Multi-source harvest done — {total} new citations added")
    return summary


def get_scraped_count() -> int:
    """Return count of web-scraped (verified=2) citations."""
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM itat_precedents WHERE verified = 2")
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_source_breakdown() -> list[dict]:
    """
    Return per-source citation counts.
    [{"source_name": "itatonline", "count": 120, "sections": 15}, ...]
    """
    _ensure_columns()
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
            COALESCE(source_name, 'indian_kanoon') as source_name,
            COUNT(*)                                as count,
            COUNT(DISTINCT section)                 as sections
        FROM itat_precedents
        WHERE verified IN (1, 2)
        GROUP BY source_name
        ORDER BY count DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


if __name__ == "__main__":
    def cb(msg): print(msg)
    result = harvest_all_sources(max_pages=2, progress_cb=cb)
    print(f"\nSummary: {result}")
    print(f"Scraped total: {get_scraped_count()}")
    print("\nSource breakdown:")
    for row in get_source_breakdown():
        print(f"  {row['source_name']}: {row['count']} citations, {row['sections']} sections")
