"""
The eligibility gate. Every failure names the specific cap breached, with
both the actual value and the limit — never a bare False.

DTI is evaluated here ONLY as pass/fail/refer. It is never converted to a
price adjustment anywhere in this codebase — see config.py's DTI section
and pricing.py's module docstring for why (FHFA deleted all DTI-based LLPAs
effective 05/01/2023).
"""

from __future__ import annotations

from . import config
from .models import EligibilityCheck, EligibilityResult, Occupancy, Program, QuoteRequest, TransactionType


def evaluate(request: QuoteRequest) -> EligibilityResult:
    if request.program == Program.CONVENTIONAL:
        return _evaluate_conventional(request)
    if request.program == Program.FHA:
        return _evaluate_fha(request)
    if request.program == Program.VA:
        return _evaluate_va(request)
    if request.program == Program.USDA:
        return _evaluate_usda(request)
    raise ValueError(f"Unknown program {request.program}")


def _units_bucket(units: int) -> int | str:
    if units <= 2:
        return units
    return "3-4"


def _loan_limit_check(request: QuoteRequest, limits: dict[int, dict[str, float]], program_label: str) -> EligibilityCheck:
    bucket = min(request.units, 4)
    if bucket not in limits:
        return EligibilityCheck(
            name="loan_limit",
            passed=False,
            detail=f"{program_label} loan limit not published in reference data for {request.units}-unit properties",
        )
    ceiling = limits[bucket].get("ceiling", limits[bucket].get("floor"))
    if request.loan_amount > ceiling:
        return EligibilityCheck(
            name="loan_limit",
            passed=False,
            detail=f"Loan amount ${request.loan_amount:,.2f} exceeds {program_label} {request.units}-unit national ceiling ${ceiling:,.2f}",
            actual=request.loan_amount,
            limit=ceiling,
        )
    return EligibilityCheck(name="loan_limit", passed=True, detail=f"Within {program_label} ceiling ${ceiling:,.2f}", actual=request.loan_amount, limit=ceiling)


def is_high_balance(request: QuoteRequest) -> bool:
    bucket = min(request.units, 4)
    limits = config.CONFORMING_LOAN_LIMITS.get(bucket)
    if not limits:
        return False
    return limits["baseline"] < request.loan_amount <= limits["ceiling"]


def _conventional_max_ltv(request: QuoteRequest) -> float:
    bucket = _units_bucket(request.units)
    if (
        request.occupancy == Occupancy.PRIMARY
        and bucket == 1
        and request.is_arm
        and request.transaction_type in (TransactionType.PURCHASE, TransactionType.LIMITED_CASH_OUT)
    ):
        return config.CONVENTIONAL_MAX_LTV_PRIMARY_1UNIT_ARM_PURCHASE_LCOR
    key = (request.occupancy.value, bucket, request.transaction_type.value)
    if key not in config.CONVENTIONAL_MAX_LTV:
        raise ValueError(f"No conventional max-LTV entry for {key}")
    return config.CONVENTIONAL_MAX_LTV[key]


