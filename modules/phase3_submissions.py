"""
Phase 3: Submission Drafter — AI-powered written submissions for ITAT.

Tabs:
  1. Submission Drafter — full written submissions from evidence + arguments
  2. Paper Book Builder — index of documents to file
  3. Synopsis Generator — 1-page case synopsis for the bench
  4. Knowledge Library   — statute text, CBDT circulars, live search (retained)
"""

from __future__ import annotations
import streamlit as st
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections, format_currency
from utils.rag_context import get_grounded_context
from ai.openrouter_client import call_openrouter as call_gemini


_SUBMISSION_SYSTEM = """You are a senior Indian Income Tax advocate with 25 years of ITAT
experience. You draft written submissions, replies to show cause notices, and ITAT memoranda.
Your submissions are:
- Precise and legally correct
- Structured with numbered grounds
- Citing real ITAT/HC/SC cases
- In formal legal English used in Indian tax tribunals
- Following the standard ITAT submission format"""


def render():
    st.header("Phase 3: Submissions & Drafting")
    st.caption("Written Submissions · Paper Book Index · Synopsis · Knowledge Library")

    case_id = st.session_state.get("active_case_id")
    if not case_id:
        st.warning("No active case loaded. Please register or load a case in Phase 1.")
        return

    case     = queries.get_case(case_id)
    sections = parse_sections(case["sections_violated"])
    evidence = queries.get_case_evidence(case_id)
    args     = queries.get_case_arguments(case_id)

    st.info(
        f"**{case['case_name']}**  |  "
        f"§ {', '.join(sections[:4])}  |  "
        f"AY: {case.get('assessment_year','—')}  |  "
        f"Demand: {format_currency(case.get('demand_amount') or 0)}"
    )

    # ── Ground Coverage Checker — show before tabs so CA sees it first ────────
    _render_coverage_checker(case_id, sections, evidence)

    tab1, tab2, tab3, tab4 = st.tabs([
        "📝 Submission Drafter",
        "📂 Paper Book",
        "📄 Synopsis",
        "📚 Knowledge Library",
    ])

    with tab1:
        _render_submission_drafter(case_id, case, sections, evidence, args)
    with tab2:
        _render_paper_book(case_id, case, evidence)
    with tab3:
        _render_synopsis(case_id, case, sections, evidence, args)
    with tab4:
        _render_knowledge_library(case_id, case, sections)


# ── Ground Coverage Checker ───────────────────────────────────────────────────

# Procedural sections — imported from evidence_builder (single source of truth).
# Coverage checker marks these as N/A (blue) — no evidence required.
try:
    from ai.evidence_builder import PROCEDURAL_SECTIONS as _PROCEDURAL_SECTIONS
except Exception:
    _PROCEDURAL_SECTIONS = {
        "139", "139(1)", "139(4)", "139(5)",
        "142", "142(1)", "143", "143(1)", "143(2)", "143(3)",
        "144", "144B", "144C",
        "272A", "271F", "271FA",
        "149", "153", "153B",
        "131", "133",
        "246A", "250", "251", "253", "254",
    }


