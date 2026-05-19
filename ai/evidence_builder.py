"""
Evidence Builder — auto-generates evidence checklist from live internet sources.

For each CONTESTED IT Act section in the case, runs:
  1. AO assessment order parsing — what did the AO specifically ask for / reject
  2. Local ITAT DB — verified precedents with key_ratio and facts_summary
  3. Indian Kanoon direct scrape — live judgment text (no API key needed)
  4. DDG + itatonline + taxguru — real case pages fetched and mined for document names
  5. Page-text mining — extract document names near "submitted / accepted / produced"
  6. Gemini synthesis — extract structured list from real case text only

PROCEDURAL SECTIONS (§139, §142, §143(2), §144B, §272A etc.) are SKIPPED —
they are mechanism sections, not dispute grounds, and need no separate evidence.

Returns structured items ready for add_evidence() in database/queries.py.
"""

import sys
import os
import json
import re
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

# ─────────────────────────────────────────────────────────────────────────────
# Procedural sections — pure procedure, not dispute grounds
# Evidence engine SKIPS these sections entirely
# ─────────────────────────────────────────────────────────────────────────────

PROCEDURAL_SECTIONS = {
    # Return filing
    "139", "139(1)", "139(4)", "139(5)",
    # Assessment procedure (not grounds of addition)
    "142", "142(1)", "143", "143(1)", "143(2)", "143(3)",
    "144", "144B",
    # Faceless procedure
    "144C",
    # Penalties for procedure (no substantive addition)
    "272A", "271F", "271FA",
    # Time-limit / notice provisions
    "149", "153", "153B",
    # Survey / information powers (cited procedurally, not as grounds)
    "131", "133",
    # Appeals procedure
    "246A", "250", "251", "253", "254",
}


def _is_procedural(section: str) -> bool:
    """Return True if this section is purely procedural (no separate evidence needed)."""
    s = section.strip()
    return s in PROCEDURAL_SECTIONS


# ─────────────────────────────────────────────────────────────────────────────
# Section → IK search queries (short phrases only — IK keyword search)
# ─────────────────────────────────────────────────────────────────────────────

_IK_QUERIES: dict[str, list[str]] = {
    "68":          ["68 cash credits identity creditworthiness", "68 unexplained credit documents accepted"],
    "69":          ["69 unexplained investment source funds", "69 agricultural income gift source"],
    "69A":         ["69A unexplained money jewellery source", "69A CBDT limit jewellery documents"],
    "69B":         ["69B investment undisclosed documents"],
    "69C":         ["69C unexplained expenditure source"],
    "115BBE":      ["115BBE unexplained income explanation documents"],
    "269SS":       ["269SS penalty deleted reasonable cause", "269SS cash loan family affidavit"],
    "269T":        ["269T cash repayment reasonable cause", "269T lender insistence affidavit"],
    "269ST":       ["269ST cash receipt 2 lakh evidence deleted"],
    "271D":        ["271D penalty deleted reasonable cause", "271D 273B documents accepted"],
    "271E":        ["271E penalty deleted cash repayment evidence"],
    "271(1)(c)":   ["271 concealment notice limb bona fide", "271 inaccurate particulars notice defect"],
    "270A":        ["270A under-reporting bona fide documents"],
    "40A(3)":      ["40A3 rule 6DD cash payment exception", "40A3 agriculturist bank unavailable"],
    "40(a)(ia)":   ["40aia TDS disallowance payee return filed"],
    "40(a)(i)":    ["40ai non-resident TDS DTAA exemption"],
    "36(1)(va)":   ["36 1 va employee contribution PF ESI due date"],
    "36(1)(iii)":  ["36 1 iii interest borrowed capital business purpose"],
    "37(1)":       ["37 business expenditure disallowance revenue capital"],
    "43B":         ["43B actual payment PF tax bonus before due date"],
    "14A":         ["14A exempt income own funds disallowance rule 8D"],
    "153A":        ["153A search incriminating material documents", "153A completed assessment no addition"],
    "153C":        ["153C other person search satisfaction note"],
    "147":         ["147 reassessment reasons tangible material"],
    "148":         ["148 notice time limit reasons to believe"],
    "148A":        ["148A show cause notice procedure evidence"],
    "263":         ["263 PCIT revision erroneous prejudicial documents"],
    "50C":         ["50C stamp duty value DVO reference deleted"],
    "56(2)(x)":    ["56 2 x receipt property inadequate consideration relatives"],
    "56(2)(viib)": ["56 2 viib angel tax FMV rule 11UA DPIIT startup"],
    "92":          ["92 transfer pricing arm length documentation"],
    "2(22)(e)":    ["2 22 e deemed dividend loan advance shareholder"],
    "132":         ["132 search seizure panchnama statement documents"],
    "133A":        ["133A survey statement not oath retraction"],
    "44AD":        ["44AD presumptive 8 percent turnover books", "44AD business income documents audit"],
    "44ADA":       ["44ADA professional receipts 50 percent presumptive", "44ADA gross receipts evidence documents"],
    "194J":        ["194J TDS professional services 10 percent", "194J technical services 2 percent payee return"],
    "194C":        ["194C TDS contract sub-contractor threshold", "194C payment contractor evidence"],
    "192":         ["192 TDS salary Form 16 employer"],
    "195":         ["195 TDS non-resident DTAA remittance"],
}


