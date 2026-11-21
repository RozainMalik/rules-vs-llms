"""
Detector family (a): DECLARATIVE RULES / SCHEMA CHECKS.

Each check is a yes/no statement about the data contract that a human can read
and audit. They are deterministic, cost nothing per row, and their alerts say
exactly which expectation failed and show the offending value.

Signature for every check:  check(batch, refs) -> list[Alert]
"""

from __future__ import annotations

import re

import pandas as pd

from project_b.alerts import Alert
from project_b.schema import (BOROUGHS, EXPECTED_COLUMNS, EXPECTED_DTYPES, ISO_REGEX,
                              NYC_LAT, NYC_LON, parse_dates)

D = "rule"


def _has(batch, *cols):
    return all(c in batch.columns for c in cols)


# (a) renamed / dropped column -------------------------------------------------
def schema_columns(batch, refs):
    missing = [c for c in EXPECTED_COLUMNS if c not in batch.columns]
    extra = [c for c in batch.columns if c not in EXPECTED_COLUMNS]
    if not missing and not extra:
        return []
    return [Alert("a", D, f"Schema check failed: expected column(s) {missing} missing; "
                          f"unexpected column(s) {extra} present.",
                  fields=missing + extra, evidence={"missing": missing, "unexpected": extra})]


# (b) column type change --------------------------------------------------------
def schema_types(batch, refs):
    alerts = []
    for col, dtype in EXPECTED_DTYPES.items():
        if col in batch.columns and str(batch[col].dtype) != dtype:
            sample = batch[col].dropna().head(1).tolist()
            alerts.append(Alert("b", D, f"Column '{col}' has dtype {batch[col].dtype}, contract says {dtype} "
                                        f"(e.g. value {sample!r}).",
                                fields=[col], evidence={"dtype": str(batch[col].dtype), "sample": sample}))
    return alerts


# (c) date format switch ----------------------------------------------------------
def date_format(batch, refs):
    alerts = []
    for col in ("created_date", "closed_date"):
        if col not in batch.columns:
            continue
        s = batch[col]
        bad = s.notna() & ~s.astype(str).str.match(ISO_REGEX)
        for i in batch.index[bad]:
            alerts.append(Alert("c", D, f"'{col}' value '{s[i]}' is not ISO-8601 (YYYY-MM-DDThh:mm:ss.sss).",
                                row=int(i), fields=[col], evidence={col: s[i]}))
    return alerts


# (d) lat/lon swapped --------------------------------------------------------------
def latlon_range(batch, refs):
    if not _has(batch, "latitude", "longitude"):
        return []
    lat = pd.to_numeric(batch["latitude"], errors="coerce")
    lon = pd.to_numeric(batch["longitude"], errors="coerce")
    present = lat.notna() & lon.notna()
    bad = present & ~(lat.between(*NYC_LAT) & lon.between(*NYC_LON))
    alerts = []
    for i in batch.index[bad]:
        swapped = NYC_LAT[0] <= lon[i] <= NYC_LAT[1] and NYC_LON[0] <= lat[i] <= NYC_LON[1]
        why = "values look swapped" if swapped else "outside New York City"
        alerts.append(Alert("d", D, f"latitude {lat[i]} / longitude {lon[i]}: {why} "
                                    f"(expected lat in {NYC_LAT}, lon in {NYC_LON}).",
                            row=int(i), fields=["latitude", "longitude"],
                            evidence={"latitude": lat[i], "longitude": lon[i]}))
    return alerts


# (e) exact duplicates -------------------------------------------------------------
def exact_duplicates(batch, refs):
    dup = batch.duplicated(keep=False)
    return [Alert("e", D, f"Row is an exact duplicate of another row in the batch (unique_key {batch.at[i, 'unique_key']}).",
                  row=int(i), fields=["unique_key"], evidence={"unique_key": str(batch.at[i, "unique_key"])})
            for i in batch.index[dup]]


