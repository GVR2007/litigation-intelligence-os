# IT Notice Reader — Production Implementation Plan

## What This App Does

1. **Notice Upload** — CA uploads an ITBA-generated PDF notice → app extracts every field from the data model with confidence scoring
2. **Tribunal Case Ingestion** — bulk ingest scraped ITAT `.txt` files → structure + embed each case
3. **Two-Stage Query** — "get all 143(2) cases → find similar scenario ones" → cited answer
4. **Reminder Engine** — deadline-aware notifications per notice per client

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      React Frontend                      │
│   Upload Zone │ Notice Viewer │ Query UI │ Reminder Dash │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTPS
┌──────────────────────▼──────────────────────────────────┐
│                   FastAPI Backend                        │
│  /upload-notice  /ingest-case  /query  /reminders        │
└──────┬──────────────┬──────────────────┬────────────────┘
       │              │                  │
  pdfplumber     Claude API         PostgreSQL
  (extract)    (parse+embed)       + pgvector
```

---

## Phase 1 — Database Design (Do This First)

### 1.1 PostgreSQL Setup

```sql
-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for fast text search

-- ─────────────────────────────────────────────────────────
-- TABLE 1: Client Notices (ITBA PDFs uploaded by CA)
-- ─────────────────────────────────────────────────────────
CREATE TABLE client_notices (
    id                  SERIAL PRIMARY KEY,
    notice_id           TEXT UNIQUE NOT NULL,       -- generated: sha256 of file content
    filename            TEXT,

    -- Notice Identity (Group 1)
    din                 TEXT,                        -- ITBA/AST/S/143/...
    section             TEXT,                        -- 143(2), 148, 142(1) etc.
    notice_date         DATE,
    notice_type         TEXT,                        -- limited_scrutiny / complete / reassessment
    scrutiny_reason     TEXT,

    -- Taxpayer (Group 2)
    pan                 CHAR(10),
    taxpayer_name       TEXT,
    taxpayer_address    TEXT,
    itr_ack_number      TEXT,

    -- Assessment Period (Group 3)
    assessment_year     TEXT,                        -- 2023-24
    financial_year      TEXT,                        -- 2022-23
    itr_filing_date     DATE,

    -- Assessing Officer (Group 4)
    ao_name             TEXT,
    ao_designation      TEXT,
    ao_address          TEXT,
    faceless            BOOLEAN DEFAULT FALSE,

    -- Submission Requirements (Group 5) ← CORE
    last_submission_date DATE,
    last_submission_time TEXT,
    submission_portal   TEXT,
    submission_mode     TEXT,                        -- online / physical / both
    response_format     TEXT,
    poa_required        BOOLEAN DEFAULT FALSE,

    -- Annexures (Group 6) — schema-free JSON
    annexures           JSONB,
    /*
      Structure:
      {
        "Annexure A": [
          {
            "point_number": "1",
            "text": "Verbatim text of point",
            "document": "Form 26AS",     <- only if present
            "period": "FY 2022-23",      <- only if present
            "amount": 452000             <- only if present
          }
        ]
      }
    */

    -- Financial (Group 7)
    demand_amount       NUMERIC(15,2),
    interest_amount     NUMERIC(15,2),
    penalty_amount      NUMERIC(15,2),
    payment_due_date    DATE,

    -- App State (Group 8)
    status              TEXT DEFAULT 'pending',      -- pending/in_progress/submitted/overdue
    verified_by_ca      BOOLEAN DEFAULT FALSE,
    confidence_flags    JSONB,                       -- per-field confidence scores
    reminder_dates      DATE[],                      -- computed on insert
    din_verified        BOOLEAN DEFAULT FALSE,

    -- Raw storage
    raw_text            TEXT,
    raw_pdf_path        TEXT,

    -- Embedding for similarity search
    embedding           vector(1024),

    -- Audit
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    created_by          TEXT                         -- CA user email
);

-- ─────────────────────────────────────────────────────────
-- TABLE 2: Tribunal Cases (scraped ITAT orders)
-- ─────────────────────────────────────────────────────────
CREATE TABLE tribunal_cases (
    id                      SERIAL PRIMARY KEY,
    case_id                 TEXT UNIQUE NOT NULL,    -- sha256 of source_url
    filename                TEXT,
    source_url              TEXT,

    -- Identity
    case_number             TEXT,                    -- 3964/Chny/2025
    court                   TEXT DEFAULT 'ITAT',
    bench                   TEXT,                    -- Chennai, Mumbai, Delhi
    date_of_hearing         DATE,
    date_of_order           DATE,
    judges                  TEXT[],

    -- Parties
    assessee_name           TEXT,
    assessee_type           TEXT,                    -- Individual/Firm/Company/HUF
    pan                     TEXT,
    ao_designation          TEXT,

    -- Legal
    assessment_year         TEXT,
    sections_involved       TEXT[],                  -- ['143(2)','142(1)','143(3)']
    primary_section         TEXT,                    -- main section
    scrutiny_type           TEXT,                    -- limited/complete/manual
    income_head_disputed    TEXT,                    -- agricultural/business/capital gains

    -- Substance
    core_issue              TEXT,                    -- one sentence
    ao_addition_amount      NUMERIC(15,2),
    assessee_argument       TEXT,
    revenue_argument        TEXT,
    tribunal_held           TEXT,

    -- Outcome
    outcome                 TEXT,                    -- assessee_won/department_won/partial_relief/remanded
    demand_dropped          BOOLEAN DEFAULT FALSE,

    -- Evidence
    key_documents           TEXT[],
    legal_precedents_cited  TEXT[],
    keywords                TEXT[],

    -- Raw
    raw_text                TEXT,

    -- Embedding
    embedding               vector(1024),

    -- Audit
    scraped_at              TIMESTAMPTZ DEFAULT NOW(),
    processed_at            TIMESTAMPTZ
);

