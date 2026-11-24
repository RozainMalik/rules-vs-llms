"""
Implementation (a): HAND-CODED RULES.

The law (numbers + clauses) lives in project_a/rules/fy<year>.yaml.
This file holds only the *procedure* (the order of computation). That split
is deliberate: when the Budget changes rates/limits we edit YAML, not code.

Every amount the engine produces is recorded as a TraceLine with its clause:
    sum(income lines) == total_income (before Sec 288A rounding line)
    sum(tax lines)    == tax_payable
so every rupee of the answer can be audited.

Run a demo:  python -m project_a.impl_rules.engine
"""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Union

import yaml

from project_a.models import (
    Clarification, QUESTIONS, RegimeResult, TaxInput, TaxResult, TraceLine,
)

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
D = Decimal  # shorthand


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def inr(x: Decimal | int) -> str:
    """Format in Indian digit grouping: 1234567.5 -> '₹12,34,567.50'."""
    x = D(x)
    sign = "-" if x < 0 else ""
    x = abs(x)
    whole = int(x)
    paise = int(((x - whole) * 100).to_integral_value())
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"{sign}₹{s}" + (f".{paise:02d}" if paise else "")


def round_to_10(x: Decimal) -> int:
    """Sec 288A / 288B: drop paise, then round to nearest 10 (5 goes up)."""
    rupees = int(x.to_integral_value(rounding=ROUND_FLOOR))
    return (rupees + 5) // 10 * 10


def slab_tax(income: Decimal, bands: list[dict]) -> tuple[Decimal, list[tuple[dict, Decimal, Decimal]]]:
    """Progressive tax. Returns (total, [(band, taxable_part, tax_on_part), ...])."""
    total = D(0)
    parts = []
    for band in bands:
        lo = D(band["from"])
        hi = D(band["to"]) if band["to"] is not None else None
        if income <= lo:
            break
        portion = (min(income, hi) if hi is not None else income) - lo
        tax = portion * D(str(band["rate"]))
        total += tax
        parts.append((band, portion, tax))
    return total, parts


def load_rules(fiscal_year: str) -> dict:
    path = RULES_DIR / f"fy{fiscal_year.replace('-', '_')}.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------
