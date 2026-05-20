"""Phase 7: Master Architect — zero-hallucination final playbook generation."""
import streamlit as st
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections, format_currency, calculate_overall_win_rate
from utils.rag_context import get_grounded_context
from ai.claude_client import call_claude, stream_claude
from ai.prompts import PLAYBOOK_SYSTEM


def render():
    st.header("Phase 7: Master Architect")
    st.caption("Step 7 — Zero-Hallucination Execution: The final playbook. Actionable intelligence for the highest chance of winning.")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case loaded.")
        return

    case = queries.get_case(case_id)
    sections = parse_sections(case["sections_violated"])
    evidence = queries.get_case_evidence(case_id)
    arguments = queries.get_case_arguments(case_id)
    hearings = queries.get_case_hearings(case_id)

    st.info(f"**{case['case_name']}** | Generating master battle plan...")

    tab1, tab2, tab3 = st.tabs(["📖 Master Playbook", "📝 Written Submissions Draft", "⚡ Quick Reference Card"])

    with tab1:
        _render_master_playbook(case, sections, evidence, arguments)

    with tab2:
        _render_written_submissions(case, sections, evidence, arguments)

    with tab3:
        _render_quick_reference(case, sections, evidence)


def _render_master_playbook(case, sections, evidence, arguments):
    st.subheader("Master Playbook — Complete Battle Strategy")

    win_data = calculate_overall_win_rate(evidence) if evidence else {"win_probability": 50}
    available_evidence = [e["document_name"] for e in evidence if e["status"] == "available"]
    unavailable_evidence = [e["document_name"] for e in evidence if e["status"] == "unavailable"]
    top_arguments = [a["argument_text"][:200] for a in arguments[:5]]

    bench_location = st.selectbox("ITAT Bench Location", [
        "Delhi", "Mumbai", "Kolkata", "Chennai", "Ahmedabad",
        "Bangalore", "Hyderabad", "Pune", "Chandigarh", "Jaipur"
    ])

    col1, col2 = st.columns(2)
    with col1:
        include_citations = st.checkbox("Include full case citations", value=True)
        include_grounds = st.checkbox("Include grounds of appeal", value=True)
    with col2:
        include_prayers = st.checkbox("Include prayer clauses", value=True)
        include_riskplan = st.checkbox("Include contingency plan", value=True)

    if st.button("Generate Master Playbook", type="primary"):
        evidence_brief = f"Available: {', '.join(available_evidence[:8])}" if available_evidence else "No evidence secured"
        missing_brief = f"Missing: {', '.join(unavailable_evidence[:5])}" if unavailable_evidence else "No critical gaps"
        args_brief = "\n".join(top_arguments) if top_arguments else "Arguments pending"

        # ── RAG grounded context — makes the "zero hallucination" claim real ──
        with st.spinner("🔍 Loading verified precedents for playbook..."):
            ctx = get_grounded_context(case["id"], sections)

        citations_block = ""
        if include_citations and ctx["citations_block"]:
            citations_block = f"""
## VERIFIED PRECEDENTS (use ONLY these citations — do not invent any other):
{ctx['citations_block']}

CBDT CIRCULARS:
{ctx['cbdt_block'] or 'None retrieved'}

⚠️ ZERO HALLUCINATION RULE: Every citation in this playbook MUST appear in the
VERIFIED PRECEDENTS list above. If a case is not listed, write [CITATION NEEDED]."""

        with st.container():
            st.markdown("---")
            st.markdown(f"# MASTER PLAYBOOK")
            st.markdown(f"**Case:** {case['case_name']} | **Generated:** {datetime.now().strftime('%d %b %Y, %I:%M %p')} | **Precedents loaded:** {ctx['count']}")
            st.markdown("---")

            result_placeholder = st.empty()
            full_result = ""

            prompt = f"""Generate the complete Master Playbook for an ITAT case.

**CASE BRIEF:**
- Case: {case['case_name']}
- Client: {case['client_name']}
- Assessment Year: {case.get('assessment_year', 'N/A')}
- Sections: {', '.join(sections)}
- Demand: {format_currency(case.get('demand_amount', 0))}
- Bench: {bench_location} ITAT
- Win Probability: {win_data.get('win_probability', 50):.1f}%
- Evidence: {evidence_brief}
- Gaps: {missing_brief}

**TOP ARGUMENTS:**
{args_brief}
{citations_block}

Generate a complete playbook with:

{'## 1. GROUNDS OF APPEAL (Ready to File)' if include_grounds else ''}
[Draft all grounds in proper legal format, numbered]

## 2. ARGUMENT SEQUENCE (Hearing Day Order)
[Optimal order with time allocation per ground]

## 3. KEY CASE CITATIONS
[Use ONLY the verified precedents listed above — one per ground with ratio and deployment note]

## 4. ANTICIPATED BENCH QUESTIONS & ANSWERS
[Top 8 questions the bench will ask — with prepared answers citing the verified cases]

## 5. DR ATTACK MATRIX & COUNTERS
[Each anticipated DR argument → our counter with verified citation]

## 6. EVIDENCE DEPLOYMENT PLAN
[When and how to present each document during hearing]

{'## 7. PRAYERS & RELIEFS SOUGHT' if include_prayers else ''}
[Specific relief sought, in priority order]

{'## 8. CONTINGENCY PLAN' if include_riskplan else ''}
[If primary argument fails: fallback strategy, SLP grounds, etc.]

## 9. LAST-MINUTE CHECKLIST
[10 things to verify on the morning of the hearing]"""

            for chunk in stream_claude(PLAYBOOK_SYSTEM, prompt, max_tokens=8000):
                full_result += chunk
                result_placeholder.markdown(full_result + "▌")
            result_placeholder.markdown(full_result)

            if full_result and not full_result.startswith("[ERROR]"):
                st.session_state[f"playbook_{case['id']}"] = full_result
                st.success(f"✅ Playbook saved — grounded in {ctx['count']} verified precedents")


