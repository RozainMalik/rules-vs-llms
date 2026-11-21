"""
Shared, DETERMINISTIC back half of both parsers:

    extracted fields + issues  ->  TaxInput  or  Clarification

The parsers (regex or LLM) only extract what the user SAID. Whether that is
enough to compute is decided here by rules, never by the LLM:
  - out-of-scope income           -> explain and ask
  - issues the extractor flagged  -> ask (contradictions, vague amounts)
  - TaxInput.validation_errors()  -> ask (impossible values)
  - TaxInput.blocking_missing()   -> ask (missing facts)
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dc_fields
from typing import Optional, Union

import yaml

from project_a.impl_rules.engine import RULES_DIR
from project_a.models import Clarification, QUESTIONS, TaxInput

METRO_CITIES = set(yaml.safe_load(open(RULES_DIR / "fy2024_25.yaml"))
                   ["old_regime"]["hra_exemption"]["metro_cities"])
INPUT_FIELDS = {f.name for f in dc_fields(TaxInput)}


@dataclass
class Extraction:
    fields: dict                          # TaxInput field -> value (only what was stated)
    rent_city: Optional[str] = None       # raw city name; metro decided by rule below
    issues: list[dict] = field(default_factory=list)   # [{"field":..., "question":...}]
    out_of_scope: list[str] = field(default_factory=list)


def is_metro(city: Optional[str]) -> Optional[bool]:
    if not city:
        return None
    c = city.strip().lower()
    c = {"bombay": "mumbai", "calcutta": "kolkata", "madras": "chennai",
         "new delhi": "delhi"}.get(c, c)
    return c in METRO_CITIES


def decide(ex: Extraction) -> Union[TaxInput, Clarification]:
    values = {k: v for k, v in ex.fields.items() if k in INPUT_FIELDS}
    if values.get("rent_city_is_metro") is None and ex.rent_city:
        values["rent_city_is_metro"] = is_metro(ex.rent_city)

    if ex.out_of_scope:
        return Clarification(
            questions=[f"This service covers salary income only; {', '.join(ex.out_of_scope)} "
                       f"is out of scope. Shall I compute tax on your salary alone?"],
            reason="out_of_scope")
    if ex.issues:
        return Clarification(questions=[i["question"] for i in ex.issues],
                             reason="issues: " + ", ".join(i["field"] for i in ex.issues))
    try:
        inp = TaxInput(**values)
    except TypeError as e:  # wrong field types from the extractor
        return Clarification([f"Could not understand the input ({e})."], "bad_extraction")

    errors = inp.validation_errors()
    if errors:
        return Clarification([f"Please check: {e}" for e in errors], "contradiction: " + "; ".join(errors))
    missing = inp.blocking_missing()
    if missing:
        return Clarification([QUESTIONS[m] for m in missing], "missing: " + ", ".join(missing))
    return inp
