"""Phase 12: Continuous Learning — post-judgment data ingestion and system hardening."""
import streamlit as st
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from database.init_db import get_connection
from utils.helpers import parse_sections, format_currency
from utils.pdf_parser import extract_text_from_pdf
from config import UPLOADS_DIR
from ai.claude_client import call_claude
from ai.prompts import LEARNING_SYSTEM


def render():
    st.header("Phase 12: Continuous Learning")
    st.caption("The Trigger: ITAT uploads the final judgment. From post-judgment data to system hardening.")

    case_id = st.session_state.get("active_case_id")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📄 Judgment Intake", "🧠 Pattern Extraction", "📚 DB Enrichment", "📊 Learning Analytics"
    ])

    with tab1:
        _render_judgment_intake(case_id)

    with tab2:
        _render_pattern_extraction(case_id)

    with tab3:
        _render_db_enrichment()

    with tab4:
        _render_learning_analytics()


def _render_judgment_intake(case_id):
    st.subheader("Step 1: Judgment PDF Intake")
    st.caption("The Trigger: ITAT uploads the final judgment PDF to the government portal.")

    if case_id:
        case = queries.get_case(case_id)
        st.info(f"Active Case: **{case['case_name']}**")

    uploaded_judgment = st.file_uploader("Upload ITAT Judgment PDF", type=["pdf"])

    col1, col2 = st.columns(2)
    with col1:
        judgment_date = st.date_input("Judgment Date")
        outcome = st.selectbox("Final Outcome", [
            "Full relief granted (assessee won)",
            "Partial relief granted",
            "Relief denied (revenue wins)",
            "Matter remanded to AO",
            "Matter remanded to CIT(A)",
            "Appeal dismissed as withdrawn",
        ])
    with col2:
        penalty_deleted = st.checkbox("Penalty fully deleted?")
        relief_amount = st.number_input("Relief Amount (₹)", min_value=0.0, step=1000.0)
        bench = st.text_input("Bench/Members", placeholder="ITAT Delhi, Bench A")

    if uploaded_judgment and case_id:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        pdf_path = os.path.join(UPLOADS_DIR, f"judgment_{case_id}_{uploaded_judgment.name}")
        with open(pdf_path, "wb") as f:
            f.write(uploaded_judgment.getbuffer())

        st.success("Judgment uploaded. Extracting text...")

        if st.button("Process Judgment & Extract Learnings", type="primary"):
            with st.spinner("Processing judgment..."):
                judgment_text = extract_text_from_pdf(pdf_path)

                sections = parse_sections(case["sections_violated"])
                prompt = f"""Analyze this ITAT judgment for sections {', '.join(sections)}.

Judgment outcome: {outcome}
Penalty deleted: {penalty_deleted}

From the judgment text, extract:
1. Key legal findings of the bench
2. Arguments that succeeded (and why)
3. Arguments that failed (and why)
4. New legal ratios established
5. Bench's observations on evidence quality
6. Any criticism of assessee's documentation
7. Any praise of assessee's arguments
8. What the bench's order template reveals about their approach

Format as structured learnings for the database."""

                analysis = call_claude(LEARNING_SYSTEM, prompt + f"\n\nJUDGMENT TEXT (first 2000 chars):\n{judgment_text[:2000]}")

                queries.add_judgment(
                    case_id,
                    judgment_date.strftime("%Y-%m-%d"),
                    outcome,
                    f"₹{relief_amount:,.0f}" if relief_amount > 0 else "No monetary relief",
                    penalty_deleted,
                    analysis[:1000],
                    analysis
                )

                won = "won" in outcome.lower() or "granted" in outcome.lower()
                queries.update_case_status(case_id, "won" if won else "lost")

                st.markdown("### Judgment Analysis:")
                st.markdown(analysis)

                _extract_and_save_precedent(case, sections, judgment_text, outcome, bench, judgment_date, analysis)
    elif not case_id:
        st.info("Load an active case in Phase 1 to process its judgment.")


