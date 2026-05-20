# Litigation Intelligence OS

> **AI Co-Pilot for Indian Tax Litigation** — Built for Chartered Accountants & Tax Advocates fighting Income Tax assessments, reassessments, and ITAT appeals.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B)](https://streamlit.io/)
[![Tests](https://img.shields.io/badge/Tests-43%20passing-brightgreen)](#testing)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)

---

## What Is This?

Litigation Intelligence OS is a practitioner-grade, AI-powered command centre for Indian income tax litigation. Upload any government tax document — assessment order, 142(1) notice, 148 reassessment notice, search assessment, penalty order — and the system instantly:

1. **Classifies** the document type from its own heading (no hard-coding)
2. **Extracts** AO allegations, additions, demanded documents, and section violations
3. **Builds** a two-layer evidence checklist (what the AO demanded + what the law requires)
4. **Retrieves** precedents from a hybrid RAG pipeline spanning SC/HC/ITAT judgments + live Indian Kanoon + CBDT circulars
5. **Drafts** legal arguments, counter-submissions, and penalty rebuttals

All in a Streamlit interface — no backend server, no cloud dependency, runs on a laptop.

---

## Key Capabilities

### Universal Document Intake
- **Truly universal** — any Indian tax document handled via two behavioral flags (`has_specific_requests` / `has_additions`), not a hardcoded enum
- Heading extracted verbatim from the document itself
- Numbered demands extracted as Layer 0 evidence (exact fidelity to what the authority asked for)
- Multi-engine PDF extraction: **PyMuPDF → pdfplumber → Tesseract OCR** fallback chain
- Accurate page count via form-feed (`\x0c`) separator
- Hallucination guard: if < 50 words extracted, no LLM call — structured warning returned instead

### Hybrid RAG Pipeline

```
User Query (AO's exact allegation language)
        │
        ├──► Pool A: ChromaDB Vector (3 collections)
        │    ├── facts    (case background embeddings)
        │    ├── holding  (legal ratios)
        │    └── docs     (full judgment text)
        │         +
        │    SQLite FTS5 (BM25 full-text search)
        │    Web-Anchored Term Injection (live IK results → FTS expansion)
        │
        ├──► Pool B: JIT Indian Kanoon Search
        │    Real-time API → embed on the fly → cosine rank → ephemeral results
        │
        └──► Pool C: CBDT Circulars
             Keyword scoring + section-exact-match bonus
                        │
                        ▼
             Cross-Pool RRF Fusion (k=60)
                        │
                        ▼
             Agentic Citation Chain (3-hop)
             SC citation extraction → AI selector → DB lookup / IK fallback
                        │
                        ▼
             HyDE Re-ranking (hypothetical ideal judgment as query vector)
                        │
                        ▼
             Final ranked precedents with win-probability boost
```

### Evidence Engine
| Layer | Source | What It Contains |
|-------|--------|-----------------|
| **Layer 0** | Notice/Order itself | Exact items the authority demanded — extracted verbatim |
| **Layer 1** | RAG (DB + Live IK + CBDT) | Supporting documents the law requires for a strong defence |

### Section Intelligence
- **130+ Income Tax Act sections** with defences, penalty provisions, and key ratios
- Covers: Unexplained income (68–69D), TDS/TCS (192–206C), Penalties (270A–273B), Reassessment (147–153C), Capital Gains (45–54F), Transfer Pricing (92–92CA), Trust exemptions (11–12AB), and more
- Auto-detected from uploaded PDFs using regex + boundary analysis

### Live Federated Search
- **Indian Kanoon API** — live ITAT/HC/SC judgment retrieval
- **JIT Vectorization** — IK results embedded and ranked at query time (no pre-indexing required)
- **Web search fallback** — Google CSE + Bing for recent circulars and judgments
- **CBDT Circular database** — curated circulars with favour assessment

### AI Synthesis
- OpenRouter API with `google/gemini-2.5-flash` default (configurable)
- FAST tier (Gemini Flash) for extraction; QUALITY tier for legal arguments
- Structured JSON output with `parse_json()` error-resilient parsing
- Temperature=0.0 for citation selection (determinism), 0.3–0.7 for argument drafting

### Data Persistence
- AO context (allegations, rejection reason, additions, demanded items) survives browser refresh
- Per-evidence feedback loop — CA marks outcome after ITAT hearing → boosts future retrieval
- Session-state-first, DB-fallback pattern (no redundant DB hits)

---

## Architecture

```
litigation-intelligence-os/
├── app.py                    # Streamlit entry point (12-phase tabs)
├── config.py                 # All sections, API keys, paths
│
├── modules/
│   ├── phase1_intake.py      # PDF upload, extraction, AO context
│   ├── phase2_evidence.py    # Evidence checklist (Layer 0 + 1)
│   ├── phase3_submissions.py # Submission drafting
│   ├── phase4_strategy.py    # Litigation strategy
│   ├── phase5_winrate.py     # Win probability analysis
│   ├── phase6_sandbox.py     # Argument sandbox
│   ├── phase7_architect.py   # Case architect
│   ├── phase8_workflow.py    # Workflow management
│   ├── phase9_midtrial.py    # Mid-trial tools
│   ├── phase10_warroom.py    # War room
│   ├── phase11_posthearing.py# Post-hearing analysis
│   └── phase12_learning.py   # Learning from outcomes
│
├── ai/
│   ├── ai_client.py          # AIClient abstraction (FAST/QUALITY tiers)
│   ├── openrouter_client.py  # OpenRouter API wrapper
│   ├── gemini_client.py      # Gemini direct API
│   ├── evidence_builder.py   # Evidence generation orchestrator
│   ├── indian_kanoon.py      # Indian Kanoon API client
│   ├── cbdt_data.py          # Curated CBDT circulars
│   └── rag/
│       ├── pipeline.py       # Full RAG orchestration + agentic chain
│       ├── retriever.py      # Hybrid retrieval (vector + FTS + JIT + CBDT)
│       ├── embedder.py       # ChromaDB vector store management
│       ├── reranker.py       # HyDE re-ranking
│       ├── models.py         # RetrievedCase, CourtType, etc.
│       └── fts.py            # SQLite FTS5 utilities
│
├── utils/
│   ├── case_extractor.py     # Universal document classification + extraction
│   ├── pdf_parser.py         # Multi-engine PDF extraction (fitz/plumber/OCR)
│   ├── pii_redactor.py       # PAN/name redaction
│   └── citation_verifier.py  # Citation verification
│
├── database/
│   ├── init_db.py            # Schema + migrations + verified seed data
│   └── queries.py            # All DB read/write operations
│
├── tests/
│   ├── test_case_extractor.py
│   ├── test_rrf_fusion.py
│   ├── test_rag_retrieval.py
│   └── test_section_detection.py
│
├── run_ingest.py             # Ingest .txt judgment files into ChromaDB
├── run_embed.py              # Re-embed existing DB judgments
└── run_harvest.py            # Harvest judgments from scraper sources
```

---

## Quick Start

### Prerequisites
- Python 3.10+
- Tesseract OCR (optional, for scanned PDFs): `choco install tesseract` / `apt install tesseract-ocr`

### Installation

```bash
git clone https://github.com/GVR2007/litigation-intelligence-os.git
cd litigation-intelligence-os
pip install -r requirements.txt
```

### Environment Setup

Create a `.env` file in the project root:

```env
# Required — AI synthesis engine
OPENROUTER_API_KEY=sk-or-...        # https://openrouter.ai (free tier available)

# Required — live judgment search
INDIAN_KANOON_API_KEY=...           # https://api.indiankanoon.org

# Optional — direct Gemini access
GEMINI_API_KEY=...                  # https://aistudio.google.com

# Optional — web search fallback
GOOGLE_CSE_API_KEY=...
GOOGLE_CSE_ID=...
BING_SEARCH_API_KEY=...
```

### Initialize & Run

```bash
# First run — initialize database
python database/init_db.py

# Launch the app
streamlit run app.py
```

### Ingest Judgments (Optional but Recommended)

Place `.txt` judgment files in a `judgments/` folder, then:

```bash
python run_ingest.py        # Parse and ingest .txt files into ChromaDB + SQLite
python run_embed.py         # Generate vector embeddings for all ingested judgments
```

The system works without ingested judgments — it will rely on live Indian Kanoon search.

---

## How It Works — A Typical Workflow

1. **Upload** an assessment order PDF in Phase 1
2. The system **classifies** the document (e.g., "Assessment Order u/s 143(3)") and detects:
   - Sections violated
   - AO allegations in the AO's own words
   - Demanded documents (Layer 0)
   - Additions/disallowances made
3. Move to Phase 2 — **Evidence Engine** builds:
   - **Layer 0**: Exact items from the notice ("provide bank statements for FY...", "explain cash credit of ₹X")
   - **Layer 1**: RAG-recommended supporting documents drawn from precedent analysis
4. The AI fetches relevant **precedents** from 3 parallel pools, fuses them via RRF, then runs a 3-hop agentic citation chain to surface SC/HC judgments
5. Phase 3 drafts **legal submissions** grounded in these precedents
6. After the hearing, mark each evidence item's **outcome** — the system learns which documents tribunals actually accept

---

## What Makes This Different

| Feature | Typical Legal Tools | This System |
|---------|-------------------|-------------|
| Document handling | Fixed templates per doc type | Universal — any document, heading extracted verbatim |
| Evidence source | Manual CA input | Layer 0 (demanded) + Layer 1 (RAG) auto-generated |
| Precedent retrieval | Keyword search | Hybrid: vector + FTS5 + JIT live IK + CBDT + RRF fusion |
| Query construction | Generic section keywords | AO's exact allegation language used as primary signal |
| Citations | AI-generated (unreliable) | Only verified SC/HC citations (real ITR/SCC reporters) + live IK |
| Learning | None | Feedback loop: CA marks outcomes → future retrieval improves |
| Persistence | Lost on refresh | All AO context persisted to SQLite, survives restart |

---

## RAG Pipeline — Technical Deep Dive

### Query Construction
The AO's exact allegation language (not generic section keywords) drives both vector embedding and FTS query construction. Web-anchored terms from live IK results are injected as a 3rd signal tier into the FTS query, expanding retrieval without hallucination.

### JIT Vectorization (Pool B)
Live Indian Kanoon API results are embedded at query time using the same sentence-transformer as the offline ChromaDB store. Results are ranked by cosine similarity and returned as ephemeral `RetrievedCase` objects (negative `db_id`). No pre-indexing required.

### Cross-Pool RRF Fusion
```
score(doc, pool) = Σ 1/(k + rank_in_pool)   for each pool containing doc
```
Deduplication by `citation[:60].lower()` ensures a judgment appearing in multiple pools gets credit from all of them.

### Agentic Citation Chain (3-hop)
1. **Hop 1**: Extract SC citations from top-6 retrieved cases' `key_ratio` using regex
2. **Hop 2**: AI (temperature=0.0) selects which citations are worth fetching (max 3)
3. **Hop 3**: DB lookup first; if not found → IK API live fetch → ephemeral RetrievedCase

### HyDE Re-ranking
A hypothetical ideal judgment (generated by AI for the given facts) is embedded and used as the query vector for a second-pass re-ranking of retrieved cases. This bridges the vocabulary gap between the user's factual query and judgment language.

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `cases` | Core case data + AO context (allegations, additions, doc_heading, notice_requirements) |
| `case_evidence` | Evidence items with Layer 0/1 separation, outcome feedback, tribunal verdict tracking |
| `itat_precedents` | Judgment store + FTS5 virtual table (`citations_fts`) |
| `cbdt_circulars` | CBDT circulars with section mapping and favour assessment |
| `case_arguments` | Generated legal arguments per case |
| `hearings` | Hearing log with outcomes and next dates |
| `judgments` | Final judgment recording with learned patterns |
| `timeline_tasks` | 30/60/90 day task timelines |
| `ocr_validations` | Document validation results |

Schema migrations are additive-only (`ALTER TABLE ADD COLUMN IF NOT EXISTS`) — existing data is never destroyed on upgrade.

---

## Testing

```bash
pytest tests/ -v
```

**43 tests across 4 modules:**
- `test_case_extractor.py` — document classification, requirement extraction
- `test_rrf_fusion.py` — Cross-pool RRF correctness, deduplication, score accumulation
- `test_rag_retrieval.py` — Hybrid retrieval pipeline, JIT ranking, CBDT retrieval
- `test_section_detection.py` — IT Act section detection across 130+ sections


---

## Configuration Reference

All behaviour is controlled via `config.py` and `.env`:

| Key | Source | Purpose |
|-----|--------|---------|
| `OPENROUTER_API_KEY` | `.env` | AI synthesis (primary) |
| `INDIAN_KANOON_API_KEY` | `.env` | Live judgment search |
| `GEMINI_API_KEY` | `.env` | Direct Gemini access (optional) |
| `GEMINI_MODEL` | `.env` | Default: `gemini-2.5-flash` |
| `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_ID` | `.env` | Web search fallback |
| `BING_SEARCH_API_KEY` | `.env` | Bing search fallback |
| `DB_PATH` | `config.py` | SQLite DB location (auto-created) |
| `UPLOADS_DIR` | `config.py` | PDF upload directory |

---

## Roadmap

- [ ] Faceless assessment (144B) dedicated flow
- [ ] Transfer pricing (92–92CA) playbook
- [ ] ITAT e-filing integration
- [ ] WhatsApp hearing reminders
- [ ] Multi-case portfolio dashboard
- [ ] Export to Word/PDF for submission filing
- [ ] Whisper-based audio transcription of hearing notes

---


## License

**Proprietary — All Rights Reserved.**

This software is the exclusive intellectual property of the owner. Viewing this
repository does **not** grant any right to use, copy, modify, or distribute the
code. See [LICENSE](LICENSE) for full terms. Unauthorised use will be prosecuted
under the Indian Copyright Act, 1957 and the IT Act, 2000.

---

## Disclaimer

This software is a research and drafting aid for qualified legal practitioners. It does not constitute legal advice. All citations must be independently verified before submission to any tribunal or court. The maintainers are not responsible for outcomes in actual litigation proceedings.

---

*Built with ❤️ for the Indian CA and tax litigation community.*
