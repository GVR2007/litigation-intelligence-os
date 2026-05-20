"""
Two-stage AO order case fact extractor — production grade.

Stage 1 — Structure detection
    Indian AO orders follow a consistent format:
      Brief Facts → Assessee's Submissions → AO's Findings → Additions → Demand
    We detect each segment using keyword scoring on paragraphs.
    No LLM needed for this stage — pure heuristics.

Stage 2 — Targeted LLM extraction
    Only the relevant segments (not the full 80-page order) are sent to OpenRouter.
    Typically 1,500–4,000 tokens instead of 40,000+.
    Returns structured JSON with case_facts, ao_allegations, additions, etc.

Cross-validation
    Regex independently extracts additions (section + amount).
    If LLM additions are empty or differ, regex fills the gap.
"""

from __future__ import annotations
import re
import json
from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Segment keyword tables
# ─────────────────────────────────────────────────────────────────────────────

# Each segment type maps to a list of (keyword, weight) tuples.
# Weight > 1 for strong heading-level signals.
_SEGMENT_WEIGHTS: dict[str, list[tuple[str, int]]] = {

    "brief_facts": [
        ("brief facts of the case", 5),
        ("brief facts", 4),
        ("facts of the case", 4),
        ("the assessee is engaged", 3),
        ("the assessee is a", 3),
        ("the assessee carries on", 3),
        ("the case was selected for scrutiny", 3),
        ("the return of income was filed", 2),
        ("filed return of income", 2),
        ("the assessee filed", 2),
        ("during the year under consideration", 2),
        ("background of the case", 3),
        ("the assessee is an individual", 3),
        ("assessee is a firm", 3),
        ("assessee is a company", 3),
    ],

    "assessee_submissions": [
        ("in response to the notice", 4),
        ("the assessee submitted", 4),
        ("the assessee explained", 4),
        ("the assessee's reply", 4),
        ("the assessee has submitted", 4),
        ("reply was filed by the assessee", 4),
        ("in reply, the assessee", 4),
        ("in his reply", 3),
        ("in her reply", 3),
        ("assessee contended", 3),
        ("the assessee stated", 3),
        ("written submissions", 3),
        ("the assessee could not", 3),
        ("the assessee failed to", 3),
        ("no reply was filed", 3),
        ("the assessee produced", 3),
        ("the assessee furnished", 3),
    ],

    "ao_findings": [
        ("on examination of the facts", 4),
        ("the ao observed", 4),
        ("the assessing officer observed", 4),
        ("the assessing officer examined", 4),
        ("i am not satisfied", 4),
        ("i am of the view", 4),
        ("after careful consideration", 4),
        ("in view of the above", 3),
        ("the explanation is not satisfactory", 4),
        ("the explanation offered", 3),
        ("the reply is not satisfactory", 4),
        ("having considered the submissions", 3),
        ("the ao held", 4),
        ("i do not find any merit", 4),
        ("i hold that", 3),
        ("the ao therefore", 3),
        ("accordingly, i am satisfied", 3),
    ],

    "additions": [
        ("accordingly, an addition of", 5),
        ("i therefore make an addition", 5),
        ("i hereby make an addition", 5),
        ("addition of rs.", 5),
        ("addition of rs ", 5),
        ("addition of ₹", 5),
        ("made an addition", 4),
        ("the addition is confirmed", 4),
        ("addition is sustained", 4),
        ("penalty is levied", 4),
        ("penalty is imposed", 4),
        ("i levy a penalty", 5),
        ("penalty under section", 4),
        ("disallowance of rs.", 4),
        ("disallowance of rs ", 4),
        ("disallowance under section", 4),
        ("the income is assessed at", 3),
        ("total addition", 4),
        ("grounds of addition", 4),
    ],

    "demand": [
        ("tax payable", 3),
        ("demand notice", 3),
        ("balance tax payable", 4),
        ("total demand", 4),
        ("net demand", 4),
        ("total tax due", 3),
        ("notice of demand", 3),
        ("intimation under section 143", 3),
        ("the assessed income is", 3),
        ("income assessed at", 3),
    ],
}


