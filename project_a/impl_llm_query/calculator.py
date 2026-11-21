"""
Implementation (b): LLM AT QUERY TIME.

For every request the LLM receives the full rule text + the structured input
and must compute both regimes itself, returning JSON with a step-by-step
trace that cites clauses. No arithmetic is done in Python except checking.

The SAME deterministic gate as the rules engine runs first (missing or
contradictory input -> Clarification), so we compare only the computation.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Optional, Union

from common.llm import LLM, LLMResponse, parse_json
from project_a.models import (
    Clarification, QUESTIONS, RegimeResult, TaxInput, TaxResult, TraceLine,
)

TEXT_DIR = Path(__file__).resolve().parent.parent / "rules_text"

SYSTEM = """You are an Indian income-tax calculator for resident salaried individuals.
Use ONLY the rule text provided. Compute the tax under BOTH the old regime and the new regime.
Work step by step. Every amount you use must cite the section it comes from.

Return ONLY JSON with this exact shape:
{
  "old": {"total_income": <int>, "tax_payable": <int>,
          "steps": [{"kind": "income"|"tax", "description": <str>, "amount": <number>, "clause": <str>}]},
  "new": { ...same... }
}
Rules for "steps":
- "income" steps start with gross salary and subtract each exemption/deduction (negative amounts);
  they must add up to total_income.
- "tax" steps are slab tax per band (positive), rebate (negative), surcharge (positive),
  marginal relief (negative), cess (positive) and the final rounding adjustment;
  they must add up EXACTLY to tax_payable.
- Fields with value 0 or false mean the person has none of that item."""

FIELD_GLOSSARY = """Input fields (all amounts are annual, in rupees):
gross_salary: total salary incl. HRA and allowances | age: taxpayer age
hra_received: HRA part of salary | basic_plus_da: basic + DA | rent_paid: annual rent
rent_city_is_metro: rented house is in Delhi/Mumbai/Kolkata/Chennai
home_loan_interest: interest on self-occupied house loan
sec_80c, sec_80ccd_1b: investments | health_ins_self, health_ins_parents: premiums
parents_senior: either parent is 60+"""


class LLMQueryCalculator:
    name = "llm_query"

    def __init__(self, fiscal_year: str = "2024-25", llm: Optional[LLM] = None):
        self.fy = fiscal_year
        self.rule_text = (TEXT_DIR / f"fy{fiscal_year.replace('-', '_')}.md").read_text()
        self.llm = llm or LLM()

    def build_prompt(self, inp: TaxInput) -> str:
        data = {k: (0 if v is None else v) for k, v in asdict(inp).items()}
        return (f"RULE TEXT (FY {self.fy}):\n{self.rule_text}\n\n{FIELD_GLOSSARY}\n\n"
                f"PERSON:\n{json.dumps(data)}\n\nCompute and return the JSON.")

    def compute_with_meta(self, inp: TaxInput, sample: int = 0
                          ) -> tuple[Union[TaxResult, Clarification], Optional[LLMResponse]]:
        errors, missing = inp.validation_errors(), inp.blocking_missing()
        if errors or missing:
            return Clarification([QUESTIONS.get(m, m) for m in missing] + errors,
                                 "missing or contradictory input"), None

        resp = self.llm.generate(self.build_prompt(inp), system=SYSTEM, json_mode=True, sample=sample)
        data = parse_json(resp.text)
        result = TaxResult(
            fiscal_year=self.fy,
            old=self._regime(data["old"], "old"),
            new=self._regime(data["new"], "new"),
            assumptions=[],
        )
        return result, resp

    def compute(self, inp: TaxInput, sample: int = 0):
        return self.compute_with_meta(inp, sample)[0]

    @staticmethod
    def _regime(d: dict, regime: str) -> RegimeResult:
        trace = [TraceLine(kind=s.get("kind", "tax"), step="llm_step",
                           description=str(s.get("description", "")),
                           amount=Decimal(str(s.get("amount", 0))),
                           clause=str(s.get("clause") or ""))
                 for s in d.get("steps", [])]
        return RegimeResult(regime=regime, gross_total_income=-1,   # not requested from the LLM
                            total_income=int(round(float(d["total_income"]))),
                            tax_payable=int(round(float(d["tax_payable"]))), trace=trace)
