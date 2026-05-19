"""
Result Cache — SQLite-backed cache for all web/IK search results.

Why: Prevents re-fetching the same queries on every upload.
     A §269SS query answered today is valid for 7 days.
     Saves Gemini quota, IK scrape quota, and DDG rate limits.

Usage:
    from utils.result_cache import cache_get, cache_set, cache_clear_old

    data = cache_get("269SS penalty deleted", "ik_scrape")
    if data is None:
        data = do_expensive_fetch(...)
        cache_set("269SS penalty deleted", "ik_scrape", data, ttl_days=7)
"""

from __future__ import annotations
import sqlite3
import json
import hashlib
import os
import time
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Cache DB lives next to the main DB
_CACHE_DB = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "search_cache.db"
)


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_CACHE_DB), exist_ok=True)
    con = sqlite3.connect(_CACHE_DB, timeout=10)
    con.execute("""
        CREATE TABLE IF NOT EXISTS search_cache (
            cache_key   TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            query       TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at  REAL NOT NULL,
            expires_at  REAL NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_expires ON search_cache(expires_at)")
    con.commit()
    return con


def _key(query: str, source: str) -> str:
    """Stable hash key from query + source."""
    raw = f"{source}::{query.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def cache_get(query: str, source: str):
    """
    Return cached result (any JSON-serialisable type) or None if
    not cached / expired.
    """
    try:
        con = _conn()
        row = con.execute(
            "SELECT result_json, expires_at FROM search_cache WHERE cache_key = ?",
            (_key(query, source),)
        ).fetchone()
        con.close()

        if row is None:
            return None

        result_json, expires_at = row
        if time.time() > expires_at:
            return None          # expired — caller will re-fetch

        return json.loads(result_json)
    except Exception:
        return None


def cache_set(query: str, source: str, result, ttl_days: int = 7) -> None:
    """
    Store result in cache with TTL.
    result must be JSON-serialisable (list, dict, str, etc.)
    """
    try:
        now     = time.time()
        expires = now + ttl_days * 86400
        key     = _key(query, source)
        con     = _conn()
        con.execute("""
            INSERT OR REPLACE INTO search_cache
                (cache_key, source, query, result_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key, source, query[:500], json.dumps(result), now, expires))
        con.commit()
        con.close()
    except Exception:
        pass    # cache failures are always silent — never break the main flow


def cache_clear_old() -> int:
    """Delete all expired entries. Returns count deleted."""
    try:
        con  = _conn()
        cur  = con.execute(
            "DELETE FROM search_cache WHERE expires_at < ?", (time.time(),)
        )
        count = cur.rowcount
        con.commit()
        con.close()
        return count
    except Exception:
        return 0


def cache_stats() -> dict:
    """Return cache statistics for diagnostics."""
    try:
        con  = _conn()
        now  = time.time()
        total  = con.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        active = con.execute(
            "SELECT COUNT(*) FROM search_cache WHERE expires_at > ?", (now,)
        ).fetchone()[0]
        expired = total - active
        by_src = con.execute(
            "SELECT source, COUNT(*) FROM search_cache WHERE expires_at > ? GROUP BY source",
            (now,)
        ).fetchall()
        con.close()
        return {
            "total": total,
            "active": active,
            "expired": expired,
            "by_source": dict(by_src),
        }
    except Exception:
        return {}
