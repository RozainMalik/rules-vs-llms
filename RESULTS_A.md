# Project A — Income-tax engine: hand rules, LLM at query time, or LLM-compiled rules?

Every number below is produced by **`python run_all.py --only a`** and written to
`project_a/results/` (`benchmark.json`, `benchmark_tables.md`, `change_log.json`).
LLM responses are cached in `llm_cache/`; `python run_all.py --offline` replays them
without an API key, and a cache miss fails loudly.

## 1. Set-up

| Item | Value |
|---|---|
| Scope | Resident individual, salary only, both regimes (see README for covered sections) |
| Years | FY 2024-25 (Finance (No. 2) Act 2024) and FY 2025-26 (Finance Act 2025) |
| Expected values | `tests/oracle.py`, a separate implementation that does not share code with the engine |
| Test cases | **293** (FY 24-25) and **298** (FY 25-26). 143 / 148 are edge cases at every threshold, cap and relief boundary (±₹5–10); 150 are random incomes |
| Plain-language inputs | 50 descriptions: 12 English, 12 Hinglish, 6 terse, 10 incomplete, 6 contradictory, 4 ambiguous |
| LLM | `gemini-3.5-flash-lite`, priced at paid-tier list prices ($0.30 / M input, $2.50 / M output) |

The three calculators:

- **(a) Rules**: `rules/fy*.yaml` holds every rate, limit and clause; `impl_rules/engine.py` (329 lines) applies them and writes one trace line per step, each with its clause.
- **(b) LLM at query time**: every request sends the rule text and the input to Gemini, which returns both taxes and a trace as JSON.
- **(c) LLM-compiled**: Gemini writes a Python module from the same rule text **once**. Candidates are reviewed and gated on the edge-case suite, the winner is frozen in `impl_llm_compiled/compiled/`, and it then runs offline.

All three share the same input gate. Missing or contradictory input returns a clarifying question before any tax is computed, so this comparison measures the calculation only.

## 2. Comparison — `results/benchmark_tables.md`

How to read the columns:
- **Rupee-exact**: both regimes match the oracle to the rupee.
- **Silent wrong**: a plausible number with no error raised. This is the dangerous failure.
- **Deterministic**: the same input run 10 times (5 inputs) gives 1 distinct answer.
- **Traceable & correct**: the answer is right *and* every tax line cites a clause, the lines sum to the tax, and no "rounding" line is ₹10 or more (a rounding line that size is a plug figure).
- The query-time LLM is measured on a stratified sample of 62 cases (4 per category). On that same sample, rules and compiled both score 100%.

### FY 2024-25

| Implementation | Cases | Rupee-exact | Silent wrong | Visible errors | Deterministic (10×) | p50 / p95 latency | Cost / 1,000 req | Traceable & correct |
|---|---|---|---|---|---|---|---|---|
| (a) rules | 293 | **293 (100%)** | 0 | 0 | yes | 0.1 ms / 0.1 ms | $0 | **100%** |
| (c) LLM-compiled | 293 | **293 (100%)** | 0 | 0 | yes | 0.1 ms / 0.1 ms | $0 at run time | 95.9% |
| (b) LLM at query time | 62 | 10 (16.1%) | **52** | 0 | **no**: 5, 8, 4, 10, 10 distinct answers | 3.3 s / 11.2 s | $3.11 | 14.5% |

### FY 2025-26

| Implementation | Cases | Rupee-exact | Silent wrong | Visible errors | Deterministic (10×) | p50 / p95 latency | Cost / 1,000 req | Traceable & correct |
|---|---|---|---|---|---|---|---|---|
| (a) rules | 298 | **298 (100%)** | 0 | 0 | yes | 0.1 ms / 0.1 ms | $0 | **100%** |
| (c) LLM-compiled | 298 | **298 (100%)** | 0 | 0 | yes | 0.1 ms / 0.1 ms | $0 at run time | 96.0% |
| (b) LLM at query time | 62 | 13 (21.0%) | **49** | 0 | **no**: 8, 7, 6, 10, 10 distinct answers | 3.0 s / 4.1 s | $3.10 | 19.4% |