def detect_ao_structure(text: str) -> dict[str, str]:
    """
    Stage 1: Split text into paragraphs, score each against segment keywords,
    assign to best-matching segment.

    Returns dict of {segment_type: concatenated_text (capped at 2000 chars each)}
    """
    paragraphs = _split_paragraphs(text)
    bucket: dict[str, list[str]] = defaultdict(list)

    for para in paragraphs:
        seg, score = _score_paragraph(para)
        if seg and score >= 2:
            bucket[seg].append(para)

    # Cap each segment — send most relevant paragraphs to LLM
    result: dict[str, str] = {}
    caps = {
        "brief_facts":            (5, 2500),
        "assessee_submissions":   (6, 2500),
        "ao_findings":            (6, 2500),
        "additions":              (8, 3000),   # additions are most important
        "demand":                 (3, 1000),
    }
    for seg, (max_paras, max_chars) in caps.items():
        paras = bucket.get(seg, [])[:max_paras]
        if paras:
            result[seg] = "\n\n".join(paras)[:max_chars]

    return result


def _split_paragraphs(text: str) -> list[str]:
    """Split on double newlines or common AO order separators."""
    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Split on blank lines or lines that are just dashes/underscores
    paras = re.split(r"\n{2,}|(?:\n[-_=]{5,}\n)", text)
    # Also split on numbered paragraph starts like "2. " or "3. " at line start
    cleaned = []
    for p in paras:
        p = p.strip()
        if len(p) > 60:   # ignore very short fragments
            cleaned.append(p)
    return cleaned


def _score_paragraph(para: str) -> tuple[str | None, int]:
    """Return (best_segment_type, score) for this paragraph."""
    para_lower = para.lower()
    scores: dict[str, int] = {}
    for seg, kw_weights in _SEGMENT_WEIGHTS.items():
        total = sum(w for kw, w in kw_weights if kw in para_lower)
        if total > 0:
            scores[seg] = total
    if not scores:
        return None, 0
    best = max(scores, key=scores.get)
    return best, scores[best]


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — LLM extraction
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM = (
    "You are an Indian Income Tax and legal document analyst. "
    "Extract structured information from any government tax document with precision. "
    "Return only valid JSON — no markdown, no commentary."
)

_CLASSIFY_SYSTEM = (
    "You are analysing an Indian Income Tax / legal document. "
    "Return only valid JSON — no markdown, no commentary."
)


_MIN_TEXT_WORDS = 50   # fewer words → scanned PDF, OCR failed → do not hallucinate


# ─────────────────────────────────────────────────────────────────────────────
# Stage 0 — Document classification (universal, no hardcoded types)
# ─────────────────────────────────────────────────────────────────────────────

def classify_document(text: str) -> dict:
    """
    Read what the document says it IS (from its own heading) and determine
    its BEHAVIOURAL nature — two binary questions that drive everything downstream.

    Design principle: we never hardcode document type names.
    The heading is extracted verbatim from the document.
    The two behavioral flags are the only thing that controls extraction flow:

      has_specific_requests  → True  : doc contains a numbered/listed set of
                                       items the recipient must produce.
                                       Extract them via extract_notice_requirements().
                                       Examples: 142(1) notice, TP questionnaire,
                                       survey notice, any notice with annexure.

      has_additions          → True  : doc makes specific additions/disallowances
                                       to income. Extract via existing order pipeline.
                                       Examples: 143(3) order, penalty order,
                                       search assessment.

    Both can be True (hybrid: e.g. a search assessment that also lists required docs).
    Both can be False (e.g. a demand notice — no additions made, no items requested).

    Only the first ~1000 chars are sent — the heading is always at the top.
    This is a very cheap call (~150 input tokens).
    """
    heading_text = text[:1000].strip()

    prompt = f"""Read the beginning of this Indian tax / legal document.

DOCUMENT START:
{heading_text}

Answer two behavioural questions about this document:

1. Does it contain a numbered or bulleted list of specific information / documents
   the recipient MUST produce or respond to? (e.g. annexure with items 1, 2, 3...)
2. Does it make specific additions to income, disallowances, or levy a penalty
   with a specific amount?

Return ONLY this JSON:
{{
  "document_heading": "exact title / heading as written in the document (copy verbatim)",
  "has_specific_requests": true or false,
  "has_additions": true or false,
  "request_location_hint": "where the list appears e.g. 'Annexure A', 'Para 3', 'items 1-11' — empty string if none",
  "doc_summary": "one sentence: what this document is and what it requires the assessee to do"
}}"""

    try:
        from ai.openrouter_client import call_openrouter
        raw  = call_openrouter(_CLASSIFY_SYSTEM, prompt,
                               temperature=0.0, max_tokens=300)
        data = _parse_json_fragment(raw)
        if isinstance(data, dict) and "document_heading" in data:
            return {
                "document_heading":     str(data.get("document_heading", "")).strip(),
                "has_specific_requests": bool(data.get("has_specific_requests", False)),
                "has_additions":         bool(data.get("has_additions", True)),
                "request_location_hint": str(data.get("request_location_hint", "")),
                "doc_summary":           str(data.get("doc_summary", "")),
            }
    except Exception:
        pass

    # Fallback: assume order (safe default — existing pipeline handles it)
    return {
        "document_heading":      "",
        "has_specific_requests": False,
        "has_additions":         True,
        "request_location_hint": "",
        "doc_summary":           "",
    }


