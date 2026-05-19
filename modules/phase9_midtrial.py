"""Phase 9: Mid-Trial Dynamics — instant adaptive drafting for surprise objections."""
import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections
from ai.claude_client import call_claude, stream_claude
from ai.prompts import MIDTRIAL_SYSTEM


def render():
    st.header("Phase 9: Mid-Trial Dynamics")
    st.caption("The Trigger: The court fires back a new objection. Instant adaptive drafting — respond in seconds.")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case loaded.")
        return

    case = queries.get_case(case_id)
    sections = parse_sections(case["sections_violated"])
    evidence = queries.get_case_evidence(case_id)
    available_docs = [e["document_name"] for e in evidence if e["status"] == "available"]

    st.warning("⚡ LIVE HEARING MODE — Real-time adaptive response system active")

    tab1, tab2, tab3 = st.tabs(["⚡ Instant Response", "📋 Objection Log", "🔄 Hearing Tracker"])

    with tab1:
        _render_instant_response(case, sections, available_docs)

    with tab2:
        _render_objection_log(case_id)

    with tab3:
        _render_hearing_tracker(case_id, case)


def _render_instant_response(case, sections, available_docs):
    st.subheader("Instant Adaptive Drafting")

    source = st.radio("Objection Source", ["Bench/Member", "DR (Departmental Representative)", "AO Representative"])

    objection = st.text_area(
        "Type/paste the exact objection or question:",
        placeholder="e.g., 'Counsel, the affidavit from the creditor is undated. How do you explain this?'\n\nOr: 'The cash book entries appear to be made in a different ink — they look backdated.'",
        height=120,
        key="live_objection"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        response_mode = st.radio("Response Mode", [
            "Instant oral response (30 seconds)",
            "Request 2-minute pause",
            "Request adjournment for additional evidence"
        ])
    with col2:
        urgency = st.selectbox("Urgency", ["🔴 CRITICAL — answer now", "🟡 Important", "🟢 Routine"])

    if st.button("Generate Instant Response", type="primary", disabled=not objection):
        mode_instruction = {
            "Instant oral response (30 seconds)": "Provide a 2-3 sentence immediate oral response. Use clear, confident language.",
            "Request 2-minute pause": "Provide a 5-7 sentence detailed response for after a brief pause.",
            "Request adjournment for additional evidence": "Provide grounds for adjournment request and what additional evidence to promise."
        }[response_mode]

        prompt = f"""LIVE HEARING: Instant response needed NOW.

Case: {case['case_name']}
Sections: {', '.join(sections)}
Source: {source}
Objection: {objection}
Available documents: {', '.join(available_docs[:8]) if available_docs else 'As in paper book'}

{mode_instruction}

Provide:

**IMMEDIATE RESPONSE:**
[Exact words to say at the podium]

**DOCUMENT TO SHOW:**
[Which specific document from available evidence answers this]

**LEGAL BASIS:**
[One case citation that supports our position]

**RISK ASSESSMENT:**
[Does this objection threaten the case? High/Medium/Low]

**IF THEY PUSH BACK:**
[Next response if the bench/DR is not satisfied]

Keep the immediate response under 60 words for oral delivery."""

        with st.container():
            st.markdown("---")
            st.markdown("### ⚡ INSTANT RESPONSE:")
            result_placeholder = st.empty()
            full_result = ""
            for chunk in stream_claude(MIDTRIAL_SYSTEM, prompt, max_tokens=1500):
                full_result += chunk
                result_placeholder.markdown(full_result + "▌")
            result_placeholder.markdown(full_result)

            if not full_result.startswith("[ERROR]"):
                if "objections" not in st.session_state:
                    st.session_state["objections"] = []
                st.session_state["objections"].append({
                    "source": source,
                    "objection": objection,
                    "response": full_result[:500],
                    "risk": urgency,
                })

    st.divider()
    st.subheader("Quick-Fire Response Library")
    st.caption("Pre-prepared responses for the most common mid-hearing challenges.")

    common_objections = {
        "Affidavit post-dated": f"Your Honour, Section 273B provides complete immunity where reasonable cause exists. The affidavit was obtained as the original creditor was in [location]. We have [bank statement] corroborating the contemporaneous transaction.",
        "Why was cash taken?": f"The transaction occurred in [year] before mandatory banking channels were implemented. Rule 6DD provides specific exemptions. We rely on [Case Name] [(citation)] where identical facts were accepted.",
        "No ITR of creditor": "We have the PAN and identity proof of the creditor. Their ITR shows agricultural income which need not be filed if below threshold. We have an affidavit explaining the source.",
        "Penalty mandatory u/s 271D": "Your Honour, Section 273B is a complete answer — penalty cannot be imposed where reasonable cause is established. We rely on CIT v. Triumph International [(2012) 345 ITR 270 (Bom)].",
    }

    for objection_type, template_response in common_objections.items():
        with st.expander(f"🎯 If bench asks: '{objection_type}'"):
            st.markdown(f"**Template Response:** {template_response}")
            if st.button(f"Customize for My Case", key=f"customize_{objection_type[:10]}"):
                st.session_state["live_objection"] = objection_type
                st.rerun()


def _render_objection_log(case_id):
    st.subheader("Objection Log")
    st.caption("Track all objections raised during the hearing for post-hearing analysis.")

    objections = st.session_state.get("objections", [])

    if objections:
        for i, obj in enumerate(reversed(objections), 1):
            with st.expander(f"Objection #{len(objections)-i+1}: {obj['objection'][:50]}..."):
                st.write(f"**Source:** {obj['source']} | **Risk:** {obj['risk']}")
                st.write(f"**Objection:** {obj['objection']}")
                st.write(f"**Response Used:** {obj['response'][:300]}")
    else:
        st.info("No objections logged yet. They will appear here as you use the Instant Response tab.")

    if objections and st.button("Add All to Hearing Record"):
        for obj in objections:
            queries.add_hearing(
                case_id,
                datetime.now().strftime("%Y-%m-%d") if 'datetime' in dir() else "2026-01-01",
                "ITAT Hearing",
                "ITAT",
                "pending",
                f"Objections: {len(objections)}",
                "\n".join([o["objection"] for o in objections[:5]])
            )
        st.success("Hearing record updated!")


def _render_hearing_tracker(case_id, case):
    st.subheader("Hearing Tracker")

    st.markdown("**Log a New Hearing:**")
    with st.form("hearing_form"):
        col1, col2 = st.columns(2)
        with col1:
            hearing_date = st.date_input("Hearing Date")
            bench = st.text_input("Bench / Members", placeholder="e.g., Judicial Member + Accountant Member")
        with col2:
            hearing_type = st.selectbox("Hearing Type", [
                "Admission", "Hearing on Merits", "Part-Heard",
                "Stayed/Adjourned", "Final Arguments", "Pronouncement"
            ])
            outcome = st.selectbox("Outcome", [
                "pending", "adjourned", "part_heard", "stayed",
                "decided_favor", "decided_against", "remanded"
            ])

        objections_raised = st.text_area("Objections/Questions Raised by Bench", height=80)
        next_date = st.date_input("Next Hearing Date", value=None)
        notes = st.text_area("Notes", height=80)

        if st.form_submit_button("Log Hearing"):
            from datetime import datetime
            queries.add_hearing(
                case_id,
                hearing_date.strftime("%Y-%m-%d"),
                hearing_type, bench, outcome,
                notes, objections_raised,
                next_date.strftime("%Y-%m-%d") if next_date else None
            )
            st.success("Hearing logged!")
            st.rerun()

    hearings = queries.get_case_hearings(case_id)
    if hearings:
        st.markdown("**Hearing History:**")
        for h in hearings:
            status_icons = {
                "pending": "⏳", "adjourned": "📅", "part_heard": "🔄",
                "decided_favor": "✅", "decided_against": "❌", "stayed": "⏸️"
            }
            icon = status_icons.get(h["outcome"], "📋")
            with st.expander(f"{icon} {h['hearing_date']} — {h['hearing_type']}"):
                st.write(f"**Bench:** {h['bench']}")
                st.write(f"**Outcome:** {h['outcome']}")
                if h["objections_raised"]:
                    st.write(f"**Objections:** {h['objections_raised']}")
                if h["next_date"]:
                    st.write(f"**Next Date:** {h['next_date']}")
                if h["notes"]:
                    st.write(f"**Notes:** {h['notes']}")
