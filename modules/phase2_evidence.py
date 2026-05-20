"""Phase 2: Evidence Engine — auto-generates evidence list from live web search + AI."""
import streamlit as st
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections, calculate_overall_win_rate
from ai.claude_client import call_claude
from ai.prompts import EVIDENCE_SYSTEM


def _get_ao_context(case_id: int) -> dict:
    """
    Return AO allegation data for a case, with DB fallback if session state is empty.

    Priority:
      1. session_state — already in memory (same session as Phase 1)
      2. DB            — persisted at registration; survives browser refresh

    Always returns a dict with keys: ao_allegations, ao_rejection_reason, ao_additions.
    Also repopulates session_state from DB when loaded that way (prevents repeat DB reads).
    """
    allegations = st.session_state.get(f"ao_allegations_{case_id}", "")
    rejection   = st.session_state.get(f"ao_rejection_reason_{case_id}", "")
    additions   = st.session_state.get(f"ao_additions_{case_id}", None)

    # If any field is missing from session state, load all from DB
    if not allegations and not rejection and additions is None:
        ctx = queries.get_ao_context(case_id)
        # Repopulate session state so subsequent reads don't hit the DB again
        st.session_state[f"ao_allegations_{case_id}"]      = ctx["ao_allegations"]
        st.session_state[f"ao_rejection_reason_{case_id}"] = ctx["ao_rejection_reason"]
        st.session_state[f"ao_additions_{case_id}"]        = ctx["ao_additions"]
        st.session_state[f"doc_heading_{case_id}"]         = ctx.get("doc_heading", "")
        st.session_state[f"notice_requirements_{case_id}"] = ctx.get("notice_requirements", [])
        return ctx

    return {
        "ao_allegations":      allegations,
        "ao_rejection_reason": rejection,
        "ao_additions":        additions if additions is not None else [],
        "doc_heading":         st.session_state.get(f"doc_heading_{case_id}", ""),
        "notice_requirements": st.session_state.get(f"notice_requirements_{case_id}", []),
    }


def render():
    st.header("Phase 2: Evidence Engine")
    st.caption("Auto-generates your evidence checklist from Indian Kanoon, itatonline, TaxGuru, Taxscan, CBDT + AI.")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case. Please register or load a case in Phase 1.")
        return

    case = queries.get_case(case_id)
    if not case:
        st.error("Case not found.")
        return

    sections = parse_sections(case["sections_violated"])
    if not sections:
        st.error("No sections found in this case. Go back to Phase 1 and register the sections.")
        return

    # Case banner
    st.info(
        f"📁 **{case['case_name']}** | "
        f"Sections: **{', '.join(f'§{s}' for s in sections)}** | "
        f"AY: {case.get('assessment_year') or '—'}"
    )

    # ── Show persistent success banner after auto-build ───────────────────────
    build_key = f"ev_build_done_{case_id}"
    if st.session_state.get(build_key):
        msg = st.session_state.pop(build_key)
        st.success(msg)

    # ── Auto-build on first load ──────────────────────────────────────────────
    existing = queries.get_case_evidence(case_id)
    if not existing:
        _auto_build(case_id, sections, case)
        return

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Evidence Checklist",
        "🎯 AO Allegations",
        "🔄 Backup Plan",
        "🔍 AI Validation",
    ])

    with tab1:
        _render_evidence_list(case_id, sections, case)

    with tab2:
        _render_allegation_tab(case_id, sections, case)

    with tab3:
        _render_backup_plan(case_id, sections)

    with tab4:
        _render_ai_validation(case_id, sections)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-build on first load
# ─────────────────────────────────────────────────────────────────────────────

