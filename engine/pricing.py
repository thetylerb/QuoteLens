"""
The rate stack and the LLPA adjuster cascade.

PRICE SPACE, NOT RATE SPACE (section 1):

    final_price(rate) = base_price(rate) + lock_adj - sum(LLPAs) - sum(adjusters)
    borrower_cost = (100 - final_price) / 100 * loan_amount
        positive -> borrower pays discount points
        negative -> lender credit

LLPAs are CUMULATIVE (section 2) — every applicable cell/adder is summed,
there is no worst-of logic.

DTI IS NEVER PRICED HERE. FHFA deleted every DTI-based LLPA effective
05/01/2023 (a proposed 0.375% adder for DTI >= 40% was rescinded before it
ever took effect). DTI only appears in eligibility.py, as pass/fail/refer.

Conventional and government (FHA/VA/USDA) are separate pipelines on purpose:
conventional is a base price stack plus the LLPA cascade; government is a
flatter stack with statutory fee tables and NO price adjusters at all. They
are implemented as two separate functions below rather than one path with
branches, because one code path for both produces wrong answers.
"""

from __future__ import annotations

from . import config, costs
from .eligibility import is_high_balance
from .models import (
    Adjustment,
    Occupancy,
    Program,
    PropertyType,
    QuoteRequest,
    RateOption,
    TransactionType,
)

_PURCHASE_ONLY_NOTE = (
    "Attribute adders are published in the reference file only for the "
    "purchase-money grid; no attribute-adder table exists for this "
    "transaction type, so it is intentionally left unpriced rather than "
    "guessed."
)


def _adder_adjustment(label: str, points: float, ltv_band_label: str) -> Adjustment:
    return Adjustment(
        name=label,
        category="llpa_adder",
        amount_in_points=points,
        source=(f"Fannie LLPA Matrix, eff. 01/28/2026, purchase attribute adders, "
                f"{label} x LTV {ltv_band_label} ({config.REFERENCE_DOC} sec. 2)"),
    )


def _triggered_purchase_attributes(request: QuoteRequest) -> list[str]:
    labels = []
    if request.is_arm:
        labels.append("ARM")
    if request.property_type == PropertyType.CONDO:
        labels.append("Condo")
    if request.occupancy == Occupancy.INVESTMENT:
        labels.append("Investment property")
    if request.occupancy == Occupancy.SECOND_HOME:
        labels.append("Second home")
    if request.property_type == PropertyType.MANUFACTURED:
        labels.append("Manufactured home")
    if request.units >= 2:
        labels.append("2-4 unit")
    if is_high_balance(request):
        labels.append("High-balance ARM" if request.is_arm else "High-balance FRM")
    if request.has_subordinate_financing:
        labels.append("Subordinate financing (CLTV)")
    return labels


def llpa_adjustments(request: QuoteRequest) -> list[Adjustment]:
    """The full ordered cumulative LLPA cascade for a conventional request."""
    ltv_band_label = config.ltv_band(request.ltv)
    fico_band_label = config.fico_band(request.fico)
    grid = config.LLPA_GRIDS[request.transaction_type.value]

    if fico_band_label not in grid or ltv_band_label not in grid[fico_band_label]:
        raise ValueError(
            f"No LLPA cell for {request.transaction_type.value} grid at "
            f"FICO {fico_band_label} x LTV {ltv_band_label} "
            f"(cash-out only publishes bands up to 75-80)"
        )

    base_points = grid[fico_band_label][ltv_band_label]
    adjustments = [Adjustment(
        name=f"Base LLPA — FICO {fico_band_label} x LTV {ltv_band_label}",
        category="llpa_base",
        amount_in_points=base_points,
        source=(f"Fannie LLPA Matrix, eff. 01/28/2026, {request.transaction_type.value} grid, "
                f"FICO {fico_band_label} x LTV {ltv_band_label} ({config.REFERENCE_DOC} sec. 2)"),
    )]

    if request.transaction_type != TransactionType.PURCHASE:
        for label in _triggered_purchase_attributes(request):
            adjustments.append(Adjustment(
                name=f"{label} (unpriced)",
                category="llpa_adder",
                amount_in_points=0.0,
                source=_PURCHASE_ONLY_NOTE,
            ))
        return adjustments

    adders = config.LLPA_PURCHASE_ADDERS
    if request.is_arm:
        adjustments.append(_adder_adjustment("ARM", adders["arm"][ltv_band_label], ltv_band_label))
    if request.property_type == PropertyType.CONDO:
        adjustments.append(_adder_adjustment("Condo", adders["condo"][ltv_band_label], ltv_band_label))
    if request.occupancy == Occupancy.INVESTMENT:
        adjustments.append(_adder_adjustment("Investment property", adders["investment_property"][ltv_band_label], ltv_band_label))
    if request.occupancy == Occupancy.SECOND_HOME:
        adjustments.append(_adder_adjustment("Second home", adders["second_home"][ltv_band_label], ltv_band_label))
    if request.property_type == PropertyType.MANUFACTURED:
        adjustments.append(Adjustment(
            name="Manufactured home",
            category="llpa_adder",
            amount_in_points=config.LLPA_MANUFACTURED_HOME_FLAT,
            source=(f"Fannie LLPA Matrix, eff. 01/28/2026, purchase attribute adders, "
                    f"manufactured home flat adder ({config.REFERENCE_DOC} sec. 2)"),
        ))
    if request.units >= 2:
        adjustments.append(_adder_adjustment("2-4 unit", adders["two_to_four_unit"][ltv_band_label], ltv_band_label))
    if is_high_balance(request):
        if request.is_arm:
            adjustments.append(_adder_adjustment("High-balance ARM", adders["high_balance_arm"][ltv_band_label], ltv_band_label))
        else:
            adjustments.append(_adder_adjustment("High-balance FRM", adders["high_balance_frm"][ltv_band_label], ltv_band_label))
    if request.has_subordinate_financing:
        cltv_band_label = config.ltv_band(request.effective_cltv)
        adjustments.append(Adjustment(
            name="Subordinate financing (CLTV)",
            category="llpa_adder",
            amount_in_points=adders["subordinate_financing"][cltv_band_label],
            source=(f"Fannie LLPA Matrix, eff. 01/28/2026, purchase attribute adders, "
                    f"subordinate financing by CLTV {cltv_band_label} ({config.REFERENCE_DOC} sec. 2)"),
        ))

    return adjustments