def _evaluate_conventional(request: QuoteRequest) -> EligibilityResult:
    checks: list[EligibilityCheck] = []

    checks.append(_loan_limit_check(request, config.CONFORMING_LOAN_LIMITS, "Conventional conforming"))

    max_ltv = _conventional_max_ltv(request)
    ltv = request.ltv
    checks.append(EligibilityCheck(
        name="max_ltv",
        passed=ltv <= max_ltv,
        detail=(f"LTV {ltv:.2f}% is within Conventional maximum {max_ltv:.1f}%" if ltv <= max_ltv
                else f"LTV {ltv:.2f}% exceeds Conventional maximum {max_ltv:.1f}%"),
        actual=ltv,
        limit=max_ltv,
    ))

    if request.has_subordinate_financing:
        cltv = request.effective_cltv
        checks.append(EligibilityCheck(
            name="max_cltv",
            passed=cltv <= max_ltv,
            detail=(f"CLTV {cltv:.2f}% is within Conventional maximum {max_ltv:.1f}%" if cltv <= max_ltv
                    else f"CLTV {cltv:.2f}% exceeds Conventional maximum {max_ltv:.1f}%"),
            actual=cltv,
            limit=max_ltv,
        ))

    min_fico = config.LENDER_OVERLAYS["min_fico_conventional"]
    checks.append(EligibilityCheck(
        name="min_fico_overlay",
        passed=request.fico >= min_fico,
        detail=(f"FICO {request.fico} meets lender overlay minimum {min_fico}" if request.fico >= min_fico
                else f"FICO {request.fico} is below lender overlay minimum {min_fico}"),
        actual=request.fico,
        limit=min_fico,
    ))

    dti_status, dti_detail = _dti_conventional(request)

    eligible = all(c.passed for c in checks) and dti_status != "fail"
    return EligibilityResult(program=Program.CONVENTIONAL, eligible=eligible, checks=checks, dti_status=dti_status, dti_detail=dti_detail)


def _dti_conventional(request: QuoteRequest) -> tuple[str, str]:
    cap = config.DTI_CONVENTIONAL_DU_MAX
    if request.dti_back <= cap:
        return "pass", f"DTI {request.dti_back:.1f}% is within DU maximum {cap:.1f}%"
    return "fail", f"DTI {request.dti_back:.1f}% exceeds DU maximum {cap:.1f}%"


def _evaluate_fha(request: QuoteRequest) -> EligibilityResult:
    checks: list[EligibilityCheck] = []

    checks.append(_loan_limit_check(request, config.FHA_LOAN_LIMITS, "FHA"))

    ltv = request.ltv
    if request.transaction_type == TransactionType.CASH_OUT:
        max_ltv = config.FHA_MAX_LTV_CASH_OUT
    elif request.transaction_type == TransactionType.LIMITED_CASH_OUT:
        max_ltv = config.FHA_MAX_LTV_RATE_TERM_REFI
    elif request.fico >= 580:
        max_ltv = config.FHA_MAX_LTV_PURCHASE_FICO_GE_580
    elif request.fico >= config.FHA_MIN_FICO_PURCHASE:
        max_ltv = config.FHA_MAX_LTV_PURCHASE_FICO_500_579
    else:
        checks.append(EligibilityCheck(
            name="min_fico_agency",
            passed=False,
            detail=f"FICO {request.fico} is below FHA absolute floor {config.FHA_MIN_FICO_PURCHASE}",
            actual=request.fico,
            limit=config.FHA_MIN_FICO_PURCHASE,
        ))
        max_ltv = config.FHA_MAX_LTV_PURCHASE_FICO_500_579

    checks.append(EligibilityCheck(
        name="max_ltv",
        passed=ltv <= max_ltv,
        detail=(f"LTV {ltv:.2f}% is within FHA maximum {max_ltv:.2f}%" if ltv <= max_ltv
                else f"LTV {ltv:.2f}% exceeds FHA maximum {max_ltv:.2f}%"),
        actual=ltv,
        limit=max_ltv,
    ))

    min_fico = config.LENDER_OVERLAYS["min_fico_fha"]
    checks.append(EligibilityCheck(
        name="min_fico_overlay",
        passed=request.fico >= min_fico,
        detail=(f"FICO {request.fico} meets lender overlay minimum {min_fico}" if request.fico >= min_fico
                else f"FICO {request.fico} is below lender overlay minimum {min_fico}"),
        actual=request.fico,
        limit=min_fico,
    ))

    dti_status, dti_detail = _dti_fha(request)

    eligible = all(c.passed for c in checks) and dti_status != "fail"
    return EligibilityResult(program=Program.FHA, eligible=eligible, checks=checks, dti_status=dti_status, dti_detail=dti_detail)


