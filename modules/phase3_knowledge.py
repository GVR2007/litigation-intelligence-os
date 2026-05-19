"""Phase 3: Knowledge Harvester — statute retrieval, ITAT precedent mapping, Indian Kanoon live search, CBDT circulars."""
import streamlit as st
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import ITAT_SECTIONS
from database import queries
from utils.helpers import parse_sections
from ai.claude_client import call_claude, stream_claude
from ai.indian_kanoon import search_itat_cases, search_hc_cases, search_sc_cases, format_results, get_doc, clean_html
from ai.prompts import KNOWLEDGE_SYSTEM


def render():
    st.header("Phase 3: Knowledge Harvester")
    st.caption("Statute Library · CBDT Circulars · Live Case Search · Local Precedents · Custom Research")

    case_id = st.session_state.get("active_case_id")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📚 Statute Library",
        "📋 CBDT Circulars",
        "🔎 Live Case Search",
        "⚖️ Local Precedents",
        "🔍 Custom Research",
    ])

    with tab1:
        _render_statute_library(case_id)
    with tab2:
        _render_cbdt_circulars(case_id)
    with tab3:
        _render_live_search(case_id)
    with tab4:
        _render_local_precedents(case_id)
    with tab5:
        _render_custom_research()


# ── Tab 1: Statute Library ─────────────────────────────────────────────────────
def _render_statute_library(case_id):
    st.subheader("Statute Library — Exact Statutory Text")

    all_sections = list(ITAT_SECTIONS.keys())
    case_sections = []
    if case_id:
        case = queries.get_case(case_id)
        if case:
            case_sections = parse_sections(case["sections_violated"])
            if case_sections:
                st.success(f"Active case sections: {', '.join(case_sections)}")

    display_sections = case_sections if case_sections else all_sections
    selected_section = st.selectbox("Select Section", display_sections,
                                    key="statute_section_select")
    info = ITAT_SECTIONS.get(selected_section, {})

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"### § {selected_section}")
        st.markdown(f"**{info.get('name', 'Section not in library')}**")
        st.caption(f"Category: {info.get('category', '—')}")
        if info.get("penalty_section"):
            st.error(f"Linked Penalty Section: § {info['penalty_section']}  |  Max: {info.get('max_penalty', 'N/A')}")
    with col2:
        st.markdown("**Key Defences:**")
        for d in info.get("key_defences", ["Consult AI analysis"]):
            st.markdown(f"✓ {d}")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button(f"Get Full AI Analysis for § {selected_section}", type="primary"):
            with st.spinner("Fetching statutory text and judicial trend..."):
                result = call_claude(
                    KNOWLEDGE_SYSTEM,
                    f"Provide a complete knowledge brief for Section {selected_section} "
                    f"({info.get('name','')}) of the Income Tax Act 1961.\n\n"
                    "Include:\n"
                    "1. Exact statutory text (verbatim)\n"
                    "2. Provisos and explanations\n"
                    "3. Thresholds and conditions\n"
                    "4. Supreme Court position\n"
                    "5. ITAT judicial trend (assessee-friendly / revenue-friendly?)\n"
                    "6. Key ratio from 5+ landmark cases (real citations only)\n"
                    "7. Recent amendments or CBDT circulars\n\n"
                    "Zero hallucination — only cite real, verifiable cases.",
                    max_tokens=6000,
                )
                st.markdown(result)
    with col_b:
        if st.button(f"Search Indian Kanoon for § {selected_section}"):
            st.session_state["ik_prefill_section"] = selected_section
            st.session_state["ik_prefill_court"] = "All Courts"
            st.rerun()

    st.divider()
    st.subheader("ITAT Bench Alignment Check")
    bench = st.selectbox("Bench Location", [
        "Delhi", "Mumbai", "Kolkata", "Chennai", "Ahmedabad",
        "Bangalore", "Hyderabad", "Pune", "Chandigarh", "Jaipur",
    ])
    if st.button(f"Run Bench Alignment — {bench}"):
        with st.spinner("Analysing bench patterns..."):
            result = call_claude(
                KNOWLEDGE_SYSTEM,
                f"Analyse the ITAT {bench} bench's track record on Section {selected_section}.\n"
                "1. Historical assessee win-rate at this bench\n"
                "2. Notable judgments from this bench\n"
                "3. Arguments that have worked here\n"
                "4. Arguments that have failed here\n"
                "5. Recommended approach for this bench",
            )
            st.markdown(result)


