"""
HybridRetriever — vector search + FTS5 + Reciprocal Rank Fusion.

Pipeline:
  1. Embed query across 3 ChromaDB collections (facts, holding, docs)
  2. FTS5 keyword search with legal term expansion
  3. RRF: fuse all 4 ranked lists into one score
  4. Load full case rows, apply authority + recency boosts
  5. Return top_k typed RetrievedCase objects
"""

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ai.rag.models    import RetrievedCase, CourtType, CaseQuery
from ai.rag.embedder  import EmbeddingService, embed_query
from ai.rag.fts       import FTSIndex

_RRF_K = 60   # standard RRF constant — higher = gentler rank difference


class HybridRetriever:

    def __init__(self, embedder: EmbeddingService, fts: FTSIndex):
        self._embedder = embedder
        self._fts      = fts

    # ── Public ────────────────────────────────────────────────────────────────

    def retrieve(self, query: CaseQuery,
                 expanded_sections: list[str],
                 top_k: int = 25) -> list[RetrievedCase]:
        """
        Full hybrid retrieval for a CaseQuery.

        Args:
            query             — CaseQuery with client facts + sections
            expanded_sections — sections expanded by section_graph.expand()
            top_k             — max cases to return

        Returns list[RetrievedCase] sorted by final_score descending.
        """
        search_text = query.search_text()
        q_embedding  = embed_query(search_text)

        # ── Vector search: 3 collections ─────────────────────────────────────
        vec_facts   = self._embedder.search(
            EmbeddingService.COLLECTION_FACTS,   q_embedding,
            top_k=top_k * 2, section_filter=expanded_sections,
        )
        vec_holding = self._embedder.search(
            EmbeddingService.COLLECTION_HOLDING, q_embedding,
            top_k=top_k * 2, section_filter=expanded_sections,
        )
        vec_docs    = self._embedder.search(
            EmbeddingService.COLLECTION_DOCS,    q_embedding,
            top_k=top_k * 2, section_filter=expanded_sections,
        )

        # ── FTS5 keyword search ───────────────────────────────────────────────
        fts_query   = self._build_fts_query(query, expanded_sections)
        fts_results = self._fts.search(
            fts_query,
            top_k=top_k * 2,
            sections=expanded_sections,
        )
        # Also run adversarial query — what Revenue argues
        adv_query   = self._adversarial_query(query)
        adv_results = self._fts.search(
            adv_query,
            top_k=top_k,
            sections=expanded_sections,
        )

        # ── RRF: combine all 5 ranked lists ──────────────────────────────────
        rrf_scores = self._rrf([
            [r["id"]    for r in vec_facts],
            [r["id"]    for r in vec_holding],
            [r["id"]    for r in vec_docs],
            [r["id"]    for r in fts_results],
            [r["id"]    for r in adv_results],
        ])

        # ── Load full case rows + build typed objects ─────────────────────────
        top_ids      = sorted(rrf_scores, key=lambda x: -rrf_scores[x])[:top_k]
        id_to_fts    = {r["id"]: i for i, r in enumerate(fts_results)}
        id_to_vec    = {r["id"]: r["score"] for r in
                        vec_facts + vec_holding + vec_docs}

        cases = self._load_cases(top_ids)

        results: list[RetrievedCase] = []
        for case in cases:
            db_id = case["id"]
            rc    = RetrievedCase(
                db_id         = db_id,
                citation      = case.get("citation", ""),
                court_type    = _parse_court(case.get("court_type", "")),
                year          = int(case.get("year") or 0),
                section       = case.get("section", ""),
                key_ratio     = case.get("key_ratio", ""),
                facts_summary = case.get("facts_summary", ""),
                url           = case.get("url", ""),
                vector_score  = id_to_vec.get(db_id, 0.0),
                fts_rank      = id_to_fts.get(db_id, 9999),
                rrf_score     = rrf_scores.get(db_id, 0.0),
            )
            rc.apply_boosts()
            results.append(rc)

        results.sort(key=lambda r: -r.final_score)
        return results

    # ── RRF ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _rrf(ranked_lists: list[list[int]]) -> dict[int, float]:
        """
        Reciprocal Rank Fusion across multiple ranked id lists.
        Score(d) = Σ  1 / (k + rank_i(d))
        """
        scores: dict[int, float] = {}
        for ranked in ranked_lists:
            for rank, doc_id in enumerate(ranked, start=1):
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank)
        return scores

    # ── Query building ────────────────────────────────────────────────────────

    @staticmethod
    def _build_fts_query(query: CaseQuery, sections: list[str]) -> str:
        """
        Combine client facts + section names + legal keywords.
        Keeps most specific terms that FTS5 can match exactly.
        """
        parts = [query.client_facts[:300]]
        parts += sections[:6]
        # Key legal phrases that are high-signal in ITAT judgments
        parts += ["penalty deleted", "reasonable cause", "genuine transaction",
                  "assessee", "ITAT"]
        return " ".join(parts)

    @staticmethod
    def _adversarial_query(query: CaseQuery) -> str:
        """
        Build a query that finds Revenue-side cases.
        Used to understand what the other side will argue.
        """
        sections_str = " ".join(query.sections)
        return (
            f"{sections_str} penalty upheld addition confirmed "
            f"burden of proof not discharged assessee failed"
        )

    # ── DB loader ─────────────────────────────────────────────────────────────

    @staticmethod
    def _load_cases(ids: list[int]) -> list[dict]:
        import sqlite3
        import config

        if not ids:
            return []

        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()

        placeholders = ",".join("?" for _ in ids)
        cur.execute(f"""
            SELECT id,
                   case_citation AS citation,
                   court_type,
                   COALESCE(year, 0) AS year,
                   section,
                   COALESCE(key_ratio, '')     AS key_ratio,
                   COALESCE(facts_summary, '') AS facts_summary,
                   COALESCE(ik_url, '')        AS url
            FROM   itat_precedents
            WHERE  id IN ({placeholders})
        """, ids)

        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        # Preserve the RRF ordering
        id_order = {id_: i for i, id_ in enumerate(ids)}
        rows.sort(key=lambda r: id_order.get(r["id"], 9999))
        return rows


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_court(court_str: str) -> CourtType:
    s = (court_str or "").upper()
    if s == "SC":
        return CourtType.SC
    if s == "HC":
        return CourtType.HC
    if s == "ITAT":
        return CourtType.ITAT
    return CourtType.OTHER
