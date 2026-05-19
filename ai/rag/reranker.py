"""
Reranker — Gemini cross-encoder scoring.

After HybridRetriever returns top-25 candidates by RRF score,
the Reranker asks Gemini to score each case 0-10 against the
full client query — factoring in fact similarity, legal relevance,
and court authority.

Batches 5 cases per Gemini call to stay within token limits.
"""

from __future__ import annotations
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ai.rag.models import RetrievedCase, CaseQuery

_BATCH_SIZE = 5

_SYSTEM = """You are an Indian Income Tax litigation expert.
Score retrieved cases for relevance to a client's situation.
Return only valid JSON — no commentary, no markdown."""


class Reranker:

    def rerank(self, cases: list[RetrievedCase],
               query: CaseQuery,
               top_k: int = 12) -> list[RetrievedCase]:
        """
        Score each candidate case against the client's situation.
        Returns cases sorted by rerank_score descending, limited to top_k.
        """
        batches = [
            cases[i: i + _BATCH_SIZE]
            for i in range(0, len(cases), _BATCH_SIZE)
        ]

        for batch in batches:
            self._score_batch(batch, query)

        # Final sort: rerank_score * rrf_score (blend both signals)
        for c in cases:
            c.final_score = (
                c.rerank_score * 0.6 +
                c.rrf_score    * 100 * 0.4   # scale rrf to ~same range
            ) * c.authority_weight * c.recency_weight

        cases.sort(key=lambda c: -c.final_score)
        return cases[:top_k]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _score_batch(self, batch: list[RetrievedCase], query: CaseQuery) -> None:
        """
        One Gemini call scores all cases in the batch.
        Writes rerank_score and rerank_explanation in-place.
        """
        client_context = (
            f"Client sections: {', '.join(query.sections)}\n"
            f"Facts: {query.client_facts[:400]}\n"
            f"AO allegation: {query.ao_text[:300]}"
        )

        cases_text = ""
        for i, case in enumerate(batch, 1):
            cases_text += (
                f"\n[CASE {i}]\n"
                f"Citation: {case.citation}\n"
                f"Court: {case.court_type.value}  Year: {case.year}\n"
                f"Section: {case.section}\n"
                f"Holding: {case.key_ratio[:400]}\n"
                f"Facts: {case.facts_summary[:300]}\n"
            )

        prompt = f"""CLIENT SITUATION:
{client_context}

CANDIDATE CASES:
{cases_text}

TASK:
Score each case 0-10 for relevance to the client's situation.
Consider:
- Fact similarity (same type of transaction? same relationship? same setting?)
- Legal holding relevance (does it establish a principle that helps this client?)
- Court authority (SC/HC > ITAT)
- Recency

Return a JSON array with exactly {len(batch)} objects, one per case in order:
[
  {{
    "case_number": 1,
    "score": 8.5,
    "explanation": "One sentence on why this matches or doesn't"
  }},
  ...
]"""

        from ai.gemini_client import call_gemini
        raw = call_gemini(_SYSTEM, prompt, temperature=0.05, max_tokens=1024, redact=False)

        scores = self._parse_scores(raw, len(batch))

        for i, case in enumerate(batch):
            if i < len(scores):
                case.rerank_score      = float(scores[i].get("score", 5.0))
                case.rerank_explanation = str(scores[i].get("explanation", ""))
            else:
                case.rerank_score      = 5.0
                case.rerank_explanation = ""

    @staticmethod
    def _parse_scores(raw: str, expected: int) -> list[dict]:
        """Parse Gemini JSON response. Returns list of score dicts."""
        try:
            clean = raw.strip()
            if "```" in clean:
                clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()

            start = clean.find("[")
            end   = clean.rfind("]") + 1
            if start >= 0 and end > start:
                clean = clean[start:end]

            parsed = json.loads(clean)
            if isinstance(parsed, list):
                return parsed[:expected]
        except Exception:
            pass

        # If parse fails, return neutral scores
        return [{"score": 5.0, "explanation": ""} for _ in range(expected)]
