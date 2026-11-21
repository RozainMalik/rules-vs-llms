# Project B — Data-quality checks: rules, statistics or LLM review?

Every number below is produced by **`python -m project_b.run`** and written to
`project_b/results/` (`profile.json`, `detector_matrix.csv/json`, `pipeline.json`,
`tables.md`). LLM responses are cached in `llm_cache/`. Run with `LLM_OFFLINE=1`
to replay them without an API key; a cache miss then fails loudly.

## 1. Data and set-up

| Item | Value |
|---|---|
| Source | NYC Open Data, 311 Service Requests (`erm2-nwe9`), Socrata API |
| Sample | first 800 rows (by `unique_key`) of **every day of 2023** = **292,000 rows**, 23 columns |
| Train split | Jan–Aug (194,400 rows). All reference data and models are learned here only. |
| Test split | Sep–Dec (97,600 rows). **Clean pool** = 88,267 test rows passing objective sanity filters (`refs.clean_mask`) |
| Batches | 2,000 rows; 10 clean batches; for each problem, 10 corrupted copies at a 2% row rate (batch-level problems a/b/g: one corruption per batch) |
| LLM | `gemini-3.5-flash-lite`, priced at paid-tier list prices ($0.30 / M input, $2.50 / M output tokens). Project B made **119 real calls** in total ($0.13 equivalent). |

Reference data comes from the data itself; no external lists. It covers ZIP→borough shares, (complaint type, descriptor) pair counts, per-agency null rates, open vs finished resolution texts, the date-format signature, column value profiles and the free-text vocabulary. Fitted models: state-plane x/y → lat/lon (linear), a geo nearest-neighbour index, Naive Bayes descriptor→complaint type, and logistic regression resolution text→open/closed.

## 2. Real problems found in the raw 2023 data (`results/profile.json`)

| Problem | Rows | % | Where / example |
|---|---|---|---|
| `due_date` empty | 290,408 | 99.5% | Column is effectively dead. A dashboard metric built on it would be silently empty. |
| Near-duplicates (same complaint, descriptor and address within 15 min) | 21,171 | 7.25% | 86% NYPD: several callers report the same party or car. Whether these count as one incident or many is a **business decision**, not a data bug. |
| Status vs resolution contradiction (phrase rule) | 2,341 | 0.80% | Mostly DSNY "…will be referred to the NYPD for further action" on Closed rows. That's a legitimate referral, so the **phrase rule over-fires on real data**, which is a key input to the k design. |
| Mojibake in text (`Parksâ`, `Transportationâs`) | 6,235 | 2.14% | DOT 5,761, DPR 385: UTF-8 read as Latin-1 upstream. |
| Phone pattern in resolution text | 7,218 | 2.47% | Almost all are **official** numbers: `212-639-9675` (311 outside NYC) 6,600+, `(212) 487-4110`, `(212) 676-1600`. Not PII, but a naive regex flags them. |
| Email pattern in text | 231 | 0.08% | `infobfscs@health.nyc.gov`, `customerservice@dsny.nyc.gov` (template constants) |
| Zero duration (closed == created) | 4,229 | 1.45% | DOHMH 2,057 (Rodent), DOB 833, DOT 822: auto-closed records |
| `resolution_action_updated_date` before `created_date` | 3,659 | 1.25% | HPD 1,748, DOB 834, DOT 754 |
| Missing lat/lon | 3,643 | 1.25% | DOT 1,520, NYPD 1,411 |
| Closed more than 365 days after creation | 3,275 | 1.12% | DPR 1,344 (tree work orders), DOHMH 947 |
| Missing ZIP | 3,035 | 1.04% | DHS 982, NYPD 932 |
| Missing descriptor | 3,034 | 1.04% | **All DHS**: an agency-specific null pattern, exactly the shape of problem g |
| Missing resolution text | 2,180 | 0.75% | EDC 1,010, DSNY 647 |
| Status Closed but `closed_date` missing | 1,294 | 0.44% | **All DHS** (Homeless Person Assistance) |
| Open-type status but `closed_date` present | 370 | 0.13% | DOT 283, DOB 82 |
| Closed before created | 356 | 0.12% | DOT 279, NYPD 75 |
| Borough "Unspecified" | 284 | 0.10% | DOT, NYPD, TLC |
| Rows identical except `unique_key` | 176 | 0.06% | HPD 94, DEP 44: double-submitted records |
| ZIP/borough pair <2% of that ZIP | 4 | 0.001% | very rare in this sample |
| Complaint-type case variants | 2 types | – | `ELEVATOR`/`Elevator`, `PLUMBING`/`Plumbing`: these split a dashboard group-by in two |

