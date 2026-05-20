"""
Shared RAG context helper — Phases 3, 4, 7.

2-tier lookup — fast, no blocking API calls:

  Tier 1 — Session state rag_strategy_{case_id}
            Phase 2 ran the full pipeline → reuse at zero cost.

  Tier 2 — FTS5 direct SQLite search  ← ALWAYS works
            Pure BM25 on itat_precedents. No ChromaDB, no API, no network.
            Returns seeded SC/HC cases + any ingested judgments instantly.

The full RAGPipeline (slow, API-dependent) is intentionally NOT run here —
that belongs to Phase 2's Evidence Builder button only.
"""

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Public entry point ────────────────────────────────────────────────────────

def get_grounded_context(case_id: int, sections: list[str]) -> dict:
    """
    Return RAG-grounded precedents ready for prompt injection.
    Always returns something — falls back to FTS5 if pipeline unavailable.

    Keys:
        count           int  — number of cases found
        cases           list[RetrievedCase]
        citations_block str  — all cases formatted  (Phase 3 submissions)
        assessee_block  str  — assessee-won cases   (Phase 3/4 our arguments)
        revenue_block   str  — revenue-won cases    (Phase 4 DR simulation)
        top3_block      str  — top 3 only           (Phase 7 battle card)
        cbdt_block      str  — CBDT circulars
        source          str  — where cases came from (for debug)
    """
    import streamlit as st

    cases: list = []
    source = ""

    # ── Tier 1: reuse Phase 2 session-state result (free) ────────────────────
    strategy = st.session_state.get(f"rag_strategy_{case_id}")
    if strategy is not None:
        cases = getattr(strategy, "retrieved_cases", []) or []
        if cases:
            source = f"Phase 2 RAG cache"

    # ── Tier 2: FTS5 direct SQLite search (fast, no API calls) ───────────────
    if not cases:
        cases = _fts_fallback(case_id, sections)
        if cases:
            source = f"FTS5 precedent search"

    if not cases:
        return _empty()

    # ── Format ────────────────────────────────────────────────────────────────
    assessee = [c for c in cases if     getattr(c, "win_for_assessee", True)]
    revenue  = [c for c in cases if not getattr(c, "win_for_assessee", True)]

    return {
        "count":            len(cases),
        "cases":            cases,
        "citations_block":  _fmt_block(cases[:12]),
        "assessee_block":   _fmt_block(assessee[:8]),
        "revenue_block":    _fmt_block(revenue[:5]),
        "top3_block":       _fmt_block(assessee[:3]),
        "cbdt_block":       _get_cbdt(sections, _ao_allegations(case_id)),
        "source":           source,
    }


# ── Tier 2: FTS5 fallback — always works ─────────────────────────────────────

