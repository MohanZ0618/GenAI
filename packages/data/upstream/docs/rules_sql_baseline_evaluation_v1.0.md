# Rules/SQL Baseline Evaluation — Version 1.0

## 1. Executive summary

The frozen deterministic baseline implemented all 15 registered rules and evaluated 439 held-out test cases. Exact 16-class accuracy was 0.849658; binary anomaly F1 was 0.980066. No learned model, LLM, API, or external service was used.

## 2. Frozen-spec provenance

- Specification: `docs/frozen_rules_sql_baseline_spec_v1.0.md`
- SHA-256: `0ee3192dd760dd2521791ef46543c9c7337cc6d8eff0f3cd4a7cba9e5d645675`
- Checksum verification: PASS
- Specification version: 1.0

## 3. Implementation architecture

The implementation uses CPython standard-library CSV parsing, strict `Decimal` arithmetic, deterministic Unicode/date normalization, in-memory relational indexes, explicit rule traces, tri-state aggregation, automated evidence-contract checks, and frozen single-label precedence. Every scored anomaly is traceable to `RSQL_F01_V1`–`RSQL_F15_V1`.

## 4. Dataset and evaluation setup

- Dataset version: `FinRCA-Bench v1 seed 42`
- Model-visible snapshot SHA-256: `d8dcd68290524db221bf07f5f654e4b930a039efb3f6ecabd98aa6e38eb7c662`
- Validation split: `data/benchmark/validation/case_ids.txt`
- Test split: `data/benchmark/test/case_ids.txt`
- Observation cutoff: `2026-06-30`
- Test cases: 439

## 5. F01 validation procedure and selected parameters

The frozen 3×4 grid was evaluated on validation only. The objective was macro-F1 over all 16 output classes; ties used higher similarity, then shorter window, then the initial value.

- Selected date window: 7 days
- Selected similarity: 1.00
- Validation macro-F1: 0.968053
- Objective ties: 12
- Decision: Selected similarity 1.00 and window 7 by the frozen objective/tie-break ordering.

## 6. Overall results

| Metric | Value |
| --- | --- |
| total_cases | 439 |
| exact_failure_type_accuracy | 0.849658 |
| binary_anomaly_accuracy_with_abstentions_incorrect | 0.858770 |
| binary_precision | 0.960912 |
| binary_recall | 1.000000 |
| binary_f1 | 0.980066 |
| false_positive_rate | 0.083333 |
| false_negative_rate_including_insufficient_as_missed | 0.000000 |
| macro_f1_16_classes | 0.951773 |
| micro_f1_16_classes | 0.900966 |
| weighted_f1_16_classes | 0.888683 |
| insufficient_evidence | 50 |

## 7. Results by failure type

| rule | failure_type | N | precision | recall | f1 | FP | FN | insufficient_evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RSQL_F01_V1 | F01_DUPLICATE_INVOICE | 21 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 |
| RSQL_F02_V1 | F02_PO_INVOICE_AMOUNT_MISMATCH | 20 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 |
| RSQL_F03_V1 | F03_QUANTITY_MISMATCH | 18 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 |
| RSQL_F04_V1 | F04_INCORRECT_VENDOR_ASSOCIATION | 17 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 |
| RSQL_F05_V1 | F05_PAYMENT_WITHOUT_VALID_INVOICE | 22 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 |
| RSQL_F06_V1 | F06_INVOICE_PAID_TWICE | 12 | 1.0 | 0.8333333333333334 | 0.9090909090909091 | 0 | 2 | 0 |
| RSQL_F07_V1 | F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE | 18 | 0.75 | 1.0 | 0.8571428571428571 | 6 | 0 | 0 |
| RSQL_F08_V1 | F08_APPROVAL_WORKFLOW_FAILURE | 22 | 0.9166666666666666 | 1.0 | 0.9565217391304348 | 2 | 0 | 0 |
| RSQL_F09_V1 | F09_GL_POSTING_MISMATCH | 17 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 |
| RSQL_F10_V1 | F10_WRONG_ACCOUNTING_PERIOD | 20 | 0.9523809523809523 | 1.0 | 0.975609756097561 | 1 | 0 | 0 |
| RSQL_F11_V1 | F11_VENDOR_MASTER_CHANGE_CONFLICT | 23 | 0.8214285714285714 | 1.0 | 0.9019607843137255 | 5 | 0 | 0 |
| RSQL_F12_V1 | F12_ERP_PAYMENT_MISSING_FROM_BANK | 21 | 1.0 | 0.9047619047619048 | 0.9500000000000001 | 0 | 2 | 0 |
| RSQL_F13_V1 | F13_BANK_TRANSACTION_MISSING_FROM_ERP | 28 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 |
| RSQL_F14_V1 | F14_BANK_ERP_AMOUNT_MISMATCH | 16 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 |
| RSQL_F15_V1 | F15_INCORRECT_PAYMENT_BANK_MATCH | 20 | 0.9090909090909091 | 1.0 | 0.9523809523809523 | 2 | 0 | 0 |

## 8. Results by Tier

| tier | N | accuracy_exact_within_group | precision_group_one_vs_rest | recall_group_one_vs_rest | f1_group_one_vs_rest | false_positive_rate | false_negative_rate | insufficient_evidence_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 21 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 |
| 2 | 103 | 0.9805825242718447 | 0.9901960784313726 | 0.9805825242718447 | 0.9853658536585367 | 0.002976190476190476 | 0.019417475728155338 | 0.0 |
| 3 | 171 | 0.9883040935672515 | 0.9293478260869565 | 1.0 | 0.9633802816901409 | 0.048507462686567165 | 0.0 | 0.0 |