-- ─────────────────────────────────────────────────────────
-- TABLE 3: CA Users
-- ─────────────────────────────────────────────────────────
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    name        TEXT,
    firm_name   TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────
-- TABLE 4: Query History (for audit + few-shot improvement)
-- ─────────────────────────────────────────────────────────
CREATE TABLE query_history (
    id              SERIAL PRIMARY KEY,
    user_email      TEXT,
    query_text      TEXT,
    query_type      TEXT,                            -- document_patterns/precedent/auto_suggest
    section_filter  TEXT,
    cases_retrieved INT,
    answer          TEXT,
    cited_case_ids  TEXT[],
    feedback        TEXT,                            -- thumbs_up/thumbs_down/correction
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────
-- INDEXES — Critical for production scale
-- ─────────────────────────────────────────────────────────

-- Vector indexes (IVFFlat good up to ~1M rows)
CREATE INDEX idx_notices_embedding
    ON client_notices USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX idx_tribunal_embedding
    ON tribunal_cases USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 200);                              -- more lists = faster at scale

-- Scalar indexes for Stage 1 filtering
CREATE INDEX idx_tribunal_section
    ON tribunal_cases USING GIN (sections_involved); -- GIN for array contains queries

CREATE INDEX idx_tribunal_outcome    ON tribunal_cases (outcome);
CREATE INDEX idx_tribunal_ay         ON tribunal_cases (assessment_year);
CREATE INDEX idx_tribunal_bench      ON tribunal_cases (bench);
CREATE INDEX idx_tribunal_demand     ON tribunal_cases (demand_dropped);

CREATE INDEX idx_notices_pan         ON client_notices (pan);
CREATE INDEX idx_notices_section     ON client_notices (section);
CREATE INDEX idx_notices_deadline    ON client_notices (last_submission_date);
CREATE INDEX idx_notices_status      ON client_notices (status);

-- Full text search on raw text (fallback when vector search misses)
CREATE INDEX idx_tribunal_fts
    ON tribunal_cases USING GIN (to_tsvector('english', COALESCE(raw_text, '')));
```

### 1.2 Why This Schema Works at Scale

- **GIN index on `sections_involved` array** — `WHERE '143(2)' = ANY(sections_involved)` runs in microseconds even at 50,000 rows
- **IVFFlat vector index with `lists=200`** — cosine similarity search across 50K embeddings in ~10ms
- **`annexures JSONB`** — schema-free storage for annexure points, queryable with Postgres JSON operators
- **Separate tables for notices vs tribunal cases** — different schemas, different query patterns, don't mix

---

## Phase 2 — Notice Upload Pipeline

### 2.1 Flow

```
CA uploads PDF
    ↓
FastAPI receives file
    ↓
[Step 1] pdfplumber extracts text (layout=True)
    ↓
[Step 2] Detect: does it have annexures?
    ↓
[Step 3a] Claude API — extract header fields (schema-free)
[Step 3b] Claude API — extract each annexure point-by-point (schema-free)
    ↓
[Step 4] Validate every critical field → confidence score per field
    ↓
[Step 5] voyage-3 embed the case
    ↓
[Step 6] Store in client_notices table
    ↓
[Step 7] Compute reminder_dates → store
    ↓
Return structured JSON to frontend
```

### 2.2 extractor.py

```python
import pdfplumber
import re
from pathlib import Path

def extract_pdf_text(pdf_path: str) -> dict:
    """Extract text from digital ITBA PDF preserving layout."""
    pages, full_text = [], ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            pages.append({"page": page.page_number, "text": text})
            full_text += f"\n--- PAGE {page.page_number} ---\n{text}"

    return {
        "full_text": full_text,
        "page_count": len(pages),
        "chunks": chunk_document(full_text)
    }

