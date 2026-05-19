"""
Case Intelligence Analyser — the core engine for upload → report.

Pipeline (runs automatically on PDF upload):
  1. extract_case_intelligence()  — Claude reads PDF, returns structured JSON:
       case_summary, key_issues, ao_contentions, search_queries (5-8 targeted)
  2. ai.live_search.run_live_search() — Scrapes all 6 sources LIVE using case queries:
       ① Indian Kanoon API   ② TaxGuru RSS search
       ③ itatonline search   ④ CAclubindia judiciary search
       ⑤ TaxGuru CBDT RSS    ⑥ Taxscan RSS (filtered)
  3. get_finance_act_history()    — Legislative history of violated sections
  4. build_report()               — Master function: runs 1-3, returns full report dict

Report dict shape:
  {
    "intelligence": {summary, issues, ao_contentions, facts, assessee_type, ...},
    "sc":           [case_dict, ...],      # Supreme Court
    "hc":           [case_dict, ...],      # High Courts
    "itat":         [case_dict, ...],      # ITAT
    "cbdt":         [case_dict, ...],      # Circulars + Notifications
    "finance_act":  str,                   # Legislative history markdown
    "advance_rulings": [case_dict, ...],   # AAR / Advance Rulings
    "queries_used": [str, ...],            # What was searched
    "error":        str | None,
  }
"""

import json
import re
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── helpers ───────────────────────────────────────────────────────────────────

