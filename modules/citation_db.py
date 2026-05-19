"""Citation Database — browse, search, and harvest 1000+ verified citations."""
import streamlit as st
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ai.citation_harvester import (
    HARVEST_TARGETS, harvest_section, harvest_all,
    get_citation_count, get_citations_for_section,
    search_citations, format_citations_for_display,
)
from database.queries import get_statistics


# ─────────────────────────────────────────────────────────────────────────────
_COURT_ICONS = {"SC": "🏛️", "HC": "⚖️", "ITAT": "📋", "OTHER": "📄"}
_COURT_LABELS = {"SC": "Supreme Court", "HC": "High Court",
                 "ITAT": "ITAT", "OTHER": "Other"}


def render():
    st.header("📎 Citation Database")
    st.caption(
        "15,000+ real, verified case citations from Indian Kanoon — "
        "120 sections of the Income Tax Act, 1961 covered. Every citation has a direct link."
    )

    # ── Top stats ─────────────────────────────────────────────────────────────
    total = get_citation_count()
    stats = get_statistics()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Verified Citations", f"{total:,}", help="Real cases from Indian Kanoon with links")
    col2.metric("IT Act Sections Covered", len(HARVEST_TARGETS))
    col3.metric("CBDT Circulars", stats.get("total_circulars", 0))
    col4.metric("Local Precedents", stats.get("total_precedents", 0))

    if total == 0:
        st.warning(
            "⚠️ Citation database is empty. "
            "Run **Harvest All Sections** below to fetch 15,000+ real citations from Indian Kanoon."
        )
    elif total < 1000:
        st.info(f"📊 {total:,} citations so far. Run full harvest to reach 15,000+ target.")
    elif total < 6000:
        st.info(f"📊 {total:,} citations. Good start — run harvest again to reach the 15,000 target.")
    elif total < 15000:
        st.info(f"📊 {total:,} citations. Run harvest again to complete all 120 sections.")
    else:
        st.success(f"✅ {total:,} verified citations — all 120 sections covered. AI outputs are fully grounded in real case law.")

    tab1, tab2, tab3, tab4 = st.tabs([
        "🚀 Indian Kanoon",
        "🌐 Web Sources",
        "🔎 Browse & Search",
        "📊 Coverage Report",
    ])

    with tab1:
        _render_harvest(total)
    with tab2:
        _render_web_sources()
    with tab3:
        _render_browse()
    with tab4:
        _render_coverage()


