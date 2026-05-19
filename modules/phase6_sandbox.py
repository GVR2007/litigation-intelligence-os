"""Phase 6: Evidence Vacuum — gap detection and sandboxing."""
import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections
from ai.claude_client import call_claude
from ai.prompts import EVIDENCE_SYSTEM


def render():
    st.header("Phase 6: Evidence Vacuum")
    st.caption("Step 6 — Sandboxing: Detect every gap in your evidence chain before the DR does.")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case loaded.")
        return

    case = queries.get_case(case_id)
    sections = parse_sections(case["sections_violated"])
    evidence = queries.get_case_evidence(case_id)

    st.info(f"**{case['case_name']}** | Running evidence gap analysis...")

    tab1, tab2, tab3 = st.tabs(["🕳️ Gap Detection", "🧪 Evidence Sandbox", "📋 Pre-Filing Checklist"])

    with tab1:
        _render_gap_detection(case_id, sections, evidence)

    with tab2:
        _render_sandbox(case_id, sections, evidence)

    with tab3:
        _render_prefiling_checklist(case_id, sections, evidence)


def _render_gap_detection(case_id, sections, evidence):
    st.subheader("Evidence Gap Detection")
    st.caption("Every missing link in your evidence chain — found before the DR exploits it.")

    unavailable = [e for e in evidence if e["status"] == "unavailable"]
    pending = [e for e in evidence if e["status"] == "pending"]
    mandatory_unavailable = [e for e in unavailable if e["is_mandatory"]]

    col1, col2, col3 = st.columns(3)
    col1.metric("Critical Gaps", len(mandatory_unavailable), delta=f"-{len(mandatory_unavailable)} risk" if mandatory_unavailable else "0 gaps", delta_color="inverse")
    col2.metric("Pending Items", len(pending))
    col3.metric("Evidence Secured", len([e for e in evidence if e["status"] == "available"]))

    if mandatory_unavailable:
        st.error(f"⚠️ {len(mandatory_unavailable)} MANDATORY documents are unavailable — HIGH RISK")
        for item in mandatory_unavailable:
            st.markdown(f"""
<div style='background:#FF4444;color:white;padding:10px;border-radius:5px;margin:5px 0;'>
⚠️ <b>CRITICAL GAP</b>: {item['document_name']} (§{item['section']}) | Win Impact: -{item['win_boost']}%
</div>""", unsafe_allow_html=True)

    if pending:
        st.warning(f"⏳ {len(pending)} documents still pending collection")

    if st.button("Run Full AI Gap Analysis", type="primary"):
        evidence_status = "\n".join([
            f"- [{e['status'].upper()}] {e['document_name']} (§{e['section']}, boost: +{e['win_boost']}%, mandatory: {bool(e['is_mandatory'])})"
            for e in evidence
        ]) if evidence else "No evidence tracked"

        with st.spinner("Analyzing evidence gaps..."):
            prompt = f"""Perform a comprehensive Evidence Gap Analysis for sections {', '.join(sections)}.

Current evidence status:
{evidence_status}

Provide:

**PART 1: CRITICAL GAPS (Mandatory Missing)**
For each mandatory missing document:
- What exactly is missing
- How the DR will use this gap
- Urgency to fill (days remaining threshold)
- Specific remedy

**PART 2: CHAIN OF CUSTODY GAPS**
Are there any missing links in the evidence chain?
(e.g., bank statement shows credit but no source explanation)

**PART 3: CORROBORATION GAPS**
Which available documents are uncorroborated and vulnerable?

**PART 4: TIMELINE GAPS**
Are there any date inconsistencies or missing contemporaneous records?

**PART 5: SILENT ADMISSIONS**
Are there any missing documents whose absence itself implies guilt?

**PART 6: REMEDIATION PLAN**
Priority-ranked 7-day action plan to close the most critical gaps.

Be brutally honest — this is a pre-filing audit."""
            result = call_claude(EVIDENCE_SYSTEM, prompt, max_tokens=5000)
            st.markdown(result)


