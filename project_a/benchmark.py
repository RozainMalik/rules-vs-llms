"""
Task 4 — MEASURE EVERYTHING for the three calculators and the two parsers.

For each implementation and fiscal year:
  accuracy        rupee-exact on both regimes (LLM query-time: stratified sample)
  determinism     same input x10 -> how many distinct answers
  latency         p50 / p95 per request (LLM: latency of the original call, from cache)
  cost / 1,000    USD at paid-tier prices from measured tokens
  traceability    % of answers whose tax lines (a) all cite a clause, (b) sum to the
                  tax payable, (c) contain no fake "rounding" line > Rs 10 — and are correct
Parsers: action accuracy (compute vs clarify), field accuracy, and UNSAFE GUESSES
(computed when it should have asked) on the 50 descriptions.

Writes project_a/results/*.json and prints Markdown tables.
Run:  python -m project_a.benchmark          (LLM_OFFLINE=1 replays the cache only)
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from project_a.impl_llm_compiled.calculator import CompiledCalculator
from project_a.impl_llm_query.calculator import LLMQueryCalculator
from project_a.impl_rules.engine import RulesEngine
from project_a.models import Clarification, TaxInput, TaxResult
from project_a.parser.common import decide
from project_a.parser.llm_parser import LLMParser
from project_a.parser import regex_parser

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
TESTS = HERE / "tests"

LLM_SAMPLE_PER_CATEGORY = 4      # stratified sample for the (slow, rate-limited) LLM calculator
DETERMINISM_INPUTS = 5
REPEATS = 10


def load_cases(fy: str) -> list[dict]:
    name = "cases.json" if fy == "2024-25" else f"cases_{fy.replace('-', '_')}.json"
    return json.loads((TESTS / name).read_text())


def stratified(cases: list[dict], per_cat: int) -> list[dict]:
    seen: dict[str, int] = {}
    out = []
    for c in cases:
        if seen.get(c["category"], 0) < per_cat:
            out.append(c)
            seen[c["category"]] = seen.get(c["category"], 0) + 1
    return out


def trace_ok(res: TaxResult) -> bool:
    for rr in (res.old, res.new):
        tax_lines = [l for l in rr.trace if l.kind == "tax"]
        if not tax_lines or not all(l.clause.strip() for l in tax_lines):
            return False
        if sum(l.amount for l in tax_lines) != rr.tax_payable:
            return False
        if any("round" in l.description.lower() and abs(l.amount) >= 10 for l in tax_lines):
            return False      # a "rounding" line can never be Rs 10 or more: it is a plug
    return True


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else 0.0


def run_calculator(impl, cases: list[dict]) -> dict:
    correct = traced = errors = 0
    latencies, costs, failures = [], [], []
    for c in cases:
        inp = TaxInput(**c["input"])
        t0 = time.perf_counter()
        try:
            res, meta = impl.compute_with_meta(inp)
        except Exception as e:  # noqa: BLE001 — malformed LLM output counts as a visible error
            errors += 1
            failures.append({"id": c["id"], "error": repr(e)[:120]})
            continue
        local = time.perf_counter() - t0
        latencies.append(meta.latency_s if meta else local)
        costs.append(meta.cost_usd if meta else 0.0)
        ok = (isinstance(res, TaxResult) and res.old.tax_payable == c["expected"]["old"]
              and res.new.tax_payable == c["expected"]["new"])
        correct += ok
        traced += ok and trace_ok(res)
        if not ok:
            failures.append({"id": c["id"], "category": c["category"], "expected": c["expected"],
                             "got": {"old": res.old.tax_payable, "new": res.new.tax_payable}})
    n = len(cases)
    return {
        "n": n, "rupee_exact": correct, "accuracy": round(correct / n, 4),
        "silent_wrong": n - correct - errors, "visible_errors": errors,
        "traceable_and_correct": round(traced / n, 4),
        "latency_p50_s": round(pct(latencies, 50), 4), "latency_p95_s": round(pct(latencies, 95), 4),
        "cost_per_1000_usd": round(1000 * statistics.mean(costs), 4) if costs else 0.0,
        "failures": failures[:25],
    }


def determinism(impl, cases: list[dict]) -> dict:
    picks = [c for c in cases if c["category"] in ("combined", "rebate_87a_relief", "surcharge_relief", "hra")]
    picks = picks[:DETERMINISM_INPUTS]
    distinct = []
    for c in picks:
        answers = set()
        for s in range(REPEATS):
            try:
                res = impl.compute(TaxInput(**c["input"]), sample=s)
                answers.add((res.old.tax_payable, res.new.tax_payable))
            except Exception:  # noqa: BLE001
                answers.add(("error",))
        distinct.append(len(answers))
    return {"inputs": len(picks), "repeats": REPEATS, "distinct_answers_per_input": distinct,
            "deterministic": all(d == 1 for d in distinct)}


def bench_calculators(fy: str) -> dict:
    cases = load_cases(fy)
    sample = stratified(cases, LLM_SAMPLE_PER_CATEGORY)
    out = {}
    for name, impl, subset in [
        ("rules", RulesEngine(fy), cases),
        ("llm_compiled", CompiledCalculator(fy), cases),
        ("llm_query", LLMQueryCalculator(fy), sample),
    ]:
        print(f"[{fy}] {name}: {len(subset)} cases ...", flush=True)
        r = run_calculator(impl, subset)
        r["determinism"] = determinism(impl, cases)
        # also score rules/compiled on the LLM's sample so the comparison is like-for-like
        if name != "llm_query":
            r["accuracy_on_llm_sample"] = run_calculator(impl, sample)["accuracy"]
        out[name] = r
    return out


def bench_parsers() -> dict:
    descs = json.loads((TESTS / "descriptions.json").read_text())
    llm = LLMParser()
    out = {}
    for name in ("regex", "llm_hybrid"):
        rows, latencies, costs = [], [], []
        for d in descs:
            t0 = time.perf_counter()
            if name == "regex":
                ex, meta = regex_parser.parse(d["text"]), None
            else:
                ex, meta = llm.parse_with_meta(d["text"])
            decision = decide(ex)
            latencies.append(meta.latency_s if meta else time.perf_counter() - t0)
            costs.append(meta.cost_usd if meta else 0.0)
            exp = d["expected"]
            computed = isinstance(decision, TaxInput)
            if exp["action"] == "compute":
                fields_ok = computed and all(getattr(decision, k) == v for k, v in exp["fields"].items())
                rows.append({"id": d["id"], "style": d["style"], "ok": fields_ok, "unsafe_guess": False})
            else:
                rows.append({"id": d["id"], "style": d["style"], "ok": not computed,
                             "unsafe_guess": computed})
        by_style: dict[str, list[bool]] = {}
        for r in rows:
            by_style.setdefault(r["style"], []).append(r["ok"])
        out[name] = {
            "correct": sum(r["ok"] for r in rows), "n": len(rows),
            "unsafe_guesses": sum(r["unsafe_guess"] for r in rows),
            "by_style": {k: f"{sum(v)}/{len(v)}" for k, v in by_style.items()},
            "wrong_ids": [r["id"] for r in rows if not r["ok"]],
            "latency_p50_s": round(pct(latencies, 50), 4),
            "cost_per_1000_usd": round(1000 * statistics.mean(costs), 4),
        }
    # determinism of the LLM parser: 3 messy descriptions x 10
    distinct = []
    for d in [x for x in descs if x["id"] in ("D13", "D35", "D44")]:
        seen = set()
        for s in range(REPEATS):
            ex, _ = llm.parse_with_meta(d["text"], sample=s)
            dec = decide(ex)
            seen.add(json.dumps(vars(dec) if isinstance(dec, TaxInput) else {"clarify": dec.reason},
                                sort_keys=True, default=str))
        distinct.append(len(seen))
    out["llm_hybrid"]["determinism_distinct_outputs"] = distinct
    return out


def markdown(results: dict) -> str:
    lines = []
    for fy in ("2024-25", "2025-26"):
        lines += [f"\n### Calculators — FY {fy}\n",
                  "| Implementation | Cases | Rupee-exact | Silent wrong | Visible errors | Deterministic (10x) "
                  "| p50 latency | Cost / 1,000 req | Traceable & correct |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for name, r in results["calculators"][fy].items():
            d = r["determinism"]
            lines.append(
                f"| {name} | {r['n']} | {r['rupee_exact']} ({r['accuracy']:.1%}) | {r['silent_wrong']} "
                f"| {r['visible_errors']} | {'yes' if d['deterministic'] else 'NO ' + str(d['distinct_answers_per_input'])} "
                f"| {r['latency_p50_s']*1000:.1f} ms | ${r['cost_per_1000_usd']:.2f} | {r['traceable_and_correct']:.1%} |")
    p = results["parsers"]
    lines += ["\n### Parsers — 50 plain-language descriptions\n",
              "| Parser | Correct | Unsafe guesses | English | Hinglish | Terse | Incomplete | Contradictory | Ambiguous | p50 latency | Cost / 1,000 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in p.items():
        s = r["by_style"]
        lines.append(f"| {name} | {r['correct']}/{r['n']} | {r['unsafe_guesses']} | {s.get('english')} | {s.get('hinglish')} "
                     f"| {s.get('terse')} | {s.get('incomplete')} | {s.get('contradictory')} | {s.get('ambiguous')} "
                     f"| {r['latency_p50_s']*1000:.1f} ms | ${r['cost_per_1000_usd']:.2f} |")
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    results = {"calculators": {fy: bench_calculators(fy) for fy in ("2024-25", "2025-26")},
               "parsers": bench_parsers()}
    (OUT / "benchmark.json").write_text(json.dumps(results, indent=1, default=str))
    md = markdown(results)
    (OUT / "benchmark_tables.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
