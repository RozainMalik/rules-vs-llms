# Rules vs LLMs — take-home

Two systems, each built several ways and measured, to decide **where a deterministic rule is the right tool, where an LLM earns its cost, and where the answer is both**.

- **Project A — Indian income-tax engine** (salaried, FY 2024-25 → FY 2025-26): hand-coded rules vs LLM at query time vs LLM-compiled rules, plus a plain-language parser that asks instead of guessing.
- **Project B — data-quality layer for NYC 311 (2023)**: declarative rules vs statistics/ML vs LLM review for 12 corruption types, combined into a hybrid pipeline.

| Document | Contents |
|---|---|
| [RESULTS_A.md](RESULTS_A.md) | Project A comparison table, Task 5 change log, final design |
| [RESULTS_B.md](RESULTS_B.md) | Project B detection / false-alarm / cost table, real issues found, scale design |
| [DECISION_MATRIX.md](DECISION_MATRIX.md) | One row per component: rule, statistical, LLM or hybrid, with the measurement behind it |
| [AI_USAGE.md](AI_USAGE.md) | Tools used, and where the AI was wrong and how it was caught |

## Setup

Python 3.10+.

```bash
pip install -r requirements.txt
echo "GEMINI_API_KEY=your-key" > .env      # only needed for LLM cache misses; .env is git-ignored
```

## Reproduce every number — one command

```bash
python run_all.py              # replays committed LLM answers (llm_cache/); calls Gemini only on a miss
python run_all.py --offline    # never calls Gemini — no API key needed
python run_all.py --only a     # Project A only   (--only b for Project B)
```

Every Gemini response used in the reports is committed under `llm_cache/` together with its original latency and token counts, so `--offline` reproduces identical accuracy, latency and cost figures. Project B downloads its 2023 sample (292,000 rows, ~128 MB) from NYC Open Data on first run into `data/raw/` (git-ignored).

## Useful commands

```bash
python -m pytest project_a/tests project_b/tests -q   # unit tests
python -m project_a.impl_rules.engine                 # demo: tax under both regimes, every rupee with its clause
python -m project_a.benchmark                         # Project A Task 4 tables -> project_a/results/
python -m project_a.change_log                        # Project A Task 5 evidence -> project_a/results/
python -m project_a.tests.build_cases 2025-26         # regenerate test cases from the independent oracle
python -m project_a.impl_llm_compiled.compiler 2025-26 \
    --feedback project_a/impl_llm_compiled/review/generic_checklist.txt   # LLM-compile rules, test, select
python -m project_b.run                               # Project B end to end -> project_b/results/
```

## Repository layout

```
run_all.py                     single entry point
common/llm.py                  Gemini client: disk cache, cross-process rate limit, retries, token -> USD
llm_cache/                     every LLM response used in the reports (committed)

project_a/
  rules/fy2024_25.yaml         the law as data; every number carries its clause   (implementation a)
  rules/fy2025_26.yaml         Finance Act 2025 change (Task 5)
  rules_text/*.md              rule text the LLM implementations read             (b, c)
  models.py                    TaxInput / TaxResult / TraceLine / Clarification
  impl_rules/engine.py         (a) hand-coded rules engine with per-clause trace
  impl_llm_query/              (b) LLM computes the tax on every request
  impl_llm_compiled/           (c) LLM writes Python once -> review -> test-gated selection -> runs offline
    review/                    reviewer feedback rounds and selection logs
  parser/                      free text -> TaxInput or a clarifying question (regex baseline + LLM hybrid)
  tests/                       oracle, 293 + 298 cases, 50 descriptions, 30 official-calculator checks
  benchmark.py                 Task 4 measurements
  change_log.py                Task 5 measurements
  results/                     generated tables (JSON + Markdown)

project_b/
  download.py, profile.py      fetch 2023 sample, profile real quality problems
  injector.py                  12 corruption types at a controlled rate, with ground-truth labels
  detectors/{rules,stats,llm}.py   three detector families for every problem type
  evaluate.py, pipeline.py     per-detector measurements; hybrid pipeline end to end
  run.py                       Project B entry point
  results/                     generated tables
```

## Scope and assumptions (Project A)

Resident individual, salary income only, annual figures. Covers standard deduction, HRA (Sec 10(13A)/Rule 2A), 80C, 80CCD(1B), 80D (incl. senior-citizen parents), self-occupied home-loan interest (Sec 24(b)), Sec 87A rebate with marginal relief, surcharge with marginal relief, 4% cess, and Sec 288A/288B rounding. Excluded: other income heads, professional tax, employer NPS (80CCD(2)), carry-forward of house-property loss.
