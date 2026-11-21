"""
Project B — one command reproduces every number in RESULTS_B.md:

    python -m project_b.run

  1. download   (skipped if data/raw/nyc311_2023_sample.csv exists)
  2. profile    -> results/profile.json
  3. evaluate   -> results/detector_matrix.{csv,json}
  4. pipeline   -> results/pipeline.json
  5. report     -> results/tables.md (the tables pasted into RESULTS_B.md)

LLM responses come from llm_cache/ (committed). Set LLM_OFFLINE=1 to guarantee
no API calls are made; a cache miss then fails loudly instead of spending quota.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from project_b import download, evaluate, pipeline, profile
from project_b.refs import load_data

RESULTS = Path(__file__).resolve().parent / "results"


def _fmt(v, pct=False):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    return f"{v:.1%}" if pct else f"{v}"


def tables() -> str:
    m = pd.read_json(RESULTS / "detector_matrix.json")
    out = ["| # | Problem | Detector | Detection | Precision | False alarms (clean) | $ / M rows | Rows/s | Clarity 0-3 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for _, r in m.iterrows():
        out.append(f"| {r.problem} | {r['name']} | {r.detector} | {_fmt(r.detection_rate, True)} | "
                   f"{_fmt(r.precision, True)} | {r.false_alarm_rate:.2%} | {r.cost_per_M_rows_usd:,.2f} | "
                   f"{r.rows_per_s:,.0f} | {_fmt(r.clarity_0_3)} |")
    p = json.loads((RESULTS / "pipeline.json").read_text())
    out += ["", "| # | Problem | Hybrid plan | Detection | Precision | False alarms |", "|---|---|---|---|---|---|"]
    for r in p["per_problem"]:
        out.append(f"| {r['problem']} | {r['name']} | {r['plan']} | {_fmt(r['detection_rate'], True)} | "
                   f"{_fmt(r['precision'], True)} | {r['false_alarm_rate']:.2%} |")
    t = p["totals"]
    out += ["", f"Pipeline totals: {t['rows']:,} rows, {t['llm_calls']} LLM calls on {t['llm_rows']:,} rows "
                f"({p['llm_rows_share']:.2%} of rows), LLM cost ${t['llm_cost_usd']:.4f} "
                f"=> ${p['cost_per_M_rows_usd']:.3f} per million rows; CPU throughput {p['cpu_rows_per_s']:,} rows/s; "
                f"mean latency per 2,000-row batch {p['batch_latency_s']} s."]
    text = "\n".join(out)
    (RESULTS / "tables.md").write_text(text)
    return text


def main() -> None:
    download.download()
    load_data()                         # builds refs + clean pool once (cached)
    profile.profile()
    evaluate.evaluate()
    pipeline.evaluate_pipeline()
    print(tables())


if __name__ == "__main__":
    main()