# ── Tab 2: CBDT Circulars ─────────────────────────────────────────────────────
def _render_cbdt_circulars(case_id):
    from ai.cbdt_data import search_circulars, get_circulars_for_section, CBDT_CIRCULARS
    from ai.indian_kanoon import search_cases, format_results, clean_html
    import config as cfg

    st.subheader("📋 CBDT Circulars & Notifications")
    st.caption(
        f"**{len(CBDT_CIRCULARS)} circulars** curated locally · "
        "Search by keyword, section, or circular number · "
        "Each entry includes subject, key para, and court cases that cited it."
    )

    # ── Quick section shortcut for active case ────────────────────────────────
    case_sections = []
    if case_id:
        case = queries.get_case(case_id)
        if case:
            case_sections = parse_sections(case["sections_violated"])

    if case_sections:
        st.markdown("**Circulars relevant to your case sections:**")
        btn_cols = st.columns(min(len(case_sections), 6))
        for i, sec in enumerate(case_sections[:6]):
            with btn_cols[i]:
                if st.button(f"§ {sec}", key=f"cbdt_quick_{sec}"):
                    st.session_state["cbdt_section_filter"] = sec
                    st.rerun()

    st.divider()

    # ── Search controls ────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([3, 1.5, 1.5])
    with col1:
        query = st.text_input(
            "Search circulars",
            value="",
            placeholder="e.g.  269SS cash loan   |   reasonable cause   |   angel tax   |   TDS contractor",
            key="cbdt_search_query",
        )
    with col2:
        section_filter = st.selectbox(
            "Filter by Section",
            ["All sections"] + list(ITAT_SECTIONS.keys()),
            index=0,
            key="cbdt_section_select",
        )
        # Override from quick button
        if st.session_state.get("cbdt_section_filter"):
            sf = st.session_state.pop("cbdt_section_filter")
            section_filter = sf
    with col3:
        favour_filter = st.selectbox(
            "Favours",
            ["All", "Assessee", "Revenue", "Neutral"],
            key="cbdt_favour_filter",
        )

    # ── Fetch results ──────────────────────────────────────────────────────────
    from ai.cbdt_data import SECTION_CIRCULAR_MAP

    if section_filter != "All sections":
        results = queries.get_circulars_for_section_db(section_filter)
        if not results:
            # Fallback to in-memory data
            from ai.cbdt_data import get_circulars_for_section
            raw = get_circulars_for_section(section_filter)
            results = [_circular_to_db_format(c) for c in raw]
        header = f"Circulars for § {section_filter}"
    elif query:
        from ai.cbdt_data import search_circulars as _search
        raw = _search(query)
        results = [_circular_to_db_format(c) for c in raw]
        header = f"Search results for: {query!r}"
    else:
        results = queries.get_all_circulars(50)
        header = f"All {len(CBDT_CIRCULARS)} circulars"

    # Apply favour filter
    if favour_filter != "All":
        results = [r for r in results if r.get("favour", "") == favour_filter.lower()]

    # ── Display results ────────────────────────────────────────────────────────
    st.markdown(f"### {header} — {len(results)} found")

    if not results:
        st.info("No circulars found for this filter. Try a different keyword or section.")
        return

    for circ in results:
        try:
            sections_list = json.loads(circ["sections"]) if isinstance(circ["sections"], str) else circ["sections"]
        except Exception:
            sections_list = []

        favour = circ.get("favour", "neutral")
        favour_icon = {"assessee": "✅", "revenue": "❌", "neutral": "⚖️"}.get(favour, "📋")
        favour_label = {"assessee": "Assessee-friendly", "revenue": "Revenue-friendly", "neutral": "Neutral"}.get(favour, "")

        with st.expander(
            f"{favour_icon} **Circular {circ['number']}** | {circ['date']} | {circ['subject'][:70]}"
        ):
            # Header row
            c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
            c1.markdown(f"**Subject:** {circ['subject']}")
            c2.markdown(f"**Type:** {circ.get('type','circular').title()}")
            c3.markdown(f"**Date:** {circ['date']}")
            c4.markdown(f"**Verdict:** {favour_icon} {favour_label}")

            # Sections tags
            if sections_list:
                tags = " ".join([f"`§ {s}`" for s in sections_list])
                st.markdown(f"**Applies to:** {tags}")

            st.divider()

            # Summary
            st.markdown("**Summary:**")
            st.markdown(circ["summary"])

            # Key para box
            st.markdown("**Key Para (cite this):**")
            st.info(f"*{circ['key_para']}*")

            # Action buttons
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                ik_query = f"CBDT Circular {circ['number']} income tax"
                if st.button("🔎 Find Cases Citing This", key=f"ik_circ_{circ['id']}"):
                    with st.spinner("Searching Indian Kanoon..."):
                        raw_ik = search_cases(ik_query, 0)
                        ik_cases = format_results(raw_ik, max_results=8)
                    if ik_cases:
                        st.markdown(f"**Cases citing Circular {circ['number']}:**")
                        for c in ik_cases:
                            st.markdown(
                                f"- [{c['title'][:65]}]({c['url']})  "
                                f"*{c['court']}* ({c['date']})"
                            )
                    else:
                        st.info("No cases found on Indian Kanoon. Try searching manually.")

            with col_b:
                if case_id and st.button("➕ Add to Case", key=f"add_circ_{circ['id']}"):
                    queries.add_argument(
                        case_id, "circular",
                        f"CBDT Circular {circ['number']} ({circ['date']}): {circ['key_para'][:200]}",
                        f"Circular {circ['number']} — {circ['subject'][:80]}",
                        8, "", 3
                    )
                    st.success("✅ Added to case arguments!")

            with col_c:
                if cfg.ANTHROPIC_API_KEY or True:  # always show
                    if st.button("🧠 AI Deep-Dive", key=f"ai_circ_{circ['id']}"):
                        with st.spinner("Analysing..."):
                            result = call_claude(
                                KNOWLEDGE_SYSTEM,
                                f"Explain CBDT Circular {circ['number']} dated {circ['date']} "
                                f"on '{circ['subject']}' in the context of ITAT litigation.\n\n"
                                "1. Exact scope and applicability\n"
                                "2. How assessee can use this circular in their defence\n"
                                "3. Revenue's counter-arguments\n"
                                "4. Top 3 ITAT/HC decisions that relied on this circular\n"
                                "5. Practical drafting tip for citing this in submission",
                                max_tokens=3000,
                            )
                        st.markdown(result)

    # ── Stats footer ──────────────────────────────────────────────────────────
    st.divider()
    assessee_count = sum(1 for c in CBDT_CIRCULARS if c["favour"] == "assessee")
    revenue_count  = sum(1 for c in CBDT_CIRCULARS if c["favour"] == "revenue")
    neutral_count  = sum(1 for c in CBDT_CIRCULARS if c["favour"] == "neutral")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Circulars", len(CBDT_CIRCULARS))
    c2.metric("Assessee-Friendly ✅", assessee_count)
    c3.metric("Revenue-Friendly ❌", revenue_count)
    c4.metric("Neutral ⚖️", neutral_count)


