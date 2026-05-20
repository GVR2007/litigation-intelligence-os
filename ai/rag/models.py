"""
Typed data models for the RAG pipeline.
Every layer passes these — no raw dicts.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CourtType(str, Enum):
    SC    = "SC"
    HC    = "HC"
    ITAT  = "ITAT"
    OTHER = "OTHER"


# ── Input ─────────────────────────────────────────────────────────────────────

@dataclass
class CaseQuery:
    case_id:             int
    sections:            list[str]
    client_facts:        str
    ao_text:             str   = ""
    ao_allegations:      str   = ""   # AO's exact objection language — primary query driver
    ao_rejection_reason: str   = ""   # Why AO rejected assessee's explanation
    demand_amount:       float = 0.0
    case_name:           str   = ""
    assessment_year:     str   = ""

    def search_text(self) -> str:
        """
        Single string used for embedding and FTS queries.
        Priority: AO's own language > client facts > AO order text > sections.
        AO allegation language produces the highest-quality matches because
        ITAT judgments use the same legal vocabulary as AO orders.
        """
        parts = []
        # Highest signal: AO's exact allegation — same words appear in winning ITAT cases
        if self.ao_allegations:
            parts.append(self.ao_allegations[:400])
        if self.ao_rejection_reason:
            parts.append(self.ao_rejection_reason[:200])
        # Client facts as context
        if self.client_facts:
            parts.append(self.client_facts[:300])
        # Sections for FTS anchor
        if self.sections:
            parts.append("section " + " ".join(self.sections))
        return " ".join(parts) if parts else self.client_facts


# ── Retrieval ─────────────────────────────────────────────────────────────────

@dataclass
class RetrievedCase:
    db_id:              int
    citation:           str
    court_type:         CourtType
    year:               int
    section:            str
    key_ratio:          str
    facts_summary:      str
    url:                str
    win_for_assessee:   bool  = True   # False = Revenue won — used to skip doc extraction
    documents_accepted: str   = ""     # JSON list of docs accepted in this case

    # Scores filled at each stage
    vector_score:          float = 0.0   # cosine similarity from ChromaDB
    fts_rank:              int   = 9999  # BM25 rank from FTS5 (lower = better)
    rrf_score:             float = 0.0   # reciprocal rank fusion combined score
    rerank_score:          float = 0.0   # cross-encoder score 0-10
    final_score:           float = 0.0   # after authority + recency boost
    rerank_explanation:    str   = ""    # why it was scored this way

    @property
    def authority_weight(self) -> float:
        weights = {CourtType.SC: 1.5, CourtType.HC: 1.2,
                   CourtType.ITAT: 1.0, CourtType.OTHER: 0.8}
        return weights.get(self.court_type, 1.0)

    @property
    def recency_weight(self) -> float:
        import datetime
        current_year = datetime.date.today().year
        if self.year >= current_year - 3:
            return 1.3
        if self.year >= current_year - 6:
            return 1.1
        return 1.0

    def apply_boosts(self) -> None:
        """Multiply rrf_score by authority and recency weights to get final_score."""
        self.final_score = self.rrf_score * self.authority_weight * self.recency_weight


# ── Output ────────────────────────────────────────────────────────────────────

@dataclass
class RequiredDocument:
    name:             str
    mandatory:        bool
    why_it_matters:   str
    how_to_obtain:    str
    accepted_in:      list[str] = field(default_factory=list)
    rejected_in:      list[str] = field(default_factory=list)
    rejection_reason: str       = ""
    acceptance_count: int       = 1
    win_boost:        int       = 10


@dataclass
class LegalArgument:
    rank:        int
    argument:    str
    win_rate:    float          # 0.0–1.0 derived from retrieved case outcomes
    section:     str            = ""
    authorities: list[RetrievedCase]    = field(default_factory=list)
    documents:   list[RequiredDocument] = field(default_factory=list)


@dataclass
class CounterArgument:
    revenue_argument: str
    rebuttal:         str
    supporting_case:  str = ""
    counter_document: str = ""


@dataclass
class CaseStrategy:
    query:              CaseQuery
    arguments:          list[LegalArgument]
    counter_arguments:  list[CounterArgument]
    win_probability:    float
    retrieved_cases:    list[RetrievedCase]
    hyde_document:      str       = ""
    expanded_sections:  list[str] = field(default_factory=list)

    def top_documents(self) -> list[RequiredDocument]:
        """Flat list of all documents across all arguments, deduped, sorted by acceptance."""
        seen: set[str] = set()
        docs: list[RequiredDocument] = []
        for arg in self.arguments:
            for doc in arg.documents:
                key = doc.name.lower()[:50]
                if key not in seen:
                    seen.add(key)
                    docs.append(doc)
        docs.sort(key=lambda d: (-int(d.mandatory), -d.acceptance_count))
        return docs