def extract_notice_requirements(text: str, location_hint: str = "") -> list[str]:
    """
    Extract the exact numbered/listed document and information requests
    from any notice or document that has them.

    Works universally: 142(1) notices, survey notices, TP questionnaires,
    any future document format — whatever list the government wrote,
    this reads it verbatim.

    Args:
        text          — full document text (capped at 6000 chars)
        location_hint — optional hint about where the list appears
                        (e.g. "Annexure A", "items 1-11") from classify_document()

    Returns list of strings — one per requested item, exactly as written.
    Empty list if no structured requests found.
    """
    # Send the full text — requests can appear anywhere in the document
    context = text[:6000]
    hint_line = (f"\nThe requests are located in: {location_hint}"
                 if location_hint else "")

    prompt = f"""This document contains a list of specific information / documents
requested from the assessee.{hint_line}

DOCUMENT TEXT:
{context}

Extract EVERY item in the numbered list / annexure of requests.
Rules:
- Copy each item EXACTLY as written — do not paraphrase or shorten
- If an item specifies a format (table, statement, reconciliation) include that detail
- If an item has a sub-item (e.g. "1(a)", "1(b)"), include each separately
- Do NOT include preamble, legal citations, or procedural text — only the actual requests

Return a JSON array of strings:
["exact text of item 1", "exact text of item 2", ...]

If no numbered request list is found, return: []"""

    try:
        from ai.openrouter_client import call_openrouter
        raw  = call_openrouter(_CLASSIFY_SYSTEM, prompt,
                               temperature=0.0, max_tokens=1500)
        data = _parse_json_fragment(raw)
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except Exception:
        pass

    return []