def _clean_html(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = re.sub(r"&[a-z#0-9]+;", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _year_from_str(s: str) -> int:
    m = re.search(r"\b(19|20)\d{2}\b", s or "")
    return int(m.group()) if m else 0


def _court_of_doc(docsource: str) -> str:
    s = (docsource or "").lower()
    if "supreme" in s:
        return "SC"
    if "high court" in s or any(hc in s for hc in [
        "bombay", "delhi", "madras", "calcutta", "allahabad",
        "gujarat", "karnataka", "punjab", "kerala", "rajasthan",
        "andhra", "telangana", "madhya", "orissa", "patna"
    ]):
        return "HC"
    if "appellate tribunal" in s or "itat" in s or "income tax appellate" in s:
        return "ITAT"
    if "authority for advance" in s or "aar" in s:
        return "AAR"
    return "OTHER"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Extract Case Intelligence via Claude
# ─────────────────────────────────────────────────────────────────────────────

def extract_case_intelligence(pdf_text: str, sections: list,
                               metadata: dict,
                               rag_context: str = "") -> dict:
    """
    Use Claude to read the PDF and extract structured case intelligence.

    Returns dict:
      case_summary, key_issues, ao_contentions, assessee_type,
      nature_of_addition, key_facts, search_queries (5-8 targeted),
      cbdt_keywords, advance_ruling_likely (bool)
    """
    from ai.claude_client import call_claude

    sections_str = ", ".join(f"§{s}" for s in sections) if sections else "unknown"
    ay = metadata.get("assessment_year", "—")
    demand = metadata.get("demand_amount", 0) or 0
    assessee = metadata.get("assessee_name", "")

    # ── Redact PII before sending to AI ──────────────────────────────────────
    from utils.pii_redactor import redact_for_ai
    clean_text, _pii_report = redact_for_ai(
        pdf_text[:4000],
        scan_metadata=metadata,
        is_external=True,
    )

    system_prompt = (
        "You are an expert Indian tax litigation AI. "
        "Extract structured intelligence from an income tax assessment or penalty order. "
        "The document has been pre-processed: sensitive identifiers replaced with tokens like "
        "《PAN-REDACTED》, 《NAME-REDACTED》 etc. — treat these as placeholders. "
        "Return ONLY valid JSON — no markdown fences, no explanation. "
        "NEVER invent case names or section numbers not visible in the document.\n\n"
        + (f"VERIFIED PRECEDENTS FOR CONTEXT (do NOT cite others):\n{rag_context}\n"
           if rag_context else "")
    )

    user_prompt = f"""Analyze this income tax order and return a JSON object.

--- DOCUMENT (first 3500 characters — PII redacted) ---
{clean_text[:3500]}
--- END ---

DETECTED SECTIONS VIOLATED: {sections_str}
ASSESSMENT YEAR: {ay}
DEMAND / PENALTY: ₹{demand:,.0f}
ASSESSEE: {assessee or "unknown"}

Return EXACTLY this JSON structure (fill every field):
{{
  "case_summary": "2-3 sentences summarising what happened: who was assessed, what was disallowed/penalised, why, and the demand amount.",
  "key_issues": ["Issue 1 in plain English", "Issue 2", "Issue 3"],
  "ao_contentions": ["AO's argument 1", "AO's argument 2"],
  "assessee_type": "one of: individual / company / HUF / firm / trust / AOP",
  "nature_of_addition": "Short description: e.g. 'Cash loans taken without cheque — §269SS addition of ₹15L'",
  "key_facts": ["Fact 1 relevant to defences", "Fact 2", "Fact 3"],
  "search_queries": [
    "Targeted IK/legal search query 1 — specific to THIS case's facts e.g. 'cash loan family member genuine 269SS penalty deleted ITAT'",
    "Query 2 — different angle e.g. 'reasonable cause 273B penalty waiver 271D cash loan'",
    "Query 3",
    "Query 4",
    "Query 5"
  ],
  "cbdt_keywords": ["keyword1 to match CBDT circulars", "keyword2"],
  "advance_ruling_likely": false,
  "finance_act_sections": {json.dumps(sections)}
}}

CRITICAL for search_queries: make them SPECIFIC to this case's actual facts.
Do NOT use generic queries like "section 269SS income tax".
DO use factual queries like "cash loan relatives no account payee cheque 269SS genuine family transaction ITAT deleted".
Include the section number AND key factual elements AND desired outcome."""

    try:
        raw = call_claude(system_prompt, user_prompt, max_tokens=1200)
        # Strip markdown fences if model added them
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        json_m = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_m:
            data = json.loads(json_m.group())
            # Ensure required keys exist
            data.setdefault("case_summary", f"Assessment order AY {ay}, demand ₹{demand:,.0f}")
            data.setdefault("key_issues", [f"§{s} violation" for s in sections])
            data.setdefault("ao_contentions", [])
            data.setdefault("search_queries",
                            [f"section {s} income tax ITAT penalty deleted" for s in sections[:5]])
            data.setdefault("cbdt_keywords", sections)
            data.setdefault("finance_act_sections", sections)
            data.setdefault("advance_ruling_likely", False)
            return data
    except Exception:
        pass

    # Graceful fallback — no AI available / parse error
    return {
        "case_summary": (
            f"Assessment order for AY {ay}. "
            f"Sections violated: {sections_str}. "
            f"Demand: ₹{demand:,.0f}."
        ),
        "key_issues": [f"§{s} violation" for s in sections],
        "ao_contentions": [],
        "assessee_type": "unknown",
        "nature_of_addition": sections_str,
        "key_facts": [],
        "search_queries": [
            f"section {s} income tax penalty ITAT assessee" for s in sections[:5]
        ],
        "cbdt_keywords": sections,
        "advance_ruling_likely": False,
        "finance_act_sections": sections,
    }


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Live Indian Kanoon Search
# ─────────────────────────────────────────────────────────────────────────────

def search_live_ik(queries: list, sections: list,
                   progress_cb=None) -> dict:
    """
    Run each query against Indian Kanoon API.
    Returns { "sc": [...], "hc": [...], "itat": [...], "aar": [...], "cbdt": [...] }
    Each item: {title, url, court, date, year, headline, court_type, source, query_matched}
    """
    try:
        from ai.indian_kanoon import search_cases, clean_html
        import config
        if not config.INDIAN_KANOON_API_KEY:
            return {"sc": [], "hc": [], "itat": [], "aar": [], "cbdt": [],
                    "error": "IK API key not configured"}
    except Exception as e:
        return {"sc": [], "hc": [], "itat": [], "aar": [], "cbdt": [], "error": str(e)}

    # Auto-add CBDT/Finance Act queries for each section
    cbdt_queries = [f"CBDT circular section {s}" for s in sections[:3]]
    all_queries  = list(queries[:8]) + cbdt_queries[:2]

    seen_tids = set()
    grouped = {"sc": [], "hc": [], "itat": [], "aar": [], "cbdt": []}

    for q in all_queries:  # main queries + auto CBDT queries
        if progress_cb:
            progress_cb(f"  🔍 IK: {q[:70]}...")
        try:
            result = search_cases(q)
            docs = result.get("docs", [])
            for doc in docs[:10]:
                tid = str(doc.get("tid", ""))
                if not tid or tid in seen_tids:
                    continue
                seen_tids.add(tid)

                title   = clean_html(doc.get("title", "Untitled"))
                src     = doc.get("docsource", "")
                date    = doc.get("publishdate", "")
                headline = clean_html(doc.get("headline", ""))
                ct      = _court_of_doc(src)
                url     = f"https://indiankanoon.org/doc/{tid}/"

                entry = {
                    "title":       title,
                    "url":         url,
                    "court":       src,
                    "court_type":  ct,
                    "date":        date,
                    "year":        _year_from_str(date),
                    "headline":    headline[:300],
                    "source":      "indian_kanoon",
                    "ik_tid":      tid,
                    "query":       q[:60],
                }

                # Route CBDT circulars/notifications into cbdt bucket
                title_lower = title.lower()
                is_cbdt = ("cbdt" in title_lower or "circular" in title_lower
                           or "notification" in title_lower
                           or "cbdt" in q.lower())
                if is_cbdt and ct not in ("SC", "HC"):
                    grouped["cbdt"].append(entry)
                elif ct == "SC":
                    grouped["sc"].append(entry)
                elif ct == "HC":
                    grouped["hc"].append(entry)
                elif ct == "ITAT":
                    grouped["itat"].append(entry)
                elif ct == "AAR":
                    grouped["aar"].append(entry)
                else:
                    grouped["itat"].append(entry)  # best-effort

            time.sleep(0.6)  # rate limit

        except Exception as e:
            if progress_cb:
                progress_cb(f"  ⚠️ IK error for query: {e}")
            continue

    # Sort each group: newest first
    for k in grouped:
        grouped[k].sort(key=lambda x: x["year"], reverse=True)

    if progress_cb:
        total = sum(len(v) for v in grouped.values())
        progress_cb(f"  ✅ IK: {total} results ({len(grouped['sc'])} SC, "
                    f"{len(grouped['hc'])} HC, {len(grouped['itat'])} ITAT)")
    return grouped


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Local DB Search
# ─────────────────────────────────────────────────────────────────────────────

def search_local_db(queries: list, sections: list,
                    progress_cb=None) -> dict:
    """
    Search local itat_precedents table across all 8 scraped sources.
    Uses LIKE-based FTS against case_citation + key_ratio + facts_summary.
    Returns { "sc": [...], "hc": [...], "itat": [...], "cbdt": [...] }
    """
    from database.init_db import get_connection

    conn   = get_connection()
    cur    = conn.cursor()
    seen   = set()
    groups = {"sc": [], "hc": [], "itat": [], "cbdt": []}

    # 1. Section-based exact match (highest relevance)
    for sec in sections:
        cur.execute("""
            SELECT * FROM itat_precedents
            WHERE verified IN (1,2)
              AND (section = ? OR sections_json LIKE ?)
            ORDER BY CASE court_type WHEN 'SC' THEN 1 WHEN 'HC' THEN 2
                     WHEN 'ITAT' THEN 3 ELSE 4 END,
                     year DESC
            LIMIT 20
        """, (sec, f'%"{sec}"%'))
        for row in cur.fetchall():
            r = dict(row)
            uid = r.get("ik_url") or r.get("case_citation", "")
            if uid in seen:
                continue
            seen.add(uid)
            _bucket_db_row(r, groups)

    # 2. Keyword search across key_ratio / case_citation
    keywords = _extract_keywords_from_queries(queries)
    for kw in keywords[:12]:
        q = f"%{kw}%"
        cur.execute("""
            SELECT * FROM itat_precedents
            WHERE verified IN (1,2)
              AND (LOWER(case_citation) LIKE LOWER(?)
                   OR LOWER(key_ratio)   LIKE LOWER(?)
                   OR LOWER(facts_summary) LIKE LOWER(?))
            ORDER BY CASE court_type WHEN 'SC' THEN 1 WHEN 'HC' THEN 2
                     WHEN 'ITAT' THEN 3 ELSE 4 END,
                     year DESC
            LIMIT 10
        """, (q, q, q))
        for row in cur.fetchall():
            r = dict(row)
            uid = r.get("ik_url") or r.get("case_citation", "")
            if uid in seen:
                continue
            seen.add(uid)
            _bucket_db_row(r, groups)

    conn.close()

    # Sort each group newest first
    for k in groups:
        groups[k].sort(key=lambda x: x.get("year", 0), reverse=True)

    if progress_cb:
        total = sum(len(v) for v in groups.values())
        progress_cb(f"  ✅ DB: {total} results from local sources")
    return groups


def _extract_keywords_from_queries(queries: list) -> list:
    """
    Extract meaningful keywords from AI-generated search queries.
    Filters out common stop words and short tokens.
    """
    stop = {
        "the", "and", "or", "of", "in", "to", "for", "a", "an", "is",
        "are", "was", "were", "be", "been", "income", "tax", "itat",
        "section", "under", "this", "with", "that", "from", "by", "on",
        "at", "as", "it", "its", "not", "but"
    }
    keywords = []
    seen_kw = set()
    for q in queries:
        for word in re.findall(r"\b[a-zA-Z]{4,}\b", q.lower()):
            if word not in stop and word not in seen_kw:
                seen_kw.add(word)
                keywords.append(word)
    return keywords


def _bucket_db_row(r: dict, groups: dict):
    """Sort a DB row into the right group."""
    ct = r.get("court_type", "OTHER")
    src = r.get("source_name", "")
    entry = {
        "title":      r.get("case_citation", "")[:120],
        "url":        r.get("ik_url") or r.get("source_url", ""),
        "court":      r.get("bench", ""),
        "court_type": ct,
        "date":       r.get("harvested_at", ""),
        "year":       r.get("year", 0),
        "headline":   (r.get("key_ratio") or "")[:300],
        "source":     src or "local_db",
        "section":    r.get("section", ""),
    }
    if src in ("cbdt_circular", "cbdt_notification"):
        groups["cbdt"].append(entry)
    elif ct == "SC":
        groups["sc"].append(entry)
    elif ct == "HC":
        groups["hc"].append(entry)
    else:
        groups["itat"].append(entry)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — CBDT Circulars / Notifications
# ─────────────────────────────────────────────────────────────────────────────

def fetch_cbdt_entries(sections: list, keywords: list,
                       progress_cb=None) -> list:
    """
    Pull CBDT circulars + notifications from local DB that match
    the sections or keywords from this case.
    """
    from database.init_db import get_connection

    conn = get_connection()
    cur  = conn.cursor()
    seen = set()
    results = []

    # 1. Match by section
    for sec in sections:
        cur.execute("""
            SELECT * FROM itat_precedents
            WHERE source_name IN ('cbdt_circular','cbdt_notification')
              AND (section = ? OR sections_json LIKE ? OR LOWER(case_citation) LIKE LOWER(?))
            ORDER BY year DESC LIMIT 10
        """, (sec, f'%"{sec}"%', f"%{sec}%"))
        for row in cur.fetchall():
            r = dict(row)
            uid = r.get("ik_url") or r.get("case_citation", "")
            if uid not in seen:
                seen.add(uid)
                results.append(_format_cbdt_row(r))

    # 2. Match by keyword
    for kw in (keywords or [])[:8]:
        q = f"%{kw}%"
        cur.execute("""
            SELECT * FROM itat_precedents
            WHERE source_name IN ('cbdt_circular','cbdt_notification')
              AND (LOWER(case_citation) LIKE LOWER(?) OR LOWER(key_ratio) LIKE LOWER(?))
            ORDER BY year DESC LIMIT 5
        """, (q, q))
        for row in cur.fetchall():
            r = dict(row)
            uid = r.get("ik_url") or r.get("case_citation", "")
            if uid not in seen:
                seen.add(uid)
                results.append(_format_cbdt_row(r))

    conn.close()
    results.sort(key=lambda x: x.get("year", 0), reverse=True)

    if progress_cb:
        progress_cb(f"  ✅ CBDT: {len(results)} circulars/notifications matched")
    return results


def _format_cbdt_row(r: dict) -> dict:
    return {
        "title":       r.get("case_citation", "")[:120],
        "url":         r.get("ik_url") or r.get("source_url", ""),
        "court":       "CBDT",
        "court_type":  "OTHER",
        "date":        "",
        "year":        r.get("year", 0),
        "headline":    (r.get("key_ratio") or "")[:300],
        "source":      r.get("source_name", "cbdt_circular"),
        "section":     r.get("section", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Finance Act Legislative History
# ─────────────────────────────────────────────────────────────────────────────

_FINANCE_ACT_DB = {
    "269SS": (
        "**§269SS — Prohibition on cash loans above threshold**\n"
        "- Introduced by **Finance Act 1984** to curb unaccounted cash movement\n"
        "- Original threshold: ₹10,000\n"
        "- Raised to **₹20,000** by Finance Act 2015 (w.e.f. 01-06-2015)\n"
        "- Linked penalty: §271D (100% of loan amount)\n"
        "- Exemption via §273B: Reasonable cause can delete penalty\n"
        "- Key CBDT Circular 387/1984: explains 'genuine' transactions"
    ),
    "269T": (
        "**§269T — Prohibition on cash repayment of loans**\n"
        "- Introduced by **Finance Act 1984** (same package as §269SS)\n"
        "- Threshold: ₹20,000 (raised by FA 2015)\n"
        "- Covers repayment of loans, deposits, and specified advances\n"
        "- Linked penalty: §271E (100% of repaid amount)"
    ),
    "269ST": (
        "**§269ST — Cash receipt limit of ₹2 lakh**\n"
        "- Inserted by **Finance Act 2017** (w.e.f. 01-04-2017)\n"
        "- Prohibits receipt of ₹2 lakh or more in cash in aggregate\n"
        "- Applies per person, per day, per transaction, per occasion\n"
        "- Linked penalty: §271DA (100% of received amount)\n"
        "- Exemption for Government/banks"
    ),
    "271D": (
        "**§271D — Penalty for §269SS violation**\n"
        "- Penalty = 100% of loan/deposit amount\n"
        "- Levied by **Joint Commissioner** (not AO)\n"
        "- Saved by §273B if 'reasonable cause' exists\n"
        "- 3-year limitation from date of initiation"
    ),
    "271E": (
        "**§271E — Penalty for §269T violation**\n"
        "- Penalty = 100% of repayment amount\n"
        "- Same reasonable cause defence via §273B"
    ),
    "68": (
        "**§68 — Unexplained Cash Credits**\n"
        "- Assessee must explain: identity, creditworthiness, genuineness of transaction\n"
        "- Amended by **Finance Act 2012**: onus on closely-held company to prove source of share capital/premium\n"
        "- CBDT Circular 6/2016: clarification on burden of proof\n"
        "- Taxable at special rate of 60% + surcharge if §115BBE applies"
    ),
    "271(1)(c)": (
        "**§271(1)(c) — Penalty for Concealment / Inaccurate Particulars**\n"
        "- 100%–300% of tax on concealed income\n"
        "- Replaced by §270A for cases from AY 2017-18 onwards\n"
        "- Bona fide mistake / full disclosure = no concealment\n"
        "- Satisfaction must be recorded at assessment stage"
    ),
    "270A": (
        "**§270A — Penalty for Under-reporting / Misreporting**\n"
        "- Inserted by **Finance Act 2016** (replaced §271(1)(c) from AY 2017-18)\n"
        "- Under-reporting: 50% of tax; Misreporting: 200% of tax\n"
        "- Immunity available under §270AA if tax + interest paid and no appeal"
    ),
    "40A(3)": (
        "**§40A(3) — Cash Payment Disallowance**\n"
        "- Payment >₹10,000 cash to a person in a day = 100% disallowance\n"
        "- Threshold reduced from ₹20,000 to ₹10,000 by **Finance Act 2017**\n"
        "- Exceptions in **Rule 6DD** (agriculturists, remote areas, emergencies)\n"
        "- §40A(3A): applies to expenses of earlier years paid in current year"
    ),
    "14A": (
        "**§14A — Disallowance for Exempt Income**\n"
        "- Inserted by **Finance Act 2001** (retrospective effect)\n"
        "- Method of computation in **Rule 8D** (w.e.f. AY 2008-09)\n"
        "- AO must record satisfaction before invoking Rule 8D\n"
        "- Finance Act 2022: no disallowance if no exempt income earned"
    ),
    "153A": (
        "**§153A — Assessment after Search**\n"
        "- Inserted by **Finance Act 2003**\n"
        "- 6 years + current year of search\n"
        "- Addition only if 'incriminating material' found during search\n"
        "- Finance Act 2021: §153A/153C amended — only 10 years for tax evasion >₹50L"
    ),
    "148": (
        "**§148 — Reassessment Notice**\n"
        "- **Finance Act 2021** completely overhauled reassessment:\n"
        "  - New §148A: mandatory show-cause notice before issuing §148\n"
        "  - Time limits reduced to 3 years (ordinary) / 10 years (>₹50L escaped income)\n"
        "  - All pre-2021 notices challenged; Supreme Court: Ashish Agarwal ruling"
    ),
    "56(2)": (
        "**§56(2) — Income from Other Sources (Gifts/Receipts)**\n"
        "- §56(2)(viib) — Angel Tax: inserted by FA 2012, exemption for DPIIT-recognised startups\n"
        "- §56(2)(x) — Replaced §56(2)(vii) from AY 2017-18: any person can be taxed on gifts >₹50,000\n"
        "- Finance Act 2023: Angel tax extended to non-residents"
    ),
}


def get_finance_act_history(sections: list) -> str:
    """
    Return markdown string with Finance Act legislative history
    for each violated section.
    Uses static DB first; falls back to Claude for unlisted sections.
    """
    lines = []
    unknown = []

    for sec in sections:
        if sec in _FINANCE_ACT_DB:
            lines.append(_FINANCE_ACT_DB[sec])
        else:
            unknown.append(sec)

    if unknown:
        # Try Claude for unknown sections
        try:
            from ai.claude_client import call_claude
            prompt = (
                f"For these Income Tax Act 1961 sections: {', '.join(unknown)}, "
                "provide a brief 3-4 bullet legislative history: "
                "when introduced, any Finance Act amendments, key changes, and penalty implications. "
                "Format as markdown bullet list. Be factual, no hallucination."
            )
            result = call_claude(
                "You are an Indian tax legislation expert. Be concise and accurate.",
                prompt, max_tokens=600
            )
            if result:
                lines.append(f"**§{', §'.join(unknown)} — Legislative History**\n{result}")
        except Exception:
            for s in unknown:
                lines.append(f"**§{s}** — Refer to the Income Tax Act 1961 for legislative history.")

    return "\n\n---\n\n".join(lines) if lines else "No legislative history available."


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Merge & Deduplicate Results
# ─────────────────────────────────────────────────────────────────────────────

def _merge_groups(ik_groups: dict, db_groups: dict) -> dict:
    """
    Merge IK live results and DB results, deduplicating by URL/title.
    IK results come first (live > cached), then DB.
    """
    merged = {}
    for key in ["sc", "hc", "itat", "cbdt", "aar"]:
        seen_urls  = set()
        combined   = []
        for item in (ik_groups.get(key, []) + db_groups.get(key, [])):
            uid = (item.get("url") or item.get("title", ""))[:100]
            if uid and uid not in seen_urls:
                seen_urls.add(uid)
                combined.append(item)
        # Sort: newest first, IK results first (they have ik_tid)
        combined.sort(
            key=lambda x: (0 if x.get("source") == "indian_kanoon" else 1, -x.get("year", 0))
        )
        merged[key] = combined[:25]  # cap per group
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# MASTER: build_report()
# ─────────────────────────────────────────────────────────────────────────────

def build_report(pdf_text: str, sections: list, metadata: dict,
                 progress_cb=None) -> dict:
    """
    Full pipeline: extract → live search → DB search → CBDT → finance act.
    Returns complete report dict ready for display.

    progress_cb(str) — optional callback for live status updates in UI.
    """
    def _cb(msg):
        if progress_cb:
            progress_cb(msg)

    _cb("🧠 Step 1/5 — Extracting case intelligence...")

    # ── Inject RAG context into extraction prompt ────────────────────────────
    from ai.rag import build_citation_context
    rag_context = build_citation_context(sections, limit=8)
    _cb(f"  📚 RAG: injecting verified citations into AI prompt")

    intel = extract_case_intelligence(pdf_text, sections, metadata,
                                      rag_context=rag_context)
    _cb(f"  ✅ Summary extracted. Issues: {len(intel.get('key_issues', []))}")

    queries = intel.get("search_queries", [])
    if not queries:
        queries = [f"section {s} income tax penalty ITAT" for s in sections[:5]]

    cbdt_keywords = intel.get("cbdt_keywords", sections)

    _cb(f"\n🌐 Step 2/4 — Live scraping all 6 sources with case-specific queries...")
    _cb(f"  Queries: {queries[:3]}")

    # ── LIVE SEARCH: IK + TaxGuru + itatonline + CAclubindia + CBDT + Taxscan
    from ai.live_search import run_live_search
    live = run_live_search(
        queries=queries,
        sections=sections,
        cbdt_keywords=cbdt_keywords,
        progress_cb=_cb,
    )

    _cb(f"\n📜 Step 3/4 — Finance Act legislative history...")
    fin_history = get_finance_act_history(sections)

    # Advance rulings (AAR from IK search that matched)
    advance_rulings = live.pop("other", [])

    total = sum(len(v) for v in live.values()) + len(advance_rulings)
    _cb(f"\n✅ Step 4/4 — Report assembled: {total} relevant items found")

    return {
        "intelligence":    intel,
        "sc":              live.get("sc", []),
        "hc":              live.get("hc", []),
        "itat":            live.get("itat", []),
        "cbdt":            live.get("cbdt", []),
        "advance_rulings": advance_rulings,
        "finance_act":     fin_history,
        "queries_used":    queries,
        "total_found":     total,
        "sections":        sections,
        "metadata":        metadata,
        "error":           None,
    }