def _dti_fha(request: QuoteRequest) -> tuple[str, str]:
    if request.fha_manual_underwrite:
        factors = min(request.fha_compensating_factors, 2)
        front_max, back_max = config.FHA_MANUAL_DTI_TIERS[factors]
        front = request.dti_front if request.dti_front is not None else 0.0
        if front <= front_max and request.dti_back <= back_max:
            return "pass", f"DTI {front:.1f}/{request.dti_back:.1f}% within manual tier {front_max:.0f}/{back_max:.0f} ({factors} compensating factor(s))"
        return "fail", f"DTI {front:.1f}/{request.dti_back:.1f}% exceeds manual tier {front_max:.0f}/{back_max:.0f} ({factors} compensating factor(s))"

    if request.dti_back <= 43.0:
        return "pass", f"Back-end DTI {request.dti_back:.1f}% is within the standard manual tier ceiling of 43.0%"
    if request.dti_back <= config.FHA_TOTAL_AUS_PRACTICAL_MAX:
        return "refer", f"Back-end DTI {request.dti_back:.1f}% exceeds 43.0% but is within TOTAL AUS's practical ceiling of {config.FHA_TOTAL_AUS_PRACTICAL_MAX:.2f}% (no published hard cap) — needs AUS run"
    return "fail", f"Back-end DTI {request.dti_back:.1f}% exceeds TOTAL AUS's practical ceiling of {config.FHA_TOTAL_AUS_PRACTICAL_MAX:.2f}%"


def _evaluate_va(request: QuoteRequest) -> EligibilityResult:
    checks: list[EligibilityCheck] = []

    ltv = request.ltv
    checks.append(EligibilityCheck(
        name="max_ltv",
        passed=ltv <= config.VA_MAX_LTV,
        detail=(f"LTV {ltv:.2f}% is within VA maximum {config.VA_MAX_LTV:.1f}%" if ltv <= config.VA_MAX_LTV
                else f"LTV {ltv:.2f}% exceeds VA maximum {config.VA_MAX_LTV:.1f}%"),
        actual=ltv,
        limit=config.VA_MAX_LTV,
    ))

    min_fico = config.LENDER_OVERLAYS["min_fico_va"]
    checks.append(EligibilityCheck(
        name="min_fico_overlay",
        passed=request.fico >= min_fico,
        detail=(f"FICO {request.fico} meets lender overlay minimum {min_fico}" if request.fico >= min_fico
                else f"FICO {request.fico} is below lender overlay minimum {min_fico}"),
        actual=request.fico,
        limit=min_fico,
    ))

    dti_status, dti_detail = _dti_va(request)

    residual_check = _va_residual_income_check(request)
    if residual_check is not None:
        checks.append(residual_check)
        if not residual_check.passed:
            dti_status = "fail"

    eligible = all(c.passed for c in checks) and dti_status != "fail"
    return EligibilityResult(program=Program.VA, eligible=eligible, checks=checks, dti_status=dti_status, dti_detail=dti_detail)


def _dti_va(request: QuoteRequest) -> tuple[str, str]:
    threshold = config.VA_DTI_SCRUTINY_THRESHOLD
    if request.dti_back <= threshold:
        return "pass", f"DTI {request.dti_back:.1f}% is at or below VA's {threshold:.0f}% scrutiny threshold"
    return "refer", f"DTI {request.dti_back:.1f}% exceeds VA's {threshold:.0f}% scrutiny threshold — residual income test governs"


