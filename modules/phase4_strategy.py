"""
Phase 4: Strategy & Hearing Preparation — adversarial analysis, DR simulation,
argument chits, expected bench questions, counter-strategy.
"""

from __future__ import annotations
import streamlit as st
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import queries
from utils.helpers import parse_sections, format_currency
from ai.gemini_client import call_gemini, stream_gemini

_STRATEGY_SYSTEM = """You are a senior Indian Income Tax advocate with 25 years of ITAT
and High Court experience. You prepare litigation strategy, simulate the Departmental
Representative's arguments, and craft counter-arguments. You know every ITAT bench's
tendencies and have appeared in thousands of hearings. Your advice is sharp, specific,
and based on real ITAT precedent."""


def render():
    st.header("Phase 4: Strategy & Hearing Preparation")
    st.caption("DR Simulation · Argument Chits · Bench Questions · Counter-Strategy · Full Case File Export")

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

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "⚔️ DR Simulation",
        "🎤 Hearing Chits",
        "❓ Bench Questions",
        "🛡️ Defence Builder",
        "📊 Argument Ranking",
    ])

    with tab1:
        _render_dr_simulation(case_id, case, sections, evidence)
    with tab2:
        _render_hearing_chits(case_id, case, sections, evidence, args)
    with tab3:
        _render_bench_questions(case_id, case, sections, evidence)
    with tab4:
        _render_defence_builder(case_id, sections)
    with tab5:
        _render_argument_ranking(case_id, case, evidence, args)


# ── Tab 1: DR Simulation ──────────────────────────────────────────────────────

def _render_dr_simulation(case_id, case, sections, evidence):
    st.subheader("⚔️ DR (Departmental Representative) Simulation")
    st.caption("AI plays the Revenue's advocate — exposes every weak point before you reach ITAT.")

    available_docs   = [e["document_name"] for e in evidence if e.get("status") == "available"]
    unavailable_docs = [e["document_name"] for e in evidence if e.get("status") == "unavailable"]

    col1, col2 = st.columns(2)
    with col1:
        aggression = st.slider("DR Aggression Level", 1, 10, 7,
                                help="10 = most aggressive DR imaginable")
    with col2:
        bench_type = st.selectbox("Bench Type",
                                   ["Mixed (balanced)", "Revenue-leaning",
                                    "Assessee-friendly", "Technical/Procedure-focused"])

    rag_strategy = st.session_state.get(f"rag_strategy_{case_id}")
    counter_args = []
    if rag_strategy:
        counter_args = [c.revenue_argument for c in
                        getattr(rag_strategy, "counter_arguments", [])[:3]]
        if counter_args:
            st.info(f"🎯 RAG counter-arguments loaded: {len(counter_args)} Revenue arguments identified")

    if st.button("▶️ Run DR Simulation", type="primary"):
        evidence_status = (
            f"Documents we HAVE: {', '.join(available_docs[:10]) or 'None'}\n"
            f"Documents MISSING: {', '.join(unavailable_docs[:8]) or 'None'}"
        )
        rag_note = ""
        if counter_args:
            rag_note = f"\nRevenue's known strong arguments (from case law):\n" + \
                       "\n".join(f"- {a}" for a in counter_args)

        prompt = f"""Simulate the Departmental Representative in an ITAT hearing.

CASE:
Sections: {', '.join(sections)}
AY: {case.get('assessment_year','—')}
Demand: {format_currency(case.get('demand_amount') or 0)}
{evidence_status}
DR Aggression: {aggression}/10
Bench: {bench_type}
{rag_note}

Play the role of a skilled, {aggression}/10 aggressive DR. Present:

**PART 1 — REVENUE'S OPENING ARGUMENTS** (5 strongest, each with specific legal basis + citations)

**PART 2 — ATTACK ON MISSING DOCUMENTS**
For each missing document, state exactly how the DR will exploit the gap.

**PART 3 — PROCEDURAL & TECHNICAL ATTACKS**
Any technical arguments: limitation, jurisdiction, notice defects, etc.

**PART 4 — BENCH TRAPS**
What questions will this {bench_type} bench ask that could hurt the assessee?

**PART 5 — THE DR'S NUCLEAR CARD**
The single most dangerous argument — why it could sink the case if not answered.

**PART 6 — VULNERABILITY SCORE**
Rate each weakness: Critical / Serious / Minor

Be brutal. The point is to expose every gap."""

        dr_key = f"dr_sim_{case_id}"
        placeholder = st.empty()
        full = ""
        with st.spinner("Simulating Revenue attack..."):
            try:
                for chunk in stream_gemini(_STRATEGY_SYSTEM, prompt, max_tokens=5000):
                    full += chunk
                    placeholder.markdown(full + "▌")
            except Exception:
                full = call_gemini(_STRATEGY_SYSTEM, prompt, max_tokens=5000)
        placeholder.markdown(full)
        st.session_state[dr_key] = full

    # Counter-strategy from simulation
    if st.session_state.get(f"dr_sim_{case_id}"):
        st.divider()
        st.subheader("🛡️ Build Counter-Strategy")
        if st.button("⚡ Generate Counter-Arguments Against DR Simulation"):
            sim = st.session_state[f"dr_sim_{case_id}"]
            with st.spinner("Building counter-strategy..."):
                prompt = f"""The DR simulation for §{', '.join(sections)} produced this attack:

{sim[:2500]}

Now generate the assessee's complete counter-strategy:

1. **Point-by-point rebuttals** for each DR argument (with ITAT/HC citations)
2. **Additional case law** the DR did NOT cite that we can use offensively
3. **Procedural objections** we can raise against the Revenue
4. **Reframing the narrative** — shift the tribunal's focus to our strongest ground
5. **Pre-emptive statements** to make BEFORE the DR raises each objection
6. **One-liners for the bench** — memorable, factual statements that stick

Each rebuttal must cite a specific ITAT/HC/SC decision."""

                result = call_gemini(_STRATEGY_SYSTEM, prompt, max_tokens=5000)
                st.markdown(result)
                queries.add_argument(
                    case_id, "counter-strategy", result[:1500],
                    "DR Simulation Counter-Strategy", 9, sim[:300], 4
                )
                st.success("✅ Counter-strategy saved to case file.")