# (f) near-duplicates ---------------------------------------------------------------
SUFFIXES = {"AVENUE": "AVE", "STREET": "ST", "ROAD": "RD", "BOULEVARD": "BLVD", "PLACE": "PL",
            "PARKWAY": "PKWY", "DRIVE": "DR", "LANE": "LN", "COURT": "CT", "TERRACE": "TER"}


def normalize_address(a) -> str:
    if not isinstance(a, str):
        return ""
    words = re.sub(r"\s+", " ", a.upper().strip()).split(" ")
    return " ".join(SUFFIXES.get(w, w) for w in words)


def near_duplicates(batch, refs, window_s: int = 900):
    """Same complaint, same descriptor, same normalised address, different
    unique_key, created within 15 minutes of each other."""
    if not _has(batch, "incident_address", "complaint_type", "descriptor", "created_date"):
        return []
    t = parse_dates(batch["created_date"])
    key = batch["complaint_type"].astype(str) + "|" + batch["descriptor"].astype(str) + "|" + \
        batch["incident_address"].map(normalize_address)
    df = pd.DataFrame({"key": key, "t": t}).loc[batch["incident_address"].notna() & t.notna()]
    df = df[~batch.loc[df.index].duplicated(keep=False)]       # exact dups are type (e)
    alerts = []
    for _, g in df.groupby("key"):
        if len(g) < 2:
            continue
        g = g.sort_values("t")
        gaps = g["t"].diff().dt.total_seconds()
        close = (gaps <= window_s) | (gaps.shift(-1) <= window_s)
        for i in g.index[close.fillna(False)]:
            alerts.append(Alert("f", D, f"Possible duplicate: same complaint/descriptor at "
                                        f"'{batch.at[i, 'incident_address']}' reported within {window_s // 60} min "
                                        f"by another request (created {batch.at[i, 'created_date']}).",
                                row=int(i), fields=["incident_address", "created_date"],
                                evidence={"incident_address": batch.at[i, "incident_address"]}))
    return alerts


# (g) null spike in one agency ------------------------------------------------------
def agency_null_rate(batch, refs, margin: float = 0.25, min_rows: int = 30):
    """Contract: for every agency and column, the null rate in a batch may exceed
    its historical rate by at most `margin` (absolute)."""
    if "agency" not in batch.columns:
        return []
    alerts = []
    for agency, g in batch.groupby("agency"):
        if len(g) < min_rows:
            continue
        for col in batch.columns:
            base = refs.null_baseline.get((agency, col))
            if base is None:
                continue
            rate = g[col].isna().mean()
            if rate > base + margin:
                alerts.append(Alert("g", D, f"{agency}: '{col}' is null in {rate:.0%} of {len(g)} rows "
                                            f"(historical {base:.0%}, limit {base + margin:.0%}).",
                                    fields=[col, "agency"], evidence={"agency": agency, "rate": round(rate, 3)}))
    return alerts


# (h) closed before created ---------------------------------------------------------
def closed_after_created(batch, refs):
    if not _has(batch, "created_date", "closed_date"):
        return []
    c, cl = parse_dates(batch["created_date"]), parse_dates(batch["closed_date"])
    bad = c.notna() & cl.notna() & (cl < c)
    return [Alert("h", D, f"closed_date {batch.at[i, 'closed_date']} is earlier than created_date {batch.at[i, 'created_date']}.",
                  row=int(i), fields=["created_date", "closed_date"],
                  evidence={"created_date": batch.at[i, "created_date"], "closed_date": batch.at[i, "closed_date"]})
            for i in batch.index[bad]]


# (i) ZIP inconsistent with borough ----------------------------------------------------
def zip_borough(batch, refs, min_share: float = 0.02):
    if not _has(batch, "incident_zip", "borough"):
        return []
    alerts = []
    for i, z, b in zip(batch.index, batch["incident_zip"], batch["borough"]):
        if b not in BOROUGHS or z not in refs.zip_boroughs:
            continue
        allowed = {k for k, v in refs.zip_boroughs[z].items() if v >= min_share}
        if b not in allowed:
            alerts.append(Alert("i", D, f"ZIP {z} belongs to {sorted(allowed)} in reference data, but borough is {b}.",
                                row=int(i), fields=["incident_zip", "borough"],
                                evidence={"incident_zip": z, "borough": b}))
    return alerts