def _va_residual_income_check(request: QuoteRequest) -> EligibilityCheck | None:
    if request.va_family_size is None or request.va_region is None:
        return None
    if request.va_monthly_gross_income is None or request.va_monthly_obligations is None:
        return None
    if request.loan_amount < config.VA_RESIDUAL_INCOME_MIN_LOAN_AMOUNT:
        return EligibilityCheck(
            name="va_residual_income",
            passed=False,
            detail=(f"Loan amount ${request.loan_amount:,.2f} is below ${config.VA_RESIDUAL_INCOME_MIN_LOAN_AMOUNT:,.0f}; "
                    "the reference file only publishes the residual income table for loans at or above that amount"),
        )

    family_size = request.va_family_size
    if family_size <= config.VA_RESIDUAL_INCOME_MAX_FAMILY_SIZE_TABLE:
        capped_size = min(family_size, max(config.VA_RESIDUAL_INCOME_TABLE))
        required = config.VA_RESIDUAL_INCOME_TABLE[capped_size][request.va_region]
        if family_size > max(config.VA_RESIDUAL_INCOME_TABLE):
            extra = family_size - max(config.VA_RESIDUAL_INCOME_TABLE)
            required += extra * config.VA_RESIDUAL_INCOME_PER_ADDITIONAL_MEMBER
    else:
        extra = family_size - max(config.VA_RESIDUAL_INCOME_TABLE)
        required = config.VA_RESIDUAL_INCOME_TABLE[max(config.VA_RESIDUAL_INCOME_TABLE)][request.va_region]
        required += extra * config.VA_RESIDUAL_INCOME_PER_ADDITIONAL_MEMBER

    penalty_applied = request.dti_back > config.VA_RESIDUAL_INCOME_DTI_PENALTY_THRESHOLD
    if penalty_applied:
        required = round(required * config.VA_RESIDUAL_INCOME_PENALTY_MULTIPLIER, 2)

    actual = request.va_monthly_gross_income - request.va_monthly_obligations
    passed = actual >= required
    penalty_note = f" (20% rule applied: DTI {request.dti_back:.1f}% > {config.VA_RESIDUAL_INCOME_DTI_PENALTY_THRESHOLD:.0f}%)" if penalty_applied else ""
    detail = (f"Residual income ${actual:,.2f}/mo {'meets' if passed else 'is below'} required ${required:,.2f}/mo "
              f"for family size {family_size}, {request.va_region}{penalty_note}")
    return EligibilityCheck(name="va_residual_income", passed=passed, detail=detail, actual=actual, limit=required)


def _evaluate_usda(request: QuoteRequest) -> EligibilityResult:
    checks: list[EligibilityCheck] = []

    ltv = request.ltv
    checks.append(EligibilityCheck(
        name="max_ltv",
        passed=ltv <= config.USDA_MAX_LTV,
        detail=(f"LTV {ltv:.2f}% is within USDA maximum {config.USDA_MAX_LTV:.1f}%" if ltv <= config.USDA_MAX_LTV
                else f"LTV {ltv:.2f}% exceeds USDA maximum {config.USDA_MAX_LTV:.1f}%"),
        actual=ltv,
        limit=config.USDA_MAX_LTV,
    ))

    min_fico = config.LENDER_OVERLAYS["min_fico_usda"]
    checks.append(EligibilityCheck(
        name="min_fico_overlay",
        passed=request.fico >= min_fico,
        detail=(f"FICO {request.fico} meets lender overlay minimum {min_fico}" if request.fico >= min_fico
                else f"FICO {request.fico} is below lender overlay minimum {min_fico}"),
        actual=request.fico,
        limit=min_fico,
    ))

    dti_status, dti_detail = _dti_usda(request)

    eligible = all(c.passed for c in checks) and dti_status == "pass"
    return EligibilityResult(program=Program.USDA, eligible=eligible, checks=checks, dti_status=dti_status, dti_detail=dti_detail)


def _dti_usda(request: QuoteRequest) -> tuple[str, str]:
    front = request.dti_front if request.dti_front is not None else 0.0
    front_max, back_max = config.USDA_DTI_RATIOS
    if front <= front_max and request.dti_back <= back_max:
        return "pass", f"DTI {front:.1f}/{request.dti_back:.1f}% within USDA guideline ratios {front_max:.0f}/{back_max:.0f}"
    if request.usda_gus_accept:
        return "refer", f"DTI {front:.1f}/{request.dti_back:.1f}% exceeds {front_max:.0f}/{back_max:.0f} but GUS Accept waives the ratio — needs AUS confirmation"
    return "fail", f"DTI {front:.1f}/{request.dti_back:.1f}% exceeds USDA guideline ratios {front_max:.0f}/{back_max:.0f}"
