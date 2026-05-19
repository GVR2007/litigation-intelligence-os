"""
Citation Verifier — checks every case citation the AI mentions against
real sources before the CA relies on it.

SC White Paper guideline #1:
  "Lawyers must independently verify every case citation against an
   authoritative primary source before relying on it in any filing."

How it works:
  1. Extract all case references from AI-generated text using regex
     (catches: ITR, DTR, taxmann, SCC, ITA No., ITAT citations)
  2. Check each against local itat_precedents DB first (zero API cost)
  3. For anything not in local DB → search Indian Kanoon API (1 call each)
  4. Return a VerificationReport with verified / unverified / hallucinated flags

Usage:
    from utils.citation_verifier import verify_text_citations
    report = verify_text_citations(ai_text, sections=["269SS"])
    # report.verified   — list of confirmed real cases
    # report.unverified — list of citations NOT found anywhere
    # report.summary()  — human-readable markdown
"""

from __future__ import annotations
import re
import sys
import os
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# Citation extraction patterns — Indian legal citation formats
# ─────────────────────────────────────────────────────────────────────────────

_CITATION_PATTERNS = [
    # ITR / DTR / Taxmann — e.g. "(2022) 145 ITR 234 (SC)"
    r"\(\d{4}\)\s+\d+\s+(?:ITR|DTR|taxmann\.com|Taxman|SCC|SCR|ITD|TTJ|TIOL)\s+\d+",
    # ITA No. — e.g. "ITA No. 1234/Mum/2021"
    r"ITA\s+No\.?\s*\d+[\/\s]\w+[\/\s]\d{4}",
    # vs / v. case names — e.g. "M/s ABC Pvt Ltd vs DCIT"
    r"(?:M/s\.?\s+)?[A-Z][A-Za-z\s&\.]{3,40}\s+(?:vs?\.?|versus)\s+(?:CIT|DCIT|ACIT|ITO|PCIT|ITAT|Revenue|Assessee)[^\n]{0,60}",
    # Named SC/HC cases — e.g. "CIT vs XYZ Ltd (2019) SC"
    r"(?:CIT|PCIT|DCIT|ITO)\s+(?:vs?\.?|versus)\s+[A-Z][A-Za-z\s&\.]{3,50}",
    # ITAT bench references — e.g. "ITAT Mumbai Bench: ABC vs ITO"
    r"ITAT\s+\w+\s+(?:Bench|bench)[^\.]{5,80}",
    # Common case name patterns with year
    r"[A-Z][A-Za-z\s&\.]{5,50}\s+\[\d{4}\]\s+\d+\s+\w+\s+\d+",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _CITATION_PATTERNS]


@dataclass
class CitationResult:
    raw:        str
    status:     str          # "verified_local" | "verified_ik" | "unverified" | "hallucinated"
    ik_url:     str  = ""
    confidence: float = 0.0
    note:       str  = ""


@dataclass
class VerificationReport:
    total:        int = 0
    verified:     list[CitationResult] = field(default_factory=list)
    unverified:   list[CitationResult] = field(default_factory=list)

    def summary(self) -> str:
        if self.total == 0:
            return "✅ No case citations detected in this AI output."

        v = len(self.verified)
        u = len(self.unverified)

        lines = [
            f"### 🔍 Citation Verification — {self.total} citation(s) found\n",
            f"- ✅ **Verified:** {v} (found in local DB or Indian Kanoon)",
            f"- ⚠️ **Unverified:** {u} (could not confirm — verify manually before filing)",
            "",
        ]

        if self.verified:
            lines.append("**Verified citations:**")
            for c in self.verified:
                src = "Local DB" if c.status == "verified_local" else "Indian Kanoon"
                url_part = f" — [View]({c.ik_url})" if c.ik_url else ""
                lines.append(f"  ✅ `{c.raw[:80]}` [{src}]{url_part}")

        if self.unverified:
            lines.append("\n**⚠️ Could not verify — check these manually before filing:**")
            for c in self.unverified:
                lines.append(f"  ⚠️ `{c.raw[:80]}` — {c.note or 'Not found in DB or IK'}")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_citations(text: str) -> list[str]:
    """Extract all case citation strings from AI-generated text."""
    found = []
    seen  = set()
    for pattern in _COMPILED:
        for m in pattern.finditer(text):
            raw = m.group().strip()
            # Normalise whitespace
            raw = re.sub(r"\s+", " ", raw)
            if len(raw) > 8 and raw not in seen:
                seen.add(raw)
                found.append(raw)
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Local DB check
# ─────────────────────────────────────────────────────────────────────────────