def _default_ik_queries(section: str) -> list[str]:
    return [
        f"{section} income tax evidence documents ITAT",
        f"{section} penalty deleted accepted assessee won",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Page text fetcher — get full text of a web page
# ─────────────────────────────────────────────────────────────────────────────

_FETCH_CACHE: dict[str, str] = {}   # in-memory session cache for fetched pages

_ASSESSEE_CONTEXT_WORDS = [
    "submitted", "produced", "furnished", "filed", "provided", "adduced",
    "placed on record", "relied upon by assessee", "accepted by tribunal",
    "tribunal accepted", "allowed by tribunal", "assessee produced",
    "assessee submitted", "assessee furnished", "evidence accepted",
    "document accepted", "relied upon in support",
]

_AO_CONTEXT_WORDS = [
    "ao issued", "officer issued", "department raised", "issued by ao",
    "assessment order", "demand notice", "penalty notice",
    "show cause notice", "notice issued by", "order passed by ao",
    "ao observed", "ao noted",
]

_DOC_NOUNS = [
    # Bank / financial — longest/most specific first
    "bank account statement", "bank account statements",
    "bank statement", "bank statements",
    "bank passbook", "pass book", "passbook",
    "bank reconciliation statement",
    "bank certificate", "banker certificate",
    "cancelled cheque", "demand draft",
    "cash deposit slip", "cash withdrawal slip",
    "fixed deposit receipt",
    # Income tax / returns — use actual ITA judgment language
    "income tax return", "return of income", "ITR",
    "form 26as", "26as", "form 16a", "form 16",
    "form 3cb", "form 3cd",
    "tax audit report", "audit report",
    "tds certificate", "tds return", "TDS certificate",
    "advance tax challan", "challan",
    "computation of income",
    # Loan and cash transaction documents — 269SS/271D common
    "promissory note", "promissory notes",
    "loan agreement", "loan agreements",
    "loan confirmation", "confirmation from lender",
    "lender confirmation", "creditor confirmation",
    "confirmation letter", "confirmation letters",
    "affidavit", "affidavits",
    "sworn affidavit",
    "cash book", "cash books",
    "cash ledger",
    "cash flow statement",
    # Books and ledgers — common ITA judgment phrases
    "books of account", "books of accounts",
    "profit and loss account", "P&L account",
    "balance sheet",
    "purchase ledger", "sales ledger", "party ledger",
    "ledger account", "ledger accounts", "ledger",
    "account books", "journal",
    # Professional / business
    "professional fee receipt", "fee receipt",
    "receipt", "receipts",
    "invoice", "invoices",
    "bill", "bills",
    "cash memo", "payment receipt",
    "voucher", "vouchers",
    # Certificates and declarations
    "chartered accountant certificate", "CA certificate",
    "certificate", "certificates",
    "declaration",
    "no dues certificate",
    # Identity / relationship
    "pan card", "PAN card",
    "aadhaar card", "aadhaar",
    "passport",
    # Gift and family transactions
    "gift deed", "gift letter",
    "will", "intestate",
    "marriage certificate",
    # Property
    "sale deed", "purchase deed",
    "registration certificate",
    "stamp duty receipt",
    # Business registration
    "GST registration", "service tax registration",
    "trade licence", "incorporation certificate",
    # Correspondence
    "letter", "letters",
    "reply", "explanation",
    "written submission",
]

_DOC_NOUN_PATTERN = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(d) for d in sorted(_DOC_NOUNS, key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE
)

# Extended assessee context words — covers actual ITA judgment language
_ASSESSEE_CONTEXT_WORDS = [
    # Standard legal document submission language
    "submitted", "produced", "furnished", "filed", "provided", "adduced",
    "placed on record", "relied upon by assessee", "accepted by tribunal",
    "tribunal accepted", "allowed by tribunal",
    "assessee produced", "assessee submitted", "assessee furnished",
    "assessee filed", "assessee placed",
    "evidence accepted", "document accepted", "relied upon in support",
    # ITA judgment specific phrases
    "in support of his claim", "in support of the claim",
    "assessee has filed", "assessee had filed",
    "assessee has placed", "assessee had placed",
    "assessee explained", "assessee could explain",
    "assessee established", "assessee proved",
    "assessee discharged", "discharged the onus",
    "onus discharged", "onus has been discharged",
    "genuineness established", "genuineness proved",
    "source explained", "source established",
    "identity established", "creditworthiness established",
    # Tribunal verdict phrases
    "tribunal held", "bench held", "we hold",
    "we are satisfied", "we find",
    "addition deleted", "addition set aside", "ground allowed",
    "appeal allowed", "penalty deleted", "penalty cancelled",
    "penalty set aside", "relief granted",
]


def fetch_page_text(url: str, timeout: int = 15) -> str:
    """
    Fetch a web page and return clean body text.
    Results cached in memory for the session.
    Returns empty string on failure.
    """
    if url in _FETCH_CACHE:
        return _FETCH_CACHE[url]

    try:
        import requests
        headers = {
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
            ]),
            "Accept": "text/html,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return ""

        html = resp.text

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            # Remove nav, header, footer, script, style
            for tag in soup(["script", "style", "nav", "header", "footer",
                              "aside", "form", "noscript"]):
                tag.decompose()
            # Try to get main content area
            main = (soup.find("div", id=re.compile(r"content|main|article", re.I)) or
                    soup.find("article") or
                    soup.find("div", class_=re.compile(r"content|main|post", re.I)) or
                    soup.body)
            text = main.get_text(" ", strip=True) if main else soup.get_text(" ", strip=True)
        except Exception:
            # Regex fallback
            text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"&[a-z#0-9]+;", " ", text)

        text = re.sub(r"\s{2,}", " ", text).strip()[:8000]
        _FETCH_CACHE[url] = text
        time.sleep(1.0)   # polite delay
        return text

    except Exception:
        return ""


