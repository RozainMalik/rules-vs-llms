"""
Reference data, learned ONLY from the training months (Jan-Aug 2023).

Rules and statistical detectors both need to know what "normal" looks like
(which ZIPs belong to which borough, which descriptors go with which complaint
type, ...). We learn it from the data itself — no external sources — and only
from the training split, so the test batches (Sep-Dec) are unseen.

Also defines the CLEAN pool: test-split rows that pass objective sanity checks,
so that false-alarm rates measure the detector, not pre-existing dirt.
"""

from __future__ import annotations

import pickle
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.neighbors import BallTree

from project_b.download import load_raw
from project_b.schema import (BOROUGHS, NYC_LAT, NYC_LON, TRAIN_END, parse_dates, to_typed)

CACHE = Path(__file__).resolve().parent / "results" / "_refs.pkl"
OPEN_STATUSES = {"Open", "In Progress", "Assigned", "Pending", "Started"}
TOKEN = re.compile(r"[A-Za-z][A-Za-z']+|\d+")


@dataclass
class Refs:
    zip_boroughs: dict = field(default_factory=dict)          # zip -> {borough: share}
    zips_by_borough: dict = field(default_factory=dict)       # borough -> [common zips]
    pair_counts: dict = field(default_factory=dict)           # (complaint, descriptor) -> n
    descriptors_by_complaint: dict = field(default_factory=dict)
    null_baseline: dict = field(default_factory=dict)         # (agency, column) -> null rate
    pending_texts: list = field(default_factory=list)         # resolution texts of OPEN work
    closure_texts: list = field(default_factory=list)         # resolution texts of FINISHED work
    duration_floor: dict = field(default_factory=dict)        # complaint -> 0.1th pct of hours
    date_signatures: dict = field(default_factory=dict)       # digit-mask -> share
    column_profiles: dict = field(default_factory=dict)       # column -> profile dict
    text_vocab: set = field(default_factory=set)              # tokens seen in free text
    latlon_from_xy: dict = field(default_factory=dict)        # linear fit coefficients + sigma
    dup_rate: tuple = (0.0, 0.0)                              # mean, std of exact-dup share per batch
    template_contacts: set = field(default_factory=set)       # phones/emails repeated in agency templates
    # fitted models
    geo_tree: object = None
    geo_zips: np.ndarray = None
    desc_vec: object = None
    desc_clf: object = None
    res_vec: object = None
    res_clf: object = None


def date_signature(s: str) -> str:
    return re.sub(r"\d", "9", s)


def column_profile(series: pd.Series) -> dict:
    s = series.dropna()
    as_str = s.astype(str)
    return {
        "null_rate": float(series.isna().mean()),
        "distinct_ratio": float(s.nunique() / max(1, len(s))),
        "mean_len": float(as_str.str.len().mean()) if len(s) else 0.0,
        "numeric_share": float(pd.to_numeric(as_str.str.replace(",", ""), errors="coerce").notna().mean()) if len(s) else 0.0,
        "digit_share": float(as_str.str.count(r"\d").sum() / max(1, as_str.str.len().sum())),
    }


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    created = parse_dates(df["created_date"])
    return df[created < TRAIN_END].copy(), df[created >= TRAIN_END].copy()


def clean_mask(df: pd.DataFrame) -> pd.Series:
    """Objective sanity filter for the clean pool (NOT the detectors under test)."""
    created, closed = parse_dates(df["created_date"]), parse_dates(df["closed_date"])
    m = created.notna() & closed.notna() & (closed >= created) & (closed < "2024-12-31")
    m &= df["latitude"].between(*NYC_LAT) & df["longitude"].between(*NYC_LON)
    m &= df["borough"].isin(BOROUGHS) & df["incident_zip"].notna()
    m &= df["descriptor"].notna() & df["resolution_description"].notna() & df["incident_address"].notna()
    m &= ~df.drop(columns="unique_key").duplicated(keep=False)
    # pre-existing contact details in text (agency phone numbers/emails) would make PII ground truth ambiguous
    m &= ~df["resolution_description"].fillna("").str.contains(r"\d{3}[-.) ]+\d{3}[-. ]\d{4}|@", regex=True)
    m &= ~df["resolution_description"].fillna("").str.contains("â", regex=False)   # mojibake rows
    return m


