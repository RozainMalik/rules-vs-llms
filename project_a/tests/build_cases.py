"""
Builds project_a/tests/cases.json — the FY 2024-25 test suite (Task 1).

  * EDGE cases: hand-chosen, on both sides of every threshold and cap
  * RANDOM cases: seeded, so the file is identical on every run
Expected values come from tests/oracle.py (independent of the engine).

Also creates official_checks.csv (30 cases for you to enter into the official
Income Tax Department calculator). It is NEVER overwritten once it exists,
because it holds your manual results.

Run:  python -m project_a.tests.build_cases [2024-25|2025-26]
"""

import csv
import json
import random
from fractions import Fraction
from pathlib import Path

from project_a.tests.oracle import oracle

HERE = Path(__file__).resolve().parent
FIELDS = ["gross_salary", "age", "hra_received", "basic_plus_da", "rent_paid",
          "rent_city_is_metro", "home_loan_interest", "sec_80c", "sec_80ccd_1b",
          "health_ins_self", "health_ins_parents", "parents_senior"]


def full(**kw) -> dict:
    """A complete input: every field stated (0/False), so no clarification."""
    base = {f: 0 for f in FIELDS}
    base.update(age=30, rent_city_is_metro=False, parents_senior=False)
    base.update(kw)
    return base


NEW_THRESHOLDS = {"2024-25": [300000, 700000, 1000000, 1200000, 1500000],
                  "2025-26": [400000, 800000, 1200000, 1600000, 2000000, 2400000]}
# 87A marginal-relief zone: relief ends where slab tax == income above the limit
REBATE_ZONE = {"2024-25": [705000, 710000, 715000, 722220, 722230, 725000, 750000],
               "2025-26": [1205000, 1210000, 1250000, 1270580, 1270590, 1275000, 1300000]}


def edge_cases(fy: str = "2024-25") -> list[tuple[str, str, dict]]:
    cases: list[tuple[str, str, dict]] = []
    add = lambda cat, desc, inp: cases.append((cat, desc, inp))

    # --- total-income thresholds, NEW regime (gross = TI + 75,000 SD) ---------
    for t in NEW_THRESHOLDS[fy] + [5000000, 10000000, 20000000, 50000000]:
        for d in (-10, 0, 1, 5, 10):          # +1 rounds down, +5 rounds up (Sec 288A)
            add("threshold_new", f"new-regime TI {t}{d:+d}", full(gross_salary=t + d + 75000))

    # --- total-income thresholds, OLD regime (gross = TI + 50,000 SD) ---------
    for t in [250000, 500000, 1000000, 5000000, 10000000, 20000000, 50000000]:
        for d in (-10, 0, 10):
            add("threshold_old", f"old-regime TI {t}{d:+d}", full(gross_salary=t + d + 50000))

    # --- 87A marginal relief zone (new regime) --------------------------------
    for ti in REBATE_ZONE[fy]:
        add("rebate_87a_relief", f"new-regime TI {ti}", full(gross_salary=ti + 75000))

    # --- surcharge marginal-relief zones --------------------------------------
    for t in [5000000, 10000000, 20000000, 50000000]:
        for d in (1000, 50000, 200000, 1000000):
            add("surcharge_relief", f"TI {t}+{d} (both regimes)", full(gross_salary=t + d + 50000))

    # --- Sec 288B: unrounded tax ends in 4.50-4.99 -> paise must be DROPPED -------
    # (rounding paise up first gives a result Rs 10 too high; found when a compiled
    #  module regressed on this while passing every other edge case)
    for regime in ("new", "old"):
        found, g = 0, 1_500_000
        while found < 3:
            g += 10
            r = oracle(full(gross_salary=g), fy)["raw_" + regime]
            whole = r.numerator // r.denominator
            if whole % 10 == 4 and r - whole >= Fraction(1, 2):
                add("rounding_288b", f"{regime}: unrounded tax {float(r):.2f}", full(gross_salary=g))
                found += 1

    # --- age x surcharge: relief must use the SAME age's slabs at the threshold --
    # (added after the FY25-26 compiled module got an 85-year-old at 50L+ wrong
    #  while passing every other edge case)
    for age in (65, 85):
        for t in (5000000, 10000000, 20000000):
            add("age_surcharge", f"age {age}, old TI {t}+20000", full(gross_salary=t + 20000 + 50000, age=age))

    # --- age bands (old-regime slabs + 80D self cap) ---------------------------
    for age in (59, 60, 79, 80):
        add("age_band", f"age {age}, TI 6L old", full(gross_salary=650000, age=age))
        add("age_band", f"age {age}, 80D self 60k", full(gross_salary=1200000, age=age, health_ins_self=60000))

    # --- deduction caps (just below / at / above) ------------------------------
    for v in (149999, 150000, 150001, 300000):
        add("cap_80c", f"80C {v}", full(gross_salary=1200000, sec_80c=v))
    for v in (49999, 50000, 50001, 100000):
        add("cap_80ccd_1b", f"80CCD(1B) {v}", full(gross_salary=1200000, sec_80ccd_1b=v))
    for v in (24999, 25000, 25001):
        add("cap_80d_self", f"80D self {v}", full(gross_salary=1200000, health_ins_self=v))
    for v, sr in ((25000, False), (25001, False), (50000, True), (50001, True), (40000, True)):
        add("cap_80d_parents", f"80D parents {v} senior={sr}",
            full(gross_salary=1200000, health_ins_parents=v, parents_senior=sr))
    for v in (199999, 200000, 200001, 350000):
        add("cap_24b", f"home-loan interest {v}", full(gross_salary=1500000, home_loan_interest=v))

    # --- HRA: make each limb of Rule 2A the binding one -----------------------
    add("hra", "limb1 binds: HRA received smallest",
        full(gross_salary=1500000, hra_received=100000, basic_plus_da=700000, rent_paid=400000, rent_city_is_metro=True))
    add("hra", "limb2 binds: rent-10% smallest",
        full(gross_salary=1500000, hra_received=350000, basic_plus_da=700000, rent_paid=200000, rent_city_is_metro=True))
    add("hra", "limb3 binds: 50% metro",
        full(gross_salary=1500000, hra_received=500000, basic_plus_da=700000, rent_paid=800000, rent_city_is_metro=True))
    add("hra", "limb3 binds: 40% non-metro",
        full(gross_salary=1500000, hra_received=500000, basic_plus_da=700000, rent_paid=800000, rent_city_is_metro=False))
    add("hra", "rent below 10% of salary -> 0 exemption",
        full(gross_salary=1500000, hra_received=300000, basic_plus_da=700000, rent_paid=60000))
    add("hra", "rent exactly 10% of salary -> 0 exemption",
        full(gross_salary=1500000, hra_received=300000, basic_plus_da=700000, rent_paid=70000))
    add("hra", "HRA received but no rent paid",
        full(gross_salary=1500000, hra_received=300000, basic_plus_da=700000, rent_paid=0))

    # --- degenerate inputs -------------------------------------------------------
    add("degenerate", "zero salary", full(gross_salary=0))
    add("degenerate", "salary below standard deduction", full(gross_salary=40000))
    add("degenerate", "deductions exceed income (Sec 80A(2))",
        full(gross_salary=250000, sec_80c=150000, sec_80ccd_1b=50000, health_ins_self=25000))
    add("degenerate", "home-loan loss exceeds salary income",
        full(gross_salary=200000, home_loan_interest=200000))

    # --- realistic "everything" profiles ----------------------------------------
    add("combined", "metro renter maxing deductions",
        full(gross_salary=1800000, hra_received=360000, basic_plus_da=900000, rent_paid=300000,
             rent_city_is_metro=True, sec_80c=150000, sec_80ccd_1b=50000, health_ins_self=20000,
             health_ins_parents=40000, parents_senior=True))
    add("combined", "home owner with loan",
        full(gross_salary=2500000, home_loan_interest=200000, sec_80c=150000, sec_80ccd_1b=50000,
             health_ins_self=25000, health_ins_parents=50000, parents_senior=True))
    add("combined", "senior employee 62",
        full(gross_salary=1100000, age=62, sec_80c=150000, health_ins_self=50000))
    return cases


