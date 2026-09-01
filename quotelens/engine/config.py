"""
All pricing/eligibility data lives here, and nowhere else.

Every table below is transcribed from reference/pricing-and-guidelines.md and
carries that file's verification flag inline:
    OK  = verified against a primary source
    SEC = secondary source, structurally right, verify before hardcoding
    ILL = illustrative, no authoritative public source, calibration only

An operations person should be able to change any number in this file
without touching the logic in eligibility.py / pricing.py / costs.py.
"""

from __future__ import annotations

REFERENCE_DOC = "reference/pricing-and-guidelines.md"

# ---------------------------------------------------------------------------
# Band definitions
# ---------------------------------------------------------------------------
# LTV/CLTV bands are EXCLUSIVE-UPPER on the label ("75-80" = 75.01-80.00) but
# each band's stored upper bound is INCLUSIVE, and bands are consulted in
# ascending order of that upper bound. That combination is what makes 80.000
# land in "75-80" while 80.001 lands in "80-85". See section 2 / section 8.3.
# (label, upper_bound_inclusive) — upper_bound_inclusive=None means "no cap".
LTV_BANDS: list[tuple[str, float | None]] = [
    ("<30", 30.0),
    ("30-60", 60.0),
    ("60-70", 70.0),
    ("70-75", 75.0),
    ("75-80", 80.0),
    ("80-85", 85.0),
    ("85-90", 90.0),
    ("90-95", 95.0),
    (">95", None),
]

# FICO bands, consulted by checking membership in (lo, hi) inclusive.
FICO_BANDS: list[tuple[str, int, int]] = [
    (">=780", 780, 9999),
    ("760-779", 760, 779),
    ("740-759", 740, 759),
    ("720-739", 720, 739),
    ("700-719", 700, 719),
    ("680-699", 680, 699),
    ("660-679", 660, 679),
    ("640-659", 640, 659),
    ("<=639", 0, 639),
]


def ltv_band(ltv: float) -> str:
    """Exclusive-upper band lookup. 80.000 -> '75-80'; 80.001 -> '80-85'."""
    ltv = round(ltv, 3)
    for label, upper in LTV_BANDS:
        if upper is None or ltv <= upper:
            return label
    raise ValueError(f"LTV {ltv} did not match any band")  # unreachable


def fico_band(fico: int) -> str:
    for label, lo, hi in FICO_BANDS:
        if lo <= fico <= hi:
            return label
    raise ValueError(f"FICO {fico} did not match any band")  # unreachable


# ---------------------------------------------------------------------------
# 2. Fannie Mae LLPAs
# Source: LLPA Matrix, effective 01/28/2026 (SEC — spot-checked, not
# cell-by-cell re-verified against the PDF; see "three things to verify").
# LTV column order matches LTV_BANDS above.
# ---------------------------------------------------------------------------
_LTV_COLS = ["<30", "30-60", "60-70", "70-75", "75-80", "80-85", "85-90", "90-95", ">95"]

LLPA_PURCHASE: dict[str, dict[str, float]] = {
    ">=780":    dict(zip(_LTV_COLS, [0.000, 0.000, 0.000, 0.000, 0.375, 0.375, 0.250, 0.250, 0.125])),
    "760-779":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.000, 0.250, 0.625, 0.625, 0.500, 0.500, 0.250])),
    "740-759":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.125, 0.375, 0.875, 1.000, 0.750, 0.625, 0.500])),
    "720-739":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.250, 0.750, 1.250, 1.250, 1.000, 0.875, 0.750])),
    "700-719":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.375, 0.875, 1.375, 1.500, 1.250, 1.125, 0.875])),
    "680-699":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.625, 1.125, 1.750, 1.875, 1.500, 1.375, 1.125])),
    "660-679":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.750, 1.375, 1.875, 2.125, 1.750, 1.625, 1.250])),
    "640-659":  dict(zip(_LTV_COLS, [0.000, 0.000, 1.125, 1.500, 2.250, 2.500, 2.000, 1.875, 1.500])),
    "<=639":    dict(zip(_LTV_COLS, [0.000, 0.125, 1.500, 2.125, 2.750, 2.875, 2.625, 2.250, 1.750])),
}