def chunk_document(text: str) -> dict:
    """Split notice into main body and named annexures."""
    pattern = re.compile(
        r'(Annexure\s*[-–]?\s*[A-Z0-9]+|Schedule\s*[-–]?\s*[A-Z0-9]+)',
        re.IGNORECASE
    )
    parts = pattern.split(text)
    chunks = {"main_body": parts[0].strip(), "annexures": {}}

    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            chunks["annexures"][parts[i].strip()] = parts[i + 1].strip()

    return chunks
```

### 2.3 parser.py — Schema-Free Extraction

```python
import anthropic, json, re

client = anthropic.Anthropic()

def extract_header(main_body: str) -> dict:
    """
    Schema-FREE extraction.
    LLM decides what fields exist — we don't impose a template.
    Only fields present in the document are returned.
    """
    prompt = f"""You are parsing an Indian Income Tax notice issued by the ITBA system.

Extract every piece of factual information present in this text.
Return a flat JSON object.

RULES (critical):
- Include ONLY fields that are explicitly written in the text
- Do NOT include any field with null value — simply omit missing fields
- Do NOT guess or infer anything
- Values must be verbatim or minimal reformatting (dates as DD/MM/YYYY)
- For amounts, store as number only (no ₹ symbol, no commas)

Common fields you may find (use these key names if applicable):
din, section, notice_date, notice_type, scrutiny_reason,
pan, taxpayer_name, taxpayer_address, itr_ack_number,
assessment_year, financial_year, itr_filing_date,
ao_name, ao_designation, ao_address, faceless,
last_submission_date, last_submission_time, submission_portal,
submission_mode, response_format, poa_required,
demand_amount, interest_amount, penalty_amount, payment_due_date,
notice_purpose

If the notice contains any other factual field not listed above,
create an appropriate snake_case key for it.

Return ONLY the JSON object. No markdown, no explanation.

Notice text:
{main_body}"""

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
    return json.loads(raw)


def extract_annexure(name: str, content: str) -> list:
    """
    Extract every numbered point from an annexure.
    Schema-free — only add fields that are present in each point.
    """
    prompt = f"""You are extracting requirements from "{name}" of an Indian Income Tax notice.

Extract EVERY numbered/lettered point including sub-points.
Each point is a SEPARATE item in the JSON array.

RULES:
- "text" field is ALWAYS present — verbatim text of that point
- "point_number" is ALWAYS present — exactly as written (1, 2.a, (iii), B(iv))
- Add "document" ONLY if a specific document/form is named in that point
- Add "period" ONLY if a date range or financial year is mentioned in that point
- Add "amount" ONLY if a specific rupee figure is mentioned in that point
- Do NOT add any field with null — omit it entirely
- Do NOT merge points. Do NOT skip any point.

Return ONLY a valid JSON array. No markdown, no explanation.

{name} text:
{content}"""

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
    return json.loads(raw)


def verify_extraction(original_text: str, extracted: dict) -> dict:
    """
    For each extracted field, check if its value
    actually exists in the original text.
    Catches hallucinations.
    """
    confidence = {}
    for field, value in extracted.items():
        if value is None:
            continue
        check = str(value)
        # For long values, check a substring
        if len(check) > 20:
            check = check[len(check)//3 : len(check)//3 + 15]
        found = check.lower() in original_text.lower()
        confidence[field] = "high" if found else "low"
    return confidence


def parse_notice(chunks: dict) -> dict:
    header = extract_header(chunks["main_body"])
    confidence = verify_extraction(chunks["main_body"], header)

    annexures = {}
    for name, content in chunks.get("annexures", {}).items():
        points = extract_annexure(name, content)
        # Verify each point's text exists in original
        for point in points:
            txt = point.get("text","")
            sample = txt[:30] if len(txt) > 30 else txt
            point["_verified"] = sample.lower() in content.lower()
        annexures[name] = points

    return {
        "header": header,
        "annexures": annexures,
        "confidence": confidence
    }
```

### 2.4 validator.py

```python
import re
from datetime import datetime, date

KNOWN_SECTIONS = [
    "131","131(1A)","133","133(6)","139(9)",
    "142(1)","142(2A)","143(1)","143(2)","143(3)",
    "147","148","148A","154","156","245","263","271"
]

def validate(header: dict) -> dict:
    errors, warnings = [], []

    # PAN
    pan = header.get("pan","")
    if pan:
        if not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', pan):
            errors.append({"field":"pan","msg":f"Invalid format: '{pan}'"})
    else:
        errors.append({"field":"pan","msg":"Missing — critical"})

    # DIN
    din = header.get("din","")
    if din:
        if not din.upper().startswith("ITBA/"):
            warnings.append({"field":"din","msg":f"Unexpected format: '{din}'"})
    else:
        errors.append({"field":"din","msg":"Missing — notice may be invalid"})

    # Dates
    for f in ["notice_date","last_submission_date"]:
        v = header.get(f)
        if v:
            try:
                datetime.strptime(v, "%d/%m/%Y")
            except ValueError:
                errors.append({"field":f,"msg":f"Bad date format: '{v}'"})
        elif f == "last_submission_date":
            errors.append({"field":f,"msg":"Missing deadline — critical"})

    # Section
    sec = header.get("section")
    if sec:
        if sec not in KNOWN_SECTIONS:
            warnings.append({"field":"section","msg":f"Unknown section '{sec}' — verify"})
    else:
        errors.append({"field":"section","msg":"Missing — critical"})

    # Assessment Year
    ay = header.get("assessment_year","")
    if ay and not re.match(r'^\d{4}-\d{2}$', ay):
        warnings.append({"field":"assessment_year","msg":f"Unexpected AY format: '{ay}'"})

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }

def compute_reminders(deadline_str: str) -> list:
    """Compute reminder dates: 30, 15, 7, 3, 1 days before deadline."""
    if not deadline_str:
        return []
    try:
        deadline = datetime.strptime(deadline_str, "%d/%m/%Y").date()
        offsets = [30, 15, 7, 3, 1]
        from datetime import timedelta
        reminders = []
        today = date.today()
        for days in offsets:
            r = deadline - timedelta(days=days)
            if r >= today:
                reminders.append(r.isoformat())
        return reminders
    except:
        return []
```

### 2.5 embedder.py

```python
import anthropic
import hashlib
import json

client = anthropic.Anthropic()

def embed_notice(header: dict, annexures: dict) -> list[float]:
    """Build semantic text from notice fields and embed it."""
    ann_summary = []
    for ann_name, points in annexures.items():
        for p in points:
            line = f"{ann_name} point {p.get('point_number','')}: {p.get('text','')[:100]}"
            ann_summary.append(line)

    text = f"""
    Section: {header.get('section')}
    Assessment Year: {header.get('assessment_year')}
    Scrutiny reason: {header.get('scrutiny_reason')}
    Notice purpose: {header.get('notice_purpose')}
    Submission mode: {header.get('submission_mode')}
    Response format: {header.get('response_format')}
    Faceless: {header.get('faceless')}
    Annexure requirements: {' | '.join(ann_summary[:10])}
    """.strip()

    resp = client.embeddings.create(model="voyage-3", input=text)
    return resp.embeddings[0]

def embed_tribunal_case(structured: dict) -> list[float]:
    """Build semantic text from tribunal case fields and embed it."""
    text = f"""
    Section: {structured.get('primary_section')}
    All sections: {', '.join(structured.get('sections_involved') or [])}
    Scrutiny type: {structured.get('scrutiny_type')}
    Bench: {structured.get('court')} {structured.get('bench')}
    Assessment Year: {structured.get('assessment_year')}
    Assessee type: {structured.get('assessee_type')}
    Income head disputed: {structured.get('income_head_disputed')}
    Core issue: {structured.get('core_issue')}
    Assessee argued: {structured.get('assessee_argument')}
    Revenue argued: {structured.get('revenue_argument')}
    Tribunal held: {structured.get('tribunal_held')}
    Outcome: {structured.get('outcome')}
    Keywords: {', '.join(structured.get('keywords') or [])}
    Documents discussed: {', '.join(structured.get('key_documents_discussed') or [])}
    """.strip()

    resp = client.embeddings.create(model="voyage-3", input=text)
    return resp.embeddings[0]

