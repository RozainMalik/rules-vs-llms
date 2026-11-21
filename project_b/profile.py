"""
Task 1: profile the RAW 2023 sample and document real quality problems,
with counts and concrete examples. Writes results/profile.json.

Run:  python -m project_b.profile
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from project_b.detectors import rules
from project_b.download import load_raw
from project_b.schema import BOROUGHS, NYC_LAT, NYC_LON, parse_dates, to_typed

RESULTS = Path(__file__).resolve().parent / "results"
SNAPSHOT = pd.Timestamp("2026-11-21")       # day the sample was downloaded
KEY = ["unique_key", "created_date", "closed_date", "agency", "complaint_type", "status"]


def _issue(df, mask, description, cols=KEY, n_examples=3):
    mask = pd.Series(mask, index=df.index).fillna(False).astype(bool)
    ex = df.loc[mask, list(dict.fromkeys(cols))].head(n_examples)
    return {"description": description, "count": int(mask.sum()), "pct": round(100 * mask.mean(), 3),
            "by_agency": df.loc[mask, "agency"].value_counts().head(5).to_dict(),
            "examples": json.loads(ex.to_json(orient="records", default_handler=str))}


def profile() -> dict:
    raw = load_raw()
    df = to_typed(raw)
    created, closed = parse_dates(df["created_date"]), parse_dates(df["closed_date"])
    updated = parse_dates(df["resolution_action_updated_date"])
    lat, lon = df["latitude"], df["longitude"]
    hours = (closed - created).dt.total_seconds() / 3600
    out = {"rows": len(df), "columns": len(df.columns),
           "created_range": [str(created.min()), str(created.max())],
           "null_rate_pct": (df.isna().mean() * 100).round(2).sort_values(ascending=False).to_dict()}
    issues = {}

    # --- time ------------------------------------------------------------------
    issues["closed_before_created"] = _issue(df, closed < created, "closed_date earlier than created_date")
    issues["zero_duration"] = _issue(df, closed == created, "closed_date exactly equals created_date (closed instantly)")
    issues["closed_after_snapshot"] = _issue(df, closed > SNAPSHOT, "closed_date in the future relative to download date")
    issues["open_over_1_year"] = _issue(df, hours > 365 * 24, "closed more than 365 days after creation")
    issues["update_before_created"] = _issue(df, updated < created, "resolution_action_updated_date before created_date",
                                             KEY + ["resolution_action_updated_date"])
    issues["closed_status_no_closed_date"] = _issue(df, (df["status"] == "Closed") & closed.isna(), "status Closed but closed_date missing")
    issues["open_status_with_closed_date"] = _issue(df, df["status"].isin(rules.OPEN) & closed.notna(),
                                                    "open-type status but a closed_date is present")
    issues["due_date_mostly_empty"] = _issue(df, df["due_date"].isna(), "due_date is empty (column nearly dead)")

    # --- location --------------------------------------------------------------
    issues["missing_coordinates"] = _issue(df, lat.isna() | lon.isna(), "latitude/longitude missing", KEY + ["incident_address"])
    issues["coords_outside_nyc"] = _issue(df, lat.notna() & ~(lat.between(*NYC_LAT) & lon.between(*NYC_LON)), "coordinates outside NYC box")
    issues["borough_unspecified"] = _issue(df, df["borough"] == "Unspecified", "borough is 'Unspecified'", KEY + ["incident_zip", "borough"])
    issues["missing_zip"] = _issue(df, df["incident_zip"].isna(), "incident_zip missing", KEY + ["incident_address"])
    zb = df[df["borough"].isin(BOROUGHS) & df["incident_zip"].notna()].groupby(["incident_zip", "borough"]).size()
    share = zb / zb.groupby(level=0).transform("sum")
    rare = set(share[share < 0.02].index)
    issues["zip_borough_mismatch"] = _issue(df, pd.Series([(z, b) in rare for z, b in zip(df["incident_zip"], df["borough"])], index=df.index),
                                            "ZIP/borough pair accounts for <2% of that ZIP's rows (likely wrong)",
                                            KEY + ["incident_zip", "borough", "incident_address"])
    city_mismatch = df["city"].isin(BOROUGHS) & df["borough"].isin(BOROUGHS) & (df["city"] != df["borough"]) & (df["city"] != "NEW YORK")
    issues["city_borough_mismatch"] = _issue(df, city_mismatch, "city is a borough name different from the borough column",
                                             KEY + ["city", "borough"])

    # --- duplicates -----------------------------------------------------------
    issues["duplicate_rows_except_key"] = _issue(df, df.drop(columns="unique_key").duplicated(keep=False),
                                                 "rows identical in every column except unique_key",
                                                 KEY + ["descriptor", "incident_address"])
    near = {a.row for a in rules.near_duplicates(df, None)}
    issues["near_duplicates"] = _issue(df, df.index.isin(near), "same complaint/descriptor/address within 15 minutes",
                                       KEY + ["descriptor", "incident_address"])

    # --- categories & text -------------------------------------------------------
    ct = df["complaint_type"].dropna()
    variants = ct.groupby(ct.str.lower().str.strip()).agg(lambda s: sorted(set(s)))
    variants = variants[variants.map(len) > 1]
    issues["complaint_type_case_variants"] = {"description": "complaint types that differ only by case/spacing",
                                              "count": int(len(variants)), "examples": variants.head(8).to_dict()}
    issues["missing_descriptor"] = _issue(df, df["descriptor"].isna(), "descriptor missing", KEY + ["descriptor"])
    issues["missing_resolution"] = _issue(df, df["resolution_description"].isna(), "resolution_description missing",
                                          KEY + ["resolution_description"])
    k_rows = {a.row for a in rules.resolution_status(df, None)}
    issues["resolution_contradicts_status"] = _issue(df, df.index.isin(k_rows), "status vs resolution text contradiction (rule k)",
                                                     ["unique_key", "agency", "status", "resolution_description"])
    res = df["resolution_description"].fillna("")
    issues["mojibake_in_text"] = _issue(df, res.str.contains("â", regex=False), "UTF-8 decoded as Latin-1 (e.g. 'Parksâ')",
                                        ["unique_key", "agency", "resolution_description"])
    issues["phone_in_text"] = _issue(df, res.str.contains(rules.PHONE), "phone-number pattern in resolution text",
                                     ["unique_key", "agency", "resolution_description"])
    issues["email_in_text"] = _issue(df, res.str.contains(rules.EMAIL), "email pattern in resolution text",
                                     ["unique_key", "agency", "resolution_description"])
    phones = res.str.findall(rules.PHONE).explode().dropna().value_counts().head(5).to_dict()
    emails = res.str.findall(rules.EMAIL).explode().dropna().value_counts().head(5).to_dict()
    issues["phone_in_text"]["top_values"] = phones
    issues["email_in_text"]["top_values"] = emails

    out["issues"] = issues
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "profile.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    p = profile()
    for k, v in p["issues"].items():
        print(f"{k:34} {v['count']:>8,}  {v.get('pct', '')}")
