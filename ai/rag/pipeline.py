"""
RAGPipeline — single entry point for the full retrieval + synthesis pipeline.

Call:
    from ai.rag.pipeline import RAGPipeline
    strategy = RAGPipeline().build(query)

Internally orchestrates:
  1. Query enrichment — extract structured facts from client description
  2. HyDE — generate ideal matching judgment for better embedding search
  3. Section graph expansion — add defence/penalty related sections
  4. HybridRetriever — vector (3 collections) + FTS5 + RRF
  5. Reranker — Gemini cross-encoder scoring
  6. Citation chain — fetch SC authorities relied on in top cases
  7. Two-phase synthesis:
       Phase A — identify strongest legal arguments
       Phase B — extract required documents per argument
       Phase C — identify Revenue counter-arguments and rebuttals
"""

from __future__ import annotations
import json
import re
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

from ai.rag.models        import (CaseQuery, CaseStrategy, LegalArgument,
                                   RequiredDocument, CounterArgument,
                                   RetrievedCase, CourtType)
from ai.rag.section_graph import expand, get_context_note
from ai.rag.embedder      import EmbeddingService
from ai.rag.fts           import FTSIndex
from ai.rag.retriever     import HybridRetriever
from ai.ai_client         import AIClient
from ai.rag.reranker      import Reranker


_SYNTHESIS_SYSTEM = """You are a senior Indian Income Tax advocate with 20 years
of ITAT / High Court experience. You analyse case law and build litigation strategy.
Return only valid JSON when asked for JSON — no markdown, no commentary."""


