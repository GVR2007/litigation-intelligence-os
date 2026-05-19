import json
from database.init_db import get_connection


def create_case(case_name, client_name, assessee_pan, assessment_year,
                ao_name, ao_ward, sections_violated, demand_amount,
                hearing_date=None, client_role="assessee"):
    conn = get_connection()
    cur = conn.cursor()
    sections_str = json.dumps(sections_violated) if isinstance(sections_violated, list) else sections_violated
    cur.execute("""
        INSERT INTO cases (case_name, client_name, assessee_pan, assessment_year,
                           ao_name, ao_ward, sections_violated, demand_amount,
                           hearing_date, client_role)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (case_name, client_name, assessee_pan, assessment_year,
          ao_name, ao_ward, sections_str, demand_amount, hearing_date, client_role))
    case_id = cur.lastrowid
    conn.commit()
    conn.close()
    return case_id


def get_all_cases():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cases ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_case(case_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cases WHERE id = ?", (case_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_case_phase(case_id, phase):
    conn = get_connection()
    conn.execute("UPDATE cases SET phase = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                 (phase, case_id))
    conn.commit()
    conn.close()


def update_case_status(case_id, status):
    conn = get_connection()
    conn.execute("UPDATE cases SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                 (status, case_id))
    conn.commit()
    conn.close()


def add_evidence(case_id, section, document_name, win_boost, is_mandatory,
                 status="pending", why_it_matters="", how_to_obtain="",
                 tribunal_verdict="accepted", rejection_reason="",
                 accepted_in="", rejected_in="", acceptance_count=1):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO case_evidence
        (case_id, section, document_name, win_boost, is_mandatory, status,
         why_it_matters, how_to_obtain, tribunal_verdict, rejection_reason,
         accepted_in, rejected_in, acceptance_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (case_id, section, document_name, win_boost, int(is_mandatory), status,
          why_it_matters, how_to_obtain, tribunal_verdict, rejection_reason,
          accepted_in, rejected_in, acceptance_count))
    conn.commit()
    conn.close()


def clear_case_evidence(case_id):
    conn = get_connection()
    conn.execute("DELETE FROM case_evidence WHERE case_id = ?", (case_id,))
    conn.commit()
    conn.close()


def get_case_evidence(case_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM case_evidence WHERE case_id = ? ORDER BY is_mandatory DESC, win_boost DESC",
                (case_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_evidence_status(evidence_id, status):
    conn = get_connection()
    conn.execute("UPDATE case_evidence SET status = ? WHERE id = ?",
                 (status, evidence_id))
    conn.commit()
    conn.close()


def get_citations_by_section(section: str, limit: int = 10,
                              court_type: str = None) -> list[dict]:
    """
    Pull verified citations for a specific section, optionally filtered by court.
    Used by RAG module to build citation context for AI prompts.

    Args:
        section    — IT Act section e.g. '269SS'
        limit      — max results
        court_type — 'SC' / 'HC' / 'ITAT' / None (all)

    Returns list of row dicts.
    """
    conn = get_connection()
    cur  = conn.cursor()

    court_filter = f"AND court_type = '{court_type}'" if court_type else ""
    cur.execute(f"""
        SELECT * FROM itat_precedents
        WHERE verified IN (1, 2)
          AND (section = ? OR sections_json LIKE ?)
          {court_filter}
        ORDER BY
          CASE verified WHEN 1 THEN 0 ELSE 1 END,
          CASE court_type WHEN 'SC' THEN 0 WHEN 'HC' THEN 1 ELSE 2 END,
          year DESC
        LIMIT ?
    """, (section, f'%"{section}"%', limit))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_precedents_for_section(section, limit=10):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM itat_precedents
        WHERE section = ?
        ORDER BY relevance_score DESC, year DESC
        LIMIT ?
    """, (section, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_argument(case_id, argument_type, argument_text, source_citation,
                 strength_score, counter_argument, phase):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO case_arguments
        (case_id, argument_type, argument_text, source_citation,
         strength_score, counter_argument, phase)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (case_id, argument_type, argument_text, source_citation,
          strength_score, counter_argument, phase))
    conn.commit()
    conn.close()


def get_case_arguments(case_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM case_arguments WHERE case_id = ? ORDER BY strength_score DESC",
                (case_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_hearing(case_id, hearing_date, hearing_type, bench, outcome="pending",
                notes="", objections_raised="", next_date=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO hearings
        (case_id, hearing_date, hearing_type, bench, outcome, notes, objections_raised, next_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (case_id, hearing_date, hearing_type, bench, outcome, notes, objections_raised, next_date))
    conn.commit()
    conn.close()


def get_case_hearings(case_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM hearings WHERE case_id = ? ORDER BY hearing_date DESC", (case_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_judgment(case_id, judgment_date, outcome, relief_granted,
                 penalty_deleted, key_findings, learned_patterns):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO judgments
        (case_id, judgment_date, outcome, relief_granted, penalty_deleted, key_findings, learned_patterns)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (case_id, judgment_date, outcome, relief_granted,
          int(penalty_deleted), key_findings, learned_patterns))
    conn.commit()
    conn.close()


def get_case_judgments(case_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM judgments WHERE case_id = ?", (case_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_timeline_task(case_id, day_number, task_title, task_description, due_date, phase):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO timeline_tasks
        (case_id, day_number, task_title, task_description, due_date, phase)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (case_id, day_number, task_title, task_description, due_date, phase))
    conn.commit()
    conn.close()


def get_timeline_tasks(case_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM timeline_tasks WHERE case_id = ? ORDER BY day_number", (case_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_timeline_task(task_id, status):
    conn = get_connection()
    conn.execute("UPDATE timeline_tasks SET status = ? WHERE id = ?", (status, task_id))
    conn.commit()
    conn.close()


def add_ocr_validation(case_id, document_name, validation_result, issues_found,
                       win_probability, recommendations):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ocr_validations
        (case_id, document_name, validation_result, issues_found, win_probability, recommendations)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (case_id, document_name, validation_result, issues_found, win_probability, recommendations))
    conn.commit()
    conn.close()


def get_statistics():
    conn = get_connection()
    cur = conn.cursor()
    stats = {}
    cur.execute("SELECT COUNT(*) as total FROM cases")
    stats["total_cases"] = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as active FROM cases WHERE status = 'active'")
    stats["active_cases"] = cur.fetchone()["active"]
    cur.execute("SELECT COUNT(*) as won FROM cases WHERE status = 'won'")
    stats["won_cases"] = cur.fetchone()["won"]
    cur.execute("SELECT COUNT(*) as total FROM itat_precedents")
    stats["total_precedents"] = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as total FROM case_arguments")
    stats["total_arguments"] = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as total FROM cbdt_circulars")
    stats["total_circulars"] = cur.fetchone()["total"]
    conn.close()
    return stats


# ── CBDT Circulars ────────────────────────────────────────────────────────────

def search_circulars_db(query: str, favour: str = "All", limit: int = 30) -> list[dict]:
    """Full-text search across circulars in local DB."""
    conn = get_connection()
    cur = conn.cursor()
    q = f"%{query.lower()}%"
    if favour != "All":
        cur.execute("""
            SELECT * FROM cbdt_circulars
            WHERE (LOWER(subject) LIKE ? OR LOWER(summary) LIKE ?
                   OR LOWER(key_para) LIKE ? OR LOWER(sections) LIKE ?)
            AND favour = ?
            ORDER BY date DESC LIMIT ?
        """, (q, q, q, q, favour.lower(), limit))
    else:
        cur.execute("""
            SELECT * FROM cbdt_circulars
            WHERE LOWER(subject) LIKE ? OR LOWER(summary) LIKE ?
                  OR LOWER(key_para) LIKE ? OR LOWER(sections) LIKE ?
            ORDER BY date DESC LIMIT ?
        """, (q, q, q, q, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_circulars_for_section_db(section: str) -> list[dict]:
    """Get all circulars tagged to a specific IT Act section from DB."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM cbdt_circulars
        WHERE sections LIKE ?
        ORDER BY date DESC
    """, (f'%"{section}"%',))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_all_circulars(limit: int = 50) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cbdt_circulars ORDER BY date DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_ik_case_for_circular(circular_id: str, case_title: str, court: str,
                               date: str, ik_tid: str, ik_url: str, headline: str):
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO circular_ik_cases
        (circular_id, case_title, court, date, ik_tid, ik_url, headline)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (circular_id, case_title, court, date, ik_tid, ik_url, headline))
    conn.commit()
    conn.close()


def get_ik_cases_for_circular(circular_id: str) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM circular_ik_cases WHERE circular_id = ?
        ORDER BY date DESC LIMIT 10
    """, (circular_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