LLPA_LIMITED_CASH_OUT: dict[str, dict[str, float]] = {
    ">=780":    dict(zip(_LTV_COLS, [0.000, 0.000, 0.000, 0.125, 0.500, 0.625, 0.500, 0.375, 0.375])),
    "760-779":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.125, 0.375, 0.875, 1.000, 0.750, 0.625, 0.625])),
    "740-759":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.250, 0.750, 1.125, 1.375, 1.125, 1.000, 1.000])),
    "720-739":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.500, 1.000, 1.625, 1.750, 1.500, 1.250, 1.250])),
    "700-719":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.625, 1.250, 1.875, 2.125, 1.750, 1.625, 1.625])),
    "680-699":  dict(zip(_LTV_COLS, [0.000, 0.000, 0.875, 1.625, 2.250, 2.500, 2.125, 1.750, 1.750])),
    "660-679":  dict(zip(_LTV_COLS, [0.000, 0.125, 1.125, 1.875, 2.500, 3.000, 2.375, 2.125, 2.125])),
    "640-659":  dict(zip(_LTV_COLS, [0.000, 0.250, 1.375, 2.125, 2.875, 3.375, 2.875, 2.500, 2.500])),
    "<=639":    dict(zip(_LTV_COLS, [0.000, 0.375, 1.750, 2.500, 3.500, 3.875, 3.625, 2.500, 2.500])),
}

# Cash-out caps at 80% LTV, so the grid stops at "75-80" — no 80-85/85-90/
# 90-95/>95 columns exist for this product.
_CASHOUT_LTV_COLS = ["<30", "30-60", "60-70", "70-75", "75-80"]

LLPA_CASH_OUT: dict[str, dict[str, float]] = {
    ">=780":    dict(zip(_CASHOUT_LTV_COLS, [0.375, 0.375, 0.625, 0.875, 1.375])),
    "760-779":  dict(zip(_CASHOUT_LTV_COLS, [0.375, 0.375, 0.875, 1.250, 1.875])),
    "740-759":  dict(zip(_CASHOUT_LTV_COLS, [0.375, 0.375, 1.000, 1.625, 2.375])),
    "720-739":  dict(zip(_CASHOUT_LTV_COLS, [0.375, 0.500, 1.375, 2.000, 2.750])),
    "700-719":  dict(zip(_CASHOUT_LTV_COLS, [0.375, 0.500, 1.625, 2.625, 3.250])),
    "680-699":  dict(zip(_CASHOUT_LTV_COLS, [0.375, 0.625, 2.000, 2.875, 3.750])),
    "660-679":  dict(zip(_CASHOUT_LTV_COLS, [0.375, 0.875, 2.750, 4.000, 4.750])),
    "640-659":  dict(zip(_CASHOUT_LTV_COLS, [0.375, 1.375, 3.125, 4.625, 5.125])),
    "<=639":    dict(zip(_CASHOUT_LTV_COLS, [0.375, 1.375, 3.375, 4.875, 5.125])),
}

LLPA_GRIDS = {
    "purchase": LLPA_PURCHASE,
    "limited_cash_out": LLPA_LIMITED_CASH_OUT,
    "cash_out": LLPA_CASH_OUT,
}

# Purchase-money attribute adders (SEC). These are CUMULATIVE with the base
# FICO x LTV cell and with each other — no worst-of logic (section 2).
#
# The reference file publishes attribute adders ONLY for the purchase grid.
# No attribute-adder table exists for limited-cash-out or cash-out refis
# (cash-out's own high-balance-FRM note gives only a bare "1.250->1.750"
# range, not a per-band table, so it is not usable as data). Per explicit
# instruction, attribute adders in this engine therefore apply to PURCHASE
# transactions only; pricing.py flags (rather than invents) an adder for
# LCOR/cash-out.
LLPA_PURCHASE_ADDERS: dict[str, dict[str, float]] = {
    "arm":                  dict(zip(_LTV_COLS, [0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.250, 0.250])),
    "condo":                dict(zip(_LTV_COLS, [0.000, 0.000, 0.125, 0.125, 0.750, 0.750, 0.750, 0.750, 0.750])),
    "investment_property":  dict(zip(_LTV_COLS, [1.125, 1.125, 1.625, 2.125, 3.375, 4.125, 4.125, 4.125, 4.125])),
    "second_home":          dict(zip(_LTV_COLS, [1.125, 1.125, 1.625, 2.125, 3.375, 4.125, 4.125, 4.125, 4.125])),
    "two_to_four_unit":     dict(zip(_LTV_COLS, [0.000, 0.000, 0.375, 0.375, 0.625, 0.625, 0.625, 0.625, 0.625])),
    "high_balance_frm":     dict(zip(_LTV_COLS, [0.500, 0.500, 0.750, 0.750, 1.000, 1.000, 1.000, 1.000, 1.000])),
    "high_balance_arm":     dict(zip(_LTV_COLS, [1.250, 1.250, 1.500, 1.500, 2.500, 2.500, 2.500, 2.750, 2.750])),
    # Keyed off CLTV, not LTV — separate lookup axis (section 2).
    "subordinate_financing": dict(zip(_LTV_COLS, [0.625, 0.625, 0.625, 0.875, 1.125, 1.125, 1.125, 1.875, 1.875])),
}
# Manufactured home is flat across every LTV band (SEC).
LLPA_MANUFACTURED_HOME_FLAT = 0.500

