"""
P&I, mortgage insurance / statutory fees, and breakeven math.

Nothing here guesses either: every rate comes from config.py, traceable back
to reference/pricing-and-guidelines.md.
"""

from __future__ import annotations

from . import config
from .models import Program, QuoteRequest, TransactionType


def monthly_pi(principal: float, annual_rate_pct: float, term_months: int) -> float:
    """Standard fixed-rate amortization payment."""
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return round(principal / term_months, 2)
    factor = (1 + r) ** term_months
    return round(principal * r * factor / (factor - 1), 2)


def monthly_pmi(loan_amount: float, fico: int, ltv: float) -> float:
    """Conventional BPMI. 0.0 when LTV <= 80 (no PMI required) — section 5."""
    band = config.pmi_ltv_band(ltv)
    if band is None:
        return 0.0
    col = config.pmi_fico_col(fico)
    factor = config.PMI_MONTHLY_FACTORS[band][col]
    return round(factor / 100 * loan_amount / 12, 2)


# ---------------------------------------------------------------------------
# FHA
# ---------------------------------------------------------------------------

def fha_ufmip(base_loan_amount: float) -> float:
    return round(base_loan_amount * config.FHA_UFMIP_RATE, 2)


def fha_final_loan_amount(base_loan_amount: float) -> float:
    """UFMIP is added AFTER the base loan amount is computed, so the final
    loan amount exceeds the LTV-derived figure — section 5 / requirement 7."""
    return round(base_loan_amount + fha_ufmip(base_loan_amount), 2)


def fha_annual_mip(base_loan_amount: float, ltv: float) -> tuple[float, float, str]:
    """Returns (monthly MIP dollars, annual rate, duration label).

    Monthly MIP is charged against the FINAL loan amount (base + financed
    UFMIP), matching how the insured balance actually sits on the note; the
    loan-amount bucket that selects the *rate* uses the base (LTV-derived)
    loan amount, per HUD's mortgage-amount definition.
    """
    bucket = "<=threshold" if base_loan_amount <= config.FHA_ANNUAL_MIP_LOAN_THRESHOLD else ">threshold"
    if ltv <= 90.0:
        ltv_bucket = "<=90"
    elif ltv <= 95.0:
        ltv_bucket = "90.01-95"
    else:
        ltv_bucket = ">95"
    rate, duration = config.FHA_ANNUAL_MIP_TABLE[bucket][ltv_bucket]
    final_loan = fha_final_loan_amount(base_loan_amount)
    monthly = round(rate * final_loan / 12, 2)
    return monthly, rate, duration


# ---------------------------------------------------------------------------
# VA
# ---------------------------------------------------------------------------

def va_funding_fee(base_loan_amount: float, request: QuoteRequest) -> tuple[float, float, str]:
    """Returns (fee dollars, rate, label). 0.0 dollars/rate when exempt."""
    if request.va_exempt:
        return 0.0, 0.0, "VA funding fee — exempt (Certificate of Eligibility)"

    if request.va_is_irrrl:
        rate = config.VA_FUNDING_FEE_IRRRL
        label = "VA funding fee — IRRRL (flat, regardless of use)"
    elif request.transaction_type == TransactionType.CASH_OUT:
        use = "first_use" if request.va_first_use else "subsequent_use"
        rate = config.VA_FUNDING_FEE_CASH_OUT[use]
        label = f"VA funding fee — cash-out refi, {'first' if request.va_first_use else 'subsequent'} use"
    else:
        tier = config.va_funding_fee_down_payment_tier(request.va_down_payment_pct)
        use = "first_use" if request.va_first_use else "subsequent_use"
        rate = config.VA_FUNDING_FEE_TABLE[tier][use]
        label = f"VA funding fee — {tier}% down, {'first' if request.va_first_use else 'subsequent'} use"

    return round(base_loan_amount * rate, 2), rate, label


def va_final_loan_amount(base_loan_amount: float, request: QuoteRequest) -> float:
    fee, _, _ = va_funding_fee(base_loan_amount, request)
    return round(base_loan_amount + fee, 2)


# ---------------------------------------------------------------------------
# USDA
# ---------------------------------------------------------------------------

def usda_guarantee_fee(base_loan_amount: float) -> float:
    return round(base_loan_amount * config.USDA_UPFRONT_GUARANTEE_FEE_RATE, 2)


def usda_final_loan_amount(base_loan_amount: float) -> float:
    return round(base_loan_amount + usda_guarantee_fee(base_loan_amount), 2)


def usda_annual_fee_monthly(base_loan_amount: float) -> float:
    """0.35% annual fee on the average scheduled unpaid balance. Approximated
    here on the original balance — a true amortization-weighted average
    requires the servicing schedule, which is out of scope; flagged, not
    invented as a separate published number."""
    return round(config.USDA_ANNUAL_FEE_RATE * base_loan_amount / 12, 2)


# ---------------------------------------------------------------------------
# Breakeven
# ---------------------------------------------------------------------------

def breakeven_months(lower_cost_dollars: float, lower_cost_payment: float,
                      higher_cost_dollars: float, higher_cost_payment: float) -> float | None:
    """Months to recoup paying more upfront (higher_cost_dollars) in exchange
    for a lower monthly payment (higher_cost_payment < lower_cost_payment).
    None when the higher-cost option doesn't actually lower the payment."""
    extra_upfront = higher_cost_dollars - lower_cost_dollars
    monthly_savings = lower_cost_payment - higher_cost_payment
    if monthly_savings <= 0:
        return None
    return round(extra_upfront / monthly_savings, 1)