def _extract_and_save_precedent(case, sections, judgment_text, outcome, bench, judgment_date, analysis):
    st.divider()
    st.subheader("Auto-Extract New Precedent")

    citation = st.text_input(
        "Case Citation (as it will appear in reports)",
        placeholder="e.g., M/s ABC Traders v. DCIT [2026] ITAT Delhi"
    )
    key_ratio = st.text_area("Key Legal Ratio (one sentence)", height=60)

    if citation and key_ratio and st.button("Save as ITAT Precedent"):
        conn = get_connection()
        cur = conn.cursor()
        win_for_assessee = 1 if "won" in outcome.lower() or "granted" in outcome.lower() else 0
        cur.execute("""
            INSERT OR IGNORE INTO itat_precedents
            (case_citation, section, bench, year, outcome, key_ratio, facts_summary, win_for_assessee, relevance_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            citation,
            ', '.join(sections),
            bench or "ITAT",
            judgment_date.year,
            outcome,
            key_ratio,
            analysis[:300],
            win_for_assessee,
            0.85
        ))
        conn.commit()
        conn.close()
        st.success(f"Precedent saved: {citation}")


def _render_pattern_extraction(case_id):
    st.subheader("Pattern Extraction Engine")
    st.caption("Extract winning patterns from this case and all prior judgments.")

    if case_id:
        judgments = queries.get_case_judgments(case_id)
        case = queries.get_case(case_id)
        sections = parse_sections(case["sections_violated"])

        if judgments:
            for j in judgments:
                with st.expander(f"Judgment: {j['judgment_date']} — {j['outcome']}"):
                    st.write(f"**Relief:** {j['relief_granted']}")
                    st.write(f"**Penalty Deleted:** {'Yes' if j['penalty_deleted'] else 'No'}")
                    st.markdown(f"**Key Findings:** {j['key_findings'][:500]}")

                    if st.button("Extract Patterns", key=f"extract_{j['id']}"):
                        with st.spinner("Extracting patterns..."):
                            prompt = f"""Extract winning/losing patterns from this ITAT case outcome.

Sections: {', '.join(sections)}
Outcome: {j['outcome']}
Key findings: {j['key_findings']}
Learned patterns: {j['learned_patterns'][:500] if j['learned_patterns'] else 'Not analyzed yet'}

Extract:
1. What specific evidence made the difference?
2. What argument framing worked/didn't work?
3. What bench signals should we watch for in future?
4. Updated win probability for these sections given this precedent
5. What to do differently next time
6. Pattern classification: Is this a landmark case or routine?

Format as reusable learnings for future similar cases."""
                            result = call_claude(LEARNING_SYSTEM, prompt)
                            st.markdown(result)
        else:
            st.info("No judgments logged yet. Process judgment in Tab 1 first.")
    else:
        st.info("Load a case to extract patterns.")

    st.divider()
    st.subheader("Cross-Case Pattern Analysis")
    if st.button("Analyze All Won Cases for Winning Patterns"):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM judgments WHERE penalty_deleted = 1 LIMIT 10")
        won_cases = [dict(r) for r in cur.fetchall()]
        conn.close()

        if won_cases:
            findings = "\n".join([f"- {j['outcome']}: {j['key_findings'][:100]}" for j in won_cases])
            with st.spinner("Analyzing winning patterns..."):
                prompt = f"""Analyze these successful ITAT case outcomes and extract universal winning patterns:

{findings}

Identify:
1. Common evidence combinations that consistently win
2. Argument structures that work across benches
3. Documentation patterns that impress judges
4. Language/framing that is persuasive
5. What distinguishes won cases from lost cases

Provide actionable guidelines for future cases."""
                result = call_claude(LEARNING_SYSTEM, prompt)
                st.markdown(result)
        else:
            st.info("No won cases in database yet.")


def _render_db_enrichment(  ):
    st.subheader("Database Enrichment")
    st.caption("Add new ITAT precedents, update win rates, expand the knowledge base.")

    st.markdown("### Add New Precedent Manually")
    with st.form("add_precedent_form"):
        col1, col2 = st.columns(2)
        with col1:
            citation = st.text_input("Case Citation *", placeholder="XYZ v. DCIT [2026] ITAT Mumbai")
            section = st.selectbox("Section *", list({"269SS", "269T", "271D", "271E", "40A(3)", "153A", "68", "69", "14A", "56(2)"}))
            bench = st.text_input("Bench", placeholder="ITAT Mumbai, B Bench")
            year = st.number_input("Year", min_value=1960, max_value=2030, value=2024)
        with col2:
            outcome = st.selectbox("Outcome", ["Assessee won", "Revenue won", "Partial relief", "Remanded"])
            win_for_assessee = st.checkbox("Favourable for assessee?", value=True)
            relevance = st.slider("Relevance Score", 0.0, 1.0, 0.80)

        key_ratio = st.text_area("Key Legal Ratio *", height=80)
        facts = st.text_area("Facts Summary", height=80)

        if st.form_submit_button("Add Precedent"):
            if citation and key_ratio and section:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR IGNORE INTO itat_precedents
                    (case_citation, section, bench, year, outcome, key_ratio, facts_summary, win_for_assessee, relevance_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (citation, section, bench, year, outcome, key_ratio, facts, int(win_for_assessee), relevance))
                conn.commit()
                conn.close()
                st.success(f"Precedent added: {citation}")
            else:
                st.error("Citation, section, and key ratio are required.")

    st.divider()
    st.subheader("Current Database Stats")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT section, COUNT(*) as count, AVG(win_for_assessee)*100 as win_rate FROM itat_precedents GROUP BY section")
    stats = [dict(r) for r in cur.fetchall()]
    conn.close()

    if stats:
        import pandas as pd
        df = pd.DataFrame(stats)
        df.columns = ["Section", "Cases in DB", "Assessee Win Rate %"]
        df["Assessee Win Rate %"] = df["Assessee Win Rate %"].round(1)
        st.dataframe(df, use_container_width=True)


def _render_learning_analytics(  ):
    st.subheader("Learning Analytics Dashboard")

    stats = queries.get_statistics()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Cases", stats["total_cases"])
    col2.metric("Active Cases", stats["active_cases"])
    col3.metric("Cases Won", stats["won_cases"])
    col4.metric("ITAT Precedents", stats["total_precedents"])

    total = stats["total_cases"]
    won = stats["won_cases"]
    if total > 0:
        win_rate = (won / total) * 100
        st.metric("System-Wide Win Rate", f"{win_rate:.1f}%", delta=f"vs 45% baseline")
        st.progress(win_rate / 100)

    st.divider()
    st.subheader("System Health")
    checks = [
        ("Database initialized", True),
        ("ITAT precedent database populated", stats["total_precedents"] > 0),
        ("Cases registered", stats["total_cases"] > 0),
        ("Arguments built", stats["total_arguments"] > 0),
    ]
    for check, status in checks:
        icon = "✅" if status else "❌"
        st.write(f"{icon} {check}")

    st.divider()
    if st.button("Generate System Improvement Report"):
        with st.spinner("Analyzing system performance..."):
            prompt = f"""Generate a system improvement report for the Litigation Intelligence OS.

Current stats:
- Total cases: {stats['total_cases']}
- Active cases: {stats['active_cases']}
- Won cases: {stats['won_cases']}
- ITAT precedents in database: {stats['total_precedents']}
- Arguments built: {stats['total_arguments']}

Provide:
1. What data gaps exist in the system?
2. Which sections need more precedents?
3. What patterns could improve win rates?
4. Recommended next additions to the precedent database
5. Key sections to focus on based on industry trends in 2025-26"""
            result = call_claude(LEARNING_SYSTEM, prompt)
            st.markdown(result)
