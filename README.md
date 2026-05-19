# Litigation Intelligence OS

An AI-powered litigation preparation system for Indian Income Tax Appellate Tribunal (ITAT) cases.

## Features

- **12-Phase Workflow** — intake to post-hearing learning
- **RAG Pipeline** — hybrid vector (ChromaDB) + FTS5 keyword search over 4,400+ ITAT precedents
- **Evidence Builder** — multi-source mining (Indian Kanoon, itatonline, taxguru, abcaus, DDG)
- **Indian Kanoon Scraper** — direct scraper (no API key needed)
- **Smart Coverage Checker** — auto-classifies procedural vs contested sections
- **Gemini AI Synthesis** — structured evidence bundles with fallback chain

## Setup

```bash
# 1. Clone
git clone https://github.com/GVR2007/CA.git
cd CA

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 4. Initialise database
python database/init_db.py

# 5. Run the app
streamlit run app.py
```

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
LITIGATION_PORT=8501
```

Get a free Gemini API key at: https://aistudio.google.com

## Project Structure

```
app.py                  — Streamlit entry point
config.py               — Central config (paths, keys)
ai/
  evidence_builder.py   — Multi-source evidence mining
  indian_kanoon.py      — IK website scraper
  rag/                  — Hybrid RAG pipeline
    fts.py              — FTS5 full-text search
    embedder.py         — ChromaDB vector search
    retriever.py        — RRF fusion retriever
    reranker.py         — Gemini cross-encoder reranker
  scrapers/             — Tax site scrapers
modules/
  phase1_intake.py      — Case intake
  phase2_evidence.py    — Evidence collection
  phase3_submissions.py — Written submissions + coverage checker
  ...                   — phases 4-12
utils/
  result_cache.py       — SQLite result cache (7-day TTL)
  web_search.py         — DDG multi-pass search
  pdf_parser.py         — PDF text extraction
database/
  init_db.py            — DB schema setup
data/                   — SQLite DBs (git-ignored)
```

## Requirements

- Python 3.11+
- Gemini API key (free tier works, paid recommended for heavy use)
- ~500MB disk for ChromaDB index

## Notes

- `data/` directory (SQLite databases) is git-ignored — run `python database/init_db.py` after cloning
- `uploads/` is git-ignored — client documents stay local
- `chroma_db/` is git-ignored — run `python run_embed.py --sync` to build vector index
