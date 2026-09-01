"""
Plain-English scenario intake — the ONLY place a language model touches this
project, and it enters at exactly one point: turning prose into a
QuoteRequest. It never touches a number that ends up in a quote; every
number QuoteRequest carries either came verbatim from the borrower's text or
is disclosed, with a reason, in the assumptions list.

THREE RESOLUTION PATHS, always labelled in the result:
    live      real Claude API call
    cache     replay of a previous live call, keyed on a hash of the input
    fallback  deterministic regex/keyword parser — used when there is no
              API key and no cache entry, so the app runs with no network
              and no key. This is NOT the model in disguise: it is a
              separate, weaker code path, and it says so everywhere it
              surfaces.

Resolution order: cache, then live (if ANTHROPIC_API_KEY is set), then
fallback. A live failure degrades to fallback rather than raising; the
failure reason goes in `notes`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from . import config
from .models import Occupancy, Program, PropertyType, QuoteRequest, TransactionType

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

CACHE_PATH = PROJECT_ROOT / "data" / "extraction_cache.json"
CONFIDENCE_THRESHOLD = 0.85
CLAUDE_MODEL = "claude-opus-5"

# One key per QuoteRequest-adjacent field Claude/the fallback parser attempt
# to fill. Not all of these exist on QuoteRequest itself (state, county,
# self_employed, first_time_buyer, va_eligible) — those are captured for a
# human reviewer but are not consumed by the deterministic engine, since
# nothing in eligibility.py/pricing.py/costs.py models them today.
EXTRACTION_FIELDS = [
    "purchase_price", "loan_amount", "down_payment", "down_payment_pct",
    "fico", "occupancy", "property_type", "units", "purpose", "program",
    "term_years", "state", "county", "self_employed", "first_time_buyer",
    "va_eligible", "va_first_use", "monthly_income", "monthly_debts", "lock_days",
]


@dataclass
class Assumption:
    field: str
    assumed_value: object
    reason: str


@dataclass
class ExtractionResult:
    source: str  # "live" | "cache" | "fallback"
    confidence: float
    fields: dict[str, object]
    assumptions: list[Assumption] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    @property
    def provisional(self) -> bool:
        return self.confidence < CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def extract(text: str, *, force_live: bool = False) -> ExtractionResult:
    """Resolution order: cache -> live (if key present) -> fallback.

    force_live=True bypasses the cache lookup (but a successful live call is
    still written to the cache). A live call that fails for any reason
    degrades to fallback rather than raising; the reason lands in `notes`.
    """
    cache_key = _hash_text(text)

    if not force_live:
        cached = _cache_lookup(cache_key)
        if cached is not None:
            return _build_result(cached, source="cache")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            payload = _extract_live(text, api_key)
        except Exception as exc:
            fallback_payload = _extract_fallback(text)
            failure_note = f"Live extraction failed ({exc}); used fallback parser instead."
            fallback_payload["notes"] = (failure_note + " " + fallback_payload.get("notes", "")).strip()
            return _build_result(fallback_payload, source="fallback")
        _cache_store(cache_key, payload)
        return _build_result(payload, source="live")

    return _build_result(_extract_fallback(text), source="fallback")


def _build_result(payload: dict, *, source: str) -> ExtractionResult:
    assumptions = [Assumption(**a) for a in payload.get("assumptions", [])]
    return ExtractionResult(
        source=source,
        confidence=float(payload.get("confidence", 0.0)),
        fields={k: payload.get("fields", {}).get(k) for k in EXTRACTION_FIELDS},
        assumptions=assumptions,
        evidence=dict(payload.get("evidence", {})),
        notes=payload.get("notes", "") or "",
    )


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _cache_lookup(key: str) -> dict | None:
    return _load_cache().get(key)


def _cache_store(key: str, payload: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = _load_cache()
    cache[key] = payload
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Live path (Claude)
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "object",
            "properties": {
                "purchase_price": {"type": ["number", "null"]},
                "loan_amount": {"type": ["number", "null"]},
                "down_payment": {"type": ["number", "null"]},
                "down_payment_pct": {"type": ["number", "null"]},
                "fico": {"type": ["integer", "null"]},
                "occupancy": {"type": ["string", "null"], "enum": ["primary", "second_home", "investment", None]},
                "property_type": {"type": ["string", "null"], "enum": ["sfr_detached", "condo", "manufactured", None]},
                "units": {"type": ["integer", "null"]},
                "purpose": {"type": ["string", "null"], "enum": ["purchase", "limited_cash_out", "cash_out", None]},
                "program": {"type": ["string", "null"], "enum": ["conventional", "fha", "va", "usda", None]},
                "term_years": {"type": ["integer", "null"]},
                "state": {"type": ["string", "null"]},
                "county": {"type": ["string", "null"]},
                "self_employed": {"type": ["boolean", "null"]},
                "first_time_buyer": {"type": ["boolean", "null"]},
                "va_eligible": {"type": ["boolean", "null"]},
                "va_first_use": {"type": ["boolean", "null"]},
                "monthly_income": {"type": ["number", "null"]},
                "monthly_debts": {"type": ["number", "null"]},
                "lock_days": {"type": ["integer", "null"]},
            },
            "required": EXTRACTION_FIELDS,
            "additionalProperties": False,
        },
        "confidence": {"type": "number"},
        "assumptions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "assumed_value": {},
                    "reason": {"type": "string"},
                },
                "required": ["field", "assumed_value", "reason"],
                "additionalProperties": False,
            },
        },
        "evidence": {"type": "object", "additionalProperties": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["fields", "confidence", "assumptions", "evidence", "notes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""You turn a free-text mortgage borrower scenario into structured fields for a \
deterministic pricing engine. You never compute a price, rate, or eligibility \
decision yourself — you only extract what the text says and honestly flag what \
you had to guess.

Fields to extract: {", ".join(EXTRACTION_FIELDS)}.
occupancy in {{primary, second_home, investment}}. property_type in \
{{sfr_detached, condo, manufactured}}. purpose in {{purchase, limited_cash_out, \
cash_out}}. program in {{conventional, fha, va, usda}}.

Rules:
- Set a field to null if the text genuinely does not address it. Do not invent
  a value and place it in `fields` as if stated — every filled gap must also
  appear in `assumptions` with the field, the value you chose, and why.
- Exception: fico, occupancy, property_type, purpose, program, term_years, and
  lock_days are needed to produce any quote at all. If one of these is truly
  unstated, fill it with a reasonable default (fico=700, occupancy=primary,
  property_type=sfr_detached, purpose=purchase, program=conventional,
  term_years=30, lock_days=30) AND record it in `assumptions` with that exact
  reasoning — never leave these seven null. Every other field (state, county,
  self_employed, first_time_buyer, va_eligible, monthly_income,
  monthly_debts, down_payment/down_payment_pct) may stay null when genuinely
  absent — do not manufacture a value for those just to fill the field.
- `evidence` maps a field name to the exact phrase from the input that supports
  it, but ONLY for fields the borrower actually stated — never for assumed
  fields.
- `confidence` is 0.0-1.0 for the extraction as a whole. Be honest and
  conservative: a scenario with several unstated required fields should not
  score above ~0.7-0.8; a scenario with a genuine ambiguity should score lower
  still.
- TOWNHOUSE TRAP: "townhouse" does not by itself tell you condo vs. non-condo,
  and that distinction is a 0.750 point difference in this engine's pricing.
  If the text says "townhouse" (or similar), you must still choose a
  property_type value to unblock a quote, but it MUST be recorded in
  `assumptions` with a reason naming the ambiguity and the point exposure —
  never place it in `evidence` as if the borrower stated the LLPA category.
- BARE DOLLAR FIGURE TRAP: if the text gives one unlabeled dollar figure and
  there is no anchor word ("price", "loan amount", "borrowing", "purchasing a
  ___ home") and no down-payment percentage to triangulate from, do not
  silently decide whether it's purchase_price or loan_amount. Make your best
  guess (most scenarios describing "a $X place/home" mean purchase price), but
  record it as an assumption, say so plainly in `notes`, and lower confidence.
- FICO PROXIMITY TRAP: if credit score is given approximately ("around",
  "about", "~", "roughly") or the number sits within about 10-15 points of a
  pricing band edge, say so explicitly in `notes` — a 20-point swing near a
  boundary changes the price materially, and the reviewer needs to see that
  risk even though you still extracted a number.
- Never let an assumed value read as something the borrower said. `notes` is
  one sentence for a human reviewer, or an empty string if there's nothing to
  flag beyond what's already in `assumptions`.

Respond with ONLY the JSON object matching the required schema."""