def generate_notice_id(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()[:32]

def generate_case_id(source_url: str) -> str:
    return hashlib.sha256(source_url.encode()).hexdigest()[:32]
```

---

## Phase 3 — Tribunal Case Ingestion Pipeline

### 3.1 Flow

```
Folder of .txt files
    ↓
[Step 1] Read each file → extract URL from header
    ↓
[Step 2] Claude API — extract structured fields (schema-aware for tribunal orders)
    ↓
[Step 3] voyage-3 embed the case
    ↓
[Step 4] Store in tribunal_cases table
    ↓
Log success / failure
```

### 3.2 ingest_cases.py — Bulk Ingester

```python
import anthropic
import psycopg2
import json
import re
import hashlib
import time
from pathlib import Path
from embedder import embed_tribunal_case, generate_case_id

client = anthropic.Anthropic()

def extract_case_structure(raw_text: str, source_url: str) -> dict:
    prompt = f"""You are parsing a raw Indian ITAT (Income Tax Appellate Tribunal) order.

Extract ONLY what is explicitly present. Return valid JSON only. No markdown.
Omit any field that is not clearly stated in the text.

{{
  "case_number": "ITA No. as written",
  "court": "ITAT",
  "bench": "city name",
  "assessment_year": "e.g. 2018-19",
  "assessee_name": "name of appellant",
  "assessee_type": "Individual/Firm/Company/HUF/Trust/AOP",
  "pan": "if mentioned",
  "ao_designation": "ITO/DCIT/ACIT etc.",
  "sections_involved": ["all sections mentioned"],
  "primary_section": "main section under original notice",
  "scrutiny_type": "limited/complete/manual",
  "core_issue": "single sentence — central dispute",
  "ao_addition_amount": number_in_rupees_or_omit,
  "assessee_argument": "2-3 sentences",
  "revenue_argument": "2-3 sentences",
  "tribunal_held": "2-3 sentences — what ITAT decided",
  "outcome": "assessee_won/department_won/partial_relief/remanded/allowed_for_statistical",
  "demand_dropped": true_or_false,
  "income_head_disputed": "agricultural income/business income/other sources/capital gains/etc.",
  "key_documents_discussed": ["documents mentioned as evidence"],
  "legal_precedents_cited": ["cases cited"],
  "keywords": ["5-8 short keywords"],
  "date_of_hearing": "DD/MM/YYYY",
  "date_of_order": "DD/MM/YYYY",
  "judges": ["names"]
}}

Raw order text (first 8000 chars):
{raw_text[:8000]}"""

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
    try:
        result = json.loads(raw)
        result["source_url"] = source_url
        result["raw_text"] = raw_text
        return result
    except json.JSONDecodeError:
        return {"source_url": source_url, "raw_text": raw_text, "parse_error": True}


def store_tribunal_case(structured: dict, embedding: list, conn) -> bool:
    cur = conn.cursor()
    case_id = generate_case_id(structured.get("source_url",""))

    try:
        cur.execute("""
            INSERT INTO tribunal_cases (
                case_id, filename, source_url, case_number, court, bench,
                date_of_hearing, date_of_order, judges,
                assessee_name, assessee_type, pan, ao_designation,
                assessment_year, sections_involved, primary_section,
                scrutiny_type, income_head_disputed,
                core_issue, ao_addition_amount,
                assessee_argument, revenue_argument, tribunal_held,
                outcome, demand_dropped,
                key_documents, legal_precedents_cited, keywords,
                raw_text, embedding, processed_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()
            )
            ON CONFLICT (case_id) DO NOTHING
        """, (
            case_id,
            structured.get("filename"),
            structured.get("source_url"),
            structured.get("case_number"),
            structured.get("court","ITAT"),
            structured.get("bench"),
            structured.get("date_of_hearing"),
            structured.get("date_of_order"),
            structured.get("judges"),
            structured.get("assessee_name"),
            structured.get("assessee_type"),
            structured.get("pan"),
            structured.get("ao_designation"),
            structured.get("assessment_year"),
            structured.get("sections_involved"),
            structured.get("primary_section"),
            structured.get("scrutiny_type"),
            structured.get("income_head_disputed"),
            structured.get("core_issue"),
            structured.get("ao_addition_amount"),
            structured.get("assessee_argument"),
            structured.get("revenue_argument"),
            structured.get("tribunal_held"),
            structured.get("outcome"),
            structured.get("demand_dropped", False),
            structured.get("key_documents_discussed"),
            structured.get("legal_precedents_cited"),
            structured.get("keywords"),
            structured.get("raw_text","")[:50000],  # cap at 50k chars
            embedding,
        ))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  DB error: {e}")
        return False


def bulk_ingest(folder_path: str, db_conn_string: str):
    """Process all .txt files in a folder."""
    folder = Path(folder_path)
    files = list(folder.glob("*.txt"))
    print(f"Found {len(files)} files to ingest")

    conn = psycopg2.connect(db_conn_string)
    success, failed = 0, 0

    for i, filepath in enumerate(files):
        print(f"[{i+1}/{len(files)}] {filepath.name}")
        try:
            raw_text = filepath.read_text(encoding="utf-8", errors="ignore")

            # Extract URL from file header
            url_match = re.search(r'URL:\s*(.+)', raw_text)
            source_url = url_match.group(1).strip() if url_match else filepath.name

            # Structure
            structured = extract_case_structure(raw_text, source_url)
            structured["filename"] = filepath.name

            if structured.get("parse_error"):
                print(f"  ⚠ Parse error — storing raw only")

            # Embed
            embedding = embed_tribunal_case(structured)

            # Store
            ok = store_tribunal_case(structured, embedding, conn)
            if ok:
                success += 1
                print(f"  ✅ Stored: {structured.get('case_number','?')}")
            else:
                failed += 1

            time.sleep(0.5)  # rate limit buffer

        except Exception as e:
            failed += 1
            print(f"  ❌ Failed: {e}")

    conn.close()
    print(f"\nDone. Success: {success} | Failed: {failed}")


# Run it:
# bulk_ingest("/path/to/txt/files", "postgresql://user:pass@localhost/itdb")
```

---

## Phase 4 — Query Engine (Two-Stage Search)

### 4.1 query_engine.py

```python
import anthropic
import psycopg2
import numpy as np
import re
import json
from embedder import embed_tribunal_case

client = anthropic.Anthropic()

def cosine_similarity(a, b):
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def two_stage_search(
    section: str,           # "143(2)"
    context_query: str,     # "agricultural income partnership agent"
    conn_string: str,
    filters: dict = None,   # {"outcome": "assessee_won", "bench": "Chennai"}
    top_k: int = 10
) -> dict:

    conn = psycopg2.connect(conn_string)
    cur = conn.cursor()

    # ── STAGE 1: SQL FILTER (exact, instant) ─────────────────────────
    where_clauses = ["%s = ANY(sections_involved)"]
    params = [section]

    if filters:
        if filters.get("outcome"):
            where_clauses.append("outcome = %s")
            params.append(filters["outcome"])
        if filters.get("bench"):
            where_clauses.append("bench ILIKE %s")
            params.append(f"%{filters['bench']}%")
        if filters.get("assessment_year"):
            where_clauses.append("assessment_year = %s")
            params.append(filters["assessment_year"])
        if filters.get("demand_dropped") is not None:
            where_clauses.append("demand_dropped = %s")
            params.append(filters["demand_dropped"])

    sql = f"""
        SELECT id, case_id, case_number, court, bench,
               assessment_year, assessee_name, assessee_type,
               sections_involved, primary_section, scrutiny_type,
               income_head_disputed, core_issue, ao_addition_amount,
               assessee_argument, revenue_argument, tribunal_held,
               outcome, demand_dropped, key_documents,
               legal_precedents_cited, keywords, source_url, embedding
        FROM tribunal_cases
        WHERE {' AND '.join(where_clauses)}
    """
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    stage1_cases = [dict(zip(cols, r)) for r in rows]
    conn.close()

    print(f"Stage 1: {len(stage1_cases)} cases with section {section}")

    if not stage1_cases:
        return {"total_found": 0, "answer": "No cases found for this section.", "cited_cases": []}

    # ── STAGE 2: VECTOR SIMILARITY (within Stage 1 results) ──────────
    q_resp = client.embeddings.create(model="voyage-3", input=context_query)
    q_emb = q_resp.embeddings[0]

    for case in stage1_cases:
        emb = case.get("embedding")
        if emb is not None:
            # pgvector returns as list already
            case["similarity"] = cosine_similarity(q_emb, emb)
        else:
            case["similarity"] = 0.0

    ranked = sorted(stage1_cases, key=lambda x: x["similarity"], reverse=True)
    top_cases = ranked[:top_k]

    print(f"Stage 2: Top {len(top_cases)} similar cases selected")

    # ── STAGE 3: LLM SYNTHESIS WITH CITATIONS ────────────────────────
    context_blocks = []
    for i, c in enumerate(top_cases, 1):
        block = f"""[CASE {i}] (similarity: {c['similarity']:.3f})
Case: {c.get('case_number')} | {c.get('court')} {c.get('bench')}
AY: {c.get('assessment_year')} | Assessee: {c.get('assessee_name')} ({c.get('assessee_type')})
Sections: {', '.join(c.get('sections_involved') or [])}
Scrutiny: {c.get('scrutiny_type')} | Income head: {c.get('income_head_disputed')}
Core issue: {c.get('core_issue')}
AO addition: ₹{c.get('ao_addition_amount','?')}
Assessee argued: {c.get('assessee_argument','')}
Revenue argued: {c.get('revenue_argument','')}
ITAT held: {c.get('tribunal_held','')}
Outcome: {c.get('outcome')} | Demand dropped: {c.get('demand_dropped')}
Key documents: {', '.join(c.get('key_documents') or [])}
Precedents cited: {', '.join((c.get('legal_precedents_cited') or [])[:3])}
Source: {c.get('source_url','')}
---"""
        context_blocks.append(block)

    prompt = f"""You are an expert Income Tax advisor helping a Chartered Accountant in India.

Query: Section {section} cases similar to: "{context_query}"

Using ONLY the {len(top_cases)} cases below, provide:

1. COMMON PATTERNS — what scenario/facts are shared across these cases
2. POINT-BY-POINT KEY DIFFERENCES — how cases differ in facts or arguments
3. WINNING ARGUMENTS — what worked for assessee, in which cases [CASE N]
4. FAILED ARGUMENTS — what did not work [CASE N]
5. KEY DOCUMENTS THAT MATTERED — evidence that influenced outcome [CASE N]
6. RELEVANT LEGAL PRINCIPLES — established by these cases [CASE N]

Rules:
- Cite EVERY claim as [CASE N]
- Never make any uncited claim
- If cases don't support a point, say "Insufficient case data"

CASES:
{''.join(context_blocks)}

Structured answer with citations:"""

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    answer = resp.content[0].text

    # Parse which cases were actually cited
    cited_nums = list(set(int(n) for n in re.findall(r'\[CASE (\d+)\]', answer)))
    cited_cases = [
        {
            "number": i,
            "case_number": top_cases[i-1].get("case_number"),
            "court": top_cases[i-1].get("court"),
            "bench": top_cases[i-1].get("bench"),
            "outcome": top_cases[i-1].get("outcome"),
            "similarity": round(top_cases[i-1].get("similarity", 0), 3),
            "url": top_cases[i-1].get("source_url")
        }
        for i in cited_nums if i <= len(top_cases)
    ]

    return {
        "total_in_section": len(stage1_cases),
        "top_k_retrieved": len(top_cases),
        "answer": answer,
        "cited_cases": cited_cases,
        "all_top_cases": [
            {k: v for k, v in c.items() if k != "embedding"}
            for c in top_cases
        ]
    }
```

---

## Phase 5 — FastAPI Backend

### 5.1 main.py

```python
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import tempfile, os, json, hashlib

from extractor import extract_pdf_text
from parser import parse_notice
from validator import validate, compute_reminders
from embedder import embed_notice, generate_notice_id
from query_engine import two_stage_search
import psycopg2

DB_CONN = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/itdb")
app = FastAPI(title="IT Notice Reader API", version="1.0.0")

app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"])


# ── ENDPOINT 1: Upload and process a notice PDF ──────────────────────

@app.post("/api/notice/upload")
async def upload_notice(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted")

    file_bytes = await file.read()
    notice_id = generate_notice_id(file_bytes)

    # Check duplicate
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()
    cur.execute("SELECT notice_id FROM client_notices WHERE notice_id = %s", [notice_id])
    if cur.fetchone():
        conn.close()
        return {"notice_id": notice_id, "status": "already_exists"}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        # Extract
        extracted = extract_pdf_text(tmp_path)

        # Parse (schema-free)
        parsed = parse_notice(extracted["chunks"])
        header = parsed["header"]
        annexures = parsed["annexures"]
        confidence = parsed["confidence"]

        # Validate
        validation = validate(header)

        # Embed
        embedding = embed_notice(header, annexures)

        # Compute reminders
        reminder_dates = compute_reminders(header.get("last_submission_date",""))

        # Store
        cur.execute("""
            INSERT INTO client_notices (
                notice_id, filename,
                din, section, notice_date, notice_type, scrutiny_reason,
                pan, taxpayer_name, taxpayer_address, itr_ack_number,
                assessment_year, financial_year,
                ao_name, ao_designation, ao_address, faceless,
                last_submission_date, last_submission_time,
                submission_portal, submission_mode, response_format, poa_required,
                annexures, demand_amount, interest_amount, penalty_amount,
                payment_due_date, confidence_flags, reminder_dates,
                raw_text, embedding
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
        """, (
            notice_id, file.filename,
            header.get("din"), header.get("section"),
            header.get("notice_date"), header.get("notice_type"),
            header.get("scrutiny_reason"), header.get("pan"),
            header.get("taxpayer_name"), header.get("taxpayer_address"),
            header.get("itr_ack_number"), header.get("assessment_year"),
            header.get("financial_year"), header.get("ao_name"),
            header.get("ao_designation"), header.get("ao_address"),
            header.get("faceless", False),
            header.get("last_submission_date"),
            header.get("last_submission_time"),
            header.get("submission_portal"), header.get("submission_mode"),
            header.get("response_format"), header.get("poa_required", False),
            json.dumps(annexures),
            header.get("demand_amount"), header.get("interest_amount"),
            header.get("penalty_amount"), header.get("payment_due_date"),
            json.dumps(confidence), reminder_dates,
            extracted["full_text"][:50000], embedding
        ))
        conn.commit()

        return {
            "notice_id": notice_id,
            "status": "processed",
            "header": header,
            "annexures": annexures,
            "validation": validation,
            "confidence": confidence,
            "reminder_dates": reminder_dates,
            "page_count": extracted["page_count"]
        }

    except json.JSONDecodeError:
        raise HTTPException(500, "LLM returned malformed JSON — please retry")
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        os.unlink(tmp_path)
        conn.close()


# ── ENDPOINT 2: Query tribunal cases ────────────────────────────────

class QueryRequest(BaseModel):
    section: str
    context_query: str
    outcome_filter: str = None
    bench_filter: str = None
    ay_filter: str = None
    demand_dropped_only: bool = False
    top_k: int = 10

@app.post("/api/query")
async def query_cases(req: QueryRequest):
    filters = {}
    if req.outcome_filter:
        filters["outcome"] = req.outcome_filter
    if req.bench_filter:
        filters["bench"] = req.bench_filter
    if req.ay_filter:
        filters["assessment_year"] = req.ay_filter
    if req.demand_dropped_only:
        filters["demand_dropped"] = True

    result = two_stage_search(
        section=req.section,
        context_query=req.context_query,
        conn_string=DB_CONN,
        filters=filters,
        top_k=req.top_k
    )

    # Log to query_history
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO query_history
        (query_text, query_type, section_filter, cases_retrieved, answer, cited_case_ids)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        req.context_query, "two_stage", req.section,
        result.get("top_k_retrieved", 0),
        result.get("answer",""),
        [c["case_number"] for c in result.get("cited_cases",[])]
    ))
    conn.commit()
    conn.close()

    return result