def mine_evidence_docs(page_text: str, section: str) -> list[dict]:
    """
    Mine a page of judgment / article text for document names that were
    SUBMITTED BY THE ASSESSEE (not by the AO).

    Returns list of:
        { "document_name": str, "context": str, "direction": "assessee" }
    """
    if not page_text:
        return []

    text_lower = page_text.lower()
    found      = []
    seen_docs  = set()

    # Split into sentences for context checking
    sentences = re.split(r"[.;]\s+", page_text)

    for sent in sentences:
        sent_lower = sent.lower()

        # Check if this sentence is about the AO (skip if so)
        if any(ao_w in sent_lower for ao_w in _AO_CONTEXT_WORDS):
            continue

        # Check if assessee context is present
        is_assessee_context = any(w in sent_lower for w in _ASSESSEE_CONTEXT_WORDS)

        # Find doc names in this sentence
        matches = _DOC_NOUN_PATTERN.findall(sent)
        for doc in matches:
            doc_norm = doc.lower().strip()
            if doc_norm in seen_docs:
                continue
            seen_docs.add(doc_norm)

            # Higher confidence if assessee context present
            if is_assessee_context or len(sent) < 200:
                # Take a short context snippet
                ctx = sent.strip()[:200]
                found.append({
                    "document_name": doc.title(),
                    "context":       ctx,
                    "direction":     "assessee",
                    "confidence":    0.9 if is_assessee_context else 0.6,
                })

    # Sort: highest confidence first
    found.sort(key=lambda x: -x["confidence"])
    return found[:20]


