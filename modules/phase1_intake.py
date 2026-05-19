"""Phase 1: PDF Drop & Case Intake — upload → auto-scan → case intelligence report."""
import streamlit as st
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import ITAT_SECTIONS, UPLOADS_DIR
from database import queries
from utils.pdf_parser import parse_assessment_order
from utils.helpers import format_currency, parse_sections
from ai.claude_client import call_claude
from ai.prompts import SECTION_ANALYSIS_SYSTEM


def render():
    # ── Client identification gate — must answer before anything else ─────────
    if "client_role" not in st.session_state:
        _render_client_identification()
        return

    # ── Role badge + change option ────────────────────────────────────────────
    _render_role_badge()

    st.header("Phase 1: Case Intake & Intelligence Report")
    st.caption("Upload the Assessment / Penalty Order — sections detected, similar cases found instantly.")

    # ── PDF Upload (full width — report is below) ─────────────────────────────
    uploaded_pdf = st.file_uploader(
        "📂 Drop the Assessment Order / Penalty Order / Notice PDF here",
        type=["pdf"],
        key="pdf_upload",
    )

    scan_key   = "pdf_scan_result"
    report_key = "case_intel_report"

    if uploaded_pdf is not None:
        last_filename = st.session_state.get("pdf_last_filename")
        if last_filename != uploaded_pdf.name:
            os.makedirs(UPLOADS_DIR, exist_ok=True)
            pdf_path = os.path.join(UPLOADS_DIR, uploaded_pdf.name)
            with open(pdf_path, "wb") as f:
                f.write(uploaded_pdf.getbuffer())

            with st.spinner(f"📄 Scanning {uploaded_pdf.name}..."):
                parsed = parse_assessment_order(pdf_path)

            st.session_state[scan_key]             = parsed
            st.session_state["pdf_last_filename"]  = uploaded_pdf.name
            st.session_state["pdf_path"]           = pdf_path
            # Clear old report so it regenerates for new file
            st.session_state.pop(report_key, None)

    scan = st.session_state.get(scan_key)

    # ── After scan: show metadata strip + auto-trigger intelligence report ────
    if scan:
        detected = scan.get("sections_violated", [])
        pdf_text = scan.get("raw_text", "")

        # Quick metadata bar
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Sections", len(detected))
        m2.metric("AY",       scan.get("assessment_year") or "—")
        m3.metric("PAN",      scan.get("pan") or "—")
        m4.metric("Demand ₹", format_currency(scan.get("demand_amount", 0)))
        m5.metric("Pages",    scan.get("page_count", "—"))

        if scan.get("assessee_name"):
            st.info(f"👤 Assessee: **{scan['assessee_name']}**")

        if not detected:
            st.warning(
                "⚠️ No standard sections auto-detected. "
                "PDF may be image-based or use non-standard phrasing. "
                "Select sections manually in the 'Register Case' tab below."
            )
        else:
            # Section badges
            badge_cols = st.columns(min(len(detected), 6))
            for i, sec in enumerate(detected):
                info = ITAT_SECTIONS.get(sec, {})
                risk_color = (
                    "#C62828" if sec in {"153A", "271(1)(c)", "270A", "68", "69"}
                    else "#E65100" if sec in {"269SS", "271D", "269T", "271E", "40A(3)"}
                    else "#1565C0"
                )
                badge_cols[i % 6].markdown(
                    f"<div style='background:{risk_color};color:white;padding:8px;"
                    f"border-radius:6px;text-align:center;margin:3px 0;'>"
                    f"<b>§ {sec}</b><br/><small>{info.get('name','')[:30]}</small></div>",
                    unsafe_allow_html=True,
                )

        # ── PII Redaction status ──────────────────────────────────────────────
        _show_pii_status(scan)

        st.divider()

        # ── Tabs: Intelligence Report | Register Case | Section Analysis ──────
        tab_report, tab_register, tab_sections = st.tabs([
            "📊 Intelligence Report",
            "📝 Register Case",
            "🔬 Section Analysis",
        ])

        # ══════════════════════════════════════════════════════════════════════
        # TAB 1 — INTELLIGENCE REPORT
        # ══════════════════════════════════════════════════════════════════════
        with tab_report:
            _render_intelligence_tab(scan, detected, pdf_text, report_key)

        # ══════════════════════════════════════════════════════════════════════
        # TAB 2 — REGISTER CASE
        # ══════════════════════════════════════════════════════════════════════
        with tab_register:
            _render_register_form(scan, detected)

        # ══════════════════════════════════════════════════════════════════════
        # TAB 3 — SECTION ANALYSIS
        # ══════════════════════════════════════════════════════════════════════
        with tab_sections:
            if detected:
                _show_section_analysis(
                    st.session_state.get("active_case_id", 0),
                    detected,
                    force_expand=False,
                )
            else:
                st.info("Upload a PDF with detectable sections to see section-by-section analysis.")

    else:
        # No PDF yet — show instructions + existing cases
        _render_landing()


