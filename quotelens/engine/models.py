"""Data shapes shared across the engine. No pricing logic lives here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Program(str, Enum):
    CONVENTIONAL = "conventional"
    FHA = "fha"
    VA = "va"
    USDA = "usda"


class Occupancy(str, Enum):
    PRIMARY = "primary"
    SECOND_HOME = "second_home"
    INVESTMENT = "investment"


class TransactionType(str, Enum):
    PURCHASE = "purchase"
    LIMITED_CASH_OUT = "limited_cash_out"
    CASH_OUT = "cash_out"


class PropertyType(str, Enum):
    SFR_DETACHED = "sfr_detached"
    CONDO = "condo"
    MANUFACTURED = "manufactured"


@dataclass
class QuoteRequest:
    program: Program
    transaction_type: TransactionType
    occupancy: Occupancy
    property_type: PropertyType

    purchase_price: float | None  # None for refinances
    loan_amount: float
    appraised_value: float | None = None  # used for refi LTV when no purchase_price

    fico: int = 0
    units: int = 1
    term_months: int = 360
    is_arm: bool = False
    lock_days: int = 30

    cltv: float | None = None  # None => no subordinate financing (CLTV == LTV)

    dti_front: float | None = None
    dti_back: float = 0.0

    fha_manual_underwrite: bool = False
    fha_compensating_factors: int = 0  # 0, 1, or 2 ("2+")

    usda_gus_accept: bool = False

    va_first_use: bool = True
    va_exempt: bool = False
    va_down_payment_pct: float = 0.0
    va_is_irrrl: bool = False

    va_family_size: int | None = None
    va_region: str | None = None  # "northeast" | "midwest" | "south" | "west"
    va_monthly_gross_income: float | None = None
    va_monthly_obligations: float | None = None  # PITI + debts + maintenance/utilities

    @property
    def value_basis(self) -> float:
        """The value LTV is computed against: purchase price, or appraised value for a refi."""
        if self.purchase_price is not None:
            return self.purchase_price
        if self.appraised_value is not None:
            return self.appraised_value
        raise ValueError("QuoteRequest needs purchase_price or appraised_value")

    @property
    def ltv(self) -> float:
        return round(self.loan_amount / self.value_basis * 100, 3)

    @property
    def effective_cltv(self) -> float:
        return self.cltv if self.cltv is not None else self.ltv

    @property
    def has_subordinate_financing(self) -> bool:
        return self.cltv is not None and self.cltv > self.ltv


@dataclass
class EligibilityCheck:
    name: str
    passed: bool
    detail: str  # e.g. "LTV 98.5% exceeds Conventional maximum 97.0%"
    actual: float | None = None
    limit: float | None = None


@dataclass
class EligibilityResult:
    program: Program
    eligible: bool
    checks: list[EligibilityCheck] = field(default_factory=list)
    dti_status: str = "pass"  # "pass" | "fail" | "refer"
    dti_detail: str = ""

    def failures(self) -> list[EligibilityCheck]:
        return [c for c in self.checks if not c.passed]


@dataclass
class Adjustment:
    name: str
    category: str  # "llpa_base" | "llpa_adder" | "lock_adjustment"
    amount_in_points: float  # positive = subtracted from price (costs the borrower)
    source: str


@dataclass
class RateOption:
    rate: float
    base_price: float
    final_price: float
    points_or_credit_dollars: float  # positive = borrower pays, negative = lender credit
    monthly_pi: float
    monthly_mi: float
    total_monthly_payment: float
    is_par_row: bool = False


@dataclass
class CostBreakdown:
    upfront_fee_name: str | None = None
    upfront_fee_amount: float = 0.0
    final_loan_amount: float = 0.0  # loan_amount + financed upfront fee, if any
    breakeven_months: float | None = None


@dataclass
class QuoteResult:
    request: QuoteRequest
    eligibility: EligibilityResult
    rate_stack: list[RateOption] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)  # waterfall for the par row (conventional only)
    costs: CostBreakdown = field(default_factory=CostBreakdown)