def rank_evidence_docs(all_mentions: list[list[dict]]) -> list[dict]:
    """
    Aggregate document mentions across multiple pages.
    Rank by frequency (appears in most pages = most important).
    Returns deduplicated list with frequency count.
    """
    from collections import Counter
    counts: Counter = Counter()
    contexts: dict[str, list[str]] = {}
    confidences: dict[str, float] = {}

    for page_docs in all_mentions:
        for item in page_docs:
            name = item["document_name"].lower().strip()
            counts[name] += 1
            contexts.setdefault(name, [])
            if item.get("context"):
                contexts[name].append(item["context"][:150])
            if name not in confidences or item.get("confidence", 0) > confidences[name]:
                confidences[name] = item.get("confidence", 0.5)

    ranked = []
    for name, count in counts.most_common():
        ranked.append({
            "document_name":   name.title(),
            "frequency":       count,
            "confidence":      confidences.get(name, 0.5),
            "sample_contexts": contexts.get(name, [])[:2],
        })

    return ranked


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_evidence_list(
    sections: list[str],
    ao_order_text: str = "",
    case_facts: str = "",
    progress_cb=None,
    case_id: int = 0,
    case_name: str = "",
    assessment_year: str = "",
    demand_amount: float = 0.0,
) -> list[dict]:
    """
    Build evidence list for all contested sections.
    Procedural sections are auto-skipped with a tagged placeholder.

    Returns list of dicts compatible with add_evidence() in database/queries.py
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    # ── Attempt full RAG pipeline ────────────────────────────────────────────
    try:
        from ai.rag.pipeline  import RAGPipeline
        from ai.rag.models    import CaseQuery
        from ai.rag.embedder  import EmbeddingService

        embedder = EmbeddingService()
        if embedder.is_indexed():
            log("🚀 Using RAG pipeline (hybrid vector + FTS5 + Gemini reranking)...")
            query = CaseQuery(
                case_id         = case_id or 0,
                sections        = [s for s in sections if not _is_procedural(s)],
                client_facts    = case_facts or f"Case under sections {', '.join(sections)}",
                ao_text         = ao_order_text,
                demand_amount   = demand_amount,
                case_name       = case_name,
                assessment_year = assessment_year,
            )
            pipeline = RAGPipeline()
            strategy = pipeline.build(query, progress_cb=log)
            items = _strategy_to_items(strategy)
            # Add procedural placeholders
            items.extend(_procedural_placeholders(sections))
            return items
        else:
            log("⚠️  ChromaDB not indexed yet — using internet search pipeline.")
    except ImportError:
        log("⚠️  chromadb not installed — using internet search pipeline.")
    except Exception as e:
        log(f"⚠️  RAG error ({e}) — using internet search pipeline...")

    # ── Internet-search pipeline ─────────────────────────────────────────────
    all_items = []

    # Extract AO demands from order text
    ao_demanded = []
    if ao_order_text and len(ao_order_text) > 100:
        log("📄 Parsing assessment order for AO-demanded documents...")
        ao_demanded = _extract_ao_demands(ao_order_text)
        log(f"  → {len(ao_demanded)} AO-demanded/rejected item(s) identified")

    # Separate contested vs procedural sections
    contested   = [s for s in sections if not _is_procedural(s)]
    procedural  = [s for s in sections if _is_procedural(s)]

    if procedural:
        log(f"  ℹ️  Procedural sections skipped (no separate evidence needed): "
            f"{', '.join(f'§{s}' for s in procedural)}")

    if not contested:
        log("  ℹ️  No contested substantive sections found — nothing to build.")
        return _procedural_placeholders(sections)

    log(f"\n🔍 Building evidence for {len(contested)} contested section(s): "
        f"{', '.join(f'§{s}' for s in contested)}")

    for section in contested:
        log(f"\n─── §{section} ────────────────────────────")

        # Step 1 — local DB
        db_snippets = _get_db_snippets(section)
        log(f"  ✓ Local DB: {len(db_snippets)} snippet(s)")

        # Step 2 — IK direct scrape
        ik_results = _search_ik(section, log)
        log(f"  ✓ IK direct: {len(ik_results)} case(s)")

        # Step 3 — Internet search + page mining
        mined_docs, web_results = _search_and_mine(section, case_facts, log)
        log(f"  ✓ Internet mined: {len(mined_docs)} distinct document(s) from {len(web_results)} pages")

        # Step 4 — Gemini synthesis
        items = _synthesize(
            section, db_snippets, ik_results, web_results,
            mined_docs, ao_demanded, case_facts, log,
        )
        all_items.extend(items)
        log(f"  ✅ §{section}: {len(items)} evidence item(s) generated")

    # Add procedural placeholders
    all_items.extend(_procedural_placeholders(procedural))

    # Deduplicate by (section, document_name)
    seen = set()
    unique = []
    for item in all_items:
        key = (item["section"], item["document_name"].lower()[:40])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    log(f"\n✅ Evidence build complete: {len(unique)} total item(s) "
        f"({len(contested)} contested + {len(procedural)} procedural sections)")
    return unique


def _procedural_placeholders(sections: list[str]) -> list[dict]:
    """Return placeholder items for procedural sections so coverage checker shows them correctly."""
    return [
        {
            "section":          s,
            "document_name":    f"Procedural section — no separate evidence required",
            "tribunal_verdict": "accepted",
            "accepted_in":      [],
            "rejected_in":      [],
            "rejection_reason": "",
            "acceptance_count": 1,
            "win_boost":        5,
            "mandatory":        False,
            "why_it_matters":   "This is a procedural/mechanism section, not a substantive ground of addition.",
            "how_to_obtain":    "No action needed — procedural compliance is handled in the submission narrative.",
            "source":           "procedural",
            "status":           "available",   # always green in coverage checker
        }
        for s in sections
        if _is_procedural(s)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Source 1 — AO assessment order extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_ao_demands(text: str) -> list[str]:
    """Extract documents the AO asked for, relied on, or noted as missing."""
    patterns = [
        r"(?:asked|called for|required|summoned|directed to produce|sought)[^.]{0,80}"
        r"(?:document|statement|ledger|book|return|certificate|affidavit|confirmation|details)[^.]{0,60}\.",
        r"(?:no|not|without|absence of|failed to produce|not produced|not furnished)[^.]{0,60}"
        r"(?:document|statement|ledger|book|return|certificate|affidavit|confirmation|evidence)[^.]{0,60}\.",
        r"(?:assessee (?:could not|did not|was unable to) (?:produce|furnish|submit|explain))[^.]{0,100}\.",
        r"(?:relied on|based on|supported by|as evident from)[^.]{0,80}"
        r"(?:document|statement|ledger|return|certificate)[^.]{0,60}\.",
    ]
    demands = []
    for pat in patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        demands.extend(matches[:5])
    return demands[:20]


# ─────────────────────────────────────────────────────────────────────────────
# Source 2 — Local ITAT DB
# ─────────────────────────────────────────────────────────────────────────────

def _get_db_snippets(section: str) -> list[str]:
    try:
        from database.queries import get_citations_by_section
        cits = get_citations_by_section(section, limit=12)
        snippets = []
        for c in cits:
            if c.get("key_ratio"):
                snippets.append(c["key_ratio"])
            if c.get("facts_summary"):
                snippets.append(c["facts_summary"])
        return snippets
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Source 3 — Indian Kanoon direct scrape
# ─────────────────────────────────────────────────────────────────────────────

def _search_ik(section: str, log) -> list[dict]:
    """
    Search IK directly (no API key), fetch full text of top results.
    Returns list of {title, headline, full_text, url, tid}
    """
    results    = []
    seen_tids  = set()
    queries_list = _IK_QUERIES.get(section, _default_ik_queries(section))

    try:
        from ai.indian_kanoon import search_cases, clean_html, get_doc

        for q in queries_list[:3]:
            try:
                raw  = search_cases(q)
                docs = raw.get("docs", [])[:6]

                for doc in docs:
                    tid = str(doc.get("tid", ""))
                    if not tid or tid in seen_tids:
                        continue
                    seen_tids.add(tid)

                    title    = clean_html(doc.get("title", ""))
                    headline = clean_html(doc.get("headline", ""))

                    # Fetch full judgment text for top results
                    full_text = ""
                    if len(results) < 10:
                        try:
                            full_data = get_doc(tid)
                            full_text = full_data.get("doc", "")[:4000]
                        except Exception:
                            pass

                    results.append({
                        "title":     title,
                        "headline":  headline,
                        "full_text": full_text,
                        "url":       f"https://indiankanoon.org/doc/{tid}/",
                        "tid":       tid,
                        "source":    "indian_kanoon",
                    })

            except Exception:
                pass

    except Exception:
        pass

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Source 4 — Internet search + page text mining
# ─────────────────────────────────────────────────────────────────────────────

def _search_and_mine(section: str, case_facts: str,
                     log) -> tuple[list[dict], list[dict]]:
    """
    1. Run DDG + itatonline + taxguru + abcaus searches for this section
    2. Fetch top result pages
    3. Mine each page for document mentions (assessee-side only)
    4. Aggregate and rank by frequency across pages

    Returns (ranked_docs, web_results_for_synthesis)
    """
    queries = [
        f"{section} ITAT documents evidence accepted",
        f"{section} penalty deleted documents submitted",
        f"section {section} income tax tribunal evidence",
    ]
    if case_facts:
        # Add case-specific keywords
        kws = [w for w in case_facts.split() if len(w) > 5][:3]
        if kws:
            queries.append(f"{section} {' '.join(kws)} evidence")

    all_urls    = []
    web_results = []   # for Gemini synthesis context

    # ── DDG search ────────────────────────────────────────────────────────────
    try:
        from utils.web_search import search_duckduckgo, score_result
        ddg_results = search_duckduckgo(queries[:3], [section], max_per_query=8)

        # Take top 6 by score
        for r in sorted(ddg_results, key=lambda x: x["score"], reverse=True)[:6]:
            url = r.get("url", "")
            if url and url not in all_urls:
                all_urls.append(url)
                web_results.append({
                    "title":    r.get("title", ""),
                    "headline": r.get("snippet", ""),
                    "source":   r.get("source", "ddg"),
                    "url":      url,
                })
    except Exception as e:
        log(f"    ⚠️ DDG search error: {e}")

    # ── itatonline direct search ──────────────────────────────────────────────
    try:
        from ai.live_search import search_itatonline
        ito = search_itatonline(queries[:2], [section])
        for r in ito[:4]:
            url = r.get("url", "")
            if url and url not in all_urls:
                all_urls.append(url)
                web_results.append({
                    "title":    r.get("title", ""),
                    "headline": r.get("headline", ""),
                    "source":   "itatonline",
                    "url":      url,
                })
    except Exception:
        pass

    # ── taxguru RSS search ────────────────────────────────────────────────────
    try:
        from ai.live_search import search_taxguru
        tg = search_taxguru(queries[:2], [section])
        for r in tg[:4]:
            url = r.get("url", "")
            if url and url not in all_urls:
                all_urls.append(url)
                web_results.append({
                    "title":    r.get("title", ""),
                    "headline": r.get("headline", ""),
                    "source":   "taxguru",
                    "url":      url,
                })
    except Exception:
        pass

    # ── abcaus.in search via DDG site: ────────────────────────────────────────
    try:
        from ddgs import DDGS
        abcaus_q = f"site:abcaus.in section {section} ITAT evidence documents"
        with DDGS() as ddgs:
            hits = list(ddgs.text(abcaus_q, max_results=5))
        for r in hits:
            url = r.get("href", "")
            if url and url not in all_urls:
                all_urls.append(url)
                web_results.append({
                    "title":    r.get("title", ""),
                    "headline": r.get("body", "")[:200],
                    "source":   "abcaus",
                    "url":      url,
                })
    except Exception:
        pass

    if not all_urls:
        return [], web_results

    # ── Fetch pages + mine for document mentions ──────────────────────────────
    all_page_mentions: list[list[dict]] = []
    pages_fetched = 0

    for url in all_urls[:8]:   # cap at 8 page fetches per section
        log(f"    📄 Mining: {url[:80]}...")
        page_text = fetch_page_text(url, timeout=12)
        if not page_text:
            log(f"       ↳ Failed to fetch")
            continue

        mentions = mine_evidence_docs(page_text, section)
        if mentions:
            all_page_mentions.append(mentions)
            pages_fetched += 1
            log(f"       ↳ {len(mentions)} doc mention(s) found")

            # Enrich web_result with page body for synthesis
            for wr in web_results:
                if wr.get("url") == url:
                    wr["page_text"] = page_text[:1500]
                    break

    # Aggregate and rank
    ranked = rank_evidence_docs(all_page_mentions) if all_page_mentions else []
    log(f"    📊 {len(ranked)} unique doc types mined from {pages_fetched} page(s)")

    return ranked, web_results


# ─────────────────────────────────────────────────────────────────────────────
# Source 5 — Gemini synthesis
# ─────────────────────────────────────────────────────────────────────────────

_SYNTHESIS_SYSTEM = """You are an Indian tax tribunal evidence analyst.
Your ONLY job is to extract documents explicitly mentioned in the tribunal cases provided.
STRICT RULE: Do NOT suggest any document not mentioned in the provided case excerpts.
Do NOT use your training knowledge to add documents. Extract only. Return valid JSON only."""


def _synthesize(
    section: str,
    db_snippets: list[str],
    ik_results: list[dict],
    web_results: list[dict],
    mined_docs: list[dict],
    ao_demanded: list[str],
    case_facts: str,
    log,
) -> list[dict]:
    """
    Synthesize all gathered sources into a structured evidence list via Gemini.
    If Gemini not available or returns nothing, fall back to mined_docs directly.
    """
    parts = []

    if ao_demanded:
        parts.append(
            "=== ASSESSMENT ORDER — AO ASKED FOR / RELIED ON / REJECTED ===\n"
            + "\n".join(f"[AO-ORDER] {d}" for d in ao_demanded[:10])
        )

    if mined_docs:
        mined_lines = "\n".join(
            f"[MINED-{i+1}] {d['document_name']} "
            f"(appeared in {d['frequency']} page(s), context: {d.get('sample_contexts', [''])[0][:100]})"
            for i, d in enumerate(mined_docs[:15])
        )
        parts.append(
            "=== DOCUMENTS FOUND IN REAL CASE PAGES (internet mined) ===\n"
            + mined_lines
        )

    if db_snippets:
        parts.append(
            "=== VERIFIED ITAT PRECEDENTS (local database) ===\n"
            + "\n".join(f"[ITAT-DB] {s}" for s in db_snippets[:10])
        )

    if ik_results:
        ik_lines = []
        for r in ik_results[:10]:
            body = r.get("full_text") or r.get("headline", "")
            ik_lines.append(f"[IK] {r['title']}\n{body[:600]}")
        parts.append("=== INDIAN KANOON LIVE CASES ===\n" + "\n\n".join(ik_lines))

    if web_results:
        web_lines = []
        for r in web_results[:8]:
            page_text = r.get("page_text", "")
            snippet   = page_text or r.get("headline", "")
            web_lines.append(
                f"[{r['source'].upper()}] {r['title']}: {snippet[:300]}"
            )
        parts.append("=== WEB SOURCES (page text mined) ===\n" + "\n".join(web_lines))

    # If literally nothing was found, return fallback based on mined_docs
    if not parts:
        log("  ⚠ No sources available — returning mined doc fallback")
        return _mined_to_items(section, mined_docs)

    if case_facts:
        parts.append(f"=== CASE CONTEXT ===\n{case_facts[:300]}")

    case_text = "\n\n".join(parts)

    prompt = f"""IT Act Section {section} — extract ASSESSEE's defence documents from the sources below.

