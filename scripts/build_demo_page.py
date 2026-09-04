"""
Generate docs/demo.html — a single self-contained interactive page.

Everything on that page comes out of this repo: the LLPA grids and caps are read
straight from engine/config.py, the scenarios are run through the real extraction
and pricing path, and the test list is parsed from tests/.

The page recomputes pricing in the browser so the controls are live. That means
the math exists in two places, which is a real risk, so this script also prices a
set of parity cases with the Python engine and embeds the expected results. The
page re-prices them on load and shows a pass/fail badge in the footer. If the two
ever drift apart, the page says so instead of quietly lying.

    python scripts/build_demo_page.py

Open docs/demo.html by double-clicking it. No server, no network, no API key.
"""

import ast
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import engine.config as C  # noqa: E402
from engine import extraction, quote  # noqa: E402
from engine.models import (Occupancy, Program, PropertyType,  # noqa: E402
                           QuoteRequest, TransactionType)


# ---------------------------------------------------------------------------
# The build log. Hand-written on purpose — this is the part of the page that is
# judgement rather than generated output, so it lives here in plain sight rather
# than being scraped out of git.
# ---------------------------------------------------------------------------

BUILD_LOG = [
    {
        "kind": "design",
        "title": "The model reads. The rules decide.",
        "where": "engine/extraction.py vs engine/pricing.py",
        "body": [
            "Extraction and eligibility look like one problem and are not. Reading a "
            "paystub or a loan officer's text message is hard for code and easy for a "
            "model — there is no schema and every source formats differently. Deciding "
            "whether a DTI passes is the reverse: there is a right answer, it comes from "
            "a published limit, and it has to be the same answer every time.",
            "So the model is confined to one function. Nothing downstream of extraction "
            "calls it. Every number in a quote comes from ordinary code comparing inputs "
            "to thresholds in config.py, which means any quote can be explained by naming "
            "a matrix, an effective date, and a cell.",
            "There is a regulatory argument as well as an engineering one. CFPB Circular "
            "2023-03 requires creditors to give specific and accurate reasons for credit "
            "decisions even when they use complex algorithms that make those reasons hard "
            "to identify. Model complexity is not a defense.",
        ],
    },
    {
        "kind": "design",
        "title": "Thresholds are configuration, not code",
        "where": "engine/config.py",
        "body": [
            "Program limits, LTV caps, DTI ceilings, MI factors, the extraction confidence "
            "floor and the lender overlays all live in one file, separate from the rule "
            "logic that reads them. Lender overlays in particular are kept structurally "
            "apart from agency rules, because that is the distinction a real shop draws.",
            "The reason is operational. The person who owns these numbers works in "
            "operations, not engineering. If changing a guideline requires a deploy, the "
            "change does not happen on time.",
        ],
    },
    {
        "kind": "caught",
        "title": "A kink in the rate sheet, hiding behind a passing test",
        "where": "engine/config.py — BASE_PRICE_TABLE",
        "body": [
            "The first build anchored the base price at 6.500% so the worked-example "
            "assertion came out to exactly $500. That made the test pass and left a 0.875 "
            "step between 6.375% and 6.500% where every neighbouring step was about 0.500.",
            "On screen it read as borrower cost dropping from $4,000 to $500 across one "
            "eighth of a point — a $3,500 swing where every other step moved about $2,000. "
            "No test caught it because no test asserted anything about the shape of the "
            "curve. I found it by reading the column.",
            "Re-anchored the whole table so it tapers smoothly from the middle outward, "
            "0.500 near par down to 0.400 at the edges, while still landing the two exact "
            "assertions the tests pin.",
        ],
    },
    {
        "kind": "caught",
        "title": "A cache builder that reported success while writing nothing",
        "where": "scripts/build_extraction_cache.py",
        "body": [
            "The script printed “calling Claude” for each scenario, then “Entries: 0”, then "
            "exited zero. It looked like a completed run. It had made no API calls at all.",
            "Two faults stacked. It was calling the cache-or-fallback path instead of forcing "
            "a live call, so it silently resolved to the regex fallback every time. And when "
            "a live call did fail, the reason went into a notes field nothing ever printed.",
            "The fix was less about the call path than about the reporting: print the path "
            "actually taken rather than the one intended, surface the exception immediately, "
            "and exit non-zero on an empty cache. A script that reports zero results as "
            "success is worse than one that crashes.",
        ],
    },
    {
        "kind": "caught",
        "title": "$450k parsed as $450",
        "where": "engine/extraction.py — fallback money parser",
        "body": [
            "The fallback parser tried the plain-digits alternative before the suffix-bearing "
            "one, so “$450k” matched “$450” and dropped three orders of magnitude. “$1.2M” "
            "was not recognised at all.",
            "Quietly wrong, not loudly broken — the parser returned a number, just the wrong "
            "one. Fixed by ordering the suffix forms first, and covered with tests for "
            "$450,000, $450000, $450k, 450k and $1.2M.",
        ],
    },
    {
        "kind": "caught",
        "title": "One dollar figure claimed by two fields",
        "where": "engine/extraction.py — price vs loan amount",
        "body": [
            "Found while fixing the money regex. Price and loan amount were located by two "
            "independent searches, so a single figure sitting near both a price word and a "
            "loan word was assigned to both — producing a scenario with a purchase price and "
            "a loan amount that were the same number, and an LTV of 100%.",
            "Replaced with a single pass that classifies each figure by whichever anchor word "
            "is nearest within the same clause. When no anchor is nearby it is treated as the "
            "price and an assumption is recorded saying so, rather than guessed silently.",
        ],
    },
    {
        "kind": "design",
        "title": "Assumptions are shown separately from stated values",
        "where": "engine/extraction.py — the assumptions array",
        "body": [
            "Real scenario descriptions are incomplete. Someone writes “credit like 705” and "
            "never mentions the lock period, the term, or whether a townhouse should price as "
            "a condo — which is a 0.750 point difference on its own.",
            "The model has to fill those gaps to produce a quote at all. So every gap it "
            "filled is listed separately from what it read, with the reason it chose that "
            "value, and the whole quote is marked provisional when confidence falls below "
            "the threshold in config.",
            "An assumed value that looks like a stated one is how a quote ends up wrong in a "
            "way nobody catches until the borrower is at the closing table.",
        ],
    },
    {
        "kind": "design",
        "title": "It refuses rather than guessing",
        "where": "engine/quote.py",
        "body": [
            "Given a sentence with one dollar figure and no way to tell whether it is the "
            "purchase price or the loan amount, the engine declines to build a quote and "
            "says what is missing.",
            "A system that quietly guesses is more dangerous than one that admits it cannot "
            "tell, because a confident guess is indistinguishable from a real answer "
            "everywhere downstream of it.",
        ],
    },
]


