"""Phase 8: Day 2-30 Case Workflow — structured timeline management."""
import streamlit as st
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections, generate_timeline
from ai.claude_client import call_claude
from ai.prompts import SYSTEM_BASE


def render():
    st.header("Phase 8: Day 2–30 Workflow")
    st.caption("Timeline: Day 2 to 30 — structured task management from registration to hearing readiness.")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case loaded.")
        return

    case = queries.get_case(case_id)
    sections = parse_sections(case["sections_violated"])

    col1, col2 = st.columns([2, 1])
    with col1:
        st.info(f"**{case['case_name']}** | {len(sections)} sections | Registered: {case['created_at'][:10]}")
    with col2:
        if st.button("Generate 30-Day Timeline", type="primary"):
            timeline = generate_timeline(case["created_at"], case.get("hearing_date"))
            for task in timeline:
                queries.add_timeline_task(
                    case_id, task["day_number"], task["task_title"],
                    task["task_description"], task["due_date"], task["phase"]
                )
            st.success("30-day timeline generated!")
            st.rerun()

    tasks = queries.get_timeline_tasks(case_id)

    if tasks:
        _render_timeline_view(tasks)
        _render_kanban_view(tasks)
    else:
        st.info("Click 'Generate 30-Day Timeline' to create your structured action plan.")

    st.divider()
    _render_deadline_tracker(case)


def _render_timeline_view(tasks):
    st.subheader("Timeline View")

    phase_colors = {
        1: "#FF6B6B", 2: "#FF8E53", 3: "#FFC300", 4: "#A8E063",
        5: "#56AB2F", 6: "#11998E", 7: "#3498DB", 8: "#9B59B6",
        9: "#E91E63", 10: "#F44336"
    }

    for task in tasks:
        status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅"}.get(task["status"], "⬜")
        phase_color = phase_colors.get(task["phase"], "#666")
        due = task.get("due_date", "")

        col1, col2, col3, col4 = st.columns([0.5, 3, 1.5, 1.5])
        with col1:
            st.markdown(f"**Day {task['day_number']}**")
        with col2:
            st.markdown(f"{status_icon} **{task['task_title']}**")
            st.caption(task["task_description"])
        with col3:
            st.write(due)
        with col4:
            new_status = st.selectbox(
                "Status",
                ["pending", "in_progress", "completed"],
                index=["pending", "in_progress", "completed"].index(task["status"]),
                key=f"task_status_{task['id']}",
                label_visibility="collapsed"
            )
            if new_status != task["status"]:
                queries.update_timeline_task(task["id"], new_status)
                st.rerun()

    completed = len([t for t in tasks if t["status"] == "completed"])
    progress = completed / len(tasks)
    st.progress(progress, text=f"Progress: {completed}/{len(tasks)} tasks completed ({progress*100:.0f}%)")


def _render_kanban_view(tasks):
    st.subheader("Kanban Board")
    col_pending, col_inprogress, col_done = st.columns(3)

    pending = [t for t in tasks if t["status"] == "pending"]
    in_progress = [t for t in tasks if t["status"] == "in_progress"]
    completed = [t for t in tasks if t["status"] == "completed"]

    with col_pending:
        st.markdown(f"**⬜ Pending ({len(pending)})**")
        for t in pending[:5]:
            st.markdown(f"""
<div style='background:#f0f0f0;padding:8px;margin:4px 0;border-radius:4px;border-left:4px solid #FF6B6B;'>
<b>Day {t['day_number']}</b>: {t['task_title'][:30]}
</div>""", unsafe_allow_html=True)

    with col_inprogress:
        st.markdown(f"**🔄 In Progress ({len(in_progress)})**")
        for t in in_progress:
            st.markdown(f"""
<div style='background:#fff3e0;padding:8px;margin:4px 0;border-radius:4px;border-left:4px solid #FF8E53;'>
<b>Day {t['day_number']}</b>: {t['task_title'][:30]}
</div>""", unsafe_allow_html=True)

    with col_done:
        st.markdown(f"**✅ Completed ({len(completed)})**")
        for t in completed[:5]:
            st.markdown(f"""
<div style='background:#e8f5e9;padding:8px;margin:4px 0;border-radius:4px;border-left:4px solid #56AB2F;'>
<b>Day {t['day_number']}</b>: {t['task_title'][:30]}
</div>""", unsafe_allow_html=True)


def _render_deadline_tracker(case):
    st.subheader("Deadline Tracker")

    appeal_period = 60
    sections = parse_sections(case["sections_violated"])

    col1, col2, col3 = st.columns(3)
    with col1:
        order_date = st.date_input("CIT(A) Order Date", value=None, key="order_date")
    with col2:
        if order_date:
            appeal_deadline = order_date + timedelta(days=appeal_period)
            days_remaining = (appeal_deadline - datetime.now().date()).days
            color = "🔴" if days_remaining < 15 else "🟡" if days_remaining < 30 else "🟢"
            st.metric(f"{color} Days to Appeal Deadline", days_remaining)
    with col3:
        if order_date:
            st.metric("Appeal Deadline", appeal_deadline.strftime("%d %b %Y"))

    if order_date:
        if st.button("Generate Custom Deadline Calendar"):
            with st.spinner("Generating deadline calendar..."):
                prompt = f"""Generate a complete deadline calendar for an ITAT appeal.

Case sections: {', '.join(sections)}
CIT(A) order date: {order_date.strftime('%d %b %Y')}

List all critical deadlines:
1. Last date to file appeal (60 days from order)
2. Stay application deadline
3. Paper book submission deadline
4. Written submissions deadline
5. Any section-specific deadlines

Also: What happens if any deadline is missed? What is the condonation procedure?

Provide dates in DD-MMM-YYYY format."""
                result = call_claude(SYSTEM_BASE, prompt)
                st.markdown(result)

    st.divider()
    st.subheader("Add Custom Task")
    with st.form("add_task_form"):
        task_title = st.text_input("Task Title")
        task_desc = st.text_area("Description", height=80)
        task_day = st.number_input("Day Number", min_value=1, max_value=60, value=7)
        task_phase = st.number_input("Phase", min_value=1, max_value=12, value=2)
        due_date = st.date_input("Due Date")

        if st.form_submit_button("Add Task"):
            case_id = st.session_state.get("active_case_id")
            if case_id and task_title:
                queries.add_timeline_task(
                    case_id, task_day, task_title, task_desc,
                    due_date.strftime("%Y-%m-%d"), task_phase
                )
                st.success("Task added!")
                st.rerun()
