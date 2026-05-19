"""
EmbeddingService — ChromaDB vector index with dual provider support.

Provider priority:
  1. OpenRouter  → openai/text-embedding-3-small  (1536-dim, no daily quota, ~$0.02/1M tokens)
  2. Gemini      → gemini-embedding-001            (3072-dim, free tier 1000/day limit)

Three collections per case:
  itat_facts    — fact pattern of the case
  itat_holding  — legal holding / ratio decidendi
  itat_docs     — documents mentioned in the judgment

All three queried at retrieval time and RRF-fused in retriever.py.

Provider switch detection:
  If the stored provider (in chroma_db/.embed_provider) differs from the
  active provider, the index is automatically cleared before re-indexing.
  This prevents dimension-mismatch errors (1536 vs 3072).
"""

from __future__ import annotations
import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

# ── OpenRouter settings ───────────────────────────────────────────────────────
_OR_BASE        = "https://openrouter.ai/api/v1"
_OR_MODEL       = "openai/text-embedding-3-small"
_OR_DIM         = 1536
_OR_BATCH_SIZE  = 50    # OpenRouter allows large batches
_OR_RATE_DELAY  = 0.3   # seconds — generous rate limits, no daily quota
_OR_MAX_RETRIES = 3

# ── Gemini fallback settings ──────────────────────────────────────────────────
_GEMINI_BASE        = "https://generativelanguage.googleapis.com/v1beta/models"
_GEMINI_MODEL       = "gemini-embedding-001"
_GEMINI_DIM         = 3072
_GEMINI_BATCH_SIZE  = 5     # small batches for free tier
_GEMINI_RATE_DELAY  = 4.5   # seconds — free tier: ~13 RPM (limit: 15 RPM)
_GEMINI_MAX_RETRIES = 3
_GEMINI_RETRY_WAIT  = 62    # wait on 429 (full 1-minute window reset)

_TEXT_CAP = 500   # chars per text — keeps tokens per call low


def _or_key() -> str:
    return getattr(config, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")


def _gemini_key() -> str:
    return getattr(config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")


def active_provider() -> str:
    """Returns 'openrouter' if key is set, else 'gemini'."""
    return "openrouter" if _or_key() else "gemini"


def active_dim() -> int:
    """Embedding dimension for the active provider."""
    return _OR_DIM if active_provider() == "openrouter" else _GEMINI_DIM


def _chroma_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base, "chroma_db")


def _provider_file() -> str:
    return os.path.join(_chroma_path(), ".embed_provider")


def _get_stored_provider() -> str | None:
    try:
        with open(_provider_file()) as f:
            return f.read().strip()
    except Exception:
        return None


def _set_stored_provider(provider: str) -> None:
    os.makedirs(_chroma_path(), exist_ok=True)
    with open(_provider_file(), "w") as f:
        f.write(provider)


# ─────────────────────────────────────────────────────────────────────────────
# OpenRouter embedding call
# ─────────────────────────────────────────────────────────────────────────────

def _embed_batch_openrouter(texts: list[str]) -> list[list[float]]:
    """
    Embed texts via OpenRouter → openai/text-embedding-3-small.
    Returns list of 1536-dim float vectors.
    """
    import requests

    key = _or_key()
    url = f"{_OR_BASE}/embeddings"

    payload = {
        "model": _OR_MODEL,
        "input": [t[:_TEXT_CAP] for t in texts],
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://github.com/GVR2007/CA",
        "X-Title":       "Litigation Intelligence OS",
    }

    for attempt in range(_OR_MAX_RETRIES):
        resp = requests.post(url, json=payload, headers=headers, timeout=60)

        if resp.status_code == 200:
            data = resp.json()["data"]
            # Sort by index to preserve order
            data.sort(key=lambda x: x["index"])
            return [item["embedding"] for item in data]

        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 10))
            if attempt < _OR_MAX_RETRIES - 1:
                print(f"    [embed/OR] 429 rate limit — waiting {wait}s...")
                time.sleep(wait)
                continue

        if resp.status_code >= 500 and attempt < _OR_MAX_RETRIES - 1:
            time.sleep(5)
            continue

        resp.raise_for_status()

    raise RuntimeError(f"OpenRouter embedding failed after {_OR_MAX_RETRIES} retries")


