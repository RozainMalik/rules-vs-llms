"""
Independent REFERENCE calculator for FY 2024-25 and FY 2025-26, used ONLY to produce expected
values for the test suite.

Why a second calculator? If the engine generated its own expected values the
tests would be circular. The oracle is written differently on purpose:
  - constants hardcoded here (does NOT read the YAML)
  - exact Fractions instead of Decimals
  - straight-line code, no classes, no trace
If the engine and oracle agree on 200+ cases, and both agree with the official
calculator on 30, a shared bug is very unlikely.
"""

from fractions import Fraction as F


def _r10(x: F) -> int:
    whole = x.numerator // x.denominator          # drop paise (floor)
    return (whole + 5) // 10 * 10


def _slabs(ti: int, bands) -> F:
    tax, prev = F(0), 0
    for upper, pct in bands:
        if ti > prev:
            top = ti if upper is None else min(ti, upper)
            tax += F(top - prev) * F(pct, 100)
        prev = upper if upper is not None else prev
    return tax


OLD_BANDS = {
    "below_60": [(250000, 0), (500000, 5), (1000000, 20), (None, 30)],
    "60_79":    [(300000, 0), (500000, 5), (1000000, 20), (None, 30)],
    "80_plus":  [(500000, 0), (1000000, 20), (None, 30)],
}
# New regime per fiscal year: (slab bands, 87A income limit, 87A max rebate)
NEW_REGIME = {
    "2024-25": ([(300000, 0), (700000, 5), (1000000, 10), (1200000, 15), (1500000, 20), (None, 30)],
                700000, 25000),                                   # Finance (No.2) Act 2024
    "2025-26": ([(400000, 0), (800000, 5), (1200000, 10), (1600000, 15), (2000000, 20),
                 (2400000, 25), (None, 30)],
                1200000, 60000),                                  # Finance Act 2025
}
OLD_SURCHARGE = [(5000000, 10), (10000000, 15), (20000000, 25), (50000000, 37)]
NEW_SURCHARGE = [(5000000, 10), (10000000, 15), (20000000, 25)]


def _rate(ti, table):
    rate = 0
    for threshold, pct in table:
        if ti > threshold:
            rate = pct
    return rate


def _with_surcharge(ti: int, tax: F, bands, table) -> F:
    rate = _rate(ti, table)
    if rate == 0:
        return tax
    threshold = max(t for t, _ in table if ti > t)
    at_t = _slabs(threshold, bands) * (1 + F(_rate(threshold, table), 100))
    return min(tax * (1 + F(rate, 100)), at_t + (ti - threshold))


def oracle(case: dict, fiscal_year: str = "2024-25") -> dict:
    """case: plain dict with TaxInput field names (missing = 0)."""
    new_bands, rebate_limit, rebate_max = NEW_REGIME[fiscal_year]
    g = lambda k: case.get(k) or 0
    gross, age = g("gross_salary"), g("age")

    # ---------------- NEW REGIME ----------------
    ti_new = _r10(F(max(0, gross - min(75000, gross))))
    t = _slabs(ti_new, new_bands)
    if ti_new <= rebate_limit:
        t = max(F(0), t - rebate_max)
    else:
        t = min(t, F(ti_new - rebate_limit))
    t = _with_surcharge(ti_new, t, new_bands, NEW_SURCHARGE)
    raw_new = t * F(104, 100)
    new_tax = _r10(raw_new)

    # ---------------- OLD REGIME ----------------
    hra = F(0)
    if g("hra_received") > 0:
        sal = F(g("basic_plus_da"))
        hra = min(F(g("hra_received")),
                  max(F(0), g("rent_paid") - sal / 10),
                  sal * (F(1, 2) if case.get("rent_city_is_metro") else F(2, 5)))
    after_hra = gross - hra
    salary_income = after_hra - min(50000, after_hra)
    gti = salary_income - min(g("home_loan_interest"), 200000, salary_income)
    via = (min(g("sec_80c"), 150000) + min(g("sec_80ccd_1b"), 50000)
           + min(g("health_ins_self"), 50000 if age >= 60 else 25000)
           + min(g("health_ins_parents"), 50000 if case.get("parents_senior") else 25000))
    ti_old = _r10(max(F(0), gti - via))
    bands = OLD_BANDS["80_plus" if age >= 80 else "60_79" if age >= 60 else "below_60"]
    t = _slabs(ti_old, bands)
    if ti_old <= 500000:
        t = max(F(0), t - 12500)
    t = _with_surcharge(ti_old, t, bands, OLD_SURCHARGE)
    raw_old = t * F(104, 100)
    old_tax = _r10(raw_old)

    return {"old": old_tax, "new": new_tax, "ti_old": ti_old, "ti_new": ti_new,
            "raw_old": raw_old, "raw_new": raw_new}   # unrounded, for building Sec 288B edge cases
