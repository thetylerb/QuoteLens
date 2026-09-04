"""
QuoteLens scenario extraction — spec.

Covers the extraction contract shape, the fallback (non-LLM) parser, the
provisional-confidence gate, graceful degradation on unparseable input, and
that a cache hit never reaches the network.
"""

from __future__ import annotations

import pytest

from engine import extraction
from engine.extraction import EXTRACTION_FIELDS, ExtractionResult


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Never touch the real data/extraction_cache.json from tests."""
    monkeypatch.setattr(extraction, "CACHE_PATH", tmp_path / "extraction_cache.json")


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """Default every test to the no-key fallback path unless it sets its own key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


CLEAN_SCENARIO = (
    "Sarah is buying a $450,000 single family home in Austin, TX as her "
    "primary residence. Credit score 760, putting 20% down, conventional "
    "loan, 30-year fixed, 45-day rate lock."
)


class TestContractShape:
    def test_returns_exact_contract_shape(self):
        result = extraction.extract(CLEAN_SCENARIO)
        assert isinstance(result, ExtractionResult)
        assert result.source in ("live", "cache", "fallback")
        assert isinstance(result.confidence, float)
        assert set(result.fields.keys()) == set(EXTRACTION_FIELDS)
        assert isinstance(result.assumptions, list)
        assert isinstance(result.evidence, dict)
        assert isinstance(result.notes, str)

    def test_assumption_entries_have_field_value_reason(self):
        sparse = "Client wants to purchase a $600,000 property, credit score 705, 15% down, conventional financing, 30-year term."
        result = extraction.extract(sparse)
        assert len(result.assumptions) > 0
        for a in result.assumptions:
            assert a.field
            assert a.reason


class TestAssumptionsPopulated:
    def test_missing_fields_produce_assumptions(self):
        sparse = "Client wants to purchase a $600,000 property, credit score 705, 15% down, conventional financing, 30-year term."
        result = extraction.extract(sparse)
        assumed_fields = {a.field for a in result.assumptions}
        # No occupancy, property type, or lock stated in this scenario.
        assert "occupancy" in assumed_fields
        assert "property_type" in assumed_fields or result.fields["property_type"] is not None

    def test_stated_field_never_also_appears_as_assumed(self):
        # lock_days is a deliberate exception: CLEAN_SCENARIO states a 45-day
        # lock, but the pricing engine only prices 30-day locks (see
        # config.LOCK_DAY_ADJUSTMENTS), so to_quote_request transparently
        # overrides it and discloses that override as an assumption. The
        # STATED block still shows the real 45-day statement — see
        # engine/extraction.py's lock_days handling in to_quote_request.
        result = extraction.extract(CLEAN_SCENARIO)
        request = extraction.to_quote_request(result)
        assumed_fields = {a.field for a in result.assumptions}
        for field_name in result.evidence:
            if field_name == "lock_days":
                continue
            assert field_name not in assumed_fields


class TestFallbackParser:
    def test_fallback_used_with_no_api_key(self):
        result = extraction.extract(CLEAN_SCENARIO)
        assert result.source == "fallback"

    def test_fallback_handles_clean_scenario(self):
        result = extraction.extract(CLEAN_SCENARIO)
        assert result.fields["purchase_price"] == 450_000
        assert result.fields["fico"] == 760
        assert result.fields["occupancy"] == "primary"
        assert result.fields["property_type"] == "sfr_detached"
        assert result.fields["program"] == "conventional"
        assert result.fields["down_payment_pct"] == 20.0

        request = extraction.to_quote_request(result)
        assert request.purchase_price == 450_000
        assert request.loan_amount == pytest.approx(360_000)
        assert request.fico == 760

    def test_townhouse_is_always_an_assumption_not_evidence(self):
        result = extraction.extract("Looking at a $400,000 townhouse, primary residence, credit 700, conventional, 30 year.")
        assert result.fields["property_type"] is not None
        assert "property_type" not in result.evidence
        assert any(a.field == "property_type" for a in result.assumptions)

    def test_ambiguous_bare_dollar_figure_is_flagged(self):
        result = extraction.extract("Client has $525,000 to work with for a primary residence purchase, credit 730, conventional, single family, 30-year fixed, 30-day lock.")
        assert any(a.field == "purchase_price" for a in result.assumptions)
        assert result.notes != ""


