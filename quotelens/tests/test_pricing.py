"""
QuoteLens pricing core — spec.

Each test below pins a fact from reference/pricing-and-guidelines.md. Where
a test fails, the fix is almost always in engine/config.py, not in the
pricing/eligibility/costs logic itself.
"""

from __future__ import annotations

import pytest

from engine import config, costs, eligibility, pricing
from engine.models import (
    Occupancy,
    Program,
    PropertyType,
    QuoteRequest,
    TransactionType,
)


def _worked_example(**overrides) -> QuoteRequest:
    """$500,000 price / $400,000 loan (80.00% LTV), FICO 745, primary, SFR
    detached, 30-yr fixed conforming, 30-day lock, no subordinate financing.
    reference/pricing-and-guidelines.md section 7."""
    fields = dict(
        program=Program.CONVENTIONAL,
        transaction_type=TransactionType.PURCHASE,
        occupancy=Occupancy.PRIMARY,
        property_type=PropertyType.SFR_DETACHED,
        purchase_price=500_000,
        loan_amount=400_000,
        fico=745,
        units=1,
        term_months=360,
        is_arm=False,
        lock_days=30,
        cltv=None,
        dti_back=36.0,
    )
    fields.update(overrides)
    return QuoteRequest(**fields)


# ---------------------------------------------------------------------------
# Worked example (section 7)
# ---------------------------------------------------------------------------

class TestWorkedExample:
    def test_ltv_is_exactly_80_percent(self):
        assert _worked_example().ltv == 80.0

    def test_total_llpa_is_exactly_0_875(self):
        """740-759 x 75-80 cell, no other adders apply."""
        request = _worked_example()
        adjustments = pricing.llpa_adjustments(request)
        total = sum(a.amount_in_points for a in adjustments)
        assert total == pytest.approx(0.875)

    def test_llpa_traces_to_a_single_named_cell(self):
        request = _worked_example()
        adjustments = pricing.llpa_adjustments(request)
        assert len(adjustments) == 1
        assert adjustments[0].amount_in_points == pytest.approx(0.875)
        assert "740-759" in adjustments[0].source
        assert "75-80" in adjustments[0].source

    def test_dti_never_appears_as_a_price_adjustment(self):
        """FHFA deleted every DTI-based LLPA effective 05/01/2023 — DTI must
        never surface as an Adjustment, only as an eligibility pass/fail/refer."""
        request = _worked_example()
        adjustments = pricing.llpa_adjustments(request)
        assert not any("dti" in a.name.lower() for a in adjustments)


# ---------------------------------------------------------------------------
# P&I, to the cent
# ---------------------------------------------------------------------------

class TestMonthlyPI:
    def test_pi_at_6_500_on_400k_360mo(self):
        assert costs.monthly_pi(400_000, 6.500, 360) == 2528.27

    def test_pi_at_6_625_on_400k_360mo(self):
        assert costs.monthly_pi(400_000, 6.625, 360) == 2561.24


# ---------------------------------------------------------------------------
# Price -> borrower cost / lender credit
# ---------------------------------------------------------------------------

class TestBorrowerCostFormula:
    def test_price_99_875_on_400k_loan_costs_500(self):
        assert pricing.borrower_cost_dollars(99.875, 400_000) == 500.0

    def test_price_100_375_on_400k_loan_credits_1500(self):
        assert pricing.borrower_cost_dollars(100.375, 400_000) == -1500.0


# ---------------------------------------------------------------------------
# LTV banding is exclusive-upper — the classic off-by-one (section 2/8.3)
# ---------------------------------------------------------------------------

class TestLTVBandBoundary:
    def test_ltv_exactly_80_000_lands_in_75_80(self):
        assert config.ltv_band(80.000) == "75-80"

    def test_ltv_80_001_lands_in_80_85(self):
        assert config.ltv_band(80.001) == "80-85"


# ---------------------------------------------------------------------------
# LLPA is NOT monotonic in LTV — the 75-80 hump (section 2)
# ---------------------------------------------------------------------------

class TestLLPANonMonotonicity:
    def test_75_80_cell_is_worse_than_above_95_cell_same_fico(self):
        row = config.LLPA_PURCHASE["740-759"]
        assert row["75-80"] > row[">95"]
        assert row["75-80"] == pytest.approx(0.875)
        assert row[">95"] == pytest.approx(0.500)


# ---------------------------------------------------------------------------
# Cumulative adders — no worst-of logic (section 2)
# ---------------------------------------------------------------------------

class TestCumulativeAdders:
    def test_investment_condo_high_balance_sum_correctly(self):
        """FICO 745, 75-80 LTV, investment + condo + high-balance FRM."""
        request = _worked_example(
            occupancy=Occupancy.INVESTMENT,
            property_type=PropertyType.CONDO,
            loan_amount=900_000,
            purchase_price=1_125_000,  # 80.00% LTV, above 1-unit conforming baseline -> high-balance
        )
        assert request.ltv == 80.0
        assert eligibility.is_high_balance(request)

        adjustments = pricing.llpa_adjustments(request)
        names = {a.name for a in adjustments}
        assert "Investment property" in names
        assert "Condo" in names
        assert "High-balance FRM" in names

        base = config.LLPA_PURCHASE["740-759"]["75-80"]
        investment = config.LLPA_PURCHASE_ADDERS["investment_property"]["75-80"]
        condo = config.LLPA_PURCHASE_ADDERS["condo"]["75-80"]
        high_balance = config.LLPA_PURCHASE_ADDERS["high_balance_frm"]["75-80"]
        expected = base + investment + condo + high_balance

        total = sum(a.amount_in_points for a in adjustments)
        assert total == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Eligibility gate names the specific cap, actual value, and limit