# ---------------------------------------------------------------------------
# 1 / 6. Base price rate stack — price space, not rate space (section 1).
#
# The reference file gives exactly four anchor points, taken verbatim from
# its worked example (section 7): 6.375/6.500/6.625/6.750% -> 99.875/
# 100.750/101.250/101.750. Those four numbers are hardcoded exactly below.
#
# Beyond that range the file gives no table, only a slope rule (section 6):
# "slope near par is roughly 0.500 price per 0.125% rate step, flattening
# toward the edges [~0.350 at 5.500%/8.000%]". The rest of the 5.500-8.000%
# stack is CONSTRUCTED from that rule: starting from the outermost anchor on
# each side, the per-step price delta is linearly interpolated from 0.500
# (nearest par) down to 0.350 (at the 5.500%/8.000% edges). This construction
# is explicitly illustrative/calibrated (ILL) — flagged, not sourced, per the
# user's direction. Nothing outside the four anchor rates should be read as
# a real rate-sheet number.
# ---------------------------------------------------------------------------
RATE_STACK_ANCHORS: dict[float, float] = {
    6.375: 99.875,
    6.500: 100.750,
    6.625: 101.250,
    6.750: 101.750,
}
RATE_STACK_LOW = 5.500
RATE_STACK_HIGH = 8.000
RATE_STEP = 0.125
NEAR_PAR_SLOPE = 0.500
EDGE_SLOPE = 0.350


def _build_base_price_table() -> dict[float, float]:
    anchors = sorted(RATE_STACK_ANCHORS)
    lo_anchor, hi_anchor = anchors[0], anchors[-1]
    table: dict[float, float] = dict(RATE_STACK_ANCHORS)

    # Walk upward from the top anchor to RATE_STACK_HIGH.
    steps_up = round((RATE_STACK_HIGH - hi_anchor) / RATE_STEP)
    price = RATE_STACK_ANCHORS[hi_anchor]
    for i in range(1, steps_up + 1):
        slope = NEAR_PAR_SLOPE + (EDGE_SLOPE - NEAR_PAR_SLOPE) * (i - 1) / max(steps_up - 1, 1)
        price = round(price + slope, 3)
        rate = round(hi_anchor + i * RATE_STEP, 3)
        table[rate] = price

    # Walk downward from the bottom anchor to RATE_STACK_LOW.
    steps_down = round((lo_anchor - RATE_STACK_LOW) / RATE_STEP)
    price = RATE_STACK_ANCHORS[lo_anchor]
    for i in range(1, steps_down + 1):
        slope = NEAR_PAR_SLOPE + (EDGE_SLOPE - NEAR_PAR_SLOPE) * (i - 1) / max(steps_down - 1, 1)
        price = round(price - slope, 3)
        rate = round(lo_anchor - i * RATE_STEP, 3)
        table[rate] = price

    return dict(sorted(table.items()))


BASE_PRICE_TABLE: dict[float, float] = _build_base_price_table()

# Lock-period adjustment. The reference file's worked example uses a 30-day
# lock with NO separate lock-adjustment line item (base price -> LLPA ->
# final price, nothing else) — so 30 days is treated as the baseline (0.000
# points). No other lock-day pricing is published anywhere in the reference
# file, so other lock periods are intentionally NOT modeled rather than
# guessed; requesting one raises rather than silently pricing it at 0.
LOCK_DAY_ADJUSTMENTS: dict[int, float] = {30: 0.000}

# ---------------------------------------------------------------------------
# 3. Eligibility caps
# ---------------------------------------------------------------------------

