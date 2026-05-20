"""
ITAT Case Ingestion Pipeline — run_ingest.py

Reads raw .txt ITAT judgment files and inserts them into itat_precedents.
After ingestion, run:  python run_embed.py --sync

Source files format (from Indian Kanoon scrape):
    URL: https://indiankanoon.org/doc/<tid>/
    TITLE: ...
    DATE: ...
    <full judgment text>

Usage:
    python run_ingest.py                          # ingest all files
    python run_ingest.py --dry-run                # parse only, no DB writes
    python run_ingest.py --limit 50               # first 50 files only
    python run_ingest.py --status                 # show current DB counts
    python run_ingest.py --source-dir "path/to"   # override source directory

Adds to itat_precedents with verified=2 (web-scraped reliable).
Safe to re-run — INSERT OR IGNORE skips already-ingested cases.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# Default source directory — update this path if yours is different
DEFAULT_SOURCE_DIR = r"E:\CA\fishing\analyst_4_4_26_only_2_prob\analyst\raw_itat_cases"

# ── IT Act section regex — matches all common formats in IK judgments ──────────
# Covers: u/s 44AD, u/s. 269SS, section 56(2)(x), section 271(1)(c), §68 etc.
_SEC_PAT = re.compile(
    r"""
    (?:
        u/s\.?\s*           # u/s or u/s.
        | section\s+        # section
        | §\s*              # § symbol
        | \bSec\.\s*        # Sec.
    )
    (
        \d{1,3}             # base number (1–3 digits)
        [A-Z]{0,4}          # optional suffix letters (A, AA, ADA, BBE…)
        (?:                 # optional parenthetical sub-parts
            \(\s*           # opening paren
            [\w\d]+         # sub-section (number or letter)
            \s*\)           # closing paren
        ){0,3}              # up to 3 levels: (1)(c)(ii)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Sections that are purely procedural — still stored but not used as primary
_PROCEDURAL = {
    "139", "142", "143", "144", "144B", "144C", "149", "153",
    "131", "133", "246A", "250", "251", "253", "254",
    "272A", "271F", "271FA",
}

# Bench abbreviation → full city name
_BENCH_MAP = {
    "Del": "Delhi",  "Mum": "Mumbai",  "Kol": "Kolkata", "Chny": "Chennai",
    "Hyd": "Hyderabad", "Ahd": "Ahmedabad", "Bang": "Bangalore",
    "Pun": "Pune", "PUN": "Pune", "Chd": "Chandigarh", "Lkw": "Lucknow",
    "LKW": "Lucknow", "Jab": "Jabalpur", "Ind": "Indore",
    "Agr": "Agra", "Agra": "Agra", "Mds": "Madras", "Kol": "Kolkata",
    "Ran": "Ranchi", "Pat": "Patna", "Rjt": "Rajkot", "Rjt": "Rajkot",
    "Vizag": "Visakhapatnam", "Jp": "Jaipur", "JP": "Jaipur",
    "Jodh": "Jodhpur", "JODH": "Jodhpur", "Nag": "Nagpur", "NAG": "Nagpur",
    "Bil": "Bilaspur", "BIL": "Bilaspur", "Ctk": "Cuttack", "CTK": "Cuttack",
    "Rpr": "Raipur", "RPR": "Raipur", "Asr": "Amritsar", "ASR": "Amritsar",
    "Alld": "Allahabad", "ALLD": "Allahabad", "Coch": "Cochin",
    "Pan": "Panaji", "PAN": "Panaji", "M": "Mumbai", "K": "Kolkata",
    "H": "Hyderabad", "A": "Ahmedabad", "B": "Bangalore", "D": "Delhi",
    "Pn": "Pune", "PN": "Pune",
}

# Win signals (assessee wins) — check last 3000 chars of file
_WIN_PATTERNS = [
    r"appeal\s+(?:of\s+the\s+assessee\s+)?(?:is\s+)?(?:hereby\s+)?allowed",
    r"appeal\s+(?:of\s+the\s+assessee\s+)?(?:is\s+)?(?:partly\s+)?allowed",
    r"allowed\s+for\s+statistical\s+purposes",
    r"addition\s+(?:is\s+)?(?:hereby\s+)?deleted",
    r"addition\s+(?:is\s+)?(?:hereby\s+)?set\s+aside",
    r"penalty\s+(?:is\s+)?(?:hereby\s+)?deleted",
    r"penalty\s+(?:is\s+)?(?:hereby\s+)?cancelled",
    r"grounds?\s+(?:of\s+the\s+assessee\s+(?:is|are)\s+)?allowed",
    r"relief\s+(?:is\s+)?(?:hereby\s+)?granted",
    r"in\s+favour\s+of\s+(?:the\s+)?assessee",
    r"assessee['']?s?\s+appeal\s+(?:is\s+)?allowed",
]

_LOSS_PATTERNS = [
    r"appeal\s+(?:of\s+the\s+assessee\s+)?(?:is\s+)?(?:hereby\s+)?dismissed",
    r"appeal\s+(?:is\s+)?dismissed\s+(?:in\s+full)?",
    r"assessee['']?s?\s+appeal\s+(?:is\s+)?dismissed",
    r"addition\s+(?:is\s+)?(?:hereby\s+)?confirmed",
    r"penalty\s+(?:is\s+)?(?:hereby\s+)?confirmed",
    r"penalty\s+(?:is\s+)?(?:hereby\s+)?upheld",
    r"we\s+uphold\s+the\s+(?:addition|order|penalty)",
    r"revenue['']?s?\s+appeal\s+(?:is\s+)?allowed",    # revenue wins = assessee loses
    r"in\s+favour\s+of\s+(?:the\s+)?(?:revenue|department)",
]

_WIN_RE  = [re.compile(p, re.IGNORECASE) for p in _WIN_PATTERNS]
_LOSS_RE = [re.compile(p, re.IGNORECASE) for p in _LOSS_PATTERNS]

# Ratio / holding paragraph signals
_RATIO_SIGNALS = [
    "we hold", "we are of the view", "we find that", "we find merit",
    "we are satisfied", "tribunal held", "bench held",
    "in the result", "resultantly", "accordingly, the appeal",
    "in view of the above", "for the reasons given above",
    "we are of the considered view", "we, thus,",
    "in our considered opinion", "in our view",
]


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(path: Path) -> dict | None:
    """
    Parse a single .txt ITAT judgment file.
    Returns a dict ready for INSERT into itat_precedents, or None on failure.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    if len(text) < 500:
        return None

    lines = text.splitlines()

    # ── Metadata header (first 3 lines) ──────────────────────────────────────
    ik_url = ""
    for ln in lines[:5]:
        if ln.startswith("URL:"):
            ik_url = ln[4:].strip()
            break

    ik_tid = ""
    m = re.search(r"/doc/(\d+)/", ik_url)
    if m:
        ik_tid = m.group(1)

    # ── Court type and bench ──────────────────────────────────────────────────
    court_type = "ITAT"
    bench_city = ""

    for ln in lines[:20]:
        ln_lower = ln.lower()
        if "supreme court" in ln_lower:
            court_type = "SC"
            bench_city = "Supreme Court"
            break
        if "high court" in ln_lower:
            court_type = "HC"
            m2 = re.search(r"(\w+)\s+high\s+court", ln, re.IGNORECASE)
            bench_city = m2.group(1).title() + " HC" if m2 else "HC"
            break
        if "income tax appellate tribunal" in ln_lower:
            court_type = "ITAT"
            m3 = re.search(
                r"income\s+tax\s+appellate\s+tribunal\s*[–\-—]\s*(\w+)", ln, re.IGNORECASE
            )
            bench_city = m3.group(1).title() if m3 else ""
            break

    # Fallback bench from filename: ITA_No.XXXX_Hyd_2025.txt
    if not bench_city:
        fn_parts = path.stem.split("_")
        for part in fn_parts:
            if part in _BENCH_MAP:
                bench_city = _BENCH_MAP[part]
                break
            if part.title() in _BENCH_MAP:
                bench_city = _BENCH_MAP[part.title()]
                break

    bench = f"ITAT {bench_city}" if court_type == "ITAT" and bench_city else bench_city or court_type

    # ── Year ──────────────────────────────────────────────────────────────────
    year = 0
    # Try ITA number year from filename (last numeric part before .txt)
    m_yr = re.search(r"_(\d{4})(?:_\d+)?$", path.stem)
    if m_yr:
        yr = int(m_yr.group(1))
        if 1990 <= yr <= 2030:
            year = yr

    if not year:
        # Try from text: "on DD Month, YYYY" or "dated DD/MM/YYYY"
        for m_yr2 in re.finditer(r"\b(20[0-2]\d|199\d)\b", text[:2000]):
            yr = int(m_yr2.group(1))
            if 1990 <= yr <= 2030:
                year = yr
                break

    # ── Party names → case citation ───────────────────────────────────────────
    appellant = ""
    respondent = ""
    # Look for "X vs Y" or "X v. Y" in first 30 lines
    for ln in lines[4:30]:
        m_vs = re.search(
            r"^(.{5,60}?)\s+[Vv][Ss]?\.?\s+(.{5,60}?)$", ln.strip()
        )
        if m_vs:
            a = _clean_party(m_vs.group(1))
            r = _clean_party(m_vs.group(2))
            if a and r and len(a) > 3 and len(r) > 3:
                appellant  = a[:80]
                respondent = r[:80]
                break

    if not appellant:
        # Fallback: use filename stem as citation base
        appellant = path.stem.replace("_", " ")[:60]

    case_citation = _build_citation(appellant, respondent, year, bench, ik_tid)

    # ── Sections ──────────────────────────────────────────────────────────────
    all_sections = _extract_sections(text)
    sections_json = json.dumps(all_sections)

    # Primary section = first non-procedural, else first of any
    primary_section = ""
    for s in all_sections:
        if s not in _PROCEDURAL:
            primary_section = s
            break
    if not primary_section and all_sections:
        primary_section = all_sections[0]

    # ── Win / loss ────────────────────────────────────────────────────────────
    tail = text[-3000:]
    win_score  = sum(1 for pat in _WIN_RE  if pat.search(tail))
    loss_score = sum(1 for pat in _LOSS_RE if pat.search(tail))
    win_for_assessee = 1 if win_score >= loss_score else 0

    # ── Key ratio — paragraph containing holding language ─────────────────────
    key_ratio = _extract_ratio(text)

    # ── Facts summary — first substantial paragraph after ORDER heading ───────
    facts_summary = _extract_facts(text)

    # ── Outcome label ─────────────────────────────────────────────────────────
    outcome = "Assessee won" if win_for_assessee else "Revenue won"

    docs_accepted = _extract_documents_accepted(text)

    return {
        "case_citation":      case_citation,
        "section":            primary_section,
        "bench":              bench,
        "year":               year,
        "outcome":            outcome,
        "key_ratio":          key_ratio[:3000],
        "facts_summary":      facts_summary[:1000],
        "win_for_assessee":   win_for_assessee,
        "relevance_score":    0.0,
        "ik_tid":             ik_tid,
        "ik_url":             ik_url,
        "court_type":         court_type,
        "verified":           2,
        "sections_json":      sections_json,
        "source_name":        "raw_txt_ingest",
        "source_url":         ik_url,
        "harvested_at":       datetime.utcnow().isoformat(),
        "documents_accepted": json.dumps(docs_accepted),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clean_party(name: str) -> str:
    """Strip ITA numbers, bench codes, noise from party names."""
    name = re.sub(r"\bITA\s+No\.?.*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(Appellant|Respondent|Petitioner|vs?\.?)\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9 &.,()/-]", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip(" .,")
    return name


def _build_citation(appellant: str, respondent: str, year: int,
                    bench: str, ik_tid: str) -> str:
    yr_str = str(year) if year else "XXXX"
    if respondent:
        base = f"{appellant} vs {respondent} [{yr_str}] {bench}"
    else:
        base = f"{appellant} [{yr_str}] {bench}"
    # Append IK tid to guarantee uniqueness even if party names are identical
    if ik_tid:
        base += f" (IK:{ik_tid})"
    return base[:250]


def _extract_sections(text: str) -> list[str]:
    """Return deduplicated list of IT Act sections, most-cited first."""
    raw = _SEC_PAT.findall(text)
    counts: dict[str, int] = {}
    for sec in raw:
        sec = sec.strip().upper()
        # Basic sanity: number part must be 1–300ish
        num_m = re.match(r"^(\d+)", sec)
        if not num_m:
            continue
        num = int(num_m.group(1))
        if num < 1 or num > 299:
            continue
        counts[sec] = counts.get(sec, 0) + 1

    # Sort by count descending
    return [s for s, _ in sorted(counts.items(), key=lambda x: -x[1])]


def _extract_ratio(text: str) -> str:
    """
    Extract the tribunal's key holding.
    Strategy: scan paragraphs (separated by blank lines), score by ratio
    signal words, return highest-scoring paragraph in last 60% of text.
    """
    # Focus on last 60% — holding is always near the end
    start = int(len(text) * 0.40)
    tail  = text[start:]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", tail) if p.strip()]

    best_para  = ""
    best_score = 0

    for para in paragraphs:
        if len(para) < 60 or len(para) > 2000:
            continue
        score = sum(1 for sig in _RATIO_SIGNALS if sig.lower() in para.lower())
        if score > best_score:
            best_score = score
            best_para  = para

    if not best_para:
        # Fallback: last non-trivial paragraph before "Order pronounced"
        op_idx = tail.lower().rfind("order pronounced")
        if op_idx > 0:
            chunk = tail[:op_idx]
            paras = [p.strip() for p in re.split(r"\n\s*\n", chunk) if p.strip()]
            best_para = next((p for p in reversed(paras) if len(p) > 80), "")

    return re.sub(r"\s+", " ", best_para).strip()


def _extract_facts(text: str) -> str:
    """
    Extract the facts summary — first 800 chars of judgment body,
    starting after the ORDER / JUDGMENT header.
    """
    # Find start of substantive text
    for marker in ["ORDER\n", "JUDGMENT\n", "O R D E R\n", "PER "]:
        idx = text.find(marker)
        if idx != -1:
            body = text[idx + len(marker):].strip()
            # Skip page headers / case number repetitions (short lines at start)
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            substantive = []
            for ln in lines:
                if len(ln) > 40:
                    substantive.append(ln)
                if sum(len(s) for s in substantive) >= 800:
                    break
            return re.sub(r"\s+", " ", " ".join(substantive))[:800]

    return text[200:800].strip()


# Document-acceptance patterns found in ITAT orders
_DOC_ACCEPT_PATTERNS = [
    r"(?:accepted|admitted|considered|relied upon|found genuine|verified)\s+(?:the\s+)?([A-Z][A-Za-z &/\-]{5,60}(?:statement|ledger|certificate|affidavit|deed|agreement|return|receipt|voucher|bill|invoice|confirmation|letter|report|valuation|copy|extract|details))",
    r"([A-Z][A-Za-z &/\-]{5,60}(?:statement|ledger|certificate|affidavit|deed|agreement|return|receipt|voucher|bill|invoice|confirmation|letter|report|valuation|copy|extract|details))\s+(?:was|were|is|are)\s+(?:accepted|admitted|verified|found genuine|relied upon)",
]
_DOC_ACCEPT_RE = [re.compile(p, re.IGNORECASE) for p in _DOC_ACCEPT_PATTERNS]


def _extract_documents_accepted(text: str) -> list[str]:
    """
    Extract document names that were accepted/admitted in the tribunal order.
    Returns a deduplicated list of up to 15 document names.
    """
    seen: set[str] = set()
    results: list[str] = []
    for pat in _DOC_ACCEPT_RE:
        for m in pat.finditer(text):
            doc = m.group(1).strip().rstrip(".,;")
            key = doc.lower()
            if key not in seen and len(doc) > 8:
                seen.add(key)
                results.append(doc)
    return results[:15]


# ─────────────────────────────────────────────────────────────────────────────
# Database writer
# ─────────────────────────────────────────────────────────────────────────────

_INSERT_SQL = """
    INSERT OR IGNORE INTO itat_precedents
    (case_citation, section, bench, year, outcome, key_ratio, facts_summary,
     win_for_assessee, relevance_score, ik_tid, ik_url, court_type,
     verified, sections_json, source_name, source_url, harvested_at,
     documents_accepted)
    VALUES
    (:case_citation, :section, :bench, :year, :outcome, :key_ratio, :facts_summary,
     :win_for_assessee, :relevance_score, :ik_tid, :ik_url, :court_type,
     :verified, :sections_json, :source_name, :source_url, :harvested_at,
     :documents_accepted)
"""


def ingest(source_dir: str, db_path: str,
           limit: int = 0, dry_run: bool = False) -> dict:
    """
    Main ingestion loop.
    Returns stats dict: {found, parsed, inserted, skipped, errors}
    """
    from database.init_db import init_database
    init_database()

    source = Path(source_dir)
    if not source.exists():
        print(f"  ❌ Source directory not found: {source_dir}")
        return {}

    files = sorted(source.glob("*.txt"))
    if limit:
        files = files[:limit]

    total  = len(files)
    parsed = inserted = skipped = errors = 0

    conn = None if dry_run else sqlite3.connect(db_path)
    if conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

    print(f"\n  Source  : {source_dir}")
    print(f"  Files   : {total:,}" + (f"  (limit={limit})" if limit else ""))
    print(f"  Mode    : {'DRY RUN — no DB writes' if dry_run else 'LIVE — writing to DB'}")
    print(f"  DB      : {db_path}")
    print()

    batch      = []
    BATCH_SIZE = 100
    interval   = max(1, total // 40)   # progress every ~2.5%

    for i, fpath in enumerate(files, 1):
        try:
            record = parse_file(fpath)
            if not record:
                errors += 1
                continue

            parsed += 1

            if dry_run:
                skipped += 1
            else:
                batch.append(record)
                if len(batch) >= BATCH_SIZE:
                    n = _flush(conn, batch)
                    inserted += n
                    skipped  += len(batch) - n
                    batch = []

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  ⚠  Error on {fpath.name}: {e}")

        if i % interval == 0 or i == total:
            pct = i / total * 100
            pending = len(batch)
            print(f"  [{i:>5}/{total}  {pct:4.0f}%]  "
                  f"parsed={parsed}  inserted={inserted}(+{pending} pending)  "
                  f"errors={errors}")

    # Flush remaining
    if batch and not dry_run:
        n = _flush(conn, batch)
        inserted += n
        skipped  += len(batch) - n

    if conn:
        conn.commit()
        conn.close()

    return {
        "found":    total,
        "parsed":   parsed,
        "inserted": inserted,
        "skipped":  skipped,
        "errors":   errors,
    }


def _flush(conn: sqlite3.Connection, batch: list[dict]) -> int:
    """Insert a batch. Returns count of rows actually inserted."""
    cur = conn.cursor()
    before = conn.execute(
        "SELECT COUNT(*) FROM itat_precedents"
    ).fetchone()[0]
    cur.executemany(_INSERT_SQL, batch)
    conn.commit()
    after = conn.execute(
        "SELECT COUNT(*) FROM itat_precedents"
    ).fetchone()[0]
    return after - before


# ─────────────────────────────────────────────────────────────────────────────
# Status command
# ─────────────────────────────────────────────────────────────────────────────

def cmd_status(db_path: str, source_dir: str):
    print("\n  ── Ingestion Status ──────────────────────────────")
    source = Path(source_dir)
    txt_count = len(list(source.glob("*.txt"))) if source.exists() else 0
    print(f"  .txt files in source dir : {txt_count:,}")

    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM itat_precedents WHERE verified IN (1,2)")
        total = cur.fetchone()[0]
        print(f"  itat_precedents total    : {total:,}")

        cur.execute("SELECT COUNT(*) FROM itat_precedents WHERE source_name='raw_txt_ingest'")
        ingested = cur.fetchone()[0]
        print(f"  ingested from .txt files : {ingested:,}")

        cur.execute("""
            SELECT court_type, COUNT(*) as cnt
            FROM itat_precedents WHERE source_name='raw_txt_ingest'
            GROUP BY court_type ORDER BY cnt DESC
        """)
        rows = cur.fetchall()
        if rows:
            print(f"\n  Court breakdown (ingested):")
            for row in rows:
                print(f"    {row[0] or 'unknown':8} : {row[1]:,}")

        cur.execute("""
            SELECT section, COUNT(*) as cnt
            FROM itat_precedents
            WHERE source_name='raw_txt_ingest'
              AND section != ''
            GROUP BY section ORDER BY cnt DESC LIMIT 20
        """)
        rows = cur.fetchall()
        if rows:
            print(f"\n  Top 20 sections (ingested):")
            for row in rows:
                print(f"    §{row[0]:12} : {row[1]:,}")

        conn.close()
    except Exception as e:
        print(f"  ❌ DB error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import config

    parser = argparse.ArgumentParser(
        description="Ingest raw ITAT .txt files into itat_precedents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_ingest.py                      # ingest all files
  python run_ingest.py --dry-run            # test parsing without DB writes
  python run_ingest.py --limit 100          # ingest first 100 files only
  python run_ingest.py --status             # show current DB state
  python run_ingest.py --source-dir "D:/cases"  # custom source dir
        """,
    )
    parser.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR,
                        help="Directory containing .txt ITAT files")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Parse files but do not write to DB")
    parser.add_argument("--limit",    type=int, default=0,
                        help="Max files to process (0 = all)")
    parser.add_argument("--status",   action="store_true",
                        help="Show current ingestion status and exit")
    args = parser.parse_args()

    db_path = config.DB_PATH

    if args.status:
        cmd_status(db_path, args.source_dir)
        return

    print("\n" + "═" * 60)
    print("  ITAT Case Ingestion Pipeline")
    print("═" * 60)

    start = datetime.now()
    stats = ingest(
        source_dir = args.source_dir,
        db_path    = db_path,
        limit      = args.limit,
        dry_run    = args.dry_run,
    )

    elapsed = (datetime.now() - start).total_seconds()

    print("\n" + "─" * 60)
    print("  Ingestion complete")
    print("─" * 60)
    print(f"  Files found    : {stats.get('found',    0):,}")
    print(f"  Successfully parsed  : {stats.get('parsed',   0):,}")
    print(f"  Inserted into DB     : {stats.get('inserted', 0):,}")
    print(f"  Already existed (skip): {stats.get('skipped', 0):,}")
    print(f"  Errors               : {stats.get('errors',   0):,}")
    print(f"  Time taken           : {elapsed:.1f}s")

    if not args.dry_run and stats.get("inserted", 0) > 0:
        print("\n  ✅  Next step — build the embedding index:")
        print("       python run_embed.py --sync")
        print("\n  Once indexed, Phase 2 will automatically use these")
        print("  6000+ cases for evidence retrieval via the RAG pipeline.")
    elif args.dry_run:
        print("\n  (dry run — no changes made to DB)")


if __name__ == "__main__":
    main()
