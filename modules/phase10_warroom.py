"""Phase 10: War Room / Hearing Preparation — day-before final briefing."""
import streamlit as st
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections, format_currency, calculate_overall_win_rate
from ai.claude_client import call_claude, stream_claude
from ai.prompts import WARROOM_SYSTEM


def render():
    st.header("Phase 10: War Room")
    st.caption("The Trigger: ITAT hearing scheduled for tomorrow. Final briefing starts NOW.")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case loaded.")
        return

    case = queries.get_case(case_id)
    sections = parse_sections(case["sections_violated"])
    evidence = queries.get_case_evidence(case_id)
    arguments = queries.get_case_arguments(case_id)

    st.error("🚨 WAR ROOM ACTIVE — Hearing is tomorrow. This is your final preparation session.")

    col1, col2, col3, col4 = st.columns(4)
    win_data = calculate_overall_win_rate(evidence) if evidence else {"win_probability": 50, "risk_level": "UNKNOWN"}
    col1.metric("Win Probability", f"{win_data['win_probability']:.0f}%")
    col2.metric("Evidence Secured", len([e for e in evidence if e["status"] == "available"]))
    col3.metric("Arguments Built", len(arguments))
    col4.metric("Risk Level", win_data.get("risk_level", "UNKNOWN"))

    tab1, tab2, tab3, tab4 = st.tabs([
        "📖 Final Brief", "🎯 Bench Simulation", "📋 Hearing Checklist", "🗣️ Oral Argument Script"
    ])

    with tab1:
        _render_final_brief(case, sections, evidence, arguments)

    with tab2:
        _render_bench_simulation(case, sections)

    with tab3:
        _render_hearing_checklist(case)

    with tab4:
        _render_oral_script(case, sections, evidence, arguments)


def _render_final_brief(case, sections, evidence, arguments):
    st.subheader("War Room Final Brief")
    st.caption("The 2-page summary of everything — read this on the way to the tribunal.")

    bench_location = st.text_input("Bench Location", placeholder="e.g., Delhi ITAT, A Bench")
    bench_members = st.text_input("Bench Members (if known)", placeholder="e.g., Shri X (JM) + Shri Y (AM)")

    if st.button("Generate War Room Brief", type="primary"):
        available = [e["document_name"] for e in evidence if e["status"] == "available"]
        top_args = [a["argument_text"][:150] for a in arguments[:5]]

        prompt = f"""Generate the WAR ROOM FINAL BRIEF — the complete 2-page briefing document for tomorrow's ITAT hearing.

**CASE:** {case['case_name']}
**CLIENT:** {case['client_name']}
**AY:** {case.get('assessment_year', 'N/A')}
**SECTIONS:** {', '.join(sections)}
**DEMAND:** {format_currency(case.get('demand_amount', 0))}
**BENCH:** {bench_location or 'ITAT'}
**MEMBERS:** {bench_members or 'Not specified'}
**EVIDENCE SECURED:** {', '.join(available[:8]) if available else 'As in paper book'}
**TOP ARGUMENTS:** {'; '.join(top_args) if top_args else 'As built in earlier phases'}

Generate:

# WAR ROOM BRIEF — {case['case_name']}
## Prepared: {datetime.now().strftime('%d %b %Y')}

### CASE SNAPSHOT (30-second pitch)
[3 sentences: what happened, what the AO/CIT(A) did, what we want]

### TOP 5 WINNING ARGUMENTS
1. [Argument + Citation + One-line why it wins]
2. [Same format]
3. [Same format]
4. [Same format]
5. [Same format]

### BENCH-SPECIFIC STRATEGY
[How to approach this specific bench; what they tend to care about]

### THE 3 MOST DANGEROUS DR ATTACKS + OUR COUNTERS
1. DR will say: [X] → We say: [Y] + cite [Z]
2. [Same format]
3. [Same format]

### EVIDENCE DEPLOYMENT ORDER
[When to pull out which document — opening/middle/closing]

### PRAYER EXACTLY AS TO BE STATED
"Your Honours, we humbly pray that..."

### CONTINGENCY PLAN
[If primary fails: what next?]

### 3 THINGS NOT TO SAY
[Common mistakes to avoid in this type of case]

Keep it crisp — this must be readable in 5 minutes."""

        result_placeholder = st.empty()
        full_result = ""
        for chunk in stream_claude(WARROOM_SYSTEM, prompt, max_tokens=6000):
            full_result += chunk
            result_placeholder.markdown(full_result + "▌")
        result_placeholder.markdown(full_result)

        if not full_result.startswith("[ERROR]"):
            st.download_button(
                "Download War Room Brief",
                data=full_result,
                file_name=f"WarRoom_{case['case_name'][:20]}_{datetime.now().strftime('%d%b%Y')}.txt",
                mime="text/plain"
            )