# Conforming loan limits, 2026, by unit count (OK).
# NOTE: high-balance/loan-limit determination is properly COUNTY-LEVEL (FIPS)
# per the reference file itself ("a realistic engine needs a FIPS->limit
# table, not one national threshold"). No FIPS table was provided, so this
# engine uses the NATIONAL baseline/ceiling only — a known, declared
# simplification, not an invented number. See README "Known limitations".
CONFORMING_LOAN_LIMITS: dict[int, dict[str, float]] = {
    1: {"baseline": 832_750, "ceiling": 1_249_125},
    2: {"baseline": 1_066_250, "ceiling": 1_599_375},
    3: {"baseline": 1_288_800, "ceiling": 1_933_200},
    4: {"baseline": 1_601_750, "ceiling": 2_402_625},
}

# FHA loan limits, 2026 (SEC). Only 1-2 unit figures are published in the
# reference file; 3-4 unit FHA limits are NOT modeled (flagged, not guessed).
FHA_LOAN_LIMITS: dict[int, dict[str, float]] = {
    1: {"floor": 541_287, "ceiling": 1_249_125},
    2: {"floor": 693_050, "ceiling": 1_599_375},
}

# Conventional (DU) max LTV by occupancy/units/transaction type (SEC).
# Keys: (occupancy, units_bucket, transaction_type) -> max LTV percent.
# units_bucket in {1, 2, "3-4"}. transaction_type in {"purchase",
# "limited_cash_out", "cash_out"}. Investment/1-unit is the one row that
# splits purchase vs LCOR (85% vs 75%) — everything else shares one number
# across purchase & LCOR, per the source table's own column layout.
CONVENTIONAL_MAX_LTV: dict[tuple[str, int | str, str], float] = {
    ("primary", 1, "purchase"): 97.0,
    ("primary", 1, "limited_cash_out"): 97.0,
    ("primary", 1, "cash_out"): 80.0,
    ("primary", 2, "purchase"): 95.0,
    ("primary", 2, "limited_cash_out"): 95.0,
    ("primary", 2, "cash_out"): 75.0,
    ("primary", "3-4", "purchase"): 95.0,
    ("primary", "3-4", "limited_cash_out"): 95.0,
    ("primary", "3-4", "cash_out"): 75.0,
    ("second_home", 1, "purchase"): 90.0,
    ("second_home", 1, "limited_cash_out"): 90.0,
    ("second_home", 1, "cash_out"): 75.0,
    ("investment", 1, "purchase"): 85.0,
    ("investment", 1, "limited_cash_out"): 75.0,
    ("investment", 1, "cash_out"): 75.0,
    ("investment", 2, "purchase"): 75.0,
    ("investment", 2, "limited_cash_out"): 75.0,
    ("investment", 2, "cash_out"): 70.0,
    ("investment", "3-4", "purchase"): 75.0,
    ("investment", "3-4", "limited_cash_out"): 75.0,
    ("investment", "3-4", "cash_out"): 70.0,
}
# Primary 1-unit ARM has its own, lower purchase/LCOR max (95% vs 97% FRM);
# everything else in the source table does not split by ARM/FRM.
CONVENTIONAL_MAX_LTV_PRIMARY_1UNIT_ARM_PURCHASE_LCOR = 95.0

# FHA max LTV (SEC).
FHA_MAX_LTV_PURCHASE_FICO_GE_580 = 96.5
FHA_MAX_LTV_PURCHASE_FICO_500_579 = 90.0
FHA_MIN_FICO_PURCHASE = 500  # below 500, FHA is not eligible at all
FHA_MAX_LTV_RATE_TERM_REFI = 97.75
FHA_MAX_LTV_CASH_OUT = 80.0  # lowered from 85% in 2019 (OK)

# VA / USDA: 100% LTV, no agency-published LTV cap (section 3).
VA_MAX_LTV = 100.0
USDA_MAX_LTV = 100.0
USDA_INCOME_CAP_PCT_OF_AMI = 115.0

# Lender overlays — deliberately a SEPARATE layer from agency rules above,
# because that is how a real lender is structured (section 3 / section 8.6).
# DU 12.0 (11/16/2025) eliminated Fannie's own minimum credit score for
# Standard/HomeReady/Manufactured/Single-Close Construction-to-Perm, but
# "in practice nearly every lender keeps a 620 overlay" — modeled here, not
# in the agency tables.
LENDER_OVERLAYS: dict[str, object] = {
    "min_fico_conventional": 620,
    "min_fico_fha": 580,
    "min_fico_va": 580,
    "min_fico_usda": 620,
}

