# Classical Machine-Learning Baseline Evaluation — Version 1.0

## 1. Executive Summary

The locked classical ML baseline evaluated all 439 held-out cases. It achieved exact 16-class accuracy 0.9544, macro F1 0.9624, and binary anomaly F1 0.9663. The selected model was **hist_gradient_boosting**, chosen exclusively on validation macro F1 from the frozen 22-configuration search. The ML method emits no source-record evidence; correct classifications therefore remain classification results, not evidence-grounded reconciliations.

## 2. Frozen ML Specification Provenance

- Specification: `docs/frozen_ml_baseline_spec_v1.0.md`
- Specification SHA-256: `0d220564335a85e6fe3a193e212d68aec2abbf7744a23f267ba4390b428d6897`
- Feature registry SHA-256: `b515b9f81e8284281dc7bddfcc2b32e9655d09fce71d8aed998b8687f7840d3d`
- Run ID: `phase3_classical_ml_v1_0_20260808T213000Z_auditfix1`
- Frozen before candidate training and held-out inference: yes

## 3. Dataset and Splits

Dataset version: `1.0.0`. Train, validation, and test contain 1,192, 416, and 439 cases. Case-ID and benchmark vendor-group overlap audits passed. The locked test set is identical to the Phase 2 Rules/SQL comparator set.

## 4. Feature Engineering

The pipeline has 147 pre-encoding case-level features: 27 categorical, 54 raw/aggregate numeric, 20 difference, 26 match, 15 missingness, and 5 relational features. It uses only deterministic NFKC/reference normalization, Decimal arithmetic, strict ISO dates, direct-link scope expansion, and registered as-of filters. Raw identifiers are used transiently for linkage but never enter the model matrix.

## 5. Leakage Controls

The implementation separates inference feature loading from evaluator labels. Numeric imputation/scaling and categorical one-hot vocabularies fit on train only. Validation/test are transform-only; raw test predictions were written before test labels were opened. Forbidden target, mutation, clean-data, expected-answer, Rules/SQL, and post-discovery fields were excluded. The implementation-level and feature-pipeline audits passed.

## 6. Models Evaluated

All three required classical families were trained: 6 logistic-regression configurations, 8 random forests, and 8 histogram gradient-boosted classifiers. All used seed 314159 and the common frozen transformed matrices.

## 7. Hyperparameter Search

Selection used the frozen lexicographic procedure: validation macro F1, weighted F1, lower FPR, lower latency, simpler family, and canonical parameter JSON. The grid was not expanded.

| Candidate | Family | Macro F1 | Weighted F1 | FPR | Selected |
|---|---|---|---|---|---|
| hist_gradient_boosting_06 | hist_gradient_boosting | 0.9727 | 0.9688 | 0.0576 | True |
| hist_gradient_boosting_08 | hist_gradient_boosting | 0.9715 | 0.9669 | 0.0719 | False |
| hist_gradient_boosting_07 | hist_gradient_boosting | 0.9702 | 0.9662 | 0.0576 | False |
| hist_gradient_boosting_05 | hist_gradient_boosting | 0.9694 | 0.9657 | 0.0504 | False |
| hist_gradient_boosting_02 | hist_gradient_boosting | 0.9692 | 0.9642 | 0.0719 | False |

## 8. Validation Results

All 22 configurations and every validation metric are in `validation_search.csv`. The selected validation macro F1 was 0.9727; selected validation weighted F1 was 0.9688.

## 9. Selected Model

- Family: `hist_gradient_boosting`
- Candidate: `hist_gradient_boosting_06`
- Hyperparameters: `{"class_weight":"balanced","early_stopping":false,"l2_regularization":1.0,"learning_rate":0.1,"max_iter":200,"max_leaf_nodes":15,"random_state":314159}`
- Estimator remained fit on train only; no train+validation refit occurred.
- Preprocessor and estimator were serialized and SHA-256 locked before test feature extraction/inference.

## 10. Held-Out Test Results

| Metric | Classical ML | Locked Rules/SQL |
|---|---|---|
| Exact 16-class accuracy | 0.9544 | 0.8497 |
| Binary anomaly accuracy | 0.9544 | 0.8588 |
| Binary precision | 0.9599 | 0.9609 |
| Binary recall | 0.9729 | 1.0000 |
| Binary F1 | 0.9663 | 0.9801 |
| Macro F1 | 0.9624 | 0.9518 |
| Micro F1 | 0.9544 | 0.9010 |
| Weighted F1 | 0.9546 | 0.8887 |
| FPR | 0.0833 | 0.0833 |
| FNR | 0.0271 | 0.0000 |

The confusion matrix and support counts are saved as machine-readable CSV artifacts. Results are reported without selecting a post-test preferred metric.