def extract_case_facts(text: str) -> dict:
    """
    Main entry point.

    1. Detects structure (Stage 1)
    2. Builds focused context from relevant segments
    3. Calls OpenRouter with targeted prompt (Stage 2)
    4. Cross-validates additions with regex
    5. Returns merged structured dict

    Returns:
    {
        "case_facts":            str  — narrative summary for RAG query
        "nature_of_business":    str  — what the assessee does
        "transaction_type":      str  — type of disputed transaction
        "ao_allegations":        str  — core AO allegation
        "assessee_explanation":  str  — what assessee told AO
        "ao_rejection_reason":   str  — why AO rejected it
        "additions": [
            {"section": str, "amount": float, "description": str}
        ]
        "disputed_total":        float — sum of all additions
        "segments_detected":     list  — which segments were found (debug)
        "ocr_required":          bool  — True if PDF had no text layer
        "extraction_warning":    str   — human-readable warning if extraction failed
    }
    """
    # ── Hallucination guard — do NOT send near-empty text to LLM ─────────────
    word_count = len(text.split())
    if word_count < _MIN_TEXT_WORDS:
        result = _empty_result()
        result["ocr_required"]       = True
        result["extraction_warning"] = (
            f"This PDF appears to be a scanned image (only {word_count} words "
            f"of text extracted). OCR via OpenRouter vision was attempted but "
            f"returned insufficient text. Please upload a text-based PDF, or "
            f"ensure OPENROUTER_API_KEY is configured for OCR to work."
        )
        return result

    # ── Stage 0: Classify document — what is it, what does it do? ────────────
    classification = classify_document(text)
    has_requests   = classification.get("has_specific_requests", False)
    has_additions  = classification.get("has_additions", True)

    result = _empty_result()
    result["document_heading"]   = classification.get("document_heading", "")
    result["doc_summary"]        = classification.get("doc_summary", "")

    # ── Stage 0B: Extract specific requests if document demands them ──────────
    if has_requests:
        hint  = classification.get("request_location_hint", "")
        reqs  = extract_notice_requirements(text, hint)
        result["notice_requirements"] = reqs
    else:
        result["notice_requirements"] = []

    # ── Stage 1 + 2: Order-style extraction (additions, allegations, facts) ──
    # Run when: document makes additions (assessment/penalty order)
    #           OR when classification is uncertain (has_additions=True default)
    #           OR when document has NO specific requests (unknown → default path)
    if has_additions or not has_requests:
        segments = detect_ao_structure(text)

        context_parts: list[str] = []
        _SEG_LABELS = [
            ("brief_facts",          "BRIEF FACTS"),
            ("assessee_submissions",  "ASSESSEE'S SUBMISSIONS"),
            ("ao_findings",          "AO FINDINGS"),
            ("additions",            "ADDITIONS / PENALTY"),
            ("demand",               "DEMAND"),
        ]
        for seg_key, label in _SEG_LABELS:
            seg_text = segments.get(seg_key, "")
            if seg_text:
                context_parts.append(f"=== {label} ===\n{seg_text}")

        if not context_parts:
            context_parts = [text[:4000]]

        context = "\n\n".join(context_parts)

        # Dynamic prompt — tells the LLM what kind of document this is
        doc_heading_line = (
            f"DOCUMENT TYPE: {classification['document_heading']}\n"
            if classification.get("document_heading") else ""
        )

        prompt = f"""Read this Indian Income Tax document excerpt and extract the information below.

{doc_heading_line}DOCUMENT EXCERPT:
{context}

Return ONLY this JSON (no other text):
{{
  "case_facts": "3-4 sentence narrative: who the assessee is, what they do, what transaction or issue is being examined, what the document requires. Be specific — include section numbers and amounts.",
  "nature_of_business": "What business or profession the assessee carries on",
  "transaction_type": "Type of issue e.g. cash loan, unexplained credit, TDS default, presumptive income, property investment, contract payments",
  "ao_allegations": "Core reason or allegation — what the authority is questioning or alleging",
  "assessee_explanation": "What the assessee submitted or explained in defence (empty string if not present)",
  "ao_rejection_reason": "Why the authority rejected the assessee's explanation (empty string if not present)",
  "additions": [
    {{
      "section": "section number e.g. 68",
      "amount": 500000,
      "description": "Brief description of what was added/disallowed and why"
    }}
  ],
  "disputed_total": 0
}}

Rules:
- case_facts is the MOST important field — make it specific and usable for legal research
- additions: only include if actual monetary additions/disallowances are made; empty array if none
- disputed_total = sum of all addition amounts (0 if no additions)
- If a field cannot be determined, use empty string or 0
- Amounts must be numbers not strings"""

        try:
            from ai.openrouter_client import call_openrouter
            raw        = call_openrouter(_EXTRACTION_SYSTEM, prompt,
                                         temperature=0.0, max_tokens=1200)
            order_data = _parse_llm_result(raw)
        except Exception:
            order_data = _empty_result()

        # Merge order extraction into result (don't overwrite doc classification fields)
        for k, v in order_data.items():
            if k not in ("document_heading", "doc_summary",
                         "notice_requirements", "ocr_required", "extraction_warning"):
                result[k] = v

        # Cross-validate additions with regex
        regex_adds = _extract_additions_regex(text)
        if regex_adds:
            if not result.get("additions"):
                result["additions"] = regex_adds
            else:
                llm_sections = {a["section"] for a in result["additions"]}
                for r in regex_adds:
                    if r["section"] not in llm_sections:
                        result["additions"].append(r)

        # Compute disputed_total if not set
        if not result.get("disputed_total") and result.get("additions"):
            result["disputed_total"] = sum(
                float(a.get("amount", 0)) for a in result["additions"]
            )

        result["segments_detected"] = list(segments.keys())

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Regex cross-validation — additions extraction
# ─────────────────────────────────────────────────────────────────────────────

_SEC_LABEL = r"(?:section|sec\.?|u/?s\.?)\s*"
_AMOUNT_PAT = r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:/-|lakhs?|lacs?)?"
_LAKH_PAT   = r"([\d,]+(?:\.\d+)?)\s*(?:lakhs?|lacs?)"

