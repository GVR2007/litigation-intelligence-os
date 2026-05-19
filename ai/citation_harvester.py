"""
Citation Harvester — comprehensive coverage of ALL litigated sections
in the Income Tax Act, 1961.

STRATEGY (why year-by-year date ranges work):
  IK's search returns the SAME top 10-30 docs for any keyword variation.
  But fromdate/todate parameters are TRUE server-side filters — each year
  returns a DIFFERENT result set.

  Pass 1 — CORE queries, no date filter    → top landmark cases
  Pass 2 — YEAR SWEEP: for each year 2012-2024, run 2 broad queries
            with fromdate/todate → genuinely different judgments per year

  120 sections × (5 core + 26 year-sweep) × 2 pages × 10 = ~74,400 raw
  After dedup → ~15,000+ unique verified citations
"""

import time
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ai.indian_kanoon import search_cases, clean_html
from database.init_db import get_connection

# ─────────────────────────────────────────────────────────────────────────────
# Helper — generate year queries (2018-2024) + bench queries for any section
# ─────────────────────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────────────────────
# CORE QUERIES — 120 sections, 4-7 precise queries each
# Then extended by year + bench + broad layers in harvest_section()
# ─────────────────────────────────────────────────────────────────────────────

_CORE_QUERIES = {

    # ── CASH TRANSACTION PENALTIES ────────────────────────────────────────────
    "269SS": [
        "section 269SS cash loan penalty deleted reasonable cause ITAT",
        "269SS genuine transaction 273B bona fide penalty ITAT",
        "section 269SS penalty cash loan agricultural emergency",
        "269SS penalty deleted explanation accepted High Court",
        "269SS penalty cash loan family member genuine",
        "section 269SS 271D penalty cash business exigency",
    ],
    "269T": [
        "section 269T cash repayment penalty deleted ITAT",
        "269T lender insistence affidavit penalty ITAT",
        "section 269T reasonable cause 273B penalty waived",
        "269T penalty quashed genuine cash repayment",
    ],
    "269ST": [
        "section 269ST 2 lakh cash receipt penalty 271DA ITAT",
        "269ST cash receipt exemption hospital marriage penalty deleted",
        "section 269ST agricultural payment cash exemption",
        "269ST penalty deleted genuine transaction ITAT",
    ],
    "271D": [
        "section 271D penalty 269SS income tax deleted",
        "271D penalty deleted reasonable cause 273B ITAT",
        "section 271D penalty quashed genuine cash loan",
        "271D penalty business exigency cash loan ITAT",
        "section 271D penalty waived High Court assessee",
    ],
    "271E": [
        "section 271E penalty 269T cash repayment deleted ITAT",
        "271E lender insistence affidavit reasonable cause",
        "section 271E penalty quashed genuine repayment",
        "271E business necessity penalty ITAT",
    ],
    "271DA": [
        "section 271DA penalty 269ST cash receipt ITAT",
        "271DA penalty deleted reasonable cause ITAT",
        "271DA cash 2 lakh penalty exemption ITAT",
    ],
    "273B": [
        "section 273B reasonable cause penalty income tax",
        "273B bona fide mistake penalty deleted ITAT",
        "section 273B genuine transaction no penalty",
        "273B medical emergency reasonable cause penalty",
        "section 273B sufficient cause penalty waived Supreme Court",
        "273B ignorance of law reasonable cause ITAT",
    ],

    # ── UNEXPLAINED INCOME ────────────────────────────────────────────────────
    "68": [
        "section 68 unexplained cash credit identity creditworthiness genuineness ITAT",
        "68 share capital unsecured loan identity bank statement deleted",
        "section 68 gift money ITR proof accepted ITAT deleted",
        "68 share application money bogus addition deleted ITAT",
        "section 68 creditworthiness confirmation affidavit ITAT",
        "68 cash credit burden shifted AO disprove ITAT",
        "section 68 director shareholder ITR filed bank transfer",
    ],
    "69": [
        "section 69 unexplained investment income tax ITAT",
        "69 agricultural income gift source funds deleted",
        "section 69 unexplained investment land purchase source explained",
        "69 addition deleted source proved bank statement",
        "section 69 investment property source origin ITAT",
    ],
    "69A": [
        "section 69A unexplained money bullion jewellery ITAT",
        "69A household jewellery CBDT circular exempt deleted",
        "section 69A cash in hand unexplained explained ITAT",
        "69A gold silver inherited source ITAT deleted",
        "section 69A prior stock declaration search ITAT",
    ],
    "69B": [
        "section 69B investment value undisclosed ITAT",
        "69B understatement investment deleted ITAT",
        "section 69B real estate undervaluation ITAT",
    ],
    "69C": [
        "section 69C unexplained expenditure bogus purchases ITAT",
        "69C unexplained expenditure source explained deleted",
        "section 69C purchases genuine bills documents",
        "69C bogus purchases addition deleted High Court",
    ],
    "115BBE": [
        "section 115BBE unexplained income 60 percent tax ITAT",
        "115BBE addition deleted explanation accepted",
        "section 115BBE constitutional validity High Court",
        "115BBE surcharge unexplained income ITAT",
    ],

    # ── BUSINESS DEDUCTIONS ───────────────────────────────────────────────────
    "28": [
        "section 28 profits gains business profession income tax ITAT",
        "28 keyman insurance business income taxable ITAT",
        "section 28 income business profession scope ITAT",
        "28 adventure in nature of trade ITAT",
    ],
    "32": [
        "section 32 depreciation plant machinery goodwill ITAT",
        "32 depreciation intangible asset goodwill allowed",
        "section 32 goodwill depreciation Supreme Court High Court",
        "32 additional depreciation new plant machinery ITAT",
        "section 32 block of assets WDV depreciation ITAT",
        "32 depreciation software intangible asset ITAT",
    ],
    "35": [
        "section 35 scientific research expenditure deduction ITAT",
        "35 R&D expenditure capital revenue deduction",
        "section 35(2AB) approved R&D facility deduction",
        "35 scientific research weighted deduction ITAT",
    ],
    "35D": [
        "section 35D preliminary expenditure amortisation ITAT",
        "35D deduction amortised preliminary expenses",
    ],
    "36": [
        "section 36 deductions business income tax ITAT",
        "36 bad debt written off deduction allowed",
        "section 36(1)(iii) interest borrowed capital business",
        "36 1 vii bad debt write off ITAT",
        "section 36 bank interest deduction borrowing ITAT",
    ],
    "36(1)(va)": [
        "section 36(1)(va) employees PF ESI due date ITAT",
        "36 1 va delayed payment PF ESI disallowance deleted",
        "section 36 1 va due date before filing return",
        "36 1 va employee PF deposit Supreme Court High Court",
        "section 36 1 va EPF ESI contribution disallowance",
    ],
    "37": [
        "section 37 business expenditure allowable income tax ITAT",
        "37 personal expense disallowance business purpose",
        "section 37 revenue capital expenditure boundary ITAT",
        "37 business necessity expenditure deleted disallowance",
        "section 37 advertisement brand expense deduction ITAT",
        "37 CSR expenditure business deduction ITAT",
    ],
    "40": [
        "section 40(a)(ia) TDS disallowance payee return filed ITAT",
        "40 a ia TDS non-deduction disallowance deleted",
        "section 40(a)(i) non-resident TDS DTAA exemption",
        "40 b partner remuneration salary deduction firm ITAT",
        "section 40 a ii income tax surcharge cess deduction",
    ],
    "40A(3)": [
        "section 40A(3) cash payment disallowance rule 6DD ITAT",
        "40A 3 agriculturist village no bank cash payment",
        "section 40A3 rule 6DD exception disallowance deleted",
        "40A3 cash payment genuine business necessity ITAT",
        "section 40A3 High Court rule 6DD exemption",
    ],
    "41": [
        "section 41(1) remission cessation liability taxable ITAT",
        "41 1 waiver loan cessation income ITAT",
        "section 41 trading liability remission ITAT",
    ],
    "43B": [
        "section 43B actual payment PF ESI deduction ITAT",
        "43B due date payment bonus government dues",
        "section 43B disallowance deleted actual payment",
        "43B ESIC PF payment before due date High Court",
    ],
    "43CA": [
        "section 43CA stamp duty value business property ITAT",
        "43CA builder property stamp duty value addition",
        "section 43CA immovable property transfer business",
        "43CA date agreement registration stamp duty ITAT",
    ],
    "44AD": [
        "section 44AD presumptive taxation 8 percent ITAT",
        "44AD digital transaction 6 percent turnover",
        "section 44AD eligible business gross receipts",
        "44AD commission agent presumptive income ITAT",
    ],
    "44ADA": [
        "section 44ADA presumptive profession 50 percent ITAT",
        "44ADA professional income doctor engineer lawyer ITAT",
    ],
    "44AE": [
        "section 44AE goods carriage presumptive income ITAT",
        "44AE truck transport presumptive taxation ITAT",
    ],
    "14A": [
        "section 14A rule 8D exempt income disallowance ITAT",
        "14A no disallowance own funds exempt income",
        "section 14A satisfaction recorded AO disallowance",
        "14A disallowance deleted no exempt income earned",
        "section 14A rule 8D proportionate disallowance",
        "14A investment dividend income disallowance ITAT",
    ],

    # ── CAPITAL GAINS ─────────────────────────────────────────────────────────
    "45": [
        "section 45 capital gains transfer income tax ITAT",
        "45 capital gain land development agreement JDA",
        "section 45 capital gains deemed transfer ITAT",
        "45 year of capital gains accrual ITAT",
    ],
    "47": [
        "section 47 transfer not regarded capital gains ITAT",
        "47 gift family partition amalgamation exempt",
        "section 47 transfer wholly owned subsidiary exempt",
        "47 conversion stock in trade capital asset ITAT",
    ],
    "48": [
        "section 48 capital gains computation indexed cost",
        "48 indexation improvement cost computation ITAT",
        "section 48 full value consideration capital gains",
    ],
    "50": [
        "section 50 depreciable asset capital gains WDV ITAT",
        "50 block of assets short term capital gains",
    ],
    "50B": [
        "section 50B slump sale capital gains income tax ITAT",
        "50B slump sale business undertaking valuation",
        "section 50B net worth computation slump sale",
    ],
    "50C": [
        "section 50C stamp duty value capital gains ITAT",
        "50C date of agreement stamp duty value different",
        "section 50C DVO reference fair market value",
        "50C stamp duty value addition deleted registered",
        "section 50C agreement sale valuation High Court",
        "50C capital gains stamp duty below market ITAT",
    ],
    "54": [
        "section 54 capital gains exemption residential house ITAT",
        "54 new house construction 3 years exemption",
        "section 54 one residential property exemption ITAT",
        "54 exemption joint property co-owner ITAT",
    ],
    "54B": [
        "section 54B agricultural land capital gains exemption",
        "54B land reinvestment agricultural ITAT",
    ],
    "54EC": [
        "section 54EC NHAI REC bond capital gains exemption ITAT",
        "54EC 6 months time limit bond investment",
        "section 54EC exemption delayed investment ITAT",
        "54EC capital gain bond 50 lakh limit ITAT",
    ],
    "54F": [
        "section 54F capital gains exemption net consideration ITAT",
        "54F residential house exemption ITAT",
        "section 54F proportionate exemption ITAT",
        "54F not qualified residential house ITAT",
    ],
    "111A": [
        "section 111A short term capital gains equity STT ITAT",
        "111A STCG 15 percent STT listed shares",
        "section 111A penny stock bogus STT exemption ITAT",
    ],
    "112": [
        "section 112 long term capital gains 20 percent ITAT",
        "112 indexed cost LTCG computation ITAT",
        "section 112 long term capital gains rate proviso",
    ],
    "112A": [
        "section 112A long term capital gains equity 10 percent ITAT",
        "112A LTCG listed shares 1 lakh exemption",
        "section 112A grandfathering valuation 31 January 2018",
    ],

    # ── INCOME FROM OTHER SOURCES ─────────────────────────────────────────────
    "56(2)(x)": [
        "section 56(2)(x) gift money property inadequate consideration ITAT",
        "56 2 x relative gift exemption FMV deleted",
        "section 56 2 x property stamp duty value addition",
        "56 2 x genuine transaction relatives ITAT",
    ],
    "56(2)(viib)": [
        "section 56(2)(viib) angel tax startup FMV share premium ITAT",
        "56 2 viib DPIIT exemption rule 11UA valuation",
        "section 56 2 viib DCF method fair market value",
        "angel tax startup DPIIT certificate deleted ITAT",
        "56 2 viib NAV method share premium ITAT",
        "section 56 2 viib addition deleted valuation report",
    ],
    "56(2)(vii)": [
        "section 56(2)(vii) gift property received relative ITAT",
        "56 2 vii stamp duty value inadequate consideration",
        "section 56 2 vii relative HUF gift exempt ITAT",
    ],
    "2(22)(e)": [
        "section 2(22)(e) deemed dividend loan shareholder ITAT",
        "2 22 e deemed dividend accumulated profits",
        "section 2 22 e 10 percent shareholder loan advance",
        "2 22 e deemed dividend deleted no accumulated profits",
        "section 2 22 e trade advance not dividend ITAT",
    ],

    # ── CHARITABLE TRUSTS / EXEMPTIONS ───────────────────────────────────────
    "11": [
        "section 11 charitable trust income exemption ITAT",
        "11 accumulation 15 percent trust income",
        "section 11 application income objects trust",
        "11 commercial activity charitable purpose ITAT",
    ],
    "12A": [
        "section 12A charitable trust registration ITAT",
        "12A registration trust cancellation",
        "section 12A 12AA provisional final registration",
    ],
    "12AA": [
        "section 12AA trust registration cancellation ITAT",
        "12AA cancellation charitable purpose violated",
        "section 12AA registration denial rejected ITAT",
    ],
    "13": [
        "section 13 trust benefit prohibited person ITAT",
        "13 trust exemption denied interested person",
        "section 13(1)(c) founder trustee benefit denied",
    ],
    "10(23C)": [
        "section 10(23C) educational institution exemption ITAT",
        "10 23C university hospital approval exemption",
        "section 10 23C corpus donation accumulation ITAT",
    ],
    "10(38)": [
        "section 10(38) long term capital gains equity exempt ITAT",
        "10 38 penny stock STT bogus claim deleted",
        "section 10 38 listed shares LTCG exemption",
    ],
    "10AA": [
        "section 10AA SEZ deduction export profit ITAT",
        "10AA SEZ unit export turnover deduction",
        "section 10AA SEZ initial year formation ITAT",
        "10AA SEZ deduction disallowed computation ITAT",
    ],

    # ── DEDUCTIONS CHAPTER VI-A ───────────────────────────────────────────────
    "80C": [
        "section 80C deduction life insurance PPF ITAT",
        "80C ELSS PPF NSC FD deduction",
        "section 80C deduction disallowed ITAT High Court",
    ],
    "80D": [
        "section 80D medical insurance premium ITAT",
        "80D health insurance family senior citizen",
        "section 80D deduction disallowed ITAT",
    ],
    "80G": [
        "section 80G donation deduction income tax ITAT",
        "80G donation disallowed cancelled trust",
        "section 80G 50 percent 100 percent approval",
        "80G donation cash above 2000 disallowed ITAT",
    ],
    "80-IA": [
        "section 80IA infrastructure deduction income tax ITAT",
        "80IA infrastructure undertaking deduction disallowed",
        "section 80IA initial year eligible profit",
        "80IA profit derived from business deduction ITAT",
    ],
    "80-IB": [
        "section 80IB industrial undertaking deduction ITAT",
        "80IB deduction disallowed computation High Court",
        "section 80IB profit derived deduction allowed",
        "80IB housing project 100 percent deduction",
    ],
    "80-IC": [
        "section 80IC special category states deduction ITAT",
        "80IC Uttarakhand Himachal Pradesh industrial",
        "section 80IC substantial expansion deduction",
    ],
    "80P": [
        "section 80P cooperative society deduction ITAT",
        "80P credit cooperative banking business denied",
        "section 80P primary cooperative exemption ITAT",
        "80P cooperative society High Court deduction",
    ],
    "80JJAA": [
        "section 80JJAA new employment deduction ITAT",
        "80JJAA additional employee 30 percent deduction",
    ],

    # ── TDS ───────────────────────────────────────────────────────────────────
    "192": [
        "section 192 TDS salary employer deduction ITAT",
        "192 TDS perquisite salary computation",
        "section 192 short deduction employer ITAT",
    ],
    "193": [
        "section 193 TDS interest securities debenture ITAT",
        "193 TDS interest non-deduction bank",
    ],
    "194A": [
        "section 194A TDS interest bank NRI ITAT",
        "194A TDS interest threshold branch aggregate",
        "section 194A TDS non-deduction penalty ITAT",
    ],
    "194C": [
        "section 194C TDS contractor sub-contractor ITAT",
        "194C TDS transport owner operator single truck",
        "section 194C 194J overlap technical services",
        "194C TDS non-deduction disallowance deleted ITAT",
    ],
    "194H": [
        "section 194H TDS commission brokerage agent ITAT",
        "194H TDS commission discount principal agent",
        "section 194H TDS non-deduction disallowance ITAT",
    ],
    "194I": [
        "section 194I TDS rent income tax ITAT",
        "194I TDS rent plant machinery infrastructure",
        "section 194I TDS rent definition service charge",
        "194I TDS hotel accommodation ITAT",
    ],
    "194IA": [
        "section 194IA TDS immovable property purchase ITAT",
        "194IA TDS 1 percent property buyer stamp duty",
        "section 194IA TDS non-deduction property ITAT",
    ],
    "194J": [
        "section 194J TDS professional technical fees ITAT",
        "194J 194C overlap technical services contract",
        "section 194J TDS non-deduction disallowance",
        "194J TDS royalty fees technical services",
    ],
    "194LA": [
        "section 194LA TDS compulsory acquisition ITAT",
        "194LA compensation land acquisition TDS",
    ],
    "195": [
        "section 195 TDS non-resident payment ITAT",
        "195 DTAA certificate exempt non-resident TDS",
        "section 195 short deduction non-resident",
        "195 royalty FTS non-resident TDS rate ITAT",
        "section 195 15CA 15CB non-resident payment",
    ],
    "197": [
        "section 197 lower deduction TDS certificate ITAT",
        "197 nil lower TDS non-resident",
    ],
    "201": [
        "section 201 failure deduct TDS consequences ITAT",
        "201 assessee in default interest TDS",
        "section 201(1A) interest TDS default paid",
        "201 TDS deposited late interest computation",
    ],
    "206AA": [
        "section 206AA PAN non-furnishing TDS 20 percent ITAT",
        "206AA non-resident DTAA override higher rate",
        "section 206AA PAN TDS rate higher ITAT",
    ],
    "206C": [
        "section 206C tax collection at source TCS ITAT",
        "206C TCS scrap alcohol forest produce",
        "section 206C motor vehicle sale TCS",
    ],

    # ── INTERNATIONAL TAXATION ────────────────────────────────────────────────
    "9": [
        "section 9(1) income deemed accrue India ITAT",
        "9(1)(vii) fees technical services make available",
        "section 9 royalty business connection PE India",
        "9 1 vi royalty non-resident source rule ITAT",
        "section 9 FTS technical services non-resident",
    ],
    "90": [
        "section 90 DTAA double taxation avoidance ITAT",
        "90 DTAA beneficial provisions apply treaty",
        "section 90 treaty override domestic law ITAT",
        "90 DTAA capital gains exemption treaty ITAT",
        "section 90 DTAA residential status certificate",
    ],
    "91": [
        "section 91 unilateral relief double taxation ITAT",
        "91 tax credit foreign income no DTAA",
    ],
    "92": [
        "section 92 transfer pricing international transaction ITAT",
        "92 ALP arm length related party transaction",
        "section 92 transfer pricing adjustment deleted",
    ],
    "92C": [
        "section 92C arm's length price transfer pricing ITAT",
        "92C TNMM CUP method comparables adjustment",
        "section 92C ALP determination comparable companies",
        "92C transfer pricing adjustment deleted ITAT",
        "section 92C arm length price method selection",
    ],
    "92CA": [
        "section 92CA TPO reference arm length price ITAT",
        "92CA TPO order transfer pricing officer",
        "section 92CA reference transfer pricing officer",
    ],

    # ── ASSESSMENTS ───────────────────────────────────────────────────────────
    "139": [
        "section 139 return income belated revised ITAT",
        "139 belated return loss carry forward denied",
        "section 139(5) revised return income tax",
        "139 due date extension return filing ITAT",
    ],
    "143(3)": [
        "section 143(3) scrutiny assessment addition ITAT",
        "143 3 scrutiny addition deleted ITAT",
        "section 143 3 ex parte best judgment ITAT",
        "143 3 opportunity hearing assessment ITAT",
    ],
    "144": [
        "section 144 best judgment assessment ITAT",
        "144 ex parte assessment natural justice deleted",
        "section 144 best judgment opportunity notice",
    ],
    "144B": [
        "section 144B faceless assessment natural justice ITAT",
        "144B show cause notice hearing opportunity",
        "section 144B faceless assessment quashed ITAT",
        "144B DIN system addition without notice ITAT",
        "section 144B faceless penalty natural justice High Court",
    ],
    "145": [
        "section 145 method accounting mercantile cash ITAT",
        "145 rejection books gross profit rate ITAT",
        "section 145 accounting method change ITAT",
        "145(3) rejection books account estimation ITAT",
    ],
    "147": [
        "section 147 income escaping assessment ITAT",
        "147 change of opinion reassessment void",
        "section 147 fresh tangible material beyond 4 years",
        "147 148 notice reasons to believe recorded",
        "section 147 audit objection reassessment ITAT",
    ],
    "148": [
        "section 148 notice reassessment income escaping ITAT",
        "148 notice time limit reasons recorded",
        "section 148 invalid notice ITAT High Court",
        "148 notice beyond 6 years limitation ITAT",
    ],
    "148A": [
        "section 148A show cause notice prior approval ITAT",
        "148A inquiry before reassessment opportunity",
        "section 148A reply ignored reassessment ITAT",
        "148A procedure PCIT approval mandatory ITAT",
    ],
    "149": [
        "section 149 time limit reassessment notice ITAT",
        "149 limitation 3 years 10 years income escaping",
        "section 149 extended time limit ITAT High Court",
    ],
    "151": [
        "section 151 sanction reassessment notice ITAT",
        "151 JCIT CIT approval without application mind",
        "section 151 mechanical sanction ITAT",
    ],

    # ── SEARCH AND SEIZURE ────────────────────────────────────────────────────
    "132": [
        "section 132 search seizure income tax ITAT",
        "132 statement during search retraction",
        "section 132 panchnama cash jewellery books",
        "132 search warrant seized material ITAT",
    ],
    "132A": [
        "section 132A requisition documents ITAT",
        "132A power to requisition ITAT",
    ],
    "133A": [
        "section 133A survey income tax statement ITAT",
        "133A survey statement retraction not under oath",
        "section 133A survey cash found addition ITAT",
        "133A survey statement admissibility ITAT",
    ],
    "153A": [
        "section 153A search assessment incriminating material ITAT",
        "153A completed assessment protection incriminating",
        "section 153A no incriminating material no addition",
        "153A abated assessment search Supreme Court",
        "section 153A search assessment High Court ITAT",
    ],
    "153B": [
        "section 153B time limit search assessment ITAT",
        "153B limitation period extension search",
        "section 153B time limit search barred ITAT",
    ],
    "153C": [
        "section 153C satisfaction other person search ITAT",
        "153C satisfaction note AO incriminating material",
        "section 153C notice quashed satisfaction invalid",
        "153C document belonging other person ITAT",
    ],

    # ── REVISION / APPEALS ────────────────────────────────────────────────────
    "263": [
        "section 263 revision PCIT erroneous prejudicial ITAT",
        "263 revision quashed two views possible ITAT",
        "section 263 erroneous prejudicial to revenue",
        "263 revision set aside AO inquiry ITAT",
    ],
    "264": [
        "section 264 revision other orders PCIT ITAT",
        "264 revision time limit application ITAT",
    ],
    "254": [
        "section 254 ITAT tribunal order recall ITAT",
        "254 recall order mistake apparent record",
        "section 254 additional ground ITAT admission",
        "254 stay demand ITAT tribunal power",
    ],

    # ── PENALTIES ─────────────────────────────────────────────────────────────
    "270A": [
        "section 270A underreporting misreporting penalty ITAT",
        "270A penalty deleted bona fide ITAT",
        "section 270A immunity penalty waived ITAT",
        "270A misreporting quashed reasonable ITAT",
    ],
    "271(1)(c)": [
        "section 271(1)(c) penalty concealment inaccurate ITAT",
        "271 1 c bona fide mistake penalty deleted",
        "section 271 1 c notice defective both limbs",
        "271 1 c penalty deleted two views possible",
        "section 271 1 c concealment penalty quashed",
        "271 1 c honest disclosure penalty ITAT",
    ],
    "271AAA": [
        "section 271AAA undisclosed income search penalty ITAT",
        "271AAA penalty deleted explanation ITAT",
    ],
    "271AAB": [
        "section 271AAB undisclosed income search rate ITAT",
        "271AAB penalty deleted explanation ITAT",
        "section 271AAB rate 30 60 percent ITAT",
    ],
    "271B": [
        "section 271B penalty failure audit accounts ITAT",
        "271B penalty deleted reasonable cause audit",
        "section 271B audit not conducted penalty ITAT",
    ],
    "271C": [
        "section 271C penalty failure deduct TDS ITAT",
        "271C TDS non-deduction penalty deleted",
        "section 271C penalty TDS High Court Supreme Court",
    ],
    "271F": [
        "section 271F penalty failure furnish return ITAT",
        "271F return not filed reasonable cause",
    ],
    "271G": [
        "section 271G penalty transfer pricing documentation ITAT",
        "271G TP documentation penalty waived ITAT",
    ],
    "271H": [
        "section 271H penalty TDS TCS return filing ITAT",
        "271H late filing TDS return penalty",
    ],

    # ── INTEREST ─────────────────────────────────────────────────────────────
    "234A": [
        "section 234A interest default return filing ITAT",
        "234A interest waiver reasonable cause",
        "section 234A interest levy deleted ITAT",
    ],
    "234B": [
        "section 234B interest advance tax default ITAT",
        "234B advance tax default interest deleted",
        "section 234B interest computation ITAT",
    ],
    "234C": [
        "section 234C interest advance tax instalment ITAT",
        "234C capital gains advance tax instalment",
        "section 234C interest deleted capital gains ITAT",
    ],

    # ── MAT / AMT ─────────────────────────────────────────────────────────────
    "115JB": [
        "section 115JB MAT minimum alternate tax ITAT",
        "115JB book profit computation adjustment",
        "section 115JB MAT credit utilisation ITAT",
        "115JB MAT exempt income provision DTA ITAT",
    ],
    "115JC": [
        "section 115JC AMT alternate minimum tax ITAT",
        "115JC AMT individual deduction adjustment",
    ],

    # ── SPECIAL PROVISIONS ────────────────────────────────────────────────────
    "115O": [
        "section 115O dividend distribution tax ITAT",
        "115O DDT exempt recipient ITAT",
    ],
    "115QA": [
        "section 115QA buyback shares tax ITAT",
        "115QA buyback additional income tax company",
    ],
    "72A": [
        "section 72A amalgamation carry forward loss ITAT",
        "72A accumulated loss carry forward merger ITAT",
    ],
    "79": [
        "section 79 shareholding change carry forward loss ITAT",
        "79 51 percent change loss carry forward denied",
    ],
    "80": [
        "section 80 loss return due date carry forward ITAT",
        "80 loss belated return denied carry forward",
    ],
    "64": [
        "section 64 clubbing income spouse minor child ITAT",
        "64 clubbing transfer assets spouse ITAT",
        "section 64 minor child income parent ITAT",
    ],
    "6": [
        "section 6 residence India NRI RNOR ITAT",
        "6 residential status 182 days test ITAT",
        "section 6 RNOR beneficial provision ITAT",
    ],
    "115BBH": [
        "section 115BBH virtual digital asset crypto tax ITAT",
        "115BBH cryptocurrency bitcoin capital gains ITAT",
    ],
    "44BB": [
        "section 44BB non-resident oil exploration ITAT",
        "44BB offshore oil services presumptive ITAT",
    ],
    "44C": [
        "section 44C non-resident head office expenditure",
        "44C deduction non-resident ITAT",
    ],
    "50A": [
        "section 50A lease assets depreciation WDV ITAT",
        "50A leased asset capital gains ITAT",
    ],
    "80-IE": [
        "section 80IE north east industrial undertaking ITAT",
        "80IE deduction North East India ITAT",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# HARVEST_TARGETS — core queries + year + bench + broad (auto-expanded)
# Total queries per section: ~20 avg  |  pages: 3  |  results: 10
# 120 × 20 × 3 × 10 = 72,000 raw → ~15,000 unique
# ─────────────────────────────────────────────────────────────────────────────

# HARVEST_TARGETS = list of (section_tag, core_queries)
# Year sweep is handled inside harvest_section() via fromdate/todate API params
HARVEST_TARGETS = list(_CORE_QUERIES.items())

# Used only in _fetch_and_save; harvest_section passes pages=2 directly
PAGES_PER_QUERY  = 2
RESULTS_PER_PAGE = 10
API_DELAY        = 0.5   # seconds between API calls


def _infer_court_type(docsource: str) -> str:
    src = docsource.lower()
    if "supreme court" in src:
        return "SC"
    if "high court" in src or any(hc in src for hc in [
        "bombay", "delhi", "madras", "calcutta", "allahabad", "gujarat",
        "karnataka", "punjab", "kerala", "rajasthan", "andhra", "telangana",
        "orissa", "patna", "gauhati", "himachal", "uttarakhand",
        "chhattisgarh", "jharkhand", "jammu",
    ]):
        return "HC"
    if "appellate tribunal" in src or "itat" in src:
        return "ITAT"
    return "OTHER"


def _extract_year(datestr: str) -> int:
    if not datestr:
        return 0
    m = re.search(r"\b(19|20)\d{2}\b", datestr)
    return int(m.group()) if m else 0


def _save_citation(cur, section: str, doc: dict, sections_json: str = "") -> bool:
    tid = str(doc.get("tid", ""))
    if not tid:
        return False
    title      = clean_html(doc.get("title", "Untitled"))
    headline   = clean_html(doc.get("headline", ""))
    date       = doc.get("publishdate", "")
    source     = doc.get("docsource", "")
    url        = f"https://indiankanoon.org/doc/{tid}/"
    court_type = _infer_court_type(source)
    year       = _extract_year(date)

    citation = f"{title} ({source}, {date})" if source else f"{title} ({date})"
    if len(citation) > 250:
        citation = citation[:247] + "..."

    try:
        cur.execute("""
            INSERT OR IGNORE INTO itat_precedents
            (case_citation, section, bench, year, outcome, key_ratio,
             facts_summary, win_for_assessee, relevance_score,
             ik_tid, ik_url, court_type, verified, sections_json, harvested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
        """, (
            citation, section, source, year,
            "Verified case — see full text on Indian Kanoon",
            headline[:500] if headline else "See full text on Indian Kanoon",
            headline[:300] if headline else "",
            1, 0.7,
            tid, url, court_type,
            sections_json or f'["{section}"]',
        ))
        return cur.rowcount > 0
    except Exception:
        return False


def _fetch_and_save(cur, section: str, query: str,
                    seen_tids: set, pages: int = 2,
                    fromdate: str = "", todate: str = "") -> int:
    """
    Fetch up to `pages` pages of IK results for one query (with optional date range).
    Saves new docs to DB.  Returns count of newly inserted rows.
    """
    added = 0
    for page in range(pages):
        try:
            raw  = search_cases(query, pagenum=page,
                                 fromdate=fromdate, todate=todate)
            docs = raw.get("docs", [])
            if not docs:
                break

            for doc in docs[:RESULTS_PER_PAGE]:
                tid = str(doc.get("tid", ""))
                if tid and tid not in seen_tids:
                    seen_tids.add(tid)
                    if _save_citation(cur, section, doc):
                        added += 1

            if "error" in raw:
                break

            time.sleep(API_DELAY)
        except Exception:
            break
    return added


def harvest_section(section: str, section_queries: list,
                    progress_callback=None) -> int:
    """
    Two-pass harvest for one section:

    Pass 1 — CORE queries with no date filter (2 pages each).
              Captures landmark / frequently cited cases.

    Pass 2 — YEAR SWEEP: for each year 2012–2024, run 2 broad queries
              with fromdate/todate so IK filters server-side.
              Each year is a genuinely different result set.
    """
    conn = get_connection()
    cur  = conn.cursor()
    added     = 0

    # ── Pre-load already-known IK tids from DB — avoids re-fetching them ─────
    cur.execute(
        "SELECT ik_tid FROM itat_precedents WHERE ik_tid != '' AND verified = 1"
    )
    seen_tids: set = {row[0] for row in cur.fetchall()}

    # ── Pass 1: core queries, no date filter ─────────────────────────────────
    core_queries = section_queries  # already built in HARVEST_TARGETS
    for query in core_queries:
        n = _fetch_and_save(cur, section, query, seen_tids, pages=2)
        added += n

    # ── Pass 2: year sweep 2012-2024 ─────────────────────────────────────────
    # Use 2 broad queries per year — keeps API calls reasonable
    broad = [
        f"section {section} income tax",
        f"{section} penalty ITAT High Court",
    ]
    years = range(2012, 2025)   # 13 years × 2 queries × 2 pages = 52 calls per section
    for year in years:
        fd = f"01-01-{year}"
        td = f"31-12-{year}"
        for q in broad:
            n = _fetch_and_save(cur, section, q, seen_tids,
                                pages=2, fromdate=fd, todate=td)
            added += n
        if progress_callback and year % 3 == 0:
            progress_callback(f"    year {year} done (+{added} total so far)")

    conn.commit()
    conn.close()
    return added


def harvest_all(progress_callback=None) -> dict:
    """
    Harvest all 120 sections using core + year-sweep strategy.
    Expected: 15,000+ unique citations.
    """
    summary = {}
    total   = 0
    n_sections = len(HARVEST_TARGETS)
    for i, (section, section_queries) in enumerate(HARVEST_TARGETS):
        if progress_callback:
            progress_callback(
                f"[{i+1}/{n_sections}] § {section} — "
                f"core queries + year sweep 2012-2024..."
            )
        count = harvest_section(section, section_queries, progress_callback)
        summary[section] = count
        total += count
        if progress_callback:
            progress_callback(
                f"  ✅ § {section}: +{count}  (DB total: {total:,})"
            )
    return {"by_section": summary, "total_added": total}


def get_citation_count() -> int:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM itat_precedents WHERE verified IN (1, 2)")
    count = cur.fetchone()[0]
    conn.close()
    return count


def get_citations_for_section(section: str, limit: int = 20,
                               court_type: str = "ALL") -> list:
    conn = get_connection()
    cur  = conn.cursor()
    order = "CASE court_type WHEN 'SC' THEN 1 WHEN 'HC' THEN 2 WHEN 'ITAT' THEN 3 ELSE 4 END"
    if court_type != "ALL":
        cur.execute(f"""
            SELECT * FROM itat_precedents
            WHERE section=? AND verified IN (1,2) AND court_type=?
            ORDER BY {order}, year DESC LIMIT ?
        """, (section, court_type, limit))
    else:
        cur.execute(f"""
            SELECT * FROM itat_precedents
            WHERE section=? AND verified IN (1,2)
            ORDER BY {order}, year DESC LIMIT ?
        """, (section, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def search_citations(query: str, section: str = "", limit: int = 15) -> list:
    conn = get_connection()
    cur  = conn.cursor()
    q = f"%{query}%"
    if section:
        cur.execute("""
            SELECT * FROM itat_precedents
            WHERE verified IN (1,2) AND section=?
              AND (LOWER(case_citation) LIKE LOWER(?)
                   OR LOWER(key_ratio) LIKE LOWER(?)
                   OR LOWER(facts_summary) LIKE LOWER(?))
            ORDER BY verified DESC,
                     CASE court_type WHEN 'SC' THEN 1 WHEN 'HC' THEN 2 ELSE 3 END,
                     year DESC LIMIT ?
        """, (section, q, q, q, limit))
    else:
        cur.execute("""
            SELECT * FROM itat_precedents
            WHERE verified IN (1,2)
              AND (LOWER(case_citation) LIKE LOWER(?)
                   OR LOWER(key_ratio) LIKE LOWER(?)
                   OR LOWER(facts_summary) LIKE LOWER(?))
            ORDER BY verified DESC,
                     CASE court_type WHEN 'SC' THEN 1 WHEN 'HC' THEN 2 ELSE 3 END,
                     year DESC LIMIT ?
        """, (q, q, q, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def format_citations_for_ai(citations: list) -> str:
    if not citations:
        return ""
    lines = ["VERIFIED CITATIONS (use ONLY these — do not invent any others):"]
    for i, c in enumerate(citations, 1):
        line = f"{i}. {c['case_citation']}"
        if c.get("key_ratio"):
            line += f"\n   Ratio: {c['key_ratio'][:200]}"
        if c.get("ik_url"):
            line += f"\n   Link: {c['ik_url']}"
        lines.append(line)
    return "\n".join(lines)


def format_citations_for_display(citations: list) -> str:
    if not citations:
        return ""
    court_order = {"SC": "🏛️ Supreme Court", "HC": "⚖️ High Court",
                   "ITAT": "📋 ITAT", "OTHER": "📄 Other"}
    groups: dict = {}
    for c in citations:
        ct = court_order.get(c.get("court_type", "OTHER"), "📄 Other")
        groups.setdefault(ct, []).append(c)

    lines = []
    for court_label in ["🏛️ Supreme Court", "⚖️ High Court", "📋 ITAT", "📄 Other"]:
        group = groups.get(court_label, [])
        if not group:
            continue
        lines.append(f"\n**{court_label}**")
        for c in group:
            title = c["case_citation"][:80]
            url   = c.get("ik_url", "")
            ratio = c.get("key_ratio", "")[:120]
            year  = f" ({c['year']})" if c.get("year") else ""
            if url:
                lines.append(f"- [{title}{year}]({url})")
            else:
                lines.append(f"- {title}{year}")
            if ratio:
                lines.append(f"  *{ratio}*")
    return "\n".join(lines)