class RulesEngine:
    def __init__(self, fiscal_year: str = "2024-25"):
        self.fy = fiscal_year
        self.rules = load_rules(fiscal_year)

    # ---- public ------------------------------------------------------------
    def compute_with_meta(self, inp: TaxInput, sample: int = 0):
        """Same interface as the LLM calculators; no LLM call, so no metadata."""
        return self.compute(inp), None

    def compute(self, inp: TaxInput, sample: int = 0) -> Union[TaxResult, Clarification]:
        # `sample` is accepted for interface parity and ignored: the engine is deterministic.
        errors = inp.validation_errors()
        if errors:
            return Clarification(
                questions=[f"Please check: {e}" for e in errors],
                reason="contradictory or impossible input",
            )
        missing = inp.blocking_missing()
        if missing:
            return Clarification(
                questions=[QUESTIONS[m] for m in missing],
                reason=f"missing: {', '.join(missing)}",
            )

        assumptions = [
            f"'{name}' was not mentioned; assumed ₹0 (affects old regime only)"
            for name in inp.unstated_optional()
        ]
        if (inp.hra_received or 0) > 0:
            assumptions.append("DA assumed to form part of salary for retirement benefits (Rule 2A)")

        return TaxResult(
            fiscal_year=self.fy,
            old=self.compute_regime(inp, "old"),
            new=self.compute_regime(inp, "new"),
            assumptions=assumptions,
        )

    def compute_regime(self, inp: TaxInput, regime: str) -> RegimeResult:
        r = self.rules[f"{regime}_regime"]
        trace: list[TraceLine] = []

        def inc(step, desc, amount, clause):
            trace.append(TraceLine("income", step, desc, D(amount), clause))

        def tax(step, desc, amount, clause):
            trace.append(TraceLine("tax", step, desc, D(amount), clause))

        # ---- 1. gross salary ------------------------------------------------
        gross = D(inp.get("gross_salary"))
        inc("gross_salary", "Gross salary (all taxable components)", gross, "Sec 17(1)")

        # ---- 2. HRA exemption (old only) ------------------------------------
        hra_ex = D(0)
        if regime == "old" and inp.get("hra_received") > 0:
            h = r["hra_exemption"]
            salary = D(inp.get("basic_plus_da"))
            pct = D(str(h["metro_pct"] if inp.rent_city_is_metro else h["non_metro_pct"]))
            limb1 = D(inp.get("hra_received"))
            limb2 = max(D(0), D(inp.get("rent_paid")) - D(str(h["rent_excess_over_salary_pct"])) * salary)
            limb3 = pct * salary
            hra_ex = min(limb1, limb2, limb3)
            inc("hra_exemption",
                f"HRA exempt = least of received {inr(limb1)}, rent-10% salary {inr(limb2)}, "
                f"{int(pct * 100)}% salary {inr(limb3)}",
                -hra_ex, h["clause"])

        # ---- 3. standard deduction ------------------------------------------
        sd = min(D(r["standard_deduction"]["amount"]), gross - hra_ex)
        inc("standard_deduction", "Standard deduction", -sd, r["standard_deduction"]["clause"])
        salary_income = gross - hra_ex - sd

        # ---- 4. home-loan interest, self-occupied (old only) ----------------
        hp_loss = D(0)
        if regime == "old" and inp.get("home_loan_interest") > 0:
            cap = D(r["home_loan_interest_self_occupied"]["cap"])
            hp_loss = min(D(inp.get("home_loan_interest")), cap)
            # loss can only absorb salary income; the rest is carried forward
            hp_loss = min(hp_loss, salary_income)
            inc("home_loan_interest",
                f"Interest on self-occupied house loan (capped at {inr(cap)})",
                -hp_loss, r["home_loan_interest_self_occupied"]["clause"])
        gti = salary_income - hp_loss

        # ---- 5. Chapter VI-A deductions (old only), capped at GTI -----------
        if regime == "old":
            d = r["deductions"]
            senior_self = inp.get("age") >= 60
            claims = [
                ("sec_80c", "80C investments",
                 min(inp.get("sec_80c"), d["sec_80c"]["cap"]), d["sec_80c"]["clause"]),
                ("sec_80ccd_1b", "Additional NPS contribution",
                 min(inp.get("sec_80ccd_1b"), d["sec_80ccd_1b"]["cap"]), d["sec_80ccd_1b"]["clause"]),
                ("sec_80d_self", "Health insurance - self/family",
                 min(inp.get("health_ins_self"),
                     d["sec_80d"]["self_family_cap_if_senior" if senior_self else "self_family_cap"]),
                 d["sec_80d"]["clause"]),
                ("sec_80d_parents", "Health insurance - parents",
                 min(inp.get("health_ins_parents"),
                     d["sec_80d"]["parents_cap_if_senior" if inp.parents_senior else "parents_cap"]),
                 d["sec_80d"]["clause"]),
            ]
            room = gti  # Sec 80A(2): deductions cannot exceed gross total income
            for step, desc, amount, clause in claims:
                allowed = min(D(amount), room)
                if allowed > 0:
                    inc(step, desc, -allowed, clause)
                    room -= allowed
            total_before_round = room
        else:
            total_before_round = gti

        # ---- 5b. round total income (Sec 288A) -------------------------------
        total_income = round_to_10(total_before_round)
        if D(total_income) != total_before_round:
            inc("round_288a", "Total income rounded to nearest ₹10",
                D(total_income) - total_before_round, self.rules["rounding"]["total_income"]["clause"])
        ti = D(total_income)

        # ---- 6. slab tax ----------------------------------------------------
        bands_cfg = self._bands(r, inp.get("age"))
        base_tax, parts = slab_tax(ti, bands_cfg["bands"])
        for band, portion, t in parts:
            if t:
                upper = inr(band["to"]) if band["to"] else "above"
                tax("slab", f"{int(band['rate'] * 100)}% on {inr(portion)} "
                            f"(slab {inr(band['from'])}-{upper})", t, bands_cfg["clause"])
        if not base_tax:
            # Say WHY tax is nil, so a zero still cites the clause that produced it.
            tax("slab", f"Nil: total income {inr(ti)} lies entirely in the 0% slab",
                D(0), bands_cfg["clause"])

        # ---- 7. Sec 87A rebate (+ marginal relief) ---------------------------
        rb = r["rebate_87a"]
        rebate = D(0)
        if ti <= rb["income_limit"]:
            rebate = min(base_tax, D(rb["max_rebate"]))
            if rebate:
                tax("rebate_87a", f"Rebate: total income ≤ {inr(rb['income_limit'])}", -rebate, rb["clause"])
        elif rb["marginal_relief"]:
            excess = ti - rb["income_limit"]
            if base_tax > excess:
                rebate = base_tax - excess
                tax("rebate_87a_marginal",
                    f"Marginal relief: tax cannot exceed income above {inr(rb['income_limit'])} ({inr(excess)})",
                    -rebate, rb["clause"])
        tax_after_rebate = base_tax - rebate

        # ---- 8. surcharge with marginal relief ------------------------------
        surcharge, relief = self._surcharge(r, bands_cfg["bands"], ti, tax_after_rebate)
        if surcharge:
            rate = self._surcharge_rate(r, ti)
            tax("surcharge", f"Surcharge @ {int(rate * 100)}%", surcharge, r["surcharge"]["clause"])
        if relief:
            tax("surcharge_marginal_relief",
                "Marginal relief: extra tax+surcharge cannot exceed income above the threshold",
                -relief, r["surcharge"]["clause"])

        # ---- 9. cess --------------------------------------------------------
        before_cess = tax_after_rebate + surcharge - relief
        cess = before_cess * D(str(self.rules["cess"]["rate"]))
        if cess:
            tax("cess", "Health & Education cess @ 4%", cess, self.rules["cess"]["clause"])

        # ---- 10. round tax (Sec 288B) ---------------------------------------
        unrounded = before_cess + cess
        payable = round_to_10(unrounded)
        if D(payable) != unrounded:
            tax("round_288b", "Tax rounded to nearest ₹10", D(payable) - unrounded,
                self.rules["rounding"]["tax_payable"]["clause"])

        return RegimeResult(
            regime=regime,
            gross_total_income=int(gti),
            total_income=total_income,
            tax_payable=payable,
            trace=trace,
        )

    # ---- internals ---------------------------------------------------------
    @staticmethod
    def _bands(r: dict, age: int) -> dict:
        slabs = r["slabs"]
        if "all_ages" in slabs:
            return slabs["all_ages"]
        if age >= 80:
            return slabs["super_senior_80_plus"]
        if age >= 60:
            return slabs["senior_60_to_79"]
        return slabs["below_60"]

    @staticmethod
    def _surcharge_rate(r: dict, income: Decimal) -> Decimal:
        """Rate for this income. Surcharge applies only when income EXCEEDS the
        threshold, so at exactly the threshold the lower rate applies."""
        rate = D(0)
        for band in r["surcharge"]["bands"]:
            if income > band["above"]:
                rate = D(str(band["rate"]))
        return rate

    def _surcharge(self, r: dict, bands: list[dict], ti: Decimal, tax_amt: Decimal) -> tuple[Decimal, Decimal]:
        rate = self._surcharge_rate(r, ti)
        if rate == 0:
            return D(0), D(0)
        surcharge = tax_amt * rate
        if not r["surcharge"]["marginal_relief"]:
            return surcharge, D(0)
        # the threshold we just crossed
        threshold = max(D(b["above"]) for b in r["surcharge"]["bands"] if ti > b["above"])
        tax_at_t, _ = slab_tax(threshold, bands)
        total_at_t = tax_at_t * (1 + self._surcharge_rate(r, threshold))
        cap = total_at_t + (ti - threshold)
        relief = max(D(0), tax_amt + surcharge - cap)
        return surcharge, relief


