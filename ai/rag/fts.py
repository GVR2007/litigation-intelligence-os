"""
FTSIndex — SQLite FTS5 full-text search over itat_precedents.

Handles:
  - creating the FTS5 virtual table (once, idempotent)
  - rebuilding the index when new cases are added
  - BM25-ranked search returning structured results
"""

from __future__ import annotations
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

_FTS_TABLE = "itat_fts"


class FTSIndex:

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or config.DB_PATH
        self._ensure_index()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _ensure_index(self) -> None:
        """
        Create FTS5 virtual table if it doesn't exist.
        Uses standalone mode (stores own content) — simpler and more reliable
        than external content mode.  Idempotent.
        """
        conn = self._conn()
        cur  = conn.cursor()

        # Standalone FTS5 — stores all text itself, no content table dependency
        cur.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE}
            USING fts5(
                db_id    UNINDEXED,
                case_citation,
                key_ratio,
                facts_summary,
                tokenize = 'porter ascii'
            )
        """)

        # Check if populated
        cur.execute(f"SELECT COUNT(*) FROM {_FTS_TABLE}")
        count = cur.fetchone()[0]

        if count == 0:
            cur.execute(f"""
                INSERT INTO {_FTS_TABLE}(db_id, case_citation, key_ratio, facts_summary)
                SELECT id,
                       COALESCE(case_citation, ''),
                       COALESCE(key_ratio, ''),
                       COALESCE(facts_summary, '')
                FROM   itat_precedents
                WHERE  verified IN (1, 2)
            """)

        conn.commit()
        conn.close()

    def rebuild(self) -> None:
        """
        Full rebuild: drop and recreate FTS5 table from current DB state.
        Call this after a large harvest.
        """
        conn = self._conn()
        cur  = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {_FTS_TABLE}")
        conn.commit()
        conn.close()
        self._ensure_index()

    def sync_new_cases(self) -> int:
        """
        Add any new rows in itat_precedents not yet in FTS5.
        Returns count of newly added rows.
        """
        conn = self._conn()
        cur  = conn.cursor()

        # Get set of already-indexed db_ids
        cur.execute(f"SELECT db_id FROM {_FTS_TABLE}")
        indexed_ids = {row[0] for row in cur.fetchall()}

        cur.execute("""
            SELECT id, COALESCE(case_citation,''),
                   COALESCE(key_ratio,''), COALESCE(facts_summary,'')
            FROM   itat_precedents
            WHERE  verified IN (1, 2)
        """)
        rows = cur.fetchall()

        new_rows = [r for r in rows if r[0] not in indexed_ids]
        if new_rows:
            cur.executemany(
                f"INSERT INTO {_FTS_TABLE}(db_id, case_citation, key_ratio, facts_summary)"
                " VALUES (?, ?, ?, ?)",
                new_rows,
            )

        conn.commit()
        conn.close()
        return len(new_rows)

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 25,
               sections: list[str] | None = None) -> list[dict]:
        """
        BM25-ranked full-text search.

        Args:
            query    — natural language query
            top_k    — max results to return
            sections — optional list of section strings to filter

        Returns list of dicts with keys:
            id, citation, court_type, year, section,
            key_ratio, facts_summary, url, bm25_score
        """
        safe_query = self._sanitize(query)
        if not safe_query:
            return []

        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()

        if sections:
            placeholders = ",".join("?" for _ in sections)
            sql = f"""
                SELECT
                    p.id,
                    p.case_citation  AS citation,
                    p.court_type,
                    COALESCE(p.year, 0) AS year,
                    p.section,
                    p.key_ratio,
                    p.facts_summary,
                    COALESCE(p.ik_url, '') AS url,
                    bm25({_FTS_TABLE})    AS bm25_score
                FROM   {_FTS_TABLE}
                JOIN   itat_precedents p ON p.id = CAST({_FTS_TABLE}.db_id AS INTEGER)
                WHERE  {_FTS_TABLE} MATCH ?
                  AND  p.verified IN (1, 2)
                  AND  p.section  IN ({placeholders})
                ORDER  BY bm25_score
                LIMIT  ?
            """
            params = [safe_query] + sections + [top_k]
        else:
            sql = f"""
                SELECT
                    p.id,
                    p.case_citation  AS citation,
                    p.court_type,
                    COALESCE(p.year, 0) AS year,
                    p.section,
                    p.key_ratio,
                    p.facts_summary,
                    COALESCE(p.ik_url, '') AS url,
                    bm25({_FTS_TABLE})    AS bm25_score
                FROM   {_FTS_TABLE}
                JOIN   itat_precedents p ON p.id = CAST({_FTS_TABLE}.db_id AS INTEGER)
                WHERE  {_FTS_TABLE} MATCH ?
                  AND  p.verified IN (1, 2)
                ORDER  BY bm25_score
                LIMIT  ?
            """
            params = [safe_query, top_k]

        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    @staticmethod
    def _sanitize(query: str) -> str:
        """
        Convert a natural language query to FTS5 MATCH syntax.
        Strips ALL characters that are invalid in FTS5 MATCH expressions.

        FTS5 MATCH only accepts: alphanumerics, spaces, and a small set
        of operators (AND/OR/NOT). Commas, colons, semicolons, brackets,
        quotes etc. all cause "fts5: syntax error near X".
        """
        import re

        # Step 1: replace all non-alphanumeric, non-space characters with space.
        # This catches commas (the main culprit), semicolons, colons, brackets,
        # quotes, backslashes, percent signs — everything FTS5 rejects.
        cleaned = re.sub(r"[^\w\s]", " ", query)

        # Step 2: strip literal AND/OR/NOT — we build our own OR chain below
        cleaned = re.sub(r"\b(AND|OR|NOT)\b", " ", cleaned, flags=re.IGNORECASE)

        # Step 3: collapse whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if not cleaned:
            return ""

        # Step 4: keep tokens with 3+ chars — filter noise
        tokens = [t for t in cleaned.split() if len(t) >= 3]
        if not tokens:
            return ""

        # Step 5: deduplicate while preserving order
        seen: set = set()
        unique = []
        for t in tokens:
            tl = t.lower()
            if tl not in seen:
                seen.add(tl)
                unique.append(t)

        # OR-chain so BM25 ranks by how many terms match (not requiring all).
        # Cap at 20 tokens — very long queries slow FTS5 down noticeably.
        return " OR ".join(unique[:20])
