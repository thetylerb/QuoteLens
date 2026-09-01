# Mortgage pricing and eligibility — reference

Everything the quote engine needs to be believable. Researched September 2026.

**Verification legend:** ✅ verified against a primary source · ⚠️ secondary source, structurally right, verify before hardcoding · 🔶 illustrative, no authoritative public source

> **Why this file exists:** a hiring manager at a mortgage company will know within thirty seconds whether the numbers are real. Everything here is either cited or explicitly flagged as illustrative. Do not invent figures to fill gaps — flag them the way this file does.

---

## 1. The one mechanic to get right: price space, not rate space

Every pricing adjustment in the industry is expressed in **price points**, and it **subtracts from price**. Rate is what you solve for and display, never what you adjust internally.

```
final_price(rate) = base_price(rate)
                  + lock_adjustment
                  - Σ(LLPAs)
                  - Σ(investor adjusters)
                  - compensation

borrower_cost($) = (100 - final_price) / 100 * loan_amount
    positive → borrower pays discount points
    negative → lender credit toward closing costs
```

Price is quoted per 100 of loan amount. **100.000 is par.** Above par is rebate/lender credit; below par is discount points the borrower pays. Higher risk → lower price → the borrower pays more points or takes a higher rate.

A rate sheet is a table of `(note rate, base price)` rows in **0.125% increments**, typically spanning about 5.500%–8.000%. Price rises as you walk up the rate stack. Slope near par is roughly **0.500 price per 0.125% rate step** 🔶, flattening toward the edges.

The engine returns the *whole stack* and the borrower picks a row. That grid of ~10 rate options each with its dollar cost or credit is the classic PPE output.

---

## 2. Fannie Mae LLPAs

