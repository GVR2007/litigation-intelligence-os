"""
Shared RAG context helper — Phases 3, 4, 7.

3-tier fallback so precedents are ALWAYS returned:

  Tier 1 — Session state (rag_strategy_{case_id})
            Phase 2 already ran the full pipeline → zero extra cost.

  Tier 2 — Full RAGPipeline
            Used when jumping straight to Phase 3/4/7 without Phase 2.
            Requires ChromaDB to be indexed. Falls through on failure.

  Tier 3 — FTS5 direct search  ← ALWAYS works
            Pure SQLite BM25 search on itat_precedents table.
            Works with only the 7 seeded SC/HC cases or any ingested judgments.
            No ChromaDB, no API key, no network needed.
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

    # ── Tier 1: reuse Phase 2 session-state result ────────────────────────────
    strategy = st.session_state.get(f"rag_strategy_{case_id}")
    if strategy is not None:
        cases = getattr(strategy, "retrieved_cases", []) or []
        if cases:
            source = f"Phase 2 RAG cache ({len(cases)} cases)"

    # ── Tier 2: full RAG pipeline ─────────────────────────────────────────────
    if not cases:
        cases = _run_full_pipeline(case_id, sections)
        if cases:
            source = f"RAG pipeline ({len(cases)} cases)"

    # ── Tier 3: FTS5 direct search — always works ────────────────────────────
    if not cases:
        cases = _fts_fallback(case_id, sections)
        if cases:
            source = f"FTS5 search ({len(cases)} cases)"

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


# ── Tier 2: full RAG pipeline ─────────────────────────────────────────────────

def _run_full_pipeline(case_id: int, sections: list[str]) -> list:
    """Full hybrid RAG — requires ChromaDB. Silent fail → Tier 3."""
    try:
        from ai.rag.pipeline import RAGPipeline
        from ai.rag.models   import CaseQuery
        from database        import queries

        case = queries.get_case(case_id)
        ctx  = queries.get_ao_context(case_id)

        q = CaseQuery(
            case_id             = case_id,
            sections            = sections,
            client_facts        = case.get("notes", "") or "",
            ao_text             = ctx.get("ao_allegations", ""),
            ao_allegations      = ctx.get("ao_allegations", ""),
            ao_rejection_reason = ctx.get("ao_rejection_reason", ""),
            demand_amount       = float(case.get("demand_amount") or 0),
            case_name           = case.get("case_name", ""),
            assessment_year     = case.get("assessment_year", ""),
        )
        strategy = RAGPipeline().build(q)
        return getattr(strategy, "retrieved_cases", []) or []
    except Exception:
        return []


# ── Tier 3: FTS5 fallback — always works ─────────────────────────────────────

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


# ── CBDT circulars ────────────────────────────────────────────────────────────

def _get_cbdt(sections: list[str], query: str) -> str:
    try:
        from ai.rag.retriever import HybridRetriever
        from ai.rag.embedder  import EmbeddingService
        from ai.rag.fts       import FTSIndex

        retriever = HybridRetriever(EmbeddingService(), FTSIndex())
        circulars = retriever.retrieve_cbdt(
            query or " ".join(sections), sections, top_k=5
        )
        if not circulars:
            return ""
        return "\n".join(
            f"• {getattr(c,'citation','')} — {(getattr(c,'key_ratio','') or '')[:150]}"
            for c in circulars
        )
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