The 10.48-point exact-accuracy increase was concentrated in normal/abstention handling: ML correctly classified 132 of 144 normal cases versus 82 for Rules/SQL, while Rules/SQL correctly classified 291 of 295 anomaly cases versus 287 for ML. Accordingly, ML binary F1 was lower (0.9663 versus 0.9801), and 45 of the 50 deterministic abstentions were classification-recovered without evidence.

## 11. Per-Failure Results

| Failure | N | Precision | Recall | F1 | FP | FN |
|---|---|---|---|---|---|---|
| F01_DUPLICATE_INVOICE | 21 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |
| F02_PO_INVOICE_AMOUNT_MISMATCH | 20 | 0.9000 | 0.9000 | 0.9000 | 2 | 2 |
| F03_QUANTITY_MISMATCH | 18 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |
| F04_INCORRECT_VENDOR_ASSOCIATION | 17 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |
| F05_PAYMENT_WITHOUT_VALID_INVOICE | 22 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |
| F06_INVOICE_PAID_TWICE | 12 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |
| F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE | 18 | 0.9474 | 1.0000 | 0.9730 | 1 | 0 |
| F08_APPROVAL_WORKFLOW_FAILURE | 22 | 0.9524 | 0.9091 | 0.9302 | 1 | 2 |
| F09_GL_POSTING_MISMATCH | 17 | 0.8235 | 0.8235 | 0.8235 | 3 | 3 |
| F10_WRONG_ACCOUNTING_PERIOD | 20 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |
| F11_VENDOR_MASTER_CHANGE_CONFLICT | 23 | 0.9583 | 1.0000 | 0.9787 | 1 | 0 |
| F12_ERP_PAYMENT_MISSING_FROM_BANK | 21 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |
| F13_BANK_TRANSACTION_MISSING_FROM_ERP | 28 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |
| F14_BANK_ERP_AMOUNT_MISMATCH | 16 | 0.8000 | 1.0000 | 0.8889 | 4 | 0 |
| F15_INCORRECT_PAYMENT_BANK_MATCH | 20 | 1.0000 | 0.9500 | 0.9744 | 0 | 1 |

The pre-specified weak deterministic classes F06, F07, and F11 are included above and were not used to retune the model.

## 12. Tier Results

| Tier | N | ML accuracy | Rules accuracy | ML F1 | Rules F1 | ML FPR | ML FNR |
|---|---|---|---|---|---|---|---|
| 1 | 21 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| 2 | 103 | 0.9709 | 0.9806 | 0.9709 | 0.9854 | 0.0089 | 0.0291 |
| 3 | 171 | 0.9708 | 0.9883 | 0.9595 | 0.9634 | 0.0336 | 0.0292 |

Rules/SQL was stronger on both Tier 2 and Tier 3 anomaly subsets; Tier 1 was tied. Neither method showed a monotonic decline from Tier 2 to Tier 3 in exact accuracy, so monotonic complexity degradation is not supported.

## 13. Hop-Count Results

| Hop | N | ML accuracy | Rules accuracy | ML F1 | Rules F1 |
|---|---|---|---|---|---|
| 0 | 21 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 1 | 103 | 0.9709 | 0.9806 | 0.9709 | 0.9854 |
| 2 | 129 | 0.9845 | 0.9845 | 0.9621 | 0.9588 |
| 3 | 20 | 0.9500 | 1.0000 | 0.9744 | 0.9524 |
| 4 | 22 | 0.9091 | 1.0000 | 0.9302 | 0.9565 |

## 14. Calibration Analysis

- Multiclass log loss: 0.107906
- Multiclass Brier score: 0.063192
- Top-label ECE, ten fixed bins: 0.016051

No probability calibration or test-set threshold tuning was applied. Reliability-bin data are in `calibration_bins.csv`.

## 15. Missing-Evidence Case Analysis

The same 50 Rules/SQL insufficient-evidence cases were evaluated. ML exactly classified 45 and binary-classified 45 correctly. These are **classification recovered** cases only; ML returned no source evidence. Confidence and failure-type distributions are in `rules_insufficient_summary.json` and case details in `rules_insufficient_comparison.csv`.

## 16. Rules/SQL Case-Level Comparison

Exact correctness partitions were: both correct 361, Rules-only correct 12, ML-only correct 58, and both wrong 8. Every case is retained in `rules_sql_comparison.csv`; groups containing an error include error annotations where applicable.

## 17. Statistical Comparison

Exact McNemar discordant counts were Rules-only 12 and ML-only 58; the two-sided exact p-value was 2.249e-08. The 2,000-resample paired bootstrap 95% intervals for ML-minus-Rules differences were:

| Metric | Difference | 95% percentile CI |
|---|---|---|
| exact_accuracy | 0.1048 | [0.0683, 0.1412] |
| macro_f1 | 0.0106 | [-0.0124, 0.0364] |
| binary_f1 | -0.0137 | [-0.0298, 0.0029] |

The comparison is paired and descriptive; subgroup significance was not mined post hoc.

## 18. Feature Importance / Interpretability

Validation-set permutation importance (macro-F1, 10 repeats) identified the following leading transformed features:

| Feature | Mean | Std |
|---|---|---|
| numeric__payment_ap_debit_abs_diff | 0.110878 | 0.007709 |
| numeric__payment_allocated_abs_diff | 0.086062 | 0.002922 |
| numeric__invoice_paid_rel_diff | 0.085635 | 0.007773 |
| numeric__duplicate_exact_reference_count | 0.075028 | 0.004549 |
| numeric__invoice_po_line_quantity_abs_diff | 0.074492 | 0.005028 |
| categorical__primary_entity_type_GL_JOURNAL | 0.073696 | 0.002889 |
| numeric__vendor_bank_history_present | 0.066859 | 0.006114 |
| numeric__bank_reference_match_count | 0.064318 | 0.008616 |
| numeric__invoice_po_total_rel_diff | 0.048753 | 0.003233 |
| numeric__bank_fee_adjusted_abs_diff | 0.047339 | 0.005512 |
| numeric__bank_economic_candidate_count | 0.047077 | 0.007266 |
| numeric__invoice_paid_abs_diff | 0.045011 | 0.005079 |
| numeric__invoice_po_vendor_match | 0.038374 | 0.006828 |
| numeric__payment_bank_abs_diff | 0.033654 | 0.004974 |
| categorical__settlement_status_FAILED | 0.026572 | 0.001840 |

These are model-level associations, not transaction-level accounting evidence.

## 19. Error Analysis

| Primary category | Count |
|---|---|
| AMBIGUOUS_CASE | 1 |
| CLASS_CONFUSION | 16 |
| RELATIONAL_COMPLEXITY | 3 |

Every incorrect prediction is recorded in `error_analysis.csv`, with deterministic primary/secondary categories, confidence, Tier, hop count, missingness, unseen-category flags, and Rules/SQL comparison context. Confidence bands contained 2 errors below 0.5, 11 from 0.5–0.8, and 7 at or above 0.8. Automated categories characterize observed model/data conditions; they are not causal adjudications and did not alter the model.

## 20. Operational Performance

- Total frozen search/training time: 60.557 seconds
- Test end-to-end mean latency: 70.941 ms/case
- Median / p95 / p99: 69.625 / 89.797 / 115.520 ms
- Throughput: 14.10 cases/second
- Serialized preprocessor + estimator: 726872 bytes
- Approximate peak RSS: 505.08 MB

The locked Rules/SQL report recorded 9.83 ms mean latency and 98.32 cases/second. Operational comparison must consider feature construction, traceability, and model complexity, not classification alone.

## 21. Robustness Results

| Scenario | Accuracy | Agreement | Changed |
|---|---|---|---|
| optional_tax_shipping_missing | 0.9544 | 0.9932 | 3 |
| vendor_category_unseen | 0.9567 | 0.9932 | 3 |
| optional_vendor_categories_missing | 0.9522 | 0.9886 | 5 |
| native_amount_plus_0_01 | 0.9544 | 1.0000 | 0 |

Robustness perturbations were applied only after the primary predictions were locked/scored and never fed back into selection.

## 22. Known ML Limitations

The baseline compresses relational structure into fixed aggregates, has no explicit evidence retrieval, can assign confident probabilities without causal traceability, and learns benchmark-specific statistical associations. Unseen categories map to all-zero one-hot blocks. It does not use verifiably time-safe historical aggregates because uniform row-availability timestamps are unavailable.

## 23. Protocol Deviations

NO PROTOCOL DEVIATIONS

An implementation mismatch in preserved precursor run `phase3_classical_ml_v1_0_20260808T210000Z` was corrected strictly under the frozen defect policy. The corrected authoritative run is `phase3_classical_ml_v1_0_20260808T213000Z_auditfix1`; details and both-result comparison are in `docs/ml_post_evaluation_implementation_defect_v1.0.md`.

## 24. Reproducibility Instructions

From the repository root, install `requirements.txt` and run:

```bash
python3 -m src.classical_ml.cli run --data-root data/benchmark --output-root results/classical_ml --run-id <new_unique_run_id>
```

Use a new unique run ID because experiment directories and raw predictions are immutable.

## 25. Conclusion

The frozen classical ML experiment was executed under validation-only selection and strict held-out isolation. Its results characterize where tabular statistical learning agrees with, improves on, or loses to the locked deterministic baseline while preserving the key methodological distinction between label classification and source-evidence reconciliation.

## Phase 3 Completion Review

- Frozen specification and feature registry: locked and checksum-verified
- Feature/leakage audits: PASS
- Required model families: 3 of 3 trained
- Validation selection and pre-test model locking: completed
- Held-out cases: 439 of 439
- Raw predictions and case-level Rules/SQL comparison: preserved
- Protocol deviations: NO PROTOCOL DEVIATIONS
- Outstanding material issues: none

**PHASE 3 COMPLETE — CLASSICAL ML BASELINE LOCKED**