## 3. Every detector on every problem (`results/detector_matrix.csv`)

How to read the columns:
- **Detection**: row-level problems use recall over corrupted rows; batch-level problems (a, b, g) use the share of corrupted batches alarmed.
- **False alarms**: rows flagged in clean batches as a share of all clean rows (a/b/g: share of clean batches alarmed).
- **$ / M rows**: LLM cost extrapolated from measured tokens; rules and stats have no API cost.
- **Rows/s**: measured on this laptop. LLM throughput assumes sequential calls.
- **Clarity**: an automatic 0–3 rubric. +1 if the alert names the field, +1 if it states the violated expectation, +1 if it shows the evidence value.

LLM rows use small samples (3 corrupted + 2 clean samples × 40 rows, or 3 + 3 batches), so expect roughly ±15 points of sampling error.

| # | Problem | Detector | Detection | Precision | False alarms | $ / M rows | Rows/s | Clarity |
|---|---|---|---|---|---|---|---|---|
| a | renamed/dropped column | **rule** | 100% | – | 0% | 0 | 1.1e8 | 3.0 |
| a | | stat | 100% | – | 0% | 0 | 1.2e6 | 2.0 |
| a | | llm | 100% | – | 0% | 0.23 | 1,396 | 3.0 |
| b | column type change | **rule** | 100% | – | 0% | 0 | 1.4e7 | 3.0 |
| b | | stat | 50% | – | 0% | 0 | 2.1e6 | 3.0 |
| b | | llm | 100% | – | 0% | 0.25 | 2,380 | 3.0 |
| c | date-format switch | **rule** | 100% | 100% | 0% | 0 | 233,054 | 3.0 |
| c | | stat | 100% | 100% | 0% | 0 | 200,420 | 3.0 |
| c | | llm | 100% | 100% | 0% | 73.26 | 15 | 3.0 |
| d | lat/lon swapped | **rule** | 100% | 100% | 0% | 0 | 3.3e6 | 3.0 |
| d | | stat | 100% | 100% | 0% | 0 | 111,106 | 3.0 |
| d | | llm | 100% | 100% | 0% | 50.87 | 16 | 3.0 |
| e | exact duplicates | **rule** | 100% | 100% | 0% | 0 | 481,062 | 3.0 |
| e | | stat | 100% | 100% | 0% | 0 | 127,267 | 2.0 |
| e | | llm | 50% | 100% | 0% | 38.65 | 29 | 3.0 |
| f | near-duplicates | **rule** | 100% | 92.2% | 0.36% | 0 | 32,776 | 3.0 |
| f | | stat | 93.8% | 45.1% | 4.66% | 0 | 7,506 | 1.0 |
| f | | llm | 93.3% | 100% | 0% | 53.76 | 19 | 3.0 |
| g | null spike in one agency | rule | 100% | – | 0% | 0 | 325,404 | 3.0 |
| g | | **stat** | 100% | – | 0% | 0 | 318,234 | 3.0 |
| g | | llm | 66.7% | – | **33%** | 0.63 | 1,374 | 2.0 |
| h | closed before created | **rule** | 100% | 100% | 0% | 0 | 1.4e6 | 3.0 |
| h | | stat | 100% | 100% | 0% | 0 | 224,028 | 2.0 |
| h | | llm | 100% | 100% | 0% | 54.26 | 5 | 3.0 |
| i | ZIP vs borough | **rule** | 99.8% | 100% | 0% | 0 | 1.7e6 | 3.0 |
| i | | stat | 100% | 95.7% | 0.10% | 0 | 15,664 | 3.0 |
| i | | llm | 100% | 100% | 1.25% | 36.14 | 5 | 2.3 |
| j | complaint type vs descriptor | **rule** | 100% | 98.3% | 0.04% | 0 | 2.8e6 | 3.0 |
| j | | stat | 100% | 66.8% | 1.01% | 0 | 37,722 | 3.0 |
| j | | llm | 73.3% | 100% | 0% | 21.23 | 5 | 3.0 |
| k | resolution vs status | rule | 83.2% | 74.3% | 0.58% | 0 | 76,842 | 3.0 |
| k | | stat | 99.8% | 92.6% | 0.16% | 0 | 49,431 | 2.0 |
| k | | llm | 66.7% | 100% | 0% | 27.66 | 9 | 3.0 |
| l | PII in free text | rule (regex) | 66.8% | 100% | 0% | 0 | 35,438 | 2.0 |
| l | | stat (novel tokens) | 100% | 99.0% | 0.02% | 0 | 131,129 | 3.0 |
| l | | llm | 100% | 100% | 0% | 32.22 | 8 | 1.9 |