CASE SOURCES:
{case_text}

TASK: Read every excerpt above. For each DOCUMENT that an ASSESSEE (taxpayer) submitted / produced /
furnished as evidence in their DEFENCE, extract it.

CRITICAL RULES:
1. ONLY extract documents submitted BY THE ASSESSEE (taxpayer) — NOT documents issued by the AO/department.
   ✅ Include: bank statements, receipts, affidavits, ledgers, ITRs, certificates — submitted by assessee
   ❌ Exclude: assessment order, demand notice, penalty notice, show cause notice — these are AO documents
2. ONLY extract documents that appear in the provided sources.
3. If sources say the tribunal ACCEPTED a document → tribunal_verdict = "accepted"
4. If the document was REJECTED or found insufficient → tribunal_verdict = "rejected"
5. Sort by acceptance_count descending.

Return ONLY a JSON array. Each object must have exactly these keys:
- "document_name": string — exact name of the document
- "tribunal_verdict": "accepted" or "rejected"
- "accepted_in": array of strings — case names where this was accepted
- "rejected_in": array of strings — case names where this was rejected
- "rejection_reason": string — exact tribunal reason (empty string if accepted)
- "acceptance_count": integer — number of cases/sources where this document appears
- "mandatory": boolean — true if case was decided against assessee due to absence of this doc
- "why_it_matters": string — what legal element this document proved
- "how_to_obtain": string — practical one sentence on sourcing this document