# ── Tab 2: Hearing Chits ──────────────────────────────────────────────────────

def _render_hearing_chits(case_id, case, sections, evidence, args):
    st.subheader("🎤 Hearing Argument Chits")
    st.caption(
        "Short, punchy argument cards for use during the hearing. "
        "Each chit = one ground + one citation + one sentence prayer."
    )

    available_docs = [e["document_name"] for e in evidence if e.get("status") == "available"]
    top_args       = [a["argument_text"][:150] for a in args[:5] if a.get("argument_text")]

    rag_strategy = st.session_state.get(f"rag_strategy_{case_id}")
    rag_args_block = ""
    if rag_strategy:
        rag_args = getattr(rag_strategy, "arguments", [])
        if rag_args:
            rag_args_block = "\nRAG-identified strongest arguments:\n" + "\n".join(
                f"- §{a.section}: {a.argument} (win rate: {a.win_rate:.0%})"
                for a in rag_args[:3]
            )

    col1, col2 = st.columns(2)
    with col1:
        chit_format = st.selectbox("Chit Format", [
            "One chit per legal ground (recommended)",
            "One comprehensive chit card",
            "Opening statement only",
            "Closing prayer only",
        ])
    with col2:
        hearing_duration = st.selectbox("Available Time", [
            "Short (15 minutes)",
            "Normal (30-45 minutes)",
            "Full day",
        ])

    if st.button("📋 Generate Argument Chits", type="primary"):
        time_note = {
            "Short (15 minutes)": "Keep each chit to 30 seconds of speaking. Maximum 3 grounds.",
            "Normal (30-45 minutes)": "3-5 minutes per ground. Include case law elaboration.",
            "Full day": "Full argument with detailed case law and response to counter-arguments.",
        }.get(hearing_duration, "")

        prompt = f"""Generate ITAT argument chits for this case.

CASE: {case.get('case_name','—')}
SECTIONS: {', '.join(sections)}
AY: {case.get('assessment_year','—')}
DEMAND: {format_currency(case.get('demand_amount') or 0)}
DOCUMENTS AVAILABLE: {', '.join(available_docs[:12]) or 'As per paper book'}
{rag_args_block}
TIME NOTE: {time_note}

Generate one chit per section/ground in this EXACT format:

---
**CHIT {'{'}N{'}'}  |  Ground: [section] — [brief ground name]**

**OPENING LINE:** [First sentence to say to the bench]

**FACTS:** [2-3 sentence factual matrix — only undisputed facts]

**LAW:** [Statutory provision + exact section text that helps us]

**CITATION:** [Best ITAT/HC/SC case — full citation]
*Ratio:* [One sentence: what the tribunal held]

**EVIDENCE:** [Documents we have that prove this ground]

**PRAYER:** [One sentence: exactly what relief to ask]

**IF BENCH ASKS:** [The one question they'll ask + the answer]
---

Generate one chit for each section in dispute. Make them self-contained — the advocate should be able to argue from the chit alone."""

        chit_key = f"chits_{case_id}"
        placeholder = st.empty()
        full = ""
        with st.spinner("Generating argument chits..."):
            try:
                for chunk in stream_gemini(_STRATEGY_SYSTEM, prompt, max_tokens=5000):
                    full += chunk
                    placeholder.markdown(full + "▌")
            except Exception:
                full = call_gemini(_STRATEGY_SYSTEM, prompt, max_tokens=5000)
        placeholder.markdown(full)
        st.session_state[chit_key] = full

    if st.session_state.get(f"chits_{case_id}"):
        chits = st.session_state[f"chits_{case_id}"]
        st.divider()
        edited = st.text_area("Review/edit chits:", value=chits, height=500,
                               key=f"chit_editor_{case_id}")
        st.session_state[f"chits_{case_id}"] = edited

        try:
            from utils.export import build_submission_docx
            docx_bytes = build_submission_docx(case, edited, "Hearing Argument Chits")
            st.download_button(
                "⬇️ Download Chits (DOCX)",
                data=docx_bytes,
                file_name=f"{case['case_name'][:25].replace(' ','_')}_chits.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True, type="primary",
            )
        except Exception as e:
            st.error(f"Export error: {e}")