def random_cases(n: int, seed: int = 2024) -> list[tuple[str, str, dict]]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        gross = int(10 ** rng.uniform(5.3, 8.0)) // 100 * 100     # ~2L to ~10Cr
        inp = full(gross_salary=gross, age=rng.choice([25, 35, 45, 58, 60, 65, 79, 80, 85]))
        if rng.random() < 0.5:
            basic = gross * rng.choice([40, 50]) // 100
            inp.update(hra_received=basic * rng.choice([40, 50]) // 100, basic_plus_da=basic,
                       rent_paid=rng.randrange(60000, 900000, 1000),
                       rent_city_is_metro=rng.random() < 0.5)
        if rng.random() < 0.7:
            inp["sec_80c"] = rng.choice([50000, 100000, 150000, 200000])
        if rng.random() < 0.4:
            inp["sec_80ccd_1b"] = rng.choice([25000, 50000, 60000])
        if rng.random() < 0.5:
            inp["health_ins_self"] = rng.randrange(5000, 60000, 500)
        if rng.random() < 0.4:
            inp["health_ins_parents"] = rng.randrange(10000, 70000, 500)
            inp["parents_senior"] = rng.random() < 0.6
        if rng.random() < 0.3:
            inp["home_loan_interest"] = rng.randrange(50000, 350000, 1000)
        out.append(("random", f"random #{i}", inp))
    return out


def main(fy: str = "2024-25") -> None:
    raw = edge_cases(fy) + random_cases(150)
    cases = []
    for i, (cat, desc, inp) in enumerate(raw):
        exp = oracle(inp, fy)
        cases.append({"id": f"A{i:03d}", "category": cat, "description": desc, "input": inp,
                      "expected": {"old": exp["old"], "new": exp["new"]},
                      "expected_total_income": {"old": exp["ti_old"], "new": exp["ti_new"]}})
    name = "cases.json" if fy == "2024-25" else f"cases_{fy.replace('-', '_')}.json"
    (HERE / name).write_text(json.dumps(cases, indent=1))
    print(f"wrote {len(cases)} cases -> {name}")
    if fy != "2024-25":
        return

    official = HERE / "official_checks.csv"
    if official.exists():
        print("official_checks.csv exists — left untouched")
        return
    # 30 cases spread across categories for manual checking
    picks = [c for c in cases if c["category"] != "random"][::3][:22] + \
            [c for c in cases if c["category"] == "random"][:8]
    with open(official, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "description", "input_json", "expected_old", "expected_new",
                    "official_old", "official_new", "checked_on", "notes"])
        for c in picks:
            w.writerow([c["id"], c["description"], json.dumps(c["input"]),
                        c["expected"]["old"], c["expected"]["new"], "", "", "", ""])
    print(f"wrote {len(picks)} rows -> official_checks.csv (fill official_old/official_new by hand)")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "2024-25")
