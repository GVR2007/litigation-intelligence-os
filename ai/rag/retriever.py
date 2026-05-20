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
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ai.rag.models    import RetrievedCase, CourtType, CaseQuery
from ai.rag.embedder  import EmbeddingService, embed_query
from ai.rag.fts       import FTSIndex

_RRF_K = 60   # standard RRF constant — higher = gentler rank difference


def _cosine_sim(a: list, b: list) -> float:
    """Cosine similarity between two float vectors (numpy if available, else pure Python)."""
    try:
        import numpy as np
        va = np.array(a, dtype=float)
        vb = np.array(b, dtype=float)
        denom = np.linalg.norm(va) * np.linalg.norm(vb)
        return float(np.dot(va, vb) / denom) if denom > 0 else 0.0
    except Exception:
        dot   = sum(x * y for x, y in zip(a, b))
        mag_a = sum(x ** 2 for x in a) ** 0.5
        mag_b = sum(x ** 2 for x in b) ** 0.5
        return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


class HybridRetriever:

    def __init__(self, embedder: EmbeddingService, fts: FTSIndex):
        self._embedder = embedder
        self._fts      = fts

    # ── Public ────────────────────────────────────────────────────────────────

    def retrieve(self, query: CaseQuery,
                 expanded_sections: list[str],
                 top_k: int = 25,
                 web_anchored_terms: list[str] | None = None) -> list[RetrievedCase]:
        """
        Full hybrid retrieval for a CaseQuery.

        Args:
            query               — CaseQuery with client facts + sections
            expanded_sections   — sections expanded by section_graph.expand()
            top_k               — max cases to return
            web_anchored_terms  — real legal terms extracted from live IK results
                                  (injected into FTS query for better vocabulary match)

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
        fts_query   = self._build_fts_query(
            query, expanded_sections, web_anchored_terms or []
        )
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
                db_id              = db_id,
                citation           = case.get("citation", ""),
                court_type         = _parse_court(case.get("court_type", "")),
                year               = int(case.get("year") or 0),
                section            = case.get("section", ""),
                key_ratio          = case.get("key_ratio", ""),
                facts_summary      = case.get("facts_summary", ""),
                url                = case.get("url", ""),
                win_for_assessee   = bool(case.get("win_for_assessee", 1)),
                documents_accepted = case.get("documents_accepted", ""),
                vector_score       = id_to_vec.get(db_id, 0.0),
                fts_rank           = id_to_fts.get(db_id, 9999),
                rrf_score          = rrf_scores.get(db_id, 0.0),
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
    def _build_fts_query(query: CaseQuery, sections: list[str],
                         web_anchored_terms: list[str] | None = None) -> str:
        """
        Build FTS5 query from AO's own language + web-anchored legal terms.

        Signal priority:
          1. AO's exact allegation language  — highest signal: same vocabulary
             appears in winning ITAT judgments because both use Indian tax law terms.
          2. AO rejection reason             — find cases that overcame this argument.
          3. Web-anchored terms              — real legal vocabulary extracted from
             live IK search results; grounded in actual judgments, not AI-generated.
          4. Client facts                    — broader factual context.
          5. Section anchors                 — FTS fallback anchor.
        """
        parts = []
        # 1. AO's exact language (primary signal)
        if query.ao_allegations:
            parts.append(query.ao_allegations[:300])
        if query.ao_rejection_reason:
            parts.append(query.ao_rejection_reason[:150])
        # 2. Web-anchored terms from live IK results (real legal vocabulary)
        if web_anchored_terms:
            parts.append(" ".join(web_anchored_terms[:6]))
        # 3. Client facts for additional context
        if query.client_facts:
            parts.append(query.client_facts[:200])
        # 4. Section anchors
        parts += sections[:6]
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
                   COALESCE(year, 0)               AS year,
                   section,
                   COALESCE(key_ratio, '')          AS key_ratio,
                   COALESCE(facts_summary, '')      AS facts_summary,
                   COALESCE(ik_url, '')             AS url,
                   COALESCE(documents_accepted, '') AS documents_accepted,
                   COALESCE(win_for_assessee, 1)    AS win_for_assessee
            FROM   itat_precedents
            WHERE  id IN ({placeholders})
        """, ids)

        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        # Preserve the RRF ordering
        id_order = {id_: i for i, id_ in enumerate(ids)}
        rows.sort(key=lambda r: id_order.get(r["id"], 9999))
        return rows

    # ── JIT Vectorization ─────────────────────────────────────────────────────

    def jit_rank(self, ik_results: list[dict],
                 query: CaseQuery, top_k: int = 10) -> list[RetrievedCase]:
        """
        JIT Vectorization: embed live IK results at query time using the
        same embedding model as the DB corpus.

        Each IK doc is embedded on-the-fly and ranked by cosine similarity
        to the query vector.  Returns top_k ephemeral RetrievedCase objects
        (db_id < 0 — never collide with real DB rows).
        """
        if not ik_results:
            return []

        q_text = query.search_text()
        q_vec  = embed_query(q_text)

        scored: list[tuple[float, dict, int]] = []
        for i, doc in enumerate(ik_results):
            text = " ".join(filter(None, [
                doc.get("title", ""),
                doc.get("headline", ""),
            ])).strip()
            if not text:
                continue
            try:
                doc_vec = embed_query(text)
                sim     = _cosine_sim(q_vec, doc_vec)
            except Exception:
                sim = 0.0
            scored.append((sim, doc, i))

        scored.sort(key=lambda x: -x[0])

        results: list[RetrievedCase] = []
        for sim, doc, i in scored[:top_k]:
            title = doc.get("title", "")

            year = 0
            m    = re.search(r'\b(19|20)\d{2}\b', title)
            if m:
                year = int(m.group(0))

            t_up = title.upper()
            if "(SC)" in t_up or "SUPREME COURT" in t_up:
                court = CourtType.SC
            elif any(hc in t_up for hc in
                     ["HIGH COURT", "(HC)", "(BOM)", "(DEL)", "(GUJ)",
                      "(MAD)", "(CAL)", "(ALL)", "(KER)", "(P&H)"]):
                court = CourtType.HC
            else:
                court = CourtType.ITAT

            rc = RetrievedCase(
                db_id            = -(i + 1),          # negative = ephemeral (JIT pool)
                citation         = title[:150],
                court_type       = court,
                year             = year,
                section          = "",
                key_ratio        = doc.get("headline", "")[:500],
                facts_summary    = doc.get("headline", "")[:300],
                url              = f"https://indiankanoon.org/doc/{doc.get('tid', '')}/",
                win_for_assessee = True,
                vector_score     = sim,
                rrf_score        = sim,
            )
            rc.final_score = sim * rc.authority_weight * rc.recency_weight
            results.append(rc)

        return results

    # ── CBDT Circular Retrieval ───────────────────────────────────────────────

    def retrieve_cbdt(self, query: CaseQuery,
                      sections: list[str], top_k: int = 5) -> list[RetrievedCase]:
        """
        Keyword search across cbdt_circulars using AO language + sections.

        Scoring:
          +1 per keyword hit in subject/summary
          +3 per section that exactly matches a section in the circular's
             sections JSON array (e.g. '["269SS","271D"]')

        Returns top_k RetrievedCase objects (db_id in -1000 range to avoid
        clash with JIT pool's -1…-N range).
        """
        import sqlite3
        import config as _config

        # Extract meaningful keywords from AO text (words longer than 4 chars)
        kw_raw = " ".join(filter(None, [
            (query.ao_allegations or "")[:200],
            (query.ao_rejection_reason or "")[:100],
        ])).split()
        keywords = list(dict.fromkeys(
            w.lower() for w in kw_raw if len(w) > 4
        ))[:8]

        if not keywords and not sections:
            return []

        try:
            conn = sqlite3.connect(_config.DB_PATH)
            conn.row_factory = sqlite3.Row
            cur  = conn.cursor()

            # Section match: sections column stores JSON e.g. '["269SS","271D"]'
            sec_clauses = [f'sections LIKE ?' for _ in sections[:4]]
            sec_params  = [f'%"{s}"%' for s in sections[:4]]

            # Keyword match across subject + summary
            kw_clauses  = [
                '(LOWER(subject) LIKE ? OR LOWER(summary) LIKE ?)'
                for _ in keywords
            ]
            kw_params   = [p for kw in keywords
                           for p in (f'%{kw}%', f'%{kw}%')]

            all_clauses = sec_clauses + kw_clauses
            all_params  = sec_params  + kw_params

            if not all_clauses:
                conn.close()
                return []

            where = " OR ".join(all_clauses)
            cur.execute(f"""
                SELECT id, type, number, date, subject,
                       sections, summary, key_para, favour
                FROM   cbdt_circulars
                WHERE  ({where})
                LIMIT  ?
            """, all_params + [top_k * 3])   # over-fetch, re-rank below

            rows = cur.fetchall()
            conn.close()
        except Exception:
            return []

        # Re-rank by relevance score
        def _score(row) -> float:
            text = " ".join(filter(None, [
                (row["subject"]  or "").lower(),
                (row["summary"]  or "").lower(),
                (row["sections"] or "").lower(),
            ]))
            s = sum(1.0 for kw in keywords if kw in text)
            for sec in sections:
                if f'"{sec}"' in (row["sections"] or ""):
                    s += 3.0       # section exact-match bonus
            return s

        scored_rows = sorted(rows, key=_score, reverse=True)[:top_k]

        results: list[RetrievedCase] = []
        for idx, row in enumerate(scored_rows):
            year = 0
            d    = row["date"] or ""
            if len(d) >= 4 and d[:4].isdigit():
                year = int(d[:4])

            favour   = (row["favour"] or "").lower()
            win_flag = favour not in ("revenue", "department")

            citation = (
                f"CBDT {row['type'] or 'Circular'} No.{row['number']} "
                f"dt.{row['date']}"
            )

            rc = RetrievedCase(
                db_id            = -(1000 + idx),   # -1000 range = CBDT pool
                citation         = citation,
                court_type       = CourtType.OTHER,
                year             = year,
                section          = row["sections"] or "",
                key_ratio        = row["summary"]   or "",
                facts_summary    = row["key_para"]  or "",
                url              = "",
                win_for_assessee = win_flag,
                vector_score     = 0.0,
                rrf_score        = max(0.1, 0.5 - idx * 0.05),
            )
            # CBDT circulars carry administrative authority — set a moderate base score
            rc.final_score = rc.rrf_score
            results.append(rc)

        return results

    # ── Cross-Pool RRF ────────────────────────────────────────────────────────

    @staticmethod
    def cross_pool_rrf(*pools: list[RetrievedCase],
                       k: int = 60,
                       top_k: int = 25) -> list[RetrievedCase]:
        """
        Cross-pool Reciprocal Rank Fusion across heterogeneous pools.

        Why cross-pool: Pool A (DB), Pool B (JIT IK), Pool C (CBDT) have no
        shared ID space. We deduplicate by citation[:60].lower() and use
        position-based RRF (same as within-pool RRF) across all pools.

        Deduplication: if the same citation appears in multiple pools, we
        keep the copy with the highest pre-fusion final_score and accumulate
        RRF scores from all pools it appeared in (so cross-pool agreement
        boosts the score).

        Args:
            *pools — any number of RetrievedCase ranked lists
            k      — RRF constant (default 60)
            top_k  — max items to return

        Returns list[RetrievedCase] sorted by fused final_score.
        """
        citation_to_case: dict[str, RetrievedCase] = {}
        rrf_acc:          dict[str, float]          = {}

        for pool in pools:
            for rank, case in enumerate(pool, start=1):
                key = (case.citation or "").lower()[:60].strip()
                if not key:
                    key = f"__id_{case.db_id}"

                score            = 1.0 / (k + rank)
                rrf_acc[key]     = rrf_acc.get(key, 0.0) + score

                # Keep the copy with the higher individual final_score
                if (key not in citation_to_case
                        or case.final_score > citation_to_case[key].final_score):
                    citation_to_case[key] = case

        # Sort by fused RRF score
        sorted_keys = sorted(rrf_acc, key=lambda ck: -rrf_acc[ck])[:top_k]

        results: list[RetrievedCase] = []
        for key in sorted_keys:
            case             = citation_to_case[key]
            case.rrf_score   = rrf_acc[key]
            case.final_score = (rrf_acc[key]
                                * case.authority_weight
                                * case.recency_weight)
            results.append(case)

        return results


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
