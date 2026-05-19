"""
ITAT Cause List Fetcher & Parser.

The ITAT publishes daily cause lists as PDFs on its public website —
no CAPTCHA, no login required.

What this module does:
  1. Fetch the cause list PDF for a given bench (Delhi, Mumbai, Chennai etc.)
  2. Parse case numbers, appellant names, sections from the PDF
  3. Cross-reference against the local DB to highlight your cases
  4. Return a structured list of today's hearings

Usage:
    from ai.itat_cause_list import get_cause_list, fetch_all_benches

    hearings = get_cause_list(bench="Delhi")
    # Returns list of dicts: case_number, appellant, respondent, sections, bench

Bench codes:
    Delhi, Mumbai, Chennai, Kolkata, Ahmedabad, Hyderabad,
    Bangalore, Pune, Chandigarh, Jaipur, Lucknow
"""

import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Known ITAT bench cause list URLs ──────────────────────────────────────────
# ITAT cause lists are publicly available at itat.gov.in
BENCH_URLS = {
    "Delhi":      "https://itat.gov.in/causelist/delhi_causelist.pdf",
    "Mumbai":     "https://itat.gov.in/causelist/mumbai_causelist.pdf",
    "Chennai":    "https://itat.gov.in/causelist/chennai_causelist.pdf",
    "Kolkata":    "https://itat.gov.in/causelist/kolkata_causelist.pdf",
    "Ahmedabad":  "https://itat.gov.in/causelist/ahmedabad_causelist.pdf",
    "Hyderabad":  "https://itat.gov.in/causelist/hyderabad_causelist.pdf",
    "Bangalore":  "https://itat.gov.in/causelist/bangalore_causelist.pdf",
    "Pune":       "https://itat.gov.in/causelist/pune_causelist.pdf",
    "Chandigarh": "https://itat.gov.in/causelist/chandigarh_causelist.pdf",
    "Jaipur":     "https://itat.gov.in/causelist/jaipur_causelist.pdf",
    "Lucknow":    "https://itat.gov.in/causelist/lucknow_causelist.pdf",
}

# Alternative: direct archive page (use when direct PDF URL fails)
BENCH_ARCHIVE_PAGE = "https://itat.gov.in/WebFiles/cause_list/"


def get_cause_list(bench: str = "Delhi",
                   progress_cb=None) -> list[dict]:
    """
    Fetch and parse the ITAT cause list for a given bench.

    Returns list of hearing dicts:
        {
          "sno":        serial number
          "case_no":    ITA No./MA No./CO No.
          "appellant":  appellant name
          "respondent": respondent name
          "ay":         assessment year
          "sections":   list of IT Act sections detected in the matter
          "bench":      bench name
          "hearing_type": "regular" / "part-heard" / "fresh"
        }

    Returns empty list if cause list unavailable (PDF not uploaded yet).
    """
    pdf_url = BENCH_URLS.get(bench)
    if not pdf_url:
        if progress_cb:
            progress_cb(f"  ⚠️ Unknown bench: {bench}")
        return []

    if progress_cb:
        progress_cb(f"  📋 Fetching ITAT {bench} cause list...")

    # ── Download PDF ────────────────────────────────────────────────────────
    pdf_bytes = _download_pdf(pdf_url, progress_cb)
    if not pdf_bytes:
        # Try IK-based approach as fallback
        if progress_cb:
            progress_cb(f"  ℹ️ Direct PDF unavailable — using IK fallback for {bench}")
        return _ik_fallback(bench, progress_cb)

    # ── Parse PDF ────────────────────────────────────────────────────────────
    hearings = _parse_cause_list_pdf(pdf_bytes, bench)

    if progress_cb:
        progress_cb(f"  ✅ ITAT {bench}: {len(hearings)} cases in today's cause list")

    return hearings