# Section number pattern — covers 68, 69A, 271D, 269SS, 40A(3), 271(1)(c) etc.
# \b at end prevents greedily absorbing following words like "68FOR" from "68 for"
_SEC_NUM = r"(\d+(?:[A-Z]{1,3})?(?:\s*\(\s*\d+\s*\))*(?:\s*\([a-z]+\))*)\b"

_ADDITION_PATTERNS = [
    # "addition of Rs. 5,00,000 under section 68"
    rf"addition\s+of\s+{_AMOUNT_PAT}.*?{_SEC_LABEL}{_SEC_NUM}",
    rf"addition\s+of\s+{_AMOUNT_PAT}.*?u/?s\.?\s*{_SEC_NUM}",
    # "addition of Rs. 5,00,000 u/s 68"
    rf"{_SEC_LABEL}{_SEC_NUM}.*?addition\s+of\s+{_AMOUNT_PAT}",
    # "penalty of Rs. X under section 271D"
    rf"penalty\s+of\s+{_AMOUNT_PAT}.*?{_SEC_LABEL}{_SEC_NUM}",
    rf"penalty\s+of\s+{_AMOUNT_PAT}.*?u/?s\.?\s*{_SEC_NUM}",
    # "disallowance of Rs. X under section 40A(3)"
    rf"disallowance\s+of\s+{_AMOUNT_PAT}.*?{_SEC_LABEL}{_SEC_NUM}",
    # "addition of X lakhs u/s 68"
    rf"addition\s+of\s+{_LAKH_PAT}.*?{_SEC_LABEL}{_SEC_NUM}",
]


def _extract_additions_regex(text: str) -> list[dict]:
    """
    Regex-based extraction of additions/penalties with amounts.
    Returns [{section, amount, description}]
    """
    found: list[dict] = []
    seen: set[str] = set()

    for pat in _ADDITION_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            groups = m.groups()
            if len(groups) < 2:
                continue

            # Amount is always first capture group, section second
            amount_str = groups[0].replace(",", "").strip()
            section    = groups[1].strip().upper().replace(" ", "")

            try:
                amount = float(amount_str)
                # Handle "lakhs" pattern — multiply
                if "lakh" in m.group(0).lower() or "lac" in m.group(0).lower():
                    if amount < 10000:   # likely in lakhs
                        amount *= 100000
            except ValueError:
                continue

            key = f"{section}_{int(amount)}"
            if key in seen or amount < 1000:
                continue
            seen.add(key)

            ctx_start = max(0, m.start() - 60)
            ctx_end   = min(len(text), m.end() + 60)
            description = text[ctx_start:ctx_end].strip().replace("\n", " ")

            found.append({
                "section":     section,
                "amount":      amount,
                "description": description[:200],
            })

    return found


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json_fragment(raw: str):
    """Parse any JSON value (array or object) from raw LLM output."""
    try:
        clean = raw.strip()
        if "```" in clean:
            clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()
        # Try array first (for notice requirements), then object
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = clean.find(start_char)
            end   = clean.rfind(end_char) + 1
            if start >= 0 and end > start:
                return json.loads(clean[start:end])
    except Exception:
        pass
    return None


def _parse_llm_result(raw: str) -> dict:
    """Parse LLM JSON output. Returns empty result on failure."""
    try:
        clean = raw.strip()
        if "```" in clean:
            clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(clean[start:end])
            if isinstance(parsed, dict):
                # Ensure additions is a list
                if not isinstance(parsed.get("additions"), list):
                    parsed["additions"] = []
                # Merge with empty result to guarantee all keys present
                base = _empty_result()
                base.update(parsed)
                return base
    except Exception:
        pass
    return _empty_result()


def _empty_result() -> dict:
    return {
        # Stage 0 — document classification
        "document_heading":    "",   # verbatim title from the document itself
        "doc_summary":         "",   # one-sentence: what it is + what it requires
        "notice_requirements": [],   # list[str] — exact items the AO requested

        # Stage 1+2 — order/penalty extraction
        "case_facts":           "",
        "nature_of_business":   "",
        "transaction_type":     "",
        "ao_allegations":       "",
        "assessee_explanation": "",
        "ao_rejection_reason":  "",
        "additions":            [],
        "disputed_total":       0.0,
        "segments_detected":    [],
        "ocr_required":         False,
        "extraction_warning":   "",
    }