def _render_coverage_checker(case_id: int, sections: list, evidence: list):
    """
    Ground coverage checker — shows per-section status before submissions tab.

    Colours:
      🔵 Blue  = Procedural section — mechanism only, no separate evidence needed
      ✅ Green = Evidence built + at least 1 doc marked available
      🟡 Amber = Evidence built but nothing collected yet
      🔴 Red   = No evidence built at all (CONTESTED section only)

    Only CONTESTED sections with zero evidence block the user.
    Procedural sections (§139, §142, §143(2), §144B, §272A etc.) are always N/A.
    """
    if not sections:
        return

    # Separate contested vs procedural
    contested  = [s for s in sections if s not in _PROCEDURAL_SECTIONS]
    procedural = [s for s in sections if s in _PROCEDURAL_SECTIONS]

    # Build per-section evidence summary
    ev_by_section: dict[str, dict] = {}
    for sec in sections:
        ev_by_section[sec] = {"total": 0, "available": 0, "pending": 0, "unavailable": 0}

    for item in evidence:
        sec = item.get("section", "")
        if sec in ev_by_section:
            ev_by_section[sec]["total"] += 1
            status = item.get("status", "pending")
            if status in ev_by_section[sec]:
                ev_by_section[sec][status] += 1
            # Procedural placeholders from evidence_builder have status="available"
            if item.get("source") == "procedural":
                ev_by_section[sec]["available"] += 1

    # Evaluate ONLY contested sections for red/yellow/green
    gaps    = [s for s in contested if ev_by_section[s]["total"] == 0]
    partial = [s for s in contested if ev_by_section[s]["total"] > 0
               and ev_by_section[s]["available"] == 0]
    covered = [s for s in contested if ev_by_section[s]["available"] > 0]

    # Label — only contested gaps matter
    if gaps:
        label    = (f"⚠️ Ground Coverage — {len(gaps)} contested section(s) "
                    f"have NO evidence built yet")
        expanded = True
    elif partial:
        label    = (f"🟡 Ground Coverage — {len(partial)} section(s) "
                    f"have pending documents")
        expanded = True
    else:
        label    = f"✅ Ground Coverage — all {len(contested)} contested grounds covered"
        expanded = False

    with st.expander(label, expanded=expanded):
        st.caption(
            "🔵 Blue = procedural section (no evidence needed)  · "
            "🔴 Red = no evidence built  · "
            "🟡 Amber = evidence built but not collected  · "
            "✅ Green = ready"
        )

        all_display_sections = sections   # show all in grid
        cols = st.columns(min(len(all_display_sections), 4))

        for i, sec in enumerate(all_display_sections):
            d   = ev_by_section[sec]
            col = cols[i % len(cols)]

            if sec in _PROCEDURAL_SECTIONS:
                color  = "#1565C0"
                icon   = "🔵"
                status = "Procedural"
            elif d["total"] == 0:
                color  = "#C62828"
                icon   = "🔴"
                status = "No evidence"
            elif d["available"] > 0:
                color  = "#2E7D32"
                icon   = "✅"
                status = f"{d['available']}/{d['total']} collected"
            else:
                color  = "#E65100"
                icon   = "🟡"
                status = f"0/{d['total']} collected"

            col.markdown(
                f"<div style='background:{color}22;border:2px solid {color};"
                f"border-radius:8px;padding:10px;text-align:center;margin:4px 0;'>"
                f"<b style='color:{color};font-size:1.1em;'>{icon} §{sec}</b><br/>"
                f"<small style='color:#ccc;'>{status}</small>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # Messages — only contested gaps are errors; partial is just a warning
        if gaps:
            st.warning(
                f"⚠️ **{len(gaps)} contested section(s) have no evidence built:** "
                f"{', '.join(f'§{s}' for s in gaps)}  \n"
                "Go to Phase 2 and run the Evidence Engine for these sections. "
                "You can still draft submissions, but they may lack case citations."
            )
            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("→ Go to Phase 2", key="go_phase2_coverage"):
                    st.session_state["current_phase"] = 2
                    st.rerun()
            with col2:
                st.caption("Or proceed below — submissions will be drafted with available evidence.")
        elif partial:
            st.warning(
                f"🟡 **{len(partial)} section(s) have evidence pending collection:** "
                f"{', '.join(f'§{s}' for s in partial)}  \n"
                "Mark documents as Available in Phase 2 as you collect them."
            )
        else:
            if contested:
                st.success(f"✅ All {len(covered)} contested grounds covered — ready to draft.")
            else:
                st.info("This case has only procedural sections — no evidence building needed.")

        if procedural:
            st.caption(
                f"🔵 Procedural sections (mechanism only — no separate evidence): "
                f"{', '.join(f'§{s}' for s in procedural)}"
            )

    st.divider()


# ── Tab 1: Submission Drafter ─────────────────────────────────────────────────

def _render_submission_drafter(case_id, case, sections, evidence, args):
    st.subheader("📝 Written Submissions Drafter")
    st.caption(
        "Generates court-ready written submissions from your evidence list and legal arguments. "
        "Drafts are saved and editable."
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        submission_type = st.selectbox("Submission Type", [
            "Written Submissions (Full)",
            "Concise Grounds of Appeal",
            "Reply to AO's Assessment Order",
            "Reply to Show Cause Notice (Penalty)",
            "Application for Stay of Demand",
            "Reply to Revision u/s 263",
            "Condonation of Delay Application",
        ])
    with col2:
        style = st.selectbox("Drafting Style", [
            "Formal (ITAT standard)",
            "Concise (bullet points)",
            "Aggressive (attack AO order)",
        ])
    with col3:
        include_citations = st.checkbox("Include case citations", value=True)
        include_circulars = st.checkbox("Include CBDT circulars", value=True)

    # AO Order context
    ao_order_text = st.text_area(
        "AO Assessment Order / Show Cause Notice (paste key paragraphs)",
        value=case.get("ao_order_text", ""),
        height=120,
        placeholder="Paste the AO's key observations, additions made, penalty imposed, etc.",
        key="sub_ao_text",
    )

    # Extra instructions
    extra_instructions = st.text_area(
        "Additional Instructions (optional)",
        height=80,
        placeholder="e.g., 'Emphasize rural background of assessee', 'Focus on 273B reasonable cause', "
                    "'Counter the ITO's finding on XYZ document'",
        key="sub_extra",
    )

    # Evidence summary for prompt
    available_docs   = [e["document_name"] for e in evidence if e.get("status") == "available"]
    unavailable_docs = [e["document_name"] for e in evidence if e.get("status") == "unavailable"]
    all_evidence     = [e["document_name"] for e in evidence[:20]]

    # Arguments for prompt
    top_args = [a["argument_text"][:200] for a in args[:6] if a.get("argument_text")]

    # RAG strategy context from session state
    rag_strategy = st.session_state.get(f"rag_strategy_{case_id}")
    rag_context  = ""
    if rag_strategy:
        rag_args = getattr(rag_strategy, "arguments", [])
        if rag_args:
            rag_context = "\n".join(
                f"- {a.argument} (win rate: {a.win_rate:.0%}, §{a.section})"
                for a in rag_args[:3]
            )
        st.success("✅ Using RAG pipeline arguments for this draft (higher accuracy)")

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        draft_btn = st.button("✍️ Draft Submissions", type="primary",
                               disabled=not sections)

    if draft_btn:
        _draft_submission(
            case_id, case, sections, ao_order_text,
            available_docs, unavailable_docs, all_evidence,
            top_args, rag_context, submission_type, style,
            include_citations, include_circulars, extra_instructions,
        )

    # ── Saved draft display ───────────────────────────────────────────────────
    draft_key = f"submission_draft_{case_id}"

    # Auto-clear stale error drafts so they don't block the UI
    cached = st.session_state.get(draft_key, "")
    if cached and str(cached).startswith("[ERROR]"):
        del st.session_state[draft_key]
        cached = ""

    if cached:
        st.divider()
        st.subheader("📋 Draft Submissions")

        col_redraft, _ = st.columns([1, 4])
        with col_redraft:
            if st.button("🔄 Re-draft", key=f"redraft_{case_id}", use_container_width=True):
                del st.session_state[draft_key]
                st.rerun()

        draft = st.session_state[draft_key]

        # Editable text area
        edited = st.text_area(
            "Review and edit before downloading:",
            value=draft,
            height=600,
            key=f"sub_editor_{case_id}",
        )
        st.session_state[draft_key] = edited

        # ── Export buttons ────────────────────────────────────────────────────
        col_pdf, col_docx, col_copy = st.columns(3)

        with col_docx:
            try:
                from utils.export import build_submission_docx
                docx_bytes = build_submission_docx(case, edited, submission_type)
                fname = f"{case['case_name'][:30].replace(' ','_')}_submissions.docx"
                st.download_button(
                    "⬇️ Download DOCX",
                    data=docx_bytes,
                    file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"DOCX error: {e}")

        with col_pdf:
            try:
                from utils.export import build_full_case_pdf
                pdf_bytes = build_full_case_pdf(case, evidence, args, edited)
                fname_pdf = f"{case['case_name'][:30].replace(' ','_')}_case_file.pdf"
                st.download_button(
                    "⬇️ Download PDF",
                    data=pdf_bytes,
                    file_name=fname_pdf,
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"PDF error: {e}")

        with col_copy:
            st.button("📋 Copy to Clipboard",
                       on_click=lambda: st.write("Use Ctrl+A, Ctrl+C in the text box above"),
                       use_container_width=True)

        # Save to DB as argument
        if st.button("💾 Save Draft to Case File", use_container_width=True):
            queries.add_argument(
                case_id, "submission",
                edited[:2000],
                f"{submission_type} — {datetime.now().strftime('%d %b %Y')}",
                9, "", 3
            )
            st.success("✅ Draft saved to case file!")


def _draft_submission(case_id, case, sections, ao_order_text,
                       available_docs, unavailable_docs, all_evidence,
                       top_args, rag_context, submission_type, style,
                       include_citations, include_circulars, extra_instructions):
    """Call LLM with RAG-grounded citations and stream the submission draft."""
    from datetime import datetime

    # ── RAG grounded context (same pipeline as Phase 2) ───────────────────────
    with st.spinner("🔍 Fetching verified precedents from case database..."):
        ctx = get_grounded_context(case_id, sections)
    if ctx["count"] == 0:
        st.warning("⚠️ No precedents found — run the Evidence Engine in Phase 2 first for best results. Drafting with AI knowledge only.")
    else:
        st.success(f"✅ {ctx['count']} precedents loaded via {ctx['source']}")

    evidence_block = ""
    if available_docs:
        evidence_block += f"\nDocuments AVAILABLE: {', '.join(available_docs[:15])}"
    if unavailable_docs:
        evidence_block += f"\nDocuments NOT AVAILABLE: {', '.join(unavailable_docs[:10])}"

    args_block = ""
    if top_args:
        args_block = "\nLegal arguments identified:\n" + "\n".join(f"- {a}" for a in top_args)

    ao_block = ""
    if ao_order_text and ao_order_text.strip():
        ao_block = f"\nAO's key observations / additions:\n{ao_order_text[:800]}"

    style_instructions = {
        "Formal (ITAT standard)": "Use formal legal English. Number each ground. Use 'it is submitted', 'without prejudice'. Follow ITAT written submission format.",
        "Concise (bullet points)": "Use brief, punchy submissions. Use bullet points. Get to the legal point immediately. No verbose preamble.",
        "Aggressive (attack AO order)": "Directly challenge the AO's reasoning. Point out factual errors. Challenge legal basis. Demand deletion in strong terms.",
    }.get(style, "")

    extra_note = f"\nAdditional instructions: {extra_instructions}" if extra_instructions.strip() else ""

    # ── Build grounded citation block ─────────────────────────────────────────
    verified_block = ""
    if include_citations and ctx["citations_block"]:
        verified_block = f"""
VERIFIED PRECEDENTS (retrieved from case database — cite ONLY these):
{ctx['citations_block']}

⚠️ CITATION RULE: Use ONLY the citations listed above. Do not invent or recall any other citation.
If a citation is not in the list above, write [CITATION NEEDED] instead."""

    cbdt_note = ""
    if include_circulars and ctx["cbdt_block"]:
        cbdt_note = f"\nCBDT CIRCULARS TO REFERENCE:\n{ctx['cbdt_block']}"

    prompt = f"""Draft {submission_type} for this Income Tax case.

CASE DETAILS:
Case: {case.get('case_name','—')}
Client: {case.get('client_name','—')}
Assessment Year: {case.get('assessment_year','—')}
Demand: {format_currency(case.get('demand_amount') or 0)}
Sections: {', '.join(sections)}
{ao_block}
{evidence_block}
{args_block}
{verified_block}
{cbdt_note}

DRAFTING INSTRUCTIONS:
{style_instructions}
{extra_note}

FORMAT:
- Start with: IN THE INCOME TAX APPELLATE TRIBUNAL
- Include: Case title, AY, Assessee details
- GROUNDS OF APPEAL numbered 1, 2, 3...
- Under each ground: facts, legal argument, verified case law from above list, prayer
- End with a PRAYER section seeking specific relief
- Close with: Respectfully submitted

Draft in full — do not abbreviate or summarize. This is the actual filing document."""

    draft_key = f"submission_draft_{case_id}"

    with st.spinner(f"✍️ Drafting {submission_type} with {ctx['count']} verified precedents..."):
        full_text = call_gemini(_SUBMISSION_SYSTEM, prompt,
                                max_tokens=6000, temperature=0.1)

    st.session_state[draft_key] = full_text
    st.success(f"✅ Draft ready — grounded in {ctx['count']} verified precedents")
    st.rerun()


# ── Tab 2: Paper Book Builder ─────────────────────────────────────────────────

def _render_paper_book(case_id, case, evidence):
    st.subheader("📂 Paper Book Index")
    st.caption(
        "The paper book is the set of documents filed before ITAT. "
        "This builds the index that goes on the cover sheet."
    )

    if not evidence:
        st.info("No evidence items yet. Build the evidence list in Phase 2 first.")
        return

    # Group by section
    by_section: dict[str, list] = {}
    for item in evidence:
        sec = item.get("section", "General")
        by_section.setdefault(sec, []).append(item)

    st.markdown(f"**{len(evidence)} documents across {len(by_section)} section(s)**")

    # Interactive status update
    st.markdown("### Mark Document Availability")
    updated = False
    for sec, items in by_section.items():
        st.markdown(f"**§ {sec}**")
        for item in items:
            col1, col2, col3 = st.columns([4, 2, 1])
            with col1:
                mandatory_tag = " 🔴" if (item.get("is_mandatory") or item.get("mandatory")) else ""
                st.markdown(f"{item['document_name'][:60]}{mandatory_tag}")
            with col2:
                new_status = st.selectbox(
                    "Status",
                    ["pending", "available", "unavailable"],
                    index=["pending", "available", "unavailable"].index(
                        item.get("status", "pending")
                    ),
                    key=f"pb_status_{item['id']}",
                    label_visibility="collapsed",
                )
                if new_status != item.get("status", "pending"):
                    queries.update_evidence_status(item["id"], new_status)
                    updated = True
            with col3:
                status_icons = {"available": "✅", "unavailable": "❌", "pending": "⏳"}
                st.write(status_icons.get(new_status, "⏳"))

    if updated:
        st.rerun()

    st.divider()

    # Stats
    available   = sum(1 for e in evidence if e.get("status") == "available")
    unavailable = sum(1 for e in evidence if e.get("status") == "unavailable")
    mandatory   = sum(1 for e in evidence if e.get("is_mandatory") or e.get("mandatory"))
    mandatory_missing = sum(1 for e in evidence
                             if (e.get("is_mandatory") or e.get("mandatory"))
                             and e.get("status") != "available")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Documents", len(evidence))
    col2.metric("✅ Collected", available)
    col3.metric("❌ Missing", unavailable)
    if mandatory_missing > 0:
        col4.metric("🔴 Mandatory Missing", mandatory_missing, delta=f"-{mandatory_missing}", delta_color="inverse")
    else:
        col4.metric("🔴 Mandatory Missing", 0, delta="All collected ✅")

    st.divider()

    # Download paper book index
    try:
        from utils.export import build_paperbook_docx, build_evidence_pdf

        col_a, col_b = st.columns(2)
        with col_a:
            pb_bytes = build_paperbook_docx(case, evidence)
            fname = f"{case['case_name'][:30].replace(' ','_')}_paperbook_index.docx"
            st.download_button(
                "⬇️ Download Paper Book Index (DOCX)",
                data=pb_bytes,
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                type="primary",
            )
        with col_b:
            ev_pdf = build_evidence_pdf(case, evidence)
            fname_pdf = f"{case['case_name'][:30].replace(' ','_')}_evidence_checklist.pdf"
            st.download_button(
                "⬇️ Download Evidence Checklist (PDF)",
                data=ev_pdf,
                file_name=fname_pdf,
                mime="application/pdf",
                use_container_width=True,
            )
    except Exception as e:
        st.error(f"Export error: {e}")


# ── Tab 3: Synopsis Generator ─────────────────────────────────────────────────

def _render_synopsis(case_id, case, sections, evidence, args):
    st.subheader("📄 Case Synopsis Generator")
    st.caption(
        "A 1-page synopsis is submitted to the ITAT bench before the hearing. "
        "It summarises the dispute, key facts, and relief sought."
    )

    col1, col2 = st.columns(2)
    with col1:
        synopsis_length = st.radio("Length", ["1 Page (~500 words)", "2 Pages (~1000 words)"])
    with col2:
        bench_location = st.selectbox("ITAT Bench", [
            "Delhi", "Mumbai", "Kolkata", "Chennai", "Ahmedabad",
            "Bangalore", "Hyderabad", "Pune", "Chandigarh", "Jaipur",
        ])

    available_docs = [e["document_name"] for e in evidence if e.get("status") == "available"]
    top_args       = [a["argument_text"][:150] for a in args[:4] if a.get("argument_text")]

    if st.button("📄 Generate Synopsis", type="primary"):
        word_count = "500" if "1 Page" in synopsis_length else "1000"
        ctx = get_grounded_context(case_id, sections)
        top3 = f"\nKEY VERIFIED CITATIONS:\n{ctx['top3_block']}" if ctx["top3_block"] else ""
        prompt = f"""Draft a {word_count}-word case synopsis for the ITAT {bench_location} bench.

CASE:
Name: {case.get('case_name','—')}
Client: {case.get('client_name','—')}
AY: {case.get('assessment_year','—')}
Demand: {format_currency(case.get('demand_amount') or 0)}
Sections in dispute: {', '.join(sections)}

DOCUMENTS AVAILABLE: {', '.join(available_docs[:12]) or 'See paper book'}
KEY ARGUMENTS: {'; '.join(top_args) or 'As per written submissions'}
{top3}

FORMAT:
1. STATEMENT OF FACTS (3-4 sentences)
2. ADDITIONS MADE BY AO (brief)
3. GROUNDS OF APPEAL (numbered, 1 line each)
4. KEY DOCUMENTS IN SUPPORT
5. RELIEF SOUGHT (specific)
6. BRIEF ON MERITS — cite from the KEY VERIFIED CITATIONS above only

Keep it precise. This will be handed to the bench at the start of the hearing.
Use formal language. No verbose introductions."""

        with st.spinner("Drafting synopsis..."):
            result = call_gemini(_SUBMISSION_SYSTEM, prompt, max_tokens=2000, temperature=0.1)

        st.session_state[f"synopsis_{case_id}"] = result

    syn_key = f"synopsis_{case_id}"
    if st.session_state.get(syn_key, "").startswith("[ERROR]"):
        del st.session_state[syn_key]

    if st.session_state.get(syn_key):
        synopsis = st.session_state[syn_key]
        st.divider()
        edited_synopsis = st.text_area("Review and edit:", value=synopsis,
                                        height=400, key=f"syn_editor_{case_id}")
        st.session_state[syn_key] = edited_synopsis

        col_a, col_b = st.columns(2)
        with col_a:
            try:
                from utils.export import build_submission_docx
                syn_bytes = build_submission_docx(case, edited_synopsis, "Case Synopsis")
                st.download_button(
                    "⬇️ Download Synopsis (DOCX)",
                    data=syn_bytes,
                    file_name=f"{case['case_name'][:25].replace(' ','_')}_synopsis.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True, type="primary",
                )
            except Exception as e:
                st.error(f"Export error: {e}")
        with col_b:
            if st.button("💾 Save to Case File", use_container_width=True):
                queries.add_argument(
                    case_id, "synopsis",
                    edited_synopsis[:1000], "Case Synopsis",
                    8, "", 3
                )
                st.success("Saved!")


# ── Tab 4: Knowledge Library (retained from old Phase 3) ─────────────────────

def _render_knowledge_library(case_id, case, sections):
    st.subheader("📚 Knowledge Library")

    kl_tab1, kl_tab2, kl_tab3 = st.tabs([
        "⚖️ Local Precedents",
        "📋 CBDT Circulars",
        "🔎 Live IK Search",
    ])

    with kl_tab1:
        _render_local_precedents(case_id, sections)
    with kl_tab2:
        _render_cbdt_quick(case_id, sections)
    with kl_tab3:
        _render_ik_search(case_id)


def _render_local_precedents(case_id, sections):
    from ai.rag.fts import FTSIndex

    query = st.text_input(
        "Search precedents",
        placeholder="e.g. 269SS cash loan family penalty deleted genuine transaction",
        key="prec_search_query",
    )
    section_filter = st.selectbox(
        "Section filter",
        ["All"] + sections,
        key="prec_sec_filter",
    )
    top_k = st.slider("Max results", 5, 30, 10, key="prec_topk")

    if st.button("🔍 Search", type="primary", disabled=not query):
        fts = FTSIndex()
        secs = None if section_filter == "All" else [section_filter]
        results = fts.search(query, top_k=top_k, sections=secs)

        if not results:
            st.warning("No results found. Try different keywords.")
        else:
            st.success(f"**{len(results)} cases found**")
            for r in results:
                court = r.get("court_type") or "ITAT"
                year  = r.get("year") or "—"
                score = abs(r.get("bm25_score", 0))
                with st.expander(f"⚖️ {r['citation'][:75]}  |  {court} {year}  |  BM25: {score:.1f}"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        if r.get("key_ratio"):
                            st.markdown(f"**Holding:** {r['key_ratio'][:400]}")
                        if r.get("facts_summary"):
                            st.markdown(f"**Facts:** {r['facts_summary'][:250]}")
                    with col2:
                        if r.get("url"):
                            st.markdown(f"[Open on IK ↗]({r['url']})")
                        # Copy citation button
                        citation_text = f"{r['citation']} ({court}, {year})"
                        st.code(citation_text, language=None)
                        if case_id and st.button("Add to Case", key=f"add_prec_{r['id']}"):
                            queries.add_argument(
                                case_id, "precedent",
                                f"{r['citation']}: {(r.get('key_ratio') or '')[:200]}",
                                r['citation'],
                                8, "", 3
                            )
                            st.success("Added!")


def _render_cbdt_quick(case_id, sections):
    try:
        from ai.cbdt_data import search_circulars, get_circulars_for_section
        import config

        query = st.text_input("Search circulars", placeholder="e.g. reasonable cause 269SS",
                               key="cbdt_q2")
        sec_filter = st.selectbox("Section", ["All"] + sections, key="cbdt_sec2")

        if sec_filter != "All":
            circs = get_circulars_for_section(sec_filter)
        elif query:
            circs = search_circulars(query)
        else:
            from ai.cbdt_data import CBDT_CIRCULARS
            circs = CBDT_CIRCULARS[:15]

        st.markdown(f"**{len(circs)} circulars**")
        for circ in circs[:10]:
            favour_icon = {"assessee": "✅", "revenue": "❌", "neutral": "⚖️"}.get(
                circ.get("favour","neutral"), "📋")
            with st.expander(f"{favour_icon} Circular {circ['number']} — {circ['subject'][:60]}"):
                st.markdown(f"**Date:** {circ['date']}")
                st.markdown(f"**Summary:** {circ['summary'][:300]}")
                st.info(f"**Key Para:** _{circ['key_para']}_")
                if case_id and st.button("Add to Case", key=f"add_circ2_{circ['id']}"):
                    queries.add_argument(
                        case_id, "circular",
                        f"CBDT Circular {circ['number']}: {circ['key_para'][:200]}",
                        f"Circular {circ['number']}",
                        8, "", 3
                    )
                    st.success("Added!")
    except Exception as e:
        st.error(f"CBDT data error: {e}")


def _render_ik_search(case_id):
    from ai.indian_kanoon import search_itat_cases, format_results, get_doc, clean_html
    import config

    query = st.text_input("Search Indian Kanoon", placeholder="section 269SS cash loan penalty",
                           key="ik_search2")
    if st.button("Search IK", type="primary", disabled=not query):
        from ai.indian_kanoon import search_cases
        with st.spinner("Searching..."):
            raw   = search_cases(query, 0)
            cases = format_results(raw, max_results=10)

        if not cases:
            st.warning("No results.")
        else:
            for c in cases:
                with st.expander(f"📄 {c['title'][:75]}  |  {c['court']}  |  {c['date']}"):
                    st.markdown(c.get("headline","")[:300])
                    st.markdown(f"[Open ↗]({c['url']})")


# ── Import needed for _draft_submission ──────────────────────────────────────
from datetime import datetime
