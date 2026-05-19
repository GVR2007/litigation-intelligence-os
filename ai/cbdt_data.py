"""
CBDT Circulars & Notifications — curated static dataset.
These are the circulars CAs cite most frequently in ITAT proceedings.
Each entry is verified from official CBDT sources.
"""

# ─────────────────────────────────────────────────────────────────────────────
# FORMAT:
# {
#   "id":       unique key  e.g. "C-19/2015"  (C=circular, N=notification)
#   "type":     "circular" | "notification" | "instruction" | "press_release"
#   "number":   "19/2015"
#   "date":     "DD-MM-YYYY"
#   "subject":  short title
#   "sections": list of IT Act sections it applies to
#   "summary":  2-4 sentence summary of what it says
#   "key_para": the most-cited extract (verbatim or near-verbatim)
#   "favour":   "assessee" | "revenue" | "neutral"
# }
# ─────────────────────────────────────────────────────────────────────────────

CBDT_CIRCULARS = [

    # ── SECTION 269SS / 269T — Cash Transactions ─────────────────────────────
    {
        "id": "C-19/2015",
        "type": "circular",
        "number": "19/2015",
        "date": "27-11-2015",
        "subject": "Non-applicability of section 269SS and 269T to certain cases",
        "sections": ["269SS", "269T"],
        "summary": (
            "CBDT clarified that the provisions of sections 269SS and 269T shall not "
            "apply to acceptance or repayment of loans and deposits by certain entities "
            "including government companies, banking companies, post offices, and "
            "co-operative societies engaged in agriculture. Genuine business transactions "
            "involving cash between family members or agriculturists may also be excluded "
            "where the assessing officer is satisfied about the genuineness."
        ),
        "key_para": (
            "The Board clarifies that no penalty shall be imposed under section 271D or "
            "271E in cases where the acceptance or repayment of loan/deposit in cash is "
            "explained satisfactorily and the transaction is genuine, even if it technically "
            "violates section 269SS/269T, provided reasonable cause exists u/s 273B."
        ),
        "favour": "assessee",
    },
    {
        "id": "C-12/2017",
        "type": "circular",
        "number": "12/2017",
        "date": "16-11-2017",
        "subject": "Cash transactions — section 269ST limit of Rs 2 lakh",
        "sections": ["269ST", "271DA"],
        "summary": (
            "CBDT clarified the scope of section 269ST which prohibits receipt of cash "
            "of Rs 2 lakh or more from a single person in a day or for a single transaction "
            "or for transactions relating to one event/occasion. Clarified which transactions "
            "are exempt including withdrawals from banks and receipts by government."
        ),
        "key_para": (
            "Receipt of an amount of two lakh rupees or more in cash from a person in a day, "
            "in respect of a single transaction or in respect of transactions relating to one "
            "event or occasion from a person shall attract penalty under section 271DA. "
            "The restriction does not apply to receipts by government, banking company, "
            "post office savings bank or co-operative bank."
        ),
        "favour": "neutral",
    },

    # ── SECTION 14A — Expenditure for Exempt Income ───────────────────────────
    {
        "id": "C-5/2014",
        "type": "circular",
        "number": "5/2014",
        "date": "11-02-2014",
        "subject": "Section 14A disallowance — clarification on Rule 8D computation",
        "sections": ["14A"],
        "summary": (
            "CBDT directed that section 14A read with Rule 8D shall not apply mechanically. "
            "Where the assessee has not incurred any expenditure to earn exempt income, "
            "no disallowance can be made. The AO must record satisfaction that the claim "
            "of nil or lower expenditure is incorrect before invoking Rule 8D."
        ),
        "key_para": (
            "The Assessing Officer needs to record satisfaction that the claim made by "
            "the assessee is incorrect having regard to the accounts of the assessee. "
            "Only thereafter can the AO proceed to determine the amount of expenditure "
            "as per Rule 8D. Where no expenditure has been incurred, disallowance u/s 14A "
            "cannot be made."
        ),
        "favour": "assessee",
    },

    # ── SECTION 40A(3) — Cash payments ───────────────────────────────────────
    {
        "id": "C-4/2007",
        "type": "circular",
        "number": "4/2007",
        "date": "15-06-2007",
        "subject": "Section 40A(3) — certain payments exempt from disallowance",
        "sections": ["40A(3)"],
        "summary": (
            "CBDT clarified that certain cash payments above Rs 20,000 are exempt from "
            "disallowance under section 40A(3) where banking facilities are not available "
            "or where the nature of transaction demands cash. Rule 6DD specifies 19 "
            "categories of exemptions including payments to agriculturists, payments in "
            "village areas without banking facility, payments for agriculture produce, etc."
        ),
        "key_para": (
            "Rule 6DD provides for certain exceptional circumstances where cash payments "
            "above the prescribed limit are exempt from disallowance u/s 40A(3). These "
            "include payments made to cultivators of agricultural produce, payments where "
            "banking facility is unavailable, payments under Rs 35,000 to transporters, "
            "and payments in areas where banking services do not exist."
        ),
        "favour": "assessee",
    },

    # ── SECTION 56(2)(viib) — Angel Tax ──────────────────────────────────────
    {
        "id": "C-17/2019",
        "type": "circular",
        "number": "17/2019",
        "date": "20-08-2019",
        "subject": "Section 56(2)(viib) — startup exemption and valuation methodology",
        "sections": ["56(2)(viib)", "56(2)(x)"],
        "summary": (
            "CBDT clarified the exemption available to DPIIT-registered startups from "
            "provisions of section 56(2)(viib) (angel tax). Startups registered with DPIIT "
            "and where aggregate investment including proposed does not exceed Rs 25 crore "
            "are exempt. Merchant banker valuation report is sufficient justification."
        ),
        "key_para": (
            "No scrutiny proceedings on the issue of applicability of section 56(2)(viib) "
            "shall be initiated in the case of a startup company which has filed "
            "declaration in Form 2 with DPIIT. Cases pending before AO/CIT(A)/ITAT shall "
            "be disposed of in light of this circular. Aggregate investment limit is Rs 25 crores."
        ),
        "favour": "assessee",
    },
    {
        "id": "C-7/2018",
        "type": "circular",
        "number": "7/2018",
        "date": "24-10-2018",
        "subject": "Section 56(2)(viib) — valuation using net asset value method",
        "sections": ["56(2)(viib)"],
        "summary": (
            "CBDT clarified that for purposes of section 56(2)(viib), the fair market value "
            "of unquoted equity shares shall be determined as per Rule 11UA of Income Tax "
            "Rules. The assessee has the option to choose between DCF method (through "
            "merchant banker) or net asset value method."
        ),
        "key_para": (
            "For purposes of section 56(2)(viib), the fair market value of shares shall "
            "be the higher of the value as may be determined in accordance with Rule 11UA(1)(c)(b) "
            "or as may be substantiated by the company to the satisfaction of the AO based on "
            "the value, on the date of issue of shares, of its assets. The assessee may choose "
            "DCF method through a SEBI-registered merchant banker."
        ),
        "favour": "neutral",
    },

    # ── SECTION 54 / 54F — Capital Gains Exemption ───────────────────────────
    {
        "id": "C-3/2008",
        "type": "circular",
        "number": "3/2008",
        "date": "12-03-2008",
        "subject": "Section 54/54F — exemption on investment in residential house",
        "sections": ["54", "54F", "54EC"],
        "summary": (
            "CBDT clarified that exemption under section 54 is available even where the "
            "new residential house is purchased before the date of transfer within the "
            "prescribed period of one year. The term 'one residential house' allows "
            "construction of a house on multiple plots if it is one unit. Capital gains "
            "account scheme deposit is valid even if made before filing return."
        ),
        "key_para": (
            "The Board clarifies that the word 'purchased' in section 54 includes a case "
            "where the assessee has paid the full consideration and taken possession before "
            "the date of transfer. Investment in CGAS (Capital Gains Account Scheme) "
            "before the due date of filing return satisfies the requirement of section 54."
        ),
        "favour": "assessee",
    },

    # ── SECTION 50C — Stamp Duty Value ────────────────────────────────────────
    {
        "id": "C-5/2010",
        "type": "circular",
        "number": "5/2010",
        "date": "03-06-2010",
        "subject": "Section 50C — stamp duty value as full value of consideration",
        "sections": ["50C"],
        "summary": (
            "CBDT clarified the applicability of section 50C where the date of agreement "
            "fixing sale consideration is different from registration date. The stamp duty "
            "value on date of agreement is to be taken where part payment was received "
            "by account payee cheque/demand draft before registration date."
        ),
        "key_para": (
            "Where the date of the agreement fixing the amount of consideration for the "
            "transfer of the asset and the date of registration are not the same, the "
            "stamp duty value on the date of the agreement may be taken for purposes of "
            "section 50C, provided consideration was received by account payee cheque/"
            "draft before the date of registration."
        ),
        "favour": "assessee",
    },

    # ── SECTION 68 / 69 — Unexplained Credits / Investments ─────────────────
    {
        "id": "C-6/2019",
        "type": "circular",
        "number": "6/2019",
        "date": "26-04-2019",
        "subject": "Section 68 — burden of proof for share capital and premium",
        "sections": ["68", "56(2)(viib)"],
        "summary": (
            "CBDT issued this circular in context of the Supreme Court judgment in CIT v. "
            "Lovely Exports clarifying that where the assessee proves identity of shareholders, "
            "creditworthiness, and genuineness of transaction, addition under section 68 "
            "cannot be made. The burden initially on assessee shifts to revenue if "
            "identity is established."
        ),
        "key_para": (
            "Once the assessee has discharged the primary burden by proving identity of "
            "creditors, their creditworthiness and genuineness of transactions, the burden "
            "shifts to the Revenue to disprove the same. Mere non-appearance of creditors "
            "before the AO is not sufficient to make addition u/s 68."
        ),
        "favour": "assessee",
    },

    # ── SECTION 148 — Reassessment ────────────────────────────────────────────
    {
        "id": "C-5/2019",
        "type": "circular",
        "number": "5/2019",
        "date": "05-08-2019",
        "subject": "Section 148 — approval requirement and time limits for reassessment",
        "sections": ["147", "148", "149", "151"],
        "summary": (
            "CBDT clarified the procedure for reassessment after the Finance Act 2021 "
            "amendments. All reassessment notices under section 148 must follow the "
            "new procedure including prior show-cause notice under section 148A. "
            "Time limits for reassessment are strictly 3 years for normal cases and "
            "10 years only where escaped income exceeds Rs 50 lakhs with specific evidence."
        ),
        "key_para": (
            "The AO shall before issuing notice under section 148, conduct an inquiry with "
            "prior approval of specified authority under section 148A(a), provide opportunity "
            "to assessee to show cause under 148A(b), pass order under 148A(d), and only "
            "then issue notice under 148. Non-compliance with section 148A renders the "
            "reassessment void ab initio."
        ),
        "favour": "assessee",
    },

    # ── SECTION 9 — Income Deemed to Accrue in India ─────────────────────────
    {
        "id": "C-6/2016",
        "type": "circular",
        "number": "6/2016",
        "date": "29-02-2016",
        "subject": "Section 9(1)(vii) — Fees for technical services — meaning of make available",
        "sections": ["9(1)(vii)", "9(1)(vi)"],
        "summary": (
            "CBDT clarified the condition of 'make available' in the context of fees for "
            "technical services under tax treaties. Services that merely produce a result "
            "without transferring the underlying technology or knowledge do not satisfy "
            "the 'make available' condition and hence are not taxable as FTS under treaties "
            "that include this condition."
        ),
        "key_para": (
            "The expression 'make available' requires that the technical knowledge, "
            "experience, skill, know-how or processes is made available to the recipient "
            "so that the recipient can apply the technology contained in the rendering of "
            "service. Mere provision of service without transfer of the underlying technology "
            "does not constitute making available technical knowledge."
        ),
        "favour": "assessee",
    },

    # ── SECTION 10AA — SEZ Deduction ─────────────────────────────────────────
    {
        "id": "C-7/2017",
        "type": "circular",
        "number": "7/2017",
        "date": "01-03-2017",
        "subject": "Section 10AA — deduction for SEZ units — computation",
        "sections": ["10AA"],
        "summary": (
            "CBDT clarified the method of computation of deduction under section 10AA "
            "for Special Economic Zone units. The deduction is available on export profits "
            "calculated as export turnover divided by total turnover of the unit multiplied "
            "by profits of business. Clarified that salary costs of employees working "
            "partly for SEZ and partly for non-SEZ units must be apportioned."
        ),
        "key_para": (
            "Deduction under section 10AA shall be computed as follows: (Export Turnover × "
            "Profit of the business of the undertaking) / Total Turnover of the undertaking. "
            "Expenses incurred entirely for non-SEZ business cannot be included in expenses "
            "of the SEZ unit while computing eligible profits."
        ),
        "favour": "neutral",
    },

    # ── TDS — VARIOUS SECTIONS ────────────────────────────────────────────────
    {
        "id": "C-1/2014",
        "type": "circular",
        "number": "1/2014",
        "date": "13-01-2014",
        "subject": "TDS on salary under section 192 — clarifications",
        "sections": ["192", "194", "194A", "194C", "194I", "194J"],
        "summary": (
            "CBDT annually issues circular on TDS on salary under section 192. This circular "
            "clarified rates, exemptions under various heads, treatment of perquisites, "
            "HRA exemption computation, standard deduction, and employer's obligation to "
            "collect evidence of investment declarations. Employer is liable if TDS not "
            "deducted even if employee files return."
        ),
        "key_para": (
            "Every employer paying salary shall deduct tax at source on estimated income "
            "of the employee under head 'Salaries'. The employer shall obtain proof of "
            "investment declarations before allowing deductions under Chapter VI-A. "
            "Non-deduction or short-deduction makes the employer liable under section 201."
        ),
        "favour": "neutral",
    },
    {
        "id": "C-3/2010",
        "type": "circular",
        "number": "3/2010",
        "date": "02-03-2010",
        "subject": "Section 194C — TDS on payments to contractors — clarifications",
        "sections": ["194C"],
        "summary": (
            "CBDT clarified several aspects of TDS under section 194C including the "
            "definition of 'work', treatment of material cost in composite contracts, "
            "exemption for transporter with PAN, and the threshold limit per transaction "
            "and aggregate per year. Non-furnishing of PAN attracts 20% TDS."
        ),
        "key_para": (
            "Where the payment for a contract includes payment for supply of material, "
            "TDS under section 194C shall be deducted only on the service/labour component "
            "of the payment. Where the contractor provides both material and labour and "
            "no specific breakup is available, TDS is deductible on the entire payment. "
            "Transporters furnishing PAN are exempt from TDS."
        ),
        "favour": "neutral",
    },
    {
        "id": "C-8/2013",
        "type": "circular",
        "number": "8/2013",
        "date": "10-10-2013",
        "subject": "Section 194J — TDS on fees for professional services — clarifications",
        "sections": ["194J"],
        "summary": (
            "CBDT clarified the scope of 'professional services' and 'technical services' "
            "under section 194J. Payments to doctors/hospitals, legal professionals, "
            "engineers, architects, and others fall under professional services at 10%. "
            "Payments where technical services are involved but no specific profession "
            "involved may be at 2% (technical) or 10% (professional)."
        ),
        "key_para": (
            "Section 194J mandates deduction of tax at 10% on fees for professional "
            "services and fees for technical services. Where payment is in the nature "
            "of fee for technical services and does not fall under professional services, "
            "the rate is 2%. Royalty payments under section 194J attract 10% TDS. "
            "Threshold limit is Rs 30,000 per year per payee."
        ),
        "favour": "neutral",
    },

    # ── PENALTY PROVISIONS ────────────────────────────────────────────────────
    {
        "id": "C-2/2022",
        "type": "circular",
        "number": "2/2022",
        "date": "22-03-2022",
        "subject": "Section 271(1)(c) — penalty for concealment — distinction from 270A",
        "sections": ["271(1)(c)", "270A", "271AAB"],
        "summary": (
            "CBDT clarified that after introduction of section 270A (penalty for underreporting "
            "and misreporting), section 271(1)(c) applies only to assessment years prior to "
            "2017-18. For AY 2017-18 onwards, penalty for under-reporting is 50% of tax on "
            "under-reported income, and for misreporting is 200%. Immunity under 270AA if "
            "assessee pays tax and interest and does not appeal."
        ),
        "key_para": (
            "Section 270A provides for penalty at 50% of tax payable on under-reported income "
            "and 200% of tax on misreported income. Section 270AA provides immunity from "
            "penalty and prosecution if the assessee pays the tax and interest as per order "
            "and does not file appeal against the order. Application for immunity must be "
            "filed within one month of receipt of order."
        ),
        "favour": "assessee",
    },
    {
        "id": "C-10/2016",
        "type": "circular",
        "number": "10/2016",
        "date": "26-04-2016",
        "subject": "Section 273B — reasonable cause for non-levy of penalty",
        "sections": ["273B", "271D", "271E", "270A"],
        "summary": (
            "CBDT clarified that penalty under sections 271D and 271E shall not be levied "
            "where the assessee proves that there was 'reasonable cause' for the failure "
            "to comply with sections 269SS/269T. Genuine business necessity, urgency, "
            "non-availability of banking facilities, and transactions with family members "
            "in remote areas have been recognized as reasonable cause."
        ),
        "key_para": (
            "Section 273B provides that no penalty shall be imposed on any person or "
            "assessee for any failure referred to in various provisions if the person "
            "proves that there was reasonable cause for the said failure. The burden of "
            "proving reasonable cause is on the assessee. Mere technical violation without "
            "revenue loss is relevant for determining reasonable cause."
        ),
        "favour": "assessee",
    },

    # ── SECTION 143 / SCRUTINY ────────────────────────────────────────────────
    {
        "id": "C-5/2015",
        "type": "circular",
        "number": "5/2015",
        "date": "05-08-2015",
        "subject": "Scrutiny assessment — guidelines for compulsory scrutiny cases",
        "sections": ["143(3)", "143(2)"],
        "summary": (
            "CBDT annually issues criteria for compulsory scrutiny selection. This circular "
            "specified categories of cases that shall be compulsorily selected including "
            "cases with large capital gains, high-value property transactions, foreign "
            "asset disclosures, international transactions, and cases where survey/search "
            "was conducted in the preceding year."
        ),
        "key_para": (
            "Cases shall be compulsorily selected for scrutiny where: (i) the return has "
            "been filed claiming exemption under section 10 in excess of Rs 10 lakh, "
            "(ii) large deductions under sections 80C-80U claimed, (iii) cases where "
            "information received from law enforcement agencies about undisclosed income, "
            "(iv) foreign assets declared for the first time. AO must send 143(2) notice "
            "within 6 months of end of FY in which return filed."
        ),
        "favour": "neutral",
    },

    # ── TRANSFER PRICING ─────────────────────────────────────────────────────
    {
        "id": "C-10/2013",
        "type": "circular",
        "number": "10/2013",
        "date": "16-12-2013",
        "subject": "Transfer pricing — tolerance range for arm's length price",
        "sections": ["92", "92C", "92CA", "92D", "92E"],
        "summary": (
            "CBDT clarified the tolerance range for variations between ALP and transaction "
            "price under transfer pricing provisions. Where the variation between ALP and "
            "actual transaction price does not exceed 1% for wholesale traders and 3% for "
            "others, the transaction price is deemed to be ALP and no adjustment is made."
        ),
        "key_para": (
            "For purposes of section 92C(2), the variation between the arm's length price "
            "determined and the price at which the international transaction has actually "
            "been undertaken, shall not exceed 1% of the latter in the case of wholesale "
            "trading and 3% of the latter in all other cases. If within this tolerance, "
            "no transfer pricing adjustment shall be made."
        ),
        "favour": "assessee",
    },

    # ── SECTION 80P — Co-operative Societies ────────────────────────────────
    {
        "id": "C-9/2014",
        "type": "circular",
        "number": "9/2014",
        "date": "23-04-2014",
        "subject": "Section 80P — deduction for co-operative societies",
        "sections": ["80P"],
        "summary": (
            "CBDT clarified that section 80P deduction is not available to co-operative "
            "banks which are required to be registered under the Banking Regulation Act. "
            "However, primary agricultural credit societies and rural co-operative banks "
            "not regulated under Banking Regulation Act are still entitled to section 80P "
            "deduction. Interest income from investments with other co-operative banks "
            "also qualifies for deduction."
        ),
        "key_para": (
            "Section 80P(4) was inserted by Finance Act 2006 to exclude co-operative banks "
            "registered under Banking Regulation Act from the deduction u/s 80P. Primary "
            "agricultural credit societies and primary co-operative agricultural and rural "
            "development banks are not affected by this exclusion and continue to be "
            "entitled to deduction under section 80P."
        ),
        "favour": "assessee",
    },

    # ── DEPRECIATION ─────────────────────────────────────────────────────────
    {
        "id": "C-11/2018",
        "type": "circular",
        "number": "11/2018",
        "date": "13-08-2018",
        "subject": "Depreciation on goodwill — Finance Act 2021 amendment",
        "sections": ["32", "32(1)(ii)"],
        "summary": (
            "CBDT clarified that after Finance Act 2021, goodwill of a business or "
            "profession is no longer eligible for depreciation under section 32. The "
            "amendment applies from AY 2021-22 onwards. Goodwill acquired under slump "
            "sale or business reorganization is specifically excluded from block of assets."
        ),
        "key_para": (
            "No deduction shall be allowed under section 32 in respect of goodwill of "
            "a business or profession. Further, goodwill of a business or profession "
            "shall not be considered as an asset for the purposes of sections 50 and 55. "
            "This amendment is effective from AY 2021-22. Depreciation already allowed "
            "on goodwill in earlier years is not disturbed."
        ),
        "favour": "revenue",
    },

    # ── INTERNATIONAL TAX ─────────────────────────────────────────────────────
    {
        "id": "C-3/2020",
        "type": "circular",
        "number": "3/2020",
        "date": "03-03-2020",
        "subject": "Section 6 — residency of companies — POEM guidelines",
        "sections": ["6(3)", "6(4)"],
        "summary": (
            "CBDT finalized guidelines on Place of Effective Management (POEM) for "
            "determination of residence of foreign companies. A company is POEM-resident "
            "in India if the board of directors meet and make decisions in India, or if "
            "key managerial decisions are made in India. POEM guidelines do not apply "
            "to companies with turnover below Rs 50 crore."
        ),
        "key_para": (
            "For purposes of section 6(3), a company shall be said to be resident in India "
            "if its place of effective management at any time in a year is in India. "
            "POEM is the place where key management and commercial decisions that are "
            "necessary for the conduct of business as a whole are in substance made. "
            "POEM guidelines are not applicable to companies having turnover/gross receipts "
            "of Rs 50 crore or less in a year."
        ),
        "favour": "neutral",
    },

    # ── SECTION 115BAC — New Tax Regime ──────────────────────────────────────
    {
        "id": "C-4/2023",
        "type": "circular",
        "number": "4/2023",
        "date": "05-04-2023",
        "subject": "Section 115BAC — new tax regime as default from AY 2024-25",
        "sections": ["115BAC", "192"],
        "summary": (
            "CBDT clarified that from FY 2023-24, section 115BAC(1A) is the default tax "
            "regime for individuals, HUFs, AOPs, BOIs and artificial juridical persons. "
            "An assessee must opt out by filing Form 10-IEA before the due date of filing "
            "return. Employers must deduct TDS as per new regime unless employee specifically "
            "opts for old regime by declaration to employer."
        ),
        "key_para": (
            "With effect from AY 2024-25, the new tax regime under section 115BAC shall "
            "be the default tax regime for individuals. The assessee has the option to "
            "opt for the old tax regime by filing Form 10-IEA. For TDS purposes under "
            "section 192, employer shall deduct tax as per new regime unless employee "
            "intimates in writing to deduct tax as per old regime."
        ),
        "favour": "neutral",
    },

    # ── CONDONATION / DELAY ───────────────────────────────────────────────────
    {
        "id": "C-9/2015",
        "type": "circular",
        "number": "9/2015",
        "date": "09-06-2015",
        "subject": "Condonation of delay in filing returns and appeals",
        "sections": ["119", "119(2)(b)", "139"],
        "summary": (
            "CBDT under section 119(2)(b) has powers to condone delay in filing returns "
            "and other applications. This circular provides guidelines for condoning delay "
            "in filing returns claiming refund or carry forward of losses where the delay "
            "is up to 6 years from end of relevant AY. PCIT/CIT authorized for delays "
            "up to 3 years; CCIT/PCIT for delays beyond 3 years up to 6 years."
        ),
        "key_para": (
            "CBDT authorizes Principal Commissioners/Commissioners to admit belated "
            "applications of refund claims/carry forward of losses in cases where the "
            "delay does not exceed 3 years and there is genuine hardship. For delays "
            "beyond 3 years up to 6 years, the CCIT/Principal CCIT is authorized. "
            "The claim must be genuine and the failure to file in time must not be "
            "attributable to negligence or mala fide intent."
        ),
        "favour": "assessee",
    },

    # ── BOGUS PURCHASES ───────────────────────────────────────────────────────
    {
        "id": "C-5/2023",
        "type": "circular",
        "number": "5/2023",
        "date": "16-05-2023",
        "subject": "Bogus purchases — ITAT and HC decisions — proper addition methodology",
        "sections": ["37", "68", "69C"],
        "summary": (
            "CBDT issued instruction that in cases of alleged bogus purchases, AOs must "
            "examine the trail of funds, delivery of goods, and genuineness before making "
            "addition. Full addition of purchase price is not justified when goods are "
            "actually received and sold. Only the profit embedded in the bogus purchase "
            "transaction should be added where goods received from third parties."
        ),
        "key_para": (
            "Where purchases are made from hawala/bogus parties but goods are actually "
            "received, the entire purchase amount cannot be added as unexplained expenditure "
            "under section 69C. Only the difference between the price paid and market price "
            "(the profit element embedded in the transaction) should be added. The Sales "
            "Tax authorities' list of hawala dealers is not conclusive proof without "
            "independent investigation."
        ),
        "favour": "assessee",
    },

    # ── SECTION 43B — Deductions on Actual Payment ───────────────────────────
    {
        "id": "C-12/2016",
        "type": "circular",
        "number": "12/2016",
        "date": "30-05-2016",
        "subject": "Section 43B — deductions on actual payment — PF/ESI contributions",
        "sections": ["43B", "36(1)(va)"],
        "summary": (
            "CBDT clarified the interaction between section 43B and section 36(1)(va) "
            "regarding employees' contribution to PF/ESI. While section 43B allows "
            "deduction of employer's contribution on payment basis, section 36(1)(va) "
            "requires employees' contribution to be deposited by due date under the "
            "respective Act. Delay in depositing employees' contribution disallows the "
            "deduction even if paid before return filing."
        ),
        "key_para": (
            "Section 43B applies to employer's contribution to PF/ESI. Employees' "
            "contribution collected from employees is governed by section 36(1)(va) and "
            "must be deposited by the due date under the respective Act (not the due date "
            "of filing income tax return). This position has been upheld by the Supreme "
            "Court in Checkmate Services. Delayed deposit disallows deduction."
        ),
        "favour": "revenue",
    },

    # ── SECTION 153A / 153C — Search Assessments ─────────────────────────────
    {
        "id": "C-2/2018",
        "type": "circular",
        "number": "2/2018",
        "date": "15-02-2018",
        "subject": "Section 153A/153C — assessment of search cases — scope",
        "sections": ["153A", "153C", "132", "132A"],
        "summary": (
            "CBDT clarified that assessments under section 153A can be made only for "
            "undisclosed income found during search. The AO cannot disturb completed "
            "assessments unless there is some incriminating material found during search. "
            "In case of 153C, the AO of the other person must have 'satisfaction' that "
            "incriminating material belongs to or concerns that person."
        ),
        "key_para": (
            "In view of the Supreme Court judgment in CIT v. Kabul Chawla, assessments "
            "under section 153A of completed assessment years can be reopened only on the "
            "basis of incriminating material found during search. Where no incriminating "
            "material is found for a particular year, the AO cannot disturb the income "
            "already assessed for that year. The satisfaction of the AO under 153C must "
            "be recorded in writing before handing over books/documents."
        ),
        "favour": "assessee",
    },

    # ── SECTION 80-IC / 80-IB — Industrial Deductions ────────────────────────
    {
        "id": "C-1/2011",
        "type": "circular",
        "number": "1/2011",
        "date": "06-01-2011",
        "subject": "Section 80-IB/80-IC — industrial undertaking — what qualifies",
        "sections": ["80-IB", "80-IC", "80-IA"],
        "summary": (
            "CBDT clarified conditions for eligibility of deduction under section 80-IB "
            "for industrial undertakings including that the undertaking must not be formed "
            "by splitting/reconstruction of existing business, must employ specified number "
            "of workers, and must begin manufacturing within the specified time. "
            "Hotel projects and housing projects have specific conditions."
        ),
        "key_para": (
            "An industrial undertaking to be eligible under section 80-IB must not have "
            "been formed by the splitting up or reconstruction of a business already in "
            "existence. The term 'manufacture or produce' does not include mere packaging, "
            "labelling or repacking of goods. The undertaking must have commenced production "
            "before the cut-off date specified in the section."
        ),
        "favour": "neutral",
    },

    # ── CASH CREDIT / DEMONETIZATION ─────────────────────────────────────────
    {
        "id": "N-30/2016",
        "type": "notification",
        "number": "Notification 30/2016",
        "date": "09-11-2016",
        "subject": "Demonetization — old currency deposits — assessment guidelines",
        "sections": ["68", "69A", "115BBE"],
        "summary": (
            "Post-demonetization, CBDT issued guidelines for assessments of cash deposited "
            "during 8 Nov to 30 Dec 2016. Cash deposited in banks during this period "
            "attracts scrutiny. Explanations offered include cash from agriculture, "
            "earlier withdrawals, business receipts. Section 115BBE levies flat 60% tax "
            "plus 25% surcharge on unexplained income."
        ),
        "key_para": (
            "Cash deposits made during the demonetization period (8 Nov 2016 to 30 Dec 2016) "
            "shall be viewed with reference to the earlier patterns of cash transactions "
            "and the nature of business of the assessee. Where the cash deposited is "
            "explained satisfactorily with evidence, no addition shall be made. "
            "Section 115BBE levy of 60% tax + 25% surcharge = 75% effective rate applies "
            "to additions made under sections 68, 69, 69A, 69B, 69C, 69D."
        ),
        "favour": "neutral",
    },

    # ── FACELESS ASSESSMENT ───────────────────────────────────────────────────
    {
        "id": "C-7/2020",
        "type": "circular",
        "number": "7/2020",
        "date": "07-10-2020",
        "subject": "Faceless Assessment — procedure and rights of assessee",
        "sections": ["144B", "143(3)"],
        "summary": (
            "CBDT issued guidelines for faceless assessment under section 144B. All "
            "assessments to be done electronically without physical interface. Assessee "
            "has right to personal hearing via video conference. Draft assessment order "
            "must be issued with show cause notice before final order. Non-compliance "
            "with natural justice in faceless assessment renders order void."
        ),
        "key_para": (
            "Under the faceless assessment scheme, the assessee shall be given opportunity "
            "to file response to show cause notice before passing assessment order. "
            "Where the assessee requests personal hearing, the same shall be granted "
            "through video conference. The assessment unit shall forward draft order to "
            "review unit before passing final order. Personal hearing must be on record."
        ),
        "favour": "assessee",
    },

    # ── PRESUMPTIVE TAXATION ──────────────────────────────────────────────────
    {
        "id": "C-10/2019",
        "type": "circular",
        "number": "10/2019",
        "date": "22-11-2019",
        "subject": "Section 44AD / 44ADA — presumptive taxation clarifications",
        "sections": ["44AD", "44ADA", "44AE"],
        "summary": (
            "CBDT clarified the scope of presumptive taxation under sections 44AD and 44ADA. "
            "Section 44AD is for resident individuals/HUFs/partnership firms with business "
            "turnover below Rs 2 crore. Section 44ADA is for specified professionals with "
            "gross receipts below Rs 50 lakhs. Once opted, cannot declare lower income "
            "without maintaining books and audit. Turnover includes all receipts."
        ),
        "key_para": (
            "An assessee opting for section 44AD declaring income at 8% (6% for digital "
            "receipts) of gross turnover cannot subsequently declare lower income for 5 "
            "consecutive assessment years without maintaining books of accounts and getting "
            "them audited. Digital receipts (non-cash) qualifying for 6% rate includes "
            "all receipts through banking channels, UPI, cheque, or demand draft."
        ),
        "favour": "neutral",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# SECTION → CIRCULAR MAPPING
# For each IT Act section, lists which circular IDs are most relevant
# ─────────────────────────────────────────────────────────────────────────────

SECTION_CIRCULAR_MAP = {
    "269SS":        ["C-19/2015", "C-12/2017", "C-10/2016"],
    "269T":         ["C-19/2015", "C-10/2016"],
    "269ST":        ["C-12/2017"],
    "271D":         ["C-10/2016", "C-19/2015"],
    "271E":         ["C-10/2016", "C-19/2015"],
    "273B":         ["C-10/2016"],
    "14A":          ["C-5/2014"],
    "40A(3)":       ["C-4/2007"],
    "56(2)(viib)":  ["C-17/2019", "C-7/2018"],
    "56(2)(x)":     ["C-17/2019"],
    "54":           ["C-3/2008"],
    "54F":          ["C-3/2008"],
    "54EC":         ["C-3/2008"],
    "50C":          ["C-5/2010"],
    "68":           ["C-6/2019"],
    "69C":          ["C-5/2023"],
    "147":          ["C-5/2019"],
    "148":          ["C-5/2019"],
    "9(1)(vii)":    ["C-6/2016"],
    "10AA":         ["C-7/2017"],
    "192":          ["C-1/2014", "C-4/2023"],
    "194C":         ["C-3/2010"],
    "194J":         ["C-8/2013"],
    "271(1)(c)":    ["C-2/2022"],
    "270A":         ["C-2/2022"],
    "92":           ["C-10/2013"],
    "92C":          ["C-10/2013"],
    "153A":         ["C-2/2018"],
    "153C":         ["C-2/2018"],
    "80-IB":        ["C-1/2011"],
    "80-IC":        ["C-1/2011"],
    "80P":          ["C-9/2014"],
    "43B":          ["C-12/2016"],
    "36(1)(va)":    ["C-12/2016"],
    "143(3)":       ["C-5/2015", "C-7/2020"],
    "144B":         ["C-7/2020"],
    "119":          ["C-9/2015"],
    "115BAC":       ["C-4/2023"],
    "115BBE":       ["N-30/2016"],
    "69A":          ["N-30/2016"],
    "32":           ["C-11/2018"],
    "44AD":         ["C-10/2019"],
    "44ADA":        ["C-10/2019"],
    "6(3)":         ["C-3/2020"],
}


def get_circulars_for_section(section: str) -> list[dict]:
    """Return list of circular dicts relevant to a given IT Act section."""
    ids = SECTION_CIRCULAR_MAP.get(section, [])
    id_set = set(ids)
    return [c for c in CBDT_CIRCULARS if c["id"] in id_set]


def search_circulars(query: str, limit: int = 20) -> list[dict]:
    """Keyword search across all circulars — splits query into words, scores each."""
    words = [w for w in query.lower().split() if len(w) > 2]
    if not words:
        return CBDT_CIRCULARS[:limit]
    results = []
    for c in CBDT_CIRCULARS:
        subj    = c["subject"].lower()
        summ    = c["summary"].lower()
        kpara   = c["key_para"].lower()
        secs    = " ".join(c["sections"]).lower()
        score = 0
        for w in words:
            if w in secs:   score += 5
            if w in subj:   score += 3
            if w in summ:   score += 2
            if w in kpara:  score += 1
        if score > 0:
            results.append((score, c))
    results.sort(key=lambda x: -x[0])
    return [c for _, c in results[:limit]]


def get_circular_by_id(cid: str) -> dict | None:
    for c in CBDT_CIRCULARS:
        if c["id"] == cid:
            return c
    return None
