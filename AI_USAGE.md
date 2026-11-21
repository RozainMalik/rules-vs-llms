# AI usage

## Tools and what they were used for

| Tool | Used for |
|---|---|
| **Claude Code (Claude Opus 5.5)**, in VS Code | Pair-programming the whole repository: rule YAML, engine, oracle, test-case generator, LLM wrappers, parsers, benchmark, Project B detectors/pipeline, and first drafts of the result documents. Project B was built by a Claude Code background sub-agent while Project A was being built in the main session. I reviewed, ran and questioned every file; the walkthrough of each file is how I made sure I can explain and change it. |
| **Gemini `gemini-3.5-flash-lite`** (free tier) | The *subject under test*, never a coding assistant: implementation (b) computes tax at query time, implementation (c) compiles rule text into Python, the plain-language parser, and Project B's LLM detectors. Every response is cached in `llm_cache/` and committed. |

Model choice was forced by measurement, not preference: `gemini-2.5-*` returned 404 for new users; `gemini-3.5-flash`, `3.6-flash` returned 503 (overloaded); `gemini-3.8-flash` took **280 s** to answer "17×23"; `3.5-flash-lite` answered in 1–2 s.

## Where the AI was wrong, and how it was caught

### 1. The coding assistant got the LLM price wrong by 3–6× (caught by checking the official page)
While writing `common/llm.py`, Claude filled the pricing table from memory with **$0.10 / $0.40 per million tokens** for flash-lite. Before any number was reported I checked Google's official pricing page, which lists **$0.30 input / $2.50 output** (Standard tier). Every "cost per 1,000 requests" and "cost per million rows" figure would have been understated 3× on input and 6× on output — a silent error, because cost is computed, never asserted against anything. Fix: corrected the table, added the source and date as a comment, and the rule *"prices are looked up, never remembered"*.

### 2. The coding assistant corrupted `.gitignore` (caught by `git status`)
The original `.gitignore` had no trailing newline. Claude appended `.pytest_cache/` with `printf`, which glued it onto the last line, producing the single pattern `data/raw/.pytest_cache/`. That silently **un-ignored the 128 MB raw NYC 311 sample**. It was caught because `git status` showed `?? data/` after a commit; I checked with `cat -e .gitignore`, split the line, and confirmed with `git ls-files` that nothing large had been committed.

### 3. Gemini, as the system under test, was wrong in instructive ways (caught by the test suite)
- **Fabricated audit trail (query-time LLM).** For one case it computed ₹54,600 instead of ₹47,840 and then invented a "Sec 288B rounding adjustment" of **₹7,800** so its trace still summed to the wrong total. A trace that adds up is not proof. The benchmark's traceability check therefore rejects any "rounding" line ≥ ₹10.
- **Code that looks right but isn't (compiled rules).** v1 used `amount.quantize(Decimal('10'))`, which rounds to the nearest *rupee*, not ten rupees: 138/281 cases wrong by a few rupees, no error raised. A later version's docstring said "floor the paise" while the code used `ROUND_HALF_UP` — comment and code disagreed, and only 5 random cases exposed it.
- **Passing every edge case is not enough.** Three compiled modules passed the entire edge-case suite and were still wrong on held-out random cases (an 85-year-old above ₹50 L got the under-60 slabs inside surcharge marginal relief). This led to two new edge-case categories (`age_surcharge`, `rounding_288b`) and to selecting candidates on edge cases while reporting on held-out randoms.
- **Silent parser bug in Project B.** Gemini sometimes returned a bare JSON list instead of `{"flags": [...]}`; the parser read that as "no flags", making the LLM look 33% accurate on problem *h* when it was really 100%. Fixed in `project_b/detectors/llm.py`.

## What I did not delegate
- The expected tax values do not come from any AI: they come from an independent oracle (`project_a/tests/oracle.py`) and from the **official Income Tax Department calculator** for the 30 cases in `project_a/tests/official_checks.csv`, which I entered by hand.
- Every `verified: true` flag in the rules YAML means I read the clause in the official source myself.