# ── Tab 3: Bench Questions ────────────────────────────────────────────────────

def _render_bench_questions(case_id, case, sections, evidence):
    st.subheader("❓ Expected Bench Questions & Answers")
    st.caption(
        "Predict what the ITAT bench will ask based on the sections and fact pattern. "
        "Prepare your answers in advance."
    )

    available_docs   = [e["document_name"] for e in evidence if e.get("status") == "available"]
    unavailable_docs = [e["document_name"] for e in evidence if e.get("status") == "unavailable"]

    col1, col2 = st.columns(2)
    with col1:
        bench_location = st.selectbox("ITAT Bench Location", [
            "Delhi", "Mumbai", "Kolkata", "Chennai", "Ahmedabad",
            "Bangalore", "Hyderabad", "Pune", "Chandigarh", "Jaipur",
        ], key="bq_bench")
    with col2:
        question_types = st.multiselect(
            "Focus areas",
            ["Factual questions", "Legal questions", "Document questions",
             "Precedent questions", "Credibility questions"],
            default=["Factual questions", "Document questions"],
        )

    if st.button("❓ Generate Expected Questions", type="primary"):
        focus = ", ".join(question_types) if question_types else "all types"
        prompt = f"""Predict the questions the ITAT {bench_location} bench will ask in this case.

CASE:
Sections: {', '.join(sections)}
AY: {case.get('assessment_year','—')}
Demand: {format_currency(case.get('demand_amount') or 0)}
Documents we have: {', '.join(available_docs[:10]) or 'See paper book'}
Documents missing: {', '.join(unavailable_docs[:5]) or 'None'}
Focus: {focus}

Generate 10-15 questions the bench is LIKELY to ask, with prepared answers.

FORMAT for each:
**Q{'{'}N{'}'}: [The exact question the judge will ask]**
*Why they'll ask it:* [1 line — what concern this reveals]
*Prepared answer:* [2-3 sentences — confident, factual, cite one case if possible]
*Danger level:* 🔴 Critical / 🟡 Important / 🟢 Routine

Start with the most dangerous questions first.
End with a "Opening your submissions" script (3-4 sentences to say when you stand up)."""

        qns_key = f"bench_qns_{case_id}"
        placeholder = st.empty()
        full = ""
        with st.spinner("Predicting bench questions..."):
            try:
                for chunk in stream_gemini(_STRATEGY_SYSTEM, prompt, max_tokens=5000):
                    full += chunk
                    placeholder.markdown(full + "▌")
            except Exception:
                full = call_gemini(_STRATEGY_SYSTEM, prompt, max_tokens=5000)
        placeholder.markdown(full)
        st.session_state[qns_key] = full

    if st.session_state.get(f"bench_qns_{case_id}"):
        qns = st.session_state[f"bench_qns_{case_id}"]
        st.divider()
        edited = st.text_area("Review/edit:", value=qns, height=500,
                               key=f"qns_editor_{case_id}")
        st.session_state[f"bench_qns_{case_id}"] = edited

        try:
            from utils.export import build_submission_docx
            docx_bytes = build_submission_docx(case, edited, "Expected Bench Questions")
            st.download_button(
                "⬇️ Download Q&A Sheet (DOCX)",
                data=docx_bytes,
                file_name=f"{case['case_name'][:25].replace(' ','_')}_bench_qna.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True, type="primary",
            )
        except Exception as e:
            st.error(f"Export: {e}")