**Source:** [LLPA Matrix, effective 01/28/2026](https://singlefamily.fanniemae.com/media/9391/display) ✅

Rules that matter for implementation:

- LLPAs are **cumulative**. Sum the FICO×LTV cell plus every applicable attribute adder. There is no worst-of logic.
- Keyed on the **representative credit score**.
- LTV bands are **exclusive-upper**: "75–80" means 75.01–80.00, so an LTV of exactly 80.000 lands in the 75–80 bucket. This off-by-one is the classic bug, and it is the difference between the pricing hump and needing PMI.
- Separate, flatter grids exist for terms ≤ 15 years. Everything below is **> 15 year terms**.
- Subordinate-financing adders key off **CLTV**, not LTV. Separate lookup axis.

### Purchase money — FICO × LTV ⚠️

| FICO | <30% | 30–60 | 60–70 | 70–75 | 75–80 | 80–85 | 85–90 | 90–95 | >95 |
|---|---|---|---|---|---|---|---|---|---|
| ≥780 | 0.000 | 0.000 | 0.000 | 0.000 | 0.375 | 0.375 | 0.250 | 0.250 | 0.125 |
| 760–779 | 0.000 | 0.000 | 0.000 | 0.250 | 0.625 | 0.625 | 0.500 | 0.500 | 0.250 |
| 740–759 | 0.000 | 0.000 | 0.125 | 0.375 | 0.875 | 1.000 | 0.750 | 0.625 | 0.500 |
| 720–739 | 0.000 | 0.000 | 0.250 | 0.750 | 1.250 | 1.250 | 1.000 | 0.875 | 0.750 |
| 700–719 | 0.000 | 0.000 | 0.375 | 0.875 | 1.375 | 1.500 | 1.250 | 1.125 | 0.875 |
| 680–699 | 0.000 | 0.000 | 0.625 | 1.125 | 1.750 | 1.875 | 1.500 | 1.375 | 1.125 |
| 660–679 | 0.000 | 0.000 | 0.750 | 1.375 | 1.875 | 2.125 | 1.750 | 1.625 | 1.250 |
| 640–659 | 0.000 | 0.000 | 1.125 | 1.500 | 2.250 | 2.500 | 2.000 | 1.875 | 1.500 |
| ≤639 | 0.000 | 0.125 | 1.500 | 2.125 | 2.750 | 2.875 | 2.625 | 2.250 | 1.750 |

**The counterintuitive bit worth knowing cold:** the worst LTV band is **75–80%**, not >95%. Above 80% the borrower carries PMI, so Fannie's own credit exposure drops and the LLPA falls. Never assume LLPA rises monotonically with LTV, and this is a genuinely good thing to be able to explain out loud in an interview.

### Purchase money — attribute adders ⚠️

| Attribute | <30 | 30–60 | 60–70 | 70–75 | 75–80 | 80–85 | 85–90 | 90–95 | >95 |
|---|---|---|---|---|---|---|---|---|---|
| ARM | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.250 | 0.250 |
| Condo | 0.000 | 0.000 | 0.125 | 0.125 | 0.750 | 0.750 | 0.750 | 0.750 | 0.750 |
| Investment property | 1.125 | 1.125 | 1.625 | 2.125 | 3.375 | 4.125 | 4.125 | 4.125 | 4.125 |
| Second home | 1.125 | 1.125 | 1.625 | 2.125 | 3.375 | 4.125 | 4.125 | 4.125 | 4.125 |
| Manufactured home | 0.500 flat across all bands |
| 2–4 unit | 0.000 | 0.000 | 0.375 | 0.375 | 0.625 | 0.625 | 0.625 | 0.625 | 0.625 |
| High-balance FRM | 0.500 | 0.500 | 0.750 | 0.750 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| High-balance ARM | 1.250 | 1.250 | 1.500 | 1.500 | 2.500 | 2.500 | 2.500 | 2.750 | 2.750 |
| Subordinate financing (by CLTV) | 0.625 | 0.625 | 0.625 | 0.875 | 1.125 | 1.125 | 1.125 | 1.875 | 1.875 |

### Limited cash-out refinance (rate/term) — FICO × LTV ⚠️

| FICO | <30 | 30–60 | 60–70 | 70–75 | 75–80 | 80–85 | 85–90 | 90–95 | >95 |
|---|---|---|---|---|---|---|---|---|---|
| ≥780 | 0.000 | 0.000 | 0.000 | 0.125 | 0.500 | 0.625 | 0.500 | 0.375 | 0.375 |
| 760–779 | 0.000 | 0.000 | 0.125 | 0.375 | 0.875 | 1.000 | 0.750 | 0.625 | 0.625 |
| 740–759 | 0.000 | 0.000 | 0.250 | 0.750 | 1.125 | 1.375 | 1.125 | 1.000 | 1.000 |
| 720–739 | 0.000 | 0.000 | 0.500 | 1.000 | 1.625 | 1.750 | 1.500 | 1.250 | 1.250 |
| 700–719 | 0.000 | 0.000 | 0.625 | 1.250 | 1.875 | 2.125 | 1.750 | 1.625 | 1.625 |
| 680–699 | 0.000 | 0.000 | 0.875 | 1.625 | 2.250 | 2.500 | 2.125 | 1.750 | 1.750 |
| 660–679 | 0.000 | 0.125 | 1.125 | 1.875 | 2.500 | 3.000 | 2.375 | 2.125 | 2.125 |
| 640–659 | 0.000 | 0.250 | 1.375 | 2.125 | 2.875 | 3.375 | 2.875 | 2.500 | 2.500 |
| ≤639 | 0.000 | 0.375 | 1.750 | 2.500 | 3.500 | 3.875 | 3.625 | 2.500 | 2.500 |

### Cash-out refinance — FICO × LTV ⚠️

Cash-out caps at 80% LTV, so the grid stops there.

| FICO | <30 | 30–60 | 60–70 | 70–75 | 75–80 |
|---|---|---|---|---|---|
| ≥780 | 0.375 | 0.375 | 0.625 | 0.875 | 1.375 |
| 760–779 | 0.375 | 0.375 | 0.875 | 1.250 | 1.875 |
| 740–759 | 0.375 | 0.375 | 1.000 | 1.625 | 2.375 |
| 720–739 | 0.375 | 0.500 | 1.375 | 2.000 | 2.750 |
| 700–719 | 0.375 | 0.500 | 1.625 | 2.625 | 3.250 |
| 680–699 | 0.375 | 0.625 | 2.000 | 2.875 | 3.750 |
| 660–679 | 0.375 | 0.875 | 2.750 | 4.000 | 4.750 |
| 640–659 | 0.375 | 1.375 | 3.125 | 4.625 | 5.125 |
| ≤639 | 0.375 | 1.375 | 3.375 | 4.875 | 5.125 |

Cash-out high-balance FRM adders run 1.250→1.750, notably higher than purchase.

### The May 2023 restructure ✅

FHFA directed a wholesale re-grid effective 05/01/2023. Two things matter:

1. **All DTI-based LLPAs were deleted.** A proposed 0.375% adder for DTI ≥ 40% was rescinded entirely. **Do not model a DTI price adjustment.** DTI is a pure eligibility gate. This is a detail almost nobody outside the industry knows, and getting it right is a credibility marker.
2. The grid flattened at the low-FICO/high-LTV corner and rose in the mid-FICO/mid-LTV zone, which produced the 75–80% hump and the "good credit subsidizes bad credit" controversy ([House Financial Services letter, Apr 2023](https://financialservices.house.gov/UploadedFiles/2023-04-25_McHenry_Davidson_letter_to_FHFA_LLPAs_Final.pdf)).

The 01/28/2026 matrix replaced "appraisal waiver" with **"value acceptance offer"** terminology. No structural re-grid since May 2023.

Freddie Mac publishes a near-identical Credit Fee Matrix. One grid with an `agency` flag is fine for a simulation.

---

## 3. Eligibility caps, 2026

### Conforming loan limits ✅

[FHFA announcement](https://www.fhfa.gov/news/news-release/fhfa-announces-conforming-loan-limit-values-for-2026) · +3.26% over 2025

| Units | Baseline | High-cost ceiling (150%) |
|---|---|---|
| 1 | **$832,750** | **$1,249,125** |
| 2 | $1,066,250 | $1,599,375 |
| 3 | $1,288,800 | $1,933,200 |
| 4 | $1,601,750 | $2,402,625 |

- AK, GU, HI, USVI baseline equals the high-cost figures.
- **Hawaii is the only high-cost exception area in 2026** (1-unit $1,299,500).
- **High-balance** = above baseline, at or below the county ceiling. This is **county-level**, so a realistic engine needs a FIPS→limit table, not one national threshold. Above the county ceiling the loan is jumbo and falls off the agency grid entirely.

### Conventional max LTV (DU) ⚠️

[Fannie Eligibility Matrix](https://singlefamily.fanniemae.com/media/20786/display)

| Occupancy / units | Purchase & LCOR | Cash-out |
|---|---|---|
| Primary, 1-unit FRM | **97%** | 80% |
| Primary, 1-unit ARM | 95% | 80% |
| Primary, 2-unit | 95% | 75% |
| Primary, 3–4 unit | 95% | 75% |
| Second home, 1-unit | 90% | 75% |
| Investment, 1-unit | 85% purchase / 75% LCOR | 75% |
| Investment, 2–4 unit | 75% | 70% |

**Credit score floor — 2026 change** ✅ [Pennymac 25-119](https://corr.pennymac.com/announcements/announcement-25-119): **DU 12.0, effective 11/16/2025, eliminated the minimum credit score requirement** for Fannie Standard, HomeReady, Manufactured Homes, and Single-Close Construction-to-Perm. DU now relies on holistic risk analysis. RefiNow keeps 620; HomeStyle keeps 680; manual underwriting keeps the 620 representative-score floor.

In practice nearly every lender keeps a **620 overlay**. Model overlays as a **separate configurable layer** distinct from agency rules — that is exactly how a real shop works, and it is a good thing to be able to point at.

### FHA ⚠️

[HUD 2026 loan limits](https://www.hud.gov/news/hud-no-25-145) ✅ — floor is 65% of conforming, ceiling 150%.

| Units | Floor | Ceiling |
|---|---|---|
| 1 | **$541,287** | **$1,249,125** |
| 2 | $693,050 | $1,599,375 |

- Purchase, FICO ≥ 580: **96.5% LTV**. FICO 500–579: **90%**.
- Rate/term refi 97.75%. **Cash-out 80%** ✅ (down from 85% in 2019).
- **FHA has no LLPA structure at all.** Risk is priced through MIP. This is an architectural difference: government products need a flatter rate stack plus statutory fee tables, conventional needs the price-adjuster cascade. One code path for both produces wrong answers.

### VA ⚠️

100% LTV. **No loan limit** with full entitlement (Blue Water Navy Act 2020); county limits bind only on partial or restored entitlement. No MI, no LLPA grid — risk is in the funding fee.

### USDA ⚠️

100% LTV. Upfront guarantee fee **1.00%** (financeable), annual fee **0.35%** on the average scheduled unpaid balance. Income cap 115% of area median. Ratios 29/41.

---

## 4. DTI and qualifying

| Program | Max DTI | Source |
|---|---|---|
| Fannie, DU | **50%** | ✅ [Selling Guide B3-6-02](https://selling-guide.fanniemae.com/sel/b3-6-02/debt-income-ratios) |
| Fannie, manual | 36% base, up to **45%** with score and reserve requirements met | ✅ same |
| Freddie, LPA | **50%** accepted; 45% manual | ⚠️ |
| FHA, TOTAL Approve/Eligible | ~**56.99%** back-end in practice; no published hard cap | 🔶 |
| FHA manual, 0 compensating factors | **31 / 43** | ⚠️ |
| FHA manual, 1 factor | **37 / 47** | ⚠️ |
| FHA manual, 2+ factors | **40 / 50** | ⚠️ |
| VA | No hard cap; **41%** is the scrutiny threshold | ⚠️ |
| USDA | 29 / 41, waivable with GUS Accept | ⚠️ |

**DTI is eligibility-only, never priced.** In the engine it returns pass/fail/refer, not a price delta.

### VA residual income ✅

VA's distinctive test: minimum dollars remaining monthly after PITI, all debts, maintenance/utilities, and taxes. [Source](https://www.veteransunited.com/valoans/explaining-the-vas-standard-for-residual-income/)

**Loan amounts $80,000 and above:**

| Family size | Northeast | Midwest | South | West |
|---|---|---|---|---|
| 1 | $450 | $441 | $441 | $491 |
| 2 | $755 | $738 | $738 | $823 |
| 3 | $909 | $889 | $889 | $990 |
| 4 | $1,025 | $1,003 | $1,003 | $1,117 |
| 5 | $1,062 | $1,039 | $1,039 | $1,158 |
| >5 | +$80 per additional member, up to family of 7 |

**The 20% rule:** if DTI > 41%, required residual must **exceed the guideline by 20%**. Midwest family of 4 at 44% DTI needs $1,003 × 1.20 = **$1,203.60**.

This is the most under-modeled piece of VA qualifying and a strong differentiator. Most consumer mortgage calculators do not implement it at all.

---

## 5. Mortgage insurance

### Conventional PMI

Required when **LTV > 80%**. Coverage is a percentage of the loan the MI company insures, set by LTV:

| LTV | Required coverage |
|---|---|
| 95.01–97% | 35% |
| 90.01–95% | 30% |
| 85.01–90% | 25% |
| 80.01–85% | 12% |

**BPMI monthly annual premium factors**, 30-yr fixed, standard coverage ⚠️🔶 — *structurally correct and realistic in magnitude, but sourced from an archived MGIC card. Current cards sit behind MI-company logins and most MIs now use proprietary risk engines rather than published grids. Calibration, not truth.*

| LTV | 760+ | 740–759 | 720–739 | 700–719 | 680–699 | 660–679 | 640–659 | 620–639 |
|---|---|---|---|---|---|---|---|---|
| 95.01–97% | 0.38 | 0.53 | 0.66 | 0.78 | 0.96 | 1.28 | 1.33 | 1.42 |
| 90.01–95% | 0.34 | 0.48 | 0.59 | 0.68 | 0.87 | 1.11 | 1.19 | 1.25 |
| 85.01–90% | 0.28 | 0.38 | 0.46 | 0.55 | 0.65 | 0.90 | 0.91 | 0.94 |
| ≤85% | 0.19 | 0.20 | 0.23 | 0.25 | 0.28 | 0.38 | 0.40 | 0.44 |

`monthly PMI = annual_factor × original_loan_amount / 12`. Auto-terminates at 78% LTV by original schedule (HPA); cancellable on request at 80%.

Note that **MI companies do price DTI** (adders above 45%) even though the agencies stopped. A nice detail.

**Sanity check for any MI grid:** it must be monotonic in both axes. A grid that isn't has a parse error in it.

### FHA MIP ⚠️

**UFMIP 1.75%** of base loan amount, financeable — and it is, nearly always. **UFMIP is added after the base loan amount is computed**, so the final loan amount exceeds the LTV-derived figure. Classic simulation bug.

**Annual MIP, term > 15 years:**

| Base loan amount | LTV | Annual MIP | Duration |
|---|---|---|---|
| ≤ $726,200 | ≤ 90% | 0.50% | 11 years |
| ≤ $726,200 | 90.01–95% | 0.50% | Life of loan |
| ≤ $726,200 | > 95% | **0.55%** | Life of loan |
| > $726,200 | ≤ 90% | 0.70% | 11 years |
| > $726,200 | 90.01–95% | 0.70% | Life of loan |
| > $726,200 | > 95% | 0.75% | Life of loan |

⚠️ **The $726,200 threshold is the 2023 conforming limit frozen into ML 2023-05 as a static figure.** Sources disagree on whether it floats. With the 2026 limit at $832,750 this materially affects loans in between. Verify against Handbook 4000.1 before relying on it.

The standard 3.5%-down FHA borrower lands at **0.55% for life of loan**. Life-of-loan MIP with no cancellation at 78% is FHA's biggest cost disadvantage against conventional and drives most FHA→conventional refi analysis.

### VA funding fee ⚠️

| Down payment | First use | Subsequent use |
|---|---|---|
| < 5% (incl. zero down) | **2.30%** | **3.60%** |
| 5–9.99% | 1.65% | 1.65% |
| ≥ 10% | 1.40% | 1.40% |

Note the structure: **subsequent use only penalizes the zero-down tier.** At 5% down or more they're identical.

Cash-out refi: 2.30% first / 3.60% subsequent. **IRRRL: 0.50%** regardless. Assumption: 0.50%.

**Exempt:** veterans receiving VA compensation for service-connected disability, those eligible but drawing retirement/active-duty pay instead, surviving spouses, and Purple Heart recipients on active duty. Exemption comes off the **Certificate of Eligibility** — treat it as an input flag, not something derived.

Financeable on top of 100% LTV, and **no monthly MI at any LTV**. One-time 2.30% versus FHA's 1.75% up front plus 0.55%/yr for life is why VA usually wins on total cost. Build that comparison into the demo.

---

## 6. Calibration anchors

- **Freddie Mac PMMS, week of 08/27/2026** ✅: 30-yr fixed **6.66%**, 15-yr **5.98%**. [freddiemac.com/pmms](https://www.freddiemac.com/pmms)
- Set par so a 780-FICO / 75%-LTV / primary / SFR scenario prices near **6.625–6.750% at zero points**. That reproduces the survey.
- Rate stack: 10–12 rows at 0.125%, roughly 5.500%–8.000%.
- Price slope near par: **~0.500 per 0.125% step** 🔶, flattening to ~0.350 at the edges.

---

## 7. Worked example — build the test fixture from this

Purchase, $500,000 price, $400,000 loan → **80.00% LTV**, FICO 745, primary, SFR detached, 30-yr fixed conforming, 30-day lock, no subordinate financing.

LLPA lookup: purchase grid, 740–759 × 75–80 → **0.875**. No other adders. Total **0.875**.

| Option | Base price | − LLPA | Final price | Borrower cost |
|---|---|---|---|---|
| 6.375% | 99.875 | 0.875 | 99.000 | pays 1.000 pt = **$4,000** |
| 6.500% | 100.750 | 0.875 | 99.875 | pays 0.125 pt = **$500** |
| 6.625% | 101.250 | 0.875 | 100.375 | **$1,500 credit** |
| 6.750% | 101.750 | 0.875 | 100.875 | **$3,500 credit** |

Base prices 🔶 illustrative, calibrated to current market.

P&I at 6.500% on $400,000 / 360 months: **$2,528.15**. At 6.625%: **$2,561.15**. The borrower trades **$33.00/mo** for **$2,000** of price — a **61-month breakeven**. That breakeven is the headline output of a good quote UI.

**Expressing an LLPA as rate:** 0.875 points ÷ ~4.5 points-per-percent ≈ **0.194% of rate**, rounding to about 0.125–0.250% higher. Compute this as a *display* value only. Always work internally in price.

---

## 8. Architecture notes

1. **Compute in price space, convert to rate for display.**
2. **Three separate concerns:** eligibility gate (limits, LTV/CLTV caps, DTI, occupancy, FICO floors → pass/fail/refer); pricing engine (rate stack + adjuster cascade); cost calculator (P&I, MI, escrows, breakeven).
3. **Band-boundary logic is exclusive-upper.** LTV exactly 80.000 → the 75–80 bucket.
4. **Conventional and government need different pipelines.** Conventional = stack + LLPA cascade + PMI. FHA/VA/USDA = flatter stack + statutory fee tables, no price adjusters.
5. **Loan limits are county-level (FIPS).**
6. **Lender overlays are their own layer**, distinct from agency rules.

---

## Three things to verify before hardcoding

1. The full LLPA cell set against the PDF. Spot-checks held, but the tables were extracted via a summarizing fetch.
2. Whether the FHA MIP $726,200 threshold is static or floats with the conforming limit.
3. The Fannie Eligibility Matrix minimum-credit-score column, which came back inconsistent with the DU 12.0 change.

## Sources

- [Fannie Mae LLPA Matrix (eff. 01/28/2026)](https://singlefamily.fanniemae.com/media/9391/display)
- [Fannie Mae Eligibility Matrix](https://singlefamily.fanniemae.com/media/20786/display)
- [Fannie Mae Selling Guide B3-6-02, Debt-to-Income Ratios](https://selling-guide.fanniemae.com/sel/b3-6-02/debt-income-ratios)
- [FHFA — 2026 Conforming Loan Limit Values](https://www.fhfa.gov/news/news-release/fhfa-announces-conforming-loan-limit-values-for-2026)
- [HUD No. 25-145 — FHA 2026 Loan Limits](https://www.hud.gov/news/hud-no-25-145)
- [Pennymac 25-119 — DU 12.0 minimum credit score](https://corr.pennymac.com/announcements/announcement-25-119)
- [Veterans United — VA Funding Fee](https://www.veteransunited.com/valoans/va-funding-fee/) · [VA Residual Income](https://www.veteransunited.com/valoans/explaining-the-vas-standard-for-residual-income/)
- [MGIC BPMI rate card](https://www.mgic.com/-/media/mi/rates/rate-cards/71-61284-rate-card-pdf-bpmi-monthly-july-2018_archive.pdf?v=9)
- [Freddie Mac PMMS](https://www.freddiemac.com/pmms)
- [Truth About Mortgage — pricing adjustments](https://www.thetruthaboutmortgage.com/mortgage-pricing-adjustments/)
- [AD Mortgage — how to read a rate sheet](https://admortgage.com/blog/how-to-read-a-rate-sheet/)
