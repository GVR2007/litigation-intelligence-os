"""Phase 5: Win-Rate Calculator — strategy & evidence ROI scoring."""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections, calculate_overall_win_rate, format_currency
from ai.claude_client import call_claude
from ai.prompts import WINRATE_SYSTEM


def render():
    st.header("Phase 5: Win-Rate Calculator")
    st.caption("Step 5 — Strategy & Evidence ROI: Precise probability scoring with actionable improvement paths.")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case loaded.")
        return

    case = queries.get_case(case_id)
    sections = parse_sections(case["sections_violated"])
    evidence = queries.get_case_evidence(case_id)

    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("Overall Win Probability")
        if evidence:
            win_data = calculate_overall_win_rate(evidence)
            prob = win_data["win_probability"]

            fig = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=prob,
                delta={"reference": 50},
                title={"text": "Win Probability %"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "#1E3A5F"},
                    "steps": [
                        {"range": [0, 40], "color": "#FF4444"},
                        {"range": [40, 65], "color": "#FF8800"},
                        {"range": [65, 100], "color": "#22AA44"},
                    ],
                    "threshold": {
                        "line": {"color": "white", "width": 4},
                        "thickness": 0.75,
                        "value": prob
                    }
                }
            ))
            fig.update_layout(height=300, margin=dict(t=50, b=0))
            st.plotly_chart(fig, use_container_width=True)

            risk_colors = {"LOW": "success", "MEDIUM": "warning", "HIGH": "error"}
            risk = win_data["risk_level"]
            getattr(st, risk_colors[risk])(f"Risk Level: {risk}")

            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Evidence Boost", f"+{win_data['total_boost']}%")
            col_b.metric("Evidence Penalty", f"-{win_data['total_penalty']:.0f}%")
            col_c.metric("Net Impact", f"{win_data['total_boost'] - win_data['total_penalty']:.0f}%")
        else:
            st.info("Generate evidence list in Phase 2 to see win probability.")
            prob = 45.0

    with col2:
        st.subheader("Evidence ROI Chart")
        if evidence:
            available = [e for e in evidence if e["status"] == "available"]
            pending = [e for e in evidence if e["status"] == "pending"]

            if available or pending:
                chart_data = available[:8] if available else pending[:8]
                fig2 = px.bar(
                    x=[e["win_boost"] for e in chart_data],
                    y=[e["document_name"][:25] for e in chart_data],
                    orientation='h',
                    color=[e["win_boost"] for e in chart_data],
                    color_continuous_scale=["#FF4444", "#FF8800", "#22AA44"],
                    labels={"x": "Win Boost %", "y": "Document"},
                    title="Evidence Win-Rate Contribution"
                )
                fig2.update_layout(height=300, margin=dict(t=50, b=0), showlegend=False)
                st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Evidence ROI Matrix")

    if evidence:
        col_headers = st.columns([3, 1, 1, 1.5, 2])
        col_headers[0].markdown("**Document**")
        col_headers[1].markdown("**Win Boost**")
        col_headers[2].markdown("**Priority**")
        col_headers[3].markdown("**Status**")
        col_headers[4].markdown("**ROI Action**")

        for item in evidence:
            cols = st.columns([3, 1, 1, 1.5, 2])
            cols[0].write(item["document_name"][:35])
            cols[1].write(f"+{item['win_boost']}%")
            cols[2].write("MUST" if item["is_mandatory"] else "Should")
            status_icons = {"available": "✅", "pending": "⏳", "unavailable": "❌"}
            cols[3].write(f"{status_icons.get(item['status'], '?')} {item['status']}")
            if item["status"] == "unavailable" and item["is_mandatory"]:
                cols[4].markdown("⚠️ **HIGH RISK** — Get substitute")
            elif item["status"] == "pending":
                cols[4].write("Collect ASAP")
            else:
                cols[4].write("✓ Secured")

    st.divider()
    st.subheader("AI Win-Rate Deep Analysis")

    col1, col2 = st.columns(2)
    with col1:
        bench_location = st.selectbox("Bench Location", [
            "Delhi", "Mumbai", "Kolkata", "Chennai", "Ahmedabad",
            "Bangalore", "Hyderabad", "Pune", "Chandigarh", "Jaipur"
        ])
    with col2:
        years_data = st.slider("Years of Historical Data to Analyze", 5, 20, 10)

    if st.button("Run Full Win-Rate Analysis", type="primary"):
        evidence_summary = "\n".join([
            f"- {e['document_name']}: {e['status']} (boost: +{e['win_boost']}%)"
            for e in evidence
        ]) if evidence else "No evidence tracked yet"

        with st.spinner("Running probability analysis..."):
            prompt = f"""Perform a comprehensive win-rate analysis for this ITAT case.

Case Details:
- Sections: {', '.join(sections)}
- Bench: {bench_location} ITAT
- Assessment Year: {case.get('assessment_year', 'Not specified')}
- Demand: ₹{case.get('demand_amount', 0):,.0f}

Evidence Status:
{evidence_summary}

Based on {years_data} years of ITAT data, provide:

**1. PROBABILITY ASSESSMENT**
- Overall win probability: X%
- Confidence interval: X% to X%
- Key drivers of this estimate

**2. SECTION-WISE PROBABILITY**
For each section, probability of deletion/relief:
- § [section]: X% (reason)

**3. SCENARIO ANALYSIS**
- Best case scenario (all evidence secured): X%
- Current scenario: X%
- Worst case (more evidence lost): X%

**4. CRITICAL PATH**
The single most important thing to do to increase win rate:

**5. ROI OF REMAINING EVIDENCE**
If you can only get ONE more document, which one gives the highest win boost?

**6. BENCH-SPECIFIC ADJUSTMENT**
{bench_location} ITAT historical bias on these sections: +/- X%

**7. FINAL RECOMMENDATION**
Should the assessee: Fight / Settle / File SLP if lost?"""
            result = call_claude(WINRATE_SYSTEM, prompt, max_tokens=5000)
            st.markdown(result)

    st.divider()
    st.subheader("Sensitivity Analysis")
    st.caption("See how each evidence item impacts your win probability.")

    if evidence and st.button("Run Sensitivity Analysis"):
        with st.spinner("Running sensitivity analysis..."):
            items = [f"- {e['document_name']} (currently {e['status']})" for e in evidence[:10]]
            prompt = f"""Run a sensitivity analysis for sections {', '.join(sections)}.

Current evidence:
{chr(10).join(items)}

For each document currently marked pending or unavailable:
1. Impact if secured: win probability increases by X%
2. Impact if lost entirely: win probability decreases by X%
3. Priority rank (1=most critical to secure)

Provide a ranked action list: which documents should the lawyer chase first to maximize win probability?"""
            result = call_claude(WINRATE_SYSTEM, prompt)
            st.markdown(result)