# ── Intelligence Report Tab ───────────────────────────────────────────────────

def _render_intelligence_tab(scan: dict, sections: list, pdf_text: str, report_key: str):
    """Auto-run or show cached case intelligence report."""
    from modules.case_report import render_report

    existing_report = st.session_state.get(report_key)

    if existing_report:
        # Already generated — show cached
        render_report(existing_report)
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🔄 Re-generate Report", key="regen_report"):
                st.session_state.pop(report_key, None)
                st.rerun()
        return

    if not sections:
        st.info(
            "No sections detected from PDF. "
            "Select sections in the **Register Case** tab, "
            "then return here to generate the intelligence report."
        )
        _manual_report_trigger(scan, sections, pdf_text, report_key)
        return

    # Auto-trigger: show a spinner and run the pipeline
    st.info("🤖 Analysing case and finding similar judgments — please wait...")
    _run_report_pipeline(scan, sections, pdf_text, report_key)


def _manual_report_trigger(scan: dict, sections: list, pdf_text: str, report_key: str):
    """Fallback: manual section picker + run button."""
    all_secs = sorted(ITAT_SECTIONS.keys())
    chosen = st.multiselect("Select sections to analyse", all_secs, key="manual_secs")
    if chosen and st.button("🚀 Generate Intelligence Report", type="primary"):
        _run_report_pipeline(scan, chosen, pdf_text, report_key)


def _run_report_pipeline(scan: dict, sections: list, pdf_text: str, report_key: str):
    """Run ai.case_analyser.build_report() and cache result."""
    from ai.case_analyser import build_report

    metadata = {
        "assessment_year": scan.get("assessment_year", ""),
        "demand_amount":   scan.get("demand_amount", 0) or 0,
        "assessee_name":   scan.get("assessee_name", ""),
        "pan":             scan.get("pan", ""),
    }

    log_box   = st.empty()
    log_lines = []

    def cb(msg):
        log_lines.append(msg)
        log_box.code("\n".join(log_lines[-20:]), language="bash")

    with st.spinner("🔍 Searching across all sources..."):
        try:
            report = build_report(
                pdf_text=pdf_text or "",
                sections=sections,
                metadata=metadata,
                progress_cb=cb,
            )
            st.session_state[report_key] = report
            log_box.empty()
            st.rerun()
        except Exception as e:
            log_box.empty()
            st.error(f"Report generation failed: {e}")


# ── PII Redaction Status ──────────────────────────────────────────────────────

def _show_pii_status(scan: dict):
    """Show what PII was detected and will be redacted before sending to AI."""
    from utils.pii_redactor import redact_for_ai

    raw_text = scan.get("raw_text", "")
    if not raw_text:
        return

    _, report = redact_for_ai(raw_text, scan_metadata=scan)

    if report.total == 0:
        st.success("🔒 No sensitive identifiers detected in document.")
        return

    with st.expander(
        f"🔒 **Privacy Shield** — {report.total} sensitive item(s) will be redacted before sending to AI",
        expanded=False,
    ):
        st.markdown(report.summary())
        st.markdown(
            "<small style='color:#888'>PAN, Aadhaar, names, mobile numbers, addresses "
            "are replaced with tokens like 《PAN-REDACTED》 before the text reaches any AI model. "
            "Your original document is never modified.</small>",
            unsafe_allow_html=True,
        )


# ── Register Case Tab ─────────────────────────────────────────────────────────

