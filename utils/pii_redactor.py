"""
PII Redactor — strips all sensitive data from Indian tax documents
before any text is sent to external AI APIs (Claude, ChatGPT, etc.).

Handles:
  • PAN          — ABCDE1234F
  • Aadhaar       — 1234 5678 9012 (any spacing)
  • TAN           — ABCD12345E
  • Bank account  — 9-18 digit numbers in account context
  • IFSC          — ABCD0123456
  • Mobile        — 10-digit Indian numbers (6–9 prefix)
  • Email         — standard email pattern
  • Assessee name — extracted from PDF metadata
  • Company name  — M/s. XYZ Ltd, XYZ Pvt. Ltd etc.
  • Address lines — door no, sector, pin code
  • Amounts       — kept (needed for legal analysis)
  • AO Ward/name  — optionally redacted

Usage:
    from utils.pii_redactor import redact, RedactionReport

    clean_text, report = redact(raw_text, known_names=["Era Infra Engineering"])
    print(report.summary())          # what was found + replaced
    print(clean_text)                # safe to send to external AI
"""

import re
from dataclasses import dataclass, field

# ── spaCy NER (optional — loaded lazily, graceful fallback if not installed) ──
_nlp = None
_nlp_tried = False   # only attempt load once


def _get_nlp():
    """Lazily load spaCy en_core_web_sm model. Returns None if unavailable."""
    global _nlp, _nlp_tried
    if _nlp_tried:
        return _nlp
    _nlp_tried = True
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        _nlp = None   # spaCy or model not installed — regex fallback will run
    return _nlp


def _redact_names_spacy(text: str) -> tuple[str, int]:
    """
    Use spaCy NER to find PERSON and ORG entities and redact them.
    Processes in reverse to preserve character offsets.

    Returns (redacted_text, count_redacted)
    Falls back gracefully if spaCy is unavailable.
    """
    nlp = _get_nlp()
    if not nlp:
        return text, 0

    try:
        # spaCy processes up to its max_length; truncate very large docs
        doc = nlp(text[:50000])
        count = 0
        result = text

        # Collect entities that are meaningful (skip very short ones)
        entities = [
            ent for ent in doc.ents
            if ent.label_ in ("PERSON", "ORG")
            and len(ent.text.strip()) > 3
            # Don't re-redact things already replaced
            and "REDACTED" not in ent.text
            # Skip common false positives from legal text
            and ent.text.upper() not in {
                "ITAT", "CIT", "AO", "DCIT", "PCIT", "JCIT", "ITO",
                "SC", "HC", "CBDT", "ITR", "PAN", "TDS", "TCS",
                "INDIA", "INDIAN", "GOVERNMENT", "GOI", "GOV",
                "ASSESSMENT", "TRIBUNAL", "COURT", "BENCH",
                "INCOME TAX", "INCOME-TAX",
            }
        ]

        # Sort by start position (reverse) so offsets remain valid
        for ent in sorted(entities, key=lambda e: e.start_char, reverse=True):
            result = (result[:ent.start_char]
                      + _R["name"]
                      + result[ent.end_char:])
            count += 1

        return result, count
    except Exception:
        return text, 0


# ── Replacement tokens ─────────────────────────────────────────────────────────
_R = {
    "pan":          "《PAN-REDACTED》",
    "aadhaar":      "《AADHAAR-REDACTED》",
    "tan":          "《TAN-REDACTED》",
    "bank_account": "《BANK-ACCT-REDACTED》",
    "ifsc":         "《IFSC-REDACTED》",
    "mobile":       "《MOBILE-REDACTED》",
    "email":        "《EMAIL-REDACTED》",
    "name":         "《NAME-REDACTED》",
    "address":      "《ADDRESS-REDACTED》",
    "pincode":      "《PIN-REDACTED》",
    "dob":          "《DOB-REDACTED》",
    "ip":           "《IP-REDACTED》",
}


@dataclass
class RedactionReport:
    counts: dict = field(default_factory=dict)      # {type: count}
    samples: dict = field(default_factory=dict)     # {type: [first 2 values found]}
    total: int = 0

    def add(self, pii_type: str, value: str):
        self.counts[pii_type] = self.counts.get(pii_type, 0) + 1
        if pii_type not in self.samples:
            self.samples[pii_type] = []
        if len(self.samples[pii_type]) < 2:
            # Store partially masked version for display
            self.samples[pii_type].append(_mask(value, pii_type))
        self.total += 1

    def summary(self) -> str:
        if not self.total:
            return "✅ No sensitive data detected."
        lines = [f"🔒 **{self.total} PII items redacted:**"]
        for t, n in sorted(self.counts.items()):
            label = t.replace("_", " ").title()
            examples = ", ".join(self.samples.get(t, []))
            lines.append(f"  • {label}: **{n}** replaced  _(e.g. {examples})_")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {"total": self.total, "by_type": self.counts}


