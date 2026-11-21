"""
Detector family (b): STATISTICAL / ML DETECTORS.

Instead of a hand-written contract, each detector compares the batch with what
the training months looked like (frequencies, distributions, fitted models) and
flags what is improbable. Deterministic given the fitted refs, cheap, but the
explanation is a score ("probability 0.001") rather than a broken rule.

Signature for every check:  check(batch, refs) -> list[Alert]
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

from project_b.alerts import Alert
from project_b.refs import TOKEN, column_profile, date_signature
from project_b.schema import EXPECTED_COLUMNS, NUMERIC_COLUMNS, parse_dates

D = "stat"


# (a) column profiles: every expected column must be present with a similar value profile
def profile_match(batch, refs, tol: float = 0.35):
    alerts = []
    for col in EXPECTED_COLUMNS:
        ref = refs.column_profiles[col]
        if col not in batch.columns:
            # find the batch column whose value profile is closest (rename detection)
            best, best_d = None, 9.0
            for other in batch.columns:
                if other in EXPECTED_COLUMNS:
                    continue
                p = column_profile(batch[other])
                d = sum(abs(p[k] - ref[k]) / (1 + abs(ref[k])) for k in ("null_rate", "distinct_ratio", "digit_share", "numeric_share"))
                if d < best_d:
                    best, best_d = other, d
            hint = f"; column '{best}' has a matching value profile (likely renamed)" if best is not None and best_d < tol else ""
            alerts.append(Alert("a", D, f"No column with the profile of '{col}' under that name{hint}.",
                                fields=[col], evidence={"closest": best, "distance": round(best_d, 3)}))
    return alerts


# (b) numeric columns: parse rate and value distribution vs training
def numeric_profile(batch, refs):
    alerts = []
    for col in NUMERIC_COLUMNS:
        if col not in batch.columns:
            continue
        s = batch[col]
        vals = pd.to_numeric(s, errors="coerce")
        parse_rate = vals.notna().sum() / max(1, s.notna().sum())
        ref_null = refs.column_profiles[col]["null_rate"]
        if parse_rate < 0.99:
            alerts.append(Alert("b", D, f"Only {parse_rate:.0%} of non-null '{col}' values parse as numbers "
                                        f"(training: ~100%); e.g. {s.dropna().head(1).tolist()}.",
                                fields=[col], evidence={"parse_rate": round(parse_rate, 3)}))
        elif vals.isna().mean() > ref_null + 0.2:
            alerts.append(Alert("b", D, f"'{col}' null rate {vals.isna().mean():.0%} vs training {ref_null:.0%}.",
                                fields=[col], evidence={}))
    return alerts


# (c) date formats: digit-mask signature never/rarely seen in training
def date_signature_rarity(batch, refs, min_share: float = 1e-4):
    alerts = []
    for col in ("created_date", "closed_date"):
        if col not in batch.columns:
            continue
        for i, v in batch[col].dropna().items():
            sig = date_signature(str(v))
            share = refs.date_signatures.get(sig, 0.0)
            if share < min_share:
                alerts.append(Alert("c", D, f"'{col}' value '{v}' has format '{sig}' seen in {share:.2%} of training dates.",
                                    row=int(i), fields=[col], evidence={col: v, "signature": sig}))
    return alerts


# (d) lat/lon must agree with state-plane x/y (fitted linear map), else robust z-score
def geo_consistency(batch, refs, k: float = 50.0):
    if not all(c in batch.columns for c in ("latitude", "longitude")):
        return []
    lat = pd.to_numeric(batch["latitude"], errors="coerce")
    lon = pd.to_numeric(batch["longitude"], errors="coerce")
    alerts = []
    have_xy = all(c in batch.columns for c in ("x_coordinate_state_plane", "y_coordinate_state_plane"))
    x = pd.to_numeric(batch["x_coordinate_state_plane"], errors="coerce") if have_xy else None
    y = pd.to_numeric(batch["y_coordinate_state_plane"], errors="coerce") if have_xy else None
    a_lat, b_lat, s_lat = refs.latlon_from_xy["latitude"]
    a_lon, b_lon, s_lon = refs.latlon_from_xy["longitude"]
    for i in batch.index[lat.notna() & lon.notna()]:
        if have_xy and pd.notna(x[i]) and pd.notna(y[i]):
            z = max(abs(lat[i] - (a_lat * y[i] + b_lat)) / s_lat, abs(lon[i] - (a_lon * x[i] + b_lon)) / s_lon)
            basis = "state-plane x/y"
        else:
            z = max(abs(lat[i] - 40.72) / 0.09, abs(lon[i] + 73.92) / 0.1)   # median / spread of NYC
            basis = "city-wide distribution"
        if z > k:
            alerts.append(Alert("d", D, f"latitude {lat[i]:.5f} / longitude {lon[i]:.5f} deviate {z:,.0f} sigma "
                                        f"from the position implied by {basis}.",
                                row=int(i), fields=["latitude", "longitude"], evidence={"z": round(float(z), 1)}))
    return alerts


# (e) duplicate-rate monitor: alarm when the share of repeated rows is far above normal
def duplicate_rate(batch, refs, z: float = 4.0):
    hashes = pd.util.hash_pandas_object(batch.astype(str), index=False)
    counts = hashes.map(hashes.value_counts())
    share = (counts > 1).mean()
    mean, std = refs.dup_rate
    if share <= mean + z * max(std, 1e-4):
        return []
    return [Alert("e", D, f"Row hash occurs {counts[i]}x; batch duplicate share {share:.1%} vs normal {mean:.2%}.",
                  row=int(i), fields=["(all columns)"], evidence={"share": round(float(share), 4)})
            for i in batch.index[counts > 1]]


# (f) near-duplicates: TF-IDF char n-grams on the request text, nearest neighbour in time
def tfidf_near_duplicates(batch, refs, sim: float = 0.9, window_s: int = 900):
    cols = ["complaint_type", "descriptor", "incident_address", "borough"]
    if not all(c in batch.columns for c in cols + ["created_date"]):
        return []
    text = batch[cols].fillna("").astype(str).agg(" | ".join, axis=1).str.upper()
    t = parse_dates(batch["created_date"])
    ok = t.notna() & batch["incident_address"].notna() & ~batch.duplicated(keep=False)
    idx = batch.index[ok]
    if len(idx) < 2:
        return []
    X = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4)).fit_transform(text[idx])
    nn = NearestNeighbors(n_neighbors=min(6, len(idx)), metric="cosine").fit(X)
    dist, nbr = nn.kneighbors(X)
    secs = t[idx].astype("int64").to_numpy() / 1e9
    alerts = []
    for a in range(len(idx)):
        for d, b in zip(dist[a][1:], nbr[a][1:]):
            if 1 - d >= sim and abs(secs[a] - secs[b]) <= window_s:
                i, j = idx[a], idx[b]
                alerts.append(Alert("f", D, f"Text similarity {1 - d:.2f} with row {j} created "
                                            f"{abs(secs[a] - secs[b]):.0f}s apart ('{batch.at[i, 'incident_address']}').",
                                    row=int(i), fields=cols, evidence={"other_row": int(j), "similarity": round(1 - d, 3)}))
                break
    return alerts


# (g) binomial z-test of null counts per agency x column vs training rate
def null_spike_ztest(batch, refs, z_thr: float = 6.0, min_rows: int = 30):
    if "agency" not in batch.columns:
        return []
    alerts = []
    for agency, g in batch.groupby("agency"):
        n = len(g)
        if n < min_rows:
            continue
        for col in batch.columns:
            p = refs.null_baseline.get((agency, col))
            if p is None:
                continue
            p = min(max(p, 0.01), 0.99)
            k = g[col].isna().sum()
            z = (k - n * p) / np.sqrt(n * p * (1 - p))
            if z > z_thr:
                alerts.append(Alert("g", D, f"{agency}: {k}/{n} nulls in '{col}' (expected ~{n * p:.0f}, z={z:.1f}).",
                                    fields=[col, "agency"], evidence={"agency": agency, "z": round(float(z), 1)}))
    return alerts


# (h) duration below the 0.1th percentile for that complaint type
def duration_outlier(batch, refs):
    if not all(c in batch.columns for c in ("created_date", "closed_date", "complaint_type")):
        return []
    hours = (parse_dates(batch["closed_date"]) - parse_dates(batch["created_date"])).dt.total_seconds() / 3600
    alerts = []
    for i in batch.index[hours.notna()]:
        floor = refs.duration_floor.get(batch.at[i, "complaint_type"], 0.0)
        if hours[i] < min(floor, 0.0) - 1e-9:
            alerts.append(Alert("h", D, f"Time to close {hours[i]:.1f} h is below the 0.1th percentile "
                                        f"({floor:.2f} h) for '{batch.at[i, 'complaint_type']}'.",
                                row=int(i), fields=["created_date", "closed_date"], evidence={"hours": round(float(hours[i]), 2)}))
    return alerts


# (i) geography: the stated ZIP should occur among historical requests near this point
def geo_zip_knn(batch, refs, k: int = 25):
    cols = ("latitude", "longitude", "incident_zip")
    if not all(c in batch.columns for c in cols):
        return []
    lat = pd.to_numeric(batch["latitude"], errors="coerce")
    lon = pd.to_numeric(batch["longitude"], errors="coerce")
    ok = lat.notna() & lon.notna() & batch["incident_zip"].notna()
    idx = batch.index[ok]
    if not len(idx):
        return []
    _, nbr = refs.geo_tree.query(np.radians(np.c_[lat[idx], lon[idx]]), k=k)
    alerts = []
    for row, nb in zip(idx, nbr):
        near = refs.geo_zips[nb]
        z = batch.at[row, "incident_zip"]
        if z not in set(near):
            common = pd.Series(near).value_counts().index[:2].tolist()
            alerts.append(Alert("i", D, f"ZIP {z} never appears among the {k} nearest historical requests "
                                        f"(they are in {common}); borough {batch.at[row, 'borough']}.",
                                row=int(row), fields=["incident_zip", "latitude", "longitude"],
                                evidence={"incident_zip": z, "nearby": common}))
    return alerts


# (j) Naive Bayes on descriptor text predicts complaint type
def descriptor_classifier(batch, refs, p_min: float = 0.01):
    if not all(c in batch.columns for c in ("complaint_type", "descriptor")):
        return []
    ok = batch["descriptor"].notna() & batch["complaint_type"].isin(refs.desc_clf.classes_)
    idx = batch.index[ok]
    if not len(idx):
        return []
    proba = refs.desc_clf.predict_proba(refs.desc_vec.transform(batch.loc[idx, "descriptor"]))
    col = {c: j for j, c in enumerate(refs.desc_clf.classes_)}
    alerts = []
    for r, (row, ct) in enumerate(zip(idx, batch.loc[idx, "complaint_type"])):
        p = proba[r, col[ct]]
        if p < p_min:
            best = refs.desc_clf.classes_[proba[r].argmax()]
            alerts.append(Alert("j", D, f"Descriptor '{batch.at[row, 'descriptor']}' gives P('{ct}')={p:.3f}; "
                                        f"model expects '{best}'.",
                                row=int(row), fields=["complaint_type", "descriptor"], evidence={"p": round(float(p), 4)}))
    return alerts


# (k) logistic regression on resolution text predicts open vs closed
def status_classifier(batch, refs, p_min: float = 0.05):
    if not all(c in batch.columns for c in ("status", "resolution_description")):
        return []
    ok = batch["resolution_description"].notna() & batch["status"].isin({"Closed", "Open", "In Progress", "Assigned", "Pending", "Started"})
    idx = batch.index[ok]
    if not len(idx):
        return []
    proba = refs.res_clf.predict_proba(refs.res_vec.transform(batch.loc[idx, "resolution_description"]))
    ci = list(refs.res_clf.classes_).index("closed")
    alerts = []
    for r, row in enumerate(idx):
        st = batch.at[row, "status"]
        p = proba[r, ci] if st == "Closed" else 1 - proba[r, ci]
        if p < p_min:
            alerts.append(Alert("k", D, f"Resolution text gives P(status={st})={p:.3f} (text model trained on Jan-Aug).",
                                row=int(row), fields=["status", "resolution_description"], evidence={"p": round(float(p), 4)}))
    return alerts


# (l) out-of-vocabulary tokens in templated free text
def text_novelty(batch, refs, min_oov: int = 2):
    alerts = []
    for col in ("descriptor", "resolution_description"):
        if col not in batch.columns:
            continue
        for i, txt in batch[col].dropna().items():
            oov = [t for t in TOKEN.findall(str(txt)) if t.lower() not in refs.text_vocab]
            if len(oov) >= min_oov:
                alerts.append(Alert("l", D, f"'{col}' contains {len(oov)} tokens never seen in training text: {oov[:5]}.",
                                    row=int(i), fields=[col], evidence={"oov": oov[:5]}))
    return alerts


CHECKS = {
    "a": profile_match, "b": numeric_profile, "c": date_signature_rarity, "d": geo_consistency,
    "e": duplicate_rate, "f": tfidf_near_duplicates, "g": null_spike_ztest, "h": duration_outlier,
    "i": geo_zip_knn, "j": descriptor_classifier, "k": status_classifier, "l": text_novelty,
}
