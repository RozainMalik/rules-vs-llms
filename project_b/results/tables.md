| # | Problem | Detector | Detection | Precision | False alarms (clean) | $ / M rows | Rows/s | Clarity 0-3 |
|---|---|---|---|---|---|---|---|---|
| a | renamed_or_dropped_column | llm | 100.0% | – | 0.00% | 0.23 | 1,396 | 3.0 |
| a | renamed_or_dropped_column | rule | 100.0% | – | 0.00% | 0.00 | 88,049,096 | 3.0 |
| a | renamed_or_dropped_column | stat | 100.0% | – | 0.00% | 0.00 | 696,022 | 2.0 |
| b | column_type_change | llm | 100.0% | – | 0.00% | 0.25 | 2,380 | 3.0 |
| b | column_type_change | rule | 100.0% | – | 0.00% | 0.00 | 10,182,760 | 3.0 |
| b | column_type_change | stat | 50.0% | – | 0.00% | 0.00 | 1,087,339 | 3.0 |
| c | date_format_switch | llm | 100.0% | 100.0% | 0.00% | 73.26 | 15 | 3.0 |
| c | date_format_switch | rule | 100.0% | 100.0% | 0.00% | 0.00 | 153,254 | 3.0 |
| c | date_format_switch | stat | 100.0% | 100.0% | 0.00% | 0.00 | 140,046 | 3.0 |
| d | lat_lon_swapped | llm | 100.0% | 100.0% | 0.00% | 50.87 | 16 | 3.0 |
| d | lat_lon_swapped | rule | 100.0% | 100.0% | 0.00% | 0.00 | 2,865,287 | 3.0 |
| d | lat_lon_swapped | stat | 100.0% | 100.0% | 0.00% | 0.00 | 78,063 | 3.0 |
| e | exact_duplicates | llm | 50.0% | 100.0% | 0.00% | 38.65 | 29 | 3.0 |
| e | exact_duplicates | rule | 100.0% | 100.0% | 0.00% | 0.00 | 382,149 | 3.0 |
| e | exact_duplicates | stat | 100.0% | 100.0% | 0.00% | 0.00 | 69,143 | 2.0 |
| f | near_duplicates | llm | 93.3% | 100.0% | 0.00% | 53.76 | 19 | 3.0 |
| f | near_duplicates | rule | 100.0% | 92.2% | 0.36% | 0.00 | 20,128 | 3.0 |
| f | near_duplicates | stat | 93.8% | 45.1% | 4.66% | 0.00 | 5,036 | 1.0 |
| g | agency_null_spike | llm | 66.7% | – | 33.33% | 0.63 | 1,374 | 2.0 |
| g | agency_null_spike | rule | 100.0% | – | 0.00% | 0.00 | 238,537 | 3.0 |
| g | agency_null_spike | stat | 100.0% | – | 0.00% | 0.00 | 251,527 | 3.0 |
| h | closed_before_created | llm | 100.0% | 100.0% | 0.00% | 54.26 | 5 | 3.0 |
| h | closed_before_created | rule | 100.0% | 100.0% | 0.00% | 0.00 | 1,049,168 | 3.0 |
| h | closed_before_created | stat | 100.0% | 100.0% | 0.00% | 0.00 | 174,034 | 2.0 |
| i | zip_borough_mismatch | llm | 100.0% | 100.0% | 1.25% | 36.14 | 5 | 2.33 |
| i | zip_borough_mismatch | rule | 99.8% | 100.0% | 0.00% | 0.00 | 1,501,192 | 3.0 |
| i | zip_borough_mismatch | stat | 100.0% | 95.7% | 0.10% | 0.00 | 12,162 | 3.0 |
| j | complaint_descriptor_mismatch | llm | 73.3% | 100.0% | 0.00% | 21.23 | 5 | 3.0 |
| j | complaint_descriptor_mismatch | rule | 100.0% | 98.3% | 0.04% | 0.00 | 2,506,168 | 3.0 |
| j | complaint_descriptor_mismatch | stat | 100.0% | 66.8% | 1.01% | 0.00 | 26,505 | 3.0 |
| k | resolution_contradicts_status | llm | 66.7% | 100.0% | 0.00% | 27.66 | 9 | 3.0 |
| k | resolution_contradicts_status | rule | 83.2% | 74.3% | 0.58% | 0.00 | 67,967 | 3.0 |
| k | resolution_contradicts_status | stat | 99.8% | 92.6% | 0.16% | 0.00 | 35,752 | 2.0 |
| l | pii_in_free_text | llm | 100.0% | 100.0% | 0.00% | 32.22 | 8 | 1.93 |
| l | pii_in_free_text | rule | 66.8% | 100.0% | 0.00% | 0.00 | 30,914 | 2.0 |
| l | pii_in_free_text | stat | 100.0% | 99.0% | 0.02% | 0.00 | 101,354 | 3.0 |

| # | Problem | Hybrid plan | Detection | Precision | False alarms |
|---|---|---|---|---|---|
| a | renamed_or_dropped_column | rule | 100.0% | – | 0.00% |
| b | column_type_change | rule | 100.0% | – | 0.00% |
| c | date_format_switch | rule | 100.0% | 100.0% | 0.00% |
| d | lat_lon_swapped | rule | 100.0% | 100.0% | 0.00% |
| e | exact_duplicates | rule | 100.0% | 100.0% | 0.00% |
| f | near_duplicates | rule | 100.0% | 85.6% | 0.49% |
| g | agency_null_spike | stat | 100.0% | – | 0.00% |
| h | closed_before_created | rule | 100.0% | 100.0% | 0.00% |
| i | zip_borough_mismatch | rule | 100.0% | 100.0% | 0.00% |
| j | complaint_descriptor_mismatch | rule | 100.0% | 98.8% | 0.01% |
| k | resolution_contradicts_status | rule&stat; LLM on rule^stat | 92.5% | 96.1% | 0.09% |
| l | pii_in_free_text | rule; LLM on stat-rule | 100.0% | 100.0% | 0.00% |

Pipeline totals: 60,160 rows, 33 LLM calls on 215 rows (0.36% of rows), LLM cost $0.0093 => $0.155 per million rows; CPU throughput 7,200 rows/s; mean latency per 2,000-row batch 2.98 s.