"""Litigation Intelligence OS — Main Application Entry Point."""
import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from config import APP_TITLE, APP_SUBTITLE, VERSION
from database.init_db import init_database
from database import queries
from utils.helpers import get_phase_name, parse_sections, format_currency

st.set_page_config(
    page_title="Litigation Intelligence OS",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_database()

# ── Ensure config has the Gemini key loaded from .env on first run ────────────
if "gemini_ready" not in st.session_state:
    import config as _cfg
    if not _cfg.GEMINI_API_KEY:
        # dotenv may not have loaded yet if running in some envs — force reload
        from dotenv import load_dotenv as _ldenv
        _ldenv(override=True)
        _cfg.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        _cfg.GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    st.session_state["gemini_ready"] = True

if "active_case_id" not in st.session_state:
    st.session_state["active_case_id"] = None
if "active_case_name" not in st.session_state:
    st.session_state["active_case_name"] = None
if "current_phase" not in st.session_state:
    st.session_state["current_phase"] = 0
if "api_key" not in st.session_state:
    st.session_state["api_key"] = ""  # kept for any legacy module references

_PHASE_ICONS = {
    1: "📥", 2: "📋", 3: "📚", 4: "⚔️",
    5: "📊", 6: "🕳️", 7: "🏛️", 8: "📅",
    9: "⚡", 10: "🚨", 11: "⏳", 12: "🧠",
}

_PHASE_LABELS = {
    1: "Case Intake", 2: "Evidence Engine", 3: "Submissions & Drafting", 4: "Strategy Simulator",
    5: "Win-Rate Calc", 6: "Evidence Vacuum", 7: "Master Architect", 8: "Day 2-30 Workflow",
    9: "Mid-Trial", 10: "War Room", 11: "Post-Hearing", 12: "Continuous Learning",
}


def _mask(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return key[:8] + "•" * 8 + key[-4:]


def render_sidebar():
    with st.sidebar:
        st.markdown(f"""
<div style='text-align:center;padding:10px 0;'>
<h2 style='color:#1E3A5F;margin:0;'>⚖️ Litigation OS</h2>
<p style='color:#666;font-size:12px;margin:0;'>{VERSION} | Privacy-First</p>
</div>
""", unsafe_allow_html=True)

        # API key status indicator
        import config as _sb_cfg
        _sb_gemini = getattr(_sb_cfg, "GEMINI_API_KEY", "")
        _sb_ik     = _sb_cfg.INDIAN_KANOON_API_KEY
        if _sb_gemini:
            st.success(f"✨ Gemini: {_mask(_sb_gemini)}", icon=None)
        else:
            st.warning("⚠️ No AI key — go to Settings", icon=None)
        if _sb_ik:
            st.success("⚖️ Indian Kanoon: ✓", icon=None)

        st.divider()

        active_id = st.session_state.get("active_case_id")
        if active_id:
            case = queries.get_case(active_id)
            if case:
                sections = parse_sections(case["sections_violated"])
                _role = case.get("client_role") or st.session_state.get("client_role", "assessee")
                _role_labels = {"assessee": "🏢 Assessee", "third_party": "🤝 Third Party", "revenue": "🏛️ Revenue"}
                _role_label = _role_labels.get(_role, "🏢 Assessee")
                st.markdown(f"""
<div style='background:#E8F4FD;padding:10px;border-radius:8px;border-left:4px solid #1E3A5F;'>
<b>📁 Active Case</b><br/>
{case['case_name'][:30]}<br/>
<small>§{', '.join(sections[:2])} | Phase {case['phase']}</small><br/>
<small style='color:#555;'>{_role_label}</small>
</div>
""", unsafe_allow_html=True)
                st.caption(f"AY: {case['assessment_year'] or 'N/A'} | {format_currency(case['demand_amount'] or 0)}")
        else:
            st.info("No active case. Register in Phase 1.")

        st.divider()
        st.markdown("**Navigation**")

        nav_options = {0: "🏠 Dashboard", **{k: f"{v} {k}. {_PHASE_LABELS[k]}" for k, v in _PHASE_ICONS.items()}, 99: "⚙️ Settings"}

        current = st.session_state.get("current_phase", 0)

        if st.button("🏠 Dashboard", use_container_width=True,
                     type="primary" if current == 0 else "secondary"):
            st.session_state["current_phase"] = 0
            st.rerun()

        st.markdown("**Phases**")
        for phase_num, icon in _PHASE_ICONS.items():
            label = _PHASE_LABELS[phase_num]
            is_current = current == phase_num
            if st.button(f"{icon} {phase_num}. {label}", key=f"nav_{phase_num}",
                         use_container_width=True,
                         type="primary" if is_current else "secondary"):
                st.session_state["current_phase"] = phase_num
                st.rerun()

        st.divider()
        if st.button("📎 Citations DB", use_container_width=True,
                     type="primary" if current == 98 else "secondary"):
            st.session_state["current_phase"] = 98
            st.rerun()
        if st.button("⚙️ Settings", use_container_width=True,
                     type="primary" if current == 99 else "secondary"):
            st.session_state["current_phase"] = 99
            st.rerun()


def render_dashboard():
    st.title(f"⚖️ {APP_TITLE}")
    st.markdown(f"### {APP_SUBTITLE}")
    st.caption("Privacy-First | Your Data, Your Server, Your Control")

    # Show setup prompt based on which AI engines are configured
    import config as _dash_cfg
    _has_gemini = bool(getattr(_dash_cfg, "GEMINI_API_KEY", ""))
    if not _has_gemini:
        st.error(
            "**Setup required:** Gemini API key not set. "
            "Go to **⚙️ Settings** and paste your Gemini API key.",
            icon="🔑",
        )
        if st.button("Go to Settings →", type="primary"):
            st.session_state["current_phase"] = 99
            st.rerun()
        st.divider()

    stats = queries.get_statistics()
    cases = queries.get_all_cases()

    from ai.citation_harvester import get_citation_count as _cite_count
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Cases", stats["total_cases"])
    col2.metric("Active Cases", stats["active_cases"])
    col3.metric("Cases Won", stats["won_cases"])
    col4.metric("Verified Citations", f"{_cite_count():,}")

    st.divider()

    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("Active Cases")
        if cases:
            for case in cases[:8]:
                sections = parse_sections(case["sections_violated"])
                phase_icon = _PHASE_ICONS.get(case["phase"], "📋")
                col_a, col_b, col_c, col_d = st.columns([3, 2, 1.5, 1.5])
                with col_a:
                    st.markdown(f"**{case['case_name'][:35]}**")
                    st.caption(f"{case['client_name']} | AY: {case['assessment_year'] or 'N/A'}")
                with col_b:
                    st.write(f"§ {', '.join(sections[:2])}")
                    st.write(format_currency(case["demand_amount"] or 0))
                with col_c:
                    st.write(f"{phase_icon} Phase {case['phase']}")
                with col_d:
                    if st.button("Open", key=f"dash_open_{case['id']}"):
                        st.session_state["active_case_id"] = case["id"]
                        st.session_state["active_case_name"] = case["case_name"]
                        st.session_state["current_phase"] = case["phase"]
                        st.rerun()
                st.divider()
        else:
            st.info("No cases registered yet. Go to Phase 1 to register your first case.")

        if st.button("+ Register New Case", type="primary"):
            st.session_state["current_phase"] = 1
            st.rerun()

    with col_right:
        st.subheader("Workflow")
        for phase_num, icon in _PHASE_ICONS.items():
            label = _PHASE_LABELS[phase_num]
            st.markdown(f"""
<div style='background:#f0f2f6;padding:6px 10px;border-radius:5px;margin:2px 0;font-size:13px;'>
{icon} <b>{phase_num}.</b> {label}
</div>""", unsafe_allow_html=True)

        st.divider()
        st.markdown("**About Litigation OS**")
        st.markdown("""
- 12-Phase ITAT Litigation Pipeline
- 163 IT Act section patterns
- Zero-hallucination evidence mapping
- Privacy-first: 100% local data
- Powered by Claude Sonnet 4.6
""")


def _render_ai_status_banner():
    """
    Show a warning banner when the Gemini API key is not configured.
    """
    import config as _cfg
    if getattr(_cfg, "GEMINI_API_KEY", ""):
        return  # Key set — no banner needed

    col1, col2 = st.columns([5, 1])
    with col1:
        st.error(
            "🔴 **Gemini API key not set** — AI features will not work. "
            "Go to ⚙️ Settings and paste your Gemini key.",
            icon=None,
        )
    with col2:
        if st.button("⚙️ Fix Now", key="_global_fix_btn", type="primary"):
            st.session_state["current_phase"] = 99
            st.rerun()


def main():
    render_sidebar()
    _render_ai_status_banner()

    phase = st.session_state.get("current_phase", 0)

    if phase == 0:
        render_dashboard()
    elif phase == 1:
        from modules.phase1_intake import render
        render()
    elif phase == 2:
        from modules.phase2_evidence import render
        render()
    elif phase == 3:
        from modules.phase3_submissions import render
        render()
    elif phase == 4:
        from modules.phase4_strategy import render
        render()
    elif phase == 5:
        from modules.phase5_winrate import render
        render()
    elif phase == 6:
        from modules.phase6_sandbox import render
        render()
    elif phase == 7:
        from modules.phase7_architect import render
        render()
    elif phase == 8:
        from modules.phase8_workflow import render
        render()
    elif phase == 9:
        from modules.phase9_midtrial import render
        render()
    elif phase == 10:
        from modules.phase10_warroom import render
        render()
    elif phase == 11:
        from modules.phase11_posthearing import render
        render()
    elif phase == 12:
        from modules.phase12_learning import render
        render()
    elif phase == 98:
        from modules.citation_db import render
        render()
    elif phase == 99:
        from modules.settings import render
        render()


if __name__ == "__main__":
    main()
