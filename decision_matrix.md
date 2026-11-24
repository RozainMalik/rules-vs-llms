# Decision matrix — rule, statistics, LLM or hybrid?

One row per component. **Choice** is what the final design uses. **Evidence** is the measurement
that decided it. Every number comes from `python run_all.py` (see [RESULTS_A.md](RESULTS_A.md) and
[RESULTS_B.md](RESULTS_B.md)).

## The rule of thumb the measurements support

> **Use a rule when correctness can be written down. Use statistics when "normal" has to be learned from data.
> Use an LLM where the input is language and nothing can be enumerated, and then only behind a deterministic gate
> or as a tie-breaker, never as the final authority on a number.**

## Project A — income-tax engine

| Component | Choice | Evidence | Why not the alternatives |
|---|---|---|---|
| Tax calculation (slabs, deductions, rebate, surcharge, cess, rounding) | **Rule** (YAML + engine) | 293/293 and 298/298 rupee-exact; deterministic; 0.1 ms; $0; 100% traceable | Query-time LLM: 16–21% rupee-exact, 49–52 silently wrong per 62, 4–10 distinct answers per input over 10 runs, $3.10 / 1,000. Compiled code is equally accurate but 96% traceable and can regress on every recompile |
| Clause-level explanation (audit trail) | **Rule** | Every tax line cites its clause and the lines sum to the tax in 100% of results | The query-time LLM invented a ₹7,800 "rounding" line to make a wrong total add up; the compiled code leaves ₹0 tax unexplained in 14 results per year |
| Rule values for a new Budget | **Hybrid**: an LLM may draft, a human verifies the clause, tests gate | FY 25-26 change = 34 YAML lines, 0 code; compile selection needed 10 candidates and 2 checklist rounds | A compiled module passed every original edge case and was still wrong on 11 random cases; review round 2 dropped from 131/131 to 18/131 |
| Test expectations | **Rule** (separate oracle) + **official calculator** | Oracle agrees with engine on 591 cases; the 30 official-calculator checks are not yet entered | Expected values must not come from an LLM. That would grade the model against itself |
| Stale-law protection | **Rule** (refuse unknown FY) | FY 24-25 code on FY 25-26 cases: 230/298 wrong, 0 errors raised, in both rules and compiled | Without a guard, both deterministic implementations fail silently |
| Field extraction from free text (English, Hinglish, terse) | **LLM** | 49/50 correct (Hinglish 12/12, terse 6/6), $0.61 / 1,000, 1.2 s | Regex baseline: 36/50, misses phrasing it was not written for |
| Compute-vs-ask decision (missing or contradictory input) | **Rule** (`parser/common.decide`) | LLM-extract → rule gate: 0 unsafe guesses on 50 | Regex alone: 7 unsafe guesses. The LLM must not decide whether enough is known |

## Project B — NYC 311 data quality

| # | Problem | Choice | Evidence (detection / false alarms) | Why not the alternatives |
|---|---|---|---|---|
| a | Renamed / dropped column | **Rule** (schema contract) | 100% / 0%, 1.1e8 rows/s | Stat and LLM equal on detection but slower and costlier |
| b | Column type change | **Rule** | 100% / 0% | Stats miss 50%: `"40.71"` as a string has the same value distribution |
| c | Date-format switch | **Rule** | 100% / 0% | LLM equal but $73 / M rows at 15 rows/s |
| d | Lat/lon swapped | **Rule** | 100% / 0% | LLM equal but $51 / M rows |
| e | Exact duplicates | **Rule** | 100% / 0% | LLM finds 50%: it can't compare 40 rows reliably |
| f | Near-duplicates | **Rule** (normalised address + 15-min window) | 100% / 0.36% | TF-IDF stat: 4.66% false alarms. LLM: 93% recall at $54 / M rows |
| g | Null spike in one agency | **Statistics** (binomial z-test vs per-agency baseline) | 100% / 0% | LLM alarmed on 33% of clean batches: it sees rows, not rates |
| h | Closed before created | **Rule** | 100% / 0% | No ambiguity, so nothing for an LLM to add |
| i | ZIP vs borough | **Rule** (learned ZIP→borough table) | 99.8% / 0% | Stat 0.10% false alarms; LLM 1.25% false alarms |
| j | Complaint type vs descriptor | **Rule** (learned allow-list) | 100% / 0.04% | LLM: 73% recall. Making the LLM confirm every flag cut recall to 84% |
| k | Resolution text vs status | **Hybrid**: rule AND stat → alert; rule XOR stat → LLM decides | 92.5% / 0.09%, LLM on 0.36% of rows | Phrase rule alone: 0.58% false alarms and over-fires on real referrals; LLM alone: 67% recall |
| l | PII in free text | **Hybrid**: regex → alert; novel tokens without a regex hit → LLM decides | 100% / 0% | Regex alone misses every name-only mention (67%); real agency phone numbers needed a statistical allow-list |
| — | Whole pipeline | **Hybrid** | $0.155 / M rows, 9,637 rows/s | LLM on every row: ≈ $388 / M rows, about 2,500× more, at 5–29 rows/s |
| — | New customer schema (at scale) | **Hybrid**: LLM proposes column mapping once, human approves, frozen as rules | Design, not measured (RESULTS_B §5) | Same pattern as Project A: the LLM authors, a human reviews, rules run |

## Where the LLM earned its cost

1. **Reading language that rules can't enumerate:** Hinglish and terse tax descriptions (A), and free-text resolutions and name-only PII (B). In every case it worked best **behind a deterministic gate or as a tie-breaker** on the small slice where cheap detectors disagree.
2. **Drafting rules a human then verifies:** next year's YAML from the Finance Act, or a new customer's column mapping.

## Where it did not

Anything with a definite right answer (arithmetic, schema, dates, duplicates, rates). There the LLM was slower, cost more, and was less accurate. Worst of all, its failures were **silent**: plausible numbers, and in Project A a trace fabricated to make a wrong total add up.