class TestMoneyForms:
    """The fallback's money regex has to recognize every common written form
    of a dollar figure, not just comma-grouped digits — see the $450,000
    Sarah/Austin bug this class was written to cover."""

    @pytest.mark.parametrize("phrase", ["$450,000", "$450000", "$450k", "450k"])
    def test_common_price_forms_resolve_to_450000(self, phrase):
        result = extraction.extract(
            f"Sarah is buying a {phrase} single family home in Austin, TX."
        )
        assert result.fields["purchase_price"] == pytest.approx(450_000)

    def test_million_suffix_resolves_correctly(self):
        result = extraction.extract(
            "Sarah is buying a $1.2M single family home in Austin, TX."
        )
        assert result.fields["purchase_price"] == pytest.approx(1_200_000)

    def test_loan_keyword_assigns_loan_amount_not_price(self):
        result = extraction.extract(
            "Client wants a $300,000 loan for a home purchase, credit 700, conventional, 30-year fixed, 30-day lock."
        )
        assert result.fields["loan_amount"] == pytest.approx(300_000)

    def test_price_and_loan_both_stated_are_kept_distinct(self):
        result = extraction.extract(
            "Purchase price is $500k, loan amount $400k, credit 700, primary residence, "
            "single family, conventional, 30-year fixed, 30-day lock."
        )
        assert result.fields["purchase_price"] == pytest.approx(500_000)
        assert result.fields["loan_amount"] == pytest.approx(400_000)

    def test_genuinely_ambiguous_figure_is_assumed_as_price(self):
        # No "price"/"loan"/"home" anchor word anywhere near this figure —
        # must still resolve (as purchase price) rather than return nothing.
        result = extraction.extract(
            "Sarah has $450,000 available, credit 700, primary residence, "
            "single family, conventional, 30-year fixed, 30-day lock."
        )
        assert result.fields["purchase_price"] == pytest.approx(450_000)
        assert any(a.field == "purchase_price" for a in result.assumptions)
        assert result.notes != ""


class TestProvisionalFlag:
    def test_low_confidence_sets_provisional(self):
        sparse = "credit's around 725"
        result = extraction.extract(sparse)
        assert result.confidence < extraction.CONFIDENCE_THRESHOLD
        assert result.provisional is True

    def test_high_confidence_scenario_is_not_provisional(self):
        result = extraction.extract(CLEAN_SCENARIO)
        assert result.confidence >= extraction.CONFIDENCE_THRESHOLD
        assert result.provisional is False


class TestGracefulDegradation:
    def test_unparseable_input_degrades_rather_than_raising(self):
        result = extraction.extract("asdf jkl qwerty zzz ??? ...")
        assert isinstance(result, ExtractionResult)
        assert result.source == "fallback"
        assert result.confidence == 0.0

    def test_unparseable_input_has_no_price_or_loan_amount(self):
        result = extraction.extract("asdf jkl qwerty zzz ??? ...")
        with pytest.raises(extraction.InsufficientDataError):
            extraction.to_quote_request(result)


class TestCacheHit:
    def test_cache_hit_returns_source_cache_without_api_call(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("live extraction should not be called on a cache hit")

        monkeypatch.setattr(extraction, "_extract_live", _boom)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key-not-used")

        text = "some scenario text for the cache test"
        key = extraction._hash_text(text)
        extraction._cache_store(key, {
            "fields": {k: None for k in EXTRACTION_FIELDS},
            "confidence": 0.95,
            "assumptions": [],
            "evidence": {},
            "notes": "",
        })

        result = extraction.extract(text)
        assert result.source == "cache"
        assert result.confidence == 0.95

    def test_force_live_bypasses_cache(self, monkeypatch):
        text = "some other scenario text"
        key = extraction._hash_text(text)
        extraction._cache_store(key, {
            "fields": {k: None for k in EXTRACTION_FIELDS},
            "confidence": 0.5,
            "assumptions": [],
            "evidence": {},
            "notes": "",
        })
        # No API key set -> force_live still can't actually call live, so it
        # must fall through to the fallback parser rather than the cache.
        result = extraction.extract(text, force_live=True)
        assert result.source == "fallback"
