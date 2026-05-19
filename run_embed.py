"""
Citation Embedding Indexer — run this ONCE after run_harvest.py.

Builds the ChromaDB vector index and SQLite FTS5 index over all
citations in the database. Required before the RAG pipeline works.

Usage:
    python run_embed.py              # index everything
    python run_embed.py --status     # show current index state
    python run_embed.py --fts-only   # rebuild FTS5 only (fast, no API calls)
    python run_embed.py --sync       # add only new cases not yet indexed

Expected time:
    FTS5 index       : < 10 seconds
    ChromaDB (OR)    : ~4,350 cases × 3 collections ÷ batch of 50
                       ≈ 270 API calls × ~0.5s = ~2-3 minutes total
                       Cost: ~$0.03 one-time (OpenRouter text-embedding-3-small)
    ChromaDB (Gemini): ~4,350 cases × 3 collections ÷ batch of 5
                       ≈ 2,610 API calls × ~5s = ~3-4 hours
                       (free tier: 1,000/day limit, needs 3 days)

Re-running is safe — only new cases are indexed (idempotent).
"""

import sys
import os
import argparse
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except ImportError:
    pass


def _banner(text: str, char: str = "─"):
    width = 70
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}")


def _progress(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def cmd_status():
    """Show current index state."""
    _banner("Embedding Index Status")

    # ChromaDB
    try:
        from ai.rag.embedder import EmbeddingService
        svc = EmbeddingService()
        count = svc.indexed_count()
        print(f"  ChromaDB vector index : {count:,} cases indexed")
        if count == 0:
            print("  → Not indexed. Run: python run_embed.py")
    except ImportError:
        print("  ChromaDB              : ❌  Not installed (pip install chromadb)")
    except Exception as e:
        print(f"  ChromaDB              : ❌  Error: {e}")

    # FTS5
    try:
        from ai.rag.fts import FTSIndex
        import sqlite3
        import config
        fts = FTSIndex()
        conn = sqlite3.connect(config.DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM itat_fts")
        fts_count = cur.fetchone()[0]
        conn.close()
        print(f"  FTS5 keyword index    : {fts_count:,} documents")
    except Exception as e:
        print(f"  FTS5 index            : ❌  Error: {e}")

    # DB
    try:
        import sqlite3
        import config
        conn = sqlite3.connect(config.DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM itat_precedents WHERE verified IN (1,2)")
        db_count = cur.fetchone()[0]
        conn.close()
        print(f"  Citation DB total     : {db_count:,} verified cases")
    except Exception as e:
        print(f"  Citation DB           : ❌  Error: {e}")


def cmd_fts_only():
    """Build / rebuild FTS5 index only — fast, no API calls."""
    _banner("FTS5 Index Build")
    try:
        from ai.rag.fts import FTSIndex
        import sqlite3
        import config

        _progress("Creating / rebuilding FTS5 virtual table...")
        fts = FTSIndex()   # _ensure_index() called in __init__

        # Force rebuild from current DB state
        fts.rebuild()
        _progress("Syncing any new cases...")
        added = fts.sync_new_cases()

        conn = sqlite3.connect(config.DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM itat_fts")
        total = cur.fetchone()[0]
        conn.close()

        _banner("FTS5 Build Complete ✅")
        print(f"  Documents in FTS5 index : {total:,}")
        print(f"  New cases synced        : {added:,}")
    except Exception as e:
        print(f"  ❌ FTS5 error: {e}")
        import traceback
        traceback.print_exc()


def cmd_index(sync_only: bool = False):
    """Build full ChromaDB + FTS5 index."""

    # ── Preflight checks ──────────────────────────────────────────────────────
    try:
        import chromadb
    except ImportError:
        print("\n  ❌ chromadb not installed.")
        print("  Run: pip install chromadb")
        return

    # Check for either OpenRouter or Gemini key
    or_key     = os.getenv("OPENROUTER_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    try:
        import config
        or_key     = or_key     or getattr(config, "OPENROUTER_API_KEY", "")
        gemini_key = gemini_key or getattr(config, "GEMINI_API_KEY", "")
    except Exception:
        pass

    if or_key:
        print(f"\n  ✅ Using OpenRouter (text-embedding-3-small, 1536-dim)")
        print(f"     No daily quota — pay-per-use (~$0.02/1M tokens)")
    elif gemini_key:
        print(f"\n  ✅ Using Gemini (gemini-embedding-001, 3072-dim)")
        print(f"     Free tier: 1,000 embeddings/day limit")
    else:
        print("\n  ❌ No embedding API key found.")
        print("  Add either to your .env file:")
        print("    OPENROUTER_API_KEY=sk-or-...   (recommended — no daily quota)")
        print("    GEMINI_API_KEY=AIza...          (free tier, 1000/day limit)")
        return

    import config
    from ai.rag.embedder import EmbeddingService
    from ai.rag.fts      import FTSIndex
    from database.init_db import init_database

    init_database()

    _banner("Citation Embedding Indexer", "═")

    # ── FTS5 ─────────────────────────────────────────────────────────────────
    _progress("Step 1/2 — Building FTS5 keyword index...")
    try:
        fts = FTSIndex(config.DB_PATH)
        fts.sync_new_cases()
        _progress("  ✅ FTS5 index ready")
    except Exception as e:
        _progress(f"  ⚠ FTS5 error: {e} (continuing with ChromaDB...)")

    # ── ChromaDB ─────────────────────────────────────────────────────────────
    _progress("Step 2/2 — Building ChromaDB vector index...")

    svc = EmbeddingService()

    if sync_only:
        _progress(f"  Sync mode: {svc.indexed_count():,} already indexed")
    else:
        _progress("  Full index mode")

    before = svc.indexed_count()

    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM itat_precedents WHERE verified IN (1,2)")
    total_db = cur.fetchone()[0]
    conn.close()

    print(f"\n  Cases in DB    : {total_db:,}")
    print(f"  Already indexed: {before:,}")
    print(f"  To index now   : {total_db - before:,}")

    if total_db == before:
        print("\n  ✅ All cases already indexed — nothing to do.")
        print("     Run --sync after each harvest to add new cases.")
        return

    if or_key:
        est_batches = ((total_db - before) // 50) + 1  # OpenRouter: batch of 50
        est_minutes = est_batches * 3 * 0.5 / 60       # 3 collections × ~0.5s per batch
        print(f"  Est. time      : ~{max(1, int(est_minutes))} minutes (OpenRouter, batch=50)")
    else:
        est_batches = ((total_db - before) // 5) + 1   # Gemini: batch of 5
        est_minutes = est_batches * 3 * 5.0 / 60       # 3 collections × ~5s per batch
        print(f"  Est. time      : ~{int(est_minutes)} minutes (Gemini free tier, batch=5)")
    print(f"\n  Starting in 3 seconds — Ctrl+C to abort...")
    time.sleep(3)

    start = time.time()
    try:
        added = svc.index_all(config.DB_PATH, progress_cb=_progress)
    except Exception as e:
        _progress(f"❌ Indexing stopped: {e}")
        added = 0
    elapsed = time.time() - start

    _banner("Indexing Complete ✅", "═")
    print(f"  Newly indexed  : {added:,}")
    print(f"  Total indexed  : {svc.indexed_count():,}")
    print(f"  Time taken     : {elapsed:.1f} seconds")
    print(f"\n  RAG pipeline is now active.")
    print(f"  Next time you build evidence for a case, it will use")
    print(f"  hybrid vector + keyword search instead of keyword-only.")


def main():
    parser = argparse.ArgumentParser(
        description="Build the ChromaDB + FTS5 index for the RAG pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_embed.py              # full index build (run once after harvest)
  python run_embed.py --sync       # add only new cases (run after each harvest)
  python run_embed.py --fts-only   # rebuild FTS5 only (no API, instant)
  python run_embed.py --status     # show index state
        """
    )
    parser.add_argument("--status",   action="store_true", help="Show index status and exit")
    parser.add_argument("--fts-only", action="store_true", help="Rebuild FTS5 index only")
    parser.add_argument("--sync",     action="store_true", help="Add only new cases to index")
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.fts_only:
        cmd_fts_only()
    else:
        cmd_index(sync_only=args.sync)


if __name__ == "__main__":
    main()
