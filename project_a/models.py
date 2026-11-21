"""
Shared data shapes for Project A.

All three implementations (hand-coded rules, LLM at query time, LLM-compiled
rules) take a `TaxInput` and return a `TaxResult`. Because they share these
types, the benchmark can compare them field by field.

Convention for every Optional field:
    None -> the user has NOT told us   (unknown: may need a clarifying question)
    0    -> the user told us it is zero (known)
This difference is what lets the parser "ask instead of guess".
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Literal, Optional

Regime = Literal["old", "new"]


# ---------------------------------------------------------------------------
# INPUT
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TaxInput:
    # --- always needed -----------------------------------------------------
    gross_salary: Optional[int] = None        # annual, includes HRA received & all taxable allowances
    age: Optional[int] = None                 # taxpayer's age; picks old-regime slab & 80D cap

    # --- HRA (old regime only) ----------------------------------------------
    hra_received: Optional[int] = None        # HRA component of gross_salary
    basic_plus_da: Optional[int] = None       # "salary" for Rule 2A
    rent_paid: Optional[int] = None           # annual rent actually paid
    rent_city_is_metro: Optional[bool] = None # Delhi/Mumbai/Kolkata/Chennai

    # --- house property (old regime only) -----------------------------------
    home_loan_interest: Optional[int] = None  # self-occupied house, Sec 24(b)

    # --- Chapter VI-A (old regime only) -------------------------------------
    sec_80c: Optional[int] = None             # PF, PPF, ELSS, LIC, principal repaid, ...
    sec_80ccd_1b: Optional[int] = None        # own extra NPS contribution
    health_ins_self: Optional[int] = None     # premium for self/spouse/children
    health_ins_parents: Optional[int] = None  # premium for parents
    parents_senior: Optional[bool] = None     # is either parent 60+?

    # ---------------------------------------------------------------------
    def blocking_missing(self) -> list[str]:
        """Fields we CANNOT compute without. The parser must ask about these.

        Some fields are only required because of another answer, e.g. if the
        user gets HRA and pays rent, we need basic+DA and the city.
        """
        missing: list[str] = []
        if self.gross_salary is None:
            missing.append("gross_salary")
        if self.age is None:
            missing.append("age")

        claims_hra = (self.hra_received or 0) > 0 or (self.rent_paid or 0) > 0
        if claims_hra:
            for name in ("hra_received", "rent_paid", "basic_plus_da", "rent_city_is_metro"):
                if getattr(self, name) is None:
                    missing.append(name)

        if (self.health_ins_parents or 0) > 0 and self.parents_senior is None:
            missing.append("parents_senior")
        return missing

    def unstated_optional(self) -> list[str]:
        """Deductions the user never mentioned. Treated as 0, but DISCLOSED
        as an assumption in the answer (never assumed silently)."""
        optional = ("home_loan_interest", "sec_80c", "sec_80ccd_1b",
                    "health_ins_self", "health_ins_parents")
        return [n for n in optional if getattr(self, n) is None]

    def validation_errors(self) -> list[str]:
        """Contradictions or impossible values. These also need a question."""
        errs: list[str] = []
        for name, value in asdict(self).items():
            if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                errs.append(f"{name} cannot be negative ({value})")
        if self.age is not None and not (18 <= self.age <= 120):
            errs.append(f"age {self.age} looks wrong for a salaried person")
        if (self.gross_salary is not None and self.hra_received is not None
                and self.hra_received > self.gross_salary):
            errs.append("HRA received is larger than total salary")
        if (self.gross_salary is not None and self.basic_plus_da is not None
                and self.basic_plus_da > self.gross_salary):
            errs.append("basic + DA is larger than total salary")
        return errs

    def get(self, name: str) -> int:
        """Numeric value with unknown treated as 0 (only call after checks)."""
        value = getattr(self, name)
        return 0 if value is None else int(value)


# Clarifying question for each field the parser might need to ask about.
QUESTIONS: dict[str, str] = {
    "gross_salary": "What is your total annual salary before tax (including HRA and all allowances)?",
    "age": "How old are you? (Under 60, 60-79 and 80+ have different old-regime slabs.)",
    "hra_received": "How much HRA do you receive in a year?",
    "basic_plus_da": "What is your annual basic salary plus dearness allowance? (Needed for the HRA exemption.)",
    "rent_paid": "How much rent do you pay in a year?",
    "rent_city_is_metro": "Which city do you rent in? (Delhi, Mumbai, Kolkata and Chennai get a higher HRA limit.)",
    "parents_senior": "Is either of your parents aged 60 or above?",
}


# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TraceLine:
    """One step of the computation. Every rupee in the answer comes from a
    TraceLine, and every TraceLine names the clause it applies."""
    kind: Literal["income", "tax"]  # income lines sum to total_income, tax lines to tax_payable
    step: str               # e.g. "rebate_87a"
    description: str        # human-readable explanation
    amount: Decimal         # signed: deductions/rebates are negative
    clause: str             # e.g. "Sec 87A"


@dataclass(frozen=True)
class RegimeResult:
    regime: Regime
    gross_total_income: int
    total_income: int        # after deductions, rounded per Sec 288A
    tax_payable: int         # final figure, rounded per Sec 288B
    trace: list[TraceLine] = field(default_factory=list)


@dataclass(frozen=True)
class TaxResult:
    fiscal_year: str
    old: RegimeResult
    new: RegimeResult
    assumptions: list[str] = field(default_factory=list)  # e.g. "No 80C investments assumed"

    @property
    def recommended(self) -> Regime:
        # Ties go to the new regime because it is the statutory default (Sec 115BAC(1A)).
        return "old" if self.old.tax_payable < self.new.tax_payable else "new"

    @property
    def savings(self) -> int:
        return abs(self.old.tax_payable - self.new.tax_payable)


@dataclass(frozen=True)
class Clarification:
    """Returned INSTEAD of a TaxResult when we must ask before computing."""
    questions: list[str]
    reason: str
