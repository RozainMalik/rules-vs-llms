"""
Measure every detector family on every problem type.

Setup (all seeded, so every number reproduces):
  - CLEAN batches: N_CLEAN batches of BATCH_SIZE rows drawn from the clean pool
    (Sep-Dec 2023 rows that pass objective sanity checks)
  - CORRUPTED batches: for each problem, the injector corrupts N_CORRUPT of those
    clean batches at RATE (row-level) or once per batch (batch-level)

Metrics per (problem, detector):
  detection_rate   row-level: recall over corrupted rows; batch-level: share of corrupted batches alarmed
  precision        row-level only: share of flagged rows in corrupted batches that were really corrupted
  false_alarm_rate row-level: share of rows flagged in CLEAN batches; batch-level: share of clean batches alarmed
  cost_per_M_rows  USD at paid-tier prices (rules/stats: $0 — no API)
  rows_per_s       throughput on this laptop (LLM: sequential calls, measured latency)
  clarity          0-3 rubric, see clarity()

LLM review runs on SAMPLES (budget): 3 corrupted + 2 clean samples of 40 rows
for row-level problems, 3 corrupted + 3 clean batches for batch-level problems.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from project_b.alerts import BATCH_LEVEL, PROBLEMS
from project_b.detectors import llm, rules, stats
from project_b.injector import inject
from project_b.refs import load_data

RESULTS = Path(__file__).resolve().parent / "results"
BATCH_SIZE, N_CLEAN, N_CORRUPT, RATE = 2000, 10, 10, 0.02
LLM_CHUNK, LLM_POS, LLM_CORRUPT_SAMPLES, LLM_CLEAN_SAMPLES = 40, 10, 3, 2


# ---------------------------------------------------------------------------
# explanation clarity rubric (0-3), applied identically to every family
# ---------------------------------------------------------------------------
EXPECT_WORDS = re.compile(r"expect|should|must|contract|never|not in|not iso|inconsisten|contradict|earlier than|"
                          r"outside|swapped|duplicate|historical|training|normal|belongs|format|percentile|sigma|"
                          r"does not|doesn't|mismatch|instead|but ", re.I)
EVIDENCE = re.compile(r"\d|'[^']+'|\"[^\"]+\"")


def clarity(alert, columns) -> int:
    """+1 names the field, +1 states the violated expectation, +1 shows the evidence."""
    text = alert.explanation
    names = [c for c in columns] + [c.replace("_", " ") for c in columns]
    s = int(any(n.lower() in text.lower() for n in names) or bool(alert.fields and alert.fields[0] in text))
    s += int(bool(EXPECT_WORDS.search(text)))
    s += int(bool(EVIDENCE.search(text)))
    return s


# ---------------------------------------------------------------------------
def make_batches(pool, refs):
    clean = [pool.sample(BATCH_SIZE, random_state=1000 + k).reset_index(drop=True) for k in range(N_CLEAN)]
    corrupted = {p: [inject(p, clean[k], RATE, seed=100 * (ord(p) - 96) + k, refs=refs) for k in range(N_CORRUPT)]
                 for p in PROBLEMS}
    return clean, corrupted


def score_rows(alerts_by_batch, labels_by_batch):
    tp = flagged = pos = 0
    for alerts, labels in zip(alerts_by_batch, labels_by_batch):
        rows = {a.row for a in alerts if a.row is not None}
        truth = set(labels.index[labels])
        tp += len(rows & truth)
        flagged += len(rows)
        pos += len(truth)
    return tp / max(1, pos), (tp / flagged if flagged else None)


def run_cheap(family_name, family, clean, corrupted, refs):
    out = []
    for p in PROBLEMS:
        check = family.CHECKS[p]
        t0 = time.perf_counter()
        corr_alerts = [check(inj.batch, refs) for inj in corrupted[p]]
        clean_alerts = [check(b, refs) for b in clean]
        elapsed = time.perf_counter() - t0
        n_rows = sum(len(i.batch) for i in corrupted[p]) + sum(len(b) for b in clean)
        all_alerts = [a for al in corr_alerts for a in al]
        cols = list(clean[0].columns)
        if p in BATCH_LEVEL:
            det = np.mean([bool(a) for a in corr_alerts])
            fa = np.mean([bool(a) for a in clean_alerts])
            prec = None
        else:
            det, prec = score_rows(corr_alerts, [i.row_labels for i in corrupted[p]])
            fa = sum(len({a.row for a in al}) for al in clean_alerts) / (N_CLEAN * BATCH_SIZE)
        out.append({
            "problem": p, "name": PROBLEMS[p], "detector": family_name,
            "detection_rate": round(float(det), 4), "precision": None if prec is None else round(prec, 4),
            "false_alarm_rate": round(float(fa), 5), "cost_per_M_rows_usd": 0.0,
            "rows_per_s": round(n_rows / elapsed), "clarity_0_3": round(float(np.mean([clarity(a, cols) for a in all_alerts[:200]])), 2) if all_alerts else None,
            "example": all_alerts[0].explanation if all_alerts else "",
            "n_samples": f"{N_CORRUPT} corrupted + {N_CLEAN} clean batches x {BATCH_SIZE} rows",
        })
    return out


def _llm_rows_for(inj, rng):
    """A 40-row review chunk with ~LLM_POS corrupted rows (and their duplicate partners)."""
    b, lab = inj.batch, inj.row_labels
    if inj.problem == "c":                                  # keep row ORDER: 20 rows each side of the switch
        start = inj.meta["switch_at_position"]
        return list(range(max(0, start - LLM_CHUNK // 2), min(len(b), start + LLM_CHUNK // 2)))
    pos = lab.index[lab].to_numpy()
    if inj.problem in ("e", "f"):                           # bring whole pairs so the duplicate is visible
        key = b["unique_key"].astype("int64") % 90_000_000 if inj.problem == "f" else \
            pd.util.hash_pandas_object(b.astype(str), index=False)
        groups = pd.Series(pos).groupby(key.loc[pos].to_numpy()).apply(list).tolist()
        chosen = [r for g in rng.permutation(len(groups))[: LLM_POS // 2] for r in groups[g]]
    else:
        chosen = list(rng.choice(pos, size=min(LLM_POS, len(pos)), replace=False))
    neg = rng.choice(lab.index[~lab].to_numpy(), size=LLM_CHUNK - len(chosen), replace=False)
    rows = sorted(int(r) for r in list(chosen) + list(neg))
    return rows


def run_llm(clean, corrupted):
    out = []
    rng = np.random.default_rng(7)
    for p in PROBLEMS:
        start = len(llm.USAGE)
        cols = list(clean[0].columns)
        if p in BATCH_LEVEL:
            corr = [llm.check(p, inj.batch) for inj in corrupted[p][:3]]
            cln = [llm.check(p, b) for b in clean[:3]]
            det, prec = np.mean([bool(a) for a in corr]), None
            fa = np.mean([bool(a) for a in cln])
            alerts = [a for al in corr for a in al]
            n_desc = "3 corrupted + 3 clean batches"
        else:
            corr_alerts, labels = [], []
            for inj in corrupted[p][:LLM_CORRUPT_SAMPLES]:
                rows = _llm_rows_for(inj, rng)
                corr_alerts.append(llm.review_rows(p, inj.batch, rows))
                labels.append(inj.row_labels.loc[rows])
            det, prec = score_rows(corr_alerts, labels)
            flagged_clean = 0
            for k in range(LLM_CLEAN_SAMPLES):
                rows = sorted(rng.choice(len(clean[k]), size=LLM_CHUNK, replace=False).tolist())
                if p == "c":
                    rows = list(range(800, 800 + LLM_CHUNK))
                flagged_clean += len({a.row for a in llm.review_rows(p, clean[k], rows)})
            fa = flagged_clean / (LLM_CLEAN_SAMPLES * LLM_CHUNK)
            alerts = [a for al in corr_alerts for a in al]
            n_desc = f"{LLM_CORRUPT_SAMPLES} corrupted + {LLM_CLEAN_SAMPLES} clean samples x {LLM_CHUNK} rows"
        usage = llm.USAGE[start:]
        cost = sum(r.cost_usd for _, _, r in usage)
        latency = sum(r.latency_s for _, _, r in usage)
        if p in BATCH_LEVEL:
            cost_per_m = cost / len(usage) / BATCH_SIZE * 1e6        # one call per 2,000-row batch
            rps = BATCH_SIZE * len(usage) / latency
        else:
            reviewed = sum(n for _, n, _ in usage)
            cost_per_m = cost / reviewed * 1e6
            rps = reviewed / latency
        out.append({
            "problem": p, "name": PROBLEMS[p], "detector": "llm",
            "detection_rate": round(float(det), 4), "precision": None if prec is None else round(prec, 4),
            "false_alarm_rate": round(float(fa), 5), "cost_per_M_rows_usd": round(cost_per_m, 2),
            "rows_per_s": round(rps, 1), "clarity_0_3": round(float(np.mean([clarity(a, cols) for a in alerts])), 2) if alerts else None,
            "example": alerts[0].explanation if alerts else "", "n_samples": n_desc,
            "llm_calls": len(usage), "input_tokens": sum(r.input_tokens for _, _, r in usage),
            "output_tokens": sum(r.output_tokens for _, _, r in usage),
            "mean_latency_s": round(latency / len(usage), 2),
        })
        print(f"[evaluate] llm {p}: det={det:.2f} fa={fa:.3f} calls={len(usage)}", flush=True)
    return out


def evaluate() -> pd.DataFrame:
    refs, pool, _, _ = load_data()
    clean, corrupted = make_batches(pool, refs)
    rows = run_cheap("rule", rules, clean, corrupted, refs)
    rows += run_cheap("stat", stats, clean, corrupted, refs)
    rows += run_llm(clean, corrupted)
    df = pd.DataFrame(rows).sort_values(["problem", "detector"])
    RESULTS.mkdir(exist_ok=True)
    df.to_csv(RESULTS / "detector_matrix.csv", index=False)
    (RESULTS / "detector_matrix.json").write_text(json.dumps(df.to_dict(orient="records"), indent=1, default=str))
    return df


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    d = evaluate()
    print(d[["problem", "detector", "detection_rate", "precision", "false_alarm_rate", "cost_per_M_rows_usd",
             "rows_per_s", "clarity_0_3"]].to_string(index=False))