**What the tables say**
- **Query-time LLM errors are large, not rounding noise.** Across the 25 failures recorded per year, no error was within ₹10. The median miss was ₹20,800 (FY 24-25) and ₹62,400 (FY 25-26), and the worst was ₹18.5 lakh. Failures cluster where the law has a second step: 87A marginal relief, surcharge marginal relief, age bands, the 288B rounding, and the 80C cap.
- **Its answers change between runs.** On two of the five inputs, 10 runs produced 10 different taxes. A user who asks twice gets two answers.
- **A trace that adds up is not proof.** In one case it computed ₹54,600 instead of ₹47,840 and added a "Sec 288B rounding adjustment" of ₹7,800 so its trace summed to the wrong total. That is why the traceability check rejects any "rounding" line of ₹10 or more.
- **Compiled code matches rules on accuracy, speed and determinism, but its trace has gaps.** In 14 regime results per year, it returns ₹0 tax with no tax lines at all, so the zero isn't explained by any clause. The rules engine had the same gap (71 results) until this benchmark exposed it. It now writes an explicit "Nil: lies entirely in the 0% slab" line.
- **Compile cost is paid once, not per request.** The final selection round cost $0.037 (FY 24-25, 3 candidates) and $0.068 (FY 25-26, 5 candidates), at 10–17 s per candidate. At $3.10 per 1,000 requests, the query-time LLM spends that in about 20 requests.

### Parsers — 50 plain-language descriptions

"Correct" means it computes when the description is complete (with every field right) and asks a question when it is not. An **unsafe guess** is computing a tax when it should have asked.

| Parser | Correct | Unsafe guesses | English | Hinglish | Terse | Incomplete | Contradictory | Ambiguous | p50 latency | Cost / 1,000 |
|---|---|---|---|---|---|---|---|---|---|---|
| regex baseline | 36/50 | **7** | 8/12 | 10/12 | 5/6 | 9/10 | 2/6 | 2/4 | <1 ms | $0 |
| LLM extract → rule gate | **49/50** | **0** | 11/12 | 12/12 | 6/6 | 10/10 | 6/6 | 4/4 | 1.2 s | $0.61 |

- **The one LLM miss is a safe one.** D03 says "consultant on payroll". The parser asked whether that was salary or consultancy income instead of computing. The expected answer was to compute, but asking is the right side to err on.
- **Determinism of the LLM parser** (3 messy descriptions × 10 runs): 1, 2 and 1 distinct outputs. On one description, a single run out of 10 gave a different result. That's far steadier than the query-time calculator (4–10 distinct answers), because the LLM only extracts fields and code does the rest.
- **Cost:** $0.61 per 1,000 descriptions, about a fifth of the query-time calculator's $3.10, because extraction prompts are short.

**The design that makes the parser safe.** The LLM only *extracts* fields from the text; it never decides whether enough is known. The same deterministic gate used by the calculators (`parser/common.decide`) makes that decision, so a missing salary or a contradiction always produces a question. The regex baseline fails in the opposite direction: it can't read "contradictory" or "ambiguous" text, so it fills a field and computes, which is 7 unsafe guesses.

## 3. Change log: FY 2024-25 → FY 2025-26 — `results/change_log.json`

**What changed in law:** new-regime slabs (nil to ₹4 L, seven bands, 30% above ₹24 L) and the Sec 87A rebate (income limit ₹7 L → ₹12 L, maximum ₹25,000 → ₹60,000). The old regime is unchanged.

| Implementation | What had to change | Effort | Result after the change |
|---|---|---|---|
| (a) rules | `rules/fy2025_26.yaml`: **34 lines** (slabs, rebate, clauses). **0 lines of engine code.** | Edit data, rebuild test cases from the oracle, rerun | 298/298 |
| (b) LLM at query time | `rules_text/fy2025_26.md`: **21 lines** | Edit text; nothing else | 13/62. It was never correct before the change either. |
| (c) LLM-compiled | Same 21 lines of rule text, then **recompile, review, gate, select** | 2 checklist rounds, 10 candidates | 298/298 (candidate 4 of round 2) |