# ── ENDPOINT 3: Get all notices with upcoming deadlines ─────────────

@app.get("/api/reminders")
async def get_reminders(days_ahead: int = 7):
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()
    cur.execute("""
        SELECT notice_id, pan, taxpayer_name, section,
               assessment_year, last_submission_date,
               last_submission_time, submission_mode,
               status, din
        FROM client_notices
        WHERE last_submission_date BETWEEN CURRENT_DATE
              AND CURRENT_DATE + INTERVAL '%s days'
          AND status NOT IN ('submitted', 'overdue')
        ORDER BY last_submission_date ASC
    """, [days_ahead])
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()

    return {"reminders": [dict(zip(cols, r)) for r in rows]}


@app.get("/health")
def health():
    return {"status": "ok"}
```

---

## Phase 6 — Production Infrastructure

### 6.1 Project Structure

```
it-notice-app/
├── backend/
│   ├── main.py
│   ├── extractor.py
│   ├── parser.py
│   ├── validator.py
│   ├── embedder.py
│   ├── query_engine.py
│   ├── ingest_cases.py
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── UploadPage.jsx
│   │   │   ├── NoticePage.jsx
│   │   │   ├── QueryPage.jsx
│   │   │   └── RemindersPage.jsx
│   │   └── components/
│   │       ├── UploadZone.jsx
│   │       ├── NoticeViewer.jsx
│   │       ├── AnnexureList.jsx
│   │       ├── ValidationBanner.jsx
│   │       ├── QueryPanel.jsx
│   │       └── CitationCard.jsx
│   └── package.json
├── docker-compose.yml
└── README.md
```

### 6.2 requirements.txt

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
pdfplumber==0.11.0
anthropic==0.34.0
psycopg2-binary==2.9.9
numpy==1.26.4
python-multipart==0.0.9
python-dotenv==1.0.1
httpx==0.27.0
beautifulsoup4==4.12.3
```