**What the matrix says**
- **Contract problems (a, b, c, d, e, h, i) belong to rules.** Rules reach 100% detection with 0% false alarms, run at 10⁵–10⁸ rows/s and cost nothing. The LLM costs $37–$73 per million rows on these problems and is no better. On exact duplicates it misses half, because it can't compare 40 rows reliably.
- **b shows why value statistics aren't enough:** a latitude arriving as the *string* `"40.712345"` has the same value distribution, so the stats detector misses 50%. Only the schema rule checks the type.
- **g belongs to statistics (or a rule derived from statistics).** From a 40-row sample the LLM alarmed on a third of *clean* batches. It sees rows, not rates.
- **Semantic problems (j, k, l) are where the families differ.** The k phrase rule has 0.58% false alarms and also over-fires on real data (section 2). The text model is far better (99.8% recall / 0.16% false alarms). The l regex misses every **name-only** mention (66.8% detection), while the novel-token statistic catches them. The LLM is precise everywhere (100% precision) but has the lowest recall on j and k, and costs $21–$32 per million rows *per problem*.
- **f:** the rule beats TF-IDF similarity (0.36% vs 4.66% false alarms), because standard address normalisation is a better "same place" signal than character n-grams.

## 4. Hybrid pipeline (`project_b/pipeline.py`, `results/pipeline.json`)

**Design:** rules run on every row; statistics run per batch; the LLM runs **only on rows where the cheap detectors are unsure**, deduplicated on the reviewed values.

| # | Problem | Plan | Detection | Precision | False alarms |
|---|---|---|---|---|---|
| a | renamed/dropped column | rule | 100% | – | 0% |
| b | type change | rule | 100% | – | 0% |
| c | date-format switch | rule | 100% | 100% | 0% |
| d | lat/lon swapped | rule | 100% | 100% | 0% |
| e | exact duplicates | rule | 100% | 100% | 0% |
| f | near-duplicates | rule | 100% | 85.6% | 0.49% |
| g | agency null spike | stat (binomial z-test) | 100% | – | 0% |
| h | closed before created | rule | 100% | 100% | 0% |
| i | ZIP vs borough | rule | 100% | 100% | 0% |
| j | complaint vs descriptor | rule | 100% | 98.8% | 0.01% |
| k | resolution vs status | rule AND stat → alert; rule XOR stat → **LLM decides** | 92.5% | 96.1% | 0.09% |
| l | PII in text | regex → alert; novel tokens without a regex hit → **LLM decides** | 100% | 100% | 0% |

**End to end (from `pipeline.json`):**
- Scale of the test: 60,160 rows; 33 LLM calls on 215 rows, which is **0.36% of rows**.
- LLM cost: $0.0093 in total, or **$0.155 per million rows**.
- CPU throughput: **9,637 rows/s** for all 12 checks in one Python process.
- Mean latency per 2,000-row batch: 2.9 s including LLM tie-breaks; about 0.2 s without them.
- On 4,000 **real, unfiltered** Sep–Dec rows, the pipeline raised:
  - 24 near-duplicate alerts;
  - 4 null-spike alerts (for example DHS `closed_date`, matching the profile);
  - 7 closed-before-created alerts;
  - 1 resolution contradiction ("conditions are still open" on a Closed HPD row);
  - 1 LLM call in total, costing **$0.06 per million rows**.

**Two design iterations, decided by measurement:**
1. *v1: the LLM confirms every j/k/l flag* (`results/pipeline_v1_llm_confirms_all.json`). Recall **fell**: j from 100% to 84%, and k (after fixing a parser bug) to 61%. False alarms dropped by only a few hundredths of a percent, and the version cost 3.4× more ($0.525 vs $0.155 per million rows). The LLM is a precise but conservative reviewer, so making it the final gate throws away real errors. v2 uses it only as a tie-breaker.
2. *Real-data false alarm:* the regex flagged `(212) 487-4110`, an agency number. The fix uses statistics: any phone or email that appears in five or more training rows is a template constant (`refs.template_contacts`). After the fix, real-data PII false alarms went to 0.

**Bug found while measuring:** Gemini sometimes returns a bare JSON list instead of `{"flags": [...]}`. My parser treated that as "no flags", a *silent failure*: it made the LLM look 33% accurate on h when it was really 100%. It's fixed in `detectors/llm.py`, and all numbers above are after the fix.

## 5. Scale design: 50 M rows/day across 120 customers with different schemas

**Load:** 50 M rows/day averages 579 rows/s; assume peaks of 3–5×, about 3,000 rows/s.