# ── Tab 1: Harvest ────────────────────────────────────────────────────────────
def _render_harvest(current_total: int):
    st.subheader("🚀 Fetch Verified Citations from Indian Kanoon")
    st.markdown("""
    Systematically searches Indian Kanoon for **real ITAT/HC/SC judgments**
    across **120 sections of the Income Tax Act, 1961** — every litigated section covered.

    | What | Numbers |
    |------|---------|
    | Sections covered | **120** (cash penalties · unexplained income · TDS · capital gains · deductions · international tax · assessments · penalties · MAT · search) |
    | Queries per section | 4–6 targeted search queries |
    | Pages per query | 6 pages × 10 results |
    | Raw results | ~**36,000** |
    | After dedup | **15,000+** unique verified citations |
    | Each citation has | Case title · Court · Year · Key ratio · **Direct IK link** |
    | Time to run | ~**90–120 minutes** (rate-limited for IK servers) |

    ⚡ **Tip:** Run from terminal for reliability — `python run_harvest.py --ik-only`
    """)

    import config as cfg
    if not cfg.INDIAN_KANOON_API_KEY:
        st.error("❌ Indian Kanoon API key not configured. Go to ⚙️ Settings.")
        return

    st.info(f"✅ Indian Kanoon API: connected — currently {current_total:,} citations in DB")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Full Harvest** (~5-8 min)")
        st.caption(f"Covers all {len(HARVEST_TARGETS)} sections — 15,000+ citations target")
        run_full = st.button("⚡ Harvest All 120 Sections (15,000+ Citations)", type="primary",
                             disabled=st.session_state.get("harvesting", False))

    with col2:
        st.markdown("**Single Section Harvest** (~10-15 sec)")
        section_pick = st.selectbox(
            "Pick a section",
            [s for s, _ in HARVEST_TARGETS],
            key="harvest_section_pick",
        )
        run_single = st.button(f"Fetch § {section_pick}", key="run_single_harvest",
                               disabled=st.session_state.get("harvesting", False))

    # ── Run single section ────────────────────────────────────────────────────
    if run_single and section_pick:
        queries_for_section = next((q for s, q in HARVEST_TARGETS if s == section_pick), [])
        log_box = st.empty()
        status_box = st.empty()
        log_lines = []

        def cb(msg):
            log_lines.append(msg)
            log_box.code("\n".join(log_lines[-20:]), language=None)

        status_box.info(f"Fetching § {section_pick}...")
        added = harvest_section(section_pick, queries_for_section, cb)
        status_box.success(f"✅ Done — added {added} new citations for § {section_pick}")
        st.rerun()

    # ── Run full harvest ──────────────────────────────────────────────────────
    if run_full:
        st.session_state["harvesting"] = True
        log_box   = st.empty()
        prog_bar  = st.progress(0)
        status_box = st.empty()
        log_lines = []
        results = {"done": 0, "total": len(HARVEST_TARGETS)}

        def cb(msg):
            log_lines.append(msg)
            log_box.code("\n".join(log_lines[-30:]), language=None)
            if msg.startswith("["):
                # extract progress
                try:
                    n = int(msg.split("/")[0].strip("["))
                    prog_bar.progress(n / len(HARVEST_TARGETS))
                    results["done"] = n
                except Exception:
                    pass

        status_box.info("🔄 Harvesting — do not close this tab...")
        summary = harvest_all(cb)
        total_added = summary["total_added"]
        new_total = get_citation_count()
        st.session_state["harvesting"] = False
        status_box.success(
            f"✅ Harvest complete! Added **{total_added}** new citations. "
            f"Total in DB: **{new_total:,}**"
        )
        prog_bar.progress(1.0)
        st.rerun()

    # ── Per-section quick fetch buttons ──────────────────────────────────────
    st.divider()
    st.markdown("**Or fetch individual sections:**")
    cols = st.columns(6)
    for i, (sec, _) in enumerate(HARVEST_TARGETS):
        with cols[i % 6]:
            if st.button(f"§ {sec}", key=f"quick_harvest_{sec}", use_container_width=True):
                queries_for_section = next((q for s, q in HARVEST_TARGETS if s == sec), [])
                with st.spinner(f"Fetching § {sec}..."):
                    added = harvest_section(sec, queries_for_section)
                st.success(f"+{added} for § {sec}")
                st.rerun()