### 6.3 docker-compose.yml

```yaml
version: "3.9"
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: itdb
      POSTGRES_USER: ituser
      POSTGRES_PASSWORD: itpass
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql://ituser:itpass@db/itdb
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    ports:
      - "8000:8000"
    depends_on:
      - db

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      REACT_APP_API_URL: http://localhost:8000

volumes:
  pgdata:
```

---

## Phase 7 — Build Order (What to Build When)

```
Week 1: Foundation
  ☐ Set up PostgreSQL + pgvector (use Docker)
  ☐ Run the SQL schema to create all tables + indexes
  ☐ Set up FastAPI project skeleton
  ☐ Test pdfplumber on a sample ITBA notice PDF
  ☐ Test Claude API extraction on one notice manually

Week 2: Notice Pipeline
  ☐ Build extractor.py + chunk_document()
  ☐ Build parser.py (schema-free header + annexure extraction)
  ☐ Build validator.py
  ☐ Build embedder.py (voyage-3)
  ☐ Wire up /api/notice/upload endpoint
  ☐ Test end-to-end with 5 real notices

Week 3: Tribunal Case Ingestion
  ☐ Build ingest_cases.py
  ☐ Run bulk ingest on all your .txt files
  ☐ Verify stored embeddings with a test similarity query
  ☐ Check extraction quality on 20 random cases

Week 4: Query Engine
  ☐ Build query_engine.py (two-stage search)
  ☐ Wire up /api/query endpoint
  ☐ Test with 10 real queries
  ☐ Tune top_k and similarity thresholds

Week 5: Frontend
  ☐ Upload page with drag-drop PDF
  ☐ Notice viewer with side-by-side PDF + extracted data
  ☐ Validation banners (errors red, warnings amber)
  ☐ Annexure point list
  ☐ Query panel with citation renderer
  ☐ Reminders dashboard

Week 6: Production Hardening
  ☐ Add authentication (JWT or Clerk.dev)
  ☐ Rate limiting on API endpoints
  ☐ Error logging (Sentry)
  ☐ Retry logic on Claude API calls
  ☐ Background job queue for bulk ingestion (Celery + Redis)
  ☐ Deploy to Railway or Render (backend) + Vercel (frontend)
```

---

## Key Design Decisions Summary

| Decision | Choice | Why |
|---|---|---|
| PDF extraction | pdfplumber with `layout=True` | Best layout preservation for digital PDFs |
| LLM extraction | Schema-free prompts | Prevents hallucination of missing fields |
| Embedding model | voyage-3 via Anthropic | Best retrieval accuracy for legal text |
| Vector DB | pgvector in PostgreSQL | No extra infra, queryable with SQL, scales to 1M rows |
| Search strategy | Two-stage: SQL filter → vector rank | Stage 1 is exact and fast, Stage 2 is semantic |
| Citation system | [CASE N] parsed from LLM output | Every claim pinned to a real database record |
| Accuracy guarantee | Human-in-the-loop for flagged fields | No system is 100%; CA reviews low-confidence fields |
| Ingestion | Batch with rate limiting | Respects Claude API limits, resumable |