## 9. Results by hop count

| hop_count | N | accuracy_exact_within_group | precision_group_one_vs_rest | recall_group_one_vs_rest | f1_group_one_vs_rest | false_positive_rate | false_negative_rate | insufficient_evidence_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 21 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 |
| 1 | 103 | 0.9805825242718447 | 0.9901960784313726 | 0.9805825242718447 | 0.9853658536585367 | 0.002976190476190476 | 0.019417475728155338 | 0.0 |
| 2 | 129 | 0.9844961240310077 | 0.927536231884058 | 0.9922480620155039 | 0.9588014981273408 | 0.03225806451612903 | 0.007751937984496124 | 0.0 |
| 3 | 20 | 1.0 | 0.9090909090909091 | 1.0 | 0.9523809523809523 | 0.00477326968973747 | 0.0 | 0.0 |
| 4 | 22 | 1.0 | 0.9166666666666666 | 1.0 | 0.9565217391304348 | 0.004796163069544364 | 0.0 | 0.0 |

## 10. Evidence-contract results

| Metric | Value |
| --- | --- |
| anomaly_decisions | 307 |
| evidence_contract_accuracy | 1.000000 |
| evidence_id_micro_precision_if_definable | 0.579749 |
| evidence_id_micro_recall_if_definable | 0.602982 |
| correct_anomaly_predictions | 291 |
| percentage_correct_anomaly_predictions_with_correct_complete_evidence | 0.130584 |
| percentage_correct_anomaly_predictions_with_incomplete_evidence | 0.869416 |
| percentage_all_incorrect_predictions_caused_by_unavailable_evidence | 0.757576 |
| evidence_id_metric_note | IDs compare returned record primary-key tokens with benchmark evidence IDs; classification and internal frozen evidence-contract checks are reported separately. |

Classification correctness and evidence correctness are separate. Evidence ID precision/recall compare returned primary-key tokens with benchmark evidence IDs; anti-join evidence is assessed by the frozen internal contract and snapshot-completeness checks.

## 11. Tri-state analysis

Overall state frequencies: `{"ANOMALY": 307, "INSUFFICIENT_EVIDENCE": 50, "MATCH": 82}`. Detailed failure-type, tier, and exact-hop state counts are saved in `tri_state.json`.

## 12. Latency / operational results

| Metric | Value |
| --- | --- |
| total_evaluation_runtime_seconds | 4.465088 |
| case_latency_sum_seconds | 4.314062 |
| mean_latency_ms | 9.827020 |
| median_latency_ms | 9.171125 |
| p95_latency_ms | 18.920417 |
| p99_latency_ms | 27.137458 |
| throughput_cases_per_second | 98.318326 |
| case_count | 439 |
| runtime_technology | CPython 3.11.3 standard-library in-memory relational indexes |
| platform | macOS-15.7.4-arm64-arm-64bit |
| machine | arm64 |
| processor | arm |
| logical_cpu_count | 8 |
| peak_process_rss_bytes_approximate | 609435648 |
| external_services | none |
| llm_or_api_cost | 0 |

## 13. Error analysis

There were 66 exact-label errors. Primary error-category aggregates are:

| failure_type | tier | hop_count | error_category | count |
| --- | --- | --- | --- | --- |
| F06_INVOICE_PAID_TWICE | 3 | 2 | COLLISION_OR_PRECEDENCE | 2 |
| F12_ERP_PAYMENT_MISSING_FROM_BANK | 2 | 1 | COLLISION_OR_PRECEDENCE | 2 |
| NO_FAILURE |  |  | FALSE_POSITIVE | 12 |
| NO_FAILURE |  |  | MISSING_EVIDENCE | 50 |

The case-level taxonomy, secondary causes, expected-rule trace status, and deterministic selected reason are saved in `error_analysis.csv`.

## 14. Known deterministic-baseline limitations

The implementation retains the specification's frozen limitations: reference-based duplicates; no receipt, amendment, alias, hierarchy, FX-rate, historical approval-policy, or holiday tables; exact chart-of-account assumptions; payment-level bank references; unique two-cycle-only F15 matching; and single-label precedence. These are descriptive limitations, not post-test rule changes.

## 15. Protocol deviations

NO PROTOCOL DEVIATIONS

One non-blocking implementation issue was recorded: F02's required-field bullet omits `invoice_total` while its explicit detection rule requires excluding nonpositive invoices. The implementation reads `invoice_total` solely for that frozen exclusion and does not alter F02 semantics.

DEFECT-001 was identified after the preserved run `phase2_rules_sql_v1_0_20260808T183500Z`: non-FX audit-event timestamps were parsed before type rejection and infrastructure index reads were underreported by the access logger. The corrected implementation now type-filters before timestamp parsing and logs all index columns. No frozen rule changed; this run uses a new ID and the original run remains preserved.

## 16. Reproducibility instructions

From the repository root with Python 3.11+ and requirements installed, run:

```bash
python3 -m src.rules_sql.cli run --data-root data/benchmark --output-root results/rules_sql --run-id <new_unique_run_id>
```

Use a new run ID because run directories and raw predictions are immutable. Materially identical predictions and aggregate metrics are expected for the same dataset snapshot and environment; latency can vary.

## 17. Final conclusion

All 15 frozen rules were executable against the released schema. The measured results above characterize only this deterministic Rules/SQL baseline. No claim about any unevaluated method is made.
