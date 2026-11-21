"""
Implementation (c): LLM-COMPILED RULES — the RUN step (no LLM involved).

Loads the reviewed module compiled/fy<year>.py and adapts its output to the
shared TaxResult type. Same deterministic gate as the other implementations.
"""

from __future__ import annotations

import importlib.util
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Union

from project_a.models import (
    Clarification, QUESTIONS, RegimeResult, TaxInput, TaxResult, TraceLine,
)

COMPILED = Path(__file__).resolve().parent / "compiled"


class CompiledCalculator:
    name = "llm_compiled"

    def __init__(self, fiscal_year: str = "2024-25"):
        self.fy = fiscal_year
        path = COMPILED / f"fy{fiscal_year.replace('-', '_')}.py"
        spec = importlib.util.spec_from_file_location(f"compiled_{path.stem}", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def compute(self, inp: TaxInput, sample: int = 0) -> Union[TaxResult, Clarification]:
        errors, missing = inp.validation_errors(), inp.blocking_missing()
        if errors or missing:
            return Clarification([QUESTIONS.get(m, m) for m in missing] + errors,
                                 "missing or contradictory input")
        data = {k: (v if v is not None else (False if k in ("rent_city_is_metro", "parents_senior") else 0))
                for k, v in asdict(inp).items()}
        out = self.module.compute(data)
        return TaxResult(self.fy, self._regime(out["old"], "old"), self._regime(out["new"], "new"), [])

    def compute_with_meta(self, inp: TaxInput, sample: int = 0):
        return self.compute(inp, sample), None

    @staticmethod
    def _regime(d: dict, regime: str) -> RegimeResult:
        trace = [TraceLine(t.get("kind", "tax"), "compiled_step", str(t.get("description", "")),
                           Decimal(str(t.get("amount", 0))), str(t.get("clause") or ""))
                 for t in d.get("trace", [])]
        return RegimeResult(regime, -1, int(d["total_income"]), int(d["tax_payable"]), trace)
