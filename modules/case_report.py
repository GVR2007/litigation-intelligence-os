"""
Case Intelligence Report — Streamlit renderer.

Displays the structured report from ai/case_analyser.py:
  📋 Case Summary & Intelligence
  📜 CBDT Circulars & Notifications
  ⚖️  Supreme Court Judgments
  🏛️  High Court Judgments
  📁  ITAT Orders
  📜  Finance Act History
  💡  Advance Rulings

Usage:
    from modules.case_report import render_report
    render_report(report_dict)            # full display
    render_report_compact(report_dict)    # inline compact mode
"""

import streamlit as st


# ── colour / icon constants ────────────────────────────────────────────────────
_COURT_COLOR = {
    "SC":    "#7B1FA2",
    "HC":    "#1565C0",
    "ITAT":  "#2E7D32",
    "OTHER": "#F57F17",
}
_SOURCE_LABEL = {
    "indian_kanoon":     "🔵 Indian Kanoon",
    "itatonline":        "⚖️ itatonline.org",
    "taxguru_itat":      "📋 TaxGuru ITAT",
    "taxguru_hc":        "🏛️ TaxGuru HC",
    "taxguru_sc":        "🏛️ TaxGuru SC",
    "taxscan":           "📰 Taxscan.in",
    "caclubindia":       "🎯 CAclubindia",
    "cbdt_circular":     "📜 CBDT Circular",
    "cbdt_notification": "📣 CBDT Notification",
    "local_db":          "💾 Local DB",
}


def _src_badge(source: str) -> str:
    return _SOURCE_LABEL.get(source, f"📄 {source}")


def _case_card(item: dict, idx: int):
    """Render a single case/circular as a compact card."""
    title   = item.get("title", "Untitled")[:110]
    url     = item.get("url", "")
    year    = item.get("year") or ""
    court   = item.get("court", "")[:60]
    headline = item.get("headline", "")[:280]
    source  = item.get("source", "")
    section = item.get("section", "")
    ct      = item.get("court_type", "OTHER")
    color   = _COURT_COLOR.get(ct, "#555")

    year_str = f" ({year})" if year else ""
    title_md = f"[{title}{year_str}]({url})" if url else f"{title}{year_str}"
    src_badge = _src_badge(source)
    sec_badge = f" · §{section}" if section else ""

    st.markdown(
        f"""<div style="border-left:4px solid {color};
                        padding:10px 14px;margin:6px 0;
                        background:#1a1a1a;border-radius:4px;">
            <div style="font-size:0.95em;font-weight:600;color:#eee;">
                {idx}. {title_md if not url else ''}</div>
            {'<a href="' + url + '" target="_blank" style="color:#90CAF9;font-weight:600;">' + title + year_str + '</a>' if url else ''}
            <div style="font-size:0.78em;color:#aaa;margin-top:4px;">
                {src_badge}{sec_badge} {'· ' + court if court else ''}
            </div>
            {'<div style="font-size:0.82em;color:#ccc;margin-top:5px;font-style:italic;">' + headline + '</div>' if headline else ''}
        </div>""",
        unsafe_allow_html=True,
    )