Return the JSON array only. No other text."""

    try:
        from ai.gemini_client import call_gemini
        raw = call_gemini(
            _SYNTHESIS_SYSTEM,
            prompt,
            temperature=0.05,
            max_tokens=4096,
            redact=False,
        )

        # Check for Gemini error response
        if not raw or raw.startswith("[ERROR]"):
            log(f"  ⚠ Gemini full synthesis failed ({raw[:60]}) — trying mini synthesis...")
            mini = _mini_synthesis(section, ik_results, db_snippets, mined_docs, log)
            if mini:
                return mini
            log("  ⚠ Mini synthesis also failed — using direct fallback")
            return _combined_fallback(section, mined_docs, ik_results, db_snippets)

        clean = raw.strip()
        if "```" in clean:
            clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()

        # Find JSON array — must start with [{ not [ERROR or other text
        start = clean.find("[{")   # valid JSON array starts with [{
        if start == -1:
            start = clean.find("[")
        end   = clean.rfind("]") + 1
        if start < 0 or end <= start:
            log("  ⚠ No JSON array in Gemini response — using mined_docs fallback")
            return _mined_to_items(section, mined_docs)

        clean  = clean[start:end]
        parsed = json.loads(clean)
        items  = []

        for obj in parsed:
            if not isinstance(obj, dict) or "document_name" not in obj:
                continue

            doc_name = str(obj.get("document_name", "")).strip()
            if not doc_name:
                continue

            # Double-check: skip if it looks like an AO document
            if _is_ao_document(doc_name):
                continue

            verdict          = str(obj.get("tribunal_verdict", "accepted")).lower()
            acceptance_count = max(0, int(obj.get("acceptance_count", 1)))
            win_boost        = min(30, max(5, acceptance_count * 5))

            items.append({
                "section":          section,
                "document_name":    doc_name,
                "tribunal_verdict": verdict,
                "accepted_in":      obj.get("accepted_in", []),
                "rejected_in":      obj.get("rejected_in", []),
                "rejection_reason": str(obj.get("rejection_reason", "")),
                "acceptance_count": acceptance_count,
                "win_boost":        win_boost,
                "mandatory":        bool(obj.get("mandatory", False)),
                "why_it_matters":   str(obj.get("why_it_matters", "")),
                "how_to_obtain":    str(obj.get("how_to_obtain", "")),
                "source":           "internet-mined",
            })

        # Sort: accepted + mandatory first, then by acceptance_count
        items.sort(key=lambda x: (
            0 if x["tribunal_verdict"] == "accepted" else 1,
            -int(x["mandatory"]),
            -x["acceptance_count"],
        ))

        # If Gemini returned nothing or filtered everything, fallback to mined
        if not items:
            log("  ⚠ Gemini returned 0 valid items — using combined fallback")
            return _combined_fallback(section, mined_docs, ik_results, db_snippets)

        return items

    except Exception as e:
        log(f"  ⚠ Synthesis error: {e} — using combined fallback")
        return _combined_fallback(section, mined_docs, ik_results, db_snippets)


def _is_ao_document(name: str) -> bool:
    """Return True if the document name looks like an AO-issued document."""
    ao_docs = [
        "assessment order", "demand notice", "penalty notice",
        "show cause notice", "notice u/s", "order u/s",
        "intimation", "rectification order", "revision order",
        "search warrant", "summons",
    ]
    name_lower = name.lower()
    return any(d in name_lower for d in ao_docs)


def _mini_synthesis(section: str, ik_results: list[dict],
                    db_snippets: list[str], mined_docs: list[dict],
                    log) -> list[dict]:
    """
    Compact Gemini call using only headlines + section number.
    Much smaller token footprint — works within tight quota.
    Falls back gracefully if Gemini still unavailable.
    """
    try:
        from ai.gemini_client import call_gemini

        # Build compact context — headlines only
        hl_lines = []
        for r in ik_results[:8]:
            hl = r.get("headline", "")
            if hl and len(hl) > 30:
                hl_lines.append(f"• {hl[:200]}")

        db_lines = [f"• {s[:180]}" for s in db_snippets[:5] if s]
        mined_names = [d["document_name"] for d in mined_docs[:6]]

        context = ""
        if hl_lines:
            context += "IK CASE SNIPPETS:\n" + "\n".join(hl_lines[:6]) + "\n\n"
        if db_lines:
            context += "ITAT DB PRECEDENTS:\n" + "\n".join(db_lines) + "\n\n"
        if mined_names:
            context += "DOCUMENTS FOUND IN PAGES: " + ", ".join(mined_names) + "\n"

        if not context.strip():
            return []

        mini_prompt = f"""Section {section} of Income Tax Act.