| Cost / latency | Hybrid pipeline (measured → projected) | LLM reviews every row (for comparison) |
|---|---|---|
| CPU | 9,637 rows/s per process gives 50 M rows in **≈ 1.4 core-hours/day**. One core covers the average and four cover the peaks (≈ $2/day cloud CPU). | – |
| LLM rows | 0.28–0.36% of rows = 140–180 k rows/day. At 40 rows per call that's about 3.5–4.5 k calls/day, roughly 3 per minute. | 50 M rows × 9 row-level checks |
| LLM cost | $0.06–$0.155 per M rows = **$3–$8 per day (≈ $90–$230 per month)** | Measured $388 per M rows (c..l summed) = **≈ $19,400 per day (≈ $7 M per year)**, about 2,500× more |
| Latency | Rule and stat alerts in **≈ 0.2 s per 2,000-row batch**; LLM tie-breaks arrive asynchronously in 1–9 s | 5–29 rows/s per stream, so ~500 concurrent streams would be needed to keep up |

**What changes at this scale, and why:**

1. **Schemas become configuration, and the LLM moves to onboarding.**
   - With 120 schemas, the hand-written column names in `schema.py` become a **per-customer data contract** (YAML): column mapping, types, and which checks apply.
   - The LLM is useful **once per customer**: it proposes the mapping from their columns to canonical fields, a human reviews it, and the mapping is frozen as rules. This is the same "LLM compiles, human reviews, rules run" pattern as Project A.
   - The statistical profile matcher (detector a/stat) suggests renames automatically when a customer's schema drifts.
2. **Reference data is learned per customer.** ZIP→borough, descriptor pairs and null baselines are NYC-311 facts. Every customer needs its own baselines, learned from their history.
   - Cold start: run only the schema and contract rules for the first ~30 days, then enable the statistical checks.
3. **Duplicates must be found across batches, not just within one.** `duplicated()` only sees one batch. At 50 M rows/day we need:
   - a keyed store of row hashes with a TTL. A 7-day TTL holds about 350 M hashes × 16 B ≈ 6 GB in RocksDB or Redis, or less with a Bloom filter;
   - a **blocking-key index** (customer, normalised address, complaint, 15-minute bucket) for near-duplicates.
4. **Alert budgets replace fixed thresholds.**
   - 120 customers × agencies × columns means **tens of thousands of null-rate tests per window**. Thresholds should be calibrated per customer to an alert budget (for example ≤ 1 false alarm per customer per week) by replaying clean history, with FDR control across the tests.
   - The 7% "near-duplicate" rate in real data shows the definition must be agreed per customer: are they counting complaints or incidents?
5. **Code paths get vectorised.**
   - The rule loops (ZIP, descriptor, PII) are per-row Python. Joins in Polars or DuckDB would give 10–100×, and partitioning by customer makes the work embarrassingly parallel.
   - Rules and stats stay well under 1% of the budget; the expensive part is human attention, not compute.
6. **The LLM becomes cheaper, not more expensive, as volume grows.**
   - Verdicts depend only on the reviewed values. k is decided by (status, resolution text), and there are only ~550 distinct resolution texts in 292 k rows. Making the in-batch dedupe a **persistent verdict cache** drives steady-state k and j calls towards zero.
   - The Batch API halves the price of the rest, since tie-breaks aren't latency-critical.
   - The pipeline **never blocks on the LLM**: if Gemini is down or rate-limited, k falls back to the text model alone (measured 99.8% recall / 0.16% false alarms) and l to regex plus novelty.
7. **Privacy reverses one choice.** Sending suspected-PII text to an external LLM is itself a data-protection problem once 120 customers' contracts apply. At scale, l would run the LLM tie-break on **redacted** text, or on a self-hosted model, or drop the LLM and send novel-token hits to a human queue.
8. **Drift is monitored.** New (complaint, descriptor) pairs appear every month. Today they become j false alarms (0.04%). A weekly job sends *new* pairs to the LLM once, a human approves them, and they join the allow-list: LLM output becomes reviewed rules. The text models for j and k are retrained monthly.

## 6. Limitations (stated honestly)

- **The corruptions are synthetic,** and some rules match the injector closely: the ISO regex, the suffix normalisation for f. Real-world detection will be lower than 100%, which is why the real-data run in section 4 is reported separately.
- **LLM rows rest on small samples:** 30 positive and 80 clean rows per problem. The ranking (rules ≥ stats > LLM on contract problems) is robust; individual LLM percentages are not.
- **The clean pool excludes rows with pre-existing problems of the objective kinds,** so false-alarm rates on unfiltered production data will be higher. Section 2 shows the base rates.
- **The clarity score is an automatic heuristic,** not a human rating.
- **The rule thresholds** (15-minute window, +25 percentage-point null margin, 2% ZIP share, z = 6) were chosen by reading the training months, not optimised on the test set.