**If someone forgets to update (stale deployment):** the FY 24-25 rules engine and the FY 24-25 compiled module, run on FY 25-26 cases, each give **230 of 298 wrong, with 0 errors raised**. Neither knows its law is out of date. A version check on the fiscal year (refuse to compute when the requested FY has no rules file) is therefore part of the final design, not an optional extra.

**Compile history: passing the edge cases is not enough.** Every compile was replayed on today's test suite:

| FY | Compile | Edge cases (original suite) | Held-out random | Silent wrong |
|---|---|---|---|---|
| 24-25 | v1, no feedback | 89/131 | 49/150 | 153 |
| 24-25 | review round 1 | **131/131** | 145/150 | **11** |
| 24-25 | review round 2 (regression) | 18/131 | 26/150 | 249 |
| 24-25 | round 3, candidates 0–4 | 0–131/131 (one crashed on all 143) | 0–150/150 | 0–153 |
| 24-25 | **selected: round 3, candidate 2** | 131/131 | **150/150** | **0** |
| 25-26 | checklist v1, candidates 0–4 | 75–100/136 | 51–146/150 | 46–172 |
| 25-26 | checklist v2 (+surcharge), candidates 0–4 | 0–136/136 (one crashed on all 148) | 0–150/150 | 0–159 |
| 25-26 | **selected: checklist v2, candidate 4** | 136/136 | **150/150** | **0** |

- **Three modules passed the entire original edge-case suite and were still silently wrong on held-out random cases** (11, 7 and 12 wrong). For example, an 85-year-old above ₹50 L got the under-60 slabs inside surcharge marginal relief. This led to two new edge categories (`age_surcharge`, `rounding_288b`, growing the suite from 131 to 143) and to a rule: **select on edge cases, report on held-out randoms.**
- **Review feedback can make it worse.** Round 2 fell from 131/131 to 18/131. Every recompile has to be re-gated; earlier success says nothing about the next compile.
- **Crashes are the good failure.** Two candidates crashed on every case and were rejected for free. The costly failures are the ones that return plausible numbers.

## 4. Final design

**Rules engine for the calculation, the LLM only at the edges, and both behind tests.**

1. **Computation: (a) rules.** It is exact, deterministic, costs nothing, answers in 0.1 ms, and has a complete clause-level trace. A Budget change is a data edit (34 YAML lines, 0 code).
2. **Authoring: (c) as an assistant, not as the production path.** The compiled module reached the same accuracy, but only after selection against a test suite that the rules engine and the oracle made possible. Its trace has gaps, and each recompile can regress. Its realistic role is drafting next year's YAML diff from the Finance Act for a human to review; the test suite then decides.
3. **Input: LLM extract → deterministic gate.** Natural-language input (Hinglish, terse) is where the LLM earns its cost. The decision to compute or ask stays in code, so the LLM can't make the system guess.
4. **(b) query-time LLM: not used for computing tax.** It was 16–21% rupee-exact, gave different answers on repeat runs, and produced plausible traces for wrong numbers.
5. **Guards:** refuse unknown fiscal years; every rule value carries its clause and a `verified` flag; CI runs the oracle suite and the official-calculator checks on every rule change.

## 5. Limitations (stated honestly)

- **⚠ The oracle is independent code but not an independent source.** It and the YAML were written from the same reading of the law, so a wrong constant in both would pass every test. The 30 rows in `tests/official_checks.csv` are meant to be checked against the official Income Tax Department calculator. **Their official columns are still empty, so that test (`test_engine.py`) is currently skipped.**
- **⚠ Most rule values are still `verified: false`** (only the FY 24-25 new-regime slabs are marked verified against the official text). The flags are honest, but the review isn't finished.
- The query-time LLM was measured on 62 stratified cases per year, not all 293/298, because of free-tier rate limits. Accuracy for (a) and (c) on the same 62 cases is 100%, so the comparison is like-for-like.
- Error magnitudes for (b) come from the first 25 recorded failures per year.
- Scope is salary income only; see README for the exclusions.
