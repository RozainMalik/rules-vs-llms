
### Calculators — FY 2024-25

| Implementation | Cases | Rupee-exact | Silent wrong | Visible errors | Deterministic (10x) | p50 latency | Cost / 1,000 req | Traceable & correct |
|---|---|---|---|---|---|---|---|---|
| rules | 293 | 293 (100.0%) | 0 | 0 | yes | 0.1 ms | $0.00 | 100.0% |
| llm_compiled | 293 | 293 (100.0%) | 0 | 0 | yes | 0.1 ms | $0.00 | 95.9% |
| llm_query | 62 | 10 (16.1%) | 52 | 0 | NO [5, 8, 4, 10, 10] | 3327.0 ms | $3.11 | 14.5% |

### Calculators — FY 2025-26

| Implementation | Cases | Rupee-exact | Silent wrong | Visible errors | Deterministic (10x) | p50 latency | Cost / 1,000 req | Traceable & correct |
|---|---|---|---|---|---|---|---|---|
| rules | 298 | 298 (100.0%) | 0 | 0 | yes | 0.1 ms | $0.00 | 100.0% |
| llm_compiled | 298 | 298 (100.0%) | 0 | 0 | yes | 0.1 ms | $0.00 | 96.0% |
| llm_query | 62 | 13 (21.0%) | 49 | 0 | NO [8, 7, 6, 10, 10] | 3011.0 ms | $3.10 | 19.4% |

### Parsers — 50 plain-language descriptions

| Parser | Correct | Unsafe guesses | English | Hinglish | Terse | Incomplete | Contradictory | Ambiguous | p50 latency | Cost / 1,000 |
|---|---|---|---|---|---|---|---|---|---|---|
| regex | 36/50 | 7 | 8/12 | 10/12 | 5/6 | 9/10 | 2/6 | 2/4 | 0.0 ms | $0.00 |
| llm_hybrid | 49/50 | 0 | 11/12 | 12/12 | 6/6 | 10/10 | 6/6 | 4/4 | 1201.0 ms | $0.61 |