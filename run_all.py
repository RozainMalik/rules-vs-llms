"""
ONE COMMAND that reproduces every number in RESULTS_A.md, RESULTS_B.md and decision_matrix.md.

    python run_all.py              # replay committed LLM cache; call Gemini only on a cache miss
    python run_all.py --offline    # never call Gemini (fails loudly on a cache miss)
    python run_all.py --only a     # just Project A   (or --only b)

Every LLM response used in the reports is committed under llm_cache/, so a
reviewer without an API key gets identical numbers with --offline.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def step(title: str, args: list[str]) -> None:
    print(f"\n{'=' * 78}\n>> {title}\n{'=' * 78}", flush=True)
    t0 = time.time()
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)
    print(f"   ({time.time() - t0:.1f}s)")


def main() -> None:
    if "--offline" in sys.argv:
        os.environ["LLM_OFFLINE"] = "1"
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else "ab"

    if "a" in only:
        step("A1  build test cases (FY24-25, FY25-26) from the independent oracle",
             ["-m", "project_a.tests.build_cases", "2024-25"])
        step("A1b build FY25-26 cases", ["-m", "project_a.tests.build_cases", "2025-26"])
        step("A2  unit tests (rules engine vs oracle, clarification behaviour)",
             ["-m", "pytest", "-q", "project_a/tests"])
        step("A3  benchmark: 3 calculators x 2 years + 2 parsers  -> project_a/results/",
             ["-m", "project_a.benchmark"])
        step("A4  Task 5 change log (stale deployment, compile history)  -> project_a/results/",
             ["-m", "project_a.change_log"])
    if "b" in only:
        step("B   profile, inject, evaluate detectors, hybrid pipeline  -> project_b/results/",
             ["-m", "project_b.run"])
        step("B   unit tests", ["-m", "pytest", "-q", "project_b/tests"])
    print("\nAll steps finished.")


if __name__ == "__main__":
    main()
