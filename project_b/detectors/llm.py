"""
Detector family (c): LLM REVIEW (Gemini, via common/llm.py).

Row-level problems: the LLM sees a chunk of rows (only the columns relevant to
the problem, ~40 rows per call) and returns which rows are wrong and why.
Batch-level problems (a, b, g): the LLM sees the header, dtypes and a sample
of rows and answers "is this batch broken?".

The LLM never sees the whole batch — at ~2,000 rows per batch that would cost
50 calls per batch per problem. In evaluation we review SAMPLES and extrapolate
cost per million rows from measured tokens.

Every call goes through common.llm (cached, rate-limited), and USAGE collects
the token counts and latencies for the cost report.
"""

from __future__ import annotations

import json

import pandas as pd

from common.llm import LLM, LLMResponse, parse_json
from project_b.alerts import Alert
from project_b.schema import EXPECTED_COLUMNS, EXPECTED_DTYPES

D = "llm"
USAGE: list[tuple[str, int, LLMResponse]] = []      # (problem, rows reviewed, response)
_llm = LLM()

SYSTEM = ("You are a meticulous data-quality reviewer for NYC 311 service-request data. "
          "Report only real problems of the requested type. Answer with JSON only.")

ROW_TASKS = {
    "c": (["created_date", "closed_date"],
          "Flag rows whose created_date or closed_date uses a different date format from the API's ISO-8601 "
          "format (YYYY-MM-DDThh:mm:ss.sss)."),
    "d": (["latitude", "longitude", "borough", "incident_zip"],
          "Flag rows whose latitude and longitude look swapped (NYC latitude is about 40.5-40.9, longitude about -74.3 to -73.7)."),
    "e": (["unique_key", "created_date", "complaint_type", "descriptor", "incident_address", "status"],
          "Flag rows that are EXACT duplicates of another row in this list (every field identical, including unique_key)."),
    "f": (["unique_key", "created_date", "complaint_type", "descriptor", "incident_address", "borough"],
          "Flag rows that are near-duplicates of another row in this list: the same request recorded twice with a different "
          "unique_key, a timestamp a few seconds/minutes apart, or slightly altered text (e.g. 'AVENUE' vs 'AVE')."),
    "h": (["created_date", "closed_date", "status"],
          "Flag rows whose closed_date is earlier than created_date."),
    "i": (["incident_zip", "borough", "city", "incident_address"],
          "Flag rows whose ZIP code is not in the stated borough."),
    "j": (["complaint_type", "descriptor"],
          "Flag rows whose descriptor does not make sense for the complaint type (it describes a different kind of complaint)."),
    "k": (["status", "resolution_description"],
          "Flag rows whose resolution_description contradicts the status: e.g. status Closed but the text says work is "
          "still pending/will happen, or an open status (Open, In Progress, Assigned, Pending) but the text says the work was "
          "completed or the complaint was closed."),
    "l": (["descriptor", "resolution_description"],
          "Flag rows whose free text contains personal data about a member of the public: phone numbers, email addresses or "
          "person names. Official agency phone numbers/websites in standard templates are NOT personal data."),
}

BATCH_TASKS = {
    "a": "Compare the batch's column names with the expected schema. Is any expected column missing or renamed?",
    "b": "Compare the batch's column dtypes with the expected dtypes. Has any column changed type (e.g. numbers arriving as strings)?",
    "g": "Look at the sample. Does any single agency have an unusually high share of missing (null) values in some column?",
}


def _fmt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return None
    return v.item() if hasattr(v, "item") else v


def review_rows(problem: str, batch: pd.DataFrame, rows: list[int], sample: int = 0) -> list[Alert]:
    cols, task = ROW_TASKS[problem]
    cols = [c for c in cols if c in batch.columns]
    lines = [json.dumps({"row": int(i), **{c: _fmt(batch.at[i, c]) for c in cols}}, default=str) for i in rows]
    prompt = (f"TASK: {task}\n\nRows (one JSON object per line):\n" + "\n".join(lines) +
              '\n\nReturn {"flags": [{"row": <row number>, "explanation": "<which field, what is wrong, the value>"}]}. '
              'Return {"flags": []} if no row has this problem.')
    resp = _llm.generate(prompt, system=SYSTEM, json_mode=True, sample=sample)
    USAGE.append((problem, len(rows), resp))
    try:
        data = parse_json(resp.text)
    except ValueError:
        return []
    # The model sometimes returns a bare list instead of {"flags": [...]}.
    # Treating that as "no flags" was a silent failure (found while debugging k).
    flags = data if isinstance(data, list) else data.get("flags", []) if isinstance(data, dict) else []
    valid = set(int(i) for i in rows)
    out = []
    for f in flags:
        try:
            r = int(f.get("row"))
        except (TypeError, ValueError):
            continue
        if r in valid:
            out.append(Alert(problem, D, str(f.get("explanation", "")), row=r, fields=cols))
    return out


def review_batch(problem: str, batch: pd.DataFrame, n_sample: int = 40, seed: int = 0) -> list[Alert]:
    sample = batch.sample(min(n_sample, len(batch)), random_state=seed)
    if problem == "g":
        show = [c for c in ["agency", "incident_zip", "descriptor", "resolution_description", "location_type",
                            "incident_address", "latitude", "longitude", "community_board"] if c in batch.columns]
        body = "Sample rows:\n" + sample[show].to_csv(index=False)
    else:
        body = (f"Expected columns: {EXPECTED_COLUMNS}\nExpected dtypes (others are strings): {EXPECTED_DTYPES}\n\n"
                f"Batch columns and dtypes: {[(c, str(t)) for c, t in batch.dtypes.items()]}\n\n"
                "First rows:\n" + batch.head(3).to_csv(index=False))
    prompt = (f"TASK: {BATCH_TASKS[problem]}\n\n{body}\n\n"
              'Return {"problem_found": true/false, "explanation": "<which column/agency, what is wrong, evidence>"}.')
    resp = _llm.generate(prompt, system=SYSTEM, json_mode=True)
    USAGE.append((problem, len(sample) if problem == "g" else len(batch), resp))
    try:
        data = parse_json(resp.text)
    except ValueError:
        return []
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if data.get("problem_found"):
        return [Alert(problem, D, str(data.get("explanation", "")))]
    return []


def check(problem: str, batch: pd.DataFrame, rows: list[int] | None = None, chunk: int = 40) -> list[Alert]:
    """Uniform entry point. Row-level: reviews `rows` (default: first `chunk` rows) in chunks."""
    if problem in BATCH_TASKS:
        return review_batch(problem, batch)
    rows = list(batch.index[:chunk]) if rows is None else list(rows)
    alerts = []
    for s in range(0, len(rows), chunk):
        alerts += review_rows(problem, batch, rows[s:s + chunk])
    return alerts
