import json
import re
from datetime import datetime, timedelta


def format_currency(amount: float) -> str:
    if amount >= 10_000_000:
        return f"₹{amount / 10_000_000:.2f} Cr"
    elif amount >= 100_000:
        return f"₹{amount / 100_000:.2f} L"
    else:
        return f"₹{amount:,.0f}"


def parse_sections(sections_str) -> list:
    if isinstance(sections_str, list):
        return sections_str
    if not sections_str:
        return []
    try:
        return json.loads(sections_str)
    except (json.JSONDecodeError, TypeError):
        return [s.strip() for s in sections_str.split(',') if s.strip()]


def generate_timeline(case_created_date: str, hearing_date: str = None) -> list:
    try:
        start = datetime.strptime(case_created_date[:10], "%Y-%m-%d")
    except Exception:
        start = datetime.now()

    tasks = [
        (1, "File Appearance & Vakalatnama", "Submit signed vakalatnama before the tribunal bench", 1),
        (2, "Obtain Case File from AO", "Collect complete assessment file including seized documents", 1),
        (3, "Prepare Section-wise Analysis", "Map each violated section to available defences", 1),
        (5, "Gather Primary Evidence", "Collect cash book, ledgers, bank statements, confirmation letters", 2),
        (7, "Send Notices to Witnesses/Creditors", "Issue notices requesting affidavits and confirmations", 2),
        (10, "ITR Verification of Creditors", "Verify and collect ITRs of all loan creditors", 2),
        (12, "Run AI Evidence Validation", "Upload all documents for OCR and AI defect checking", 2),
        (14, "Draft Grounds of Appeal", "Prepare comprehensive grounds covering all sections", 3),
        (16, "Prepare Written Submissions", "Draft detailed written submissions with all citations", 3),
        (18, "Adversarial Simulation", "Run AI simulation of DR's strongest arguments", 4),
        (20, "Compile Paper Book", "Assemble all evidence documents in proper order", 4),
        (22, "File Additional Grounds (if needed)", "File any supplementary grounds before deadline", 5),
        (25, "Final Evidence Gap Check", "Run final AI scan for any missing critical documents", 6),
        (28, "War Room Briefing Preparation", "Prepare day-before-hearing final brief", 10),
        (29, "War Room Session", "Conduct final War Room session with full team", 10),
        (30, "Hearing Day", "Appear before ITAT bench with complete preparation", 10),
    ]

    result = []
    for day, title, desc, phase in tasks:
        due = start + timedelta(days=day)
        result.append({
            "day_number": day,
            "task_title": title,
            "task_description": desc,
            "due_date": due.strftime("%Y-%m-%d"),
            "phase": phase,
            "status": "pending",
        })
    return result


def calculate_overall_win_rate(evidence_items: list, base_rate: float = 45.0) -> dict:
    available = [e for e in evidence_items if e.get("status") == "available"]
    pending = [e for e in evidence_items if e.get("status") == "pending"]
    unavailable = [e for e in evidence_items if e.get("status") == "unavailable"]

    boost = sum(e.get("win_boost", 0) for e in available)
    penalty = sum(e.get("win_boost", 0) * 0.5 for e in unavailable if e.get("is_mandatory"))

    final_rate = min(95.0, max(5.0, base_rate + boost - penalty))

    return {
        "win_probability": round(final_rate, 1),
        "available_count": len(available),
        "pending_count": len(pending),
        "unavailable_count": len(unavailable),
        "total_boost": boost,
        "total_penalty": penalty,
        "risk_level": "HIGH" if final_rate < 40 else "MEDIUM" if final_rate < 65 else "LOW",
    }


def get_phase_name(phase: int) -> str:
    names = {
        1: "Phase 1: Case Intake",
        2: "Phase 2: Evidence Engine",
        3: "Phase 3: Knowledge Harvester",
        4: "Phase 4: Strategy Simulator",
        5: "Phase 5: Win-Rate Calculator",
        6: "Phase 6: Evidence Vacuum",
        7: "Phase 7: Master Architect",
        8: "Phase 8: Day 2-30 Workflow",
        9: "Phase 9: Mid-Trial Dynamics",
        10: "Phase 10: War Room",
        11: "Phase 11: Post-Hearing",
        12: "Phase 12: Continuous Learning",
    }
    return names.get(phase, f"Phase {phase}")


def clean_ai_response(text: str) -> str:
    text = re.sub(r'\[ERROR\].*', '', text).strip()
    return text


def section_badge_color(section: str) -> str:
    high_risk = {"153A", "271(1)(c)", "68", "69"}
    medium_risk = {"269SS", "271D", "269T", "271E"}
    low_risk = {"40A(3)", "14A", "56(2)"}
    if section in high_risk:
        return "#FF4444"
    elif section in medium_risk:
        return "#FF8800"
    return "#22AA44"
