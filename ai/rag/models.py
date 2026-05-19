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
    case_id:         int
    sections:        list[str]
    client_facts:    str
    ao_text:         str   = ""
    demand_amount:   float = 0.0
    case_name:       str   = ""
    assessment_year: str   = ""

    def search_text(self) -> str:
        """Single string used for embedding and FTS queries."""
        parts = [self.client_facts]
        if self.ao_text:
            parts.append(self.ao_text[:500])
        if self.sections:
            parts.append("section " + " ".join(self.sections))
        return " ".join(parts)


# ── Retrieval ─────────────────────────────────────────────────────────────────

@dataclass
class RetrievedCase:
    db_id:         int
    citation:      str
    court_type:    CourtType
    year:          int
    section:       str
    key_ratio:     str
    facts_summary: str
    url:           str

    # Scores filled at each stage
    vector_score:          float = 0.0   # cosine similarity from ChromaDB
    fts_rank:              int   = 9999  # BM25 rank from FTS5 (lower = better)
    rrf_score:             float = 0.0   # reciprocal rank fusion combined score
    rerank_score:          float = 0.0   # Gemini cross-encoder score 0-10
    final_score:           float = 0.0   # after authority + recency boost
    rerank_explanation:    str   = ""    # why Gemini scored it this way

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