def _download_pdf(url: str, progress_cb=None) -> bytes | None:
    """Download PDF bytes from URL. Returns None on failure."""
    try:
        import requests
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 Chrome/122.0"},
            timeout=20,
            stream=True,
        )
        if r.status_code == 200 and "pdf" in r.headers.get("Content-Type", "").lower():
            return r.content
        # Try without checking content-type (some servers mis-report)
        if r.status_code == 200 and len(r.content) > 1000:
            # Check first bytes for PDF magic number
            if r.content[:4] == b"%PDF":
                return r.content
    except Exception as e:
        if progress_cb:
            progress_cb(f"  ⚠️ PDF download failed: {e}")
    return None


def _parse_cause_list_pdf(pdf_bytes: bytes, bench: str) -> list[dict]:
    """
    Parse ITAT cause list PDF into structured hearing records.

    ITAT cause lists typically have columns like:
        S.No | Case Number | Appellant vs Respondent | AY | Member(s)

    Handles both pdfplumber and PyMuPDF parsers.
    """
    text = _extract_pdf_text(pdf_bytes)
    if not text:
        return []

    hearings = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Pattern: serial number followed by ITA/MA/CO/IT number
    case_pattern = re.compile(
        r'^(\d{1,4})\s+'               # S.No
        r'((?:ITA|IT A|M\.?A\.?|CO|SA|RA|MP|OA|WTA)\s*[No.]*\s*[\d/\-]+/\w+/\d{4})'  # Case No
        r'(?:\s+(.+?)\s+(?:vs?\.?|Vs?\.?|V/s)\s+(.+?))?'  # Appellant vs Respondent
        r'(?:\s+((?:\d{4}-\d{2}|\d{4})))?$',  # AY
        re.IGNORECASE
    )

    # Simpler fallback: just extract case numbers
    simple_pattern = re.compile(
        r'\b(ITA|IT A|MA|CO)\s*[No.]*\s*(\d+(?:\s*&\s*\d+)*)\s*/\s*([A-Z]{3,6})\s*/\s*(\d{4})\b',
        re.IGNORECASE
    )

    i = 0
    while i < len(lines):
        line = lines[i]

        m = case_pattern.match(line)
        if m:
            sno        = m.group(1)
            case_no    = m.group(2).strip()
            appellant  = (m.group(3) or "").strip()
            respondent = (m.group(4) or "").strip()
            ay_str     = (m.group(5) or "").strip()

            # Look ahead for multi-line party names
            if not appellant and i + 1 < len(lines):
                next_line = lines[i + 1]
                vs_m = re.search(r'(.+?)\s+[Vv]/?[Ss]\.?\s+(.+)', next_line)
                if vs_m:
                    appellant  = vs_m.group(1).strip()
                    respondent = vs_m.group(2).strip()
                    i += 1

            sections = _extract_sections_from_text(line + " " + appellant + " " + respondent)

            hearings.append({
                "sno":          sno,
                "case_no":      case_no,
                "appellant":    appellant[:80],
                "respondent":   respondent[:80],
                "ay":           ay_str,
                "sections":     sections,
                "bench":        bench,
                "hearing_type": _hearing_type(line),
            })

        elif simple_pattern.search(line):
            sm = simple_pattern.search(line)
            case_no = sm.group(0)
            # Try to extract party names from same/adjacent lines
            vs_m = re.search(r'(.{5,60})\s+[Vv]/?[Ss]\.?\s+(.{5,60})', line)
            appellant  = vs_m.group(1).strip() if vs_m else ""
            respondent = vs_m.group(2).strip() if vs_m else ""

            hearings.append({
                "sno":          str(len(hearings) + 1),
                "case_no":      case_no,
                "appellant":    appellant[:80],
                "respondent":   respondent[:80],
                "ay":           "",
                "sections":     _extract_sections_from_text(line),
                "bench":        bench,
                "hearing_type": _hearing_type(line),
            })

        i += 1

    return hearings


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber or PyMuPDF."""
    # Try pdfplumber first (better table extraction)
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages[:20]:   # max 20 pages
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n".join(pages)
    except Exception:
        pass

    # Fallback: PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n".join(pages)
    except Exception:
        pass

    return ""


def _extract_sections_from_text(text: str) -> list[str]:
    """Extract IT Act section numbers mentioned in a cause list line."""
    pattern = re.compile(
        r"\b(269SS|269T|269ST|271D|271E|273B|68|69[ACD]?|40A\(3\)|14A|"
        r"153A|153C|148A?|147|263|56\(2\)\([vx]+\)|270A|271\(1\)\(c\)|"
        r"92[CA]?|44AD|43B|40\(a\)\(ia\)|80P|115BBE|132)\b",
        re.IGNORECASE
    )
    found = list(dict.fromkeys(m.group().upper() for m in pattern.finditer(text)))
    return found


def _hearing_type(line: str) -> str:
    """Detect if this is a fresh, part-heard, or regular hearing."""
    l = line.lower()
    if "part heard" in l or "p/h" in l or "ph" in l:
        return "part-heard"
    if "fresh" in l:
        return "fresh"
    return "regular"


def _ik_fallback(bench: str, progress_cb=None) -> list[dict]:
    """
    When direct PDF download fails, use Indian Kanoon to find recent
    ITAT orders from the given bench as a proxy for activity.
    """
    try:
        from ai.indian_kanoon import search_cases, clean_html
        import config

        if not config.INDIAN_KANOON_API_KEY:
            return []

        query  = f"Income Tax Appellate Tribunal {bench} 2025"
        result = search_cases(query)
        docs   = result.get("docs", [])[:10]

        hearings = []
        for doc in docs:
            title = clean_html(doc.get("title", ""))
            src   = doc.get("docsource", "")
            tid   = str(doc.get("tid", ""))
            date  = doc.get("publishdate", "")
            if "itat" in src.lower() or "appellate" in src.lower():
                hearings.append({
                    "sno":          str(len(hearings) + 1),
                    "case_no":      title[:60],
                    "appellant":    "",
                    "respondent":   "",
                    "ay":           "",
                    "sections":     [],
                    "bench":        bench,
                    "hearing_type": "ik_result",
                    "url":          f"https://indiankanoon.org/doc/{tid}/",
                    "date":         date,
                })

        if progress_cb and hearings:
            progress_cb(f"  ✅ IK fallback: {len(hearings)} recent ITAT {bench} orders")
        return hearings

    except Exception:
        return []


def cross_reference_with_db(hearings: list[dict]) -> list[dict]:
    """
    Check which hearings in the cause list match cases in the local DB.
    Adds 'matched_case_id' and 'matched_case_name' to matching hearings.
    """
    from database.init_db import get_connection

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT id, case_name, assessee_pan FROM cases WHERE status = 'active'")
    db_cases = [dict(r) for r in cur.fetchall()]
    conn.close()

    for hearing in hearings:
        hearing["matched_case_id"]   = None
        hearing["matched_case_name"] = None

        appellant = hearing.get("appellant", "").lower()
        respondent = hearing.get("respondent", "").lower()

        for case in db_cases:
            name = case["case_name"].lower()
            pan  = (case.get("assessee_pan") or "").lower()

            # Match by PAN (most reliable)
            if pan and pan in (appellant + " " + respondent):
                hearing["matched_case_id"]   = case["id"]
                hearing["matched_case_name"] = case["case_name"]
                break

            # Match by name (fuzzy — first 15 chars)
            name_short = name[:15]
            if name_short and (name_short in appellant or name_short in respondent):
                hearing["matched_case_id"]   = case["id"]
                hearing["matched_case_name"] = case["case_name"]
                break

    return hearings


def fetch_all_benches(benches: list[str] = None,
                      progress_cb=None) -> dict[str, list]:
    """
    Fetch cause lists for multiple benches in sequence.

    Args:
        benches — list of bench names (default: Delhi + Mumbai + Chennai)
        progress_cb — progress callback

    Returns dict: {bench_name: [hearing_dict, ...]}
    """
    if not benches:
        benches = ["Delhi", "Mumbai", "Chennai"]

    results = {}
    for bench in benches:
        results[bench] = get_cause_list(bench, progress_cb=progress_cb)

    total = sum(len(v) for v in results.values())
    if progress_cb:
        progress_cb(f"  ✅ All benches fetched: {total} total hearings")

    return results
