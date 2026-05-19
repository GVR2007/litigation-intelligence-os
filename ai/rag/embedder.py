"""
EmbeddingService — Gemini text-embedding-004 + ChromaDB.

Three collections per case:
  itat_facts    — fact pattern of the case
  itat_holding  — legal holding / ratio decidendi
  itat_docs     — documents mentioned in the judgment

All three queried at retrieval time and RRF-fused in retriever.py.
"""

from __future__ import annotations
import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

_EMBED_BASE   = "https://generativelanguage.googleapis.com/v1beta/models"
_EMBED_MODEL  = "gemini-embedding-001"   # 3072-dim, stable, available on all Gemini API keys
_BATCH_SIZE   = 5    # 5 cases per batch → 5 texts per API call → ~2500 tokens max
_TEXT_CAP     = 500  # chars per text — keeps tokens per call very low (~2500 total)
_RATE_DELAY   = 4.5  # seconds between calls → ~13 RPM (free tier limit: 15 RPM)
_MAX_RETRIES  = 3    # retry attempts on 429 / transient errors
_RETRY_WAIT   = 62   # seconds — wait on 429 (full 1-minute window reset)


def _key() -> str:
    return getattr(config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")


def _chroma_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base, "chroma_db")


# ─────────────────────────────────────────────────────────────────────────────
# Low-level Gemini embedding calls (pure requests — consistent with codebase)
# ─────────────────────────────────────────────────────────────────────────────

def _embed_batch(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """
    Embed a batch of texts via Gemini REST API.
    Returns list of 3072-dim float vectors.
    Retries with exponential backoff on 429 / 5xx errors.
    """
    import requests

    key = _key()
    url = f"{_EMBED_BASE}/{_EMBED_MODEL}:batchEmbedContents?key={key}"

    payload = {
        "requests": [
            {
                "model": f"models/{_EMBED_MODEL}",
                "content": {"parts": [{"text": t[:_TEXT_CAP]}]},   # cap per text → low tokens
                "taskType": task_type,
            }
            for t in texts
        ]
    }

    for attempt in range(_MAX_RETRIES):
        resp = requests.post(url, json=payload, timeout=60)

        if resp.status_code == 200:
            return [e["values"] for e in resp.json()["embeddings"]]

        if resp.status_code == 429:
            # Detect daily quota exhaustion — no point retrying until tomorrow
            body = resp.json()
            for detail in body.get("error", {}).get("details", []):
                for v in detail.get("violations", []):
                    if "PerDay" in v.get("quotaId", ""):
                        raise DailyQuotaExhausted(
                            "Gemini free tier: 1,000 embeddings/day limit reached.\n"
                            "Options:\n"
                            "  1. Run again tomorrow (quota resets at midnight)\n"
                            "  2. Enable billing on Google Cloud for higher limits\n"
                            "  The app works fully with FTS5 search until then."
                        )
            # Per-minute rate limit — wait and retry
            if attempt < _MAX_RETRIES - 1:
                retry_after = int(resp.headers.get("Retry-After", _RETRY_WAIT))
                wait = max(retry_after, _RETRY_WAIT)
                print(f"    [embed] 429 rate limit — waiting {wait}s (attempt {attempt+1}/{_MAX_RETRIES})...")
                time.sleep(wait)
                continue

        if resp.status_code >= 500:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_WAIT)
                continue

        resp.raise_for_status()

    raise RuntimeError(f"Embedding failed after {_MAX_RETRIES} retries")


class DailyQuotaExhausted(Exception):
    """Raised when the Gemini free-tier daily embedding quota is exhausted."""


def embed_query(text: str) -> list[float]:
    """Embed a single query string (task_type=RETRIEVAL_QUERY)."""
    result = _embed_batch([text], task_type="RETRIEVAL_QUERY")
    return result[0]