# ─────────────────────────────────────────────────────────────────────────────
# Gemini embedding call (fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _embed_batch_gemini(texts: list[str],
                        task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """
    Embed texts via Gemini REST API → gemini-embedding-001.
    Returns list of 3072-dim float vectors.
    Retries with backoff on 429 / 5xx errors.
    """
    import requests

    key = _gemini_key()
    url = f"{_GEMINI_BASE}/{_GEMINI_MODEL}:batchEmbedContents?key={key}"

    payload = {
        "requests": [
            {
                "model":    f"models/{_GEMINI_MODEL}",
                "content":  {"parts": [{"text": t[:_TEXT_CAP]}]},
                "taskType": task_type,
            }
            for t in texts
        ]
    }

    for attempt in range(_GEMINI_MAX_RETRIES):
        resp = requests.post(url, json=payload, timeout=60)

        if resp.status_code == 200:
            return [e["values"] for e in resp.json()["embeddings"]]

        if resp.status_code == 429:
            body = resp.json()
            for detail in body.get("error", {}).get("details", []):
                for v in detail.get("violations", []):
                    if "PerDay" in v.get("quotaId", ""):
                        raise DailyQuotaExhausted(
                            "Gemini free tier: 1,000 embeddings/day limit reached.\n"
                            "  → Set OPENROUTER_API_KEY in .env to use OpenRouter instead (no daily quota).\n"
                            "  → Or run again tomorrow when Gemini quota resets.\n"
                            "  → FTS5 keyword search still works until then."
                        )
            if attempt < _GEMINI_MAX_RETRIES - 1:
                retry_after = int(resp.headers.get("Retry-After", _GEMINI_RETRY_WAIT))
                wait = max(retry_after, _GEMINI_RETRY_WAIT)
                print(f"    [embed/Gemini] 429 rate limit — waiting {wait}s (attempt {attempt+1}/{_GEMINI_MAX_RETRIES})...")
                time.sleep(wait)
                continue

        if resp.status_code >= 500 and attempt < _GEMINI_MAX_RETRIES - 1:
            time.sleep(_GEMINI_RETRY_WAIT)
            continue

        resp.raise_for_status()

    raise RuntimeError(f"Gemini embedding failed after {_GEMINI_MAX_RETRIES} retries")


# ─────────────────────────────────────────────────────────────────────────────
# Unified embed_batch — routes to active provider
# ─────────────────────────────────────────────────────────────────────────────