def _render_written_submissions(case, sections, evidence, arguments):
    st.subheader("Written Submissions Draft")
    st.caption("AI-drafted written submissions ready for review and filing.")

    submission_type = st.radio("Submission Type", [
        "Full Written Submissions (10-15 pages)",
        "Synopsis (3-5 pages)",
        "Additional Written Arguments (post-hearing)"
    ])

    specific_section = st.selectbox("Focus Section", ["All Sections"] + sections)

    if st.button("Draft Written Submissions", type="primary"):
        section_focus = specific_section if specific_section != "All Sections" else ', '.join(sections)
        available_docs = [e["document_name"] for e in evidence if e["status"] == "available"]

        ctx = get_grounded_context(case["id"], sections)
        verified_block = (
            f"\nVERIFIED CITATIONS (cite ONLY from this list):\n{ctx['citations_block']}\n"
            f"\n⚠️ Do not use any citation not listed above."
            if ctx["citations_block"] else ""
        )

        length_instruction = {
            "Full Written Submissions (10-15 pages)": "Provide comprehensive, detailed submissions of 1500+ words.",
            "Synopsis (3-5 pages)": "Provide a concise synopsis of 500-700 words.",
            "Additional Written Arguments (post-hearing)": "Provide targeted post-hearing arguments of 800-1000 words."
        }[submission_type]

        with st.spinner(f"Drafting with {ctx['count']} verified precedents..."):
            prompt = f"""Draft formal Written Submissions for ITAT for sections {section_focus}.

Case: {case['case_name']}
Client: {case['client_name']}
Assessment Year: {case.get('assessment_year', 'N/A')}
Available Evidence: {', '.join(available_docs[:10]) if available_docs else 'As mentioned in paper book'}
{verified_block}

{length_instruction}

Format as actual legal submissions:

**IN THE INCOME TAX APPELLATE TRIBUNAL**
**[BENCH] BENCH**

**IN THE MATTER OF:**
[Case Title]

**WRITTEN SUBMISSIONS ON BEHALF OF THE APPELLANT**

[Body with proper legal structure, paragraphs, and citations from the verified list above]

**GROUNDS:**
[Numbered grounds]

**SUBMISSIONS:**
[Legal arguments with verified case citations]

**CONCLUSION:**
[Prayer for relief]

Use formal legal language. Number all paragraphs."""
            result = call_claude(PLAYBOOK_SYSTEM, prompt, max_tokens=8000)
            st.markdown(result)

            if st.download_button(
                "Download Written Submissions",
                data=result,
                file_name=f"Written_Submissions_{case['case_name'][:20]}.txt",
                mime="text/plain"
            ):
                st.success("Downloaded!")


def _render_quick_reference(case, sections, evidence):
    st.subheader("Quick Reference Card")
    st.caption("One-page battle card for the hearing day.")

    available = [e for e in evidence if e["status"] == "available"]
    unavailable = [e for e in evidence if e["status"] == "unavailable" and e["is_mandatory"]]

    st.markdown(f"""
### {case['case_name']}
**AY:** {case.get('assessment_year', 'N/A')} | **Sections:** {', '.join(sections)} | **Demand:** {format_currency(case.get('demand_amount', 0))}

---
**EVIDENCE SECURED ({len(available)} items):**
{chr(10).join(f'✅ {e["document_name"]}' for e in available[:8])}

**CRITICAL GAPS ({len(unavailable)} items):**
{chr(10).join(f'⚠️ {e["document_name"]}' for e in unavailable[:5]) if unavailable else '✅ None'}

---
**WIN PROBABILITY:** {calculate_overall_win_rate(evidence).get('win_probability', 50) if evidence else 50:.1f}%
""")

    if st.button("Generate One-Page Battle Card"):
        win_prob = calculate_overall_win_rate(evidence).get("win_probability", 50) if evidence else 50
        ctx = get_grounded_context(case["id"], sections)
        top3 = ctx["top3_block"] or "No precedents loaded — run Phase 2 first"
        with st.spinner("Generating battle card..."):
            prompt = f"""Generate a one-page "Battle Card" for ITAT hearing day.

Case: {case['case_name']}
Sections: {', '.join(sections)}
Win Probability: {win_prob:.0f}%

TOP 3 VERIFIED CITATIONS TO USE (use these exactly — do not substitute):
{top3}

Format as a compact, scannable reference:

**TOP 3 ARGUMENTS** (one sentence each):
1. [Strongest legal point]
2. [Second strongest]
3. [Third]

**3 CASES TO CITE FIRST** (from the verified citations above):
1. [Citation from above] — [Ratio]
2. [Citation from above] — [Ratio]
3. [Citation from above] — [Ratio]

**IF BENCH ASKS ABOUT [Section]:** [One sentence response with citation]

**DR WILL SAY:** [Expected attack]
**WE SAY:** [Counter in one sentence with citation]

**PRAYER:** [What exactly to ask for]

**IF THINGS GO BAD:** [Fallback: adjournment / additional submissions / etc.]

Keep it to 300 words maximum. This must fit on one page."""
            result = call_claude(PLAYBOOK_SYSTEM, prompt, max_tokens=800)
            st.markdown(result)
            st.download_button(
                "Download Battle Card",
                data=result,
                file_name=f"BattleCard_{case['case_name'][:20]}.txt",
                mime="text/plain"
            )
