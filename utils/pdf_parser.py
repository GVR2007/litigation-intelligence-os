import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_OCR_WORD_THRESHOLD = 80   # if extracted text has fewer words → assume scanned PDF → OCR


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text from PDF.
    If the PDF is image-based (scanned), automatically falls back to OCR
    via Gemini Vision — no extra library install needed.
    """
    text = _extract_native(pdf_path)

    # Scanned PDF detection — too few words means no text layer
    if len(text.split()) < _OCR_WORD_THRESHOLD:
        ocr_text = _ocr_with_gemini(pdf_path)
        if ocr_text and len(ocr_text.split()) > len(text.split()):
            return ocr_text

    return text


def _extract_native(pdf_path: str) -> str:
    """Native text extraction — PyMuPDF or pdfplumber."""
    try:
        import fitz
        doc  = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if text.strip():
            return text
    except ImportError:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass
    return ""


def _ocr_with_gemini(pdf_path: str) -> str:
    """
    OCR fallback using Gemini Vision API — no extra install needed.
    Converts each PDF page to a PNG image and sends to Gemini for text extraction.
    Works on scanned AO orders, notices, printed PDFs — anything without a text layer.
    """
    try:
        import fitz
        import base64
        import requests
        import config

        key = getattr(config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
        if not key:
            return ""

        doc   = fitz.open(pdf_path)
        pages = list(doc)[:15]          # cap at 15 pages to stay within limits
        texts = []

        for i, page in enumerate(pages):
            pix      = page.get_pixmap(dpi=200)
            img_b64  = base64.b64encode(pix.tobytes("png")).decode()

            payload = {
                "contents": [{
                    "parts": [
                        {
                            "text": (
                                "This is a page from an Indian income tax assessment order or "
                                "penalty notice. Extract ALL text exactly as written — "
                                "preserve section numbers, amounts, names, dates. "
                                "Return only the extracted text, nothing else."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": img_b64,
                            }
                        },
                    ]
                }],
                "generationConfig": {"temperature": 0},
            }

            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.0-flash:generateContent?key={key}",
                json=payload,
                timeout=30,
            )
            if resp.status_code == 200:
                page_text = (
                    resp.json()
                    .get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if page_text:
                    texts.append(page_text)

        doc.close()
        return "\n\n".join(texts)

    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# MASTER SECTION PATTERN TABLE
# Each entry: (canonical_section_name, [regex_pattern, ...])
# Patterns use re.IGNORECASE. Multiple patterns per section — first match wins.
# For ambiguous numbers (68, 69, 147 etc.) we require "section/u/s/sec." prefix
# to avoid false matches on page numbers, amounts, dates etc.
# ─────────────────────────────────────────────────────────────────────────────
_SEC = r"(?:section|sec\.?|u/?s\.?|under\s+section|provisions?\s+of\s+(?:section)?|as\s+per\s+section)"

_SECTION_PATTERNS = [

    # ── DEFINITIONS ────────────────────────────────────────────────────────
    ("2(14)",     [rf"{_SEC}\s*2\s*\(\s*14\s*\)", r"\bcapital\s+asset\b.*\bdefinition\b"]),
    ("2(22)(e)",  [rf"{_SEC}\s*2\s*\(\s*22\s*\)\s*\(\s*e\s*\)", r"\bdeemed\s+dividend\b", r"loan.*shareholder.*deemed"]),
    ("2(47)",     [rf"{_SEC}\s*2\s*\(\s*47\s*\)", r"\bdefinition\s+of\s+transfer\b"]),

    # ── RESIDENTIAL STATUS & SCOPE ─────────────────────────────────────────
    ("5",         [rf"{_SEC}\s*5\b", r"scope\s+of\s+total\s+income"]),
    ("6",         [rf"{_SEC}\s*6\b", r"residential\s+status", r"resident.*india.*days"]),
    ("9",         [rf"{_SEC}\s*9\b", r"income\s+deemed\s+to\s+accrue", r"deemed\s+to\s+arise\s+in\s+india"]),
    ("9A",        [rf"{_SEC}\s*9\s*A\b", r"offshore\s+fund.*PE", r"eligible\s+investment\s+fund"]),

    # ── EXEMPTIONS ─────────────────────────────────────────────────────────
    ("10",        [rf"{_SEC}\s*10\b(?!\s*A\b)(?!\s*AA\b)(?!\s*B\b)", r"income\s+not\s+included.*total\s+income"]),
    ("10A",       [rf"{_SEC}\s*10\s*A\b(?!\s*A\b)", r"export.oriented\s+undertaking"]),
    ("10AA",      [rf"{_SEC}\s*10\s*AA\b", r"SEZ\s+unit\s+deduction", r"special\s+economic\s+zone.*deduction"]),
    ("10B",       [rf"{_SEC}\s*10\s*B\b", r"100\s*%\s*export\s+oriented\s+undertaking"]),

    # ── CHARITABLE TRUSTS ──────────────────────────────────────────────────
    ("11",        [rf"{_SEC}\s*11\b", r"income.*property.*charitable.*religious", r"85\s*%\s*application"]),
    ("12",        [rf"{_SEC}\s*12\b(?!\s*A\b)(?!\s*AA\b)(?!\s*AB\b)", r"voluntary\s+contribution.*trust"]),
    ("12A",       [rf"{_SEC}\s*12\s*A\b(?!\s*A\b)(?!\s*B\b)", r"registration.*trust.*12\s*A"]),
    ("12AA",      [rf"{_SEC}\s*12\s*AA\b", r"procedure.*registration.*trust"]),
    ("12AB",      [rf"{_SEC}\s*12\s*AB\b", r"fresh\s+registration.*trust", r"renewal.*trust.*registration"]),

    # ── SALARIES ───────────────────────────────────────────────────────────
    ("17",        [rf"{_SEC}\s*17\b", r"perquisite[s]?\s+taxable", r"profits\s+in\s+lieu\s+of\s+salary"]),

    # ── HOUSE PROPERTY ─────────────────────────────────────────────────────
    ("22",        [rf"{_SEC}\s*22\b", r"annual\s+value.*house\s+property"]),
    ("24",        [rf"{_SEC}\s*24\b", r"deduction.*house\s+property\s+income", r"interest.*home\s+loan.*deduction"]),

    # ── BUSINESS INCOME ────────────────────────────────────────────────────
    ("28",        [rf"{_SEC}\s*28\b", r"profits.*gains.*business.*profession.*chargeable"]),
    ("32",        [rf"{_SEC}\s*32\b", r"depreciation.*disallowed", r"additional\s+depreciation"]),
    ("35",        [rf"{_SEC}\s*35\b", r"scientific\s+research.*expenditure"]),
    ("36(1)(iii)",[rf"{_SEC}\s*36\s*\(\s*1\s*\)\s*\(\s*iii\s*\)", r"interest.*borrowed\s+capital.*disallow"]),
    ("36(1)(va)", [rf"{_SEC}\s*36\s*\(\s*1\s*\)\s*\(\s*va\s*\)", r"employee\s+contribution.*PF.*ESI.*disallow", r"employees.*provident\s+fund.*due\s+date"]),
    ("36(1)(vii)",[rf"{_SEC}\s*36\s*\(\s*1\s*\)\s*\(\s*vii\s*\)", r"bad\s+debt[s]?.*disallow"]),
    ("37(1)",     [rf"{_SEC}\s*37\s*\(\s*1\s*\)", r"\b37\s*\(\s*1\s*\)\b", r"general\s+deduction.*business\s+expenditure.*disallow"]),
    ("40(a)(i)",  [rf"{_SEC}\s*40\s*\(\s*a\s*\)\s*\(\s*i\s*\)", r"\b40\s*\(\s*a\s*\)\s*\(\s*i\s*\)", r"non.resident.*TDS.*disallow"]),
    ("40(a)(ia)", [rf"{_SEC}\s*40\s*\(\s*a\s*\)\s*\(\s*ia\s*\)", r"\b40\s*\(\s*a\s*\)\s*\(\s*ia\s*\)", r"TDS.*not\s+deducted.*disallowance\s+30"]),
    ("40(b)",     [rf"{_SEC}\s*40\s*\(\s*b\s*\)", r"\b40\s*\(\s*b\s*\)\b", r"partner.*remuneration.*disallow", r"salary.*partner.*excess"]),
    ("40A(2)",    [rf"{_SEC}\s*40\s*A\s*\(\s*2\s*\)", r"\b40\s*A\s*\(\s*2\s*\)\b", r"payment.*related\s+party.*disallow", r"specified\s+persons.*excessive"]),
    ("40A(3)",    [rf"{_SEC}\s*40\s*A\s*\(\s*3\s*\)", r"\b40\s*A\s*\(\s*3\s*\)\b", r"\b40\s*A\(3\)\b", r"cash\s+payment.*exceeding.*10,?000", r"cash\s+payment.*disallow.*40"]),
    ("40A(3A)",   [rf"{_SEC}\s*40\s*A\s*\(\s*3\s*A\s*\)", r"\b40\s*A\s*\(\s*3\s*A\s*\)\b"]),
    ("41",        [rf"{_SEC}\s*41\b", r"remission\s+of\s+liability", r"recovery\s+of\s+deduction.*earlier\s+year"]),
    ("43B",       [rf"{_SEC}\s*43\s*B\b", r"\b43\s*B\b", r"actual\s+payment.*PF.*ESI.*tax.*43"]),
    ("43CA",      [rf"{_SEC}\s*43\s*CA\b", r"\b43\s*CA\b", r"immovable\s+property.*stamp\s+duty.*business"]),

    # ── PRESUMPTIVE TAXATION ───────────────────────────────────────────────
    ("44AD",      [rf"{_SEC}\s*44\s*AD\b", r"\b44\s*AD\b", r"presumptive\s+taxation.*business"]),
    ("44ADA",     [rf"{_SEC}\s*44\s*ADA\b", r"\b44\s*ADA\b", r"presumptive.*professional"]),
    ("44AE",      [rf"{_SEC}\s*44\s*AE\b", r"\b44\s*AE\b", r"goods\s+carriage.*presumptive"]),

    # ── CAPITAL GAINS ──────────────────────────────────────────────────────
    ("45",        [rf"{_SEC}\s*45\b", r"capital\s+gains.*chargeable", r"long.term\s+capital\s+gain", r"short.term\s+capital\s+gain"]),
    ("47",        [rf"{_SEC}\s*47\b", r"transaction.*not\s+regarded\s+as\s+transfer", r"gift.*inheritance.*not.*transfer"]),
    ("50",        [rf"{_SEC}\s*50\b(?!\s*B\b)(?!\s*C\b)", r"depreciable\s+asset.*capital\s+gain"]),
    ("50B",       [rf"{_SEC}\s*50\s*B\b", r"\b50\s*B\b", r"slump\s+sale"]),
    ("50C",       [rf"{_SEC}\s*50\s*C\b", r"\b50\s*C\b", r"stamp\s+duty\s+value.*land.*building.*capital\s+gain", r"full\s+value.*consideration.*stamp"]),
    ("50CA",      [rf"{_SEC}\s*50\s*CA\b", r"\b50\s*CA\b", r"unquoted\s+shares.*fair\s+market\s+value"]),
    ("54",        [rf"{_SEC}\s*54\b(?!\s*B\b)(?!\s*EC\b)(?!\s*F\b)(?!\s*G\b)", r"exemption.*residential\s+house.*capital\s+gain(?!.*agricultural)"]),
    ("54B",       [rf"{_SEC}\s*54\s*B\b", r"\b54\s*B\b", r"exemption.*agricultural\s+land.*capital\s+gain"]),
    ("54EC",      [rf"{_SEC}\s*54\s*EC\b", r"\b54\s*EC\b", r"NHAI.*REC.*bonds.*exemption", r"capital\s+gain.*bonds.*six\s+month"]),
    ("54F",       [rf"{_SEC}\s*54\s*F\b", r"\b54\s*F\b", r"long.term.*capital\s+gain.*residential\s+house.*net\s+sale"]),

    # ── INCOME FROM OTHER SOURCES ──────────────────────────────────────────
    ("56(2)(i)",  [rf"{_SEC}\s*56\s*\(\s*2\s*\)\s*\(\s*i\s*\)", r"dividend.*income.*other\s+sources"]),
    ("56(2)(vii)",[rf"{_SEC}\s*56\s*\(\s*2\s*\)\s*\(\s*vii\s*\)(?!\s*[ab])", r"gift\s+received.*56.*vii\b"]),
    ("56(2)(x)",  [rf"{_SEC}\s*56\s*\(\s*2\s*\)\s*\(\s*x\s*\)", r"\b56\s*\(\s*2\s*\)\s*\(\s*x\s*\)", r"property.*received.*inadequate\s+consideration"]),
    ("56(2)(viib)",[rf"{_SEC}\s*56\s*\(\s*2\s*\)\s*\(\s*viib\s*\)", r"\b56\s*\(\s*2\s*\)\s*\(\s*viib\s*\)", r"angel\s+tax", r"shares.*issued.*above.*fair\s+market\s+value"]),
    ("2(22)(e)",  [rf"{_SEC}\s*2\s*\(\s*22\s*\)\s*\(\s*e\s*\)", r"deemed\s+dividend\b"]),

    # ── UNEXPLAINED INCOME / ADDITIONS ────────────────────────────────────
    ("68",        [rf"{_SEC}\s*68\b", r"\bu/?s\.?\s*68\b", r"unexplained\s+cash\s+credit", r"cash\s+credit[s]?\s+added", r"addition.*cash\s+credit"]),
    ("69",        [rf"{_SEC}\s*69\b(?!\s*A\b)(?!\s*B\b)(?!\s*C\b)(?!\s*D\b)", r"\bu/?s\.?\s*69\b(?!\s*[ABCD])", r"unexplained\s+investment"]),
    ("69A",       [rf"{_SEC}\s*69\s*A\b", r"\bu/?s\.?\s*69\s*A\b", r"unexplained\s+money", r"unexplained\s+jewellery", r"unexplained\s+bullion"]),
    ("69B",       [rf"{_SEC}\s*69\s*B\b", r"\bu/?s\.?\s*69\s*B\b", r"investment\s+not\s+fully\s+disclosed"]),
    ("69C",       [rf"{_SEC}\s*69\s*C\b", r"\bu/?s\.?\s*69\s*C\b", r"unexplained\s+expenditure"]),
    ("69D",       [rf"{_SEC}\s*69\s*D\b", r"\bu/?s\.?\s*69\s*D\b", r"amount\s+borrowed.*hundi", r"hundi\s+transaction"]),
    ("115BBE",    [rf"{_SEC}\s*115\s*BBE\b", r"\b115\s*BBE\b", r"60\s*%.*tax.*unexplained", r"tax.*unexplained\s+income.*115"]),

    # ── CASH TRANSACTION VIOLATIONS ───────────────────────────────────────
    ("269SS",     [rf"{_SEC}\s*269\s*[-–]?\s*SS\b", r"\b269\s*SS\b", r"cash\s+loan.*269", r"acceptance.*cash.*loan.*violation"]),
    ("269ST",     [rf"{_SEC}\s*269\s*[-–]?\s*ST\b", r"\b269\s*ST\b", r"cash\s+receipt.*2\s*lakh", r"receipt.*exceeding.*2,?00,?000.*cash"]),
    ("269T",      [rf"{_SEC}\s*269\s*[-–]?\s*T\b", r"\b269\s*T\b(?!\s*[A-Z])", r"repayment.*loan.*cash.*269", r"cash\s+repayment.*violation"]),
    ("269SU",     [rf"{_SEC}\s*269\s*SU\b", r"\b269\s*SU\b", r"prescribed\s+electronic\s+modes.*acceptance"]),
    ("271D",      [rf"{_SEC}\s*271\s*[-–]?\s*D\b", r"\b271\s*D\b", r"penalty.*269\s*SS", r"penalty.*cash\s+loan"]),
    ("271DA",     [rf"{_SEC}\s*271\s*DA\b", r"\b271\s*DA\b", r"penalty.*269\s*ST"]),
    ("271E",      [rf"{_SEC}\s*271\s*[-–]?\s*E\b", r"\b271\s*E\b", r"penalty.*269\s*T"]),

    # ── TDS / TCS ──────────────────────────────────────────────────────────
    ("192",       [rf"{_SEC}\s*192\b", r"\b192\b.*TDS.*salary", r"TDS.*salary.*192"]),
    ("193",       [rf"{_SEC}\s*193\b", r"TDS.*interest.*securities"]),
    ("194",       [rf"{_SEC}\s*194\b(?!\s*[A-Z])", r"TDS.*dividend.*194\b"]),
    ("194A",      [rf"{_SEC}\s*194\s*A\b", r"\b194\s*A\b", r"TDS.*interest.*(?:other\s+than|not\s+on)\s+securities"]),
    ("194C",      [rf"{_SEC}\s*194\s*C\b", r"\b194\s*C\b", r"TDS.*contract.*194\s*C"]),
    ("194D",      [rf"{_SEC}\s*194\s*D\b", r"\b194\s*D\b", r"TDS.*insurance\s+commission"]),
    ("194H",      [rf"{_SEC}\s*194\s*H\b", r"\b194\s*H\b", r"TDS.*commission.*brokerage.*194"]),
    ("194I",      [rf"{_SEC}\s*194\s*I\b(?!\s*A\b)(?!\s*B\b)(?!\s*C\b)", r"\b194\s*I\b(?!\s*[ABC])", r"TDS.*rent.*194\s*I\b"]),
    ("194IA",     [rf"{_SEC}\s*194\s*IA\b", r"\b194\s*IA\b", r"TDS.*immovable\s+property.*194"]),
    ("194IB",     [rf"{_SEC}\s*194\s*IB\b", r"\b194\s*IB\b", r"TDS.*rent.*individual.*194\s*IB"]),
    ("194IC",     [rf"{_SEC}\s*194\s*IC\b", r"\b194\s*IC\b", r"TDS.*joint\s+development\s+agreement"]),
    ("194J",      [rf"{_SEC}\s*194\s*J\b", r"\b194\s*J\b", r"TDS.*professional\s+fees", r"TDS.*technical\s+services.*194"]),
    ("194M",      [rf"{_SEC}\s*194\s*M\b", r"\b194\s*M\b"]),
    ("194N",      [rf"{_SEC}\s*194\s*N\b", r"\b194\s*N\b", r"TDS.*cash\s+withdrawal"]),
    ("194O",      [rf"{_SEC}\s*194\s*O\b", r"\b194\s*O\b", r"TDS.*e.commerce"]),
    ("194Q",      [rf"{_SEC}\s*194\s*Q\b", r"\b194\s*Q\b", r"TDS.*purchase.*goods.*194\s*Q"]),
    ("195",       [rf"{_SEC}\s*195\b", r"\b195\b.*non.resident", r"TDS.*non.resident.*195", r"remittance.*non.resident.*TDS"]),
    ("200",       [rf"{_SEC}\s*200\b", r"duty.*deduct.*deposit.*TDS"]),
    ("201",       [rf"{_SEC}\s*201\b", r"\b201\b.*assessee\s+in\s+default", r"failure.*deduct.*TDS.*default"]),
    ("206C",      [rf"{_SEC}\s*206\s*C\b", r"\b206\s*C\b", r"tax\s+collection\s+at\s+source", r"TCS.*206"]),
    ("234E",      [rf"{_SEC}\s*234\s*E\b", r"\b234\s*E\b", r"fee.*late\s+filing.*TDS.*return"]),

    # ── ASSESSMENT PROCEDURE ───────────────────────────────────────────────
    ("131",       [rf"{_SEC}\s*131\b", r"power.*discovery.*production.*evidence"]),
    ("132",       [rf"{_SEC}\s*132\b(?!\s*A\b)", r"search\s+and\s+seizure\b", r"search\s+conducted.*132"]),
    ("132A",      [rf"{_SEC}\s*132\s*A\b", r"power.*requisition.*books"]),
    ("133",       [rf"{_SEC}\s*133\b(?!\s*A\b)(?!\s*B\b)", r"power.*call.*information.*133\b"]),
    ("133A",      [rf"{_SEC}\s*133\s*A\b", r"power\s+of\s+survey\b", r"survey.*conducted.*133\s*A"]),
    ("133B",      [rf"{_SEC}\s*133\s*B\b", r"power.*collect.*information.*133\s*B"]),
    ("139",       [rf"{_SEC}\s*139\b(?!\s*A\b)", r"return\s+of\s+income.*filed", r"late\s+filing.*return"]),
    ("139(1)",    [rf"{_SEC}\s*139\s*\(\s*1\s*\)", r"mandatory\s+return.*filing"]),
    ("139A",      [rf"{_SEC}\s*139\s*A\b", r"PAN.*mandatory.*furnish"]),
    ("142",       [rf"{_SEC}\s*142\b(?!\s*A\b)", r"notice.*inquiry.*before\s+assessment"]),
    ("142A",      [rf"{_SEC}\s*142\s*A\b", r"DVO.*valuation", r"district\s+valuation\s+officer"]),
    ("143(1)",    [rf"{_SEC}\s*143\s*\(\s*1\s*\)", r"intimation.*143\s*\(1\)", r"processing.*return.*143"]),
    ("143(2)",    [rf"{_SEC}\s*143\s*\(\s*2\s*\)", r"notice.*scrutiny.*143\s*\(2\)"]),
    ("143(3)",    [rf"{_SEC}\s*143\s*\(\s*3\s*\)", r"scrutiny\s+assessment\b", r"assessment\s+order.*143\s*\(3\)"]),
    ("144",       [rf"{_SEC}\s*144\b(?!\s*A\b)(?!\s*B\b)", r"best\s+judgment\s+assessment"]),
    ("144A",      [rf"{_SEC}\s*144\s*A\b", r"special\s+audit.*direction"]),
    ("144B",      [rf"{_SEC}\s*144\s*B\b", r"\b144\s*B\b", r"faceless\s+assessment", r"NFAC.*assessment"]),
    ("145",       [rf"{_SEC}\s*145\b(?!\s*A\b)", r"method\s+of\s+accounting", r"accounting\s+method.*rejected"]),
    ("147",       [rf"{_SEC}\s*147\b", r"\bu/?s\.?\s*147\b", r"income.*escaping\s+assessment", r"escaped\s+assessment.*147", r"reassessment.*147"]),
    ("148",       [rf"{_SEC}\s*148\b(?!\s*A\b)", r"\bu/?s\.?\s*148\b(?!\s*A\b)", r"notice.*reassessment.*148\b", r"notice.*u/s\s*148\b"]),
    ("148A",      [rf"{_SEC}\s*148\s*A\b", r"\b148\s*A\b", r"show\s+cause\s+notice.*148\s*A", r"SCN.*148\s*A"]),
    ("149",       [rf"{_SEC}\s*149\b", r"time\s+limit.*reassessment\s+notice"]),
    ("153",       [rf"{_SEC}\s*153\b(?!\s*A\b)(?!\s*B\b)(?!\s*C\b)", r"time\s+limit.*completion.*assessment.*153\b"]),
    ("153A",      [rf"{_SEC}\s*153\s*A\b", r"\b153\s*A\b", r"assessment.*search.*153\s*A", r"search\s+assessment"]),
    ("153B",      [rf"{_SEC}\s*153\s*B\b", r"\b153\s*B\b", r"time\s+limit.*153\s*A\s+assessment"]),
    ("153C",      [rf"{_SEC}\s*153\s*C\b", r"\b153\s*C\b", r"assessment.*other\s+person.*search"]),
    ("154",       [rf"{_SEC}\s*154\b", r"rectification.*mistake.*apparent.*record"]),

    # ── APPEAL & REVISION ──────────────────────────────────────────────────
    ("246A",      [rf"{_SEC}\s*246\s*A\b", r"\b246\s*A\b", r"appeal.*CIT\s*\(A\).*246"]),
    ("250",       [rf"{_SEC}\s*250\b", r"procedure.*appeal.*CIT\s*\(A\)"]),
    ("251",       [rf"{_SEC}\s*251\b", r"powers\s+of\s+(?:CIT|Commissioner)\s*\(A\)", r"CIT\s*\(A\).*enhance"]),
    ("253",       [rf"{_SEC}\s*253\b", r"appeal.*ITAT", r"appeal.*Tribunal.*253"]),
    ("254",       [rf"{_SEC}\s*254\b", r"orders?\s+of\s+(?:the\s+)?(?:Appellate\s+)?Tribunal", r"ITAT.*order.*254", r"rectification.*ITAT.*254"]),
    ("260A",      [rf"{_SEC}\s*260\s*A\b", r"\b260\s*A\b", r"appeal.*High\s+Court.*substantial\s+question"]),
    ("261",       [rf"{_SEC}\s*261\b", r"appeal.*Supreme\s+Court.*261"]),
    ("263",       [rf"{_SEC}\s*263\b", r"revision.*(?:PCIT|CIT|Commissioner).*prejudicial", r"revisional\s+order.*263"]),
    ("264",       [rf"{_SEC}\s*264\b", r"revision.*favour\s+of\s+assessee"]),

    # ── PENALTIES ──────────────────────────────────────────────────────────
    ("270A",      [rf"{_SEC}\s*270\s*A\b", r"\b270\s*A\b", r"under.reporting\s+of\s+income", r"misreporting.*penalty", r"penalty.*under.report"]),
    ("271",       [rf"{_SEC}\s*271\b(?!\s*\(1\)\s*\(c\)\b)(?!\s*A\b)(?!\s*AA\b)(?!\s*B\b)(?!\s*C\b)(?!\s*D\b)(?!\s*E\b)(?!\s*F\b)(?!\s*G\b)(?!\s*H\b)(?!\s*J\b)(?!\s*DA\b)", r"penalty.*failure.*furnish\s+return"]),
    ("271(1)(c)", [rf"{_SEC}\s*271\s*\(\s*1\s*\)\s*\(\s*c\s*\)", r"\b271\s*\(\s*1\s*\)\s*\(\s*c\s*\)", r"concealment.*penalty", r"inaccurate\s+particulars.*penalty", r"penalty.*concealment"]),
    ("271A",      [rf"{_SEC}\s*271\s*A\b(?!\s*A\b)", r"\b271\s*A\b(?!\s*A\b)", r"penalty.*failure.*maintain.*books"]),
    ("271AA",     [rf"{_SEC}\s*271\s*AA\b(?!\s*A\b)(?!\s*B\b)(?!\s*C\b)", r"\b271\s*AA\b(?!\s*[ABC])", r"penalty.*transfer\s+pricing.*documentation\s+failure"]),
    ("271AAB",    [rf"{_SEC}\s*271\s*AAB\b", r"\b271\s*AAB\b", r"penalty.*undisclosed\s+income.*search"]),
    ("271AAC",    [rf"{_SEC}\s*271\s*AAC\b", r"\b271\s*AAC\b", r"penalty.*115\s*BBE"]),
    ("271B",      [rf"{_SEC}\s*271\s*B\b(?!\s*A\b)", r"\b271\s*B\b(?!\s*A\b)", r"penalty.*audit.*failure.*44\s*AB"]),
    ("271C",      [rf"{_SEC}\s*271\s*C\b(?!\s*A\b)", r"\b271\s*C\b(?!\s*A\b)", r"penalty.*failure.*deduct.*TDS"]),
    ("271CA",     [rf"{_SEC}\s*271\s*CA\b", r"\b271\s*CA\b", r"penalty.*failure.*collect.*TCS"]),
    ("271F",      [rf"{_SEC}\s*271\s*F\b(?!\s*A\b)(?!\s*B\b)", r"\b271\s*F\b(?!\s*[AB])", r"penalty.*PAN.*failure"]),
    ("271FA",     [rf"{_SEC}\s*271\s*FA\b(?!\s*A\b)(?!\s*B\b)", r"\b271\s*FA\b(?!\s*[AB])", r"penalty.*SFT.*failure"]),
    ("271G",      [rf"{_SEC}\s*271\s*G\b(?!\s*A\b)(?!\s*B\b)", r"\b271\s*G\b(?!\s*[AB])", r"penalty.*transfer\s+pricing.*info.*failure.*92\s*D"]),
    ("271H",      [rf"{_SEC}\s*271\s*H\b", r"\b271\s*H\b", r"penalty.*TDS.*TCS.*return.*failure"]),
    ("271J",      [rf"{_SEC}\s*271\s*J\b", r"\b271\s*J\b", r"penalty.*accountant.*incorrect\s+information"]),
    ("272A",      [rf"{_SEC}\s*272\s*A\b(?!\s*A\b)", r"\b272\s*A\b(?!\s*A\b)", r"penalty.*failure.*answer.*questions.*131"]),
    ("273B",      [rf"{_SEC}\s*273\s*B\b", r"\b273\s*B\b", r"reasonable\s+cause.*no\s+penalty", r"penalty\s+not\s+leviable.*reasonable\s+cause"]),

    # ── INTEREST ───────────────────────────────────────────────────────────
    ("234A",      [rf"{_SEC}\s*234\s*A\b", r"\b234\s*A\b", r"interest.*default.*furnishing\s+return"]),
    ("234B",      [rf"{_SEC}\s*234\s*B\b", r"\b234\s*B\b", r"interest.*default.*advance\s+tax"]),
    ("234C",      [rf"{_SEC}\s*234\s*C\b", r"\b234\s*C\b", r"interest.*deferment.*advance\s+tax"]),
    ("234D",      [rf"{_SEC}\s*234\s*D\b", r"\b234\s*D\b", r"interest.*excess\s+refund"]),

    # ── TRANSFER PRICING ───────────────────────────────────────────────────
    ("92",        [rf"{_SEC}\s*92\b(?!\s*A\b)(?!\s*B\b)(?!\s*C\b)(?!\s*D\b)(?!\s*E\b)", r"transfer\s+pricing.*computation.*income"]),
    ("92B",       [rf"{_SEC}\s*92\s*B\b", r"\b92\s*B\b", r"international\s+transaction.*definition"]),
    ("92C",       [rf"{_SEC}\s*92\s*C\b(?!\s*A\b)", r"\b92\s*C\b(?!\s*A\b)", r"arm.s\s+length\s+price.*computation"]),
    ("92CA",      [rf"{_SEC}\s*92\s*CA\b", r"\b92\s*CA\b", r"reference.*transfer\s+pricing\s+officer", r"TPO.*reference.*92"]),
    ("92D",       [rf"{_SEC}\s*92\s*D\b", r"\b92\s*D\b", r"maintenance.*information.*transfer\s+pricing.*92\s*D"]),
    ("92E",       [rf"{_SEC}\s*92\s*E\b", r"\b92\s*E\b", r"accountant.*report.*transfer\s+pricing"]),

    # ── MINIMUM ALTERNATE TAX ──────────────────────────────────────────────
    ("115JB",     [rf"{_SEC}\s*115\s*JB\b", r"\b115\s*JB\b", r"minimum\s+alternate\s+tax", r"MAT.*book\s+profit", r"book\s+profit.*MAT"]),
    ("115JC",     [rf"{_SEC}\s*115\s*JC\b", r"\b115\s*JC\b", r"alternate\s+minimum\s+tax", r"AMT.*non.corporate"]),

    # ── DEDUCTIONS ─────────────────────────────────────────────────────────
    ("14A",       [rf"{_SEC}\s*14\s*A\b", r"\b14\s*A\b", r"disallowance.*exempt\s+income.*14\s*A", r"rule\s*8\s*D", r"expenditure.*exempt.*income.*disallow"]),
    ("80C",       [rf"{_SEC}\s*80\s*C\b(?!\s*C\b)", r"\b80\s*C\b(?!\s*C\b)", r"LIC.*PPF.*ELSS.*deduction"]),
    ("80D",       [rf"{_SEC}\s*80\s*D\b", r"\b80\s*D\b", r"medical\s+insurance.*deduction"]),
    ("80G",       [rf"{_SEC}\s*80\s*G\b(?!\s*G\b)(?!\s*A\b)", r"\b80\s*G\b(?!\s*[GA])", r"donation.*80\s*G\b", r"deduction.*donation.*approved"]),
    ("80-IC",     [rf"{_SEC}\s*80\s*[-–]?\s*IC\b", r"\b80\s*IC\b", r"deduction.*undertakings.*Himachal"]),
    ("80P",       [rf"{_SEC}\s*80\s*P\b", r"\b80\s*P\b", r"co.operative\s+society.*deduction"]),
    ("80RRB",     [rf"{_SEC}\s*80\s*RRB\b", r"\b80\s*RRB\b", r"royalty.*patent.*deduction"]),

    # ── INTERNATIONAL / DTAA ───────────────────────────────────────────────
    ("90",        [rf"{_SEC}\s*90\b(?!\s*A\b)", r"double\s+taxation.*avoidance\s+agreement", r"DTAA.*treaty.*benefit"]),
    ("90A",       [rf"{_SEC}\s*90\s*A\b", r"adopted.*agreement.*specified\s+association"]),
    ("91",        [rf"{_SEC}\s*91\b", r"relief.*double\s+taxation.*country.*no\s+agreement"]),
]


def detect_sections_from_text(text: str) -> list[str]:
    """Return list of all IT Act sections detected in the text."""
    found = []
    for section_name, patterns in _SECTION_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                if section_name not in found:
                    found.append(section_name)
                break
    return found


def extract_demand_amount(text: str) -> float:
    patterns = [
        r"(?:demand|penalty|tax\s+payable|balance\s+payable|total\s+tax\s+due).*?(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:/-)?",
        r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:/-)?.*?(?:demand|penalty|payable|due)",
        r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:/-)?",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if val > 100:
                    return val
            except ValueError:
                continue
    return 0.0


def extract_assessment_year(text: str) -> str:
    for pattern in [
        r"A\.?\s*Y\.?\s*[:\-]?\s*(\d{4}[-–]\d{2,4})",
        r"Assessment\s+Year\s*[:\-]?\s*(\d{4}[-–]\d{2,4})",
        r"F\.?\s*Y\.?\s*[:\-]?\s*(\d{4}[-–]\d{2,4})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def extract_pan(text: str) -> str:
    m = re.search(r"\b([A-Z]{5}\d{4}[A-Z])\b", text)
    return m.group(1) if m else ""


def extract_assessee_name(text: str) -> str:
    for pattern in [
        r"(?:Name\s+of\s+the\s+[Aa]ssessee|Assessee\s*[:\-])\s*([A-Z][^\n]{3,60})",
        r"(?:IN\s+THE\s+MATTER\s+OF|M/[Ss]\.?)\s*([A-Z][^\n]{3,60})",
        r"(?:Shri|Smt\.|M/s\.?|Mr\.|Mrs\.)\s+([A-Za-z][^\n]{3,50})",
    ]:
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()[:60]
    return ""


def extract_ao_name(text: str) -> str:
    for pattern in [
        r"(?:ITO|DCIT|ACIT|JCIT|PCIT|CIT)[^\n]{0,60}(?:Ward|Circle|Range)[^\n]{0,40}",
        r"(?:Ward|Circle)\s*[-:]?\s*\d+[^\n]{0,30}",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()[:80]
    return ""


def parse_assessment_order(pdf_path: str) -> dict:
    text = extract_text_from_pdf(pdf_path)
    return {
        "raw_text": text,
        "sections_violated": detect_sections_from_text(text),
        "demand_amount": extract_demand_amount(text),
        "assessment_year": extract_assessment_year(text),
        "pan": extract_pan(text),
        "assessee_name": extract_assessee_name(text),
        "ao_name": extract_ao_name(text),
        "word_count": len(text.split()),
        "page_count": text.count("\x0c") + 1,
    }
