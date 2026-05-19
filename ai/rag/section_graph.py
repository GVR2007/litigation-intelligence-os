"""
Income Tax Act, 1961 — Section Relationship Graph.

Every section node carries:
  related      — sections that appear in the same proceeding
  defences     — sections that provide legal defences against this one
  penalties    — sections that impose penalties for violating this one
  procedure    — procedural / approval sections governing this one
  triggered_by — what must happen before this section applies
  overridden_by— superseded by another section (AY-specific)

expand(sections, context) returns an intelligently expanded list:
  always adds defences + penalties for the queried sections,
  adds procedure sections so you get the full legal picture,
  and respects the adversarial flag to pull Revenue-side cases too.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class SectionCategory(str, Enum):
    CASH_TRANSACTION      = "cash_transaction"
    UNEXPLAINED_INCOME    = "unexplained_income"
    REASSESSMENT          = "reassessment"
    SEARCH_SEIZURE        = "search_seizure"
    PENALTY               = "penalty"
    TDS                   = "tds"
    DEDUCTIONS            = "deductions"
    CAPITAL_GAINS         = "capital_gains"
    BUSINESS_INCOME       = "business_income"
    INTERNATIONAL_TAX     = "international_tax"
    TRANSFER_PRICING      = "transfer_pricing"
    ASSESSMENT            = "assessment"
    APPEALS               = "appeals"
    SPECIAL_INCOME        = "special_income"
    EXEMPTIONS            = "exemptions"
    MAT                   = "mat"
    PROCEDURE             = "procedure"
    INTEREST              = "interest"
    RESIDENCE             = "residence"
    CLUBBING              = "clubbing"


class CourtType(str, Enum):
    SC   = "SC"
    HC   = "HC"
    ITAT = "ITAT"
    ALL  = "ALL"


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SectionNode:
    section:       str
    title:         str
    category:      SectionCategory

    # Who typically litigates this — SC landmark, HC challenge, ITAT first hearing
    primary_court: CourtType = CourtType.ITAT

    # Sections that nearly always appear in the same proceedings
    related:       list[str] = field(default_factory=list)

    # Sections that provide legal defences against additions/penalties here
    defences:      list[str] = field(default_factory=list)

    # Sections that impose penalties when THIS section is violated
    penalties:     list[str] = field(default_factory=list)

    # Procedural / approval / notice sections that must be satisfied
    procedure:     list[str] = field(default_factory=list)

    # What triggers applicability of this section
    triggered_by:  list[str] = field(default_factory=list)

    # Superseded by — e.g. 271(1)(c) overridden by 270A from AY 2017-18
    overridden_by: Optional[str] = None

    # True = assessee generally wins at ITAT; False = Revenue generally wins
    assessee_favorable: bool = True

    # Short plain-English note on the section for prompt context
    note: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# The Graph — 120 sections, fully connected
# ─────────────────────────────────────────────────────────────────────────────

_NODES: list[SectionNode] = [

    # ── CASH TRANSACTIONS ─────────────────────────────────────────────────────

    SectionNode(
        section="269SS",
        title="Mode of taking or accepting certain loans and deposits",
        category=SectionCategory.CASH_TRANSACTION,
        related=["269T", "271D", "273B", "269ST"],
        defences=["273B"],
        penalties=["271D"],
        procedure=["274"],
        note="Prohibits accepting loan/deposit >₹20,000 in cash. "
             "Penalty deleted when genuine transaction + reasonable cause shown.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="269T",
        title="Mode of repayment of certain loans and deposits",
        category=SectionCategory.CASH_TRANSACTION,
        related=["269SS", "271E", "273B"],
        defences=["273B"],
        penalties=["271E"],
        procedure=["274"],
        note="Prohibits repaying loan/deposit >₹20,000 in cash. "
             "Lender insistence for cash repayment is an accepted defence.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="269ST",
        title="Mode of undertaking transactions — 2 lakh cash limit",
        category=SectionCategory.CASH_TRANSACTION,
        related=["271DA", "273B", "269SS"],
        defences=["273B"],
        penalties=["271DA"],
        procedure=["274"],
        note="No cash receipt >₹2L in single transaction, single person, "
             "single occasion. Hospital/marriage/agriculture exemptions litigated.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="271D",
        title="Penalty for contravention of section 269SS",
        category=SectionCategory.PENALTY,
        related=["269SS", "273B", "271E"],
        defences=["273B"],
        triggered_by=["269SS"],
        procedure=["274"],
        note="Penalty = 100% of loan amount. Deleted under 273B when "
             "reasonable cause exists. AO must record satisfaction before levying.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="271E",
        title="Penalty for contravention of section 269T",
        category=SectionCategory.PENALTY,
        related=["269T", "273B", "271D"],
        defences=["273B"],
        triggered_by=["269T"],
        procedure=["274"],
        note="Penalty = 100% of repayment amount. Same defences as 271D.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="271DA",
        title="Penalty for contravention of section 269ST",
        category=SectionCategory.PENALTY,
        related=["269ST", "273B"],
        defences=["273B"],
        triggered_by=["269ST"],
        procedure=["274"],
        note="Penalty = 100% of receipt amount. Newer provision, limited ITAT history.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="273B",
        title="Penalty not to be imposed in certain cases — reasonable cause",
        category=SectionCategory.PENALTY,
        primary_court=CourtType.ITAT,
        related=["271D", "271E", "271DA", "271(1)(c)", "271B", "271C", "271H"],
        note="Omnibus defence section. If assessee proves reasonable cause, "
             "ALL penalties under Chapter XXI can be deleted. Strongest defence.",
        assessee_favorable=True,
    ),

    # ── UNEXPLAINED INCOME ────────────────────────────────────────────────────

    SectionNode(
        section="68",
        title="Cash credits",
        category=SectionCategory.UNEXPLAINED_INCOME,
        related=["69", "69A", "115BBE", "271AAC", "56(2)(x)"],
        defences=["68"],   # identity + creditworthiness + genuineness = full discharge
        penalties=["271AAC"],
        note="AO can add unexplained cash credit to income. Assessee must prove "
             "identity, creditworthiness of creditor, and genuineness of transaction. "
             "All three required — partial proof insufficient.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="69",
        title="Unexplained investments",
        category=SectionCategory.UNEXPLAINED_INCOME,
        related=["68", "69A", "69B", "115BBE", "271AAC"],
        penalties=["271AAC"],
        note="Investment not recorded in books + no satisfactory explanation → "
             "taxed as income. Agricultural income and gifts commonly litigated.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="69A",
        title="Unexplained money, bullion, jewellery",
        category=SectionCategory.UNEXPLAINED_INCOME,
        related=["68", "69", "115BBE", "132"],
        penalties=["271AAC"],
        note="CBDT circular on jewellery allowance (500g married woman etc.) "
             "is a key defence. Found during search under 132.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="69B",
        title="Amount of investments not fully disclosed",
        category=SectionCategory.UNEXPLAINED_INCOME,
        related=["69", "115BBE", "50C"],
        penalties=["271AAC"],
        note="Difference between investment value and disclosed amount taxed. "
             "Often arises with 50C stamp duty disputes.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="69C",
        title="Unexplained expenditure",
        category=SectionCategory.UNEXPLAINED_INCOME,
        related=["37(1)", "115BBE", "40A(3)"],
        penalties=["271AAC"],
        note="Expenditure not explained = income. Often paired with 37(1) "
             "disallowance disputes.",
        assessee_favorable=False,
    ),
    SectionNode(
        section="115BBE",
        title="Tax on income referred to in sections 68/69/69A/69B/69C",
        category=SectionCategory.SPECIAL_INCOME,
        related=["68", "69", "69A", "69B", "69C", "271AAC"],
        triggered_by=["68", "69", "69A", "69B", "69C"],
        penalties=["271AAC"],
        note="Unexplained income taxed at 60% + surcharge 25% = effective 78%. "
             "No deduction or set-off allowed. Extremely punitive.",
        assessee_favorable=False,
    ),
    SectionNode(
        section="271AAC",
        title="Penalty in respect of certain income",
        category=SectionCategory.PENALTY,
        related=["115BBE", "68", "69", "69A"],
        triggered_by=["115BBE"],
        note="10% penalty on top of 115BBE tax. Applied when income admitted "
             "but not declared in return.",
        assessee_favorable=False,
    ),

    # ── REASSESSMENT ──────────────────────────────────────────────────────────

    SectionNode(
        section="147",
        title="Income escaping assessment",
        category=SectionCategory.REASSESSMENT,
        primary_court=CourtType.HC,
        related=["148", "148A", "149", "151", "143(3)", "292BB"],
        procedure=["148A", "148", "149", "151"],
        note="AO can reopen completed assessment if income has escaped. "
             "Change of opinion not valid reason. Tangible material required. "
             "Post-2021: 148A inquiry mandatory before 148 notice.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="148",
        title="Issue of notice where income has escaped assessment",
        category=SectionCategory.REASSESSMENT,
        primary_court=CourtType.HC,
        related=["147", "148A", "149", "151", "292BB"],
        triggered_by=["147"],
        procedure=["148A", "149", "151"],
        note="Notice must be served within time limits of 149. "
             "Post-2021: 148A show cause notice mandatory before 148. "
             "Invalid 148 notice = reassessment void.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="148A",
        title="Conducting inquiry before issue of notice under 148",
        category=SectionCategory.REASSESSMENT,
        primary_court=CourtType.HC,
        related=["147", "148", "149", "151"],
        procedure=["151"],
        note="Introduced by Finance Act 2021. Mandatory show cause notice + "
             "reply opportunity + PCIT/CCIT approval before issuing 148 notice. "
             "Non-compliance = reassessment void.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="149",
        title="Time limit for notice under section 148",
        category=SectionCategory.REASSESSMENT,
        primary_court=CourtType.HC,
        related=["147", "148", "148A"],
        triggered_by=["147"],
        note="3 years from end of AY (general). 10 years if income escaped >₹50L "
             "and AO has evidence in possession. Strict limitation — most litigated.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="151",
        title="Sanction for issue of notice",
        category=SectionCategory.REASSESSMENT,
        related=["147", "148", "148A"],
        triggered_by=["147", "148"],
        note="JCIT/PCIT sanction required before issuing 148 notice. "
             "Mechanical/rubber-stamp sanction = notice invalid. "
             "Sanctioning authority must independently apply mind.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="292BB",
        title="Notice deemed to be valid in certain circumstances",
        category=SectionCategory.REASSESSMENT,
        related=["148", "143(2)", "147"],
        note="If assessee participated in proceedings without objecting to notice, "
             "notice deemed valid. Revenue uses this to cure procedural defects.",
        assessee_favorable=False,
    ),

    # ── SEARCH AND SEIZURE ────────────────────────────────────────────────────

    SectionNode(
        section="132",
        title="Search and seizure",
        category=SectionCategory.SEARCH_SEIZURE,
        related=["132A", "153A", "153B", "153C", "153D", "69A", "132B"],
        procedure=["153A", "153B", "153D"],
        note="Search warrant, panchnama, statement under oath (s.132(4)), "
             "seizure of books/cash/jewellery. Statement retraction heavily litigated. "
             "Seized material is incriminating material for 153A additions.",
        assessee_favorable=False,
    ),
    SectionNode(
        section="132A",
        title="Power to requisition books of account",
        category=SectionCategory.SEARCH_SEIZURE,
        related=["132", "153A", "153C"],
        triggered_by=["132"],
        note="Used when material found during someone else's search is relevant "
             "to another person's assessment.",
        assessee_favorable=False,
    ),
    SectionNode(
        section="153A",
        title="Assessment in cases of search or requisition",
        category=SectionCategory.SEARCH_SEIZURE,
        primary_court=CourtType.HC,
        related=["132", "153B", "153C", "153D", "143(3)"],
        triggered_by=["132", "132A"],
        procedure=["153B", "153D"],
        note="6 years of completed assessments reopened after search. "
             "Addition must be based on incriminating material found during search. "
             "No incriminating material = no addition in completed assessments.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="153B",
        title="Time limit for completion of assessment under 153A",
        category=SectionCategory.SEARCH_SEIZURE,
        related=["153A", "153C"],
        triggered_by=["153A"],
        note="2 years from end of FY in which last authorisation for search executed. "
             "Strict time limit — order beyond this period = void.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="153C",
        title="Assessment of income of any other person",
        category=SectionCategory.SEARCH_SEIZURE,
        related=["132", "153A", "153D"],
        triggered_by=["132"],
        procedure=["153D"],
        note="Documents/assets belonging to a person other than searched person. "
             "AO of searched person must be 'satisfied' and send materials to "
             "assessee's AO. Satisfaction note is a crucial document.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="153D",
        title="Prior approval required for assessment under 153A/153C",
        category=SectionCategory.SEARCH_SEIZURE,
        related=["153A", "153C"],
        triggered_by=["153A", "153C"],
        note="PCIT/CCIT prior approval mandatory. "
             "Mechanical/blanket approval = assessment void.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="133A",
        title="Survey",
        category=SectionCategory.SEARCH_SEIZURE,
        related=["132", "131", "132B"],
        note="Survey at business premises. Statement under 133A NOT under oath "
             "— cannot be sole basis for addition. Retraction of survey statement "
             "widely accepted at ITAT.",
        assessee_favorable=True,
    ),

    # ── PENALTIES ─────────────────────────────────────────────────────────────

    SectionNode(
        section="271(1)(c)",
        title="Penalty for concealment of income / furnishing inaccurate particulars",
        category=SectionCategory.PENALTY,
        primary_court=CourtType.ITAT,
        related=["270A", "273B", "274", "271AAA", "271AAB"],
        defences=["273B"],
        procedure=["274"],
        overridden_by="270A",   # for AY 2017-18 onwards
        note="Penalty 100-300% of tax on concealed income. AO must specify "
             "which limb — concealment OR inaccurate particulars — in notice u/s 274. "
             "Omnibus notice = penalty not valid. Replaced by 270A from AY 2017-18.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="270A",
        title="Penalty for under-reporting and misreporting of income",
        category=SectionCategory.PENALTY,
        primary_court=CourtType.ITAT,
        related=["271(1)(c)", "273B", "274"],
        defences=["273B"],
        procedure=["274"],
        triggered_by=["143(3)", "144", "147"],
        note="Replaces 271(1)(c) for AY 2017-18 onwards. Under-reporting = 50% "
             "of tax. Misreporting = 200% of tax. Immunity if income disclosed "
             "in return — only applies to amounts not disclosed.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="274",
        title="Procedure for imposing penalties",
        category=SectionCategory.PROCEDURE,
        related=["271(1)(c)", "270A", "271D", "271E", "271B"],
        note="Mandatory notice to assessee before penalty. Must specify exact "
             "charge. Failure to follow procedure = penalty void.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="271B",
        title="Failure to get accounts audited",
        category=SectionCategory.PENALTY,
        related=["44AB", "273B"],
        defences=["273B"],
        note="Penalty for not getting tax audit done under 44AB. "
             "Technical glitches, illness, and bona fide reasons accepted as "
             "reasonable cause under 273B.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="271AAA",
        title="Penalty for search — income admitted during search",
        category=SectionCategory.PENALTY,
        related=["132", "153A", "271AAB"],
        triggered_by=["132"],
        note="10% penalty if income admitted during search and declared in return. "
             "Effectively grants immunity from higher penalty.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="271AAB",
        title="Penalty for search — new provision",
        category=SectionCategory.PENALTY,
        related=["132", "153A", "271AAA"],
        triggered_by=["132"],
        note="Applies to searches initiated on/after 1-Jul-2012. "
             "30% if income admitted during search, 60% if not. "
             "Replaces 271AAA.",
        assessee_favorable=False,
    ),

    # ── TDS ───────────────────────────────────────────────────────────────────

    SectionNode(
        section="192",
        title="TDS on salaries",
        category=SectionCategory.TDS,
        related=["201", "271C", "192A"],
        penalties=["201", "271C"],
        note="Employer must deduct TDS on salary. Perquisites valuation and "
             "exemptions (HRA, LTA) commonly disputed.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="194A",
        title="TDS on interest other than interest on securities",
        category=SectionCategory.TDS,
        related=["201", "271C", "40(a)(ia)"],
        penalties=["201", "271C"],
        defences=["273B"],
        note="15G/15H declarations, threshold limits, bank cooperative "
             "exemptions litigated.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="194C",
        title="TDS on payments to contractors",
        category=SectionCategory.TDS,
        related=["194J", "40(a)(ia)", "201", "271C"],
        penalties=["201", "271C", "40(a)(ia)"],
        defences=["273B"],
        note="194C (2%) vs 194J (10%) characterisation is heavily litigated. "
             "Work contracts vs service contracts. Transport contractor "
             "PAN-based exemption.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="194H",
        title="TDS on commission or brokerage",
        category=SectionCategory.TDS,
        related=["194C", "194J", "40(a)(ia)", "201"],
        penalties=["201", "40(a)(ia)"],
        defences=["273B"],
        note="194H vs 194C characterisation — commission vs discount litigated. "
             "Telecom companies extensively litigated 194H.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="194I",
        title="TDS on rent",
        category=SectionCategory.TDS,
        related=["40(a)(ia)", "201", "194IC"],
        penalties=["201", "40(a)(ia)"],
        defences=["273B"],
        note="2% machinery/equipment, 10% land/building. "
             "CAM charges and maintenance charges TDS applicability litigated.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="194J",
        title="TDS on professional or technical fees",
        category=SectionCategory.TDS,
        related=["194C", "40(a)(ia)", "201", "271C"],
        penalties=["201", "271C", "40(a)(ia)"],
        defences=["273B"],
        note="194J (10%) vs 194C (2%) is most litigated TDS issue. "
             "Technical services vs works contract. Royalty vs FTS.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="195",
        title="TDS on other sums payable to non-residents",
        category=SectionCategory.TDS,
        related=["9", "90", "201", "206AA", "271C", "15CA", "15CB"],
        defences=["90"],  # DTAA override
        penalties=["201", "271C"],
        procedure=["195(2)", "195(3)", "197"],
        note="TDS on non-resident payments. DTAA override, 'make available' test "
             "for FTS, PE existence. No deduction if payer not beneficial owner. "
             "15CA/15CB certificate requirement.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="197",
        title="Certificate for lower rate TDS",
        category=SectionCategory.TDS,
        related=["195", "194J", "201"],
        note="Assessee can obtain nil/lower deduction certificate from AO. "
             "If certificate obtained in good faith and later found invalid, "
             "deductor protected.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="201",
        title="Consequences of failure to deduct or pay TDS",
        category=SectionCategory.TDS,
        related=["192", "194A", "194C", "194J", "195", "271C"],
        triggered_by=["194A", "194C", "194J", "194H", "194I", "195"],
        note="Deductor treated as 'assessee in default'. Interest under 201(1A) = "
             "1%/1.5% p.m. If payee has paid tax directly (Agarwal Industries "
             "principle), no TDS default — widely accepted.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="271C",
        title="Penalty for failure to deduct TDS",
        category=SectionCategory.PENALTY,
        related=["201", "273B"],
        defences=["273B"],
        triggered_by=["194A", "194C", "194J", "195"],
        note="Penalty = amount of TDS not deducted. Deleted if payee has paid "
             "tax — no revenue loss principle.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="206AA",
        title="TDS at higher rate for non-furnishing of PAN",
        category=SectionCategory.TDS,
        related=["195", "90", "201"],
        defences=["90"],   # DTAA overrides 206AA for non-residents
        note="20% TDS if PAN not provided. DTAA overrides 206AA for non-residents "
             "— landmark SC ruling in Wipro.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="40(a)(ia)",
        title="Disallowance for TDS default",
        category=SectionCategory.DEDUCTIONS,
        related=["194C", "194J", "194H", "194I", "40A(3)"],
        triggered_by=["194A", "194C", "194J", "194H", "194I"],
        note="30% disallowance if TDS not deducted/deposited. If payee files return "
             "and pays tax, disallowance deleted — second proviso to 40(a)(ia). "
             "Applicable to amounts payable as on 31-Mar, not amounts paid.",
        assessee_favorable=True,
    ),

    # ── DEDUCTIONS ────────────────────────────────────────────────────────────

    SectionNode(
        section="37(1)",
        title="Business expenditure — general deduction",
        category=SectionCategory.DEDUCTIONS,
        related=["40A(3)", "40(a)(ia)", "36(1)(iii)", "14A"],
        note="Expenditure must be (i) wholly and exclusively for business, "
             "(ii) not capital in nature, (iii) not personal. Capitalisation vs "
             "revenue expenditure is most litigated issue.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="40A(3)",
        title="Disallowance of cash payments exceeding ₹10,000",
        category=SectionCategory.DEDUCTIONS,
        related=["37(1)", "269SS", "40(a)(ia)"],
        defences=["40A(3)"],  # Rule 6DD exceptions
        note="Cash payments >₹10,000 disallowed. Rule 6DD carve-outs: agricultural "
             "produce, village without banking, transporter with PAN. "
             "Genuine business necessity and rural area accepted.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="43B",
        title="Certain deductions on actual payment basis",
        category=SectionCategory.DEDUCTIONS,
        related=["36(1)(va)", "36(1)(iii)", "37(1)"],
        note="Tax, duty, bonus, PF, ESI — deductible only on actual payment. "
             "Key issue: employee contribution to PF must be deposited before "
             "return due date (36(1)(va)) vs employer contribution under 43B.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="36(1)(iii)",
        title="Deduction of interest on borrowed capital",
        category=SectionCategory.DEDUCTIONS,
        related=["14A", "37(1)", "43B"],
        note="Interest on capital borrowed for business. If borrowed funds diverted "
             "to investment in tax-exempt income, 14A applies. Must prove direct "
             "nexus between loan and business use.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="36(1)(va)",
        title="Employee contribution to PF/ESI — deduction",
        category=SectionCategory.DEDUCTIONS,
        related=["43B"],
        note="Employee contributions to PF/ESI must be deposited by due date "
             "under the relevant Act, NOT by return filing date. "
             "Late deposit = disallowance regardless of 43B.",
        assessee_favorable=False,
    ),
    SectionNode(
        section="14A",
        title="Expenditure incurred in relation to exempt income",
        category=SectionCategory.DEDUCTIONS,
        related=["36(1)(iii)", "Rule 8D"],
        note="Disallows expenditure attributable to earning exempt income. "
             "Rule 8D formula applied if own funds sufficient for investments, "
             "no disallowance — Maxopp Investment SC principle.",
        assessee_favorable=True,
    ),

    # ── CAPITAL GAINS ─────────────────────────────────────────────────────────

    SectionNode(
        section="45",
        title="Capital gains — chargeability",
        category=SectionCategory.CAPITAL_GAINS,
        related=["48", "50", "50C", "2(47)", "54", "54F", "54EC"],
        note="Transfer of capital asset triggers capital gains. "
             "Year of chargeability, nature (STCG/LTCG), and AOP/BOI issues.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="50C",
        title="Capital gains — stamp duty value as full consideration",
        category=SectionCategory.CAPITAL_GAINS,
        related=["45", "56(2)(x)", "48", "69B"],
        defences=["50C(2)"],  # DVO reference
        note="Stamp duty value = full consideration for land/building. "
             "Assessee can request DVO valuation. If DVO value lower, DVO value applies. "
             "Court date valuation vs stamp duty date valuation.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="54",
        title="Capital gains exemption on sale of residential house",
        category=SectionCategory.EXEMPTIONS,
        related=["45", "54F", "54EC", "54B"],
        note="Exemption on LTCG from sale of residential house if proceeds invested "
             "in new residential house. One house limit post-2019 amendment. "
             "Construction completion within 3 years.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="54B",
        title="Capital gains on transfer of agricultural land",
        category=SectionCategory.EXEMPTIONS,
        related=["45", "54", "54F"],
        note="Exemption if proceeds invested in agricultural land within 2 years. "
             "Urban/rural agricultural land distinction, family member usage.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="54EC",
        title="Capital gains exemption — investment in specified bonds",
        category=SectionCategory.EXEMPTIONS,
        related=["45", "54", "54F"],
        note="LTCG exempt if invested in NHAI/REC bonds within 6 months. "
             "₹50L cap per AY. Time limit strictly enforced.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="54F",
        title="Capital gains on transfer of any long-term capital asset",
        category=SectionCategory.EXEMPTIONS,
        related=["45", "54", "54EC"],
        note="Full exemption if net consideration invested in residential house. "
             "Proportional if partial. Must not own more than one house. "
             "Construction vs purchase time limits.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="56(2)(x)",
        title="Income from other sources — receipt of property at undervalue",
        category=SectionCategory.SPECIAL_INCOME,
        related=["50C", "69B", "45"],
        note="Deemed income if property received for inadequate consideration. "
             "Relative gifts exempt. FMV vs stamp duty value litigated. "
             "Same section applies to both buyer and seller (50C for seller).",
        assessee_favorable=True,
    ),
    SectionNode(
        section="56(2)(viib)",
        title="Angel tax — share premium above FMV",
        category=SectionCategory.SPECIAL_INCOME,
        related=["56(2)(x)"],
        note="Premium on issue of shares above FMV taxed as income. "
             "DPIIT-recognised startups exempt. Rule 11UA valuation methods. "
             "DCF method vs NAV method.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="2(22)(e)",
        title="Deemed dividend — loans to shareholders",
        category=SectionCategory.SPECIAL_INCOME,
        related=["115-O", "2(22)"],
        note="Loan/advance by closely-held company to shareholder having "
             "substantial interest = deemed dividend. Must have accumulated profits. "
             "Trade advances excluded.",
        assessee_favorable=True,
    ),

    # ── ASSESSMENTS ───────────────────────────────────────────────────────────

    SectionNode(
        section="143(3)",
        title="Scrutiny assessment order",
        category=SectionCategory.ASSESSMENT,
        related=["143(2)", "144", "144B", "145", "263"],
        procedure=["143(2)", "144B"],
        note="Main assessment after scrutiny notice. Addition must be based on "
             "material on record. Opportunity of hearing mandatory.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="144",
        title="Best judgment assessment",
        category=SectionCategory.ASSESSMENT,
        related=["143(3)", "144B", "145"],
        note="Ex-parte assessment when assessee doesn't respond. "
             "Natural justice violation = major ground for appeal. "
             "Gross profit estimation must have comparable basis.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="144B",
        title="Faceless assessment",
        category=SectionCategory.ASSESSMENT,
        primary_court=CourtType.HC,
        related=["143(3)", "144", "270A"],
        note="All scrutiny assessments routed through NFAC. "
             "Show cause notice + 15-day response mandatory before addition. "
             "DIN mandatory on all communications. Non-compliance = void order. "
             "Heavy HC litigation since 2021.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="145",
        title="Method of accounting",
        category=SectionCategory.ASSESSMENT,
        related=["143(3)", "44AB"],
        note="AO can reject books of account and estimate income. "
             "Rejection must be based on specific defects — GP rate comparison "
             "with comparable cases required.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="263",
        title="Revision by PCIT — erroneous and prejudicial to revenue",
        category=SectionCategory.ASSESSMENT,
        primary_court=CourtType.ITAT,
        related=["264", "143(3)", "147", "144B"],
        note="PCIT can revise assessment if (i) erroneous AND (ii) prejudicial. "
             "Both conditions must co-exist. If AO took one of two possible views, "
             "not erroneous. Twin conditions strictly interpreted.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="264",
        title="Revision in favour of assessee",
        category=SectionCategory.ASSESSMENT,
        related=["263"],
        note="CIT can revise assessment in assessee's favour. "
             "Underutilised remedy — alternative to appeal in clear cases.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="154",
        title="Rectification of mistake apparent from record",
        category=SectionCategory.ASSESSMENT,
        related=["143(1)", "143(3)"],
        note="AO/ITAT/CIT(A) can rectify mistakes apparent from record. "
             "Not a substitute for appeal — debatable questions of law not rectifiable.",
        assessee_favorable=True,
    ),

    # ── INTERNATIONAL TAXATION ────────────────────────────────────────────────

    SectionNode(
        section="9",
        title="Income deemed to accrue or arise in India",
        category=SectionCategory.INTERNATIONAL_TAX,
        primary_court=CourtType.HC,
        related=["90", "195", "44BB", "44C"],
        defences=["90"],
        note="Business connection, salary, dividend, royalty, FTS deemed to accrue "
             "in India. 'Make available' test for FTS under most DTAAs. "
             "PE existence for business connection.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="90",
        title="Double taxation avoidance agreements",
        category=SectionCategory.INTERNATIONAL_TAX,
        primary_court=CourtType.HC,
        related=["9", "91", "195", "206AA"],
        note="DTAA provisions override domestic law if more beneficial to assessee. "
             "Residential status certificate, beneficial ownership, LOB clause. "
             "Treaty shopping limitations.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="91",
        title="Unilateral relief from double taxation",
        category=SectionCategory.INTERNATIONAL_TAX,
        related=["90"],
        note="Where no DTAA exists — credit for foreign tax paid. "
             "Applies only to resident assessees.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="92",
        title="Computation of income from international transactions",
        category=SectionCategory.TRANSFER_PRICING,
        primary_court=CourtType.ITAT,
        related=["92A", "92B", "92C", "92CA", "92E"],
        procedure=["92E", "92CA"],
        note="All international transactions between AEs must be at arm's length. "
             "Benchmarking, comparables, documentation requirements.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="92C",
        title="Computation of arm's length price",
        category=SectionCategory.TRANSFER_PRICING,
        related=["92", "92CA"],
        procedure=["92CA"],
        note="TNMM, CUP, RPM, CPM, PSM methods. Comparable selection, "
             "functional analysis, working capital adjustment. "
             "Most TP disputes litigated here.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="92CA",
        title="Reference to Transfer Pricing Officer",
        category=SectionCategory.TRANSFER_PRICING,
        related=["92", "92C"],
        triggered_by=["92"],
        note="AO refers TP determination to TPO. TPO's order binding on AO. "
             "Assessee can challenge TPO order before DRP/ITAT.",
        assessee_favorable=True,
    ),

    # ── APPEALS / PROCEDURE ───────────────────────────────────────────────────

    SectionNode(
        section="246A",
        title="Appealable orders before CIT(A)/NFAC",
        category=SectionCategory.APPEALS,
        related=["250", "253", "143(3)", "144", "271(1)(c)"],
        procedure=["250"],
        note="First appeal to CIT(A). Penalty orders, assessment orders all "
             "appealable. Stay of demand application before CIT(A).",
        assessee_favorable=True,
    ),
    SectionNode(
        section="250",
        title="Procedure in appeal before CIT(A)",
        category=SectionCategory.APPEALS,
        related=["246A", "253"],
        note="Additional evidence can be filed before CIT(A) with permission. "
             "CIT(A) can enhance assessment — limited use of enhancement power.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="253",
        title="Appeals to the Appellate Tribunal (ITAT)",
        category=SectionCategory.APPEALS,
        related=["254", "255", "260A", "246A"],
        procedure=["254", "255"],
        note="Second appeal to ITAT. Both assessee and Revenue can appeal. "
             "Stay of demand application. Cross-objections.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="254",
        title="Orders of Appellate Tribunal",
        category=SectionCategory.APPEALS,
        related=["253", "255", "260A"],
        note="ITAT can confirm, modify or annul. Rectification of ITAT order "
             "under 254(2). Special bench reference. Delay condonation.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="260A",
        title="Appeal to High Court",
        category=SectionCategory.APPEALS,
        primary_court=CourtType.HC,
        related=["253", "261"],
        note="Substantial question of law required. Factual findings of ITAT final. "
             "HC cannot re-appreciate evidence. 120-day limitation.",
        assessee_favorable=True,
    ),

    # ── SPECIAL / MAT / AMT ───────────────────────────────────────────────────

    SectionNode(
        section="115JB",
        title="Special provision for payment of tax by certain companies — MAT",
        category=SectionCategory.MAT,
        related=["115JAA"],
        note="15% tax on book profit if regular tax lower. Book profit adjustments "
             "under Explanation 1. MAT credit available for 15 years. "
             "Exempt income reduction from book profit.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="115JC",
        title="Alternative minimum tax for non-company assessees",
        category=SectionCategory.MAT,
        related=["115JD"],
        note="18.5% on adjusted total income for LLPs and individuals with "
             "certain deductions. AMT credit carryforward.",
        assessee_favorable=True,
    ),

    # ── INTEREST ──────────────────────────────────────────────────────────────

    SectionNode(
        section="234A",
        title="Interest for default in filing return",
        category=SectionCategory.INTEREST,
        related=["139", "234B", "234C"],
        note="1% p.m. on tax due from due date to filing date. "
             "Waiver under 220(2A) for genuine hardship.",
        assessee_favorable=False,
    ),
    SectionNode(
        section="234B",
        title="Interest for default in payment of advance tax",
        category=SectionCategory.INTEREST,
        related=["234A", "234C", "208"],
        note="1% p.m. on 90% of assessed tax not paid as advance tax. "
             "Capital gains mid-year — interest computation.",
        assessee_favorable=False,
    ),
    SectionNode(
        section="234C",
        title="Interest for deferment of advance tax",
        category=SectionCategory.INTEREST,
        related=["234A", "234B", "208"],
        note="1% on shortfall in quarterly advance tax instalments. "
             "Capital gains and casual income exempt from 234C computation — "
             "if paid in remaining instalments.",
        assessee_favorable=True,
    ),

    # ── RESIDENCE / SCOPE ─────────────────────────────────────────────────────

    SectionNode(
        section="6",
        title="Residence in India",
        category=SectionCategory.RESIDENCE,
        related=["5", "9", "90"],
        note="182-day rule + 60-day rule. RNOR status: 2 out of 10 years NR "
             "OR 729 days in last 7 years. NRI status and deemed residential. "
             "Finance Act 2020 amendments.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="64",
        title="Clubbing of income — spouse and minor child",
        category=SectionCategory.CLUBBING,
        related=["60", "61", "62", "63"],
        note="Spouse income clubbed if asset transferred without adequate "
             "consideration. Minor child income clubbed with higher-income parent. "
             "Exceptions: technical skill-based income.",
        assessee_favorable=True,
    ),

    # ── LOSS PROVISIONS ───────────────────────────────────────────────────────

    SectionNode(
        section="72",
        title="Carry forward and set off of business losses",
        category=SectionCategory.BUSINESS_INCOME,
        related=["72A", "79", "80", "139"],
        note="8-year carry forward of business loss. Must be set off against "
             "business income only. Return must be filed in time under 139(1).",
        assessee_favorable=True,
    ),
    SectionNode(
        section="72A",
        title="Carry forward of losses in case of amalgamation/demerger",
        category=SectionCategory.BUSINESS_INCOME,
        related=["72", "79"],
        note="Accumulated losses and unabsorbed depreciation carry forward on "
             "amalgamation if conditions met. Genuineness of amalgamation litigated.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="79",
        title="Carry forward of losses — change in shareholding",
        category=SectionCategory.BUSINESS_INCOME,
        related=["72", "80"],
        note="Loss carry forward denied if >49% change in beneficial shareholders. "
             "Start-up exemption. Change by inheritance not counted.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="80",
        title="Loss must be submitted in return filed within time",
        category=SectionCategory.BUSINESS_INCOME,
        related=["72", "139"],
        note="Belated return = loss not allowed to be carried forward. "
             "CBDT extensions of due dates and their impact.",
        assessee_favorable=False,
    ),

    # ── PRESUMPTIVE TAXATION ──────────────────────────────────────────────────

    SectionNode(
        section="44AD",
        title="Presumptive taxation for small businesses",
        category=SectionCategory.BUSINESS_INCOME,
        related=["44ADA", "44AE", "143(3)"],
        note="8%/6% of turnover = presumptive income for businesses <₹2Cr. "
             "If lower income claimed, books must be maintained + audit u/s 44AB. "
             "Once opted out, 5-year lock-in.",
        assessee_favorable=True,
    ),
    SectionNode(
        section="44ADA",
        title="Presumptive taxation for professionals",
        category=SectionCategory.BUSINESS_INCOME,
        related=["44AD", "44AB"],
        note="50% of gross receipts = presumptive income for professionals <₹75L. "
             "Specified professions: doctor, lawyer, CA, engineer etc.",
        assessee_favorable=True,
    ),

    # ── RETURN FILING ─────────────────────────────────────────────────────────

    SectionNode(
        section="139",
        title="Return of income",
        category=SectionCategory.PROCEDURE,
        related=["148", "80", "234A"],
        procedure=["234A"],
        note="Original return, belated return (139(4)), revised return (139(5)). "
             "Loss return must be filed on time. Updated return (139(8A)) within "
             "2 years — pays additional 25%/50% tax.",
        assessee_favorable=True,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Build fast-lookup index
# ─────────────────────────────────────────────────────────────────────────────

_GRAPH: dict[str, SectionNode] = {node.section: node for node in _NODES}


def get(section: str) -> SectionNode | None:
    """Return the SectionNode for a section, or None if unknown."""
    return _GRAPH.get(section)


def expand(sections: list[str], include_defences: bool = True,
           include_penalties: bool = True,
           include_procedure: bool = False) -> list[str]:
    """
    Expand a list of sections to the full set of related sections
    that should be searched for complete coverage.

    Args:
        sections         — sections from the case (e.g. ["269SS", "271D"])
        include_defences — add defence sections (273B for 271D cases)
        include_penalties— add penalty sections (271D for 269SS cases)
        include_procedure— add procedural sections (274 for penalties)

    Returns deduplicated list preserving original order first.
    """
    expanded: list[str] = list(sections)
    seen: set[str] = set(sections)

    for s in sections:
        node = _GRAPH.get(s)
        if node is None:
            continue

        for rel in node.related:
            if rel not in seen:
                seen.add(rel)
                expanded.append(rel)

        if include_defences:
            for d in node.defences:
                if d not in seen:
                    seen.add(d)
                    expanded.append(d)

        if include_penalties:
            for p in node.penalties:
                if p not in seen:
                    seen.add(p)
                    expanded.append(p)

        if include_procedure:
            for pr in node.procedure:
                if pr not in seen:
                    seen.add(pr)
                    expanded.append(pr)

    return expanded


def get_defences(sections: list[str]) -> list[str]:
    """Return all defence sections for the given sections."""
    defences: list[str] = []
    seen: set[str] = set()
    for s in sections:
        node = _GRAPH.get(s)
        if node:
            for d in node.defences:
                if d not in seen:
                    seen.add(d)
                    defences.append(d)
    return defences


def get_penalties(sections: list[str]) -> list[str]:
    """Return all penalty sections triggered by the given sections."""
    penalties: list[str] = []
    seen: set[str] = set()
    for s in sections:
        node = _GRAPH.get(s)
        if node:
            for p in node.penalties:
                if p not in seen:
                    seen.add(p)
                    penalties.append(p)
    return penalties


def get_context_note(sections: list[str]) -> str:
    """
    Return a concatenated plain-English description of each section.
    Used to enrich the Gemini query prompt with legal context.
    """
    lines = []
    for s in sections:
        node = _GRAPH.get(s)
        if node:
            lines.append(f"§ {s} ({node.title}): {node.note}")
    return "\n".join(lines)


def is_assessee_favorable(section: str) -> bool:
    """True if assessee generally wins ITAT cases on this section."""
    node = _GRAPH.get(section)
    return node.assessee_favorable if node else True


def get_category(section: str) -> SectionCategory | None:
    node = _GRAPH.get(section)
    return node.category if node else None


def sections_in_category(category: SectionCategory) -> list[str]:
    """Return all sections belonging to a given category."""
    return [n.section for n in _NODES if n.category == category]


def all_sections() -> list[str]:
    """Return all section identifiers in the graph."""
    return list(_GRAPH.keys())