def _section_header(icon: str, title: str, count: int, color: str = "#90CAF9"):
    """Render a group header with count badge."""
    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:10px;
                        margin:18px 0 8px 0;padding:10px 14px;
                        background:#111;border-radius:8px;
                        border:1px solid #333;">
            <span style="font-size:1.3em;">{icon}</span>
            <span style="font-size:1.05em;font-weight:700;color:{color};">{title}</span>
            <span style="margin-left:auto;background:{color};color:#000;
                         padding:2px 10px;border-radius:12px;
                         font-size:0.8em;font-weight:700;">{count} results</span>
        </div>""",
        unsafe_allow_html=True,
    )


def render_report(report: dict):
    """Full-width report display."""
    if not report:
        st.warning("No report available. Upload a PDF to generate the case intelligence report.")
        return

    intel    = report.get("intelligence", {})
    sc       = report.get("sc", [])
    hc       = report.get("hc", [])
    itat     = report.get("itat", [])
    cbdt     = report.get("cbdt", [])
    arlings  = report.get("advance_rulings", [])
    fin_act  = report.get("finance_act", "")
    queries  = report.get("queries_used", [])
    total    = report.get("total_found", 0)
    sections = report.get("sections", [])

    # ── Top summary banner ────────────────────────────────────────────────────
    meta = report.get("metadata", {})
    ay   = meta.get("assessment_year", "—")
    demand = meta.get("demand_amount", 0) or 0
    secs_str = "  ·  ".join(f"§{s}" for s in sections)

    st.markdown(
        f"""<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);
                        border:1px solid #0f3460;border-radius:12px;
                        padding:20px 24px;margin-bottom:16px;">
            <div style="font-size:1.3em;font-weight:700;color:#E3F2FD;margin-bottom:8px;">
                📊 Case Intelligence Report
            </div>
            <div style="font-size:0.9em;color:#90CAF9;margin-bottom:12px;">
                AY: <b>{ay}</b> &nbsp;|&nbsp; Demand: <b>₹{demand:,.0f}</b> &nbsp;|&nbsp;
                Sections: <b>{secs_str or '—'}</b> &nbsp;|&nbsp;
                <b>{total}</b> relevant items found
            </div>
            <div style="font-size:0.95em;color:#CFD8DC;line-height:1.6;">
                {intel.get('case_summary', '')}
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Key Intelligence Tiles ─────────────────────────────────────────────────
    issues      = intel.get("key_issues", [])
    ao_args     = intel.get("ao_contentions", [])
    facts       = intel.get("key_facts", [])
    nature      = intel.get("nature_of_addition", "")
    ass_type    = intel.get("assessee_type", "")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**🎯 Key Issues**")
        for iss in issues[:4]:
            st.markdown(f"• {iss}")
    with c2:
        st.markdown("**⚔️ AO's Contentions**")
        for arg in ao_args[:4] or ["Not extracted — review PDF"]:
            st.markdown(f"• {arg}")
    with c3:
        st.markdown("**📌 Key Facts**")
        for f in facts[:4] or ["Not extracted from PDF"]:
            st.markdown(f"• {f}")

    if nature or ass_type:
        cols = st.columns(2)
        if nature:
            cols[0].info(f"**Nature of Addition:** {nature}")
        if ass_type:
            cols[1].info(f"**Assessee Type:** {ass_type.title()}")

    st.divider()

    # ── Result Groups ──────────────────────────────────────────────────────────

    # CBDT Circulars & Notifications
    _section_header("📜", "CBDT Circulars & Notifications", len(cbdt), "#FFD54F")
    if cbdt:
        with st.expander(f"Show {len(cbdt)} CBDT circular(s) — threshold limits, reasonable cause, exemptions",
                         expanded=len(cbdt) <= 5):
            for i, item in enumerate(cbdt, 1):
                _case_card(item, i)
    else:
        st.caption("  No CBDT circulars found for these sections in local database. Run Web Sources harvest to populate.")

    # Supreme Court
    _section_header("⚖️", "Supreme Court Judgments", len(sc), "#CE93D8")
    if sc:
        with st.expander(f"Show {len(sc)} SC judgment(s) — highest authority, binding on all courts",
                         expanded=len(sc) <= 4):
            for i, item in enumerate(sc, 1):
                _case_card(item, i)
    else:
        st.caption("  No SC judgments found. Adjust search queries or expand IK harvest.")

    # High Courts
    _section_header("🏛️", "High Court Judgments", len(hc), "#90CAF9")
    if hc:
        with st.expander(f"Show {len(hc)} HC judgment(s) — binding in respective jurisdictions",
                         expanded=len(hc) <= 6):
            for i, item in enumerate(hc, 1):
                _case_card(item, i)
    else:
        st.caption("  No HC judgments found for these queries.")

    # ITAT Orders
    _section_header("📁", "ITAT Orders", len(itat), "#A5D6A7")
    if itat:
        with st.expander(f"Show {len(itat)} ITAT order(s) — persuasive, directly on point",
                         expanded=len(itat) <= 8):
            for i, item in enumerate(itat, 1):
                _case_card(item, i)
    else:
        st.caption("  No ITAT orders found. Try running a web harvest (CAclubindia / itatonline).")

    # Finance Act History
    _section_header("📜", "Finance Act Legislative History", len(sections), "#FFCC80")
    with st.expander("Show Finance Act history for violated sections", expanded=True):
        st.markdown(fin_act or "_No history available._")

    # Advance Rulings
    if arlings:
        _section_header("💡", "Advance Rulings (AAR)", len(arlings), "#80DEEA")
        with st.expander(f"Show {len(arlings)} advance ruling(s)"):
            for i, item in enumerate(arlings, 1):
                _case_card(item, i)

    # ── Citation Verification Panel ───────────────────────────────────────────
    st.divider()
    _render_citation_verifier(intel, sections)

    # Queries used (debug / transparency)
    with st.expander("🔎 Search queries used for this report", expanded=False):
        st.caption("These queries were generated from your case facts and used to search Indian Kanoon + local DB:")
        for i, q in enumerate(queries, 1):
            st.markdown(f"`{i}.` {q}")


