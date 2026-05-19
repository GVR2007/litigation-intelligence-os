"""
RAG — Retrieval-Augmented Generation for Litigation OS.

Pulls verified citations from the local DB and injects them into
every AI prompt so the model cites REAL cases, not hallucinations.

Usage:
    from ai.rag import build_citation_context, inject_into_prompt

    # Get citation block for a section list
    block = build_citation_context(["269SS", "271D"])

    # Wrap a user message with verified citations
    grounded = inject_into_prompt(user_message, ["269SS"], case_facts="...")
    result = call_claude(STRATEGY_SYSTEM, grounded)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# Core: pull citations from local DB
# ─────────────────────────────────────────────────────────────────────────────

def get_citations_for_sections(sections: list[str],
                                limit: int = 10,
                                prefer_assessee_wins: bool = True) -> list[dict]:
    """
    Pull the top verified citations for the given sections from the local DB.

    Priority:
      1. verified=1 (Indian Kanoon — authoritative)
      2. verified=2 (web-scraped — reliable)
      3. SC > HC > ITAT
      4. Assessee wins preferred (when prefer_assessee_wins=True)
      5. Newest first

    Returns list of dicts with keys:
        case_citation, section, court_type, bench, year, key_ratio,
        facts_summary, win_for_assessee, ik_url, source_url
    """
    from database.init_db import get_connection

    conn = get_connection()
    cur  = conn.cursor()
    seen = set()
    results = []

    per_section = max(2, limit // max(len(sections), 1))

    for sec in sections:
        win_filter = "AND win_for_assessee = 1" if prefer_assessee_wins else ""
        cur.execute(f"""
            SELECT * FROM itat_precedents
            WHERE verified IN (1, 2)
              AND (section = ? OR sections_json LIKE ?)
              {win_filter}
            ORDER BY
              CASE verified WHEN 1 THEN 0 ELSE 1 END,
              CASE court_type WHEN 'SC' THEN 0 WHEN 'HC' THEN 1 ELSE 2 END,
              year DESC
            LIMIT ?
        """, (sec, f'%"{sec}"%', per_section + 3))

        for row in cur.fetchall():
            r   = dict(row)
            uid = (r.get("ik_url") or r.get("case_citation", "")).strip()
            if uid and uid not in seen:
                seen.add(uid)
                results.append(r)

    # If we got fewer than limit, do a keyword fill from all sections
    if len(results) < limit:
        remaining = limit - len(results)
        section_list = ", ".join(f"'{s}'" for s in sections)
        cur.execute(f"""
            SELECT * FROM itat_precedents
            WHERE verified IN (1, 2)
              AND section IN ({section_list})
            ORDER BY
              CASE verified WHEN 1 THEN 0 ELSE 1 END,
              CASE court_type WHEN 'SC' THEN 0 WHEN 'HC' THEN 1 ELSE 2 END,
              year DESC
            LIMIT ?
        """, (remaining,))
        for row in cur.fetchall():
            r   = dict(row)
            uid = (r.get("ik_url") or r.get("case_citation", "")).strip()
            if uid and uid not in seen:
                seen.add(uid)
                results.append(r)

    conn.close()

    # Final sort: SC first, HC second, ITAT last; newest within group
    _order = {"SC": 0, "HC": 1, "ITAT": 2}
    results.sort(key=lambda x: (
        _order.get(x.get("court_type", "ITAT"), 2),
        -x.get("year", 0)
    ))

    return results[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Format citation block for injection into prompts
# ─────────────────────────────────────────────────────────────────────────────

def build_citation_context(sections: list[str],
                            limit: int = 10,
                            include_losing: bool = False) -> str:
    """
    Build a formatted citation block to inject into AI prompts.

    Returns a string like:
        • Vijay Kumar Talwar v. CIT [2011] 330 ITR 1 (SC) [§153A]
          Ratio: No addition in completed assessments without incriminating material
        ...

    If no citations in DB, returns a placeholder message.
    """
    rows = get_citations_for_sections(
        sections,
        limit=limit,
        prefer_assessee_wins=not include_losing
    )

    if not rows:
        return (
            "No verified citations in local database for these sections. "
            "Run Citation DB → Indian Kanoon Harvest to populate. "
            "DO NOT invent any case names."
        )

    lines = []
    for r in rows:
        citation = r.get("case_citation", "").strip()
        if not citation:
            continue
        court   = r.get("court_type", "")
        sec     = r.get("section", "")
        ratio   = (r.get("key_ratio") or "").strip()
        win     = r.get("win_for_assessee", 1)
        year    = r.get("year", 0)
        url     = r.get("ik_url") or r.get("source_url") or ""

        outcome = "✓ Assessee won" if win else "✗ Revenue won"
        sec_tag = f"[§{sec}]" if sec else ""

        line = f"• {citation} {sec_tag} — {court} {year} — {outcome}"
        if ratio:
            line += f"\n  Ratio: {ratio[:200]}"
        if url:
            line += f"\n  Link: {url}"
        lines.append(line)

    header = (
        f"VERIFIED CITATIONS FROM LOCAL DATABASE ({len(lines)} cases — "
        f"ONLY cite these; do NOT invent any others):\n\n"
    )
    return header + "\n\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Inject into prompt (main entry point for all phases)
# ─────────────────────────────────────────────────────────────────────────────

def inject_into_prompt(user_message: str,
                        sections: list[str],
                        case_facts: str = "",
                        limit: int = 10) -> str:
    """
    Wrap user_message with verified citation context + case facts.

    This is the primary function called by all phase modules before
    any AI call. It grounds the model with real precedents.

    Args:
        user_message  — the original question/task
        sections      — IT Act sections for this case  e.g. ['269SS', '271D']
        case_facts    — extracted facts from the PDF (optional, already redacted)
        limit         — max citations to inject (default 10)

    Returns:
        Enriched prompt string ready to send to Gemini via call_claude() or call_gemini()
    """
    from ai.prompts import ANTI_HALLUCINATION_REMINDER

    citation_block = build_citation_context(sections, limit=limit)

    parts = []

    parts.append("━━━ VERIFIED PRECEDENTS (GROUND YOUR ANSWER IN THESE) ━━━")
    parts.append(citation_block)

    if case_facts and case_facts.strip():
        parts.append("\n━━━ CASE FACTS (FROM UPLOADED DOCUMENT) ━━━")
        facts_truncated = case_facts.strip()[:800]
        parts.append(facts_truncated)

    parts.append("\n━━━ YOUR TASK ━━━")
    parts.append(user_message)

    parts.append(ANTI_HALLUCINATION_REMINDER)

    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Smart routing: Ollama for extraction, Claude for deep reasoning
# ─────────────────────────────────────────────────────────────────────────────

def call_with_routing(task_type: str,
                      system_prompt: str,
                      user_message: str,
                      sections: list[str] = None,
                      case_facts: str = "",
                      temperature: float = 0.15,
                      max_tokens: int = 2048) -> str:
    """
    Route AI calls to Gemini 2.5 Flash with RAG citation injection.

    All task types — simple and complex — go to Gemini 2.5 Flash.
    RAG context (verified citations) is injected when sections are provided.
    """
    from ai.gemini_client import call_gemini, is_available

    # Inject RAG if sections provided
    if sections:
        grounded = inject_into_prompt(user_message, sections, case_facts)
    else:
        grounded = user_message

    if not is_available():
        return (
            "[ERROR] Gemini API key not set.\n\n"
            "Go to **⚙️ Settings** → paste your Gemini API key."
        )

    return call_gemini(
        system_prompt, grounded,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Citation count helper (for UI display)
# ─────────────────────────────────────────────────────────────────────────────

def get_citation_stats() -> dict:
    """Return citation counts per section for dashboard display."""
    from database.init_db import get_connection

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT section, court_type, COUNT(*) as cnt
        FROM itat_precedents
        WHERE verified IN (1, 2) AND section IS NOT NULL AND section != ''
        GROUP BY section, court_type
        ORDER BY cnt DESC
        LIMIT 50
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Also get total
    conn2 = get_connection()
    cur2  = conn2.cursor()
    cur2.execute("SELECT COUNT(*) as total FROM itat_precedents WHERE verified IN (1,2)")
    total = cur2.fetchone()["total"]
    conn2.close()

    return {"breakdown": rows, "total": total}