def _auto_build(case_id: int, sections: list, case: dict):
    """Triggered automatically when no evidence exists for this case."""
    st.markdown("### 🔍 Searching live sources for evidence requirements...")
    st.caption(
        "Querying Indian Kanoon API (full judgments) · itatonline.org · TaxGuru · Taxscan · "
        "CAclubindia · CBDT circulars · Gemini AI analysis"
    )

    log_box   = st.empty()
    log_lines = []

    def log(msg):
        log_lines.append(msg)
        log_box.code("\n".join(log_lines[-25:]), language="bash")

    ao_text = (
        st.session_state.get(f"ao_text_{case_id}")
        or st.session_state.get("pdf_scan_result", {}).get("raw_text", "")
        or ""
    )

    # Load full document context once — session state first, DB fallback on refresh
    ao_ctx = _get_ao_context(case_id)

    # ── Layer 0: seed notice requirements as mandatory items BEFORE RAG ───────
    # These are the exact items the authority wrote in the notice/annexure.
    # They are ground truth — AO directly demanded them. RAG adds on top.
    notice_reqs = ao_ctx.get("notice_requirements", [])
    if notice_reqs:
        log(f"📋 Seeding {len(notice_reqs)} items directly from notice (Layer 0)...")
        for req in notice_reqs:
            queries.add_evidence(
                case_id,
                section       = sections[0] if sections else "",
                document_name = req,
                win_boost     = 50,   # highest priority — AO directly asked for this
                is_mandatory  = True,
                status        = "pending",
                why_it_matters= "AO/authority directly requested this item in the notice.",
                how_to_obtain = "",   # CA knows their client's records
                tribunal_verdict = "requested",
                source        = "notice-requirement",
                notes         = ao_ctx.get("doc_heading", ""),
            )
        log(f"   ✅ Layer 0 complete — {len(notice_reqs)} mandatory items added")

    # Prefer AI-extracted case facts from Phase 1; fall back to assembled parts
    case_facts = st.session_state.get(f"case_facts_{case_id}", "").strip()

    if not case_facts:
        facts_parts = []
        if case.get("case_name"):
            facts_parts.append(f"Client/case name: {case['case_name']}")
        if case.get("assessment_year"):
            facts_parts.append(f"Assessment year: {case['assessment_year']}")
        if case.get("demand_amount"):
            facts_parts.append(f"Demand amount: ₹{case['demand_amount']:,.0f}")
        if case.get("nature_of_addition"):
            facts_parts.append(f"Nature of addition: {case['nature_of_addition']}")
        if case.get("assessee_type"):
            facts_parts.append(f"Assessee type: {case['assessee_type']}")
        if case.get("remarks"):
            facts_parts.append(f"Additional facts: {case['remarks']}")
        facts_parts.append(f"Sections under dispute: {', '.join(f'§{s}' for s in sections)}")
        case_facts = ". ".join(facts_parts)

    from ai.evidence_builder import build_evidence_list

    items = build_evidence_list(
        sections            = sections,
        ao_order_text       = ao_text,
        case_facts          = case_facts,
        progress_cb         = log,
        case_id             = case_id,
        case_name           = case.get("case_name", ""),
        assessment_year     = case.get("assessment_year", ""),
        demand_amount       = float(case.get("demand_amount") or 0),
        ao_allegations      = ao_ctx["ao_allegations"],
        ao_rejection_reason = ao_ctx["ao_rejection_reason"],
        ao_additions        = ao_ctx["ao_additions"],
    )

    log_box.empty()

    if items:
        accepted = sum(1 for i in items if i.get("tribunal_verdict") == "accepted")
        rejected = sum(1 for i in items if i.get("tribunal_verdict") == "rejected")

        for item in items:
            accepted_in = ", ".join(item.get("accepted_in", []))
            rejected_in = ", ".join(item.get("rejected_in", []))
            queries.add_evidence(
                case_id,
                item["section"],
                item["document_name"],
                item["win_boost"],
                item["mandatory"],
                "pending",
                item.get("why_it_matters", ""),
                item.get("how_to_obtain", ""),
                tribunal_verdict  = item.get("tribunal_verdict", "accepted"),
                rejection_reason  = item.get("rejection_reason", ""),
                accepted_in       = accepted_in,
                rejected_in       = rejected_in,
                acceptance_count  = item.get("acceptance_count", 1),
                source            = item.get("source", ""),
                notes             = item.get("counter_point", ""),
            )

        st.session_state[f"ev_build_done_{case_id}"] = (
            f"✅ Extracted from live full-text judgments — "
            f"**{accepted} tribunal-accepted** · "
            f"**{rejected} tribunal-rejected** · "
            f"ranked by frequency across {len(sections)} section(s)."
        )
    else:
        st.session_state[f"ev_build_done_{case_id}"] = (
            "⚠️ No documents found in the provided cases. "
            "Try harvesting citations first (📎 Citation DB)."
        )

    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Evidence Checklist