def _render_register_form(scan: dict, detected: list):
    """Case registration form (pre-filled from scan)."""
    with st.form("new_case_form", clear_on_submit=False):
        case_name = st.text_input(
            "Case Title *",
            value=f"{scan.get('assessee_name', '')} vs DCIT" if scan.get("assessee_name") else "",
            placeholder="e.g., M/s ABC Traders vs DCIT Ward 5(2)",
        )
        client_name = st.text_input(
            "Client / Assessee Name *",
            value=scan.get("assessee_name", "") if scan else "",
            placeholder="Full legal name of assessee",
        )
        col_a, col_b = st.columns(2)
        with col_a:
            assessee_pan = st.text_input(
                "PAN",
                value=scan.get("pan", "") if scan else "",
                placeholder="ABCDE1234F",
            )
            assessment_year = st.text_input(
                "Assessment Year",
                value=scan.get("assessment_year", "") if scan else "",
                placeholder="2022-23",
            )
        with col_b:
            ao_name = st.text_input(
                "Assessing Officer / Office",
                value=scan.get("ao_name", "") if scan else "",
                placeholder="ITO Ward 4(1), Mumbai",
            )
            ao_ward = st.text_input("AO Ward/Circle", placeholder="Ward 4(1)")

        demand_amount = st.number_input(
            "Demand / Penalty Amount (₹)",
            value=float(scan.get("demand_amount", 0)) if scan else 0.0,
            min_value=0.0,
            step=1000.0,
        )
        hearing_date = st.date_input("Next Hearing Date (optional)", value=None)

        st.markdown("**Violated Sections** — auto-detected. Add any missed:")
        all_sections = sorted(ITAT_SECTIONS.keys())
        extra_sections = st.multiselect(
            "Add / remove sections",
            options=all_sections,
            default=detected,
            help="Sections auto-detected from PDF are pre-selected.",
        )

        submit = st.form_submit_button("✅ Register Case", type="primary")

    if submit:
        if not case_name.strip() or not client_name.strip():
            st.error("Case title and client name are required.")
            return

        final_sections = extra_sections or detected
        if not final_sections:
            st.error("Please select at least one section.")
            return

        hearing_str = hearing_date.strftime("%Y-%m-%d") if hearing_date else None
        case_id = queries.create_case(
            case_name.strip(), client_name.strip(),
            assessee_pan, assessment_year,
            ao_name, ao_ward,
            final_sections, demand_amount, hearing_str,
            client_role=st.session_state.get("client_role", "assessee"),
        )
        st.session_state["active_case_id"]   = case_id
        st.session_state["active_case_name"] = case_name
        st.session_state.pop("pdf_scan_result", None)
        st.session_state.pop("pdf_last_filename", None)
        st.success(f"✅ Case registered — ID #{case_id} with {len(final_sections)} section(s).")
        st.balloons()


# ── Landing page (no PDF yet) ─────────────────────────────────────────────────

def _render_landing():
    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("""
        ### How it works

        1. **Upload** your Assessment Order or Penalty Notice PDF above
        2. **Auto-scan** detects violated sections (§269SS, §68, §271D etc.)
        3. **Intelligence Report** is generated immediately:
           - 📜 CBDT Circulars related to your case
           - ⚖️ Supreme Court judgments (live Indian Kanoon search)
           - 🏛️ High Court judgments (IK + itatonline.org)
           - 📁 ITAT Orders (all scraped sources)
           - 📜 Finance Act history of the sections
        4. **Register** the case to proceed to full litigation workflow
        """)

    with col2:
        st.subheader("Existing Cases")
        cases = queries.get_all_cases()
        if cases:
            for case in cases[:5]:
                secs = parse_sections(case["sections_violated"])
                with st.expander(f"#{case['id']} — {case['case_name'][:28]}"):
                    st.write(f"**AY:** {case['assessment_year'] or '—'} | Phase {case['phase']}")
                    sec_badges = " ".join(f"`§{s}`" for s in secs)
                    st.markdown(f"**Sections:** {sec_badges or '—'}")
                    st.write(f"**Demand:** {format_currency(case['demand_amount'] or 0)}")
                    if st.button("Load Case", key=f"load_{case['id']}"):
                        st.session_state["active_case_id"]   = case["id"]
                        st.session_state["active_case_name"] = case["case_name"]
                        st.rerun()
        else:
            st.info("No cases yet. Upload a PDF to begin.")

    # Active case panel
    if st.session_state.get("active_case_id"):
        case_id = st.session_state["active_case_id"]
        case    = queries.get_case(case_id)
        if case:
            st.divider()
            secs = parse_sections(case["sections_violated"])
            st.subheader(f"Active: {case['case_name']}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Sections",  len(secs))
            c2.metric("Demand",    format_currency(case["demand_amount"] or 0))
            c3.metric("AY",        case["assessment_year"] or "—")
            c4.metric("Phase",     f"Phase {case['phase']}")

            if secs:
                st.subheader("Section Analysis")
                _show_section_analysis(case_id, secs, force_expand=False)

            if st.button("→ Phase 2: Evidence Engine", type="primary"):
                queries.update_case_phase(case_id, 2)
                st.session_state["current_phase"] = 2
                st.rerun()


# ── Client Identification ─────────────────────────────────────────────────────

