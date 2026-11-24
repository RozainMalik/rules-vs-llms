# Rules vs LLMs

**When should you write a plain rule, when should you use statistics, and when is an LLM actually worth its cost?**

This repo answers that question empirically. It builds the same systems several different ways and measures each one on accuracy, consistency, latency, and cost.

| | Project A: Income tax engine | Project B: Data quality layer |
|---|---|---|
| **Domain** | Indian income tax for salaried individuals (FY 2024-25 → FY 2025-26) | NYC 311 service requests, 2023 (292K rows) |
| **Approaches compared** | Hand-written rules · LLM computes at query time · LLM writes the code once | Declarative rules · Statistics/ML · LLM review |
| **Evaluation** | 293 + 298 oracle test cases, repeat-query consistency | 12 injected corruption types with ground-truth labels |
| **Outcome** | Rules engine with an LLM-assisted input parser | Hybrid pipeline using the best detector per problem type |

---

## Key findings

- **Rules won on calculation.** The rules engine was correct on every test case (293 for FY 2024-25, 298 for FY 2025-26).
- **The LLM computing tax directly was correct only 16–21% of the time**, and gave different answers to the same question when asked again. In one case it invented a ₹7,800 "rounding adjustment" so that its wrong answer would add up.
- **LLM-written code reached 100%, but only with guardrails.** It took several rounds of review and test-gated selection between candidates. Some versions passed every edge case and were still wrong on random inputs.
- **Stale rules fail silently.** Running the FY 2024-25 engine on FY 2025-26 inputs gave 230 of 298 answers wrong, with no error raised, which is why rules are versioned per financial year.
- **LLMs earned their cost on messy text.** The LLM parser read 49 of 50 plain-English and Hinglish descriptions correctly with **0 unsafe guesses**, asking a clarifying question whenever information was missing. The same held for free-text fields in the 311 data, *as long as deterministic code made the final decision*.

Full write-ups:

| Document | Contents |
|---|---|
| [RESULTS_A.md](RESULTS_A.md) | Project A comparison tables, the FY 2025-26 update, and the recommended design |
| [RESULTS_B.md](RESULTS_B.md) | Project B detection, false-alarm and cost tables, real issues found in the data, and how it would scale |
| [DECISION_MATRIX.md](DECISION_MATRIX.md) | Every component: rule, statistics, LLM, or hybrid, with the measurement behind the choice |
| [AI_USAGE.md](AI_USAGE.md) | AI tools used during development, and where they got things wrong |

---

## Project A: Income tax engine

Three implementations of the same tax calculation:

1. **Rules engine.** The tax law is stored as data in YAML, one file per financial year, with every value linked to its legal clause. The engine produces a per-clause trace showing where each rupee comes from.
2. **LLM at query time.** Gemini reads the rule text and computes the tax on every request.
3. **LLM-compiled code.** Gemini writes Python once. Candidates go through review rounds, only a version that passes the test suite is selected, and it then runs offline without calling the LLM.

A **natural-language parser** turns plain English or Hinglish descriptions into structured inputs. When information is missing, it asks a clarifying question instead of guessing.

**Scope:** resident individuals with salary income. Covers the standard deduction, HRA (Sec 10(13A)), 80C, 80CCD(1B), 80D (including senior-citizen parents), home-loan interest under Sec 24(b), the Sec 87A rebate with marginal relief, surcharge with marginal relief, 4% cess, and rounding under Sec 288A/288B.
**Not covered:** other income heads, professional tax, employer NPS contributions (80CCD(2)), and carry-forward of house-property losses.

## Project B: Data quality layer for NYC 311

1. Download a 2023 sample of NYC 311 service requests from NYC Open Data and profile it for real quality problems.
2. Inject **12 types of corruption** at a controlled rate, recording exactly which rows were changed as ground-truth labels.
3. Run three detector families (rules, statistics/ML, and LLM review) against every corruption type.
4. Score each detector on detection rate, false-alarm rate, and cost, then combine the best performers into a single **hybrid pipeline**.

---

## Quick start

Requires Python 3.11+ (developed on 3.12).

```bash
pip install -r requirements.txt

# Optional: only needed for LLM calls that aren't already cached
echo "GEMINI_API_KEY=your-key" > .env
```

### Reproduce the results

```bash
python run_all.py              # runs everything, using cached LLM answers where available
python run_all.py --offline    # never calls Gemini; no API key needed
python run_all.py --only a     # Project A only (use --only b for Project B)
```

Every Gemini response used in the write-ups is committed to `llm_cache/` along with its original latency and token counts, so the accuracy, latency, and cost figures reproduce exactly without an API key. Project B downloads its data sample (~128 MB) on the first run.

### Other useful commands

```bash
python -m pytest project_a/tests project_b/tests -q   # run the test suites
python -m project_a.impl_rules.engine                 # demo: tax computed with each clause shown
python -m project_a.benchmark                         # Project A comparison tables
python -m project_a.change_log                        # evidence for the FY 2025-26 update
python -m project_b.run                               # Project B end to end
```

---

## Repository structure

```
run_all.py               single entry point
common/llm.py            Gemini wrapper: disk cache, rate limiting, retries, cost tracking
llm_cache/               every LLM response used in the results

project_a/
  rules/                 tax law as YAML, one file per year, each value tagged with its clause
  rules_text/            the same rules as text, read by the LLM implementations
  impl_rules/            (1) hand-written rules engine
  impl_llm_query/        (2) LLM computes tax on every request
  impl_llm_compiled/     (3) LLM writes the code once, then runs without the LLM
  parser/                free text -> structured input, or a clarifying question
  tests/                 oracle, test cases, natural-language descriptions
  benchmark.py           comparison tables
  change_log.py          FY 2025-26 update
  results/               generated tables

project_b/
  download.py, profile.py    fetch the data and profile real quality problems
  injector.py                inject 12 corruption types with ground-truth labels
  detectors/                 rule, statistical, and LLM detectors
  evaluate.py, pipeline.py   scoring and the hybrid pipeline
  run.py                     Project B entry point
  results/                   generated tables
```

---

## Known limitations

Being explicit about what is and isn't verified:

- **Official-calculator checks are pending.** `project_a/tests/official_checks.csv` contains 30 cases to verify against the Income Tax Department's calculator, but the official values haven't been filled in yet, so that test is skipped.
- **Tax values are not yet independently verified.** Most values in the rules YAML are marked `verified: false`. The test oracle is a separate implementation, but it was written from the same reading of the law, so it catches code bugs, not a misread number in the law itself.