# (j) complaint type vs descriptor --------------------------------------------------------
def complaint_descriptor(batch, refs):
    if not _has(batch, "complaint_type", "descriptor"):
        return []
    alerts = []
    known = set(refs.descriptors_by_complaint)
    for i, ct, d in zip(batch.index, batch["complaint_type"], batch["descriptor"]):
        if ct in known and isinstance(d, str) and refs.pair_counts.get((ct, d), 0) == 0:
            alerts.append(Alert("j", D, f"Descriptor '{d}' never occurs with complaint type '{ct}' in reference data.",
                                row=int(i), fields=["complaint_type", "descriptor"],
                                evidence={"complaint_type": ct, "descriptor": d}))
    return alerts


# (k) resolution contradicts status ----------------------------------------------------
# Hand-written phrase lists, tuned by reading the training months.
PENDING = re.compile(r"will visit|expects to address|is reviewing|conditions are still open|check back later|"
                     r"further investigation is required|for further action|sent you a complaint form|"
                     r"assigned it to|will be made|will investigate", re.I)
DONE = re.compile(r"took action|observed no evidence|issued a summons|were gone|found no condition|"
                  r"collected the|repaired|has been closed|no violations were issued|violations were issued|"
                  r"action was not necessary|cleaned the|removed the|unable to gain entry|"
                  r"provided additional information", re.I)
OPEN = {"Open", "In Progress", "Assigned", "Pending", "Started"}


def resolution_status(batch, refs):
    if not _has(batch, "status", "resolution_description"):
        return []
    alerts = []
    for i, st, txt in zip(batch.index, batch["status"], batch["resolution_description"]):
        if not isinstance(txt, str):
            continue
        if st == "Closed" and PENDING.search(txt) and not DONE.search(txt):
            phrase = PENDING.search(txt).group(0)
            why = f"status is Closed but resolution says work is pending ('{phrase}')"
        elif st in OPEN and DONE.search(txt):
            phrase = DONE.search(txt).group(0)
            why = f"status is {st} but resolution says work is finished ('{phrase}')"
        else:
            continue
        alerts.append(Alert("k", D, why + ".", row=int(i), fields=["status", "resolution_description"],
                            evidence={"status": st, "phrase": phrase}))
    return alerts


# (l) PII in free text ---------------------------------------------------------------
PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")
HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.? [A-Z][a-z]+")
# Official numbers/addresses that appear in agency templates are not personal data
ALLOW = re.compile(r"212-639-9675|\(212\) NEW-YORK|[\w.]+@[a-z.]*nyc\.gov", re.I)


def pii_regex(batch, refs):
    alerts = []
    for col in ("descriptor", "resolution_description"):
        if col not in batch.columns:
            continue
        for i, txt in zip(batch.index, batch[col]):
            if not isinstance(txt, str):
                continue
            cleaned = ALLOW.sub("", txt)
            for kind, rx in (("phone number", PHONE), ("email address", EMAIL), ("name with title", HONORIFIC)):
                # a contact that occurs in >= 5 training rows is a template constant (agency number)
                hits = [m for m in rx.finditer(cleaned) if m.group(0) not in getattr(refs, "template_contacts", ())]
                m = hits[0] if hits else None
                if m:
                    alerts.append(Alert("l", D, f"'{col}' contains a {kind}: '{m.group(0)}'.",
                                        row=int(i), fields=[col], evidence={"match": m.group(0)}))
                    break
    return alerts


CHECKS = {
    "a": schema_columns, "b": schema_types, "c": date_format, "d": latlon_range,
    "e": exact_duplicates, "f": near_duplicates, "g": agency_null_rate, "h": closed_after_created,
    "i": zip_borough, "j": complaint_descriptor, "k": resolution_status, "l": pii_regex,
}