def _extract_live(text: str, api_key: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    )
    raw_text = next(b.text for b in response.content if b.type == "text")
    return json.loads(raw_text)


# ---------------------------------------------------------------------------
# Fallback path — deterministic regex/keyword parser.
#
# NOT the model in disguise: no fuzzy matching, no cross-sentence reasoning,
# no geocoding. Every rule below is a fixed regex or keyword lookup, and the
# things it cannot do are documented next to the rule that doesn't do them.
# ---------------------------------------------------------------------------

_HEDGE_WORDS = re.compile(r"\b(around|about|approx(?:imately)?|roughly|~)\b", re.IGNORECASE)

# A "money-shaped" number: needs a $ sign, comma-grouped thousands, or a
# k/thousand suffix — never a bare 2-3 digit number. Without this, a FICO
# score or a loan term ("730", "30") would false-positive as a dollar figure.
_MONEY = r"\$\s*[\d,]+(?:\.\d+)?|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\s*(?:k|K|thousand)\b"


def _money_value(matched_text: str) -> float:
    suffix_k = bool(re.search(r"(?:k|thousand)\s*$", matched_text, re.IGNORECASE))
    digits = re.sub(r"[^\d.]", "", matched_text)
    value = float(digits)
    if suffix_k:
        value *= 1000
    return value