def build_refs(train: pd.DataFrame) -> Refs:
    r = Refs()

    # --- ZIP <-> borough ----------------------------------------------------
    zb = train[train["borough"].isin(BOROUGHS) & train["incident_zip"].notna()]
    counts = zb.groupby(["incident_zip", "borough"]).size()
    for z, grp in counts.groupby(level=0):
        tot = grp.sum()
        r.zip_boroughs[z] = {b: n / tot for (_, b), n in grp.items()}
    for b in BOROUGHS:
        z = counts.xs(b, level=1)
        main = [k for k in z[z >= 20].index if r.zip_boroughs[k].get(b, 0) > 0.95]
        r.zips_by_borough[b] = sorted(main)

    # --- complaint type <-> descriptor ---------------------------------------
    pc = train.dropna(subset=["complaint_type", "descriptor"]).groupby(["complaint_type", "descriptor"]).size()
    r.pair_counts = {k: int(v) for k, v in pc.items()}
    by = defaultdict(list)
    for (ct, d), n in pc.items():
        if n >= 3:
            by[ct].append(d)
    r.descriptors_by_complaint = dict(by)

    # --- null-rate baseline per agency x column -------------------------------
    for col in train.columns:
        rates = train[col].isna().groupby(train["agency"]).mean()
        for ag, v in rates.items():
            r.null_baseline[(ag, col)] = float(v)

    # --- resolution texts: open vs finished work ------------------------------
    res = train.dropna(subset=["resolution_description"])
    is_open = res["status"].isin(OPEN_STATUSES)
    stats = res.groupby("resolution_description").agg(n=("status", "size"), open_share=("status", lambda s: s.isin(OPEN_STATUSES).mean()))
    r.pending_texts = sorted(stats[(stats.n >= 5) & (stats.open_share >= 0.9)].index)
    r.closure_texts = sorted(stats[(stats.n >= 50) & (stats.open_share <= 0.005)].index)

    # --- duration floor per complaint type ------------------------------------
    hours = (parse_dates(train["closed_date"]) - parse_dates(train["created_date"])).dt.total_seconds() / 3600
    ok = hours >= 0                     # learn from plausible history only
    q = hours[ok].groupby(train.loc[ok, "complaint_type"]).quantile(0.001)
    r.duration_floor = {k: float(v) for k, v in q.items()}

    # --- date format signatures ------------------------------------------------
    sig = pd.concat([train["created_date"], train["closed_date"]]).dropna().map(date_signature)
    r.date_signatures = sig.value_counts(normalize=True).to_dict()

    # --- column value profiles (for the statistical schema detector) ----------
    r.column_profiles = {c: column_profile(train[c]) for c in train.columns}

    # --- free-text vocabulary --------------------------------------------------
    vocab = Counter()
    for col in ("descriptor", "resolution_description"):
        for text in train[col].dropna().unique():
            vocab.update(t.lower() for t in TOKEN.findall(text))
    r.text_vocab = set(vocab)

    # --- lat/lon as a linear function of state-plane x/y ------------------------
    g = train.dropna(subset=["latitude", "longitude", "x_coordinate_state_plane", "y_coordinate_state_plane"])
    for target, src in (("latitude", "y_coordinate_state_plane"), ("longitude", "x_coordinate_state_plane")):
        a, b = np.polyfit(g[src], g[target], 1)
        resid = g[target] - (a * g[src] + b)
        r.latlon_from_xy[target] = (float(a), float(b), float(resid.std()))

    # --- contact details that are part of agency templates (not personal data) -
    from project_b.detectors.rules import EMAIL, PHONE
    found = Counter()
    for text in train["resolution_description"].dropna():
        for rx in (PHONE, EMAIL):
            found.update(m.group(0) for m in rx.finditer(text))
    r.template_contacts = {c for c, n in found.items() if n >= 5}

    # --- normal share of repeated rows in a 2,000-row batch --------------------
    shares = []
    for s in range(20):
        b = train.sample(2000, random_state=s)
        h = pd.util.hash_pandas_object(b.astype(str), index=False)
        shares.append(float(h.duplicated(keep=False).mean()))
    r.dup_rate = (float(np.mean(shares)), float(np.std(shares)))

    # --- geo nearest neighbours: which ZIPs occur near a point -----------------
    geo = train.dropna(subset=["latitude", "longitude", "incident_zip"]).sample(60000, random_state=0)
    r.geo_tree = BallTree(np.radians(geo[["latitude", "longitude"]].to_numpy()), metric="haversine")
    r.geo_zips = geo["incident_zip"].to_numpy()

    # --- text classifiers ----------------------------------------------------
    d = train.dropna(subset=["descriptor", "complaint_type"])
    r.desc_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2, sublinear_tf=True)
    X = r.desc_vec.fit_transform(d["descriptor"])
    r.desc_clf = MultinomialNB(alpha=0.01).fit(X, d["complaint_type"])

    s = res[res["status"].isin(OPEN_STATUSES | {"Closed"})]
    r.res_vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    X = r.res_vec.fit_transform(s["resolution_description"])
    y = np.where(s["status"] == "Closed", "closed", "open")
    r.res_clf = LogisticRegression(max_iter=2000, class_weight="balanced").fit(X, y)
    return r


def load_data(rebuild: bool = False):
    """Returns (refs, clean_test_pool, train, test). Cached to results/_refs.pkl."""
    if CACHE.exists() and not rebuild:
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    typed = to_typed(load_raw())
    train, test = split(typed)
    refs = build_refs(train)
    pool = test[clean_mask(test)].reset_index(drop=True)
    CACHE.parent.mkdir(exist_ok=True)
    out = (refs, pool, train, test)
    with open(CACHE, "wb") as f:
        pickle.dump(out, f)
    return out
