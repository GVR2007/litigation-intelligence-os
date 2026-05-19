import os
from dotenv import load_dotenv

load_dotenv()

INDIAN_KANOON_API_KEY = os.getenv("INDIAN_KANOON_API_KEY", "")

# Google Gemini — sole AI engine
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── Web Search (Source ⑦) ────────────────────────────────────────────────────
# Google Custom Search Engine
#   1. Go to https://programmablesearchengine.google.com/ → Create engine
#   2. Set to "Search the entire web" (or restrict to tax sites)
#   3. Copy the Search Engine ID (cx value)
#   4. Enable "Custom Search API" in Google Cloud Console → get API key
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_ID      = os.getenv("GOOGLE_CSE_ID", "")

# Bing Web Search API v7 (fallback / parallel source)
#   1. Go to https://portal.azure.com → Create "Bing Search v7" resource
#   2. Free tier: 1,000 queries/month
#   3. Copy the API key from "Keys and Endpoint"
BING_SEARCH_API_KEY = os.getenv("BING_SEARCH_API_KEY", "")

# All tasks route to Gemini (kept for backward compatibility with call_with_routing callers)
COMPLEX_TASKS = {"playbook", "strategy", "warroom", "adversarial", "midtrial"}
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "litigation_os.db")
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")

# ─────────────────────────────────────────────────────────────────────────────
# ALL INCOME TAX ACT 1961 SECTIONS — complete reference used for:
#   • Detection in uploaded PDFs
#   • Display in Phase 1
#   • Evidence mapping, strategy, playbook generation
# ─────────────────────────────────────────────────────────────────────────────
ITAT_SECTIONS = {

    # ── DEFINITIONS ──────────────────────────────────────────────────────────
    "2(14)": {
        "name": "Capital Asset — Definition",
        "category": "Definition",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Asset used for personal use/business", "Agricultural land exclusion", "Movable personal effects exclusion"],
    },
    "2(22)(e)": {
        "name": "Deemed Dividend — Loans/advances to shareholders",
        "category": "Income from Other Sources",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax",
        "key_defences": ["Not a shareholder at time of loan", "Loan given in ordinary course of business", "Loan repaid before year end", "No accumulated profits"],
    },
    "2(47)": {
        "name": "Transfer — Definition for capital gains",
        "category": "Definition",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Transaction does not amount to transfer", "Covered under section 47 exclusions"],
    },

    # ── RESIDENTIAL STATUS & SCOPE ───────────────────────────────────────────
    "5": {
        "name": "Scope of Total Income",
        "category": "Chargeability",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Non-resident; income not received in India", "DTAA exemption applies"],
    },
    "6": {
        "name": "Residence in India — Residential Status",
        "category": "Residential Status",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Days in India below threshold", "RNOR status applicable", "Treaty tie-breaker clause"],
    },
    "9": {
        "name": "Income Deemed to Accrue or Arise in India",
        "category": "International Taxation",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["No business connection in India", "DTAA exempts such income", "FTS not taxable under treaty", "No PE in India"],
    },
    "9A": {
        "name": "Offshore Fund — No PE merely due to fund management",
        "category": "International Taxation",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Eligible investment fund conditions met", "No business connection attributed"],
    },

    # ── EXEMPTIONS ────────────────────────────────────────────────────────────
    "10": {
        "name": "Incomes Not Included in Total Income",
        "category": "Exemption",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Income falls within specified clauses of Sec 10", "Agricultural income exempt u/s 10(1)", "HRA exempt u/s 10(13A)", "LTA exempt u/s 10(5)"],
    },
    "10A": {
        "name": "Special Provision — Export-oriented undertakings (pre-2003)",
        "category": "Exemption",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Conditions of section 10A fully satisfied", "Profits derived from export turnover"],
    },
    "10AA": {
        "name": "Special Economic Zone (SEZ) Unit Deduction",
        "category": "Exemption",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Unit in notified SEZ", "Derived from export", "Approval from Development Commissioner"],
    },
    "10B": {
        "name": "100% Export Oriented Undertaking — Exemption",
        "category": "Exemption",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["All goods exported", "Conditions under 10B satisfied", "Export realisation in foreign exchange"],
    },

    # ── CHARITABLE TRUSTS ─────────────────────────────────────────────────────
    "11": {
        "name": "Income from Property Held for Charitable/Religious Purposes",
        "category": "Trust / Exemption",
        "penalty_section": None, "max_penalty": "Loss of exemption",
        "key_defences": ["85% application rule satisfied", "Accumulation u/s 11(2) validly done", "Objects charitable in nature", "Registered u/s 12A/12AB"],
    },
    "12": {
        "name": "Income of Trusts — Voluntary Contributions",
        "category": "Trust / Exemption",
        "penalty_section": None, "max_penalty": "Loss of exemption",
        "key_defences": ["Corpus donations not income", "Treated as part of corpus", "Applied for charitable purposes"],
    },
    "12A": {
        "name": "Registration of Trust / Institution (Old Regime)",
        "category": "Trust / Exemption",
        "penalty_section": None, "max_penalty": "Denial of exemption",
        "key_defences": ["Registration granted; cannot be denied retrospectively", "De-registration requires specific grounds"],
    },
    "12AA": {
        "name": "Procedure for Registration of Trust (Old Regime)",
        "category": "Trust / Exemption",
        "penalty_section": None, "max_penalty": "Denial of exemption",
        "key_defences": ["CIT cannot cancel registration without reasonable opportunity", "Activities genuinely charitable"],
    },
    "12AB": {
        "name": "Registration of Trust — New Regime (w.e.f. 2022)",
        "category": "Trust / Exemption",
        "penalty_section": None, "max_penalty": "Denial of exemption",
        "key_defences": ["Application filed within prescribed time", "Objects not changed", "Renewal within 5 years"],
    },

    # ── SALARIES ─────────────────────────────────────────────────────────────
    "17": {
        "name": "Salary — Perquisites and Profits in Lieu of Salary",
        "category": "Salary Income",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Amount not salary; it is reimbursement", "Perquisite rules not applicable", "Exempt perquisite under rules"],
    },

    # ── HOUSE PROPERTY ────────────────────────────────────────────────────────
    "22": {
        "name": "Income from House Property — Chargeability",
        "category": "House Property",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Property used for business — chargeable u/s 28, not 22", "Property not capable of being let"],
    },
    "24": {
        "name": "Deductions from House Property Income",
        "category": "House Property",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Standard deduction 30% allowed", "Interest on home loan deductible"],
    },

    # ── BUSINESS INCOME ───────────────────────────────────────────────────────
    "28": {
        "name": "Profits and Gains of Business or Profession — Chargeability",
        "category": "Business Income",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Amount is capital receipt, not income", "Amount is reimbursement of expense"],
    },
    "32": {
        "name": "Depreciation",
        "category": "Business Income / Deduction",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Asset used for business purposes", "Rate as per Income Tax Rules", "Actual cost correctly determined"],
    },
    "35": {
        "name": "Deduction for Scientific Research Expenditure",
        "category": "Business Income / Deduction",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Expenditure for approved research", "Approved institution certification"],
    },
    "36(1)(iii)": {
        "name": "Interest on Borrowed Capital — Deduction",
        "category": "Business Income / Deduction",
        "penalty_section": None, "max_penalty": "Disallowance",
        "key_defences": ["Capital borrowed for business", "Interest actually paid", "Nexus between loan and business established"],
    },
    "36(1)(va)": {
        "name": "Employee Contribution to PF/ESI — Deduction",
        "category": "Business Income / Deduction",
        "penalty_section": None, "max_penalty": "Disallowance of PF/ESI amount",
        "key_defences": ["Deposited before due date of return u/s 139(1)", "Vikram Woollens ratio — SC ruling", "Amendment prospective, not retrospective"],
    },
    "36(1)(vii)": {
        "name": "Bad Debts — Deduction",
        "category": "Business Income / Deduction",
        "penalty_section": None, "max_penalty": "Disallowance",
        "key_defences": ["Debt was offered as income in earlier year", "Written off in books", "Debt irrecoverable"],
    },
    "37(1)": {
        "name": "General Deduction — Business Expenditure",
        "category": "Business Income / Deduction",
        "penalty_section": None, "max_penalty": "Disallowance",
        "key_defences": ["Expenditure wholly for business purpose", "Capital vs revenue distinction", "Not personal in nature", "Incurred for business expediency"],
    },
    "40(a)(i)": {
        "name": "Disallowance — TDS not deducted on non-resident payments",
        "category": "Disallowance",
        "penalty_section": None, "max_penalty": "100% disallowance",
        "key_defences": ["DTAA exempts — no TDS obligation", "Payee filed return disclosing income", "Amount not chargeable to tax in India"],
    },
    "40(a)(ia)": {
        "name": "Disallowance — TDS not deducted on resident payments",
        "category": "Disallowance",
        "penalty_section": None, "max_penalty": "30% disallowance",
        "key_defences": ["TDS deducted though deposited late — only 30% disallowed", "Payee filed return — second proviso applies", "Correct TDS rate applied"],
    },
    "40(b)": {
        "name": "Disallowance — Partner's Remuneration / Interest",
        "category": "Disallowance",
        "penalty_section": None, "max_penalty": "Excess remuneration disallowed",
        "key_defences": ["Remuneration within limits specified in deed and section", "Partnership deed authorises payment", "Working partner condition satisfied"],
    },
    "40A(2)": {
        "name": "Disallowance — Payments to Specified Persons / Related Parties",
        "category": "Disallowance",
        "penalty_section": None, "max_penalty": "Excess over market rate disallowed",
        "key_defences": ["Payment at market rate; not excessive", "Comparable evidence furnished", "Transaction at arm's length"],
    },
    "40A(3)": {
        "name": "Disallowance — Cash Payments Exceeding ₹10,000",
        "category": "Disallowance",
        "penalty_section": None, "max_penalty": "100% disallowance",
        "key_defences": ["Rule 6DD exception applies", "Payee is agriculturist in village", "No bank within 20 km", "Bank holiday / strike", "Payment to government"],
    },
    "40A(3A)": {
        "name": "Disallowance — Cash Payments in Subsequent Year (40A(3A))",
        "category": "Disallowance",
        "penalty_section": None, "max_penalty": "100% disallowance",
        "key_defences": ["Rule 6DD exception applies", "Genuine emergency repayment"],
    },
    "41": {
        "name": "Profits Chargeable to Tax — Remission of Liability / Recovery",
        "category": "Business Income",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Liability not actually remitted", "Amount not allowed as deduction originally"],
    },
    "43B": {
        "name": "Deductions Only on Actual Payment — PF, Tax, Bonus etc.",
        "category": "Disallowance",
        "penalty_section": None, "max_penalty": "Disallowance until paid",
        "key_defences": ["Paid before due date of return", "Government dues — relaxation applies", "Proviso 2 applicable for conversion to loan"],
    },
    "43CA": {
        "name": "Transfer of Immovable Property Below Stamp Duty Value — Business",
        "category": "Business Income",
        "penalty_section": None, "max_penalty": "Deemed income on difference",
        "key_defences": ["Stamp duty value disputed — reference to DVO", "Property sold for a price not less than SDV as on agreement date", "Tolerance band of 10% applies"],
    },

    # ── PRESUMPTIVE TAXATION ──────────────────────────────────────────────────
    "44AD": {
        "name": "Presumptive Taxation — Small Business (8%/6% of turnover)",
        "category": "Presumptive Taxation",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Turnover below ₹2 crore", "6% rate for digital receipts", "Opted out rightfully"],
    },
    "44ADA": {
        "name": "Presumptive Taxation — Professionals (50% of receipts)",
        "category": "Presumptive Taxation",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Gross receipts below ₹50L", "50% deemed profit declared", "Eligible profession covered"],
    },
    "44AE": {
        "name": "Presumptive Taxation — Goods Carriage",
        "category": "Presumptive Taxation",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Not more than 10 goods vehicles", "Fixed per-vehicle income declared"],
    },

    # ── CAPITAL GAINS ─────────────────────────────────────────────────────────
    "45": {
        "name": "Capital Gains — Chargeability",
        "category": "Capital Gains",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["No transfer took place", "Amount is capital receipt", "Agricultural land — not a capital asset", "Section 47 exclusion applies"],
    },
    "47": {
        "name": "Transactions Not Regarded as Transfer",
        "category": "Capital Gains",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Gift or inheritance — no transfer", "Family arrangement", "Transfer within group company — 47(iv)/(v)", "Conversion of bonds — 47(x)"],
    },
    "50": {
        "name": "Special Provision — Capital Gains on Depreciable Assets",
        "category": "Capital Gains",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Asset part of block; section 50 not applicable if block not empty", "Slump sale — 50B applies"],
    },
    "50B": {
        "name": "Slump Sale — Capital Gains",
        "category": "Capital Gains",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Not a slump sale; individual asset sale", "Net worth correctly determined", "Report of CA filed"],
    },
    "50C": {
        "name": "Full Value of Consideration — Stamp Duty Value (Land/Building)",
        "category": "Capital Gains",
        "penalty_section": None, "max_penalty": "Deemed income on difference",
        "key_defences": ["SDV disputed — reference to DVO u/s 50C(2)", "Agreement date SDV applicable", "Tolerance band of 10%", "Property under litigation"],
    },
    "50CA": {
        "name": "Unquoted Shares — Fair Market Value as Full Value",
        "category": "Capital Gains",
        "penalty_section": None, "max_penalty": "Deemed income on difference",
        "key_defences": ["FMV correctly computed per Rule 11UA", "Shares quoted — 50CA not applicable"],
    },
    "54": {
        "name": "Exemption — Residential House (Long-term Capital Gains)",
        "category": "Capital Gains Exemption",
        "penalty_section": None, "max_penalty": "Loss of exemption",
        "key_defences": ["Invested in new residential house within 2 years", "Construction within 3 years", "Capital gains deposited in CGAS account"],
    },
    "54B": {
        "name": "Exemption — Agricultural Land Purchase",
        "category": "Capital Gains Exemption",
        "penalty_section": None, "max_penalty": "Loss of exemption",
        "key_defences": ["New agricultural land purchased within 2 years", "Used for agriculture by assessee/parent"],
    },
    "54EC": {
        "name": "Exemption — Investment in Specified Bonds (NHAI/REC)",
        "category": "Capital Gains Exemption",
        "penalty_section": None, "max_penalty": "Loss of exemption",
        "key_defences": ["Invested within 6 months in NHAI/REC bonds", "Holding period of 5 years maintained", "Limit of ₹50L per year"],
    },
    "54F": {
        "name": "Exemption — Long-term CG on Residential House Purchase",
        "category": "Capital Gains Exemption",
        "penalty_section": None, "max_penalty": "Loss of exemption",
        "key_defences": ["Not owning more than one residential house", "Invested net sale consideration", "Proportionate exemption allowed"],
    },

    # ── INCOME FROM OTHER SOURCES ─────────────────────────────────────────────
    "56(2)(i)": {
        "name": "Dividends — Income from Other Sources",
        "category": "Income from Other Sources",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["DDT paid at company level", "Covered under section 10(34)"],
    },
    "56(2)(vii)": {
        "name": "Gifts Received by Individual/HUF — Taxable (pre-2017)",
        "category": "Income from Other Sources",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax",
        "key_defences": ["Gift from relative — exempt", "On occasion of marriage — exempt", "Under will/inheritance — exempt", "Amount below ₹50,000 threshold"],
    },
    "56(2)(x)": {
        "name": "Receipt of Property/Money for Inadequate Consideration",
        "category": "Income from Other Sources",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax",
        "key_defences": ["Transaction between relatives — exempt", "On occasion of marriage", "Under will/inheritance", "Adequate consideration established", "Tolerance band applies"],
    },
    "56(2)(viib)": {
        "name": "Issue of Shares Above FMV — Angel Tax",
        "category": "Income from Other Sources",
        "penalty_section": None, "max_penalty": "Excess over FMV taxable",
        "key_defences": ["DPIIT registered startup — exempt", "FMV computed per Rule 11UA correctly", "Category I/II AIF investor — exempt", "Consideration justified by business prospects"],
    },

    # ── UNEXPLAINED INCOME / ADDITIONS ───────────────────────────────────────
    "68": {
        "name": "Cash Credits — Unexplained",
        "category": "Addition",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax + 115BBE tax",
        "key_defences": ["Identity of creditor established", "Creditworthiness proven (ITR/bank stmt)", "Genuineness of transaction proven", "Source of funds explained"],
    },
    "69": {
        "name": "Unexplained Investments",
        "category": "Addition",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax + 115BBE tax",
        "key_defences": ["Source of investment explained", "Investment made from known income", "Agricultural income source", "Gift/inheritance received"],
    },
    "69A": {
        "name": "Unexplained Money, Bullion, Jewellery",
        "category": "Addition",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax + 115BBE tax",
        "key_defences": ["Jewellery within CBDT prescribed limits", "Source explained (savings/gift)", "Gold/silver from agricultural income", "Gift from relatives at marriage"],
    },
    "69B": {
        "name": "Amount of Investment Not Fully Disclosed",
        "category": "Addition",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax + 115BBE tax",
        "key_defences": ["Full investment amount disclosed", "Difference within tolerance", "Stamp duty value not correct measure"],
    },
    "69C": {
        "name": "Unexplained Expenditure",
        "category": "Addition",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax + 115BBE tax",
        "key_defences": ["Expenditure explained from known income", "Business expenditure duly vouched"],
    },
    "69D": {
        "name": "Amount Borrowed / Repaid on Hundi",
        "category": "Addition",
        "penalty_section": "271(1)(c)", "max_penalty": "100–300% of tax",
        "key_defences": ["Not a hundi transaction", "Genuine loan with documentation"],
    },
    "115BBE": {
        "name": "Tax on Unexplained Income u/s 68–69D (60%+25% surcharge)",
        "category": "Special Tax Rate",
        "penalty_section": "271AAC", "max_penalty": "10% of tax additionally",
        "key_defences": ["Income explained — 115BBE not applicable", "Explanation accepted — normal tax rates apply"],
    },

    # ── CASH TRANSACTION VIOLATIONS ───────────────────────────────────────────
    "269SS": {
        "name": "Mode of Taking / Accepting Loans in Cash (>₹20,000)",
        "category": "Cash Transaction",
        "penalty_section": "271D", "max_penalty": "100% of loan amount",
        "key_defences": ["Genuine business necessity", "Reasonable cause u/s 273B", "Bank account not available", "Family transaction / genuine urgency", "Agricultural emergency"],
    },
    "269ST": {
        "name": "Cash Receipt Exceeding ₹2 Lakh in Single Transaction",
        "category": "Cash Transaction",
        "penalty_section": "271DA", "max_penalty": "100% of cash received",
        "key_defences": ["Transaction through banking channel", "Not a single transaction — multiple payments", "Government receipts excluded"],
    },
    "269T": {
        "name": "Mode of Repayment of Loans — No Cash (>₹20,000)",
        "category": "Cash Transaction",
        "penalty_section": "271E", "max_penalty": "100% of repayment amount",
        "key_defences": ["Reasonable cause u/s 273B", "Lender insisted on cash", "Bank holiday/strike", "Genuine emergency repayment"],
    },
    "269SU": {
        "name": "Acceptance of Payments Through Prescribed Electronic Modes",
        "category": "Cash Transaction",
        "penalty_section": None, "max_penalty": "₹5,000 per day",
        "key_defences": ["Turnover below ₹50 crore", "Electronic modes provided"],
    },

    # ── TDS / TCS ─────────────────────────────────────────────────────────────
    "192": {
        "name": "TDS on Salary",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Tax correctly estimated and deducted", "Exemptions correctly allowed"],
    },
    "193": {
        "name": "TDS on Interest on Securities",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Securities held by FII/Non-resident — different provisions", "Below threshold"],
    },
    "194": {
        "name": "TDS on Dividends",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Dividend below ₹5,000 threshold", "Form 15G/15H filed by recipient"],
    },
    "194A": {
        "name": "TDS on Interest (Other than Securities)",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Below ₹40,000 threshold (₹50,000 for senior citizens)", "Form 15G/H filed", "Interest accrued not paid — no obligation"],
    },
    "194C": {
        "name": "TDS on Contracts",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Not a contract — purchase of goods", "Single payment below ₹30,000", "Annual payments below ₹1,00,000"],
    },
    "194H": {
        "name": "TDS on Commission / Brokerage",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Not commission — discount/trade discount", "Below ₹15,000 threshold", "Insurance commission — 194D applies"],
    },
    "194I": {
        "name": "TDS on Rent",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Composite payment — not purely rent", "Below ₹2,40,000 threshold", "Rental characterisation disputed"],
    },
    "194IA": {
        "name": "TDS on Purchase of Immovable Property",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Property value below ₹50L", "Agricultural land — not applicable"],
    },
    "194J": {
        "name": "TDS on Professional / Technical Services",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Not professional service — routine technical work at 2%", "Below ₹30,000 threshold", "FTS — DTAA exempts"],
    },
    "194N": {
        "name": "TDS on Cash Withdrawal (>₹1 crore)",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Withdrawal below ₹1 crore threshold", "Specific exemptions apply (bank withdrawals for cash payments)"],
    },
    "194O": {
        "name": "TDS on E-commerce Operator Payments",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Below ₹5L threshold for individuals", "Not an e-commerce operator"],
    },
    "194Q": {
        "name": "TDS on Purchase of Goods (>₹50L)",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Turnover of seller below ₹10 crore", "TCS u/s 206C(1H) already collected"],
    },
    "195": {
        "name": "TDS on Payments to Non-Residents",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Income not chargeable in India", "DTAA exemption", "Lower/nil TDS certificate obtained", "Remittance is not income"],
    },
    "200": {
        "name": "Duty to Deduct and Deposit TDS",
        "category": "TDS Procedure",
        "penalty_section": "201", "max_penalty": "Interest + 271C penalty",
        "key_defences": ["TDS deposited though delayed — no default", "Payee's tax liability set off"],
    },
    "201": {
        "name": "Consequences of Failure to Deduct TDS",
        "category": "TDS",
        "penalty_section": "271C", "max_penalty": "Treated as assessee in default + interest",
        "key_defences": ["Payee filed return and paid tax — second proviso", "TDS deducted though late deposited", "Income shown in payee's return — no default"],
    },
    "206C": {
        "name": "Tax Collection at Source (TCS)",
        "category": "TCS",
        "penalty_section": "271CA", "max_penalty": "100% of TCS not collected",
        "key_defences": ["Buyer has no profit element — TCS not applicable", "Below threshold", "Applicable exception applies"],
    },

    # ── ASSESSMENT PROCEDURE ──────────────────────────────────────────────────
    "131": {
        "name": "Power — Discovery, Production of Evidence, Survey",
        "category": "Assessment Procedure",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Information obtained without valid authority", "Rights of assessee under article 20(3)"],
    },
    "132": {
        "name": "Search and Seizure",
        "category": "Search & Seizure",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["No valid reason to believe", "Authorization defective", "Panchnama not prepared properly", "Seized assets not belonging to assessee"],
    },
    "132A": {
        "name": "Power to Requisition Books of Account",
        "category": "Search & Seizure",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Requisition authority exceeded", "Books already returned"],
    },
    "133A": {
        "name": "Power of Survey",
        "category": "Assessment Procedure",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Statement u/s 133A not binding — not under oath", "Voluntary disclosure retracted", "Survey findings incorrectly relied upon"],
    },
    "139": {
        "name": "Return of Income — Filing",
        "category": "Return Filing",
        "penalty_section": "271F", "max_penalty": "₹5,000 late fee",
        "key_defences": ["Return filed within extended time", "Income below taxable limit — no obligation"],
    },
    "139(1)": {
        "name": "Mandatory Return Filing (Original Return)",
        "category": "Return Filing",
        "penalty_section": "271F", "max_penalty": "₹5,000 late fee",
        "key_defences": ["Filed within due date", "Income below threshold"],
    },
    "142": {
        "name": "Inquiry Before Assessment — Notice for Documents",
        "category": "Assessment Procedure",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Documents furnished on time", "Notice not properly served"],
    },
    "142A": {
        "name": "Valuation by District Valuation Officer (DVO)",
        "category": "Assessment Procedure",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["DVO report not binding — assessee can challenge", "DVO's method incorrect", "Report beyond terms of reference"],
    },
    "143(1)": {
        "name": "Intimation — Processing of Return",
        "category": "Assessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Adjustment u/s 143(1) not valid — requires 143(2) notice", "Time limit for intimation exceeded"],
    },
    "143(2)": {
        "name": "Notice for Scrutiny Assessment",
        "category": "Assessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Notice not served within 6 months of end of AY", "Notice invalid — assessment void", "Not served on correct address"],
    },
    "143(3)": {
        "name": "Scrutiny Assessment",
        "category": "Assessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["AO exceeded jurisdiction", "Natural justice violated", "Addition not supported by material"],
    },
    "144": {
        "name": "Best Judgment Assessment",
        "category": "Assessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Sufficient cause for non-appearance", "Books of accounts available", "Best judgment arbitrary — not based on material"],
    },
    "144B": {
        "name": "Faceless Assessment",
        "category": "Assessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["NFAC procedure not followed", "Personal hearing not granted though requested", "Violation of principles of natural justice"],
    },
    "147": {
        "name": "Assessment of Income Escaping Assessment (Reassessment)",
        "category": "Reassessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["No 'reason to believe' income escaped", "Change of opinion — not fresh material", "Income was disclosed fully in original return", "AO must have tangible material"],
    },
    "148": {
        "name": "Notice for Reassessment",
        "category": "Reassessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Notice time-barred (4 years / 6 years / 10 years limit)", "Sanction u/s 151 not obtained properly", "No failure to disclose fully and truly"],
    },
    "148A": {
        "name": "Show Cause Notice Before Reassessment (w.e.f. 2021)",
        "category": "Reassessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["SCN issued without proper information", "Response to SCN ignored", "Procedure under 148A(b) not followed", "TOLA extension not applicable"],
    },
    "149": {
        "name": "Time Limit for Issuing Reassessment Notice",
        "category": "Reassessment",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Notice issued beyond 3/10 year time limit", "No suppression — 3 year limit applies"],
    },
    "153": {
        "name": "Time Limit for Completion of Assessment",
        "category": "Assessment",
        "penalty_section": None, "max_penalty": "Assessment void if time-barred",
        "key_defences": ["Assessment order passed beyond time limit — void", "Extension provisions not applicable"],
    },
    "153A": {
        "name": "Assessment in Search Cases",
        "category": "Search Assessment",
        "penalty_section": None, "max_penalty": "Tax on undisclosed income + interest",
        "key_defences": ["No incriminating material found for completed assessments", "SC ratio in Vijay Kumar Talwar case", "Completed assessment cannot be disturbed without incriminating material"],
    },
    "153B": {
        "name": "Time Limit for Assessment u/s 153A",
        "category": "Search Assessment",
        "penalty_section": None, "max_penalty": "Assessment void if time-barred",
        "key_defences": ["Order passed beyond 21 months from end of year of search — void"],
    },
    "153C": {
        "name": "Assessment of Other Persons in Search",
        "category": "Search Assessment",
        "penalty_section": None, "max_penalty": "Tax on undisclosed income",
        "key_defences": ["Documents not belonging to or pertaining to assessee", "Satisfaction note not recorded", "No incriminating document"],
    },
    "154": {
        "name": "Rectification of Mistake Apparent on Record",
        "category": "Assessment Procedure",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Matter requires debate — not a mistake apparent on record", "Within 4 years from end of year of assessment"],
    },

    # ── APPEAL & REVISION ─────────────────────────────────────────────────────
    "246A": {
        "name": "Appealable Orders before CIT(A)",
        "category": "Appeals",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Appeal within 30 days of order", "Condonation of delay available"],
    },
    "250": {
        "name": "Procedure in Appeal before CIT(A)",
        "category": "Appeals",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["New grounds can be raised at CIT(A)", "Additional evidence can be filed"],
    },
    "251": {
        "name": "Powers of CIT(A)",
        "category": "Appeals",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["CIT(A) can enhance — but give opportunity of being heard", "CIT(A) can admit additional evidence"],
    },
    "253": {
        "name": "Appeal to ITAT",
        "category": "Appeals",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Appeal filed within 60 days", "Condonation available with sufficient cause"],
    },
    "254": {
        "name": "Orders of ITAT",
        "category": "Appeals",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["ITAT has power to pass any order", "Rectification u/s 254(2) for mistakes", "4 years for rectification"],
    },
    "260A": {
        "name": "Appeal to High Court on Substantial Question of Law",
        "category": "Appeals",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["No substantial question of law — HC cannot interfere", "Concurrent finding of fact — HC bound"],
    },
    "261": {
        "name": "Appeal to Supreme Court",
        "category": "Appeals",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["SLP on substantial question of law", "Doctrine of res judicata"],
    },
    "263": {
        "name": "Revision by PCIT/CIT — Prejudicial to Revenue",
        "category": "Revision",
        "penalty_section": None, "max_penalty": "Revised assessment + demand",
        "key_defences": ["Assessment not erroneous — merely another possible view", "Twin conditions (erroneous + prejudicial) not satisfied", "AO made an inquiry — not a lacuna", "No prejudice to revenue"],
    },
    "264": {
        "name": "Revision by CIT — In Favour of Assessee",
        "category": "Revision",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Manifest error in assessment", "Law clearly on assessee's side"],
    },

    # ── PENALTIES ─────────────────────────────────────────────────────────────
    "270A": {
        "name": "Penalty for Under-reporting / Misreporting of Income",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "50% (under-reporting) or 200% (misreporting) of tax",
        "key_defences": ["Not misreporting — bona fide position taken", "Surrendered in search — lower rate", "No tax evasion intent"],
    },
    "271": {
        "name": "Penalty for Failure to Furnish Returns / Comply with Notices",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "₹10,000 for each default",
        "key_defences": ["Reasonable cause for failure", "Return filed belatedly — penalty not automatic"],
    },
    "271(1)(c)": {
        "name": "Penalty for Concealment / Furnishing Inaccurate Particulars",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "100–300% of tax evaded",
        "key_defences": ["No concealment — bona fide claim disallowed", "Explanation accepted", "Penalty notice defective — not specifying limb", "Mala fide intent not established"],
    },
    "271A": {
        "name": "Penalty — Failure to Keep, Maintain, or Retain Books",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "₹25,000",
        "key_defences": ["Reasonable cause for non-maintenance", "Books maintained though not in prescribed form"],
    },
    "271AA": {
        "name": "Penalty — Failure to Keep Transfer Pricing Documentation",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "2% of value of transaction",
        "key_defences": ["Documentation maintained and filed", "Good faith attempt at compliance"],
    },
    "271AAB": {
        "name": "Penalty on Undisclosed Income in Search (w.e.f. 2012)",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "30% or 60% of undisclosed income",
        "key_defences": ["Income disclosed in statement u/s 132(4)", "Income declared in return — lower 30% rate", "Income not attributable to year of search"],
    },
    "271AAC": {
        "name": "Penalty on Income u/s 68–69D Taxed u/s 115BBE",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "10% of tax payable",
        "key_defences": ["Income explained — 115BBE not applicable", "Explanation accepted — normal tax applies"],
    },
    "271B": {
        "name": "Penalty — Failure to Get Accounts Audited (44AB)",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "0.5% of turnover or ₹1.5L whichever is less",
        "key_defences": ["Reasonable cause — audit delayed by CA", "Audit completed; only minor delay in filing", "Turnover below ₹1 crore — not applicable"],
    },
    "271C": {
        "name": "Penalty — Failure to Deduct TDS",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "100% of TDS not deducted",
        "key_defences": ["Payee filed return showing income — second proviso to 201(1)", "Bona fide belief that TDS not applicable", "DTAA exemption relied upon in good faith"],
    },
    "271CA": {
        "name": "Penalty — Failure to Collect TCS",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "100% of TCS not collected",
        "key_defences": ["Reasonable cause", "Buyer exempted from TCS"],
    },
    "271D": {
        "name": "Penalty for Violation of Section 269SS",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "100% of loan/deposit amount",
        "key_defences": ["Reasonable cause u/s 273B", "Genuine urgency", "Bona fide belief", "No tax evasion intent"],
    },
    "271DA": {
        "name": "Penalty for Violation of Section 269ST (>₹2L cash receipt)",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "100% of cash receipt",
        "key_defences": ["Multiple transactions not aggregated", "Reasonable cause under 273B", "Not a prohibited transaction"],
    },
    "271E": {
        "name": "Penalty for Violation of Section 269T (Cash Repayment)",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "100% of repayment amount",
        "key_defences": ["Reasonable cause u/s 273B", "Lender demanded cash", "Banking not available"],
    },
    "271F": {
        "name": "Penalty for Failure to Furnish PAN",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "₹10,000",
        "key_defences": ["PAN was applied for", "PAN furnished eventually before levy"],
    },
    "271FA": {
        "name": "Penalty — Failure to Furnish SFT (Statement of Financial Transactions)",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "₹500–₹1,000 per day",
        "key_defences": ["SFT filed with reasonable delay", "Reporting entity not covered"],
    },
    "271G": {
        "name": "Penalty — Failure to Furnish Transfer Pricing Info/Documents",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "2% of value of transaction",
        "key_defences": ["Documents maintained and provided", "Bona fide reason for delay"],
    },
    "271H": {
        "name": "Penalty — Failure / Incorrect TDS/TCS Return",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "₹10,000 to ₹1,00,000",
        "key_defences": ["Return filed with reasonable delay", "Correction statement filed"],
    },
    "271J": {
        "name": "Penalty on Accountant / Merchant Banker for Incorrect Information",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "₹10,000 per report",
        "key_defences": ["Report based on correct information available", "Error bona fide"],
    },
    "272A": {
        "name": "Penalty for Failure to Answer Questions / Attend / Produce Books",
        "category": "Penalty",
        "penalty_section": None, "max_penalty": "₹10,000 per failure",
        "key_defences": ["Reasonable cause for non-compliance", "Documents not in assessee's possession"],
    },
    "273B": {
        "name": "Reasonable Cause — No Penalty if Reasonable Cause Shown",
        "category": "Penalty Defence",
        "penalty_section": None, "max_penalty": "N/A — This is a DEFENCE section",
        "key_defences": ["This section is a DEFENCE — cite this to escape all penalties", "Genuine and bona fide transaction", "Acted on professional advice"],
    },

    # ── INTEREST ──────────────────────────────────────────────────────────────
    "234A": {
        "name": "Interest for Default in Furnishing Return",
        "category": "Interest",
        "penalty_section": None, "max_penalty": "1% per month on tax due",
        "key_defences": ["Return filed in time", "Tax paid in advance — no interest"],
    },
    "234B": {
        "name": "Interest for Default in Payment of Advance Tax",
        "category": "Interest",
        "penalty_section": None, "max_penalty": "1% per month on shortfall",
        "key_defences": ["TDS deducted adequately — no advance tax shortfall", "Agricultural income — exempt from advance tax"],
    },
    "234C": {
        "name": "Interest for Deferment of Advance Tax Instalments",
        "category": "Interest",
        "penalty_section": None, "max_penalty": "1% per month per instalment shortfall",
        "key_defences": ["Capital gain arose after instalment — no shortfall attributable"],
    },
    "234D": {
        "name": "Interest on Excess Refund",
        "category": "Interest",
        "penalty_section": None, "max_penalty": "0.5% per month on excess refund",
        "key_defences": ["Refund correctly granted — no excess refund"],
    },
    "234E": {
        "name": "Fee for Late Filing of TDS/TCS Statements",
        "category": "Fee",
        "penalty_section": None, "max_penalty": "₹200 per day",
        "key_defences": ["Reasonable cause — levy was unconstitutional per various HCs"],
    },

    # ── TRANSFER PRICING ──────────────────────────────────────────────────────
    "92": {
        "name": "Computation of Income from International Transactions (TP)",
        "category": "Transfer Pricing",
        "penalty_section": "271G", "max_penalty": "2% of transaction value",
        "key_defences": ["Arm's length price correctly determined", "Method selected is most appropriate", "Comparable companies correctly selected"],
    },
    "92B": {
        "name": "International Transaction — Definition",
        "category": "Transfer Pricing",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Transaction not between associated enterprises", "Not an international transaction — domestic"],
    },
    "92C": {
        "name": "Computation of Arm's Length Price",
        "category": "Transfer Pricing",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["ALP correctly computed using TNMM/CUP/other method", "Tolerance band (3%) applies — no adjustment"],
    },
    "92CA": {
        "name": "Reference to Transfer Pricing Officer (TPO)",
        "category": "Transfer Pricing",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["TPO order passed beyond time limit", "DRP direction not followed"],
    },

    # ── MINIMUM ALTERNATE TAX / ALTERNATE MINIMUM TAX ─────────────────────────
    "115JB": {
        "name": "Minimum Alternate Tax (MAT) — Book Profit Tax (Companies)",
        "category": "Minimum Alternate Tax",
        "penalty_section": None, "max_penalty": "15% of book profit",
        "key_defences": ["Book profit computation incorrect", "Deductions not added back improperly", "Loss/depreciation correctly carried forward"],
    },
    "115JC": {
        "name": "Alternate Minimum Tax (AMT) — Non-corporate",
        "category": "Minimum Alternate Tax",
        "penalty_section": None, "max_penalty": "18.5% of adjusted total income",
        "key_defences": ["AMT not applicable for firms not claiming Chapter VI-A deductions", "Adjusted total income correctly computed"],
    },

    # ── DEDUCTIONS ─────────────────────────────────────────────────────────────
    "14A": {
        "name": "Expenditure Incurred on Exempt Income — Disallowance",
        "category": "Disallowance",
        "penalty_section": None, "max_penalty": "Disallowance of expenses",
        "key_defences": ["No expenditure incurred for exempt income", "Own funds exceed investments — no borrowed funds", "Rule 8D not applicable when assessee's computation accepted", "Strategic investment — no dividend intent"],
    },
    "80C": {
        "name": "Deduction — Life Insurance, PPF, ELSS etc. (up to ₹1.5L)",
        "category": "Deduction",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Investment proof submitted", "Deduction within limit"],
    },
    "80D": {
        "name": "Deduction — Medical Insurance Premium",
        "category": "Deduction",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Premium paid for self/family/parents", "Senior citizen benefit applies"],
    },
    "80G": {
        "name": "Deduction — Donations to Approved Funds/Institutions",
        "category": "Deduction",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Donation to registered institution with valid 80G certificate", "Payment by cheque/DD", "Within 10% of adjusted gross total income for 50% deductions"],
    },
    "80-IC": {
        "name": "Deduction — Undertakings in Himachal Pradesh / Uttaranchal etc.",
        "category": "Deduction",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Unit in eligible area", "Commencement before prescribed date", "New machinery condition satisfied"],
    },
    "80P": {
        "name": "Deduction — Co-operative Societies",
        "category": "Deduction",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Co-operative society registered under Co-operative Societies Act", "Income from eligible activities"],
    },
    "80RRB": {
        "name": "Deduction — Royalty Income of Patents",
        "category": "Deduction",
        "penalty_section": None, "max_penalty": "N/A",
        "key_defences": ["Patent registered under Patents Act 1970", "Royalty income within ₹3L"],
    },
}

APP_TITLE = "Litigation Intelligence OS"
APP_SUBTITLE = "AI Co-Pilot for Indian Tax Litigation"
VERSION = "1.0.0 MVP"
