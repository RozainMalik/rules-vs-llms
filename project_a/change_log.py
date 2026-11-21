"""
Task 5 evidence — reproduces every number in the RESULTS_A change log.

1. Size of each change (lines of rule data / text / code touched).
2. STALE deployment: what each implementation answers for FY 2025-26 if the
   update is forgotten. These failures are all SILENT (a plausible number, no error).
3. LLM-compiled review history, replayed from the LLM cache: every compile we
   made, scored on today's test suite. Shows regressions and candidates that pass
   every edge case yet are silently wrong on held-out random cases.

Run:  python -m project_a.change_log      (uses cached LLM responses only)
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path

from project_a.impl_llm_compiled.calculator import CompiledCalculator
from project_a.impl_llm_compiled.compiler import cases_for, compile_rules, evaluate
from project_a.impl_rules.engine import RulesEngine
from project_a.models import TaxInput

HERE = Path(__file__).resolve().parent
REVIEW = HERE / "impl_llm_compiled" / "review"


def changed_lines(a: Path, b: Path) -> int:
    diff = difflib.unified_diff(a.read_text().splitlines(), b.read_text().splitlines(), lineterm="", n=0)
    return sum(1 for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---"))


def stale_check() -> dict:
    """Run the FY24-25 versions on FY25-26 cases (i.e. someone forgot to update)."""
    cases = cases_for("2025-26")
    out = {}
    for name, impl in [("rules", RulesEngine("2024-25")), ("llm_compiled", CompiledCalculator("2024-25"))]:
        wrong = 0
        for c in cases:
            r = impl.compute(TaxInput(**c["input"]))
            wrong += (r.old.tax_payable, r.new.tax_payable) != (c["expected"]["old"], c["expected"]["new"])
        out[name] = {"wrong": wrong, "total": len(cases), "raised_error": 0}
    return out


def compile_history() -> list[dict]:
    """Every FY24-25 / FY25-26 compile made during development, replayed from cache."""
    os.environ["LLM_OFFLINE"] = "1"
    fb = lambda name: (REVIEW / name).read_text() if name else ""
    plan = [
        ("2024-25", "v1: no feedback", "", 0),
        ("2024-25", "review round 1", "fy2024_25_round1.txt", 0),
        ("2024-25", "review round 2", "fy2024_25_round2.txt", 0),
        *[("2024-25", f"round 3, candidate {s}", "fy2024_25_round3.txt", s) for s in range(5)],
        *[("2025-26", f"checklist v1, candidate {s}", None, s) for s in range(5)],
        *[("2025-26", f"checklist v2 (+surcharge), candidate {s}", "generic_checklist.txt", s) for s in range(5)],
    ]
    # checklist v1 = generic_checklist.txt without item 8 (the version first used for FY25-26)
    v1 = "\n".join(l for l in fb("generic_checklist.txt").splitlines() if not l.startswith("8."))
    rows = []
    for fy, label, fname, sample in plan:
        feedback = v1 + "\n" if fname is None else fb(fname)
        try:
            source, meta = compile_rules(fy, sample, feedback)
        except Exception:  # noqa: BLE001 — not in cache (never compiled)
            continue
        cases = cases_for(fy)
        edge = [c for c in cases if c["category"] != "random"]
        # the edge suite as it was BEFORE the two categories added during Task 5
        edge_orig = [c for c in edge if c["category"] not in ("age_surcharge", "rounding_288b")]
        rnd = [c for c in cases if c["category"] == "random"]
        e, eo, r = evaluate(source, edge), evaluate(source, edge_orig), evaluate(source, rnd)
        visible = bool(e.get("load_error")) or e.get("crashes", 0) > 0
        wrong = (e["total"] - e["correct"]) + (r["total"] - r["correct"])
        rows.append({"fy": fy, "compile": label,
                     "edge_original_suite": f"{eo['correct']}/{eo['total']}",
                     "edge": f"{e['correct']}/{e['total']}", "random": f"{r['correct']}/{r['total']}",
                     "silent_wrong": 0 if visible else wrong,
                     "visible_failure": (e.get("load_error") or f"{e.get('crashes', 0)} crashes") if visible else "",
                     "passed_original_edges_but_wrong": eo["correct"] == eo["total"] and wrong > 0})
    return rows


def main() -> dict:
    root = HERE
    result = {
        "change_size": {
            "rules_yaml_lines": changed_lines(root / "rules/fy2024_25.yaml", root / "rules/fy2025_26.yaml"),
            "rule_text_lines": changed_lines(root / "rules_text/fy2024_25.md", root / "rules_text/fy2025_26.md"),
            "engine_code_lines": 0,
        },
        "stale_deployment_on_fy2025_26": stale_check(),
        "compile_history": compile_history(),
    }
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / "change_log.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result["change_size"]), json.dumps(result["stale_deployment_on_fy2025_26"]))
    print("| FY | Compile | Original edge suite | Final edge suite | Random (held-out) | Silent wrong | Visible failure | Passed original edges yet wrong |")
    print("|---|---|---|---|---|---|---|---|")
    for r in result["compile_history"]:
        print(f"| {r['fy']} | {r['compile']} | {r['edge_original_suite']} | {r['edge']} | {r['random']} "
              f"| {r['silent_wrong']} | {r['visible_failure'][:40]} "
              f"| {'**yes**' if r['passed_original_edges_but_wrong'] else ''} |")
    return result


if __name__ == "__main__":
    main()