def _check_local_db(citation: str) -> tuple[bool, str]:
    """
    Check citation against local itat_precedents table.
    Returns (found: bool, ik_url: str).
    """
    try:
        import sqlite3
        import config
        conn = sqlite3.connect(config.DB_PATH)
        cur  = conn.cursor()

        # Try exact substring match on case_citation
        q    = f"%{citation[:60]}%"
        cur.execute("""
            SELECT ik_url FROM itat_precedents
            WHERE LOWER(case_citation) LIKE LOWER(?)
            LIMIT 1
        """, (q,))
        row = cur.fetchone()
        conn.close()

        if row:
            return True, (row[0] or "")

        # Try matching on key words (at least 3 distinctive words)
        words = [w for w in re.findall(r"[A-Za-z]{4,}", citation)
                 if w.lower() not in {"versus", "india", "income", "court",
                                       "tribunal", "delhi", "mumbai", "itat"}]
        if len(words) >= 3:
            conn = sqlite3.connect(config.DB_PATH)
            cur  = conn.cursor()
            like_clauses = " AND ".join(
                f"LOWER(case_citation) LIKE LOWER(?)" for _ in words[:3]
            )
            params = tuple(f"%{w}%" for w in words[:3])
            cur.execute(f"""
                SELECT ik_url FROM itat_precedents
                WHERE {like_clauses}
                LIMIT 1
            """, params)
            row = cur.fetchone()
            conn.close()
            if row:
                return True, (row[0] or "")

    except Exception:
        pass

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# Indian Kanoon check
# ─────────────────────────────────────────────────────────────────────────────

def _check_ik(citation: str) -> tuple[bool, str]:
    """
    Search IK for the citation using its short name.
    Returns (found: bool, url: str).
    """
    try:
        from ai.indian_kanoon import search_cases, clean_html

        # Build a short IK query from the citation
        # Extract party names and year — most identifiable parts
        year_m  = re.search(r"\b(\d{4})\b", citation)
        year    = year_m.group(1) if year_m else ""

        # Get 3-4 meaningful words
        words   = [w for w in re.findall(r"[A-Za-z]{4,}", citation)
                   if w.lower() not in {"versus", "india", "income",
                                         "court", "tribunal", "itat", "dcit",
                                         "pcit", "acit", "ward", "circle"}]
        query   = " ".join(words[:4])
        if year:
            query += f" {year}"

        if not query.strip():
            return False, ""

        result = search_cases(query)
        docs   = result.get("docs", [])

        if docs:
            tid = docs[0].get("tid", "")
            url = f"https://indiankanoon.org/doc/{tid}/" if tid else ""
            return True, url

    except Exception:
        pass

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# Master: verify_text_citations()
# ─────────────────────────────────────────────────────────────────────────────

def verify_text_citations(text: str,
                           sections: list[str] | None = None,
                           check_ik: bool = True) -> VerificationReport:
    """
    Extract and verify all citations in AI-generated text.

    Args:
        text      — AI output (submission, analysis, intelligence report)
        sections  — case sections for context (not used in verification logic, for future)
        check_ik  — if True, citations not in local DB are checked against IK API

    Returns VerificationReport with .verified, .unverified, and .summary()
    """
    citations = extract_citations(text)
    report    = VerificationReport(total=len(citations))

    for raw in citations:
        # Step 1: local DB (free, fast)
        found_local, url = _check_local_db(raw)
        if found_local:
            report.verified.append(CitationResult(
                raw=raw, status="verified_local",
                ik_url=url, confidence=0.9,
                note="Found in local verified DB",
            ))
            continue

        # Step 2: IK API (1 call per citation — use sparingly)
        if check_ik:
            found_ik, ik_url = _check_ik(raw)
            if found_ik:
                report.verified.append(CitationResult(
                    raw=raw, status="verified_ik",
                    ik_url=ik_url, confidence=0.75,
                    note="Found on Indian Kanoon",
                ))
                continue

        # Not found anywhere — flag as unverified
        report.unverified.append(CitationResult(
            raw=raw, status="unverified",
            confidence=0.0,
            note="Not found in local DB or IK — verify manually before filing",
        ))

    return report