def _fts_fallback(case_id: int, sections: list[str]) -> list:
    """
    Direct SQLite FTS5 search on itat_precedents.
    Works with the 7 seeded SC/HC cases + any ingested .txt judgments.
    No ChromaDB, no API, no embeddings needed.
    """
    try:
        from ai.rag.fts    import FTSIndex
        from ai.rag.models import RetrievedCase, CourtType

        allegations = _ao_allegations(case_id)
        query = allegations if allegations else " ".join(sections)

        fts  = FTSIndex()
        rows = fts.search(query, top_k=15, sections=sections or None)

        # Also search by section alone if main query gave few results
        if len(rows) < 5 and sections:
            for sec in sections[:3]:
                extra = fts.search(sec, top_k=10, sections=[sec])
                seen  = {r.get("id") for r in rows}
                rows += [r for r in extra if r.get("id") not in seen]

        cases = []
        for r in rows:
            try:
                ct_raw = str(r.get("court_type") or "ITAT").upper()
                if "SC" in ct_raw or "SUPREME" in ct_raw:
                    ct = CourtType.SC
                elif "HC" in ct_raw or "HIGH" in ct_raw:
                    ct = CourtType.HC
                else:
                    ct = CourtType.ITAT

                cases.append(RetrievedCase(
                    db_id            = int(r.get("id") or 0),
                    citation         = r.get("citation") or r.get("case_citation") or "",
                    court_type       = ct,
                    year             = int(r.get("year") or 0),
                    section          = r.get("section") or "",
                    key_ratio        = r.get("key_ratio") or "",
                    facts_summary    = r.get("facts_summary") or "",
                    url              = r.get("ik_url") or r.get("url") or "",
                    win_for_assessee = bool(int(r.get("win_for_assessee") or 1)),
                    rrf_score        = float(abs(r.get("bm25_score") or 0.5)),
                    final_score      = float(abs(r.get("bm25_score") or 0.5)),
                ))
            except Exception:
                continue

        return cases
    except Exception:
        return []


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_block(cases: list) -> str:
    """Format a list of RetrievedCase into numbered citation-ready text."""
    if not cases:
        return ""
    lines = []
    for i, c in enumerate(cases, 1):
        cit   = getattr(c, "citation", "") or ""
        ratio = (getattr(c, "key_ratio", "") or "")[:200]
        court = str(getattr(c, "court_type", "") or "")
        year  = str(getattr(c, "year", "") or "")
        loc   = f"({court}, {year})" if (court or year) else ""
        lines.append(f"{i}. {cit} {loc}\n   Ratio: {ratio}")
    return "\n\n".join(lines)


def _fmt_inline(cases: list) -> str:
    """One-liner per case — for chits and battle cards."""
    return "\n".join(
        f"• {getattr(c,'citation','')} — {(getattr(c,'key_ratio','') or '')[:100]}"
        for c in cases
    )


# ── CBDT circulars — direct SQL, no ChromaDB ─────────────────────────────────

def _get_cbdt(sections: list[str], query: str) -> str:
    """
    Query cbdt_circulars table directly via SQLite — no EmbeddingService,
    no HybridRetriever, no ChromaDB init required.
    Scores by section overlap + keyword hits.
    """
    try:
        import sqlite3, json
        import config

        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()
        cur.execute("SELECT id, type, number, subject, summary, key_para, favour, sections FROM cbdt_circulars")
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return ""

        query_words = set((query or "").lower().split())
        sec_set     = {s.lower() for s in sections}

        scored = []
        for r in rows:
            score = 0
            try:
                circ_secs = json.loads(r["sections"] or "[]")
            except Exception:
                circ_secs = []

            # Section overlap
            for cs in circ_secs:
                if str(cs).lower() in sec_set:
                    score += 3

            # Keyword overlap in subject + key_para
            text = f"{r['subject']} {r['key_para']}".lower()
            score += sum(1 for w in query_words if len(w) > 3 and w in text)

            if score > 0:
                scored.append((score, r))

        scored.sort(key=lambda x: -x[0])
        top = scored[:5]

        if not top:
            # Fallback: return first 3 regardless of score
            top = [(0, r) for r in rows[:3]]

        lines = []
        for _, r in top:
            favour = {"assessee": "✅", "revenue": "❌"}.get(r["favour"] or "", "⚖️")
            lines.append(
                f"{favour} Circular {r['number']} ({r['type']}) — {r['subject'][:80]}\n"
                f"   Key para: {(r['key_para'] or '')[:150]}"
            )
        return "\n\n".join(lines)

    except Exception:
        return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ao_allegations(case_id: int) -> str:
    """AO allegations: session state first → DB fallback."""
    try:
        import streamlit as st
        val = st.session_state.get(f"ao_allegations_{case_id}", "")
        if not val:
            from database import queries
            val = queries.get_ao_context(case_id).get("ao_allegations", "")
        return val or ""
    except Exception:
        return ""


def _empty() -> dict:
    return {
        "count": 0, "cases": [],
        "citations_block": "", "assessee_block": "",
        "revenue_block":   "", "top3_block":     "",
        "cbdt_block":      "", "source":         "none",
    }