# ---------------------------------------------------------------------------

class TestEligibilityFailureMessages:
    def test_ltv_failure_names_actual_and_limit(self):
        """98.5% LTV on a conventional purchase exceeds the 97% cap."""
        request = _worked_example(loan_amount=985_000, purchase_price=1_000_000)
        result = eligibility.evaluate(request)
        failure = next(c for c in result.checks if c.name == "max_ltv")
        assert not failure.passed
        assert failure.actual == pytest.approx(98.5)
        assert failure.limit == pytest.approx(97.0)
        assert "98.50%" in failure.detail
        assert "97.0%" in failure.detail
        assert not result.eligible

    def test_min_fico_overlay_failure_names_actual_and_limit(self):
        request = _worked_example(fico=600)
        result = eligibility.evaluate(request)
        failure = next(c for c in result.checks if c.name == "min_fico_overlay")
        assert not failure.passed
        assert failure.actual == 600
        assert failure.limit == config.LENDER_OVERLAYS["min_fico_conventional"]


# ---------------------------------------------------------------------------
# Conventional PMI: required above 80% LTV, none at or below (section 5)
# ---------------------------------------------------------------------------

class TestConventionalPMI:
    def test_no_pmi_at_80_percent_ltv(self):
        assert costs.monthly_pmi(400_000, 745, 80.0) == 0.0

    def test_pmi_required_above_80_percent_ltv(self):
        pmi = costs.monthly_pmi(400_000, 745, 85.0)
        assert pmi > 0.0
        # 85.01-90 band would be the next one up; 85.0 itself lands in 80.01-85
        factor = config.PMI_MONTHLY_FACTORS["80.01-85"]["740-759"]
        assert pmi == pytest.approx(round(factor / 100 * 400_000 / 12, 2))


# ---------------------------------------------------------------------------
# FHA UFMIP inflates the final loan amount (section 5 / requirement 7)
# ---------------------------------------------------------------------------

class TestFHAUFMIP:
    def test_ufmip_added_after_base_loan_amount(self):
        base_loan = 400_000
        final = costs.fha_final_loan_amount(base_loan)
        assert final > base_loan
        assert final == pytest.approx(base_loan * 1.0175)

    def test_ufmip_amount_is_1_75_percent_of_base(self):
        assert costs.fha_ufmip(400_000) == pytest.approx(7_000.0)


# ---------------------------------------------------------------------------
# VA funding fee (section 5)
# ---------------------------------------------------------------------------

class TestVAFundingFee:
    def _va_request(self, **overrides):
        fields = dict(
            program=Program.VA,
            transaction_type=TransactionType.PURCHASE,
            occupancy=Occupancy.PRIMARY,
            property_type=PropertyType.SFR_DETACHED,
            purchase_price=400_000,
            loan_amount=400_000,
            fico=680,
            dti_back=30.0,
        )
        fields.update(overrides)
        return QuoteRequest(**fields)

    def test_first_use_zero_down_is_2_30_percent(self):
        req = self._va_request(va_first_use=True, va_down_payment_pct=0.0)
        fee, rate, _ = costs.va_funding_fee(req.loan_amount, req)
        assert rate == pytest.approx(0.0230)
        assert fee == pytest.approx(400_000 * 0.0230)

    def test_subsequent_use_zero_down_is_3_60_percent(self):
        req = self._va_request(va_first_use=False, va_down_payment_pct=0.0)
        fee, rate, _ = costs.va_funding_fee(req.loan_amount, req)
        assert rate == pytest.approx(0.0360)
        assert fee == pytest.approx(400_000 * 0.0360)

    def test_first_and_subsequent_use_identical_at_5_percent_down(self):
        first = self._va_request(va_first_use=True, va_down_payment_pct=5.0)
        subsequent = self._va_request(va_first_use=False, va_down_payment_pct=5.0)
        fee_first, rate_first, _ = costs.va_funding_fee(first.loan_amount, first)
        fee_subsequent, rate_subsequent, _ = costs.va_funding_fee(subsequent.loan_amount, subsequent)
        assert rate_first == rate_subsequent == pytest.approx(0.0165)
        assert fee_first == fee_subsequent

    def test_exempt_borrower_pays_no_fee_at_all(self):
        req = self._va_request(va_exempt=True, va_first_use=True, va_down_payment_pct=0.0)
        fee, rate, label = costs.va_funding_fee(req.loan_amount, req)
        assert fee == 0.0
        assert rate == 0.0
        assert "exempt" in label.lower()