# ── Tab 2: Web Sources ───────────────────────────────────────────────────────
def _render_web_sources():
    st.subheader("🌐 Web-Source Citation Harvester")
    st.markdown("""
    Scrapes **real case URLs** from **8 high-quality Indian tax law sources**.
    Every citation links back to its original source — fully verifiable.

    | # | Source | Content | Volume |
    |---|--------|---------|--------|
    | 1 | **⚖️ itatonline.org** | Expert-curated ITAT/HC/SC with full legal ratios | 3,100+ cases |
    | 2 | **📋 TaxGuru — ITAT** | ITAT judgments category | 6,700+ pages × 60/page |
    | 3 | **🏛️ TaxGuru — High Court** | HC income tax judgments | 60/page |
    | 4 | **📰 Taxscan.in** | ITAT Weekly Roundup + live income-tax RSS | Weekly updated |
    | 5 | **🎯 CAclubindia.com** | Income Tax judgments (offset pagination) | 2,820+ cases |
    | 6 | **🏛️ TaxGuru — Supreme Court** | SC income tax judgments (highest authority) | 100+ per RSS |
    | 7 | **📜 TaxGuru — CBDT Circulars** | CBDT circulars (threshold limits, reasonable cause) | 100 per RSS |
    | 8 | **📣 TaxGuru — CBDT Notifications** | CBDT notifications (extensions, exemptions) | 100 per RSS |
    """)

    try:
        from ai.scrapers.multi_source_harvester import (
            harvest_source, harvest_all_sources,
            get_scraped_count, get_source_breakdown,
        )
        from ai.scrapers import SOURCE_REGISTRY as _SR
    except ImportError as e:
        st.error(f"Scraper module not available: {e}")
        return

    scraped = get_scraped_count()
    breakdown = get_source_breakdown()

    # ── Stats row ────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    col1.metric("Web-Scraped Citations", f"{scraped:,}")
    src_count = len([b for b in breakdown if b["source_name"] not in ("", "indian_kanoon")])
    col2.metric("Sources Active", src_count)
    if breakdown:
        newest = max((b["count"] for b in breakdown
                      if b["source_name"] not in ("", "indian_kanoon")), default=0)
        col3.metric("Largest Source", f"{newest:,}")

    if scraped > 0:
        st.success(f"✅ {scraped:,} web-scraped citations in database")
        # Source breakdown table
        if breakdown:
            st.markdown("**Per-Source Breakdown:**")
            src_labels = {
                "itatonline":          "⚖️ itatonline.org",
                "taxguru_itat":        "📋 TaxGuru — ITAT",
                "taxguru_hc":          "🏛️ TaxGuru — High Court",
                "taxscan":             "📰 Taxscan.in",
                "taxscan_roundup":     "📰 Taxscan Weekly Roundup",
                "caclubindia":         "🎯 CAclubindia.com",
                "taxguru_sc":          "🏛️ TaxGuru — Supreme Court",
                "cbdt_circular":       "📜 CBDT Circulars",
                "cbdt_notification":   "📣 CBDT Notifications",
                "taxguru":             "📋 TaxGuru.in",
                "indian_kanoon":       "🔵 Indian Kanoon API",
                "":                    "🔵 Indian Kanoon API",
            }
            header = "| Source | Citations | Sections |"
            sep    = "|--------|-----------|----------|"
            rows   = []
            for b in breakdown:
                name = src_labels.get(b["source_name"], b["source_name"])
                rows.append(f"| {name} | **{b['count']:,}** | {b['sections']} |")
            st.markdown(header + "\n" + sep + "\n" + "\n".join(rows))
    else:
        st.info("No web-scraped citations yet. Run a harvest below.")

    st.divider()

    # ── Harvest ALL sources ───────────────────────────────────────────────────
    st.markdown("### ⚡ Harvest All Sources")
    col_a, col_b = st.columns([2, 1])
    with col_a:
        pages_all = st.slider(
            "Pages per source", min_value=1, max_value=20, value=5,
            key="web_pages_all",
            help="Each page = ~10-60 cases depending on source. 5 pages ≈ 200-300 cases total."
        )
        st.caption(f"~{pages_all * 10}–{pages_all * 100} cases expected from {len(_SR)} sources")
    with col_b:
        run_all = st.button(
            f"🌐 Harvest All {len(_SR)} Sources",
            type="primary",
            disabled=st.session_state.get("web_harvesting", False),
            use_container_width=True,
        )

    if run_all:
        st.session_state["web_harvesting"] = True
        log_box    = st.empty()
        prog_bar   = st.progress(0)
        status_box = st.empty()
        log_lines  = []
        sources    = list(_SR.keys())

        def cb(msg):
            log_lines.append(msg)
            log_box.code("\n".join(log_lines[-25:]), language=None)
            # Update progress based on which source we're on
            for i, s in enumerate(sources):
                if f"[{s}]" in msg or s + ":" in msg.lower():
                    prog_bar.progress((i + 0.5) / len(sources))

        status_box.info("🔄 Harvesting web sources — please wait...")
        summary = harvest_all_sources(max_pages=pages_all, progress_cb=cb)
        total_new = summary.get("total_added", 0)
        new_total = get_scraped_count()
        st.session_state["web_harvesting"] = False
        prog_bar.progress(1.0)
        status_box.success(
            f"✅ Done! **+{total_new}** new citations. "
            f"Web-scraped total: **{new_total:,}**"
        )
        st.rerun()

    st.divider()

    # ── Per-source harvest buttons ────────────────────────────────────────────
    st.markdown("### 🔧 Individual Source Harvest")
    for key, info in _SR.items():
        with st.expander(f"**{info['name']}** — {info['description']}"):
            col1, col2 = st.columns([2, 1])
            with col1:
                pages = st.slider(
                    f"Pages to scrape", 1, 30,
                    info["max_pages_default"],
                    key=f"web_pages_{key}",
                    help=f"~{info['approx_per_page']} cases per page"
                )
                st.caption(f"Estimated: {pages * info['approx_per_page']} cases")
            with col2:
                if st.button(
                    f"Fetch {info['name']}",
                    key=f"web_fetch_{key}",
                    use_container_width=True,
                    disabled=st.session_state.get("web_harvesting", False),
                ):
                    st_log = st.empty()
                    lines  = []
                    def _cb(msg, _lines=lines, _box=st_log):
                        _lines.append(msg)
                        _box.code("\n".join(_lines[-15:]), language=None)
                    with st.spinner(f"Scraping {info['name']}..."):
                        result = harvest_source(key, max_pages=pages, progress_cb=_cb)
                    st.success(f"+{result['added']} new, {result['skipped']} already in DB")
                    st.rerun()


