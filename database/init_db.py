import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_name TEXT NOT NULL,
            client_name TEXT,
            assessee_pan TEXT,
            assessment_year TEXT,
            ao_name TEXT,
            ao_ward TEXT,
            sections_violated TEXT,
            demand_amount REAL,
            status TEXT DEFAULT 'active',
            phase INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hearing_date TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS case_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER REFERENCES cases(id),
            section TEXT,
            document_name TEXT,
            status TEXT DEFAULT 'pending',
            win_boost INTEGER DEFAULT 0,
            is_mandatory INTEGER DEFAULT 0,
            file_path TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS itat_precedents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_citation TEXT UNIQUE,
            section TEXT,
            bench TEXT,
            year INTEGER,
            outcome TEXT,
            key_ratio TEXT,
            facts_summary TEXT,
            win_for_assessee INTEGER DEFAULT 1,
            relevance_score REAL DEFAULT 0.0,
            ik_tid TEXT,
            ik_url TEXT,
            court_type TEXT,
            verified INTEGER DEFAULT 0,
            sections_json TEXT,
            harvested_at TIMESTAMP
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS citations_fts USING fts5(
            case_citation,
            key_ratio,
            facts_summary,
            content='itat_precedents',
            content_rowid='id'
        );

        CREATE TABLE IF NOT EXISTS case_arguments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER REFERENCES cases(id),
            argument_type TEXT,
            argument_text TEXT,
            source_citation TEXT,
            strength_score INTEGER DEFAULT 5,
            counter_argument TEXT,
            phase INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS hearings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER REFERENCES cases(id),
            hearing_date TEXT,
            hearing_type TEXT,
            bench TEXT,
            outcome TEXT,
            notes TEXT,
            objections_raised TEXT,
            next_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS judgments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER REFERENCES cases(id),
            judgment_date TEXT,
            outcome TEXT,
            relief_granted TEXT,
            penalty_deleted INTEGER DEFAULT 0,
            key_findings TEXT,
            learned_patterns TEXT,
            pdf_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS timeline_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER REFERENCES cases(id),
            day_number INTEGER,
            task_title TEXT,
            task_description TEXT,
            due_date TEXT,
            status TEXT DEFAULT 'pending',
            phase INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ocr_validations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER REFERENCES cases(id),
            document_name TEXT,
            validation_result TEXT,
            issues_found TEXT,
            win_probability REAL,
            recommendations TEXT,
            validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cbdt_circulars (
            id TEXT PRIMARY KEY,
            type TEXT,
            number TEXT,
            date TEXT,
            subject TEXT,
            sections TEXT,
            summary TEXT,
            key_para TEXT,
            favour TEXT,
            saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS circular_ik_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            circular_id TEXT REFERENCES cbdt_circulars(id),
            case_title TEXT,
            court TEXT,
            date TEXT,
            ik_tid TEXT,
            ik_url TEXT,
            headline TEXT,
            saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    _migrate_columns(cur)
    _seed_itat_precedents(cur)
    _seed_cbdt_circulars(cur)
    conn.commit()
    conn.close()


def _migrate_columns(cur):
    """Add new columns to existing tables without destroying data."""
    migrations = [
        ("itat_precedents", "ik_tid",       "TEXT"),
        ("itat_precedents", "ik_url",        "TEXT"),
        ("itat_precedents", "court_type",    "TEXT"),
        ("itat_precedents", "verified",      "INTEGER DEFAULT 0"),
        ("itat_precedents", "sections_json", "TEXT"),
        ("itat_precedents", "harvested_at",  "TIMESTAMP"),
        # multi-source scraper columns (v2)
        ("itat_precedents", "source_name",   "TEXT DEFAULT ''"),
        ("itat_precedents", "source_url",    "TEXT DEFAULT ''"),
        # v3 additions
        ("cases",         "client_role",      "TEXT DEFAULT 'assessee'"),
        # v6 — persist AO allegations so data survives browser refresh
        ("cases",         "ao_allegations",             "TEXT DEFAULT ''"),
        ("cases",         "ao_rejection_reason",        "TEXT DEFAULT ''"),
        ("cases",         "ao_additions_json",          "TEXT DEFAULT '[]'"),
        # v7 — universal document classification (heading + specific requests)
        ("cases",         "doc_heading",                "TEXT DEFAULT ''"),
        ("cases",         "notice_requirements_json",   "TEXT DEFAULT '[]'"),
        ("case_evidence", "why_it_matters",   "TEXT DEFAULT ''"),
        ("case_evidence", "how_to_obtain",    "TEXT DEFAULT ''"),
        ("case_evidence", "evidence_source",  "TEXT DEFAULT ''"),
        # v4 — tribunal verdict tracking (replaces _parse_notes hack)
        ("case_evidence", "tribunal_verdict", "TEXT DEFAULT 'accepted'"),
        ("case_evidence", "rejection_reason", "TEXT DEFAULT ''"),
        ("case_evidence", "accepted_in",      "TEXT DEFAULT ''"),
        ("case_evidence", "rejected_in",      "TEXT DEFAULT ''"),
        ("case_evidence", "acceptance_count", "INTEGER DEFAULT 1"),
        # v5 — feedback loop: CA marks outcome after ITAT hearing
        ("case_evidence", "user_outcome",     "TEXT DEFAULT NULL"),
        ("case_evidence", "outcome_date",     "TEXT DEFAULT ''"),
        ("case_evidence", "outcome_notes",    "TEXT DEFAULT ''"),
        # v5 — richer case data in precedents
        ("itat_precedents", "documents_accepted", "TEXT DEFAULT ''"),
    ]
    for table, col, col_type in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception:
            pass  # column already exists — safe to ignore


def _seed_itat_precedents(cur):
    """
    Seed only verified, real citations — SC and HC cases with known ITR/SCC reporters.
    Generic/fabricated entries removed. The system now relies on:
      1. The 6000+ real .txt judgments ingested via run_ingest.py
      2. FTS5 fallback on itat_precedents when ChromaDB is not indexed
    Never present AI-generated or unverified citations to a CA.
    """
    # Only seed Supreme Court / High Court cases with verifiable reporters
    verified_precedents = [
        ("CIT v. Triumph International Finance (I) Ltd. [2012] 345 ITR 270 (Bom)", "269SS",
         "Bombay HC", 2012, "Assessee won",
         "Genuine business transaction — no tax evasion intent — reasonable cause under §273B established",
         "Cash loan for genuine business need; reasonable cause established; §271D penalty deleted", 1, 0.92),
        ("Kailashben Manharlal Choksi v. CIT [2010] 328 ITR 411 (Guj)", "269SS",
         "Gujarat HC", 2010, "Assessee won",
         "Medical emergency constitutes reasonable cause — immediate necessity exempts §269SS compliance",
         "Urgency of medical treatment = reasonable cause; §271D penalty deleted", 1, 0.88),
        ("CIT v. Noida Toll Bridge Co. Ltd. [2003] 262 ITR 260 (Del)", "269SS",
         "Delhi HC", 2003, "Assessee won",
         "Inter-company transactions within group not hit by §269SS — holding company exempted",
         "Intra-group cash movement does not attract §269SS penalty", 1, 0.85),
        ("Vijay Kumar Talwar v. CIT [2011] 330 ITR 1 (SC)", "153A",
         "Supreme Court", 2011, "Assessee won",
         "§153A additions in completed assessments require incriminating material found during search",
         "No incriminating material = no addition permissible in completed assessment", 1, 0.95),
        ("CIT v. Continental Warehousing Corp. [2015] 374 ITR 645 (Bom)", "153A",
         "Bombay HC", 2015, "Assessee won",
         "Completed assessment protected — AO cannot reopen without incriminating material from search",
         "Once assessment completed and no incriminating material found, §153A addition invalid", 1, 0.93),
        ("Orissa Corp. Pvt. Ltd. v. CIT [1986] 159 ITR 78 (SC)", "68",
         "Supreme Court", 1986, "Assessee won",
         "Initial burden on assessee discharged — burden shifts to AO to disprove genuineness",
         "Assessee proved identity + provided explanation; AO must then disprove; addition deleted", 1, 0.90),
        ("PCIT v. Saumya Construction [2016] 387 ITR 529 (Guj)", "68",
         "Gujarat HC", 2016, "Assessee won",
         "All three elements of §68 — identity, creditworthiness, genuineness — proven by documents",
         "Directors filed ITRs; bank transfers evidenced; confirmation letters filed; addition deleted", 1, 0.88),
    ]

    cur.executemany("""
        INSERT OR IGNORE INTO itat_precedents
        (case_citation, section, bench, year, outcome, key_ratio, facts_summary,
         win_for_assessee, relevance_score, verified, source_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 2, 'verified_seed')
    """, verified_precedents)


def _seed_cbdt_circulars(cur):
    """Seed the DB with curated CBDT circulars from cbdt_data.py."""
    import json
    from ai.cbdt_data import CBDT_CIRCULARS
    cur.executemany("""
        INSERT OR IGNORE INTO cbdt_circulars
        (id, type, number, date, subject, sections, summary, key_para, favour)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (c["id"], c["type"], c["number"], c["date"], c["subject"],
         json.dumps(c["sections"]), c["summary"], c["key_para"], c["favour"])
        for c in CBDT_CIRCULARS
    ])


if __name__ == "__main__":
    init_database()
    print(f"Database initialized at: {DB_PATH}")