def _render_bench_simulation(case, sections):
    st.subheader("Bench Simulation — Q&A Practice")
    st.caption("Simulate the bench asking questions. Practice your answers.")

    bench_style = st.selectbox("Simulate Bench Style", [
        "Balanced (asks both sides equally)",
        "Skeptical of assessee",
        "Very technical (asks procedural questions)",
        "Sympathetic (but needs convincing)",
    ])

    question_count = st.slider("Number of Questions", 3, 10, 5)

    if st.button("Start Bench Simulation"):
        with st.spinner("Generating bench questions..."):
            prompt = f"""Simulate a {bench_style} ITAT bench asking questions to the assessee's counsel.

Case sections: {', '.join(sections)}

Generate {question_count} realistic questions the bench will ask, progressing from introductory to challenging.

For each question:
**Q{'{n}'}: [The exact question the bench asks]**
**Suggested Answer:** [Best 3-4 sentence response with citation]
**Red Flag:** [What NOT to say in response]

Make questions realistic and in proper judicial language."""

            result = call_claude(WARROOM_SYSTEM, prompt, max_tokens=4000)
            st.markdown(result)

    st.divider()
    st.subheader("Live Q&A Practice")
    bench_question = st.text_input("Type a bench question to practice:", placeholder="e.g., Counsel, the penalty is mandatory under 271D — how do you escape it?")
    if bench_question and st.button("Get Model Answer"):
        with st.spinner("Generating model answer..."):
            prompt = f"""BENCH QUESTION PRACTICE for sections {', '.join(sections)}.

Question: {bench_question}

Provide:
1. Model answer (as would be spoken at the podium, 60-100 words)
2. Citation to open with
3. One-line fallback if bench pushes back"""
            result = call_claude(WARROOM_SYSTEM, prompt, max_tokens=600)
            st.markdown(result)


def _render_hearing_checklist(case):
    st.subheader("Night-Before Hearing Checklist")

    items = [
        ("Paper book compiled, indexed, and paginated", "documents"),
        ("3 sets of paper book ready (bench + DR + own)", "documents"),
        ("All cited cases printed and highlighted", "documents"),
        ("Written submissions printed", "documents"),
        ("Vakalatnama on file", "documents"),
        ("Appearance memo filed", "documents"),
        ("Stay order copy if applicable", "documents"),
        ("Case diary/notes organized", "preparation"),
        ("Opening statement rehearsed (< 3 minutes)", "preparation"),
        ("All amounts cross-verified with AO's order", "preparation"),
        ("Alternate arguments prepared (3 levels)", "preparation"),
        ("Know the hearing room location", "logistics"),
        ("Arrival time planned (30 minutes early)", "logistics"),
        ("Phone charged and on silent", "logistics"),
        ("Emergency contact of senior counsel", "logistics"),
    ]

    doc_items = [(i, t) for i, t in items if t == "documents"]
    prep_items = [(i, t) for i, t in items if t == "preparation"]
    log_items = [(i, t) for i, t in items if t == "logistics"]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**📁 Documents**")
        for item, _ in doc_items:
            st.checkbox(item, key=f"wrc_{item[:15]}")
    with col2:
        st.markdown("**🧠 Preparation**")
        for item, _ in prep_items:
            st.checkbox(item, key=f"wrc_{item[:15]}")
    with col3:
        st.markdown("**🚗 Logistics**")
        for item, _ in log_items:
            st.checkbox(item, key=f"wrc_{item[:15]}")


def _render_oral_script(case, sections, evidence, arguments):
    st.subheader("Oral Argument Script")
    st.caption("Word-for-word script for the hearing — from appearance to prayer.")

    time_available = st.number_input("Expected time before bench (minutes)", min_value=5, max_value=60, value=20)

    if st.button("Generate Full Oral Script", type="primary"):
        available = [e["document_name"] for e in evidence if e["status"] == "available"]
        top_args = [a["argument_text"][:100] for a in arguments[:3]]

        with st.spinner("Drafting oral argument script..."):
            prompt = f"""Draft a complete oral argument script for the ITAT hearing.

Case: {case['case_name']}
Sections: {', '.join(sections)}
Time available: {time_available} minutes
Evidence: {', '.join(available[:6]) if available else 'As in paper book'}
Key arguments: {'; '.join(top_args) if top_args else 'As developed in preparation'}

Write a word-for-word script:

**[APPEARANCE]**
"May it please Your Honours, I am [NAME], appearing for the Appellant..."

**[OPENING — 2 minutes]**
[Narrative of facts — keep it compelling]

**[MAIN ARGUMENTS — {time_available-5} minutes]**

*Argument 1: [Section issue]*
"Your Honours, on the first issue of Section [X]..."
[Full argument with case citation]

*Argument 2: [Next issue]*
[Same format]

*[Continue for all sections]*

**[PRAYER — 1 minute]**
"In view of the above submissions, we most humbly pray that..."

**[IF INTERRUPTED]**
"Your Honours, with your permission, I shall address that point momentarily after completing..."

Keep it natural, confident, and citable. Total speaking time: {time_available} minutes."""

            result = call_claude(WARROOM_SYSTEM, prompt, max_tokens=6000)
            st.markdown(result)
            st.download_button(
                "Download Oral Script",
                data=result,
                file_name=f"OralScript_{case['case_name'][:20]}.txt",
                mime="text/plain"
            )
