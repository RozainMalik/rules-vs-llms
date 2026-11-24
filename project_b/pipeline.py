"""
 The HYBRID pipeline — the winners from evaluate.py, combined.

  Stage 1  RULES on every row        a b c d e f h i j, regex part of l, phrase part of k
  Stage 2  STATISTICS per batch      g (null-spike z-test), k (text model), l (novel tokens)
  Stage 3  LLM only where the cheap stages are UNSURE:
             k: rule and text model DISAGREE about a row  -> LLM decides
             l: novel tokens but no phone/email regex hit -> LLM decides (names)
           The LLM never sees rows that no cheap check flagged.

Design history (kept in results/pipeline_v1_llm_confirms_all.json): v1 sent
EVERY flagged j/k/l row to the LLM for confirmation. That lowered recall
(j 100% -> 84%, k 99.8% -> 61%) for a negligible drop in false alarms, so v2
uses the LLM only as a tie-breaker. Measured, not assumed.

Measured end to end on fresh batches (different seeds from evaluate.py) and on
a slice of REAL, unfiltered Sep-Dec data.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from project_b.alerts import Alert, BATCH_LEVEL, PROBLEMS
from project_b.detectors import llm, rules, stats
from project_b.injector import inject
from project_b.refs import load_data

RESULTS = Path(__file__).resolve().parent / "results"
BATCH_SIZE, RATE = 2000, 0.02

# problem -> (rows alerted directly, rows sent to the LLM)
#   "rule" / "stat"   : that family's flags
#   "rule&stat"       : both agree        "rule^stat": exactly one flags
#   "stat-rule"       : stat flags that the rule did not
PLAN = {
    "a": ("rule", None), "b": ("rule", None), "c": ("rule", None), "d": ("rule", None),
    "e": ("rule", None), "f": ("rule", None), "g": ("stat", None), "h": ("rule", None),
    "i": ("rule", None), "j": ("rule", None),
    "k": ("rule&stat", "rule^stat"),
    "l": ("rule", "stat-rule"),
}


def _select(expr, R, S):
    return {"rule": R, "stat": S, "rule&stat": R & S, "rule^stat": R ^ S, "stat-rule": S - R}[expr]


def _llm_decide(p, batch, rows) -> dict:
    """Send rows to the LLM, deduplicated on the reviewed columns (identical
    values get one shared verdict). Returns {row: Alert} for rows it flags."""
    if not rows:
        return {}
    cols = [c for c in llm.ROW_TASKS[p][0] if c in batch.columns]
    keys = batch.loc[sorted(rows), cols].astype(str).agg("\x1f".join, axis=1)
    reps = keys.groupby(keys).head(1).index.tolist()
    verdict = {}
    for s in range(0, len(reps), 40):
        for a in llm.review_rows(p, batch, reps[s:s + 40]):
            verdict[keys[a.row]] = a
    return {r: verdict[keys[r]] for r in keys.index if keys[r] in verdict}


def run_pipeline(batch: pd.DataFrame, refs) -> tuple[list[Alert], dict]:
    alerts: list[Alert] = []
    calls_before = len(llm.USAGE)
    t0 = time.perf_counter()
    llm_wall = 0.0                       # time spent inside LLM calls (excluded from CPU throughput)
    for p, (direct, ask) in PLAN.items():
        needs_rule = "rule" in direct or (ask and "rule" in ask)
        needs_stat = "stat" in direct or (ask and "stat" in ask)
        r_alerts = rules.CHECKS[p](batch, refs) if needs_rule else []
        s_alerts = stats.CHECKS[p](batch, refs) if needs_stat else []
        if p in BATCH_LEVEL:
            alerts += r_alerts if direct == "rule" else s_alerts
            continue
        by_row = {}
        for a in s_alerts + r_alerts:          # rule explanation wins when both exist
            by_row[a.row] = a
        R, S = {a.row for a in r_alerts}, {a.row for a in s_alerts}
        for r in sorted(_select(direct, R, S)):
            alerts.append(by_row[r])
        if ask:
            t_llm = time.perf_counter()
            decided = _llm_decide(p, batch, _select(ask, R, S))
            llm_wall += time.perf_counter() - t_llm
            for r, a in decided.items():
                alerts.append(Alert(p, "hybrid", f"{by_row[r].explanation} LLM: {a.explanation}",
                                    row=r, fields=by_row[r].fields, evidence=by_row[r].evidence))
    usage = llm.USAGE[calls_before:]
    return alerts, {"seconds": time.perf_counter() - t0 - llm_wall, "llm_calls": len(usage),
                    "llm_cost_usd": sum(r.cost_usd for _, _, r in usage),
                    "llm_rows": sum(n for _, n, _ in usage),
                    "llm_latency_s": sum(r.latency_s for _, _, r in usage)}


def evaluate_pipeline(n_corrupt: int = 2, n_clean: int = 4) -> dict:
    refs, pool, _, test = load_data()
    clean = [pool.sample(BATCH_SIZE, random_state=5000 + k).reset_index(drop=True) for k in range(n_clean)]
    per_problem, totals = [], {"rows": 0, "seconds": 0.0, "llm_calls": 0, "llm_cost_usd": 0.0, "llm_rows": 0, "llm_latency_s": 0.0}

    def add(meta, n):
        totals["rows"] += n
        for k in ("seconds", "llm_calls", "llm_cost_usd", "llm_rows", "llm_latency_s"):
            totals[k] += meta[k]

    clean_alerts = []
    for b in clean:
        al, meta = run_pipeline(b, refs)
        clean_alerts.append(al)
        add(meta, len(b))

    for p in PROBLEMS:
        hit = pos = flagged = tp = 0
        for k in range(n_corrupt):
            base = pool.sample(BATCH_SIZE, random_state=7000 + 10 * (ord(p) - 96) + k).reset_index(drop=True)
            inj = inject(p, base, RATE, seed=9000 + 10 * (ord(p) - 96) + k, refs=refs)
            al, meta = run_pipeline(inj.batch, refs)
            add(meta, len(inj.batch))
            mine = [a for a in al if a.problem == p]
            if p in BATCH_LEVEL:
                hit += bool(mine)
                pos += 1
            else:
                rows = {a.row for a in mine}
                truth = set(inj.row_labels.index[inj.row_labels])
                tp += len(rows & truth)
                flagged += len(rows)
                pos += len(truth)
        if p in BATCH_LEVEL:
            det = hit / pos
            fa = np.mean([any(a.problem == p for a in al) for al in clean_alerts])
            prec = None
        else:
            det = tp / max(1, pos)
            prec = tp / flagged if flagged else None
            fa = sum(len({a.row for a in al if a.problem == p}) for al in clean_alerts) / (n_clean * BATCH_SIZE)
        per_problem.append({"problem": p, "name": PROBLEMS[p], "plan": PLAN[p][0] + (f"; LLM on {PLAN[p][1]}" if PLAN[p][1] else ""),
                            "detection_rate": round(det, 4), "precision": None if prec is None else round(prec, 4),
                            "false_alarm_rate": round(float(fa), 5)})

    # --- real, unfiltered data: what does the pipeline raise on actual Sep-Dec rows? ---
    real = test.sample(4000, random_state=11).reset_index(drop=True)
    real_alerts, meta = run_pipeline(real, refs)
    add(meta, len(real))
    real_counts = pd.Series([a.problem for a in real_alerts]).value_counts().reindex(list(PROBLEMS), fill_value=0)
    real_examples = {}
    for a in real_alerts:
        real_examples.setdefault(a.problem, a.explanation)

    summary = {
        "per_problem": per_problem,
        "totals": totals,
        "cost_per_M_rows_usd": round(totals["llm_cost_usd"] / totals["rows"] * 1e6, 3),
        "llm_rows_share": round(totals["llm_rows"] / totals["rows"], 5),
        "cpu_rows_per_s": round(totals["rows"] / max(1e-9, totals["seconds"])),
        "batch_latency_s": round((totals["seconds"] + totals["llm_latency_s"]) / (totals["rows"] / BATCH_SIZE), 2),
        "real_data_alerts_per_4000_rows": real_counts.to_dict(),
        "real_data_llm": {"rows": len(real), "llm_calls": meta["llm_calls"], "llm_rows": meta["llm_rows"],
                          "llm_cost_usd": meta["llm_cost_usd"], "cpu_seconds": meta["seconds"],
                          "llm_latency_s": meta["llm_latency_s"],
                          "cost_per_M_rows_usd": round(meta["llm_cost_usd"] / len(real) * 1e6, 3)},
        "real_data_examples": real_examples,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "pipeline.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


if __name__ == "__main__":
    s = evaluate_pipeline()
    print(pd.DataFrame(s["per_problem"]).to_string(index=False))
    print({k: v for k, v in s.items() if k not in ("per_problem", "real_data_examples")})
