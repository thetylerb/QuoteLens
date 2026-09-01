# QuoteLens — Checkpoint 1: deterministic pricing core

A mortgage quote engine's pricing core. No AI, no web UI — this checkpoint
is the part that has to be *right* and *defensible* before anything gets
built on top of it.

## What it does

Given a scenario (loan amount, value, FICO, program, occupancy, property
type, transaction type...), QuoteLens:

1. **Gates eligibility** — loan limits, max LTV/CLTV, lender FICO overlay,
   DTI (pass/fail/refer). Every failure names the specific cap breached,
   with the actual value and the limit, e.g. `LTV 98.50% exceeds
   Conventional maximum 97.0%`.
2. **Prices a full rate stack** — for conventional loans, every row is
   `base_price(rate) + lock_adj − Σ(LLPAs)`, with the entire LLPA cascade
   returned as an ordered list of `Adjustment` objects, each carrying a
   `source` string naming the exact grid cell it came from. FHA/VA/USDA use
   a flatter stack with statutory fee tables and no price adjusters at all.
3. **Computes costs** — P&I, PMI/MIP/funding fee, and the loan amount
   actually being amortized (which for FHA/VA/USDA includes the financed
   upfront fee, so it's *larger* than the LTV-derived loan amount).

Every number the engine produces traces to a named cell in
`engine/config.py`, which is itself a transcription of
`reference/pricing-and-guidelines.md` — nothing is invented, and every
config table carries the reference file's own verification flag (✅/⚠️/🔶)
inline as a comment.

## Why price space, not rate space

The mortgage secondary market prices in **price points**, not rate. A rate
sheet is a table of `(rate, base_price)` rows in 0.125% increments; every
risk adjustment (credit score, LTV, occupancy, property type...) is a price
*point* deduction, and they're cumulative — there's no "worst-of" logic.
Rate is what falls out the other end once you decide how many points you're
willing to pay or credit:

```
final_price(rate) = base_price(rate) + lock_adj − Σ(LLPAs) − Σ(adjusters)
borrower_cost($)   = (100 − final_price) / 100 × loan_amount
    positive → borrower pays discount points
    negative → lender credit toward closing costs
```

If you price in rate space instead, you lose the additive structure that
makes an LLPA cascade auditable — you'd have to convert every adjuster to a
rate delta first, and those deltas aren't linear or portable across the
stack. Pricing in points and only converting to rate for display is what
lets every dollar of borrower cost trace back to a specific grid cell.

The classic bug this discipline catches: **LLPAs are not monotonic in
LTV**. The reference file's 75–80% LTV band is *worse* than the >95% band
for the same FICO row, because above 80% the borrower carries PMI, so
Fannie's own credit exposure drops. A rate-space mental model makes this
look like a bug; in price space it's just a cell in a table.

## Structure

```
engine/config.py       every grid, limit, fee, and calibration constant — nothing inline elsewhere
engine/models.py       QuoteRequest, QuoteResult, RateOption, Adjustment, EligibilityResult
engine/eligibility.py  the gate — pass/fail/refer, never a bare False
engine/pricing.py      rate stack + LLPA cascade (conventional) / flat stack + no adjusters (govt)
engine/costs.py        P&I, PMI/MIP, funding fee, breakeven
engine/quote.py         orchestrates request -> eligibility -> pricing -> costs
cli.py                  scenario in, formatted quote out
examples/worked_example.json
tests/test_pricing.py
```

`LENDER_OVERLAYS` in `config.py` is kept structurally separate from the
agency tables (loan limits, LTV caps, LLPA grids) — that mirrors how a real
lender is organized: agency eligibility is a floor set by Fannie/Freddie/
HUD/VA, and the lender's own credit box sits on top of it as an independent,
tunable layer. Right now it's just `min_fico: 620`, but the separation is
the point, not the single value in it.

## Running it

```
pip install -r requirements.txt

python cli.py examples/worked_example.json
# or
cat examples/worked_example.json | python cli.py

pytest tests/ -v
```

## Known limitations (declared, not hidden)

- **Base price rate stack**: the reference file publishes exact base prices
  for only 4 rates (from its own worked example). Those 4 are hardcoded
  exactly; the rest of the 5.500%–8.000% stack is constructed from the
  file's documented slope rule ("~0.500 price per 0.125% step near par,
  flattening to ~0.350 at the edges") and is explicitly illustrative — see
  the comment block above `RATE_STACK_ANCHORS` in `config.py`.
- **Attribute adders (condo, investment, high-balance, etc.)** are published
  in the reference file only for the purchase-money grid. Limited-cash-out
  and cash-out refis get their FICO×LTV base grid priced correctly, but a
  triggered attribute on those transaction types shows up in the waterfall
  as an explicit `(unpriced)` line rather than borrowing the purchase
  number.
- **High-balance / loan-limit determination is national, not county-level.**
  Real conforming/FHA limits are set per county (FIPS), and the reference
  file says as much explicitly. No FIPS table was provided, so this engine
  uses the national baseline/ceiling only.
- **FHA 3–4 unit loan limits** aren't published in the reference file and
  aren't modeled; a 3–4 unit FHA request is flagged as unsupported rather
  than guessed.
- **The FHA $726,200 MIP threshold** is used exactly as published (static),
  though the reference file itself flags disagreement over whether it
  floats with the current conforming limit — see the comment above
  `FHA_ANNUAL_MIP_TABLE`.
- **USDA's annual fee** is approximated on the original loan balance rather
  than the true average scheduled unpaid balance (which needs a full
  amortization schedule); flagged in `costs.usda_annual_fee_monthly`.
- **VA residual income** only supports loan amounts ≥ $80,000 and family
  sizes up to 7 (both are the limits of what the reference file publishes).

## Tests

`tests/test_pricing.py` is written to read as a spec — each test class pins
one fact from the reference file, including the two easiest ways to get a
pricing engine wrong: the LTV band off-by-one at exactly 80.000%, and the
non-monotonic LLPA hump at 75–80% LTV.