def _render_sandbox(case_id, sections, evidence):
    st.subheader("Evidence Sandbox")
    st.caption("Test your evidence chain against hypothetical scenarios before the actual hearing.")

    scenario = st.selectbox("Select Test Scenario", [
        "DR challenges: 'Where is the cash book entry?'",
        "Bench asks: 'Why was cash taken despite having a bank account?'",
        "DR argues: 'The affidavit is post-dated by 30 days'",
        "Bench: 'The creditor has not filed ITR — explain the source'",
        "DR: 'The confirmation letter is from a related party — not independent'",
        "Bench: 'Amount exceeds ₹20L — why no banking channel?'",
        "Custom scenario (type below)",
    ])

    if scenario == "Custom scenario (type below)":
        custom_scenario = st.text_area("Describe the scenario", height=100)
        scenario = custom_scenario

    available_docs = [e["document_name"] for e in evidence if e["status"] == "available"]

    if st.button("Run Sandbox Test", type="primary"):
        with st.spinner("Running sandbox simulation..."):
            prompt = f"""Sandbox Test for sections {', '.join(sections)}.

Scenario: {scenario}

Available evidence: {', '.join(available_docs) if available_docs else 'None'}

Simulate:
1. The exact objection/question in legal terms
2. The best immediate response using available evidence
3. Which specific document answers this challenge
4. If no document exists, what is the verbal response?
5. Does this scenario expose a critical weakness?
6. What additional document would completely solve this issue?

Rate the response strength: 1-10."""
            result = call_claude(EVIDENCE_SYSTEM, prompt)
            st.markdown(result)

    st.divider()
    st.subheader("Batch Stress Test")
    if st.button("Run All Common Scenarios"):
        scenarios = [
            "DR challenges: No contemporaneous cash book entries",
            "Bench asks about source of funds for creditor",
            "DR argues penalty u/s 271D should be imposed",
            "Bench questions reasonable cause under 273B",
        ]
        for s in scenarios:
            with st.expander(f"Scenario: {s}"):
                with st.spinner(f"Testing: {s}"):
                    prompt = f"Sandbox test for §{', '.join(sections)}: {s}\nAvailable docs: {', '.join(available_docs[:5])}\nProvide: best response (3 sentences), weakness exposed (yes/no), fix needed."
                    result = call_claude(EVIDENCE_SYSTEM, prompt, max_tokens=600)
                    st.markdown(result)


def _render_prefiling_checklist(case_id, sections, evidence):
    st.subheader("Pre-Filing Checklist")
    st.caption("Mandatory verification before submitting to ITAT.")

    checklist = [
        ("Grounds of Appeal filed within 60 days of CIT(A) order", False),
        ("Form 36 / 36A filled completely", False),
        ("Stay application filed (if demand outstanding)", False),
        ("Paper book compiled and indexed", False),
        ("All cited cases printed and paginated", False),
        ("Vakalatnama signed and stamped", False),
        ("AR details updated", False),
        ("Evidence list finalized", False),
        ("Written submissions drafted", False),
        ("All amounts verified for consistency", False),
    ]

    st.markdown("**Mark each item as completed:**")
    completed_count = 0
    for i, (task, default) in enumerate(checklist):
        checked = st.checkbox(task, value=default, key=f"prefiling_{i}")
        if checked:
            completed_count += 1

    progress = completed_count / len(checklist)
    st.progress(progress, text=f"{completed_count}/{len(checklist)} items completed")

    if completed_count == len(checklist):
        st.success("✅ All pre-filing checks complete! Ready to advance to Phase 7: Master Architect.")
    else:
        remaining = len(checklist) - completed_count
        st.warning(f"{remaining} items remaining before you can file.")

    st.divider()
    if st.button("Generate AI Pre-Filing Risk Report"):
        evidence_summary = f"Available: {len([e for e in evidence if e['status'] == 'available'])}, Pending: {len([e for e in evidence if e['status'] == 'pending'])}, Unavailable: {len([e for e in evidence if e['status'] == 'unavailable'])}"
        with st.spinner("Generating pre-filing risk report..."):
            prompt = f"""Generate a pre-filing risk report for sections {', '.join(sections)}.

Evidence Status: {evidence_summary}
Pre-filing checklist: {completed_count}/{len(checklist)} completed

Provide:
1. Overall filing readiness score: X/10
2. Top 3 risks if filed immediately
3. What CANNOT be added after filing
4. Last-minute document additions still possible
5. Recommended: File now or delay?
6. If delay: What to achieve in extra time?"""
            result = call_claude(EVIDENCE_SYSTEM, prompt)
            st.markdown(result)