def _embed_batch(texts: list[str],
                 task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """
    Route to OpenRouter (primary) or Gemini (fallback).
    task_type is ignored for OpenRouter (OpenAI API doesn't use it).
    """
    if active_provider() == "openrouter":
        return _embed_batch_openrouter(texts)
    else:
        return _embed_batch_gemini(texts, task_type)


def embed_query(text: str) -> list[float]:
    """Embed a single query string."""
    if active_provider() == "openrouter":
        return _embed_batch_openrouter([text])[0]
    else:
        result = _embed_batch_gemini([text], task_type="RETRIEVAL_QUERY")
        return result[0]


class DailyQuotaExhausted(Exception):
    """Raised when the Gemini free-tier daily embedding quota is exhausted."""


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

        # Detect provider switch — clear index if dimension would mismatch
        current = active_provider()
        stored  = _get_stored_provider()

        needs_clear = False
        if stored and stored != current:
            needs_clear = True
        elif not stored:
            # No provider file yet — check actual stored dimension
            # (handles migration from old Gemini-only setup)
            try:
                test_col = self._client.get_or_create_collection(
                    self.COLLECTION_FACTS, metadata={"hnsw:space": "cosine"}
                )
                if test_col.count() > 0:
                    sample     = test_col.get(limit=1, include=["embeddings"])
                    embs       = sample.get("embeddings")
                    stored_dim = None
                    # Handle both numpy arrays and plain lists
                    if embs is not None and len(embs) > 0:
                        first = embs[0]
                        if hasattr(first, "__len__"):
                            stored_dim = len(first)
                    if stored_dim and stored_dim != active_dim():
                        needs_clear = True
                        stored = "gemini" if stored_dim == _GEMINI_DIM else "unknown"
            except Exception:
                pass

        if needs_clear:
            existing = self._client.list_collections()
            if existing:
                old_dim = _GEMINI_DIM if (stored or "gemini") == "gemini" else _OR_DIM
                print(f"\n  ⚠️  Embedding provider changed: {stored or 'gemini'} → {current}")
                print(f"      Dimension change ({old_dim} → {active_dim()}) — clearing existing index...")
                for col in existing:
                    self._client.delete_collection(col.name)
                print("      Index cleared. Will re-index all cases.\n")

        _set_stored_provider(current)

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
        return self._facts.count() > 0

    def indexed_count(self) -> int:
        return self._facts.count()

    def index_all(self, db_path: str, progress_cb=None) -> int:
        """
        Read all cases from itat_precedents, embed them into 3 collections.
        Idempotent — skips already-indexed IDs.
        Returns count of newly indexed cases.
        """
        provider   = active_provider()
        batch_size = _OR_BATCH_SIZE if provider == "openrouter" else _GEMINI_BATCH_SIZE
        rate_delay = _OR_RATE_DELAY if provider == "openrouter" else _GEMINI_RATE_DELAY

        cases = self._load_cases(db_path)
        if progress_cb:
            progress_cb(f"  Loaded {len(cases):,} cases from DB  [provider: {provider}]")

        existing_ids = set(self._facts.get(include=[])["ids"])
        new_cases    = [c for c in cases if str(c["id"]) not in existing_ids]

        if not new_cases:
            if progress_cb:
                progress_cb("  All cases already indexed — nothing to do.")
            return 0

        if progress_cb:
            progress_cb(f"  New cases to index: {len(new_cases):,}")

        added = 0
        for batch_start in range(0, len(new_cases), batch_size):
            batch = new_cases[batch_start: batch_start + batch_size]

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

            facts_texts   = [self._facts_text(c)[:_TEXT_CAP]   for c in batch]
            holding_texts = [self._holding_text(c)[:_TEXT_CAP] for c in batch]
            docs_texts    = [self._docs_text(c)[:_TEXT_CAP]    for c in batch]

            try:
                if provider == "openrouter":
                    # OpenRouter: can send all 3 in quick succession
                    facts_emb   = _embed_batch_openrouter(facts_texts)
                    holding_emb = _embed_batch_openrouter(holding_texts)
                    docs_emb    = _embed_batch_openrouter(docs_texts)
                    time.sleep(rate_delay)
                else:
                    # Gemini: rate-limited, sleep between each call
                    facts_emb   = _embed_batch_gemini(facts_texts,   "RETRIEVAL_DOCUMENT")
                    time.sleep(rate_delay)
                    holding_emb = _embed_batch_gemini(holding_texts, "RETRIEVAL_DOCUMENT")
                    time.sleep(rate_delay)
                    docs_emb    = _embed_batch_gemini(docs_texts,    "RETRIEVAL_DOCUMENT")
                    time.sleep(rate_delay)

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

            except DailyQuotaExhausted as e:
                if progress_cb:
                    progress_cb(f"\n  ⛔ Daily quota exhausted after indexing {added} cases.")
                    progress_cb(f"  ✅ {added} cases saved to ChromaDB.")
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

        count = col.count()
        if count == 0:
            return []

        kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results":        min(top_k, count),
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
        parts = []
        if case.get("facts_summary"):
            parts.append(case["facts_summary"])
        if case.get("case_citation"):
            parts.append(case["case_citation"])
        return " ".join(parts)[:4000] or "No facts available."

    @staticmethod
    def _holding_text(case: dict) -> str:
        return (case.get("key_ratio") or "")[:4000] or "No holding available."

    @staticmethod
    def _docs_text(case: dict) -> str:
        ratio    = (case.get("key_ratio") or "")
        facts    = (case.get("facts_summary") or "")
        combined = f"{ratio} {facts}"
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