class RAGPipeline:
    """
    Initialise once at module load; reuse across requests.
    """

    def __init__(self):
        self._embedder  = EmbeddingService()
        self._fts       = FTSIndex()
        self._retriever = HybridRetriever(self._embedder, self._fts)
        self._reranker  = Reranker()

    # ── Public ────────────────────────────────────────────────────────────────

    def build(self, query: CaseQuery,
              progress_cb=None) -> CaseStrategy:
        """
        Full pipeline. Single call. Returns complete CaseStrategy.

        Args:
            query       — CaseQuery with client facts, sections, AO text
            progress_cb — optional callable(str) for progress messages

        Returns:
            CaseStrategy — arguments, documents, counter-arguments, win probability
        """
        def log(msg: str):
            if progress_cb:
                progress_cb(msg)

        # ── 1. Enrich query ──────────────────────────────────────────────────
        log("🔍 Enriching query — extracting structured facts...")
        enriched = self._enrich_query(query)

        # ── 2. Live IK fetch (shared: web-anchor + JIT source) ──────────────
        log("🌐 Fetching live IK results for web-anchoring + JIT vectorization...")
        live_ik_results = self._fetch_live_ik(query)
        log(f"   {len(live_ik_results)} live result(s) fetched")

        # ── 3. Web-Anchored Query Expansion ──────────────────────────────────
        if live_ik_results:
            log("🔗 Web-anchoring query with real legal terms from IK results...")
            enriched = self._web_anchor_expansion(live_ik_results, enriched)
            anchored = enriched.get("web_anchored_terms", [])
            citations = enriched.get("web_anchored_citations", [])
            if anchored or citations:
                log(f"   Anchored terms: {anchored[:4]} | citations: {len(citations)}")

        # ── 4. HyDE — generate ideal judgment text ───────────────────────────
        log("📝 Generating hypothetical ideal judgment (HyDE)...")
        hyde_doc = self._generate_hyde(query, enriched)

        # Swap client_facts with HyDE text — preserve AO language fields
        hyde_query = CaseQuery(
            case_id             = query.case_id,
            sections            = query.sections,
            client_facts        = hyde_doc,
            ao_text             = query.ao_text,
            ao_allegations      = query.ao_allegations,
            ao_rejection_reason = query.ao_rejection_reason,
            demand_amount       = query.demand_amount,
            case_name           = query.case_name,
            assessment_year     = query.assessment_year,
        )

        # ── 5. Expand sections ───────────────────────────────────────────────
        log(f"🔗 Expanding sections: {query.sections} → related sections...")
        expanded_sections = expand(
            query.sections,
            include_defences=True,
            include_penalties=True,
        )
        log(f"   Expanded to: {expanded_sections}")

        # ── 6. Federated Retrieval (3 pools → cross-pool RRF) ────────────────
        log("🗄️  Pool A: hybrid DB retrieval (vector + FTS5 + RRF)...")
        pool_a = self._retriever.retrieve(
            hyde_query, expanded_sections, top_k=25,
            web_anchored_terms=enriched.get("web_anchored_terms", []),
        )
        log(f"   Pool A: {len(pool_a)} candidates")

        log("⚡ Pool B: JIT vectorizing live IK results...")
        pool_b = self._retriever.jit_rank(
            live_ik_results, hyde_query, top_k=10
        )
        log(f"   Pool B: {len(pool_b)} JIT-ranked IK result(s)")

        log("📜 Pool C: searching CBDT circulars...")
        pool_c = self._retriever.retrieve_cbdt(query, expanded_sections, top_k=5)
        log(f"   Pool C: {len(pool_c)} CBDT circular(s)")

        log("🔀 Cross-pool RRF — merging all three pools...")
        candidates = HybridRetriever.cross_pool_rrf(
            pool_a, pool_b, pool_c, top_k=30
        )
        log(f"   {len(candidates)} candidates after federated RRF")

        # ── 7. Rerank ────────────────────────────────────────────────────────
        if candidates:
            log("⚖️  Reranking with AI cross-encoder (OpenRouter)...")
            top_cases = self._reranker.rerank(candidates, query, top_k=12)
            log(f"   Top {len(top_cases)} cases after reranking")
        else:
            top_cases = []

        # ── 8. Agentic citation chain (3-hop bounded agent) ──────────────────
        if top_cases:
            log("🤖 Agentic citation chain (up to 3 hops)...")
            top_cases = self._agentic_citation_chain(top_cases, query, log)

        # ── 7. Two-phase synthesis ───────────────────────────────────────────
        log("🧠 Phase A — identifying strongest legal arguments...")
        arguments = self._synthesize_arguments(query, top_cases, enriched)

        log("📋 Phase B — extracting required documents per argument...")
        arguments = self._synthesize_documents(query, arguments, top_cases)

        log("⚔️  Phase C — building counter-argument strategy...")
        counter_args = self._synthesize_counters(query, top_cases, arguments)

        # ── 8. Win probability ───────────────────────────────────────────────
        win_prob = self._calculate_win_probability(top_cases, arguments)

        log(f"✅ Done — {len(arguments)} arguments, "
            f"{sum(len(a.documents) for a in arguments)} documents, "
            f"win probability: {win_prob:.0%}")

        return CaseStrategy(
            query             = query,
            arguments         = arguments,
            counter_arguments = counter_args,
            win_probability   = win_prob,
            retrieved_cases   = top_cases,
            hyde_document     = hyde_doc,
            expanded_sections = expanded_sections,
        )

    # ── Step 1: Query enrichment ──────────────────────────────────────────────

    def _enrich_query(self, query: CaseQuery) -> dict:
        """
        Extract structured legal facts from the client description.
        Returns dict with: fact_pattern, defences, keywords, transaction_type.
        """
        section_context = get_context_note(query.sections)

        # AO's language takes priority — it shares vocabulary with ITAT judgments
        ao_context = query.ao_allegations or (query.ao_text[:400] if query.ao_text else "")

        prompt = f"""Extract structured legal facts from this client situation.

SECTIONS: {', '.join(query.sections)}
SECTION CONTEXT: {section_context[:500]}
CLIENT FACTS: {query.client_facts}
AO ALLEGATION (exact language): {ao_context or 'Not provided'}
AO REJECTION REASON: {query.ao_rejection_reason or 'Not provided'}

Return JSON with exactly these keys:
{{
  "transaction_type": "e.g. cash loan / agricultural payment / family gift",
  "relationship":     "e.g. father-son / business partner / stranger",
  "setting":          "e.g. rural agricultural / urban business / emergency",
  "available_defences": ["list of legal defences available based on facts"],
  "fts_keywords":     ["5-8 specific legal keywords for full-text search"],
  "hyde_context":     "2-sentence description of what ideal matching judgment looks like"
}}"""
        raw = AIClient.call(_SYNTHESIS_SYSTEM, prompt,
                            temperature=0.05, max_tokens=512)
        return AIClient.parse_json(raw) or {}

    # ── Step 2: HyDE ─────────────────────────────────────────────────────────

    def _generate_hyde(self, query: CaseQuery, enriched: dict) -> str:
        """
        Generate a hypothetical ideal ITAT judgment that would perfectly
        match the client's situation. Used as the embedding query.
        """
        section_context = get_context_note(query.sections)
        hyde_ctx        = enriched.get("hyde_context", "")

        # Use AO's exact allegation as the fact pattern anchor — produces sharper HyDE
        ao_allegation = query.ao_allegations or ""
        ao_rejection  = query.ao_rejection_reason or ""

        prompt = f"""Write a 200-word summary of an ITAT/High Court judgment that would be
the IDEAL precedent for this client's situation.

CLIENT: {query.client_facts}
SECTIONS: {', '.join(query.sections)}
LEGAL CONTEXT: {section_context[:400]}
{f'AO ALLEGED: {ao_allegation[:300]}' if ao_allegation else ''}
{f'AO REJECTED EXPLANATION BECAUSE: {ao_rejection[:200]}' if ao_rejection else ''}
{f'ADDITIONAL CONTEXT: {hyde_ctx}' if hyde_ctx else ''}

Write as if summarising a real judgment. Include:
- The SAME type of AO allegation that was raised and defeated
- The SPECIFIC documents the assessee produced to counter it
- Why the tribunal deleted the addition / penalty
- The legal principle established

Write only the judgment summary — no introduction, no commentary."""
        hyde = AIClient.call(_SYNTHESIS_SYSTEM, prompt,
                             temperature=0.2, max_tokens=512)

        if hyde.startswith("[ERROR]"):
            return query.client_facts   # fallback to original
        return hyde

    # ── Step 2B: Live IK fetch (shared source for web-anchor + JIT) ─────────

    @staticmethod
    def _fetch_live_ik(query: CaseQuery, max_results: int = 15) -> list[dict]:
        """
        Single IK fetch using AO allegation language as query.
        Results are reused by both web-anchor expansion and JIT vectorization —
        so IK is called only once per pipeline run.
        """
        try:
            from ai.indian_kanoon import search_cases
            seed = (query.ao_allegations or query.ao_rejection_reason
                    or query.client_facts or "")
            if len(seed.split()) < 3:
                return []
            raw  = search_cases(seed[:200])
            docs = raw.get("docs", [])[:max_results]
            return [d for d in docs if d.get("tid")]
        except Exception:
            return []

    # ── Step 3: Web-Anchored Query Expansion ─────────────────────────────────

    @staticmethod
    def _web_anchor_expansion(ik_results: list[dict], enriched: dict) -> dict:
        """
        Extract real legal terms and case citations from live IK results.
        These ground the query in vocabulary that actually appears in ITAT judgments —
        not AI-generated synonyms.

        Adds to enriched:
          web_anchored_terms    — legal keywords found in IK headlines
          web_anchored_citations — case citations found in IK titles
          fts_keywords          — extended with anchored terms for FTS search
        """
        _HIGH_SIGNAL = [
            "identity", "creditworthiness", "genuineness", "reasonable cause",
            "burden of proof", "incriminating material", "contemporaneous",
            "unexplained", "cash credit", "penalty deleted", "addition deleted",
            "confirmation letter", "affidavit", "source of funds", "agricultural",
            "bank statement", "ITR filed", "lender", "creditor", "satisfaction note",
            "rule 6DD", "section 273B", "bona fide", "books of account",
        ]
        _CITATION_RE = re.compile(
            r'[A-Z][a-zA-Z .]+v\.?\s+[A-Z][a-zA-Z .]+\[?\d{4}\]?',
            re.IGNORECASE,
        )

        terms:     list[str] = []
        citations: list[str] = []

        for doc in ik_results:
            text = ((doc.get("headline") or "") + " " +
                    (doc.get("title") or "")).lower()

            for signal in _HIGH_SIGNAL:
                if signal in text and signal not in terms:
                    terms.append(signal)

            for m in _CITATION_RE.finditer(doc.get("title", "")):
                cit = m.group(0).strip()[:80]
                if cit not in citations:
                    citations.append(cit)

        enriched = dict(enriched)   # don't mutate caller's dict
        enriched["web_anchored_terms"]     = terms[:8]
        enriched["web_anchored_citations"] = citations[:4]

        # Extend fts_keywords so FTS query gets these real terms
        existing_kw = enriched.get("fts_keywords", [])
        enriched["fts_keywords"] = list(dict.fromkeys(existing_kw + terms[:4]))

        return enriched

    # ── Step 5B: Extract documents grounded in real cases ────────────────────

    @staticmethod
    def extract_docs_from_cases(
        cases: list[RetrievedCase],
        query: CaseQuery,
    ) -> list[dict]:
        """
        Pull evidence items directly from retrieved cases — no AI imagination.

        Sources in priority order:
        1. documents_accepted JSON field (populated during .txt ingest)
        2. key_ratio text — regex-mine document mentions
        3. facts_summary text — regex-mine document mentions

        Each item is grounded: it comes from a real case citation.
        Returns flat list of dicts compatible with add_evidence().
        """
        import re, json as _json

        # Patterns for document names mentioned in judgment text
        _DOC_RE = re.compile(
            r"\b(bank\s+(?:statement|passbook)|"
            r"(?:confirmation|affidavit|declaration)\s+(?:letter|from|of|by)[^,.]{0,40}|"
            r"(?:ITR|income.tax\s+return)\s+(?:of|filed\s+by)[^,.]{0,40}|"
            r"(?:ledger|cash\s+book|day\s+book|journal)[^,.]{0,30}|"
            r"(?:balance\s+sheet|profit\s+and\s+loss)[^,.]{0,20}|"
            r"(?:PAN\s+card|aadhar|identity\s+proof)[^,.]{0,20}|"
            r"sale\s+deed|gift\s+deed|loan\s+agreement|"
            r"(?:audit\s+report|Form\s+3C[BD])[^,.]{0,20}|"
            r"Form\s+(?:16|26AS|15CA|15CB)|"
            r"GSTR-\w+|GST\s+return|"
            r"valuation\s+report[^,.]{0,20}|"
            r"registered\s+(?:deed|agreement)[^,.]{0,20})",
            re.IGNORECASE,
        )

        seen:  set  = set()
        items: list = []

        for case in cases:
            if not case.win_for_assessee:
                continue  # skip Revenue-win cases for document extraction

            # Source 1: structured documents_accepted JSON
            raw_docs = getattr(case, "documents_accepted", "") or ""
            doc_names: list[str] = []
            if raw_docs:
                try:
                    parsed = _json.loads(raw_docs)
                    if isinstance(parsed, list):
                        doc_names = [str(d).strip() for d in parsed if d]
                except Exception:
                    pass

            # Source 2: mine key_ratio + facts_summary text
            for text in [case.key_ratio, case.facts_summary]:
                for m in _DOC_RE.finditer(text or ""):
                    doc = m.group(0).strip().rstrip(".,;")
                    if len(doc) > 8:
                        doc_names.append(doc)

            for doc in doc_names:
                key = doc.lower()[:50]
                if key in seen:
                    continue
                seen.add(key)

                # Find the relevant section for this document
                doc_section = case.section or (
                    query.sections[0] if query.sections else ""
                )

                items.append({
                    "section":          doc_section,
                    "document_name":    doc,
                    "win_boost":        min(30, 10 + case.final_score * 10),
                    "mandatory":        True,
                    "tribunal_verdict": "accepted",
                    "rejection_reason": "",
                    "accepted_in":      [case.citation],
                    "rejected_in":      [],
                    "acceptance_count": 1,
                    "why_it_matters":   case.key_ratio[:200] if case.key_ratio else "",
                    "how_to_obtain":    "Collect from client records / relevant authority",
                    "source":           "rag-case-grounded",
                    "counter_allegation": query.ao_allegations[:150] if query.ao_allegations else "",
                })

        return items

    # ── Step 6: Citation chain ────────────────────────────────────────────────

    # ── Step 8: Agentic citation chain (replaces _expand_citation_chain) ─────

    def _agentic_citation_chain(self, cases: list[RetrievedCase],
                                 query: CaseQuery,
                                 log) -> list[RetrievedCase]:
        """
        3-hop bounded agentic citation chain.

        Hop 1: Extract SC citations referenced inside top cases' key_ratio text.
        Hop 2: AI decides which citations are worth chasing (prevents runaway).
        Hop 3: Fetch AI-approved SC cases — local DB first, IK API fallback.

        Hard bounds: checks top 6 cases, fetches at most 3 new authorities.
        """
        existing: set[str] = {c.citation.lower() for c in cases}
        sc_refs:  list[str] = []

        # Hop 1 — mine SC citations from top-6 cases' key_ratio
        for case in cases[:6]:
            ref = self._extract_sc_citation(case.key_ratio)
            if ref and ref.lower() not in existing:
                sc_refs.append(ref)

        if not sc_refs:
            log("   No SC citations found in top cases — skipping chain")
            return cases

        log(f"   Hop 1: {len(sc_refs)} SC citation(s) detected: {sc_refs[:3]}")

        # Hop 2 — AI decides which are relevant enough to fetch
        decide_prompt = f"""You are reviewing ITAT case citations to decide which
Supreme Court authorities should be fetched for deeper analysis.

CLIENT SECTIONS: {', '.join(query.sections)}
CLIENT FACTS (brief): {(query.client_facts or '')[:200]}
AO ALLEGATION: {(query.ao_allegations or '')[:150]}

SC CITATIONS FOUND IN RETRIEVED CASES:
{chr(10).join(f'- {r}' for r in sc_refs[:5])}

Which citations directly address the sections and AO allegation above?
Return JSON only: {{"fetch": ["citation..."], "skip": ["citation..."]}}
Only put citations in "fetch" if they directly bear on the sections listed."""

        raw_decision = AIClient.call(_SYNTHESIS_SYSTEM, decide_prompt,
                                     temperature=0.0, max_tokens=256)
        decision     = AIClient.parse_json(raw_decision) or {}
        to_fetch: list[str] = decision.get("fetch", sc_refs[:2])  # fallback: first 2

        log(f"   Hop 2: agent approved {len(to_fetch)} citation(s) to fetch: {to_fetch[:3]}")

        # Hop 3 — fetch approved citations
        additions: list[RetrievedCase] = []
        for ref in to_fetch[:3]:   # hard cap — max 3 new authority cases
            if ref.lower() in existing:
                continue

            # Try local DB first (zero latency)
            sc_case = self._fetch_sc_case(ref)

            # IK API fallback if not in local DB
            if sc_case is None:
                sc_case = self._fetch_via_ik(ref)

            if sc_case and sc_case.citation.lower() not in existing:
                additions.append(sc_case)
                existing.add(sc_case.citation.lower())
                log(f"   Hop 3 ✓ {sc_case.citation[:60]}")

            time.sleep(0.3)   # polite rate limit

        log(f"   Citation chain complete — {len(additions)} new authority case(s) added")
        return cases + additions

    @staticmethod
    def _fetch_via_ik(citation: str) -> RetrievedCase | None:
        """
        Fetch a specific case from IndianKanoon by citation text (IK search fallback).
        Returns an ephemeral RetrievedCase (db_id < -2000) or None on failure.
        """
        try:
            from ai.indian_kanoon import search_cases
            from ai.rag.retriever import _parse_court

            results = search_cases(citation[:80])
            docs    = results.get("docs", [])
            if not docs:
                return None

            doc   = docs[0]
            title = doc.get("title", citation)

            year  = 0
            m     = re.search(r'\b(19|20)\d{2}\b', title)
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
                db_id            = -abs(hash(citation) % 10_000) - 2_000,
                citation         = title[:150],
                court_type       = court,
                year             = year,
                section          = "",
                key_ratio        = doc.get("headline", "")[:500],
                facts_summary    = doc.get("headline", "")[:300],
                url              = f"https://indiankanoon.org/doc/{doc.get('tid', '')}/",
                win_for_assessee = True,
                rerank_score     = 7.5,   # IK authority — decent default score
            )
            rc.apply_boosts()
            return rc
        except Exception:
            return None

    # ── Legacy (kept for reference — not called by build()) ──────────────────

    def _expand_citation_chain(self, cases: list[RetrievedCase]) -> list[RetrievedCase]:
        """
        Check if top cases cite a Supreme Court authority.
        If so, fetch that SC case and add it to the list (if not already present).
        Max 3 additional SC cases to avoid bloat.
        """
        existing_citations = {c.citation.lower() for c in cases}
        sc_additions       = []

        for case in cases[:5]:   # only check top 5
            sc_ref = self._extract_sc_citation(case.key_ratio)
            if not sc_ref:
                continue
            if sc_ref.lower() in existing_citations:
                continue
            sc_case = self._fetch_sc_case(sc_ref)
            if sc_case and sc_case.citation.lower() not in existing_citations:
                sc_additions.append(sc_case)
                existing_citations.add(sc_case.citation.lower())
            if len(sc_additions) >= 3:
                break
            time.sleep(0.3)

        return cases + sc_additions

    @staticmethod
    def _extract_sc_citation(text: str) -> str:
        """Extract first Supreme Court case citation from text."""
        if not text:
            return ""
        patterns = [
            r"([A-Z][a-zA-Z\s&.]+\s+vs?\.\s+[A-Z][a-zA-Z\s&.]+)\s*[\[(]SC",
            r"([A-Z][a-zA-Z\s&.]+\s+v\.\s+[A-Z][a-zA-Z\s&.]+)\s*[\[(]Supreme Court",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1).strip()[:100]
        return ""

    @staticmethod
    def _fetch_sc_case(citation: str) -> RetrievedCase | None:
        """Try to find this SC case in local DB or via IK API."""
        try:
            import sqlite3
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            cur  = conn.cursor()
            cur.execute("""
                SELECT id, case_citation, court_type, year, section,
                       key_ratio, facts_summary, ik_url
                FROM   itat_precedents
                WHERE  LOWER(case_citation) LIKE LOWER(?)
                  AND  court_type = 'SC'
                LIMIT  1
            """, (f"%{citation[:40]}%",))
            row = cur.fetchone()
            conn.close()

            if row:
                from ai.rag.retriever import _parse_court
                return RetrievedCase(
                    db_id         = row["id"],
                    citation      = row["case_citation"],
                    court_type    = _parse_court(row["court_type"]),
                    year          = int(row["year"] or 0),
                    section       = row["section"] or "",
                    key_ratio     = row["key_ratio"] or "",
                    facts_summary = row["facts_summary"] or "",
                    url           = row["ik_url"] or "",
                    rerank_score  = 8.0,   # SC authority — high score
                    final_score   = 12.0,  # boosted above ITAT cases
                )
        except Exception:
            pass
        return None

    # ── Step 7A: Argument synthesis ───────────────────────────────────────────

    def _synthesize_arguments(self, query: CaseQuery,
                               cases: list[RetrievedCase],
                               enriched: dict) -> list[LegalArgument]:
        """
        Phase A: Identify the 3 strongest legal arguments for this client
        based on the retrieved cases.
        """
        if not cases:
            return []

        cases_block = self._format_cases_for_prompt(cases[:10])
        defences    = enriched.get("available_defences", [])

        prompt = f"""CLIENT SITUATION:
Sections: {', '.join(query.sections)}
Facts: {query.client_facts}
Available defences identified: {', '.join(defences) if defences else 'analyse from cases'}

RETRIEVED CASES:
{cases_block}

TASK — Phase A:
Based ONLY on the retrieved cases above, identify the 3 strongest legal arguments
for the client. For each argument:

1. State the legal principle clearly
2. Name which retrieved cases support it
3. Estimate win rate (0.0 to 1.0) based on how many similar cases were decided in assessee's favour
4. Which section this argument is under

Return JSON array of exactly 3 objects:
[
  {{
    "rank": 1,
    "argument": "Clear statement of the legal argument",
    "win_rate": 0.78,
    "section": "269SS",
    "supporting_case_indices": [1, 3, 5]
  }},
  ...
]"""
        raw     = AIClient.call(_SYNTHESIS_SYSTEM, prompt,
                                temperature=0.05, max_tokens=1024)
        parsed  = AIClient.parse_json(raw)

        if not isinstance(parsed, list):
            return []

        arguments: list[LegalArgument] = []
        for obj in parsed:
            if not isinstance(obj, dict):
                continue

            # Attach supporting cases
            indices    = [int(i) - 1 for i in obj.get("supporting_case_indices", [])
                          if isinstance(i, (int, float))]
            supporting = [cases[i] for i in indices if 0 <= i < len(cases)]

            arguments.append(LegalArgument(
                rank        = int(obj.get("rank", len(arguments) + 1)),
                argument    = str(obj.get("argument", "")),
                win_rate    = min(1.0, max(0.0, float(obj.get("win_rate", 0.5)))),
                section     = str(obj.get("section", query.sections[0] if query.sections else "")),
                authorities = supporting,
                documents   = [],   # filled in Phase B
            ))

        return sorted(arguments, key=lambda a: a.rank)

    # ── Step 7B: Document synthesis ───────────────────────────────────────────

    def _synthesize_documents(self, query: CaseQuery,
                               arguments: list[LegalArgument],
                               cases: list[RetrievedCase]) -> list[LegalArgument]:
        """
        Phase B: For each legal argument, extract the documents needed
        to prove it — based on what the retrieved cases say.
        """
        if not arguments or not cases:
            return arguments

        cases_block = self._format_cases_for_prompt(cases[:10])
        args_text   = "\n".join(
            f"{a.rank}. {a.argument}" for a in arguments
        )

        prompt = f"""CLIENT SITUATION:
Sections: {', '.join(query.sections)}
Facts: {query.client_facts}

LEGAL ARGUMENTS TO PROVE:
{args_text}

RETRIEVED CASES (showing what documents worked):
{cases_block}

TASK — Phase B:
For each argument, extract the documents needed to prove it.
Base your answer ONLY on documents explicitly mentioned in the retrieved cases.

Return JSON array — one object per argument:
[
  {{
    "argument_rank": 1,
    "documents": [
      {{
        "name":             "Exact document name",
        "mandatory":        true,
        "why_it_matters":   "What this document proves in the context of this argument",
        "how_to_obtain":    "One practical sentence",
        "accepted_in":      ["Case citation where this document was accepted"],
        "rejected_in":      ["Case citation where this document was rejected"],
        "rejection_reason": "Exact reason if rejected (empty string if not rejected)",
        "acceptance_count": 3
      }}
    ]
  }},
  ...
]"""
        raw    = AIClient.call(_SYNTHESIS_SYSTEM, prompt,
                               temperature=0.05, max_tokens=3000)
        parsed = AIClient.parse_json(raw)

        if not isinstance(parsed, list):
            return arguments

        # Map documents back to arguments by rank
        rank_to_docs: dict[int, list[RequiredDocument]] = {}
        for obj in parsed:
            if not isinstance(obj, dict):
                continue
            rank = int(obj.get("argument_rank", 0))
            docs = []
            for d in obj.get("documents", []):
                if not isinstance(d, dict) or not d.get("name"):
                    continue
                count = max(1, int(d.get("acceptance_count", 1)))
                docs.append(RequiredDocument(
                    name             = str(d["name"]).strip(),
                    mandatory        = bool(d.get("mandatory", False)),
                    why_it_matters   = str(d.get("why_it_matters", "")),
                    how_to_obtain    = str(d.get("how_to_obtain", "")),
                    accepted_in      = list(d.get("accepted_in", [])),
                    rejected_in      = list(d.get("rejected_in", [])),
                    rejection_reason = str(d.get("rejection_reason", "")),
                    acceptance_count = count,
                    win_boost        = min(30, count * 5),
                ))
            rank_to_docs[rank] = docs

        for arg in arguments:
            if arg.rank in rank_to_docs:
                arg.documents = sorted(
                    rank_to_docs[arg.rank],
                    key=lambda d: (-int(d.mandatory), -d.acceptance_count),
                )

        return arguments

    # ── Step 7C: Counter-argument synthesis ───────────────────────────────────

    def _synthesize_counters(self, query: CaseQuery,
                              cases: list[RetrievedCase],
                              arguments: list[LegalArgument]) -> list[CounterArgument]:
        """
        Phase C: Identify what Revenue will argue and build rebuttals.
        """
        if not cases:
            return []

        args_summary = "; ".join(a.argument[:80] for a in arguments[:3])

        prompt = f"""CLIENT SITUATION:
Sections: {', '.join(query.sections)}
Facts: {query.client_facts}
Our arguments: {args_summary}

TASK — Phase C:
Identify 3 counter-arguments Revenue will raise at ITAT and the rebuttal for each.
Base rebuttals on the standard ITAT case law for these sections.

Return JSON array of 3 counter-argument objects:
[
  {{
    "revenue_argument":  "What Revenue will argue",
    "rebuttal":          "How assessee should counter this",
    "supporting_case":   "Best case that supports the rebuttal (name + year)",
    "counter_document":  "Document that defeats this Revenue argument"
  }},
  ...
]"""
        raw    = AIClient.call(_SYNTHESIS_SYSTEM, prompt,
                               temperature=0.1, max_tokens=1024)
        parsed = AIClient.parse_json(raw)

        if not isinstance(parsed, list):
            return []

        counters: list[CounterArgument] = []
        for obj in parsed:
            if not isinstance(obj, dict):
                continue
            counters.append(CounterArgument(
                revenue_argument = str(obj.get("revenue_argument", "")),
                rebuttal         = str(obj.get("rebuttal", "")),
                supporting_case  = str(obj.get("supporting_case", "")),
                counter_document = str(obj.get("counter_document", "")),
            ))

        return counters

    # ── Win probability ───────────────────────────────────────────────────────

    @staticmethod
    def _calculate_win_probability(cases: list[RetrievedCase],
                                   arguments: list[LegalArgument]) -> float:
        """
        Derive win probability from:
        - Average win_rate across arguments (weighted by rank)
        - SC/HC authority in top cases (boosts confidence)
        """
        if not arguments:
            return 0.5

        weighted_sum = 0.0
        weight_total = 0.0
        for arg in arguments:
            weight        = 1.0 / arg.rank   # rank 1 = weight 1.0, rank 2 = 0.5 etc.
            weighted_sum += arg.win_rate * weight
            weight_total += weight

        base_prob = weighted_sum / weight_total if weight_total > 0 else 0.5

        # Boost if SC/HC authorities in top 5 cases
        authority_boost = 0.0
        for case in cases[:5]:
            if case.court_type.value == "SC":
                authority_boost += 0.03
            elif case.court_type.value == "HC":
                authority_boost += 0.015

        return min(0.95, max(0.1, base_prob + authority_boost))

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _format_cases_for_prompt(cases: list[RetrievedCase]) -> str:
        lines = []
        for i, c in enumerate(cases, 1):
            lines.append(
                f"[{i}] {c.citation} ({c.court_type.value}, {c.year})\n"
                f"    Section: {c.section}\n"
                f"    Holding: {c.key_ratio[:350]}\n"
                f"    Facts:   {c.facts_summary[:200]}\n"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> list | dict | None:
        try:
            clean = raw.strip()
            if "```" in clean:
                clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()

            # Try array first, then object
            for start_char, end_char in [("[", "]"), ("{", "}")]:
                start = clean.find(start_char)
                end   = clean.rfind(end_char) + 1
                if start >= 0 and end > start:
                    return json.loads(clean[start:end])
        except Exception:
            pass
        return None