def _circular_to_db_format(c: dict) -> dict:
    """Convert in-memory cbdt_data format to DB row format."""
    import json
    return {
        "id": c["id"],
        "type": c["type"],
        "number": c["number"],
        "date": c["date"],
        "subject": c["subject"],
        "sections": json.dumps(c["sections"]),
        "summary": c["summary"],
        "key_para": c["key_para"],
        "favour": c["favour"],
    }


# ── Tab 3: Live Indian Kanoon Search ──────────────────────────────────────────
def _render_live_search(case_id):
    st.subheader("🔎 Live Case Search — Indian Kanoon")
    st.caption("Searches real ITAT, High Court and Supreme Court judgments via Indian Kanoon API.")

    # Pre-fill from statute library button
    prefill_section = st.session_state.pop("ik_prefill_section", "")
    prefill_court = st.session_state.pop("ik_prefill_court", "All Courts")

    # Get active case sections for quick-fill buttons
    case_sections = []
    if case_id:
        case = queries.get_case(case_id)
        if case:
            case_sections = parse_sections(case["sections_violated"])

    col1, col2, col3 = st.columns([2, 1.5, 1])
    with col1:
        query = st.text_input(
            "Search query",
            value=f"section {prefill_section} income tax" if prefill_section else "",
            placeholder="e.g.  section 269SS cash loan penalty 273B reasonable cause",
        )
    with col2:
        court_type = st.selectbox(
            "Court",
            ["All Courts", "ITAT", "High Court", "Supreme Court"],
            index=["All Courts", "ITAT", "High Court", "Supreme Court"].index(prefill_court)
                  if prefill_court in ["All Courts", "ITAT", "High Court", "Supreme Court"] else 0,
        )
    with col3:
        page = st.number_input("Page", min_value=0, value=0, step=1)

    # Quick section buttons for active case
    if case_sections:
        st.markdown("**Quick search for your case sections:**")
        btn_cols = st.columns(min(len(case_sections), 6))
        for i, sec in enumerate(case_sections[:6]):
            with btn_cols[i]:
                if st.button(f"§ {sec}", key=f"ik_quick_{sec}"):
                    st.session_state["ik_prefill_section"] = sec
                    st.session_state["ik_prefill_court"] = court_type
                    st.rerun()

    search_clicked = st.button("🔍 Search Indian Kanoon", type="primary", disabled=not query)

    if search_clicked and query:
        # Build court-specific query
        if court_type == "ITAT":
            full_query = f"{query} income tax appellate tribunal"
        elif court_type == "High Court":
            full_query = f"{query} high court"
        elif court_type == "Supreme Court":
            full_query = f"{query} supreme court"
        else:
            full_query = query

        with st.spinner(f"Searching Indian Kanoon for: {full_query!r}..."):
            raw = search_itat_cases.__wrapped__(full_query, page) if False else \
                  __import__("ai.indian_kanoon", fromlist=["search_cases"]).search_cases(full_query, page)
            cases = format_results(raw, max_results=15)

        if "error" in raw and not cases:
            st.error(f"Indian Kanoon API error: {raw['error']}")
        elif not cases:
            st.warning("No cases found. Try different keywords.")
        else:
            total = raw.get("total", len(cases))
            st.success(f"Found **{total:,}** matching judgments — showing top {len(cases)}")

            for c in cases:
                with st.expander(f"📄 {c['title'][:80]}  |  {c['court']}  |  {c['date']}"):
                    st.markdown(f"**Headline:** {c['headline'][:400]}" if c['headline'] else "")
                    col_a, col_b, col_c = st.columns(3)
                    col_a.write(f"**Court:** {c['court']}")
                    col_b.write(f"**Date:** {c['date']}")
                    col_c.markdown(f"[Open on Indian Kanoon ↗]({c['url']})")

                    if c['tid']:
                        if st.button("Load Full Judgment Text", key=f"ik_full_{c['tid']}"):
                            with st.spinner("Loading full judgment..."):
                                doc = get_doc(c['tid'])
                                if "error" in doc:
                                    st.error(doc["error"])
                                else:
                                    full_text = clean_html(doc.get("doc", ""))
                                    st.text_area("Full Judgment", full_text[:5000], height=300)
                                    if case_id and st.button("Add to Case Precedents", key=f"add_prec_{c['tid']}"):
                                        queries.add_argument(
                                            case_id, "precedent",
                                            f"Indian Kanoon: {c['title']} — {c['headline'][:150]}",
                                            c['title'],
                                            7, "", 3
                                        )
                                        st.success("Added to case arguments!")

    st.divider()
    _render_ik_stats()