def _mask(value: str, pii_type: str) -> str:
    """Partially mask a value for display in the report."""
    v = value.strip()
    if pii_type == "pan" and len(v) == 10:
        return f"{v[:3]}****{v[-1]}"
    if pii_type == "aadhaar":
        digits = re.sub(r"\D", "", v)
        return f"****-****-{digits[-4:]}" if len(digits) >= 4 else "****"
    if pii_type in ("mobile",):
        return f"{v[:3]}****{v[-2:]}" if len(v) >= 5 else "****"
    if pii_type == "email" and "@" in v:
        parts = v.split("@")
        return f"{parts[0][:2]}****@{parts[1]}"
    if pii_type == "bank_account":
        return f"****{v[-4:]}" if len(v) >= 4 else "****"
    if pii_type == "name":
        words = v.split()
        return f"{words[0][:1]}*** {words[-1][:1]}***" if len(words) > 1 else f"{v[:2]}***"
    return v[:3] + "****"


# ── Pattern definitions ────────────────────────────────────────────────────────

# PAN: 5 uppercase letters, 4 digits, 1 uppercase letter
_PAN_RE = re.compile(r'\b([A-Z]{5}[0-9]{4}[A-Z])\b')

# TAN: 4 uppercase letters, 5 digits, 1 uppercase letter (different from PAN)
_TAN_RE = re.compile(r'\b([A-Z]{4}[0-9]{5}[A-Z])\b')

# Aadhaar: 12 digits with optional spaces/hyphens
_AADHAAR_RE = re.compile(
    r'\b([2-9]\d{3}[\s\-]?\d{4}[\s\-]?\d{4})\b'
)

# IFSC: 4 letters + 0 + 6 alphanumeric
_IFSC_RE = re.compile(r'\b([A-Z]{4}0[A-Z0-9]{6})\b')

# Bank account: 9-18 digit number, preceded/followed by account keywords
_BANK_CTX_RE = re.compile(
    r'(?:a/?c(?:count)?|account\s*no\.?|acc\.?\s*no\.?)'
    r'[\s:\-#]*(\d{9,18})\b',
    re.IGNORECASE
)

# Mobile: 10-digit starting 6-9 (Indian numbers)
_MOBILE_RE = re.compile(
    r'(?<!\d)([6-9]\d{9})(?!\d)'
)

# Email
_EMAIL_RE = re.compile(
    r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b'
)

# Date of birth patterns
_DOB_RE = re.compile(
    r'\b(?:dob|date\s+of\s+birth|born\s+on)[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})\b',
    re.IGNORECASE
)

# Indian PIN code (6 digits, often standalone or with state)
_PIN_RE = re.compile(r'\b((?:110|400|411|500|600|700|800|560|302|226|380|395|248)\d{3})\b')

# IP address
_IP_RE = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')

# Address patterns — door/plot/flat numbers + locality keywords
_ADDRESS_RE = re.compile(
    r'\b(?:(?:flat|door|house|plot|f\.?no\.?|h\.?no\.?)[\s\.\-#]+[\w/\-,]+[\s,]+)?'
    r'(?:sector|block|phase|ward|layout|nagar|colony|marg|road|street|lane|avenue)'
    r'[\s\-#\w,/\.]{5,60}',
    re.IGNORECASE
)

# Company / person name patterns — "M/s XYZ" or "Shri/Smt/Mr/Ms NAME"
_COMPANY_RE = re.compile(
    r'(?:M/s\.?\s+|M/S\.?\s+)([A-Z][A-Za-z\s&\.\(\)]{3,60}?)'
    r'(?=\s*(?:,|\.|\n|Ltd|Pvt|LLP|HUF|$))',
)
_PERSON_RE = re.compile(
    r'(?:Shri|Smt\.?|Sri|Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s+'
    r'([A-Z][a-zA-Z\s\.]{3,50}?)(?=\s*[,\n\(])',
)


# ── Core redact function ───────────────────────────────────────────────────────

