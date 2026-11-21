"""
Corruption injector (Task 2).

inject(problem, clean_batch, rate, seed, refs) -> Injected

Returns the corrupted batch plus GROUND TRUTH:
  - row_labels: boolean Series (index = batch index), True = this row was corrupted
  - meta: what exactly was done (column renamed, agency affected, ...)
For batch-level problems (a, b, g) the whole batch is the positive.

Everything is driven by a numpy Generator seeded by the caller, so every
corrupted batch is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from project_b.schema import NUMERIC_COLUMNS, parse_dates

# Socrata's display names — a realistic "someone renamed the column" scenario
DISPLAY_NAMES = {
    "incident_zip": "Incident Zip", "complaint_type": "Complaint Type", "borough": "Borough",
    "created_date": "Created Date", "closed_date": "Closed Date", "descriptor": "Descriptor",
    "status": "Status", "agency": "Agency", "latitude": "Latitude", "longitude": "Longitude",
    "resolution_description": "Resolution Description",
}

FIRST = ["James", "Maria", "Michael", "Jennifer", "David", "Linda", "Jose", "Priya", "Wei", "Fatima",
         "Robert", "Aisha", "Daniel", "Sofia", "Kevin", "Rosa", "Ahmed", "Emily", "Carlos", "Grace"]
LAST = ["Smith", "Rodriguez", "Johnson", "Nguyen", "Williams", "Garcia", "Brown", "Patel", "Lee",
        "Martinez", "Cohen", "Okafor", "Kim", "Rivera", "Murphy", "Singh", "Chen", "Lopez", "Davis", "Khan"]


@dataclass
class Injected:
    problem: str
    batch: pd.DataFrame
    row_labels: pd.Series                     # bool per row of the CORRUPTED batch
    meta: dict = field(default_factory=dict)


def _pick(rng: np.random.Generator, candidates: pd.Index, rate: float) -> pd.Index:
    k = max(1, int(round(len(candidates) * rate)))
    k = min(k, len(candidates))
    return pd.Index(rng.choice(candidates.to_numpy(), size=k, replace=False))


def _iso(ts: pd.Series) -> pd.Series:
    return ts.dt.strftime("%Y-%m-%dT%H:%M:%S.000")


# ---------------------------------------------------------------------------
# one function per problem type
# ---------------------------------------------------------------------------
def _a_rename_or_drop(df, rng, rate, refs):
    col = str(rng.choice(list(DISPLAY_NAMES)))
    if rng.random() < 0.5:
        df = df.drop(columns=[col])
        meta = {"op": "drop", "column": col}
    else:
        df = df.rename(columns={col: DISPLAY_NAMES[col]})
        meta = {"op": "rename", "column": col, "new_name": DISPLAY_NAMES[col]}
    return df, pd.Series(True, index=df.index), meta


def _b_type_change(df, rng, rate, refs):
    col = str(rng.choice(NUMERIC_COLUMNS + ["unique_key"]))
    if col.startswith(("x_", "y_")):
        fmt = lambda v: f"{int(v):,}"            # "1,004,092"  (thousands separator)
    elif col == "unique_key":
        fmt = lambda v: str(int(v))
    else:
        fmt = lambda v: f"{v:.6f}"
    df[col] = df[col].map(lambda v: None if pd.isna(v) else fmt(v)).astype(object)
    return df, pd.Series(True, index=df.index), {"column": col}


def _c_date_switch(df, rng, rate, refs):
    start = int(len(df) * rng.uniform(0.3, 0.7))
    rows = df.index[start:]
    for col in ("created_date", "closed_date"):
        ts = parse_dates(df.loc[rows, col])
        df.loc[rows, col] = ts.dt.strftime("%m/%d/%Y %I:%M:%S %p").where(ts.notna(), None)
    labels = pd.Series(False, index=df.index)
    labels.loc[rows] = df.loc[rows, "created_date"].notna()
    return df, labels, {"switch_at_position": start, "format": "%m/%d/%Y %I:%M:%S %p"}


def _d_swap_latlon(df, rng, rate, refs):
    rows = _pick(rng, df.index[df["latitude"].notna() & df["longitude"].notna()], rate)
    df.loc[rows, ["latitude", "longitude"]] = df.loc[rows, ["longitude", "latitude"]].to_numpy()
    labels = pd.Series(False, index=df.index)
    labels.loc[rows] = True
    return df, labels, {"n": len(rows)}


def _insert_copies(df, copies, rng):
    """Append copies and move each to a random position; returns (df, labels).
    BOTH the original and its copy are labelled True: a duplicate is a pair,
    and a detector that flags either member of the pair has found it."""
    copies = copies.copy()
    copies["_is_copy"] = True
    base = df.assign(_is_copy=False)
    base.loc[copies.index, "_is_copy"] = True          # the originals
    out = pd.concat([base, copies], ignore_index=True)
    order = rng.permutation(len(out))
    out = out.iloc[order].reset_index(drop=True)
    labels = out.pop("_is_copy").astype(bool)
    return out, labels


def _e_exact_dupes(df, rng, rate, refs):
    src = _pick(rng, df.index, rate)
    out, labels = _insert_copies(df, df.loc[src], rng)
    return out, labels, {"n": len(src)}


ABBREV = [(" AVENUE", " AVE"), (" STREET", " ST"), (" ROAD", " RD"), (" BOULEVARD", " BLVD"), (" PLACE", " PL")]


def _f_near_dupes(df, rng, rate, refs):
    src = _pick(rng, df.index[df["created_date"].notna()], rate)
    copies = df.loc[src].copy()
    copies["unique_key"] = (copies["unique_key"] + 90_000_000).astype("Int64")   # new request id
    shift = pd.to_timedelta(rng.integers(1, 600, size=len(copies)), unit="s")      # 1 s .. 10 min
    for col in ("created_date", "closed_date"):
        ts = parse_dates(copies[col])
        copies[col] = _iso(ts + shift).where(ts.notna(), None)

    def alter(addr):
        if not isinstance(addr, str):
            return addr
        for long, short in ABBREV:
            if long in addr:
                return addr.replace(long, short)
        return addr.title()                     # case change if no abbreviation applies
    copies["incident_address"] = copies["incident_address"].map(alter)
    out, labels = _insert_copies(df, copies, rng)
    return out, labels, {"n": len(src)}


NULLABLE_FOR_SPIKE = ["incident_zip", "descriptor", "resolution_description", "location_type",
                      "incident_address", "latitude", "longitude", "community_board"]


def _g_null_spike(df, rng, rate, refs):
    counts = df["agency"].value_counts()
    agency = str(rng.choice(counts[counts >= 40].index.to_numpy()))
    col = str(rng.choice(NULLABLE_FOR_SPIKE))
    rows = df.index[(df["agency"] == agency) & df[col].notna()]
    rows = _pick(rng, rows, 0.7)                         # 70% of that agency's values vanish
    df.loc[rows, col] = np.nan if col in NUMERIC_COLUMNS else None
    labels = pd.Series(True, index=df.index)
    return df, labels, {"agency": agency, "column": col, "n_nulled": len(rows)}


def _h_closed_before_created(df, rng, rate, refs):
    created = parse_dates(df["created_date"])
    rows = _pick(rng, df.index[created.notna() & df["closed_date"].notna()], rate)
    back = pd.to_timedelta(rng.integers(60, 30 * 86400, size=len(rows)), unit="s")
    df.loc[rows, "closed_date"] = _iso(created.loc[rows] - back).to_numpy()
    labels = pd.Series(False, index=df.index)
    labels.loc[rows] = True
    return df, labels, {"n": len(rows)}


def _i_zip_borough(df, rng, rate, refs):
    rows = _pick(rng, df.index[df["borough"].isin(refs.zips_by_borough) & df["incident_zip"].notna()], rate)
    for r in rows:
        other = [b for b in refs.zips_by_borough if b != df.at[r, "borough"]]
        b = str(rng.choice(other))
        df.at[r, "incident_zip"] = str(rng.choice(refs.zips_by_borough[b]))
    labels = pd.Series(False, index=df.index)
    labels.loc[rows] = True
    return df, labels, {"n": len(rows)}


def _j_complaint_descriptor(df, rng, rate, refs):
    ok = df["complaint_type"].isin(refs.descriptors_by_complaint) & df["descriptor"].notna()
    rows = _pick(rng, df.index[ok], rate)
    all_types = list(refs.descriptors_by_complaint)
    for r in rows:
        ct = df.at[r, "complaint_type"]
        own = set(refs.descriptors_by_complaint[ct])
        while True:
            other = all_types[rng.integers(len(all_types))]
            cands = [d for d in refs.descriptors_by_complaint[other] if d not in own]
            if other != ct and cands:
                break
        df.at[r, "descriptor"] = cands[rng.integers(len(cands))]
    labels = pd.Series(False, index=df.index)
    labels.loc[rows] = True
    return df, labels, {"n": len(rows)}


def _k_resolution_status(df, rng, rate, refs):
    """Two realistic mechanisms, half each:
       1. a Closed row gets a resolution text that says the work is still pending
          (texts learned from training rows whose status was NOT closed)
       2. a Closed row whose text clearly says the work is done has its status
          flipped to an open state
    """
    closed = df.index[(df["status"] == "Closed") & df["resolution_description"].notna()]
    done = df.index[(df["status"] == "Closed") & df["resolution_description"].isin(refs.closure_texts)]
    k = max(2, int(round(len(df) * rate)))
    flip = _pick(rng, done, min(1.0, (k // 2) / max(1, len(done))))
    swap = _pick(rng, closed.difference(flip), min(1.0, (k - len(flip)) / max(1, len(closed))))
    for r in swap:
        df.at[r, "resolution_description"] = refs.pending_texts[rng.integers(len(refs.pending_texts))]
    for r in flip:
        df.at[r, "status"] = str(rng.choice(["Open", "In Progress", "Assigned"]))
    labels = pd.Series(False, index=df.index)
    labels.loc[swap.union(flip)] = True
    return df, labels, {"n_text_swapped": len(swap), "n_status_flipped": len(flip)}


def _fake_phone(rng):
    a, b, c = rng.choice([212, 347, 646, 718, 917, 929]), rng.integers(200, 999), rng.integers(1000, 9999)
    return str(rng.choice([f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}{b}{c}", f"{a}.{b}.{c}"]))


def _pii_snippet(rng):
    first, last = FIRST[rng.integers(len(FIRST))], LAST[rng.integers(len(LAST))]
    kind = rng.integers(3)
    if kind == 0:
        return f" Caller {first} {last} can be reached at {_fake_phone(rng)}.", "phone+name"
    if kind == 1:
        return f" Contact {first.lower()}.{last.lower()}{rng.integers(10, 99)}@gmail.com for access.", "email"
    return f" Spoke with tenant {first} {last} on site.", "name_only"


def _l_pii(df, rng, rate, refs):
    rows = _pick(rng, df.index[df["resolution_description"].notna()], rate)
    kinds = {}
    for r in rows:
        snippet, kind = _pii_snippet(rng)
        col = "resolution_description" if rng.random() < 0.8 else "descriptor"
        df.at[r, col] = f"{df.at[r, col] or ''}{snippet}".strip()
        kinds[kind] = kinds.get(kind, 0) + 1
    labels = pd.Series(False, index=df.index)
    labels.loc[rows] = True
    return df, labels, {"n": len(rows), "kinds": kinds}


INJECTORS = {
    "a": _a_rename_or_drop, "b": _b_type_change, "c": _c_date_switch, "d": _d_swap_latlon,
    "e": _e_exact_dupes, "f": _f_near_dupes, "g": _g_null_spike, "h": _h_closed_before_created,
    "i": _i_zip_borough, "j": _j_complaint_descriptor, "k": _k_resolution_status, "l": _l_pii,
}


def inject(problem: str, clean: pd.DataFrame, rate: float, seed: int, refs) -> Injected:
    rng = np.random.default_rng(seed)
    df = clean.copy().reset_index(drop=True)
    out, labels, meta = INJECTORS[problem](df, rng, rate, refs)
    return Injected(problem, out.reset_index(drop=True), labels.reset_index(drop=True), meta)