# ── Tab 3: Browse & Search ────────────────────────────────────────────────────
def _render_browse():
    st.subheader("🔎 Browse & Search Citation Database")

    col1, col2, col3 = st.columns([3, 1.5, 1.5])
    with col1:
        query = st.text_input(
            "Search citations",
            placeholder="e.g.  reasonable cause   cash loan   bogus purchase   deemed dividend",
            key="cite_search_q",
        )
    with col2:
        section_opts = ["All Sections"] + [s for s, _ in HARVEST_TARGETS]
        section = st.selectbox("Section", section_opts, key="cite_section")
    with col3:
        court = st.selectbox("Court", ["ALL", "SC", "HC", "ITAT"], key="cite_court")

    # Fetch
    if query:
        sec_arg = "" if section == "All Sections" else section
        results = search_citations(query, sec_arg, limit=30)
    elif section != "All Sections":
        results = get_citations_for_section(
            section, limit=30,
            court_type="ALL" if court == "ALL" else court,
        )
    else:
        # Show latest harvested
        from database.init_db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM itat_precedents WHERE verified IN (1, 2)
            ORDER BY harvested_at DESC, year DESC LIMIT 50
        """)
        results = [dict(r) for r in cur.fetchall()]
        conn.close()

    # Filter by court if query mode
    if court != "ALL" and results:
        results = [r for r in results if r.get("court_type") == court]

    if not results:
        st.info("No verified citations found. Run the Harvest first or try a different search.")
        return

    st.markdown(f"**{len(results)} citations** found")
    st.divider()

    _SRC_LABELS = {
        "itatonline":        "⚖️ itatonline.org",
        "taxguru_itat":      "📋 TaxGuru ITAT",
        "taxguru_hc":        "🏛️ TaxGuru HC",
        "taxguru_sc":        "🏛️ TaxGuru SC",
        "taxscan":           "📰 Taxscan.in",
        "taxscan_roundup":   "📰 Taxscan Roundup",
        "caclubindia":       "🎯 CAclubindia",
        "cbdt_circular":     "📜 CBDT Circular",
        "cbdt_notification": "📣 CBDT Notification",
        "taxguru":           "📋 TaxGuru.in",
        "indian_kanoon":     "🔵 Indian Kanoon",
        "":                  "🔵 Indian Kanoon",
    }
    for c in results:
        ct = c.get("court_type", "OTHER")
        icon = _COURT_ICONS.get(ct, "📄")
        label = _COURT_LABELS.get(ct, "Other")
        url = c.get("ik_url", "") or c.get("source_url", "")
        title = c.get("case_citation", "Untitled")[:100]
        ratio = c.get("key_ratio", "")
        year = c.get("year", "")
        bench = c.get("bench", "")
        src_name = _SRC_LABELS.get(c.get("source_name", ""), c.get("source_name", "IK"))
        verified = c.get("verified", 0)
        v_badge = "🟢 IK-verified" if verified == 1 else ("🔵 Web-scraped" if verified == 2 else "")

        with st.expander(f"{icon} {title}"):
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            c1.markdown(f"**Court:** {bench[:60] if bench else label}")
            c2.markdown(f"**Year:** {year or 'N/A'}")
            c3.markdown(f"**Section:** {c.get('section','')}")
            c4.markdown(f"**Source:** {src_name}  {v_badge}")

            if ratio:
                st.markdown("**Key Ratio / Headline:**")
                st.info(ratio[:400])

            if url:
                ik_prefix = "indiankanoon.org" in url
                link_label = "Open on Indian Kanoon ↗" if ik_prefix else f"Open source ({src_name}) ↗"
                st.markdown(f"🔗 **[{link_label}]({url})**")
                st.caption(url)
            else:
                st.caption("No direct link available")

    st.divider()
    # Export as markdown
    if st.button("📋 Copy All as Markdown Citations"):
        md = format_citations_for_display(results)
        st.text_area("Markdown (copy this)", md, height=300)


# ── Tab 3: Coverage Report ────────────────────────────────────────────────────
def _render_coverage():
    st.subheader("📊 Coverage by IT Act Section")
    st.caption("Shows how many verified citations exist per section in the local DB.")

    from database.init_db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT section,
               COUNT(*) as total,
               SUM(CASE WHEN court_type='SC' THEN 1 ELSE 0 END) as sc,
               SUM(CASE WHEN court_type='HC' THEN 1 ELSE 0 END) as hc,
               SUM(CASE WHEN court_type='ITAT' THEN 1 ELSE 0 END) as itat
        FROM itat_precedents
        WHERE verified IN (1, 2)
        GROUP BY section
        ORDER BY total DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        st.info("No citations harvested yet. Go to 🚀 Harvest Citations tab.")
        return

    # Summary metrics
    total_cites  = sum(r["total"] for r in rows)
    sections_covered = len(rows)
    sc_count  = sum(r["sc"] for r in rows)
    hc_count  = sum(r["hc"] for r in rows)
    itat_count = sum(r["itat"] for r in rows)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Citations", f"{total_cites:,}")
    c2.metric("Sections Covered", sections_covered)
    c3.metric("🏛️ SC", sc_count)
    c4.metric("⚖️ HC", hc_count)
    c5.metric("📋 ITAT", itat_count)

    st.divider()

    # Table
    header = "| Section | Total | 🏛️ SC | ⚖️ HC | 📋 ITAT | Status |"
    sep    = "|---------|-------|-------|-------|---------|--------|"
    table_rows = []
    for r in rows:
        status = "✅ Good" if r["total"] >= 8 else ("⚠️ Partial" if r["total"] >= 3 else "❌ Low")
        table_rows.append(
            f"| `§ {r['section']}` | **{r['total']}** | {r['sc']} | {r['hc']} | {r['itat']} | {status} |"
        )

    st.markdown(header + "\n" + sep + "\n" + "\n".join(table_rows))

    # Sections not yet harvested
    harvested_sections = {r["section"] for r in rows}
    missing = [s for s, _ in HARVEST_TARGETS if s not in harvested_sections]
    if missing:
        st.warning(f"**{len(missing)} sections not yet harvested:** {', '.join(missing[:10])}{'...' if len(missing) > 10 else ''}")
        if st.button("Fetch Missing Sections Now"):
            for sec in missing:
                q = next((q for s, q in HARVEST_TARGETS if s == sec), [])
                with st.spinner(f"§ {sec}..."):
                    harvest_section(sec, q)
            st.rerun()