# ---------------------------------------------------------------------------
# 4. DTI — ELIGIBILITY ONLY, NEVER PRICED.
#
# FHFA deleted every DTI-based LLPA effective 05/01/2023 (a proposed 0.375%
# adder for DTI >= 40% was rescinded entirely before ever taking effect).
# DTI must never appear as a price adjustment anywhere in pricing.py — it is
# strictly a pass/fail/refer gate, evaluated in eligibility.py. See section
# 4 / section 2 "the May 2023 restructure" of the reference file.
# ---------------------------------------------------------------------------
DTI_CONVENTIONAL_DU_MAX = 50.0        # OK — Selling Guide B3-6-02
DTI_CONVENTIONAL_MANUAL_BASE = 36.0   # OK
DTI_CONVENTIONAL_MANUAL_MAX = 45.0    # OK, with score/reserve requirements
DTI_FREDDIE_LPA_MAX = 50.0            # SEC
DTI_FREDDIE_MANUAL_MAX = 45.0         # SEC

# FHA manual-underwrite tiers, front/back, by compensating factor count (SEC).
FHA_MANUAL_DTI_TIERS: dict[int, tuple[float, float]] = {
    0: (31.0, 43.0),
    1: (37.0, 47.0),
    2: (40.0, 50.0),  # "2+"
}
# FHA TOTAL AUS (automated) has no published hard cap; ~56.99% back-end is
# the commonly cited practical ceiling (ILL). Used only as a refer/fail
# split above the manual tiers, never as a price input.
FHA_TOTAL_AUS_PRACTICAL_MAX = 56.99

VA_DTI_SCRUTINY_THRESHOLD = 41.0  # SEC — not a hard cap, triggers residual-income scrutiny

USDA_DTI_FRONT_MAX = 29.0  # SEC, waivable with GUS Accept
USDA_DTI_BACK_MAX = 41.0   # SEC, waivable with GUS Accept

# ---------------------------------------------------------------------------
# VA residual income (section 4). Only the ">= $80,000 loan amount" bracket
# is published in the reference file; no <$80,000 table exists here, so
# loans under $80,000 are flagged unsupported rather than guessed.
# ---------------------------------------------------------------------------
VA_RESIDUAL_INCOME_TABLE: dict[int, dict[str, float]] = {
    1: {"northeast": 450, "midwest": 441, "south": 441, "west": 491},
    2: {"northeast": 755, "midwest": 738, "south": 738, "west": 823},
    3: {"northeast": 909, "midwest": 889, "south": 889, "west": 990},
    4: {"northeast": 1025, "midwest": 1003, "south": 1003, "west": 1117},
    5: {"northeast": 1062, "midwest": 1039, "south": 1039, "west": 1158},
}
VA_RESIDUAL_INCOME_MIN_LOAN_AMOUNT = 80_000
VA_RESIDUAL_INCOME_PER_ADDITIONAL_MEMBER = 80  # beyond family of 5, up to 7
VA_RESIDUAL_INCOME_MAX_FAMILY_SIZE_TABLE = 7
VA_RESIDUAL_INCOME_DTI_PENALTY_THRESHOLD = 41.0
VA_RESIDUAL_INCOME_PENALTY_MULTIPLIER = 1.20  # "the 20% rule"

# ---------------------------------------------------------------------------
# 5. Mortgage insurance
# ---------------------------------------------------------------------------

# Conventional PMI required coverage % by LTV band (informational/
# traceability only — monthly premium uses the factor table below).
PMI_REQUIRED_COVERAGE: dict[str, float] = {
    "95.01-97": 35.0,
    "90.01-95": 30.0,
    "85.01-90": 25.0,
    "80.01-85": 12.0,
}

# BPMI monthly annual premium factors, 30-yr fixed, standard coverage.
# ILL/SEC — "structurally correct and realistic in magnitude, but sourced
# from an archived MGIC card... calibration, not truth" per the reference
# file. FICO columns here use MI-industry bands (760+, floor 620-639), which
# differ from the LLPA FICO bands (780+, floor <=639) — that split is in the
# source table, not an error.
_PMI_FICO_COLS = ["760+", "740-759", "720-739", "700-719", "680-699", "660-679", "640-659", "620-639"]

