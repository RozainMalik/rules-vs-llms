"""
The 12 problem types and the Alert every detector returns.

An Alert is either ROW-level (row = batch index of the offending row) or
BATCH-level (row = None), always with a human-readable explanation so the
person on call can act without opening the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

PROBLEMS = {
    "a": "renamed_or_dropped_column",
    "b": "column_type_change",
    "c": "date_format_switch",
    "d": "lat_lon_swapped",
    "e": "exact_duplicates",
    "f": "near_duplicates",
    "g": "agency_null_spike",
    "h": "closed_before_created",
    "i": "zip_borough_mismatch",
    "j": "complaint_descriptor_mismatch",
    "k": "resolution_contradicts_status",
    "l": "pii_in_free_text",
}

# Problems judged per batch (is THIS batch broken?) vs per row (WHICH rows?)
BATCH_LEVEL = {"a", "b", "g"}
ROW_LEVEL = set(PROBLEMS) - BATCH_LEVEL


@dataclass
class Alert:
    problem: str                 # key of PROBLEMS
    detector: str                # "rule" | "stat" | "llm" | "hybrid"
    explanation: str
    row: Optional[int] = None    # batch index; None = batch-level alert
    fields: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)   # offending values

    def as_dict(self) -> dict:
        return {"problem": self.problem, "detector": self.detector, "row": self.row,
                "fields": self.fields, "evidence": self.evidence, "explanation": self.explanation}
