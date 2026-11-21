"""
The data contract for a batch of 311 rows, plus the train/test split.

A *batch* is a pandas DataFrame with EXPECTED_COLUMNS and these dtypes:
  - numeric columns  -> float64 / Int64
  - date columns     -> ISO-8601 strings, exactly as the API delivers them
                        (kept as strings so a date-format switch is observable)
  - everything else  -> object (str), missing = NaN
"""

from __future__ import annotations

import pandas as pd

from project_b.download import COLUMNS

EXPECTED_COLUMNS: list[str] = list(COLUMNS)

NUMERIC_COLUMNS = ["x_coordinate_state_plane", "y_coordinate_state_plane", "latitude", "longitude"]
INT_COLUMNS = ["unique_key"]
DATE_COLUMNS = ["created_date", "closed_date", "due_date", "resolution_action_updated_date"]
TEXT_COLUMNS = ["descriptor", "resolution_description"]          # free text checked for PII

EXPECTED_DTYPES = {c: "float64" for c in NUMERIC_COLUMNS}
EXPECTED_DTYPES.update({c: "Int64" for c in INT_COLUMNS})

# ISO format the API uses: 2023-01-01T00:59:51.000
ISO_REGEX = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?$"

# Generous bounding box around the five boroughs
NYC_LAT = (40.47, 40.93)
NYC_LON = (-74.27, -73.68)

BOROUGHS = ["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"]

# Train = Jan-Aug (reference data is learned here), Test = Sep-Dec (batches come from here)
TRAIN_END = "2023-09-01"


def to_typed(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw all-string frame -> typed frame following the contract."""
    df = raw.copy()
    df = df.replace("", pd.NA)
    for c in NUMERIC_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in INT_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for c in df.columns:
        if c not in NUMERIC_COLUMNS and c not in INT_COLUMNS:
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


def parse_dates(s: pd.Series) -> pd.Series:
    """Strict ISO parse; anything else becomes NaT."""
    return pd.to_datetime(s, format="%Y-%m-%dT%H:%M:%S.%f", errors="coerce")