{context}
List the 5-8 most important documents an assessee must produce to defend against a §{section} addition/penalty.
Focus on documents SUBMITTED BY THE ASSESSEE, not AO-issued orders.

Return ONLY a JSON array like:
[{{"document_name":"Bank Statement","mandatory":true,"why_it_matters":"Proves source of funds","how_to_obtain":"From bank"}}]
No other text."""

        raw = call_gemini(
            "You are an Indian tax lawyer. Return only JSON arrays.",
            mini_prompt,
            temperature=0.1,
            max_tokens=1024,
            redact=False,
        )

        if not raw or raw.startswith("[ERROR]"):
            return []

        clean = raw.strip()
        if "```" in clean:
            clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()

        start = clean.find("[{")
        if start == -1:
            start = clean.find("[")
        end = clean.rfind("]") + 1
        if start < 0 or end <= start:
            return []

        parsed = json.loads(clean[start:end])
        items  = []
        for obj in parsed:
            if not isinstance(obj, dict) or "document_name" not in obj:
                continue
            name = str(obj.get("document_name", "")).strip()
            if not name or _is_ao_document(name):
                continue
            items.append({
                "section":          section,
                "document_name":    name,
                "tribunal_verdict": "accepted",
                "accepted_in":      [],
                "rejected_in":      [],
                "rejection_reason": "",
                "acceptance_count": 2,
                "win_boost":        10,
                "mandatory":        bool(obj.get("mandatory", False)),
                "why_it_matters":   str(obj.get("why_it_matters", "")),
                "how_to_obtain":    str(obj.get("how_to_obtain", "Collect from client")),
                "source":           "mini-synthesis",
            })
        return items

    except Exception as e:
        log(f"  ⚠ Mini synthesis error: {e}")
        return []


def _combined_fallback(section: str, mined_docs: list[dict],
                       ik_results: list[dict],
                       db_snippets: list[str]) -> list[dict]:
    """
    Fallback when Gemini is unavailable (quota / error).
    Mines IK headlines + full text + DB snippets for document mentions,
    then merges with web-mined docs and ranks by frequency.

    Strategy:
    1. IK headlines — condensed judgment summaries, best signal-to-noise
    2. IK full text — works for shorter judgments
    3. DB snippets — verified precedent text
    4. Web-mined docs — already ranked
    """
    all_page_mentions: list[list[dict]] = []

    # ── 1. Mine IK headlines (condensed summaries — best source) ──────────────
    all_headlines = " ".join(
        r.get("headline", "") for r in ik_results if r.get("headline")
    )
    if all_headlines:
        hl_mentions = mine_evidence_docs(all_headlines, section)
        if hl_mentions:
            # Give headlines double weight by appending twice
            all_page_mentions.append(hl_mentions)
            all_page_mentions.append(hl_mentions)

    # ── 2. Mine IK full text (shorter judgments only) ──────────────────────────
    for r in ik_results[:6]:
        text = r.get("full_text", "")
        if not text or len(text) < 200:
            continue
        # Skip headers (first 500 chars are usually party names / ITA numbers)
        # Take middle portion which contains substantive discussion
        if len(text) > 1500:
            # Use last 60% of text — evidence discussion is in the decision portion
            start_idx = int(len(text) * 0.35)
            text = text[start_idx:]
        mentions = mine_evidence_docs(text, section)
        if mentions:
            all_page_mentions.append(mentions)

    # ── 3. Mine DB snippets ────────────────────────────────────────────────────
    if db_snippets:
        combined_db = " ".join(db_snippets[:10])
        db_mentions = mine_evidence_docs(combined_db, section)
        if db_mentions:
            all_page_mentions.append(db_mentions)

    # ── 4. Include web-mined docs ──────────────────────────────────────────────
    if mined_docs:
        web_mentions = [
            {"document_name": d["document_name"],
             "confidence":    d.get("confidence", 0.5),
             "context":       d.get("sample_contexts", [""])[0]}
            for d in mined_docs
        ]
        all_page_mentions.append(web_mentions)

    if not all_page_mentions:
        return []

    ranked = rank_evidence_docs(all_page_mentions)
    return _mined_to_items(section, ranked)


def _mined_to_items(section: str, mined_docs: list[dict]) -> list[dict]:
    """Convert raw mined_docs to evidence items without Gemini."""
    items = []
    for doc in mined_docs[:12]:
        name = doc["document_name"]
        # Skip generic single-word results and AO documents
        if _is_ao_document(name):
            continue
        if len(name.split()) < 2 and name.lower() not in {
            "affidavit", "invoice", "receipt", "ledger", "certificate",
            "correspondence", "itr",
        }:
            continue   # too generic — skip single-word matches

        freq = doc.get("frequency", 1)
        ctx  = doc.get("sample_contexts", [""])[0]

        items.append({
            "section":          section,
            "document_name":    name,
            "tribunal_verdict": "accepted",
            "accepted_in":      [],
            "rejected_in":      [],
            "rejection_reason": "",
            "acceptance_count": freq,
            "win_boost":        min(25, freq * 5),
            "mandatory":        freq >= 3,
            "why_it_matters":   (f"Found in {freq} case page(s) — {ctx[:100]}"
                                  if ctx else f"Found in {freq} case source(s) for §{section}"),
            "how_to_obtain":    "Collect from client records",
            "source":           "internet-mined",
        })
    return items


# ─────────────────────────────────────────────────────────────────────────────
# RAG CaseStrategy → flat item list (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def _strategy_to_items(strategy) -> list[dict]:
    """Convert a CaseStrategy (from RAGPipeline) into flat evidence item list."""
    seen:  set   = set()
    items: list  = []

    for arg in strategy.arguments:
        section = arg.section or (
            strategy.query.sections[0] if strategy.query.sections else ""
        )
        for doc in arg.documents:
            key = doc.name.lower()[:50]
            if key in seen:
                continue
            seen.add(key)

            has_rejection = bool(doc.rejected_in or doc.rejection_reason)
            verdict       = "rejected" if has_rejection else "accepted"

            items.append({
                "section":          section,
                "document_name":    doc.name,
                "win_boost":        doc.win_boost,
                "mandatory":        doc.mandatory,
                "tribunal_verdict": verdict,
                "rejection_reason": doc.rejection_reason,
                "accepted_in":      doc.accepted_in,
                "rejected_in":      doc.rejected_in,
                "acceptance_count": doc.acceptance_count,
                "why_it_matters":   doc.why_it_matters,
                "how_to_obtain":    doc.how_to_obtain,
                "source":           "rag-pipeline",
            })

    items.sort(key=lambda x: (
        0 if x["tribunal_verdict"] == "accepted" else 1,
        -int(x["mandatory"]),
        -x["acceptance_count"],
    ))
    return items