def _lock_adjustment(request: QuoteRequest) -> Adjustment:
    if request.lock_days not in config.LOCK_DAY_ADJUSTMENTS:
        raise ValueError(
            f"No lock-day pricing published for a {request.lock_days}-day lock; "
            f"only {sorted(config.LOCK_DAY_ADJUSTMENTS)} are supported by the reference data"
        )
    points = config.LOCK_DAY_ADJUSTMENTS[request.lock_days]
    return Adjustment(
        name=f"{request.lock_days}-day lock",
        category="lock_adjustment",
        amount_in_points=points,
        source=(f"Reference worked example uses a 30-day lock with no separate lock line "
                f"item; treated as baseline 0.000 ({config.REFERENCE_DOC} sec. 7)"),
    )


def borrower_cost_dollars(final_price: float, loan_amount: float) -> float:
    """borrower_cost = (100 - final_price) / 100 * loan_amount — section 1.
    Positive = borrower pays discount points. Negative = lender credit."""
    return round((100 - final_price) / 100 * loan_amount, 2)


def _build_stack(base_prices: dict[float, float], lock_points: float, total_deduction_points: float,
                  principal_for_pi: float, monthly_mi: float, term_months: int) -> list[RateOption]:
    rows = []
    for rate, base_price in base_prices.items():
        final_price = round(base_price + lock_points - total_deduction_points, 3)
        borrower_cost = borrower_cost_dollars(final_price, principal_for_pi)
        pi = costs.monthly_pi(principal_for_pi, rate, term_months)
        rows.append(RateOption(
            rate=rate,
            base_price=base_price,
            final_price=final_price,
            points_or_credit_dollars=borrower_cost,
            monthly_pi=pi,
            monthly_mi=monthly_mi,
            total_monthly_payment=round(pi + monthly_mi, 2),
        ))
    par_row = min(rows, key=lambda r: abs(r.final_price - 100.0))
    par_row.is_par_row = True
    return rows


def price_conventional(request: QuoteRequest) -> tuple[list[RateOption], list[Adjustment]]:
    adjustments = llpa_adjustments(request)
    lock = _lock_adjustment(request)
    adjustments_with_lock = adjustments + [lock]

    total_llpa_points = sum(a.amount_in_points for a in adjustments)
    monthly_mi = costs.monthly_pmi(request.loan_amount, request.fico, request.ltv)

    stack = _build_stack(
        base_prices=config.BASE_PRICE_TABLE,
        lock_points=lock.amount_in_points,
        total_deduction_points=total_llpa_points,
        principal_for_pi=request.loan_amount,
        monthly_mi=monthly_mi,
        term_months=request.term_months,
    )
    return stack, adjustments_with_lock


def price_government(request: QuoteRequest) -> tuple[list[RateOption], list[Adjustment]]:
    """FHA/VA/USDA: flatter stack, statutory fee tables, NO price adjusters
    (section 3 / section 8.4). The base price curve is the same secondary-
    market rate sheet as conventional; what's absent is the LLPA cascade."""
    lock = _lock_adjustment(request)

    if request.program == Program.FHA:
        principal_for_pi = costs.fha_final_loan_amount(request.loan_amount)
        monthly_mi, _, _ = costs.fha_annual_mip(request.loan_amount, request.ltv)
    elif request.program == Program.VA:
        principal_for_pi = costs.va_final_loan_amount(request.loan_amount, request)
        monthly_mi = 0.0  # no monthly MI at any LTV for VA
    elif request.program == Program.USDA:
        principal_for_pi = costs.usda_final_loan_amount(request.loan_amount)
        monthly_mi = costs.usda_annual_fee_monthly(request.loan_amount)
    else:
        raise ValueError(f"{request.program} is not a government pipeline program")

    stack = _build_stack(
        base_prices=config.BASE_PRICE_TABLE,
        lock_points=lock.amount_in_points,
        total_deduction_points=0.0,
        principal_for_pi=principal_for_pi,
        monthly_mi=monthly_mi,
        term_months=request.term_months,
    )
    return stack, [lock]