def _find_money_near(text: str, keywords: list[str]) -> tuple[float, str] | None:
    """Find a dollar figure whose surrounding words include one of `keywords`.

    Keyword matching is word-boundary based so a keyword like "home" doesn't
    false-positive on a substring inside another word (e.g. "townhome").
    """
    for m in re.finditer(_MONEY, text):
        window = text[max(0, m.start() - 30): m.end() + 20].lower()
        if any(re.search(r"\b" + re.escape(kw) + r"\b", window) for kw in keywords):
            return _money_value(m.group(0)), m.group(0).strip()
    return None


def _find_any_money(text: str) -> list[tuple[float, str, int]]:
    out = []
    for m in re.finditer(_MONEY, text):
        out.append((_money_value(m.group(0)), m.group(0).strip(), m.start()))
    return out


def _extract_fallback(text: str) -> dict:
    fields: dict[str, object] = {k: None for k in EXTRACTION_FIELDS}
    assumptions: list[dict] = []
    evidence: dict[str, str] = {}
    notes: list[str] = []
    stated_required = 0
    total_required = 5  # price/loan, fico, occupancy, property_type, program

    lower = text.lower()

    # --- down payment ---------------------------------------------------
    no_down_match = re.search(r"\bno down ?payment\b|\bno money down\b|\b0\s*%\s*down\b|\bzero down\b", lower)
    pct_match = re.search(r"([\d.]+)\s*%\s*(?:down|dwn)|(?:down|dwn)\D{0,6}([\d.]+)\s*%", lower)
    if no_down_match:
        fields["down_payment_pct"] = 0.0
        evidence["down_payment_pct"] = no_down_match.group(0).strip()
    elif pct_match:
        pct = float(pct_match.group(1) or pct_match.group(2))
        fields["down_payment_pct"] = pct
        evidence["down_payment_pct"] = pct_match.group(0).strip()
    else:
        dp_money = _find_money_near(text, ["down payment", "down pmt", "putting down"])
        if dp_money:
            fields["down_payment"] = dp_money[0]
            evidence["down_payment"] = dp_money[1]

    # --- purchase price vs. loan amount ----------------------------------
    price_hit = _find_money_near(text, ["price", "place", "home", "house", "property", "buying a", "purchasing", "purchase"])
    loan_hit = _find_money_near(text, ["loan amount", "loan of", "borrowing", "loan for"])

    if price_hit:
        fields["purchase_price"] = price_hit[0]
        evidence["purchase_price"] = price_hit[1]
        stated_required += 1
    if loan_hit:
        fields["loan_amount"] = loan_hit[0]
        evidence["loan_amount"] = loan_hit[1]
        stated_required += 1

    if fields["purchase_price"] is None:
        claimed_texts = {t for t in (price_hit[1] if price_hit else None,
                                      loan_hit[1] if loan_hit else None,
                                      evidence.get("down_payment")) if t}
        candidates = [m for m in _find_any_money(text) if m[0] >= 1000 and m[1] not in claimed_texts]

        if loan_hit and len(candidates) == 1:
            # A loan amount is already anchored, and exactly one other dollar
            # figure remains unclaimed — almost certainly the property value,
            # just missing an anchor word (e.g. "$500,000 condo"). Not the
            # genuine price-vs-loan ambiguity below: still an assumption
            # (never silently promoted to "stated"), but a much safer guess.
            value, matched_text, _ = candidates[0]
            fields["purchase_price"] = value
            assumptions.append({
                "field": "purchase_price",
                "assumed_value": value,
                "reason": (
                    f"'{matched_text}' has no explicit 'price'/'value' anchor word, but a loan "
                    "amount was already identified separately, so this remaining figure is "
                    "assumed to be the property value."
                ),
            })
        elif not loan_hit and len(candidates) == 1:
            # No anchor word next to any dollar figure at all. Guess
            # purchase_price (most scenarios describe the property, not the
            # loan) but disclose it — never silently.
            value, matched_text, _ = candidates[0]
            fields["purchase_price"] = value
            assumptions.append({
                "field": "purchase_price",
                "assumed_value": value,
                "reason": (
                    f"'{matched_text}' has no 'price'/'loan amount' anchor word, so it is "
                    "genuinely ambiguous whether this is purchase price or loan amount; "
                    "assumed purchase price as the more common phrasing."
                ),
            })
            notes.append(
                f"'{matched_text}' could be purchase price or loan amount — text does not say which."
            )
        elif len(candidates) > 1:
            notes.append("Multiple unlabeled dollar figures found; could not confidently assign price vs. loan amount.")

    # --- FICO --------------------------------------------------------------
    fico_match = re.search(r"(?:credit(?:'s| score| is| of)?|fico)\D{0,15}?(\d{3})", lower)
    if fico_match:
        fico = int(fico_match.group(1))
        if 300 <= fico <= 850:
            fields["fico"] = fico
            evidence["fico"] = fico_match.group(0).strip()
            stated_required += 1
            hedge = _HEDGE_WORDS.search(text[max(0, fico_match.start() - 15): fico_match.end()])
            boundaries = {b for _, lo, hi in config.FICO_BANDS for b in (lo, hi)}
            near_edge = any(abs(fico - b) <= 15 for b in boundaries)
            if hedge or near_edge:
                notes.append(
                    f"FICO {fico} was given approximately and/or sits close to a pricing band edge — "
                    "a small swing here changes the price materially; confirm the exact score."
                )

    # --- occupancy -----------------------------------------------------
    if re.search(r"\b(primary residence|primary home|owner.?occupied|pri(?:mary)? res)\b", lower):
        fields["occupancy"] = "primary"
        evidence["occupancy"] = "primary residence"
        stated_required += 1
    elif re.search(r"\b(investment|rental|non.?owner)\b", lower):
        fields["occupancy"] = "investment"
        evidence["occupancy"] = "investment"
        stated_required += 1
    elif re.search(r"\b(second home|vacation home)\b", lower):
        fields["occupancy"] = "second_home"
        evidence["occupancy"] = "second home"
        stated_required += 1

    # --- property type (townhouse trap handled explicitly) --------------
    if re.search(r"\b(condo|condominium)\b", lower):
        fields["property_type"] = "condo"
        evidence["property_type"] = "condo"
        stated_required += 1
    elif re.search(r"\b(manufactured|mobile home)\b", lower):
        fields["property_type"] = "manufactured"
        evidence["property_type"] = "manufactured"
        stated_required += 1
    elif re.search(r"\btown\s?house\b|\btown\s?home\b", lower):
        fields["property_type"] = "sfr_detached"
        assumptions.append({
            "field": "property_type",
            "assumed_value": "sfr_detached",
            "reason": (
                "'townhouse' is ambiguous for LLPA purposes (may or may not be condo-classified, "
                "a 0.750 point difference); assumed non-condo (sfr_detached). Confirm with the "
                "borrower before quoting."
            ),
        })
    elif re.search(r"\b(single family|sfr|sfh|detached)\b", lower):
        fields["property_type"] = "sfr_detached"
        evidence["property_type"] = "single family"
        stated_required += 1

    # --- units -----------------------------------------------------------
    unit_words = {"duplex": 2, "triplex": 3, "fourplex": 4, "quadplex": 4}
    for word, n in unit_words.items():
        if word in lower:
            fields["units"] = n
            evidence["units"] = word
            break
    else:
        unit_match = re.search(r"(\d)\s*[- ]unit", lower)
        if unit_match:
            fields["units"] = int(unit_match.group(1))
            evidence["units"] = unit_match.group(0)

    # --- purpose / program ------------------------------------------------
    if re.search(r"\bcash.?out\b", lower):
        fields["purpose"] = "cash_out"
        evidence["purpose"] = "cash-out"
    elif re.search(r"\brefi(?:nance)?\b", lower):
        fields["purpose"] = "limited_cash_out"
        evidence["purpose"] = "refinance"
    elif re.search(r"\b(purchas(?:e|ing)|buying)\b", lower):
        fields["purpose"] = "purchase"
        evidence["purpose"] = "purchase"

    if re.search(r"\bva\b|veteran", lower):
        fields["program"] = "va"
        evidence["program"] = "VA"
        stated_required += 1
        if re.search(r"first.?time|first use|never used", lower):
            fields["va_first_use"] = True
        elif re.search(r"second use|prior va|subsequent use|used.*va.*before", lower):
            fields["va_first_use"] = False
    elif re.search(r"\bfha\b", lower):
        fields["program"] = "fha"
        evidence["program"] = "FHA"
        stated_required += 1
    elif re.search(r"\busda\b|rural", lower):
        fields["program"] = "usda"
        evidence["program"] = "USDA"
        stated_required += 1
    elif re.search(r"\bconventional|conv\b", lower):
        fields["program"] = "conventional"
        evidence["program"] = "conventional"
        stated_required += 1

    # --- term --------------------------------------------------------------
    term_match = re.search(r"(\d{1,2})[- ]?(?:yr|year)s?\b", lower)
    if term_match:
        fields["term_years"] = int(term_match.group(1))
        evidence["term_years"] = term_match.group(0)

    # --- lock --------------------------------------------------------------
    lock_match = re.search(r"(\d{2,3})[- ]?day\s*(?:rate\s*)?lock", lower)
    if lock_match:
        fields["lock_days"] = int(lock_match.group(1))
        evidence["lock_days"] = lock_match.group(0)

    # --- self-employed / first-time buyer / state ------------------------
    if re.search(r"self.?employed|1099|own(?:s)? (?:his|her|their|my) (?:own )?business", lower):
        fields["self_employed"] = True
        evidence["self_employed"] = "self-employed"
    if re.search(r"first.?time (?:buyer|homebuyer|home buyer)|fthb", lower):
        fields["first_time_buyer"] = True
        evidence["first_time_buyer"] = "first-time buyer"

    state_match = re.search(
        r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|"
        r"NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b",
        text,
    )
    if state_match:
        fields["state"] = state_match.group(1)
        evidence["state"] = state_match.group(1)

    county_match = re.search(r"([A-Z][a-zA-Z]+)\s+County", text)
    if county_match:
        fields["county"] = county_match.group(1)
        evidence["county"] = county_match.group(0)
    elif state_match is None:
        notes.append(
            "Fallback parser does not geocode city/place names to state or county — only an "
            "explicit state code or 'X County' phrase is captured."
        )

    # --- income / debts -> rough DTI hint (no math here; see to_quote_request) ---
    income_match = re.search(r"(?:income|makes?|earns?)\D{0,12}(?P<amt>" + _MONEY + r")\s*/?\s*(?:a\s+)?(?:mo|month)", lower)
    if income_match:
        fields["monthly_income"] = _money_value(income_match.group("amt"))
        evidence["monthly_income"] = income_match.group(0).strip()
    debts_match = re.search(r"debts?\D{0,12}(?P<amt>" + _MONEY + r")\s*/?\s*(?:a\s+)?(?:mo|month)", lower)
    if debts_match:
        fields["monthly_debts"] = _money_value(debts_match.group("amt"))
        evidence["monthly_debts"] = debts_match.group(0).strip()

    # --- default the fields a quote genuinely can't be built without ------
    # (FICO, occupancy, property type, purpose, program, term, lock) — each
    # default is disclosed as an assumption right here, not deferred, so the
    # ExtractionResult itself is already complete and honest about every gap
    # it filled, per contract. Price/loan reconciliation, DTI, and VA
    # first-use stay in to_quote_request() since they depend on values
    # derived from other fields, not a fixed default.
    _REQUIRED_DEFAULTS = [
        ("fico", 700, "No credit score stated; assumed 700 (a conservative mid-range placeholder)."),
        ("occupancy", "primary", "No occupancy stated; assumed primary residence (the most common case)."),
        ("property_type", "sfr_detached", "No property type stated; assumed single-family detached."),
        ("purpose", "purchase", "No refinance/cash-out language present; assumed purchase."),
        ("program", "conventional", "No program stated; assumed conventional."),
        ("term_years", 30, "No loan term stated; assumed 30-year fixed."),
        ("lock_days", 30, "No rate lock period stated; assumed 30 days."),
    ]
    for field_name, default_value, reason in _REQUIRED_DEFAULTS:
        if fields[field_name] is None:
            fields[field_name] = default_value
            assumptions.append({"field": field_name, "assumed_value": default_value, "reason": reason})

    # --- confidence ----------------------------------------------------
    confidence = stated_required / total_required
    confidence -= 0.05 * len(assumptions)
    if _HEDGE_WORDS.search(text):
        confidence -= 0.05
    confidence = max(0.0, min(1.0, round(confidence, 2)))

    return {
        "fields": fields,
        "confidence": confidence,
        "assumptions": assumptions,
        "evidence": evidence,
        "notes": " ".join(notes),
    }


