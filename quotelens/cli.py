#!/usr/bin/env python3
"""
QuoteLens CLI — reads a scenario JSON from a file path or stdin, prints
eligibility, the rate stack, and the adjustment waterfall for the par row.
With --text, extracts a scenario from free text first (see engine/extraction.py).

Usage:
    python cli.py examples/worked_example.json
    cat examples/worked_example.json | python cli.py
    python cli.py --text "I've got a client looking at a $525k place..."
    python cli.py --text "..." --force-live
"""

from __future__ import annotations

import json
import sys

if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from engine import config, extraction
from engine.extraction import InsufficientDataError
from engine.models import Occupancy, Program, PropertyType, QuoteRequest, TransactionType
from engine.quote import generate_quote


def _load_request(data: dict) -> QuoteRequest:
    data = dict(data)  # shallow copy; don't mutate caller's dict
    data["program"] = Program(data["program"])
    data["transaction_type"] = TransactionType(data["transaction_type"])
    data["occupancy"] = Occupancy(data["occupancy"])
    data["property_type"] = PropertyType(data["property_type"])
    return QuoteRequest(**data)


def _read_scenario() -> dict:
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            return json.load(f)
    return json.load(sys.stdin)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _print_header(result) -> None:
    req = result.request
    print("=" * 78)
    print("QuoteLens — Deterministic Pricing Quote")
    print("=" * 78)
    print(f"Program:      {req.program.value.upper()} | {req.transaction_type.value} | "
          f"{req.occupancy.value} | {req.property_type.value}")
    value_label = "purchase price" if req.purchase_price is not None else "appraised value"
    print(f"Loan:         {_money(req.loan_amount)} on {_money(req.value_basis)} {value_label} "
          f"(LTV {req.ltv:.2f}%)")
    print(f"Borrower:     FICO {req.fico} | {req.term_months}mo term | {req.lock_days}-day lock")
    print()


def _print_eligibility(result) -> None:
    elig = result.eligibility
    status = "ELIGIBLE" if elig.eligible else "NOT ELIGIBLE"
    print(f"ELIGIBILITY: {status}")
    for check in elig.checks:
        tag = "PASS" if check.passed else "FAIL"
        print(f"  [{tag}] {check.name:<20s} {check.detail}")
    print(f"  DTI status: {elig.dti_status.upper():<6s} {elig.dti_detail}")
    print()


def _display_window(stack, size: int = 11):
    par_idx = next(i for i, r in enumerate(stack) if r.is_par_row)
    half = size // 2
    lo = max(0, par_idx - half)
    hi = min(len(stack), lo + size)
    lo = max(0, hi - size)
    return stack[lo:hi]


def _print_rate_stack(result) -> None:
    print("RATE STACK")
    header = f"  {'Rate':>7s}  {'Price':>8s}  {'Pts/Credit':>14s}  {'Mo. P&I':>11s}  {'Mo. MI':>10s}  {'Total Pmt':>11s}"
    print(header)
    for row in _display_window(result.rate_stack):
        marker = "*" if row.is_par_row else " "
        if row.points_or_credit_dollars >= 0:
            pts = f"{_money(row.points_or_credit_dollars)} pts"
        else:
            pts = f"{_money(-row.points_or_credit_dollars)} cr"
        print(f" {marker}{row.rate:6.3f}%  {row.final_price:8.3f}  {pts:>14s}  "
              f"{_money(row.monthly_pi):>11s}  {_money(row.monthly_mi):>10s}  {_money(row.total_monthly_payment):>11s}")
    print("  * = par row (final price closest to 100.000)")
    print()