# ---------------------------------------------------------------------------
# pretty printer + demo
# ---------------------------------------------------------------------------
def explain(result: Union[TaxResult, Clarification]) -> str:
    if isinstance(result, Clarification):
        return "I need a bit more information:\n" + "\n".join(f"  - {q}" for q in result.questions)
    out = [f"Income tax, FY {result.fiscal_year}"]
    for rr in (result.old, result.new):
        out.append(f"\n{rr.regime.upper()} REGIME — tax payable {inr(rr.tax_payable)}")
        for line in rr.trace:
            out.append(f"  [{line.kind:6}] {inr(line.amount):>16}  {line.description}  ({line.clause})")
        out.append(f"  total income {inr(rr.total_income)}")
    out.append(f"\nRecommendation: {result.recommended.upper()} regime, saves {inr(result.savings)}")
    if result.assumptions:
        out.append("Assumptions:\n" + "\n".join(f"  - {a}" for a in result.assumptions))
    return "\n".join(out)


if __name__ == "__main__":
    demo = TaxInput(
        gross_salary=1_800_000, age=32,
        hra_received=360_000, basic_plus_da=900_000, rent_paid=300_000, rent_city_is_metro=True,
        sec_80c=150_000, sec_80ccd_1b=50_000, health_ins_self=20_000,
        health_ins_parents=40_000, parents_senior=True, home_loan_interest=0,
    )
    print(explain(RulesEngine("2024-25").compute(demo)))