# ─────────────────────────────────────────────────────────────────────────────

def _render_evidence_list(case_id: int, sections: list, case: dict):
    evidence = queries.get_case_evidence(case_id)

    # ── Metrics bar ───────────────────────────────────────────────────────────
    if evidence:
        win_data = calculate_overall_win_rate(evidence)
        prob  = win_data["win_probability"]
        color = "🟢" if prob >= 65 else "🟡" if prob >= 40 else "🔴"

        n_accepted = sum(1 for e in evidence if e.get("tribunal_verdict", "accepted") == "accepted")
        n_rejected = len(evidence) - n_accepted

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Win Probability",     f"{color} {prob}%")
        c2.metric("✅ Tribunal Accepted", n_accepted)
        c3.metric("❌ Tribunal Rejected", n_rejected)
        c4.metric("Available",           win_data["available_count"])
        c5.metric("Pending",             win_data["pending_count"])
        c6.metric("Unavailable",         win_data["unavailable_count"])
        st.progress(prob / 100)
        st.divider()

    # ── Controls ──────────────────────────────────────────────────────────────
    col_rebuild, col_export_pdf, col_export_docx, col_clear = st.columns([3, 1.5, 1.5, 1])
    with col_rebuild:
        if st.button("🔄 Re-search & Rebuild from Live Cases", use_container_width=True):
            queries.clear_case_evidence(case_id)
            st.rerun()
    with col_export_pdf:
        try:
            from utils.export import build_evidence_pdf
            evidence_for_export = queries.get_case_evidence(case_id)
            if evidence_for_export:
                pdf_bytes = build_evidence_pdf(case, evidence_for_export)
                st.download_button(
                    "⬇️ PDF",
                    data=pdf_bytes,
                    file_name=f"{case['case_name'][:25].replace(' ','_')}_evidence.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        except Exception:
            pass
    with col_export_docx:
        try:
            from utils.export import build_paperbook_docx
            evidence_for_export = queries.get_case_evidence(case_id)
            if evidence_for_export:
                pb_bytes = build_paperbook_docx(case, evidence_for_export)
                st.download_button(
                    "⬇️ Paper Book",
                    data=pb_bytes,
                    file_name=f"{case['case_name'][:25].replace(' ','_')}_paperbook.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
        except Exception:
            pass
    with col_clear:
        if st.button("🗑️ Clear", use_container_width=True):
            queries.clear_case_evidence(case_id)
            st.rerun()

    if not evidence:
        st.info("No evidence items yet. Click 'Re-search' above.")
        return

    st.divider()

    # ── Split Layer 0 (notice demands) from Layer 1 (RAG recommendations) ─────
    layer0 = [i for i in evidence
              if (i.get("evidence_source") or i.get("notes", "")).startswith("notice-requirement")
              or i.get("tribunal_verdict") == "requested"]
    layer1 = [i for i in evidence if i not in layer0]

    # ── Layer 0: items the authority directly demanded ─────────────────────────
    if layer0:
        doc_heading = _get_ao_context(case_id).get("doc_heading", "")
        heading_line = f"  •  *{doc_heading}*" if doc_heading else ""
        st.markdown(
            f"### 📋 Authority-Demanded Items{heading_line}",
            unsafe_allow_html=False,
        )
        st.caption(
            "These are the exact items written in the notice/annexure. "
            "You MUST produce every one of them. "
            "Layer 1 below adds supporting documents that strengthen your response."
        )
        collected = sum(1 for i in layer0 if i["status"] == "available")
        st.progress(collected / len(layer0),
                    text=f"{collected} / {len(layer0)} collected")

        for rank, item in enumerate(layer0, 1):
            status_icon = {"available": "✅", "pending": "⏳",
                           "unavailable": "❌"}.get(item["status"], "⏳")
            col_check, col_label, col_status = st.columns([0.5, 8, 1.5])
            with col_check:
                st.markdown(f"**{rank}.**")
            with col_label:
                st.markdown(
                    f"<span style='background:#1a3a5c;color:#7ecfff;"
                    f"padding:2px 8px;border-radius:4px;font-size:11px;"
                    f"font-weight:600;'>📋 AO DEMANDED</span>  "
                    f"**{item['document_name']}**",
                    unsafe_allow_html=True,
                )
                if item.get("notes") and item["notes"] != item.get("evidence_source", ""):
                    st.caption(item["notes"])
            with col_status:
                new_status = st.selectbox(
                    "status",
                    ["pending", "available", "unavailable"],
                    index=["pending", "available", "unavailable"].index(
                        item.get("status", "pending")),
                    key=f"layer0_status_{item['id']}",
                    label_visibility="collapsed",
                )
                if new_status != item.get("status"):
                    queries.update_evidence_status(item["id"], new_status)
                    st.rerun()

        st.divider()

    # ── Layer 1: RAG-recommended documents grouped by section ─────────────────
    if layer1:
        st.markdown("### ⚖️ RAG-Recommended Supporting Documents")
        st.caption(
            "Found by searching real ITAT / HC / SC judgments. "
            "These strengthen your response to each notice item."
        )

    by_section: dict[str, list] = {}
    for item in layer1:
        by_section.setdefault(item["section"], []).append(item)

    for sec, items in by_section.items():
        accepted    = [i for i in items if i.get("tribunal_verdict", "accepted") == "accepted"]
        rejected    = [i for i in items if i.get("tribunal_verdict") == "rejected"]
        avail_count = sum(1 for i in items if i["status"] == "available")

        st.subheader(f"§ {sec}  —  {avail_count}/{len(items)} collected")

        # ── Tribunal-Accepted (ranked by acceptance_count) ────────────────────
        if accepted:
            accepted.sort(key=lambda x: (-x.get("is_mandatory", 0), -x.get("acceptance_count", 1)))
            st.markdown(
                "#### ✅ Tribunal-Accepted Documents  "
                "<small style='color:#555;font-weight:normal;'>"
                "ranked by frequency across cases</small>",
                unsafe_allow_html=True,
            )
            _render_accepted_items(accepted)

        # ── Tribunal-Rejected (understand why) ────────────────────────────────
        if rejected:
            st.markdown("#### ❌ Documents Tribunal Rejected — Understand Why")
            st.caption(
                "These documents appeared in cases but were found insufficient. "
                "Collect them anyway but ensure the gaps the tribunal flagged are addressed."
            )
            _render_rejected_items(rejected)

        st.divider()


def _render_accepted_items(items: list):
    """Render tribunal-accepted documents with rank badge and case references."""
    for rank, item in enumerate(items, 1):
        mandatory_tag = "🔴 MANDATORY" if item.get("is_mandatory") else "🔵 Supporting"
        count = item.get("acceptance_count", 1)
        freq_badge = (
            "🥇 High frequency" if count >= 4
            else "🥈 Moderate"  if count >= 2
            else "🥉 Cited once"
        )

        with st.container():
            col_rank, col_doc, col_freq, col_action = st.columns([0.5, 5, 2, 1.5])

            with col_rank:
                st.markdown(
                    f"<div style='font-size:20px;font-weight:bold;color:#1565C0;"
                    f"text-align:center;padding-top:6px;'>#{rank}</div>",
                    unsafe_allow_html=True,
                )

            with col_doc:
                st.markdown(f"**{item['document_name']}**  `{mandatory_tag}`")
                if item.get("why_it_matters"):
                    st.caption(f"⚖️ {item['why_it_matters']}")
                if item.get("how_to_obtain"):
                    st.caption(f"📍 {item['how_to_obtain']}")
                if item.get("accepted_in"):
                    st.caption(f"📜 Accepted in: *{item['accepted_in'][:150]}*")

            with col_freq:
                st.markdown(
                    f"<div style='text-align:center;padding-top:4px;'>"
                    f"{freq_badge}<br/>"
                    f"<small>accepted in {count} case(s)</small></div>",
                    unsafe_allow_html=True,
                )

            with col_action:
                status_opts = ["pending", "available", "unavailable"]
                cur_status  = item.get("status", "pending")
                try:
                    idx = status_opts.index(cur_status)
                except ValueError:
                    idx = 0
                new_status = st.selectbox(
                    "Status",
                    status_opts,
                    index=idx,
                    key=f"ev_{item['id']}",
                    label_visibility="collapsed",
                )
                if new_status != cur_status:
                    queries.update_evidence_status(item["id"], new_status)
                    st.rerun()

                # ── Post-hearing feedback ─────────────────────────────────
                cur_outcome = item.get("user_outcome") or ""
                outcome_opts = ["", "accepted", "partially_accepted", "rejected"]
                outcome_labels = ["Post-hearing outcome…", "✅ Accepted", "🔶 Partial", "❌ Rejected"]
                try:
                    oidx = outcome_opts.index(cur_outcome)
                except ValueError:
                    oidx = 0
                new_outcome = st.selectbox(
                    "ITAT outcome",
                    outcome_opts,
                    index=oidx,
                    format_func=lambda x: outcome_labels[outcome_opts.index(x)],
                    key=f"out_{item['id']}",
                    label_visibility="collapsed",
                )
                if new_outcome and new_outcome != cur_outcome:
                    queries.update_evidence_outcome(item["id"], new_outcome)
                    st.rerun()

        st.markdown("---")


def _render_rejected_items(items: list):
    """Render tribunal-rejected documents with exact rejection reason."""
    for item in items:
        rejection  = item.get("rejection_reason") or "Reason not specified in extracted cases."
        rejected_in = item.get("rejected_in") or ""

        with st.expander(
            f"⚠️ {item['document_name']} — rejected by tribunal",
            expanded=False,
        ):
            st.error(f"**Rejection reason:** {rejection}")
            if rejected_in:
                st.caption(f"📜 Rejected in: *{rejected_in[:150]}*")
            if item.get("why_it_matters"):
                st.caption(f"What it was meant to prove: {item['why_it_matters']}")
            st.info(
                "**What to do:** Collect this document anyway but address the tribunal's "
                "objection — e.g., if rejected for being post-dated, ensure yours is "
                "contemporaneous. Use AI Backup Plan tab for stronger alternatives."
            )
            status_opts = ["pending", "available", "unavailable"]
            cur_status  = item.get("status", "pending")
            try:
                idx = status_opts.index(cur_status)
            except ValueError:
                idx = 0
            new_status = st.selectbox(
                "Collect status",
                status_opts,
                index=idx,
                key=f"ev_{item['id']}",
            )
            if new_status != cur_status:
                queries.update_evidence_status(item["id"], new_status)
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — Backup Plan
# ─────────────────────────────────────────────────────────────────────────────

def _render_allegation_tab(case_id: int, sections: list, case: dict):
    """
    Tab 2 — AO Allegations.
    Shows each AO objection and the specific documents that counter it,
    grouped by allegation rather than section.
    """
    st.subheader("AO Allegation → Counter-Evidence Map")
    st.caption(
        "Each AO allegation from the assessment order is mapped to documents "
        "that directly demolish that specific objection — not just §-level lists."
    )

    # Load from session state; fall back to DB if session was lost after refresh
    _ctx                 = _get_ao_context(case_id)
    ao_allegations       = _ctx["ao_allegations"]
    ao_rejection_reason  = _ctx["ao_rejection_reason"]
    ao_additions         = _ctx["ao_additions"]

    # ── Show what was extracted ───────────────────────────────────────────────
    has_data = ao_allegations or ao_additions
    if not has_data:
        st.info(
            "No AO allegation data found for this case.\n\n"
            "**To enable this tab:** upload the AO order PDF in Phase 1 *before* registering "
            "the case — the system will auto-extract allegations from the order text."
        )
        return

    if ao_allegations:
        with st.expander("📋 AO Allegations (raw extracted text)", expanded=False):
            st.warning(ao_allegations)
            if ao_rejection_reason:
                st.error(f"**Why AO rejected assessee's explanation:** {ao_rejection_reason}")

    # ── Per-section allegation blocks ─────────────────────────────────────────
    if ao_additions:
        st.markdown("### Additions Made by AO")
        for i, add in enumerate(ao_additions):
            sec    = add.get("section", "?")
            amount = add.get("amount", 0)
            desc   = add.get("description", "")
            amt_str = f"₹{amount:,.0f}" if amount else "Amount unclear"
            st.markdown(
                f"**§{sec}** — {amt_str}  \n"
                f"<small style='color:#c0392b;'>{desc[:200]}</small>",
                unsafe_allow_html=True,
            )
        st.divider()

    # ── Allegation-targeted evidence from DB ──────────────────────────────────
    evidence     = queries.get_case_evidence(case_id)
    targeted     = [e for e in evidence if e.get("evidence_source") == "allegation-targeted"
                    or e.get("notes", "").startswith("counter:")]

    # Fallback: filter by source stored in notes field
    # (add_evidence stores source in notes if evidence_source col not present)
    if not targeted:
        targeted = [e for e in evidence
                    if "allegation-targeted" in (e.get("notes") or "")]

    if not targeted:
        st.info(
            "No allegation-targeted documents yet. "
            "Click **Re-build Evidence** below to generate them for this case."
        )
        _render_rebuild_button(case_id, sections, case)
        return

    # Group by section, then by counter_allegation text
    by_section: dict = {}
    for item in targeted:
        by_section.setdefault(item["section"], []).append(item)

    for sec, items in by_section.items():
        st.markdown(f"### §{sec} — Allegation-Targeted Documents")

        for rank, item in enumerate(items, 1):
            counter_point = item.get("notes") or ""
            mandatory_tag = "🔴 MANDATORY" if item.get("is_mandatory") else "🔵 Targeted"

            with st.container():
                c1, c2, c3 = st.columns([0.5, 6, 2])

                with c1:
                    st.markdown(
                        f"<div style='font-size:18px;font-weight:bold;color:#B71C1C;"
                        f"text-align:center;padding-top:6px;'>#{rank}</div>",
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.markdown(f"**{item['document_name']}**  `{mandatory_tag}`")
                    if item.get("why_it_matters"):
                        st.caption(f"⚖️ {item['why_it_matters']}")
                    if item.get("how_to_obtain"):
                        st.caption(f"📍 {item['how_to_obtain']}")
                    if counter_point and counter_point != item.get("why_it_matters"):
                        st.caption(f"🎯 Counters: _{counter_point[:180]}_")
                with c3:
                    status_opts = ["pending", "available", "unavailable"]
                    cur_status  = item.get("status", "pending")
                    try:
                        idx = status_opts.index(cur_status)
                    except ValueError:
                        idx = 0
                    new_status = st.selectbox(
                        "Status",
                        status_opts,
                        index=idx,
                        key=f"alleg_ev_{item['id']}",
                        label_visibility="collapsed",
                    )
                    if new_status != cur_status:
                        queries.update_evidence_status(item["id"], new_status)
                        st.rerun()

            st.markdown("---")

    _render_rebuild_button(case_id, sections, case)


def _render_rebuild_button(case_id: int, sections: list, case: dict):
    st.divider()
    if st.button("🔄 Re-build allegation evidence", key=f"rebuild_alleg_{case_id}"):
        ao_text   = st.session_state.get(f"ao_text_{case_id}", "")
        facts     = st.session_state.get(f"case_facts_{case_id}", "")
        # DB fallback — works even after browser refresh
        _rctx     = _get_ao_context(case_id)
        alleg     = _rctx["ao_allegations"]
        reject    = _rctx["ao_rejection_reason"]
        adds      = _rctx["ao_additions"]

        if not alleg and not adds:
            st.error("No allegation data found for this case. "
                     "Upload the AO order PDF in Phase 1 and re-register to enable this.")
            return

        with st.spinner("Generating allegation-targeted documents..."):
            from ai.evidence_builder import _build_allegation_targeted_items
            targeted = _build_allegation_targeted_items(
                sections, alleg, reject, adds, facts, lambda m: None
            )

        if targeted:
            for item in targeted:
                queries.add_evidence(
                    case_id,
                    item["section"],
                    item["document_name"],
                    item["win_boost"],
                    item["mandatory"],
                    item["tribunal_verdict"],
                    item["why_it_matters"],
                    item["how_to_obtain"],
                    source=item["source"],
                    rejection_reason=item.get("rejection_reason", ""),
                    accepted_in="",
                    rejected_in="",
                    acceptance_count=item.get("acceptance_count", 1),
                    notes=item.get("counter_point", ""),
                )
            st.success(f"✅ {len(targeted)} allegation-targeted document(s) added.")
            st.rerun()
        else:
            st.warning("AI returned no targeted documents — check allegation data.")


def _render_backup_plan(case_id: int, sections: list):
    st.subheader("Backup Plan — Substitute Documents")
    st.caption("For every unavailable document, AI finds ITAT-accepted substitutes.")

    evidence    = queries.get_case_evidence(case_id)
    unavailable = [e for e in evidence if e["status"] == "unavailable"]

    if not unavailable:
        st.success("No documents marked as Unavailable yet. Mark items in the Evidence Checklist tab.")
        return

    for item in unavailable:
        with st.expander(f"❌ {item['document_name']} (§ {item['section']})", expanded=True):
            if st.button(f"🤖 Find Substitutes", key=f"sub_{item['id']}"):
                with st.spinner("Searching ITAT precedents for accepted substitutes..."):
                    prompt = (
                        f'The document "{item["document_name"]}" is unavailable for '
                        f'§ {item["section"]}.\n\n'
                        "List 5 substitute documents that ITAT has accepted as replacement. "
                        "For each:\n"
                        "1. Substitute document name\n"
                        "2. How to obtain it (practical steps)\n"
                        "3. ITAT cases where this substitute was accepted\n"
                        "4. Any risk or caveat\n\n"
                        "Focus on practical, obtainable alternatives."
                    )
                    result = call_claude(EVIDENCE_SYSTEM, prompt)
                    st.markdown(result)

    st.divider()
    st.subheader("Recovery Pattern Analysis")
    if st.button("📊 Analyse Recovery Patterns from ITAT Case Law", use_container_width=True):
        with st.spinner("Analysing..."):
            prompt = (
                f"For sections {', '.join(sections)}, analyse ITAT case law on document recovery:\n\n"
                "1. Most common document failures at ITAT\n"
                "2. Substitutes that consistently worked\n"
                "3. Win rate when primary documents absent but substitutes provided\n"
                "4. Which ITAT benches are most flexible\n"
                "5. Absolute minimum documentation to avoid dismissal\n\n"
                "Cite specific cases for each finding."
            )
            result = call_claude(EVIDENCE_SYSTEM, prompt)
            st.markdown(result)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 — AI Validation
# ─────────────────────────────────────────────────────────────────────────────

def _render_ai_validation(case_id: int, sections: list):
    st.subheader("AI Document Validation")
    st.caption("Upload documents — AI reads the full content and checks for defects, date issues, missing fields, and phrasing risks.")

    uploaded_docs = st.file_uploader(
        "Upload Documents for Validation",
        type=["pdf", "jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )

    if uploaded_docs:
        for doc in uploaded_docs:
            st.divider()
            st.markdown(f"**{doc.name}**")
            col1, col2 = st.columns(2)
            with col1:
                doc_type = st.selectbox(
                    "Document Type",
                    ["Cash Book", "Bank Statement", "Affidavit", "Confirmation Letter",
                     "ITR Copy", "Ledger", "Assessment Order", "PAN Card", "Other"],
                    key=f"dtype_{doc.name}",
                )
            with col2:
                section_for_doc = st.selectbox(
                    "Related Section",
                    sections,
                    key=f"dsec_{doc.name}",
                )

            if st.button(f"🔍 Validate {doc.name}", key=f"val_{doc.name}"):
                with st.spinner("Extracting text and running AI validation..."):
                    # Extract document text
                    doc_content = ""
                    if doc.name.lower().endswith(".pdf"):
                        try:
                            from utils.pdf_parser import parse_assessment_order
                            import tempfile, pathlib
                            raw_bytes = doc.read()
                            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                                tmp.write(raw_bytes)
                                tmp_path = tmp.name
                            parsed = parse_assessment_order(tmp_path)
                            doc_content = parsed.get("raw_text", "") or ""
                            pathlib.Path(tmp_path).unlink(missing_ok=True)
                        except Exception as e:
                            doc_content = f"[PDF extraction error: {e}]"
                    else:
                        doc_content = "[Image — visual content not extracted; reviewing based on document type only]"

                    doc_excerpt = doc_content[:3000] if doc_content else "No text extracted."

                    prompt = (
                        f"Validate a {doc_type} for § {section_for_doc} at ITAT.\n\n"
                        f"DOCUMENT CONTENT (extracted text):\n{doc_excerpt}\n\n"
                        "Check:\n"
                        "1. Date consistency — contemporaneous with transaction?\n"
                        "2. Signature completeness and proper attestation\n"
                        "3. Correct phrasing — no incriminating admissions\n"
                        "4. Amount accuracy and consistency with other documents\n"
                        "5. Missing mandatory fields for this document type\n"
                        "6. Notarisation requirements\n\n"
                        "Output:\n"
                        "🔴 RED FLAGS — issues that will hurt the case\n"
                        "🟡 YELLOW FLAGS — minor risks\n"
                        "🟢 STRONG POINTS — what helps the case\n"
                        "📊 Impact: estimated win probability change (+/- %)\n"
                        "🔧 Fixes: specific corrective actions"
                    )
                    result = call_claude(EVIDENCE_SYSTEM, prompt)
                    st.markdown(result)

    st.divider()
    if st.button("📋 Generate Section-Specific Validation Checklist", use_container_width=True):
        with st.spinner("Generating checklist..."):
            prompt = (
                f"Generate a practical document validation checklist for § {', '.join(sections)}.\n\n"
                "For each section:\n"
                "1. Red flags ITAT rejects\n"
                "2. Required attestations / certifications\n"
                "3. Common mistakes that reduce credibility\n"
                "4. Exact format requirements\n"
                "5. Notable cases where defects caused loss\n\n"
                "Format as a checklist a CA can use before filing."
            )
            result = call_claude(EVIDENCE_SYSTEM, prompt)
            st.markdown(result)
