"""
Shared RAG context helper — Phases 3, 4, 7.

Single source of truth for grounded precedents across all downstream phases.

Priority:
  1. Session state rag_strategy_{case_id}  — Phase 2 already ran the full pipeline;
     reuse those results at zero cost.
  2. Fresh pipeline run — if the CA jumps straight to Phase 3/4/7 without Phase 2.

Returns pre-formatted prompt blocks so each phase only needs one function call
before its LLM generation.
"""

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Public entry point ────────────────────────────────────────────────────────

def get_grounded_context(case_id: int, sections: list[str]) -> dict:
    """
    Return RAG-grounded precedents ready for prompt injection.

    Returns:
        count           int  — number of cases found
        cases           list[RetrievedCase]
        citations_block str  — all cases formatted  (Phase 3 submissions)
        assessee_block  str  — assessee-won cases   (Phase 3/4 our arguments)
        revenue_block   str  — revenue-won cases    (Phase 4 DR simulation)
        top3_block      str  — top 3 only           (Phase 7 battle card)
        cbdt_block      str  — CBDT circulars       (Phase 3/7)
    """
    import streamlit as st

    cases: list = []

    # ── Priority 1: reuse Phase 2 strategy already in session state ───────────
    strategy = st.session_state.get(f"rag_strategy_{case_id}")
    if strategy is not None:
        cases = getattr(strategy, "retrieved_cases", []) or []

    # ── Priority 2: fresh pipeline run ────────────────────────────────────────
    if not cases:
        cases = _run_pipeline(case_id, sections)

    if not cases:
        return _empty()

    # ── Format ────────────────────────────────────────────────────────────────
    assessee = [c for c in cases if getattr(c, "win_for_assessee", True) is not False]
    revenue  = [c for c in cases if getattr(c, "win_for_assessee", True) is     False]

    return {
        "count":            len(cases),
        "cases":            cases,
        "citations_block":  _fmt_block(cases[:12]),
        "assessee_block":   _fmt_block(assessee[:8]),
        "revenue_block":    _fmt_block(revenue[:5]),
        "top3_block":       _fmt_block(assessee[:3]),
        "cbdt_block":       _get_cbdt(sections, _ao_allegations(case_id)),
    }


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_block(cases: list) -> str:
    """Format a list of RetrievedCase into numbered, citation-ready text."""
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


# ── Pipeline runner ───────────────────────────────────────────────────────────

def _run_pipeline(case_id: int, sections: list[str]) -> list:
    """Build a fresh CaseQuery and run the RAGPipeline."""
    try:
        from ai.rag.pipeline import RAGPipeline
        from ai.rag.models   import CaseQuery
        from database        import queries

        case = queries.get_case(case_id)
        ctx  = queries.get_ao_context(case_id)

        query = CaseQuery(
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

        strategy = RAGPipeline().build(query)
        return getattr(strategy, "retrieved_cases", []) or []

    except Exception:
        return []


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
    """AO allegations from session state → DB fallback."""
    try:
        import streamlit as st
        val = st.session_state.get(f"ao_allegations_{case_id}", "")
        if not val:
            from database import queries
            val = queries.get_ao_context(case_id).get("ao_allegations", "")
        return val
    except Exception:
        return ""


def _empty() -> dict:
    return {
        "count": 0, "cases": [],
        "citations_block": "", "assessee_block": "",
        "revenue_block": "", "top3_block": "", "cbdt_block": "",
    }