def _render_ik_stats():
    import config as cfg
    key = cfg.INDIAN_KANOON_API_KEY
    if key:
        st.caption(f"✅ Indian Kanoon API connected — Token: {key[:8]}••••{key[-4:]}")
    else:
        st.warning("Indian Kanoon API key not set. Go to ⚙️ Settings.")


# ── Tab 3: Local Precedents DB ────────────────────────────────────────────────
def _render_local_precedents(case_id):
    st.subheader("Local Precedent Database")

    all_sections = list(ITAT_SECTIONS.keys())
    section_filter = st.selectbox("Filter by Section", ["All"] + all_sections, key="local_prec_filter")
    outcome_filter = st.selectbox("Outcome", ["All", "Assessee Won", "Revenue Won"])

    if section_filter != "All":
        precedents = queries.get_precedents_for_section(section_filter, limit=25)
    else:
        from database.init_db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM itat_precedents ORDER BY relevance_score DESC LIMIT 25")
        precedents = [dict(r) for r in cur.fetchall()]
        conn.close()

    if outcome_filter == "Assessee Won":
        precedents = [p for p in precedents if p["win_for_assessee"]]
    elif outcome_filter == "Revenue Won":
        precedents = [p for p in precedents if not p["win_for_assessee"]]

    if precedents:
        st.markdown(f"**{len(precedents)} precedents**")
        for p in precedents:
            icon = "✅" if p["win_for_assessee"] else "❌"
            bar = "█" * int(p["relevance_score"] * 10)
            with st.expander(f"{icon} {p['case_citation'][:80]} ({p['year']})  |  {bar}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Bench", p["bench"])
                c2.metric("Year", p["year"])
                c3.metric("Outcome", p["outcome"])
                st.markdown(f"**Key Ratio:** {p['key_ratio']}")
                st.markdown(f"**Facts:** {p['facts_summary']}")
                if case_id and st.button("Add to Case", key=f"add_local_{p['id']}"):
                    queries.add_argument(case_id, "precedent",
                                         f"{p['case_citation']}: {p['key_ratio']}",
                                         p["case_citation"],
                                         int(p["relevance_score"] * 10), "", 3)
                    st.success("Added!")
    else:
        st.info("No local precedents for this filter.")

    if st.button("Fetch More via AI"):
        sec = section_filter if section_filter != "All" else "269SS"
        with st.spinner(f"Researching precedents for § {sec}..."):
            result = call_claude(
                KNOWLEDGE_SYSTEM,
                f"List 10 important ITAT/HC/SC cases on Section {sec}.\n"
                "For each: full citation, outcome, key ratio, facts (2 sentences).\n"
                "Only cite real, verifiable cases.",
                max_tokens=5000,
            )
            st.markdown(result)


