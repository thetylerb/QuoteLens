"""Orchestrates request -> eligibility -> pricing -> costs."""

from __future__ import annotations

from . import costs, eligibility, pricing
from .models import CostBreakdown, Program, QuoteRequest, QuoteResult


def generate_quote(request: QuoteRequest) -> QuoteResult:
    elig = eligibility.evaluate(request)

    if request.program == Program.CONVENTIONAL:
        stack, adjustments = pricing.price_conventional(request)
        cost_breakdown = CostBreakdown(final_loan_amount=request.loan_amount)
    elif request.program == Program.FHA:
        stack, adjustments = pricing.price_government(request)
        ufmip = costs.fha_ufmip(request.loan_amount)
        cost_breakdown = CostBreakdown(
            upfront_fee_name="FHA UFMIP (1.75%, financed)",
            upfront_fee_amount=ufmip,
            final_loan_amount=costs.fha_final_loan_amount(request.loan_amount),
        )
    elif request.program == Program.VA:
        stack, adjustments = pricing.price_government(request)
        fee, _rate, label = costs.va_funding_fee(request.loan_amount, request)
        cost_breakdown = CostBreakdown(
            upfront_fee_name=f"{label} (financed)" if fee else label,
            upfront_fee_amount=fee,
            final_loan_amount=costs.va_final_loan_amount(request.loan_amount, request),
        )
    elif request.program == Program.USDA:
        stack, adjustments = pricing.price_government(request)
        fee = costs.usda_guarantee_fee(request.loan_amount)
        cost_breakdown = CostBreakdown(
            upfront_fee_name="USDA upfront guarantee fee (1.00%, financed)",
            upfront_fee_amount=fee,
            final_loan_amount=costs.usda_final_loan_amount(request.loan_amount),
        )
    else:
        raise ValueError(f"Unknown program {request.program}")

    par_row = next(r for r in stack if r.is_par_row)
    idx = stack.index(par_row)
    if idx + 1 < len(stack):
        # One rate step higher: lower upfront cost (more credit), higher
        # payment. Choosing the par row instead means paying more upfront
        # to buy the payment down — the classic breakeven trade (section 7).
        neighbor = stack[idx + 1]
        cost_breakdown.breakeven_months = costs.breakeven_months(
            lower_cost_dollars=neighbor.points_or_credit_dollars,
            lower_cost_payment=neighbor.total_monthly_payment,
            higher_cost_dollars=par_row.points_or_credit_dollars,
            higher_cost_payment=par_row.total_monthly_payment,
        )

    return QuoteResult(
        request=request,
        eligibility=elig,
        rate_stack=stack,
        adjustments=adjustments,
        costs=cost_breakdown,
    )
