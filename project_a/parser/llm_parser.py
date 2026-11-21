"""
Parser option 2: HYBRID — LLM for language, rules for decisions.

The LLM ONLY turns free text (English, Hinglish, terse, messy) into fields and
flags contradictions / vague amounts / out-of-scope income. It never decides
whether we have enough information, never maps cities to metro status, and
never computes tax — those stay in deterministic code (parser/common.py).
"""

from __future__ import annotations

from common.llm import LLM, LLMResponse, parse_json
from project_a.parser.common import Extraction, INPUT_FIELDS

SYSTEM = """You extract facts for an Indian income-tax calculator from a user's message.
The message may be English, Hinglish or very terse. You do NOT compute tax.

Return ONLY JSON:
{
 "fields": {
   "gross_salary": int|null,        // ANNUAL rupees, total salary incl. HRA/allowances
   "age": int|null,
   "hra_received": int|null,        // annual
   "basic_plus_da": int|null,       // annual basic (+DA)
   "rent_paid": int|null,           // annual rent
   "home_loan_interest": int|null,  // interest on a loan for the house they live in
   "sec_80c": int|null,             // PPF, ELSS, LIC, EPF, tuition, principal...
   "sec_80ccd_1b": int|null,        // own extra NPS
   "health_ins_self": int|null,     // premium for self/spouse/children
   "health_ins_parents": int|null,
   "parents_senior": bool|null      // is either parent 60 or older
 },
 "rent_city": str|null,             // city of the rented house, as written
 "issues": [{"field": str, "question": str}],
 "out_of_scope": [str]
}

Conversion rules: lakh/lac/L/LPA = 100,000; crore/cr = 10,000,000; k/hazaar/thousand = 1,000;
monthly / per month / pm / mahina amounts are multiplied by 12. "Max out 80C" = 150000.

Use null when the user did NOT state something. Use 0 / false when they clearly said they have none.
NEVER guess a value. Add an entry to "issues" (with a short clarifying question to the user) when:
 - two statements contradict each other (e.g. two different salaries, rent paid AND no rent),
 - an amount is a range, approximate, or changed during the year,
 - they mention a deduction or investment but no amount,
 - an age band is given without an exact age (e.g. "senior citizen"), or an age contradicts it.
Put non-salary income (rental income, capital gains, business, interest, freelance) in "out_of_scope"."""


class LLMParser:
    name = "llm_parser"

    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    def parse_with_meta(self, text: str, sample: int = 0) -> tuple[Extraction, LLMResponse]:
        resp = self.llm.generate(f"MESSAGE:\n{text}", system=SYSTEM, json_mode=True, sample=sample)
        data = parse_json(resp.text)
        raw = data.get("fields") or {}
        fields = {k: v for k, v in raw.items() if k in INPUT_FIELDS and v is not None}
        return Extraction(fields=fields, rent_city=data.get("rent_city"),
                          issues=[i for i in data.get("issues") or [] if isinstance(i, dict)],
                          out_of_scope=list(data.get("out_of_scope") or [])), resp

    def parse(self, text: str) -> Extraction:
        return self.parse_with_meta(text)[0]