# ── Tab 4: Custom Research ─────────────────────────────────────────────────────
def _render_custom_research():
    st.subheader("Custom Legal Research")
    st.caption("Ask any Indian tax law question. Results pull from AI + optionally Indian Kanoon.")

    query = st.text_area(
        "Your research question",
        placeholder="e.g. Can ITAT condone delay beyond 365 days? What is the SC position on 40A(3) for agriculturists?\n"
                    "Or: Latest amendments to section 148A after Supreme Court ruling in Union of India v Ashish Agarwal.",
        height=120,
        key="custom_research_query",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        depth = st.radio("Depth", ["Quick (300 words)", "Deep (1000+ words)"])
    with col2:
        also_search_ik = st.checkbox("Also search Indian Kanoon", value=True)
    with col3:
        focus = st.multiselect("Focus", ["SC", "HC", "ITAT", "Circulars", "Amendments"])

    if st.button("Run Research", type="primary", disabled=not query):
        # Indian Kanoon live search
        if also_search_ik:
            with st.spinner("Searching Indian Kanoon..."):
                from ai.indian_kanoon import search_cases, format_results
                raw = search_cases(query, 0)
                ik_cases = format_results(raw, max_results=5)

            if ik_cases:
                st.markdown("#### Live Results from Indian Kanoon")
                for c in ik_cases:
                    st.markdown(
                        f"- [{c['title'][:70]}]({c['url']})  "
                        f"— *{c['court']}* ({c['date']})"
                    )
                st.divider()

        # AI research
        focus_str = ", ".join(focus) if focus else "all courts"
        depth_str = "Provide a concise 300-word answer with key citations." \
                    if "Quick" in depth else \
                    "Provide comprehensive 1000+ word analysis with full citations."
        with st.container():
            st.markdown("#### AI Legal Research")
            placeholder = st.empty()
            full = ""
            for chunk in stream_claude(
                KNOWLEDGE_SYSTEM,
                f"Research: {query}\nFocus on: {focus_str}\n{depth_str}\n\nOnly cite real, verifiable cases.",
            ):
                full += chunk
                placeholder.markdown(full + "▌")
            placeholder.markdown(full)
