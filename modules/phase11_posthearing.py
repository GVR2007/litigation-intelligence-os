"""Phase 11: Post-Hearing Monitoring & Finalization — the waiting game."""
import streamlit as st
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections, format_currency
from ai.claude_client import call_claude
from ai.prompts import SYSTEM_BASE


def render():
    st.header("Phase 11: Post-Hearing Monitoring")
    st.caption("The Trigger: The final hearing is over. The case awaits ruling. Monitoring and finalization.")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case loaded.")
        return

    case = queries.get_case(case_id)
    sections = parse_sections(case["sections_violated"])
    hearings = queries.get_case_hearings(case_id)

    st.info(f"**{case['case_name']}** | Awaiting ITAT judgment...")

    tab1, tab2, tab3, tab4 = st.tabs([
        "⏳ Status Monitor", "📬 Additional Submissions", "🔔 Alert Setup", "📊 Outcome Predictor"
    ])

    with tab1:
        _render_status_monitor(case, hearings, case_id)

    with tab2:
        _render_additional_submissions(case, sections)

    with tab3:
        _render_alert_setup(case)

    with tab4:
        _render_outcome_predictor(case, sections, hearings)


def _render_status_monitor(case, hearings, case_id):
    st.subheader("Case Status Monitor")

    status_options = ["active", "part_heard", "reserved", "pronounced", "won", "lost", "remanded", "settled"]
    current_status = case.get("status", "active")

    col1, col2 = st.columns(2)
    with col1:
        new_status = st.selectbox("Update Case Status", status_options,
                                  index=status_options.index(current_status) if current_status in status_options else 0)
        if new_status != current_status:
            if st.button("Update Status"):
                queries.update_case_status(case_id, new_status)
                st.success(f"Status updated to: {new_status}")
                st.rerun()

    with col2:
        status_display = {
            "active": ("🟡", "Case Active"),
            "part_heard": ("🔄", "Part Heard"),
            "reserved": ("⏸️", "Order Reserved"),
            "pronounced": ("📋", "Order Pronounced"),
            "won": ("✅", "WON"),
            "lost": ("❌", "Lost"),
            "remanded": ("↩️", "Remanded"),
            "settled": ("🤝", "Settled"),
        }
        icon, label = status_display.get(current_status, ("⚪", current_status))
        st.metric("Current Status", f"{icon} {label}")

    if hearings:
        last_hearing = hearings[0]
        st.markdown("**Last Hearing:**")
        col_a, col_b = st.columns(2)
        col_a.metric("Date", last_hearing.get("hearing_date", "N/A"))
        col_b.metric("Type", last_hearing.get("hearing_type", "N/A"))
        if last_hearing.get("next_date"):
            col_a.metric("Next Date", last_hearing["next_date"])
        if last_hearing.get("notes"):
            st.markdown(f"**Notes:** {last_hearing['notes']}")

    st.divider()
    st.subheader("Post-Hearing Action Items")

    actions = [
        ("File additional written arguments if permitted", False),
        ("Check ITAT website daily for pronouncement", False),
        ("Monitor any similar cases decided by the same bench", False),
        ("Prepare SLP grounds (in case of adverse order)", False),
        ("Brief senior counsel on outcome possibilities", False),
        ("Client has been updated on hearing outcome", False),
    ]

    for i, (action, default) in enumerate(actions):
        st.checkbox(action, key=f"post_action_{i}")

    if st.button("Generate AI Post-Hearing Action Plan"):
        last_hearing_notes = hearings[0]["notes"] if hearings else "No hearing notes"
        last_objections = hearings[0].get("objections_raised", "") if hearings else ""

        with st.spinner("Generating post-hearing plan..."):
            prompt = f"""The ITAT hearing for sections {', '.join(sections)} is over.

Last hearing outcome: {hearings[0].get('outcome', 'pending') if hearings else 'Not logged'}
Objections raised: {last_objections or 'Not logged'}
Notes: {last_hearing_notes}

Generate:
1. Immediate next steps (next 48 hours)
2. How to track when order is pronounced
3. How to read the ITAT website for updates
4. What to prepare while waiting (SLP grounds, appeal to HC?)
5. How to communicate status to client
6. What triggers an urgent escalation"""
            result = call_claude(SYSTEM_BASE, prompt)
            st.markdown(result)