# ─────────────────────────────────────────────────────────────────────────────
# EmbeddingService
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingService:

    COLLECTION_FACTS   = "itat_facts"
    COLLECTION_HOLDING = "itat_holding"
    COLLECTION_DOCS    = "itat_docs"

    def __init__(self, chroma_path: str | None = None):
        import chromadb
        path = chroma_path or _chroma_path()
        os.makedirs(path, exist_ok=True)
        self._client = chromadb.PersistentClient(path=path)

        self._facts   = self._client.get_or_create_collection(
            self.COLLECTION_FACTS,
            metadata={"hnsw:space": "cosine"},
        )
        self._holding = self._client.get_or_create_collection(
            self.COLLECTION_HOLDING,
            metadata={"hnsw:space": "cosine"},
        )
        self._docs    = self._client.get_or_create_collection(
            self.COLLECTION_DOCS,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Public ────────────────────────────────────────────────────────────────

    def is_indexed(self) -> bool:
        """True if at least one case has been indexed."""
        return self._facts.count() > 0

    def indexed_count(self) -> int:
        return self._facts.count()

    def index_all(self, db_path: str, progress_cb=None) -> int:
        """
        Read all cases from itat_precedents, embed them into 3 collections.
        Idempotent — skips already-indexed IDs.
        Returns count of newly indexed cases.
        """
        cases = self._load_cases(db_path)
        if progress_cb:
            progress_cb(f"  Loaded {len(cases):,} cases from DB")

        existing_ids = set(self._facts.get(include=[])["ids"])
        new_cases    = [c for c in cases if str(c["id"]) not in existing_ids]

        if not new_cases:
            if progress_cb:
                progress_cb("  All cases already indexed — nothing to do.")
            return 0

        if progress_cb:
            progress_cb(f"  New cases to index: {len(new_cases):,}")

        added = 0
        for batch_start in range(0, len(new_cases), _BATCH_SIZE):
            batch = new_cases[batch_start: batch_start + _BATCH_SIZE]

            ids       = [str(c["id"]) for c in batch]
            metadatas = [
                {
                    "section":    c.get("section", ""),
                    "court_type": c.get("court_type", "OTHER"),
                    "year":       int(c.get("year") or 0),
                    "citation":   c.get("case_citation", "")[:200],
                    "url":        c.get("ik_url", ""),
                }
                for c in batch
            ]

            # Cap text length — keeps tokens per call low (~2500 tokens max)
            facts_texts   = [self._facts_text(c)[:_TEXT_CAP]   for c in batch]
            holding_texts = [self._holding_text(c)[:_TEXT_CAP] for c in batch]
            docs_texts    = [self._docs_text(c)[:_TEXT_CAP]    for c in batch]

            try:
                # Three separate small calls — each with only _BATCH_SIZE texts
                facts_emb   = _embed_batch(facts_texts,   "RETRIEVAL_DOCUMENT")
                time.sleep(_RATE_DELAY)
                holding_emb = _embed_batch(holding_texts, "RETRIEVAL_DOCUMENT")
                time.sleep(_RATE_DELAY)
                docs_emb    = _embed_batch(docs_texts,    "RETRIEVAL_DOCUMENT")

                self._facts.upsert(
                    ids=ids, embeddings=facts_emb, metadatas=metadatas,
                    documents=facts_texts,
                )
                self._holding.upsert(
                    ids=ids, embeddings=holding_emb, metadatas=metadatas,
                    documents=holding_texts,
                )
                self._docs.upsert(
                    ids=ids, embeddings=docs_emb, metadatas=metadatas,
                    documents=docs_texts,
                )

                added += len(batch)
                if progress_cb:
                    progress_cb(
                        f"  [{batch_start + len(batch)}/{len(new_cases)}] "
                        f"+{len(batch)} indexed  (total: {added})"
                    )
                time.sleep(_RATE_DELAY)

            except DailyQuotaExhausted as e:
                # Daily limit hit — stop immediately, don't waste time on remaining batches
                if progress_cb:
                    progress_cb(f"\n  ⛔ Daily quota exhausted after indexing {added} cases.")
                    progress_cb(f"  ✅ {added} cases indexed so far (saved to ChromaDB).")
                    progress_cb(str(e))
                return added

            except Exception as e:
                if progress_cb:
                    progress_cb(f"  ⚠ Batch {batch_start} error: {e} — skipping")
                continue

        return added

    def search(self, collection_name: str,
               query_embedding: list[float],
               top_k: int = 25,
               section_filter: list[str] | None = None) -> list[dict]:
        """
        Query one collection.
        Returns list of {id, score, metadata} dicts, sorted by score desc.
        """
        col = self._get_collection(collection_name)

        where = None
        if section_filter and len(section_filter) == 1:
            where = {"section": {"$eq": section_filter[0]}}
        elif section_filter:
            where = {"section": {"$in": section_filter}}

        kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results":        min(top_k, col.count()) or 1,
            "include":          ["distances", "metadatas"],
        }
        if where:
            kwargs["where"] = where

        result = col.query(**kwargs)

        ids        = result["ids"][0]
        distances  = result["distances"][0]
        metadatas  = result["metadatas"][0]

        # ChromaDB cosine distance → similarity: score = 1 - distance
        return [
            {
                "id":       int(id_),
                "score":    round(1.0 - float(dist), 6),
                "metadata": meta,
            }
            for id_, dist, meta in zip(ids, distances, metadatas)
        ]

    # ── Text builders (3 aspects per case) ───────────────────────────────────

    @staticmethod
    def _facts_text(case: dict) -> str:
        """What happened in this case — the fact pattern."""
        parts = []
        if case.get("facts_summary"):
            parts.append(case["facts_summary"])
        if case.get("case_citation"):
            parts.append(case["case_citation"])
        return " ".join(parts)[:4000] or "No facts available."

    @staticmethod
    def _holding_text(case: dict) -> str:
        """What the tribunal decided and why — the legal ratio."""
        return (case.get("key_ratio") or "")[:4000] or "No holding available."

    @staticmethod
    def _docs_text(case: dict) -> str:
        """Documents mentioned in the case — for document-level matching."""
        # key_ratio often contains document names
        ratio = (case.get("key_ratio") or "")
        facts = (case.get("facts_summary") or "")
        combined = f"{ratio} {facts}"
        # Extract document-like phrases
        import re
        doc_patterns = re.findall(
            r'\b(?:affidavit|cash book|bank statement|ITR|ledger|'
            r'confirmation letter|PAN|certificate|agreement|invoice|'
            r'receipt|voucher|return|evidence|document|record|deed|'
            r'panchnama|statement|declaration)\b[^.]{0,60}',
            combined, re.IGNORECASE
        )
        return " ".join(doc_patterns)[:3000] or combined[:3000]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_collection(self, name: str):
        mapping = {
            self.COLLECTION_FACTS:   self._facts,
            self.COLLECTION_HOLDING: self._holding,
            self.COLLECTION_DOCS:    self._docs,
        }
        return mapping[name]

    @staticmethod
    def _load_cases(db_path: str) -> list[dict]:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()
        cur.execute("""
            SELECT id, case_citation, section, court_type, year,
                   key_ratio, facts_summary, ik_url
            FROM   itat_precedents
            WHERE  verified IN (1, 2)
              AND  (key_ratio IS NOT NULL OR facts_summary IS NOT NULL)
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