# ── Tab 4: Defence Builder ────────────────────────────────────────────────────

def _render_defence_builder(case_id, sections):
    st.subheader("🛡️ Defence Builder")
    st.caption("Construct the assessee's legal arguments, layer by layer.")

    col1, col2 = st.columns([2, 1])
    with col1:
        section_to_argue = st.selectbox("Build arguments for section", sections,
                                         key="def_sec")
        case_facts = st.text_area(
            "Case facts",
            placeholder="e.g. Small trader, loan from father-in-law (₹3L), cash needed urgently as bank closed due to strike, "
                        "contemporaneous cash book entries exist, lender filed ITR...",
            height=130,
            key="def_facts",
        )
        strategy_type = st.radio("Strategy", [
            "Full Defence (deny all charges)",
            "Alternative Plea (admit transaction, argue reasonable cause)",
            "Partial Relief (admit some, fight others)",
            "Delete Penalty Only (admit tax, fight penalty u/s 271D/273B)",
        ], key="def_strat")

    with col2:
        st.markdown("**Quick Templates**")
        templates = {
            "269SS Defence":   "Genuine business necessity + reasonable cause under 273B",
            "40A(3) Defence":  "Rule 6DD exception — payee is agriculturist in village",
            "153A Defence":    "No incriminating material; completed assessment protected",
            "68 Defence":      "Identity, creditworthiness, genuineness all established via ITR+bank",
            "148 Attack":      "No fresh tangible material; reopening is change of opinion",
        }
        for name, template in templates.items():
            if st.button(name, key=f"tmpl_{name}"):
                st.session_state["def_template"] = template

    if st.button("⚒️ Build Defence", type="primary",
                  disabled=not (section_to_argue and case_facts)):
        rag_strategy = st.session_state.get(f"rag_strategy_{case_id}")
        rag_block = ""
        if rag_strategy:
            rag_args = [a for a in getattr(rag_strategy, "arguments", [])
                        if a.section == section_to_argue]
            if rag_args:
                rag_block = "\nRAG-identified arguments for this section:\n" + "\n".join(
                    f"- {a.argument} (win rate {a.win_rate:.0%})" for a in rag_args[:3]
                )

        prompt = f"""Build comprehensive legal defence for Section {section_to_argue}.

Facts: {case_facts}
Strategy: {strategy_type}
{rag_block}

Draft in ITAT written submission format:

**GROUND 1 — PRIMARY LEGAL ARGUMENT**
[Main argument with statutory basis]

**GROUND 2 — PRECEDENT SUPPORT**
[5+ cases — ITAT/HC/SC — each with citation, court, year, and exact ratio]

**GROUND 3 — FACTUAL MATRIX**
[How the facts align with the law — point by point]

**GROUND 4 — REASONABLE CAUSE U/S 273B** (if applicable)
[Detailed reasonable cause argument with ITAT cases]

**GROUND 5 — ALTERNATIVE PLEA**
[Fallback: if primary ground fails, what next?]

**PRAYER**
[Specific relief: delete addition / delete penalty / reduce to ₹X / remand]

Format as ready-to-file written submissions. No preamble."""

        with st.spinner(f"Building defence for §{section_to_argue}..."):
            result = call_gemini(_STRATEGY_SYSTEM, prompt, max_tokens=5000)
        st.markdown(result)

        queries.add_argument(
            case_id, "defence",
            f"Defence §{section_to_argue}: {case_facts[:150]}",
            f"Defence Builder — §{section_to_argue}",
            9, "", 4
        )
        st.success("✅ Defence saved to case file.")

        try:
            from utils.export import build_submission_docx
            docx_bytes = build_submission_docx(case, result,
                                                f"Defence — §{section_to_argue}")
            st.download_button(
                "⬇️ Download Defence (DOCX)",
                data=docx_bytes,
                file_name=f"defence_{section_to_argue}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception:
            pass


# ── Tab 5: Argument Ranking ───────────────────────────────────────────────────

def _render_argument_ranking(case_id, case, evidence, args):
    st.subheader("📊 Argument Ranking & Full Case File")
    st.caption("All arguments ranked by strength. Export the complete case file.")

    if not args:
        st.info("No arguments saved yet. Use the Defence Builder and DR Simulation to generate them.")
    else:
        st.markdown(f"**{len(args)} arguments saved**")
        type_icons = {
            "defence": "🛡️", "precedent": "⚖️", "counter-strategy": "⚔️",
            "submission": "📝", "synopsis": "📄", "circular": "📋",
        }
        for i, arg in enumerate(args, 1):
            strength = arg.get("strength_score", 5)
            icon     = type_icons.get(arg.get("argument_type", ""), "📌")
            bar      = "█" * strength + "░" * (10 - strength)

            with st.expander(
                f"{icon} #{i} {arg.get('argument_type','').title()} | "
                f"Strength: {bar} ({strength}/10)"
            ):
                st.markdown(f"**{arg.get('argument_text','')[:400]}**")
                if arg.get("source_citation"):
                    st.caption(f"Source: {arg['source_citation'][:100]}")

        if len(args) > 1 and st.button("🎯 Optimise Argument Sequence"):
            summary = "\n".join(
                f"- [{a.get('argument_type','')}] {a.get('argument_text','')[:100]}"
                for a in args[:8]
            )
            with st.spinner("Optimising sequence..."):
                result = call_gemini(
                    _STRATEGY_SYSTEM,
                    f"Optimal ITAT hearing sequence for these arguments:\n{summary}\n\n"
                    "Provide: recommended order, reasoning, time allocation, "
                    "which to drop if short on time, how to transition between grounds.",
                    max_tokens=2000,
                )
            st.markdown(result)

    st.divider()
    st.subheader("📁 Full Case File Export")

    col1, col2 = st.columns(2)
    with col1:
        try:
            from utils.export import build_full_case_pdf
            submission_text = st.session_state.get(f"submission_draft_{case_id}", "")
            pdf_bytes = build_full_case_pdf(case, evidence, args, submission_text)
            fname = f"{case['case_name'][:30].replace(' ','_')}_full_case_file.pdf"
            st.download_button(
                "⬇️ Download Full Case File (PDF)",
                data=pdf_bytes,
                file_name=fname,
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
            st.caption("Includes: case summary · evidence checklist · arguments · submissions")
        except Exception as e:
            st.error(f"PDF export error: {e}")

    with col2:
        try:
            from utils.export import build_evidence_pdf
            ev_pdf = build_evidence_pdf(case, evidence)
            st.download_button(
                "⬇️ Evidence Checklist PDF",
                data=ev_pdf,
                file_name=f"{case['case_name'][:25].replace(' ','_')}_evidence.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Evidence PDF error: {e}")