def _render_additional_submissions(case, sections):
    st.subheader("Additional Written Submissions")
    st.caption("File additional submissions if bench has granted time or raised new questions.")

    submission_reason = st.selectbox("Reason for Additional Submissions", [
        "Bench requested clarification",
        "New precedent decided after hearing",
        "Additional documents obtained",
        "Reply to DR's post-hearing note",
        "Rejoinder to Revenue's additional submissions",
        "Other"
    ])

    specific_issue = st.text_area(
        "Specific Issue to Address",
        placeholder="e.g., The bench asked about the SC's recent ruling in XYZ case — provide our position.",
        height=100
    )

    if st.button("Draft Additional Submissions", disabled=not specific_issue):
        with st.spinner("Drafting additional submissions..."):
            prompt = f"""Draft additional written submissions for ITAT for sections {', '.join(sections)}.

Reason: {submission_reason}
Issue to address: {specific_issue}

Draft formal additional submissions:

**ADDITIONAL WRITTEN SUBMISSIONS**

**IN THE INCOME TAX APPELLATE TRIBUNAL**

**IN THE MATTER OF:**
{case['case_name']}

**ADDITIONAL SUBMISSIONS:**

[Address the specific issue with:
1. Legal position
2. Case citations
3. Factual matrix
4. Conclusion]

**PRAYER:**
[Specific relief sought]

Use formal legal language. Keep it concise — additional submissions should be under 5 pages."""
            result = call_claude(SYSTEM_BASE, prompt, max_tokens=4000)
            st.markdown(result)
            st.download_button(
                "Download Additional Submissions",
                data=result,
                file_name=f"AdditionalSubmissions_{case['case_name'][:20]}.txt",
                mime="text/plain"
            )


def _render_alert_setup(case):
    st.subheader("Monitoring & Alert Setup")
    st.caption("Track when the ITAT uploads the order.")

    st.markdown("""
**How to monitor ITAT orders:**

1. **ITAT Official Website**: [itat.gov.in](https://itat.gov.in) → Orders section
2. **Income Tax Portal**: efiling.incometax.gov.in → Pending Actions
3. **Tax Management India / itatonline.org** — for quicker unofficial uploads
4. **Set up Google Alert**: `"[Case Name]" site:itat.gov.in`

**Expected timelines after hearing:**
- Simple cases: 2-4 weeks
- Complex cases: 1-3 months
- Third member reference: 3-6 months
""")

    monitoring_interval = st.selectbox("Check interval reminder", [
        "Daily", "Every 2 days", "Weekly", "When I remember"
    ])

    expected_weeks = st.slider("Expected wait time (weeks)", 1, 24, 4)
    estimated_order_date = (datetime.now() + timedelta(weeks=expected_weeks)).strftime("%d %b %Y")
    st.info(f"Estimated order date: **{estimated_order_date}** (based on {expected_weeks} weeks)")

    st.divider()
    st.subheader("Similar Cases to Monitor")
    if st.button("Find Similar Pending Cases"):
        sections = parse_sections(case["sections_violated"])
        with st.spinner("Identifying similar cases..."):
            prompt = f"""What similar cases on sections {', '.join(parse_sections(case['sections_violated']))} might be decided around the same time that could impact this case?

Provide:
1. Pending SC matters on these sections (any admitted SLPs)
2. Recent HC decisions that ITAT must follow
3. CBDT circulars or instructions recently issued
4. Any Finance Act amendments affecting these sections
5. How pending SC matters could help or hurt our case"""
            result = call_claude(SYSTEM_BASE, prompt)
            st.markdown(result)


def _render_outcome_predictor(case, sections, hearings):
    st.subheader("Outcome Predictor")
    st.caption("Based on hearing progression, predict the likely outcome.")

    hearing_went = st.radio("How did the hearing go?", [
        "Very well — bench seemed convinced",
        "Mixed — bench had questions but heard us fully",
        "Difficult — bench was skeptical",
        "Could not complete — adjourned",
    ])

    bench_signals = st.multiselect("Bench signals observed during hearing:", [
        "Bench asked detailed questions showing interest",
        "Bench interrupted DR frequently",
        "Bench asked about amounts and calculations",
        "Bench seemed sympathetic to hardship argument",
        "Bench was strict on procedural compliance",
        "Bench cited cases unfavorable to us",
        "Bench cited cases favorable to us",
        "Bench granted extra time for additional submissions",
        "Bench suggested settlement",
    ])

    if st.button("Predict Outcome", type="primary"):
        with st.spinner("Analyzing hearing signals..."):
            prompt = f"""Based on the ITAT hearing signals, predict the outcome for sections {', '.join(sections)}.

Hearing went: {hearing_went}
Bench signals: {', '.join(bench_signals) if bench_signals else 'None observed'}
Case demand: {format_currency(case.get('demand_amount', 0))}

Provide:
1. Outcome prediction: Win / Partial Win / Loss (with probability %)
2. Most likely order type: Full relief / Partial / Confirmed / Remanded
3. Key signals that informed this prediction
4. What the order will likely say
5. If partial: Which sections will be decided in our favour?
6. Recommended preparation if order is adverse: SLP to HC? Rectification?

Base this on realistic ITAT outcome patterns."""
            result = call_claude(SYSTEM_BASE, prompt)
            st.markdown(result)