def _print_waterfall(result) -> None:
    """final_price = base_price + lock_adj - sum(LLPAs) — section 1. LLPA/adder
    lines subtract from the running price; the lock line (currently always
    0.000, see config.LOCK_DAY_ADJUSTMENTS) adds."""
    par_row = next(r for r in result.rate_stack if r.is_par_row)
    print(f"ADJUSTMENT WATERFALL — par row {par_row.rate:.3f}%")
    running = par_row.base_price
    print(f"  {'Base price':<55s} {' ':>10s} {running:>10.3f}")
    for adj in result.adjustments:
        if adj.category == "lock_adjustment":
            running = round(running + adj.amount_in_points, 3)
            sign = "+"
        else:
            running = round(running - adj.amount_in_points, 3)
            sign = "-"
        label = f"{adj.name} [{adj.category}]"
        print(f"  {label:<55s} {sign}{abs(adj.amount_in_points):>9.3f} {running:>10.3f}")
        print(f"      source: {adj.source}")
    settlement = "credit to borrower" if par_row.points_or_credit_dollars < 0 else "borrower pays"
    print(f"  {'Final price':<55s} {' ':>10s} {par_row.final_price:>10.3f}  -> {settlement} "
          f"{_money(abs(par_row.points_or_credit_dollars))}")
    print()


def _print_costs(result) -> None:
    cb = result.costs
    if cb.upfront_fee_name:
        print(f"UPFRONT FEE: {cb.upfront_fee_name} = {_money(cb.upfront_fee_amount)}")
        print(f"  Base loan amount:  {_money(result.request.loan_amount)}")
        print(f"  Final loan amount: {_money(cb.final_loan_amount)} (includes financed fee)")
        print()
    if cb.breakeven_months is not None:
        print(f"BREAKEVEN (par row vs. next-higher rate): {cb.breakeven_months:.1f} months")
        print()


def _print_extraction(extraction_result) -> None:
    src_label = {"live": "LIVE (Claude API)", "cache": "CACHE (replayed)", "fallback": "FALLBACK (regex parser, not the model)"}
    print("=" * 78)
    print("QuoteLens — Scenario Extraction")
    print("=" * 78)
    print(f"Source:     {src_label.get(extraction_result.source, extraction_result.source)}")
    print(f"Confidence: {extraction_result.confidence:.2f}")
    if extraction_result.provisional:
        print()
        print("!" * 78)
        print("! PROVISIONAL — confidence below 0.85. Confirm these fields with the")
        print("! borrower before treating this quote as real.")
        print("!" * 78)
    print()

    evidence = extraction_result.evidence
    stated = {k: v for k, v in extraction_result.fields.items() if v is not None and k in evidence}
    print("STATED (from the text)")
    if stated:
        for k, v in stated.items():
            print(f"  {k:<20s} = {v!r:<15s}  <- \"{evidence[k]}\"")
    else:
        print("  (nothing the parser could anchor to explicit text)")
    print()

    print("ASSUMED (filled in, not stated)")
    if extraction_result.assumptions:
        for a in extraction_result.assumptions:
            print(f"  {a.field:<20s} = {a.assumed_value!r:<15s}  reason: {a.reason}")
    else:
        print("  (none)")
    print()

    if extraction_result.notes:
        print(f"NOTES: {extraction_result.notes}")
        print()


def _run_from_text(text: str, *, force_live: bool) -> None:
    extraction_result = extraction.extract(text, force_live=force_live)
    _print_extraction(extraction_result)

    try:
        request = extraction.to_quote_request(extraction_result)
    except InsufficientDataError as exc:
        print(f"COULD NOT BUILD A QUOTE: {exc}")
        return

    result = generate_quote(request)
    _print_header(result)
    _print_eligibility(result)
    if not result.eligibility.eligible:
        print("(Rate stack and waterfall withheld — request is not eligible.)")
        return
    _print_rate_stack(result)
    _print_waterfall(result)
    _print_costs(result)


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--text":
        if len(args) < 2:
            print("Usage: python cli.py --text \"<scenario description>\" [--force-live]", file=sys.stderr)
            sys.exit(1)
        text = args[1]
        force_live = "--force-live" in args[2:]
        _run_from_text(text, force_live=force_live)
        return

    scenario = _read_scenario()
    request = _load_request(scenario)
    result = generate_quote(request)

    _print_header(result)
    _print_eligibility(result)
    if not result.eligibility.eligible:
        print("(Rate stack and waterfall withheld — request is not eligible.)")
        return
    _print_rate_stack(result)
    _print_waterfall(result)
    _print_costs(result)


if __name__ == "__main__":
    main()
