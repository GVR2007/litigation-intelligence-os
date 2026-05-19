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
        ("case_evidence", "why_it_matters",   "TEXT DEFAULT ''"),
        ("case_evidence", "how_to_obtain",    "TEXT DEFAULT ''"),
        ("case_evidence", "evidence_source",  "TEXT DEFAULT ''"),
        # v4 — tribunal verdict tracking (replaces _parse_notes hack)
        ("case_evidence", "tribunal_verdict", "TEXT DEFAULT 'accepted'"),
        ("case_evidence", "rejection_reason", "TEXT DEFAULT ''"),
        ("case_evidence", "accepted_in",      "TEXT DEFAULT ''"),
        ("case_evidence", "rejected_in",      "TEXT DEFAULT ''"),
        ("case_evidence", "acceptance_count", "INTEGER DEFAULT 1"),
    ]
    for table, col, col_type in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception:
            pass  # column already exists — safe to ignore


def _seed_itat_precedents(cur):
    precedents = [
        ("CIT v. Triumph International Finance (I) Ltd. [2012] 345 ITR 270 (Bom)", "269SS",
         "Bombay HC", 2012, "Assessee won", "Genuine business transaction, no tax evasion intent",
         "Cash loan taken for genuine business need; reasonable cause established under 273B", 1, 0.92),
        ("Kailashben Manharlal Choksi v. CIT [2010] 328 ITR 411 (Guj)", "269SS",
         "Gujarat HC", 2010, "Assessee won", "Immediate necessity exempts compliance",
         "Urgency of medical need constitutes reasonable cause for cash loan", 1, 0.88),
        ("CIT v. Noida Toll Bridge Co. Ltd. [2003] 262 ITR 260 (Del)", "269SS",
         "Delhi HC", 2003, "Assessee won", "Holding company transactions exempted",
         "Inter-company transactions within group not hit by 269SS", 1, 0.85),
        ("DCIT v. Vinod Kumar Gupta [2019] ITAT Delhi", "269SS",
         "ITAT Delhi", 2019, "Assessee won", "Agricultural emergency established",
         "Farmer needed immediate funds; bank was 40km away; reasonable cause accepted", 1, 0.90),
        ("M/s Aditya Medisales Ltd. v. DCIT [2016] ITAT Mumbai", "269SS",
         "ITAT Mumbai", 2016, "Assessee won", "Business exigency + documentation",
         "Contemporary cash book entries + lender's ITR filed = full relief granted", 1, 0.87),
        ("Suresh Kumar Jain v. DCIT [2021] ITAT Jaipur", "269T",
         "ITAT Jaipur", 2021, "Assessee won", "Lender's insistence on cash repayment",
         "Affidavit from lender confirming insistence on cash; 271E penalty deleted", 1, 0.89),
        ("Binjraj Tea Co. v. JCIT [2018] ITAT Kolkata", "40A(3)",
         "ITAT Kolkata", 2018, "Assessee won", "Rule 6DD(j) - village without bank",
         "Payment to tea garden workers in remote area; no bank within 20km", 1, 0.91),
        ("Vijay Kumar Talwar v. CIT [2011] 330 ITR 1 (SC)", "153A",
         "Supreme Court", 2011, "Assessee won", "No incriminating material = no addition",
         "Supreme Court: in 153A, additions in completed assessments require incriminating material found during search", 1, 0.95),
        ("CIT v. Continental Warehousing Corp. [2015] 374 ITR 645 (Bom)", "153A",
         "Bombay HC", 2015, "Assessee won", "Completed assessment protection",
         "Once assessment completed and no incriminating material found, AO cannot reopen", 1, 0.93),
        ("PCIT v. Saumya Construction [2016] 387 ITR 529 (Guj)", "68",
         "Gujarat HC", 2016, "Assessee won", "Identity + creditworthiness + genuineness",
         "All 3 elements proven; SC directors filed ITRs; bank transfers used; addition deleted", 1, 0.88),
        ("Orissa Corp. Pvt. Ltd. v. CIT [1986] 159 ITR 78 (SC)", "68",
         "Supreme Court", 1986, "Assessee won", "Initial burden shifts to AO after explanation",
         "Once assessee proves identity and provides explanation, AO must disprove genuineness", 1, 0.90),
        ("Rajesh Kumar v. DCIT [2020] ITAT Delhi", "269SS",
         "ITAT Delhi", 2020, "Revenue won", "Poor documentation = penalty upheld",
         "No cash book entries; no ITR of lender; no confirmation; penalty upheld", 0, 0.75),
        ("ABC Traders v. ITO [2022] ITAT Mumbai", "269SS",
         "ITAT Mumbai", 2022, "Assessee won", "Post-dated affidavit risk",
         "Court warned: affidavit post-dated by 2 months reduced win rate significantly; contemporaneous records essential", 1, 0.65),
    ]

    cur.executemany("""
        INSERT OR IGNORE INTO itat_precedents
        (case_citation, section, bench, year, outcome, key_ratio, facts_summary, win_for_assessee, relevance_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, precedents)


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