# ---------------------------------------------------------------------------
# Mapping ExtractionResult -> QuoteRequest
#
# Shared by every resolution path: the ExtractionResult only carries the raw
# extraction contract; deriving the actual QuoteRequest (loan amount from
# price + down payment, purpose -> TransactionType, etc.) happens here, once,
# so live/cache/fallback all produce a quote the same way.
# ---------------------------------------------------------------------------

class InsufficientDataError(ValueError):
    """Raised when the extraction genuinely lacks enough to build a quote."""


def to_quote_request(result: ExtractionResult) -> QuoteRequest:
    f = dict(result.fields)
    assumptions = list(result.assumptions)

    purchase_price = f.get("purchase_price")
    loan_amount = f.get("loan_amount")
    down_payment = f.get("down_payment")
    down_payment_pct = f.get("down_payment_pct")

    if purchase_price is not None and loan_amount is None:
        if down_payment_pct is not None:
            loan_amount = round(purchase_price * (1 - down_payment_pct / 100), 2)
        elif down_payment is not None:
            loan_amount = round(purchase_price - down_payment, 2)
        else:
            assumptions.append(Assumption("down_payment_pct", 20.0, "No down payment stated; assumed 20% down to derive a loan amount."))
            loan_amount = round(purchase_price * 0.80, 2)
    elif loan_amount is not None and purchase_price is None:
        if down_payment_pct is not None:
            purchase_price = round(loan_amount / (1 - down_payment_pct / 100), 2)
        elif down_payment is not None:
            purchase_price = round(loan_amount + down_payment, 2)
    elif purchase_price is None and loan_amount is None:
        raise InsufficientDataError(
            "Could not determine a purchase price or loan amount from the text — nothing to quote."
        )

    fico = f.get("fico")
    if fico is None:
        assumptions.append(Assumption("fico", 700, "No credit score stated; assumed 700 (a conservative mid-range placeholder)."))
        fico = 700

    occupancy_raw = f.get("occupancy")
    if occupancy_raw is None:
        assumptions.append(Assumption("occupancy", "primary", "No occupancy stated; assumed primary residence (the most common case)."))
        occupancy_raw = "primary"
    occupancy = Occupancy(occupancy_raw)

    property_type_raw = f.get("property_type")
    if property_type_raw is None:
        assumptions.append(Assumption("property_type", "sfr_detached", "No property type stated; assumed single-family detached."))
        property_type_raw = "sfr_detached"
    property_type = PropertyType(property_type_raw)

    purpose_raw = f.get("purpose")
    if purpose_raw is None:
        assumptions.append(Assumption("purpose", "purchase", "No refinance/cash-out language present; assumed purchase."))
        purpose_raw = "purchase"
    transaction_type = TransactionType(purpose_raw)

    program_raw = f.get("program")
    if program_raw is None:
        assumptions.append(Assumption("program", "conventional", "No program stated; assumed conventional."))
        program_raw = "conventional"
    program = Program(program_raw)

    units = f.get("units")
    if units is None:
        units = 1

    term_years = f.get("term_years")
    if term_years is None:
        assumptions.append(Assumption("term_years", 30, "No loan term stated; assumed 30-year fixed."))
        term_years = 30
    term_months = int(term_years) * 12

    lock_days = f.get("lock_days")
    if lock_days is None:
        assumptions.append(Assumption("lock_days", 30, "No rate lock period stated; assumed 30 days."))
        lock_days = 30
    elif int(lock_days) not in config.LOCK_DAY_ADJUSTMENTS:
        assumptions.append(Assumption(
            "lock_days", 30,
            f"Text said a {int(lock_days)}-day lock, but this engine's reference data only prices "
            f"a 30-day lock ({sorted(config.LOCK_DAY_ADJUSTMENTS)}); substituted 30 days rather than "
            "guessing a lock-day adjustment that isn't published."
        ))
        lock_days = 30

    monthly_income = f.get("monthly_income")
    monthly_debts = f.get("monthly_debts")
    if monthly_income and monthly_debts is not None and monthly_income > 0:
        dti_back = round(monthly_debts / monthly_income * 100, 1)
    else:
        assumptions.append(Assumption(
            "dti_back", 0.0,
            "Monthly income/debts not both stated; DTI could not be computed and is left at 0.0 "
            "(this will always pass the DTI gate — confirm actual DTI before relying on eligibility)."
        ))
        dti_back = 0.0

    va_first_use = f.get("va_first_use")
    if program == Program.VA and va_first_use is None:
        assumptions.append(Assumption("va_first_use", True, "VA loan with no prior-use language; assumed first use."))
        va_first_use = True
    if va_first_use is None:
        va_first_use = True

    result.assumptions[:] = assumptions

    return QuoteRequest(
        program=program,
        transaction_type=transaction_type,
        occupancy=occupancy,
        property_type=property_type,
        purchase_price=purchase_price,
        loan_amount=loan_amount,
        fico=int(fico),
        units=int(units),
        term_months=term_months,
        lock_days=int(lock_days),
        dti_back=dti_back,
        va_first_use=bool(va_first_use),
    )