def _render_client_identification():
    """
    One-time gate shown before Phase 1.
    Asks who the client is in this matter.
    Stores answer in st.session_state['client_role'].
    """
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        "<h2 style='text-align:center;color:#1E3A5F;'>⚖️ Before we begin</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;color:#555;font-size:16px;'>"
        "Who is your client in this matter?</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)

    _ROLES = {
        "assessee": {
            "label":    "The Assessee",
            "icon":     "🏢",
            "desc":     "Representing the taxpayer — defending against additions, penalties, or reassessment.",
            "bg":       "#E3F2FD",
            "border":   "#1565C0",
        },
        "third_party": {
            "label":    "A Third Party",
            "icon":     "🤝",
            "desc":     "Acting for a lender, creditor, director, or other person summoned or implicated.",
            "bg":       "#F3E5F5",
            "border":   "#6A1B9A",
        },
        "revenue": {
            "label":    "The Revenue",
            "icon":     "🏛️",
            "desc":     "Advising the Department — preparing grounds to sustain an assessment or penalty.",
            "bg":       "#FFF3E0",
            "border":   "#E65100",
        },
    }

    col1, col2, col3 = st.columns(3)
    cols = [col1, col2, col3]

    for col, (role_key, role) in zip(cols, _ROLES.items()):
        with col:
            st.markdown(
                f"""
<div style='
    background:{role["bg"]};
    border:2px solid {role["border"]};
    border-radius:12px;
    padding:24px 16px;
    text-align:center;
    min-height:160px;
'>
<div style='font-size:36px;'>{role["icon"]}</div>
<h3 style='margin:8px 0 6px 0;color:{role["border"]};'>{role["label"]}</h3>
<p style='color:#555;font-size:13px;margin:0;'>{role["desc"]}</p>
</div>
""",
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(
                f"Select — {role['label']}",
                key=f"role_{role_key}",
                use_container_width=True,
                type="primary",
            ):
                st.session_state["client_role"] = role_key
                st.rerun()


def _render_role_badge():
    """
    Small banner at the top of Phase 1 showing the chosen client role.
    Includes a 'Change' button to reset the selection.
    """
    _ROLE_META = {
        "assessee":    ("🏢", "Assessee",    "#1565C0", "#E3F2FD"),
        "third_party": ("🤝", "Third Party",  "#6A1B9A", "#F3E5F5"),
        "revenue":     ("🏛️", "Revenue",      "#E65100", "#FFF3E0"),
    }
    role = st.session_state.get("client_role", "assessee")
    icon, label, color, bg = _ROLE_META.get(role, _ROLE_META["assessee"])

    col_badge, col_change = st.columns([6, 1])
    with col_badge:
        st.markdown(
            f"<div style='background:{bg};border-left:4px solid {color};"
            f"border-radius:6px;padding:8px 14px;display:inline-block;"
            f"font-size:14px;color:{color};'>"
            f"{icon} <b>Client:</b> {label}</div>",
            unsafe_allow_html=True,
        )
    with col_change:
        if st.button("✏️ Change", key="change_role", help="Change client identification"):
            st.session_state.pop("client_role", None)
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)


# ── Section Analysis Panel ────────────────────────────────────────────────────

def _show_section_analysis(case_id: int, sections: list, force_expand: bool = True):
    for section in sections:
        info  = ITAT_SECTIONS.get(section, {})
        label = info.get("name", "Section not in standard library")
        with st.expander(f"§ {section} — {label}", expanded=force_expand):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Available Defences:**")
                for d in info.get("key_defences", ["Consult AI analysis below"]):
                    st.markdown(f"✓ {d}")
            with c2:
                if info.get("penalty_section"):
                    st.error(f"Linked Penalty: § {info['penalty_section']}")
                st.warning(f"Max Exposure: {info.get('max_penalty', 'N/A')}")

            if st.button(f"🤖 Run AI Analysis for § {section}",
                         key=f"ai_{case_id}_{section}"):
                with st.spinner(f"Analysing § {section} with verified precedents..."):
                    # ── RAG-grounded analysis ─────────────────────────────
                    from ai.rag import inject_into_prompt, get_citations_for_sections
                    from ai.rag import call_with_routing

                    db_cits = get_citations_for_sections([section], limit=6)
                    cit_count = len(db_cits)

                    base_question = (
                        f"Analyse section {section} ({label}) for a tax assessee at ITAT.\n\n"
                        "Provide:\n"
                        "1. Legal elements the AO must prove\n"
                        "2. Top 5 defences with statutory/case law basis\n"
                        "3. Key ITAT/HC/SC precedents in assessee's favour "
                        "(ONLY cite cases from the VERIFIED CITATIONS block — no others)\n"
                        "4. Critical documents required\n"
                        "5. Risk level: High / Medium / Low"
                    )

                    grounded_prompt = inject_into_prompt(
                        base_question,
                        sections=[section],
                        limit=6,
                    )

                    result = call_with_routing(
                        task_type="section_analysis",
                        system_prompt=SECTION_ANALYSIS_SYSTEM,
                        user_message=grounded_prompt,
                        temperature=0.15,
                        max_tokens=2048,
                    )

                    if cit_count:
                        st.caption(f"📚 Grounded with {cit_count} verified precedents from local DB")
                    st.markdown(result)
