"""
Citation Database Harvester — run this ONCE to populate the DB with 6000+ citations.

Run from the Litigation OS root directory:
    python run_harvest.py                    # full harvest (all 46 sections)
    python run_harvest.py --section 269SS    # single section only
    python run_harvest.py --ik-only          # Indian Kanoon API only
    python run_harvest.py --web-only         # Web sources only (itatonline/TaxGuru/etc)
    python run_harvest.py --status           # show current DB count + breakdown

This script runs outside Streamlit — no event loop conflicts, no timeouts.
Leave it running in a terminal; it prints progress live.

Expected time:
    Full IK harvest:   90-120 minutes  (~120 sections × 5 queries × 6 pages × 0.6s)
    Full web harvest:  15-25 minutes   (8 sources, rate-limited)
    Total:             ~2 hours for 15,000+ citations across 120 IT Act sections
"""

import sys
import os
import argparse
import time
from datetime import datetime

# ── Setup path ────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# ── Load .env ─────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except ImportError:
    pass  # dotenv optional — keys can be set as env vars directly


def _banner(text: str, char: str = "─"):
    width = 70
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}")


def _progress(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def cmd_status():
    """Show current DB state."""
    from ai.citation_harvester import get_citation_count, HARVEST_TARGETS
    from database.queries import get_statistics
    from database.init_db import get_connection

    total = get_citation_count()
    stats = get_statistics()

    _banner("Citation DB Status")
    print(f"  Total verified citations : {total:,}")
    print(f"  Sections covered         : {len(HARVEST_TARGETS)}")
    print(f"  CBDT circulars           : {stats.get('total_circulars', 0):,}")
    print(f"  Total precedents (all)   : {stats.get('total_precedents', 0):,}")

    # Per-section breakdown
    conn = get_connection()
    cur  = conn.cursor()
    print(f"\n  {'Section':<14} {'Citations':>10}  {'SC':>5}  {'HC':>5}  {'ITAT':>6}")
    print(f"  {'─'*14} {'─'*10}  {'─'*5}  {'─'*5}  {'─'*6}")
    for section, _ in HARVEST_TARGETS:
        cur.execute(
            "SELECT COUNT(*) FROM itat_precedents WHERE section=? AND verified IN (1,2)",
            (section,)
        )
        cnt = cur.fetchone()[0]
        if cnt == 0:
            continue
        for ct in ("SC", "HC", "ITAT"):
            cur.execute(
                "SELECT COUNT(*) FROM itat_precedents "
                "WHERE section=? AND court_type=? AND verified IN (1,2)",
                (section, ct)
            )
        cur.execute(
            "SELECT "
            "  SUM(CASE WHEN court_type='SC'   THEN 1 ELSE 0 END), "
            "  SUM(CASE WHEN court_type='HC'   THEN 1 ELSE 0 END), "
            "  SUM(CASE WHEN court_type='ITAT' THEN 1 ELSE 0 END) "
            "FROM itat_precedents WHERE section=? AND verified IN (1,2)",
            (section,)
        )
        row = cur.fetchone()
        sc, hc, itat = row[0] or 0, row[1] or 0, row[2] or 0
        bar = "█" * min(20, cnt // 10)
        print(f"  {section:<14} {cnt:>10,}  {sc:>5}  {hc:>5}  {itat:>6}  {bar}")
    conn.close()

    target = 15000
    pct = min(100, total * 100 // target)
    print(f"\n  Progress to 15,000 target: [{('█' * (pct // 5)).ljust(20)}] {pct}%")
    if total < target:
        print(f"  → Need {target - total:,} more. Run: python run_harvest.py")
    else:
        print(f"  ✅ Target reached! All 120 sections fully populated.")


def cmd_ik_harvest(section_filter: str = None):
    """Run Indian Kanoon API harvest."""
    from ai.citation_harvester import harvest_all, harvest_section, HARVEST_TARGETS, get_citation_count
    from database.init_db import init_database

    # Ensure DB schema is up to date
    init_database()

    before = get_citation_count()
    _banner("Indian Kanoon API Harvest", "═")
    print(f"  Starting DB count: {before:,}")

    if section_filter:
        queries_for_section = next(
            (q for s, q in HARVEST_TARGETS if s == section_filter), None
        )
        if not queries_for_section:
            print(f"  ❌ Section '{section_filter}' not found in HARVEST_TARGETS")
            print(f"  Available: {', '.join(s for s, _ in HARVEST_TARGETS)}")
            return
        _banner(f"Harvesting § {section_filter} only")
        added = harvest_section(section_filter, queries_for_section, _progress)
        after = get_citation_count()
        print(f"\n  ✅ Done — added {added} new | total now: {after:,}")
    else:
        sections_count = len(HARVEST_TARGETS)
        total_queries  = sum(len(q) for _, q in HARVEST_TARGETS)
        print(f"  Sections to harvest : {sections_count}")
        print(f"  Total search queries: {total_queries}")
        print(f"  Pages per query     : 6")
        print(f"  Results per page    : 10")
        print(f"  Est. raw results    : ~{total_queries * 6 * 10:,}")
        print(f"  API delay           : 0.6s per call")
        est_mins = (total_queries * 6 * 0.6) / 60
        print(f"  Est. time           : ~{est_mins:.0f} minutes")
        print(f"\n  Starting in 3 seconds — Ctrl+C to abort...")
        time.sleep(3)

        start = time.time()
        summary = harvest_all(_progress)
        elapsed = time.time() - start

        after = get_citation_count()
        added = summary["total_added"]

        _banner("Harvest Complete ✅", "═")
        print(f"  New citations added : {added:,}")
        print(f"  Total in DB now     : {after:,}")
        print(f"  Time taken          : {elapsed/60:.1f} minutes")

        # Top sections by count
        print(f"\n  Top sections by additions:")
        top = sorted(summary["by_section"].items(), key=lambda x: -x[1])[:10]
        for sec, cnt in top:
            if cnt > 0:
                print(f"    § {sec:<14} +{cnt}")


def cmd_web_harvest(max_pages: int = 10):
    """
    Run web sources harvest (itatonline, TaxGuru, Taxscan, CAclubindia).

    max_pages controls how many listing pages are scraped per source:
      10 pages → ~3,000-4,000 new citations   (20-30 min)
      30 pages → ~8,000-10,000 new citations  (60-80 min)
      50 pages → ~12,000+ new citations       (2+ hours)

    TaxGuru ITAT alone has 6,700+ pages — so there is essentially no ceiling
    from the web side.
    """
    try:
        from ai.scrapers.multi_source_harvester import (
            harvest_all_sources, get_scraped_count
        )
    except ImportError as e:
        print(f"  ❌ Web harvester not available: {e}")
        return

    from database.init_db import init_database
    init_database()

    before = get_scraped_count()
    _banner("Web Sources Harvest", "═")
    print(f"  Sources : itatonline · TaxGuru ITAT/HC/SC · Taxscan · CAclubindia · CBDT")
    print(f"  Pages   : {max_pages} per source")
    print(f"  Est. new: {max_pages * 60:,}–{max_pages * 100:,} citations")
    print(f"  Est. time: {max_pages * 1.2 / 60:.0f}–{max_pages * 1.5 / 60:.0f} minutes")
    print(f"  DB now  : {before:,} web-scraped citations already in DB")
    print(f"\n  Starting in 3 seconds — Ctrl+C to abort...")
    time.sleep(3)

    start = time.time()
    try:
        summary = harvest_all_sources(max_pages=max_pages, progress_cb=_progress)
        elapsed = time.time() - start
        after   = get_scraped_count()

        _banner("Web Harvest Complete ✅", "═")
        print(f"  New citations added : {after - before:,}")
        print(f"  Total web-scraped   : {after:,}")
        print(f"  Time taken          : {elapsed/60:.1f} minutes")
        print(f"\n  Per-source breakdown:")
        for key, result in summary.items():
            if isinstance(result, dict) and "added" in result:
                added   = result.get("added", 0)
                skipped = result.get("skipped", 0)
                err     = result.get("error", "")
                status  = f"❌ {err[:50]}" if err else f"+{added:,} new, {skipped:,} skip"
                print(f"    {key:<30} {status}")
    except Exception as e:
        print(f"  ❌ Web harvest error: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description="Populate the Litigation OS citation database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_harvest.py --web-only               # web sources, 10 pages each (~30 min)
  python run_harvest.py --web-only --pages 30    # deep web harvest (~8,000 new, ~70 min)
  python run_harvest.py --web-only --pages 50    # full web harvest (~12,000+ new, ~2 hrs)
  python run_harvest.py --ik-only                # Indian Kanoon API only
  python run_harvest.py --section 269SS          # one section from IK
  python run_harvest.py --status                 # show current DB count
        """
    )
    parser.add_argument("--ik-only",  action="store_true", help="Indian Kanoon API harvest only")
    parser.add_argument("--web-only", action="store_true", help="Web sources harvest only")
    parser.add_argument("--section",  type=str, default=None,
                        help="Harvest a single section from IK (e.g. 269SS)")
    parser.add_argument("--status",   action="store_true", help="Show DB status and exit")
    parser.add_argument("--pages",    type=int, default=10,
                        help="Pages per web source (default: 10, max meaningful: 50+)")
    args = parser.parse_args()

    if args.status:
        cmd_status()
        return

    if args.section:
        cmd_ik_harvest(section_filter=args.section.strip())
        return

    if args.web_only:
        cmd_web_harvest(max_pages=args.pages)
    elif args.ik_only:
        cmd_ik_harvest()
    else:
        # Full harvest: IK first, then web
        cmd_ik_harvest()
        print("\n")
        cmd_web_harvest(max_pages=args.pages)
        print("\n")
        cmd_status()


if __name__ == "__main__":
    main()
