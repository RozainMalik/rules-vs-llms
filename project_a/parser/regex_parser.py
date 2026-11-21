"""
Parser option 1: PURE RULES (regex + keyword windows). No LLM.

Kept as the baseline so we can MEASURE whether an LLM parser earns its cost.
Strategy: split the text into clauses, find amounts (with lakh/crore/k units
and per-month markers), and attach each amount to the keyword in its clause.
"""

from __future__ import annotations

import re

from project_a.parser.common import Extraction, METRO_CITIES

UNIT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5, "lpa": 1e5,
        "cr": 1e7, "crore": 1e7, "crores": 1e7, "k": 1e3, "hazaar": 1e3, "hazar": 1e3,
        "thousand": 1e3}
AMOUNT = re.compile(r"(?:rs\.?|₹|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|lpa|crores?|cr|k|hazaa?r|thousand|l)?\b",
                    re.I)
MONTHLY = re.compile(r"per month|monthly|/month|\bpm\b|mahin[ae]|a month|month", re.I)
SPLIT = re.compile(r"[.;/]\s|,\s|\band\b|\baur\b|\bplus\b", re.I)

KEYWORDS = [  # (field, pattern) — first match in a clause wins, so order matters
    ("hra_received", r"\bhra\b"),
    ("basic_plus_da", r"\bbasic"),
    ("rent_paid", r"\brent|kiray"),
    ("sec_80ccd_1b", r"\bnps\b"),
    ("home_loan_interest", r"home loan|housing loan|loan ka interest|interest"),
    ("health_ins_parents", r"(health|insurance|mediclaim|premium).*(parent|papa|mummy|father|mother)|"
                           r"(parent|papa|mummy|father|mother).*(health|insurance|mediclaim|premium)"),
    ("health_ins_self", r"health|insurance|mediclaim"),
    ("sec_80c", r"80c|ppf|elss|\blic\b|provident"),
    ("gross_salary", r"salary|ctc|package|\bpay\b|income|earn|\blpa\b|\bpm\b"),
]
AGE = [r"\bage[:\s]*(\d{2})", r"(\d{2})[\s-]*(?:years?|yrs?|y)(?:[\s-]*old)?\b", r"(\d{2})\s*yo\b",
       r"umar\s*(\d{2})", r"(\d{2})\s*saal", r"\bi'?m\s*(\d{2})\b", r"(\d{2})\s*ki age"]


def _amount(clause: str):
    for m in AMOUNT.finditer(clause):
        num, unit = m.group(1).replace(",", ""), (m.group(2) or "").lower()
        if not unit and float(num) < 1000:      # bare small numbers are ages, not money
            continue
        value = float(num) * UNIT.get(unit, 1)
        if MONTHLY.search(clause) and value < 5e5:
            value *= 12
        return int(round(value))
    return None


def parse(text: str) -> Extraction:
    low = text.lower()
    fields: dict = {}

    for pat in AGE:
        m = re.search(pat, low)
        if m:
            fields["age"] = int(m.group(1))
            break

    for clause in SPLIT.split(low):
        amount = _amount(clause)
        if amount is None:
            continue
        for name, pat in KEYWORDS:
            if re.search(pat, clause) and name not in fields:
                fields[name] = amount
                break

    city = next((c for c in METRO_CITIES | {"bangalore", "bengaluru", "pune", "hyderabad"} if c in low), None)
    if "health_ins_parents" in fields:
        if re.search(r"above 60|over 60|60\+|65\+|senior|\b[6-9]\d\b", low):
            fields["parents_senior"] = True
        elif re.search(r"50s|below 60|under 60", low):
            fields["parents_senior"] = False
    if re.search(r"no hra|don'?t get hra", low):
        fields["hra_received"] = 0
    return Extraction(fields=fields, rent_city=city if "rent_paid" in fields else None)