def _render_citation_verifier(intel: dict, sections: list):
    """
    Citation verification panel — checks every case name in the AI output
    against local DB and IK before CA relies on them for filing.
    """
    with st.expander("🔍 Citation Verification — verify AI output before filing", expanded=False):
        st.caption(
            "SC White Paper guideline: *Lawyers must independently verify every citation "
            "against a primary source before relying on it in any filing.*"
        )

        # Build text to verify from all intelligence fields
        verify_text_parts = []
        if intel.get("case_summary"):
            verify_text_parts.append(intel["case_summary"])
        if intel.get("ao_contentions"):
            verify_text_parts.extend(intel["ao_contentions"])
        if intel.get("key_facts"):
            verify_text_parts.extend(intel["key_facts"])

        verify_text = " ".join(str(p) for p in verify_text_parts)

        if st.button("🔍 Verify All Citations in This Report", type="primary",
                     key="verify_citations_btn"):
            with st.spinner("Checking citations against local DB and Indian Kanoon..."):
                try:
                    from utils.citation_verifier import verify_text_citations
                    report = verify_text_citations(verify_text, sections=sections,
                                                   check_ik=True)
                    st.session_state["citation_verify_report"] = report
                except Exception as e:
                    st.error(f"Verification error: {e}")

        saved = st.session_state.get("citation_verify_report")
        if saved:
            if saved.total == 0:
                st.info("No case citations detected in the AI summary. "
                        "Citations in the results list above link directly to Indian Kanoon — "
                        "click any result to verify.")
            else:
                v = len(saved.verified)
                u = len(saved.unverified)

                if u == 0:
                    st.success(f"✅ All {v} citation(s) verified against local DB / Indian Kanoon.")
                else:
                    st.warning(f"⚠️ {u} citation(s) could not be verified — check manually before filing.")

                st.markdown(saved.summary())


def render_report_compact(report: dict):
    """
    Compact inline version for the Phase 1 sidebar / quick view.
    Shows counts only with expand-to-see-all.
    """
    if not report:
        return

    sc    = report.get("sc", [])
    hc    = report.get("hc", [])
    itat  = report.get("itat", [])
    cbdt  = report.get("cbdt", [])
    total = report.get("total_found", 0)

    st.markdown(f"**🔍 {total} relevant cases found**")

    rows = [
        ("📜 CBDT Circulars",     cbdt,  "#FFD54F"),
        ("⚖️ Supreme Court",       sc,   "#CE93D8"),
        ("🏛️ High Courts",          hc,   "#90CAF9"),
        ("📁 ITAT Orders",         itat,  "#A5D6A7"),
    ]
    for label, items, color in rows:
        if items:
            st.markdown(
                f'<div style="padding:4px 10px;border-left:3px solid {color};'
                f'margin:3px 0;font-size:0.9em;">'
                f'<b>{label}</b> — {len(items)} result(s)</div>',
                unsafe_allow_html=True,
            )