PMI_MONTHLY_FACTORS: dict[str, dict[str, float]] = {
    "95.01-97": dict(zip(_PMI_FICO_COLS, [0.38, 0.53, 0.66, 0.78, 0.96, 1.28, 1.33, 1.42])),
    "90.01-95": dict(zip(_PMI_FICO_COLS, [0.34, 0.48, 0.59, 0.68, 0.87, 1.11, 1.19, 1.25])),
    "85.01-90": dict(zip(_PMI_FICO_COLS, [0.28, 0.38, 0.46, 0.55, 0.65, 0.90, 0.91, 0.94])),
    "80.01-85": dict(zip(_PMI_FICO_COLS, [0.19, 0.20, 0.23, 0.25, 0.28, 0.38, 0.40, 0.44])),
}
PMI_LTV_BANDS: list[tuple[str, float, float]] = [
    ("80.01-85", 80.0, 85.0),
    ("85.01-90", 85.0, 90.0),
    ("90.01-95", 90.0, 95.0),
    ("95.01-97", 95.0, 97.0),
]
PMI_AUTO_TERMINATE_LTV = 78.0  # by original amortization schedule (HPA)
PMI_CANCELLABLE_ON_REQUEST_LTV = 80.0


def pmi_fico_col(fico: int) -> str:
    if fico >= 760:
        return "760+"
    bounds = [(740, 759), (720, 739), (700, 719), (680, 699), (660, 679), (640, 659), (620, 639)]
    for lo, hi in bounds:
        if lo <= fico <= hi:
            return f"{lo}-{hi}"
    raise ValueError(f"FICO {fico} below PMI table floor of 620")


def pmi_ltv_band(ltv: float) -> str | None:
    ltv = round(ltv, 3)
    if ltv <= 80.0:
        return None  # no PMI required
    for label, lo, hi in PMI_LTV_BANDS:
        if ltv <= hi:
            return label
    return None  # above 97% is not a conventional-eligible LTV at all


# FHA MIP (SEC). UFMIP is added AFTER the base loan amount is computed, so
# the final loan amount exceeds the LTV-derived figure — see costs.py.
FHA_UFMIP_RATE = 0.0175

# The $726,200 threshold is the 2023 conforming limit frozen into ML 2023-05
# as a STATIC figure; the reference file flags disagreement on whether it
# floats with the current conforming limit. Used here exactly as published
# (static), per instruction to use the file's exact values. Re-verify against
# Handbook 4000.1 before relying on this for loans between $726,200 and the
# current $832,750 baseline.
FHA_ANNUAL_MIP_LOAN_THRESHOLD = 726_200

FHA_ANNUAL_MIP_TABLE: dict[str, dict[str, tuple[float, str]]] = {
    # loan_bucket -> ltv_bucket -> (annual rate, duration)
    "<=threshold": {
        "<=90": (0.0050, "11 years"),
        "90.01-95": (0.0050, "life of loan"),
        ">95": (0.0055, "life of loan"),
    },
    ">threshold": {
        "<=90": (0.0070, "11 years"),
        "90.01-95": (0.0070, "life of loan"),
        ">95": (0.0075, "life of loan"),
    },
}

# VA funding fee (SEC). Down-payment tiers keyed by percent down.
VA_FUNDING_FEE_TABLE: dict[str, dict[str, float]] = {
    "<5": {"first_use": 0.0230, "subsequent_use": 0.0360},
    "5-9.99": {"first_use": 0.0165, "subsequent_use": 0.0165},
    ">=10": {"first_use": 0.0140, "subsequent_use": 0.0140},
}
VA_FUNDING_FEE_CASH_OUT = {"first_use": 0.0230, "subsequent_use": 0.0360}
VA_FUNDING_FEE_IRRRL = 0.0050  # flat, regardless of use


def va_funding_fee_down_payment_tier(down_payment_pct: float) -> str:
    if down_payment_pct < 5.0:
        return "<5"
    if down_payment_pct < 10.0:
        return "5-9.99"
    return ">=10"


# USDA (SEC).
USDA_UPFRONT_GUARANTEE_FEE_RATE = 0.0100  # financeable, added after base loan amount like FHA UFMIP
USDA_ANNUAL_FEE_RATE = 0.0035             # on average scheduled unpaid balance; approximated on original balance
USDA_DTI_RATIOS = (29.0, 41.0)

# ---------------------------------------------------------------------------
# 6. Calibration anchors (context only, not consumed directly by the engine)
# ---------------------------------------------------------------------------
FREDDIE_PMMS_30YR_2026_08_27 = 6.66  # OK
FREDDIE_PMMS_15YR_2026_08_27 = 5.98  # OK