# ---------------------------------------------------------------------------

def field_label(name: str) -> str:
    return name.replace("_", " ")


def value_str(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, int) and v >= 10000:
            return f"{v:,}"
        return str(v)
    return str(v)


def run_scenarios():
    """Extract + quote every scenario in examples/scenarios.txt."""
    lines = [
        ln.strip()
        for ln in (ROOT / "examples" / "scenarios.txt").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    out = []
    for text in lines:
        result = extraction.extract(text)
        fields = result.fields or {}
        evidence = result.evidence or {}
        assumptions = result.assumptions or []
        assumed_names = {a.field for a in assumptions}

        stated = [
            {"k": field_label(k), "v": value_str(v),
             "ev": (evidence.get(k) if isinstance(evidence, dict) else None) or ""}
            for k, v in fields.items()
            if v not in (None, "") and k not in assumed_names
        ]
        assumed = [
            {"k": field_label(a.field), "v": value_str(a.assumed_value), "why": a.reason}
            for a in assumptions
        ]

        quoted, eligible, outcome = False, None, ""
        try:
            req = extraction.to_quote_request(result)
            res = quote.generate_quote(req)
            eligible = bool(getattr(res.eligibility, "eligible", False))
            quoted = True
            if eligible and res.rate_stack:
                par = next((r for r in res.rate_stack if getattr(r, "is_par_row", False)),
                           res.rate_stack[0])
                total = sum(a.amount_in_points for a in res.adjustments)
                cost = par.points_or_credit_dollars
                side = (f"the borrower pays {abs(cost):,.0f} in points"
                        if cost > 0 else f"the borrower receives a {abs(cost):,.0f} credit")
                outcome = (f"Eligible. {total:.3f} points of adjustment. At the par rate of "
                           f"{par.rate:.3f}%, {side}, with a monthly payment of "
                           f"{par.total_monthly_payment:,.0f}.")
            else:
                failed = [c for c in getattr(res.eligibility, "checks", []) if not c.passed]
                outcome = ("Ineligible. " + " ".join(c.detail for c in failed)) if failed \
                    else "Ineligible as submitted."
        except Exception as exc:  # noqa: BLE001
            outcome = (f"No quote produced. {exc}")

        status = ("Quoted" if (quoted and eligible)
                  else "Ineligible" if quoted else "No quote")
        out.append({
            "text": text, "stated": stated, "assumed": assumed,
            "source": result.source,
            "confidence": result.confidence,
            "quoted": quoted, "eligible": eligible,
            "status": status, "outcome": outcome,
        })
    return out


def parity_cases():
    """Price a spread of scenarios with the Python engine for the browser to check."""
    specs = [
        ("745 / 80% / primary SFR purchase", dict(fico=745, price=500_000, down=20.0)),
        ("780 / 95% / primary SFR purchase", dict(fico=780, price=400_000, down=5.0)),
        ("680 / 75% / investment condo", dict(fico=680, price=350_000, down=25.0,
                                              occ="investment", prop="condo")),
        ("700 / 90% / second home", dict(fico=700, price=600_000, down=10.0, occ="second_home")),
        ("660 / 80.0% exactly — band edge", dict(fico=660, price=300_000, down=20.0)),
        ("720 / high-balance purchase", dict(fico=720, price=1_000_000, down=12.0)),
        ("640 / 3-unit primary", dict(fico=640, price=700_000, down=20.0, units=3)),
        ("760 / ARM at 95%", dict(fico=760, price=450_000, down=5.0, arm=True)),
    ]
    cases = []
    for label, s in specs:
        price = s["price"]
        loan = round(price * (1 - s["down"] / 100))
        req = QuoteRequest(
            program=Program.CONVENTIONAL,
            transaction_type=TransactionType(s.get("txn", "purchase")),
            occupancy=Occupancy(s.get("occ", "primary")),
            property_type=PropertyType(s.get("prop", "sfr_detached")),
            purchase_price=float(price), loan_amount=float(loan),
            appraised_value=float(price), fico=s["fico"],
            units=s.get("units", 1), term_months=360,
            is_arm=s.get("arm", False), lock_days=30,
        )
        res = quote.generate_quote(req)
        par = next((r for r in res.rate_stack if getattr(r, "is_par_row", False)),
                   res.rate_stack[0])
        cases.append({
            "label": label,
            "in": {"txn": s.get("txn", "purchase"), "price": price, "down": s["down"],
                   "fico": s["fico"], "occ": s.get("occ", "primary"),
                   "prop": s.get("prop", "sfr_detached"), "units": s.get("units", 1),
                   "arm": s.get("arm", False)},
            "expect": {
                "llpa": round(sum(a.amount_in_points for a in res.adjustments), 6),
                "par_price": round(par.final_price, 3),
            },
        })
    return cases


def collect_tests():
    """Parse test names and one-line docstrings out of tests/ without running them."""
    groups = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        items = []

        def walk(nodes):
            for n in nodes:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
                    doc = ast.get_docstring(n) or ""
                    items.append({"name": n.name,
                                  "doc": " ".join(doc.split())[:180]})
                elif isinstance(n, ast.ClassDef):
                    walk(n.body)

        walk(tree.body)
        if items:
            groups.append({"file": f"tests/{path.name}", "items": items})
    return groups


def limits_table():
    conv = C.CONFORMING_LOAN_LIMITS[1]
    rows = [
        ("Conforming limit, 1 unit", f"${conv['baseline']:,}", "FHFA, 2026"),
        ("High-cost ceiling, 1 unit", f"${conv['ceiling']:,}", "FHFA, 2026"),
        ("Conventional max LTV — primary purchase",
         f"{C.CONVENTIONAL_MAX_LTV[('primary', 1, 'purchase')]:.1f}%", "Fannie Eligibility Matrix"),
        ("Conventional max LTV — cash-out",
         f"{C.CONVENTIONAL_MAX_LTV[('primary', 1, 'cash_out')]:.1f}%", "Fannie Eligibility Matrix"),
        ("Max DTI — DU", f"{C.DTI_CONVENTIONAL_DU_MAX * 100:.0f}%", "Selling Guide B3-6-02"),
        ("Max DTI — manual", f"{C.DTI_CONVENTIONAL_MANUAL_MAX * 100:.0f}%", "Selling Guide B3-6-02"),
        ("FHA UFMIP", f"{C.FHA_UFMIP_RATE * 100:.2f}%", "ML 2023-05"),
        ("FHA max LTV — cash-out", f"{C.FHA_MAX_LTV_CASH_OUT:.1f}%", "HUD 4000.1"),
        ("VA max LTV", f"{C.VA_MAX_LTV:.1f}%", "VA lender handbook"),
        ("PMI auto-terminates at", f"{C.PMI_AUTO_TERMINATE_LTV:.0f}% LTV", "Homeowners Protection Act"),
        ("Lender overlay — min FICO",
         str(C.LENDER_OVERLAYS["min_fico_conventional"]), "Lender overlay, not agency"),
    ]
    return [{"k": k, "v": v, "s": s} for k, v, s in rows]


def main() -> int:
    print("Reading grids from engine/config.py ...")
    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fico_bands": [list(b) for b in C.FICO_BANDS],
        "ltv_bands": [list(b) for b in C.LTV_BANDS],
        "llpa": {
            "purchase": C.LLPA_PURCHASE,
            "limited_cash_out": C.LLPA_LIMITED_CASH_OUT,
            "cash_out": C.LLPA_CASH_OUT,
        },
        "adders": C.LLPA_PURCHASE_ADDERS,
        "manufactured_flat": C.LLPA_MANUFACTURED_HOME_FLAT,
        "llpa_source": "Fannie Mae LLPA Matrix, eff. 01/28/2026",
        # Parallel arrays, deliberately. Keying this by the rate as a string breaks:
        # Python writes 7.0 as "7.0" and JavaScript reads the number 7.0 back as "7",
        # so those rows silently look up undefined. The parity check caught it.
        "rates": sorted(C.BASE_PRICE_TABLE),
        "base_price": [C.BASE_PRICE_TABLE[r] for r in sorted(C.BASE_PRICE_TABLE)],
        "conforming": {str(k): v for k, v in C.CONFORMING_LOAN_LIMITS.items()},
        "max_ltv": {f"{o}|{u}|{t}": v for (o, u, t), v in C.CONVENTIONAL_MAX_LTV.items()},
        "overlays": C.LENDER_OVERLAYS,
        "pmi": C.PMI_MONTHLY_FACTORS,
        "pmi_ltv_bands": [list(b) for b in C.PMI_LTV_BANDS],
        "pmi_fico_cols": C._PMI_FICO_COLS,
        "limits": limits_table(),
    }

    print("Running scenarios through extraction + pricing ...")
    data["scenarios"] = run_scenarios()
    srcs = {s["source"] for s in data["scenarios"]}
    print(f"  extraction sources: {', '.join(sorted(srcs))}")
    if srcs == {"fallback"}:
        print("  NOTE: no cache and no API key, so these are fallback extractions.")
        print("        Run scripts/build_extraction_cache.py first for real model output.")

    print("Pricing parity cases with the Python engine ...")
    data["parity"] = parity_cases()

    print("Parsing tests ...")
    data["tests"] = collect_tests()
    n_tests = sum(len(g["items"]) for g in data["tests"])
    print(f"  {n_tests} tests across {len(data['tests'])} files")

    data["log"] = BUILD_LOG

    tpl = (ROOT / "scripts" / "demo_template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/", json.dumps(data, separators=(",", ":")))

    out = ROOT / "docs" / "demo.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    kb = out.stat().st_size / 1024
    print(f"\nWrote {out}  ({kb:,.0f} KB)")
    print("Open it by double-clicking. No server, no network, no API key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