def redact(text: str,
           known_names: list[str] = None,
           redact_amounts: bool = False,
           redact_addresses: bool = True) -> tuple[str, RedactionReport]:
    """
    Redact all PII from text.

    Args:
        text           — raw text from PDF or user input
        known_names    — list of names extracted from PDF (assessee name etc.)
                         These are redacted by exact match first.
        redact_amounts — if True, also redact ₹ amounts (default False —
                         amounts are needed for legal analysis)
        redact_addresses — if True, redact address patterns (default True)

    Returns:
        (clean_text, RedactionReport)
    """
    report = RedactionReport()
    out    = text

    # 1. Known names (highest priority — exact match, case-insensitive)
    for name in (known_names or []):
        name = name.strip()
        if not name or len(name) < 4:
            continue
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        if pattern.search(out):
            report.add("name", name)
            out = pattern.sub(_R["name"], out)

    # 2. Company names (M/s. XYZ format)
    for m in _COMPANY_RE.finditer(out):
        report.add("name", m.group(0))
    out = _COMPANY_RE.sub(_R["name"], out)

    # 3. Person names (Shri/Mr/Mrs format)
    for m in _PERSON_RE.finditer(out):
        report.add("name", m.group(0))
    out = _PERSON_RE.sub(_R["name"], out)

    # 3b. spaCy NER — catches HUF names, trust names, unusual formats
    #     Runs AFTER regex to avoid re-detecting already-replaced tokens
    spacy_out, spacy_count = _redact_names_spacy(out)
    if spacy_count > 0:
        report.counts["name"] = report.counts.get("name", 0) + spacy_count
        report.total += spacy_count
        out = spacy_out

    # 4. PAN
    for m in _PAN_RE.finditer(out):
        report.add("pan", m.group(1))
    out = _PAN_RE.sub(_R["pan"], out)

    # 5. TAN (after PAN so overlap is handled)
    for m in _TAN_RE.finditer(out):
        # Skip if already replaced by PAN token
        if "REDACTED" not in m.group(0):
            report.add("tan", m.group(1))
    out = re.sub(r'\b([A-Z]{4}[0-9]{5}[A-Z])\b', _R["tan"], out)

    # 6. Aadhaar
    for m in _AADHAAR_RE.finditer(out):
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) == 12:
            report.add("aadhaar", m.group(1))
    out = re.sub(
        r'\b([2-9]\d{3}[\s\-]?\d{4}[\s\-]?\d{4})\b',
        lambda m: _R["aadhaar"] if len(re.sub(r"\D","",m.group(1))) == 12 else m.group(0),
        out
    )

    # 7. IFSC
    for m in _IFSC_RE.finditer(out):
        report.add("ifsc", m.group(1))
    out = _IFSC_RE.sub(_R["ifsc"], out)

    # 8. Bank account (context-dependent)
    for m in _BANK_CTX_RE.finditer(out):
        report.add("bank_account", m.group(1))
    out = _BANK_CTX_RE.sub(
        lambda m: m.group(0).replace(m.group(1), _R["bank_account"]),
        out
    )

    # 9. Mobile numbers
    for m in _MOBILE_RE.finditer(out):
        report.add("mobile", m.group(1))
    out = _MOBILE_RE.sub(_R["mobile"], out)

    # 10. Email
    for m in _EMAIL_RE.finditer(out):
        report.add("email", m.group(1))
    out = _EMAIL_RE.sub(_R["email"], out)

    # 11. Date of birth
    for m in _DOB_RE.finditer(out):
        report.add("dob", m.group(1))
    out = _DOB_RE.sub(
        lambda m: m.group(0).replace(m.group(1), _R["dob"]),
        out
    )

    # 12. PIN codes (specific Indian prefix patterns)
    for m in _PIN_RE.finditer(out):
        report.add("pincode", m.group(1))
    out = _PIN_RE.sub(_R["pincode"], out)

    # 13. IP addresses
    for m in _IP_RE.finditer(out):
        report.add("ip", m.group(1))
    out = _IP_RE.sub(_R["ip"], out)

    # 14. Address lines
    if redact_addresses:
        for m in _ADDRESS_RE.finditer(out):
            val = m.group(0).strip()
            if len(val) > 10:
                report.add("address", val)
        out = re.sub(
            r'\b(?:(?:flat|door|house|plot|f\.?no\.?|h\.?no\.?)[\s\.\-#]+[\w/\-,]+[\s,]+)?'
            r'(?:sector|block|phase|ward|layout|nagar|colony|marg|road|street|lane|avenue)'
            r'[\s\-#\w,/\.]{5,60}',
            _R["address"],
            out,
            flags=re.IGNORECASE
        )

    return out, report


def redact_for_ai(text: str, scan_metadata: dict = None,
                  is_external: bool = True) -> tuple[str, RedactionReport]:
    """
    Convenience wrapper — redacts text before sending to any AI.

    scan_metadata: dict from parse_assessment_order() — supplies known names.
    is_external: True = external API (Claude/ChatGPT) — full redaction.
                 False = local Ollama — still redact (good practice).
    """
    known_names = []
    if scan_metadata:
        for field in ("assessee_name", "ao_name"):
            v = scan_metadata.get(field, "")
            if v:
                known_names.append(v)

    return redact(text, known_names=known_names)


def redact_query(query: str) -> tuple[str, RedactionReport]:
    """
    Redact a user-typed query or search string.
    Less aggressive — only PAN, Aadhaar, mobile, email.
    """
    report = RedactionReport()
    out = query

    for pattern, key in [
        (_PAN_RE,    "pan"),
        (_AADHAAR_RE, "aadhaar"),
        (_MOBILE_RE, "mobile"),
        (_EMAIL_RE,  "email"),
    ]:
        for m in pattern.finditer(out):
            report.add(key, m.group(1))
        out = pattern.sub(_R[key], out)

    return out, report


def is_clean(text: str) -> bool:
    """Quick check — returns True if no obvious PII detected."""
    for pattern in [_PAN_RE, _AADHAAR_RE, _MOBILE_RE, _EMAIL_RE, _IFSC_RE]:
        if pattern.search(text):
            return False
    return True
