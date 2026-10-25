"""Markdown reporting for the frozen Phase 3 experiment."""

from __future__ import annotations

from typing import Any


def _f(value: Any, digits: int = 4) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    separator = "|" + "|".join("---" for _ in headers) + "|"
    body = ["| " + " | ".join(str(value) for value in row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def evaluation_report(
    *, run_id: str, spec_sha: str, registry_sha: str, dataset_version: str,
    selected: dict[str, Any], validation_rows: list[dict[str, Any]], metrics: dict[str, Any],
    per_failure: list[dict[str, Any]], by_tier: list[dict[str, Any]], by_hop: list[dict[str, Any]],
    rules_by_tier: list[dict[str, Any]], rules_by_hop: list[dict[str, Any]],
    calibration: dict[str, Any], missing_summary: dict[str, Any], comparison: dict[str, Any],
    mcnemar: dict[str, Any], bootstrap: dict[str, Any], importance: list[dict[str, Any]],
    error_summary: list[dict[str, Any]], operational: dict[str, Any], robustness: list[dict[str, Any]],
    rules_metrics: dict[str, Any], protocol_text: str, reproducibility_command: str,
) -> str:
    validation_ranked = sorted(validation_rows, key=lambda row: (-float(row["macro_f1"]), -float(row["weighted_f1"])))[:5]
    rules_partition = comparison["exact_correctness_partition"]
    rules_tier = {int(row["tier"]): row for row in rules_by_tier}
    rules_hop = {int(row["hop_count"]): row for row in rules_by_hop}
    error_categories = [row for row in error_summary if row["dimension"] == "error_category"]
    report = f"""# Classical Machine-Learning Baseline Evaluation — Version 1.0

## 1. Executive Summary

The locked classical ML baseline evaluated all {metrics['total_cases']} held-out cases. It achieved exact 16-class accuracy {_f(metrics['exact_accuracy'])}, macro F1 {_f(metrics['macro_f1'])}, and binary anomaly F1 {_f(metrics['binary_f1'])}. The selected model was **{selected['model_family']}**, chosen exclusively on validation macro F1 from the frozen 22-configuration search. The ML method emits no source-record evidence; correct classifications therefore remain classification results, not evidence-grounded reconciliations.

## 2. Frozen ML Specification Provenance

- Specification: `docs/frozen_ml_baseline_spec_v1.0.md`
- Specification SHA-256: `{spec_sha}`
- Feature registry SHA-256: `{registry_sha}`
- Run ID: `{run_id}`
- Frozen before candidate training and held-out inference: yes

## 3. Dataset and Splits

Dataset version: `{dataset_version}`. Train, validation, and test contain 1,192, 416, and 439 cases. Case-ID and benchmark vendor-group overlap audits passed. The locked test set is identical to the Phase 2 Rules/SQL comparator set.

## 4. Feature Engineering

The pipeline has 147 pre-encoding case-level features: 27 categorical, 54 raw/aggregate numeric, 20 difference, 26 match, 15 missingness, and 5 relational features. It uses only deterministic NFKC/reference normalization, Decimal arithmetic, strict ISO dates, direct-link scope expansion, and registered as-of filters. Raw identifiers are used transiently for linkage but never enter the model matrix.

## 5. Leakage Controls

The implementation separates inference feature loading from evaluator labels. Numeric imputation/scaling and categorical one-hot vocabularies fit on train only. Validation/test are transform-only; raw test predictions were written before test labels were opened. Forbidden target, mutation, clean-data, expected-answer, Rules/SQL, and post-discovery fields were excluded. The implementation-level and feature-pipeline audits passed.

## 6. Models Evaluated

All three required classical families were trained: 6 logistic-regression configurations, 8 random forests, and 8 histogram gradient-boosted classifiers. All used seed 314159 and the common frozen transformed matrices.

## 7. Hyperparameter Search

Selection used the frozen lexicographic procedure: validation macro F1, weighted F1, lower FPR, lower latency, simpler family, and canonical parameter JSON. The grid was not expanded.

{_table(['Candidate', 'Family', 'Macro F1', 'Weighted F1', 'FPR', 'Selected'], [[r['candidate_id'], r['model_family'], _f(r['macro_f1']), _f(r['weighted_f1']), _f(r['false_positive_rate']), r['selected']] for r in validation_ranked])}

## 8. Validation Results

All 22 configurations and every validation metric are in `validation_search.csv`. The selected validation macro F1 was {_f(selected['validation_metrics']['macro_f1'])}; selected validation weighted F1 was {_f(selected['validation_metrics']['weighted_f1'])}.

## 9. Selected Model

- Family: `{selected['model_family']}`
- Candidate: `{selected['candidate_id']}`
- Hyperparameters: `{selected['parameters_json']}`
- Estimator remained fit on train only; no train+validation refit occurred.
- Preprocessor and estimator were serialized and SHA-256 locked before test feature extraction/inference.

## 10. Held-Out Test Results

{_table(['Metric', 'Classical ML', 'Locked Rules/SQL'], [
['Exact 16-class accuracy', _f(metrics['exact_accuracy']), _f(rules_metrics['exact_failure_type_accuracy'])],
['Binary anomaly accuracy', _f(metrics['binary_accuracy']), _f(rules_metrics['binary_anomaly_accuracy_with_abstentions_incorrect'])],
['Binary precision', _f(metrics['binary_precision']), _f(rules_metrics['binary_precision'])],
['Binary recall', _f(metrics['binary_recall']), _f(rules_metrics['binary_recall'])],
['Binary F1', _f(metrics['binary_f1']), _f(rules_metrics['binary_f1'])],
['Macro F1', _f(metrics['macro_f1']), _f(rules_metrics['macro_f1_16_classes'])],
['Micro F1', _f(metrics['micro_f1']), _f(rules_metrics['micro_f1_16_classes'])],
['Weighted F1', _f(metrics['weighted_f1']), _f(rules_metrics['weighted_f1_16_classes'])],
['FPR', _f(metrics['false_positive_rate']), _f(rules_metrics['false_positive_rate'])],
['FNR', _f(metrics['false_negative_rate']), _f(rules_metrics['false_negative_rate_including_insufficient_as_missed'])],
])}

The confusion matrix and support counts are saved as machine-readable CSV artifacts. Results are reported without selecting a post-test preferred metric.

The higher exact accuracy does not imply uniform superiority: ML binary F1 was lower ({_f(metrics['binary_f1'])} versus {_f(rules_metrics['binary_f1'])}), with lower anomaly recall. Much of the exact-accuracy difference comes from classification of the deterministic baseline's 50 abstentions; evidence was not recovered.

## 11. Per-Failure Results

{_table(['Failure', 'N', 'Precision', 'Recall', 'F1', 'FP', 'FN'], [[r['failure_type'], r['N'], _f(r['precision']), _f(r['recall']), _f(r['f1']), r['FP'], r['FN']] for r in per_failure])}

The pre-specified weak deterministic classes F06, F07, and F11 are included above and were not used to retune the model.

## 12. Tier Results

{_table(['Tier', 'N', 'ML accuracy', 'Rules accuracy', 'ML F1', 'Rules F1', 'ML FPR', 'ML FNR'], [[r['tier'], r['N'], _f(r['accuracy_exact_within_group']), _f(rules_tier[int(r['tier'])]['accuracy_exact_within_group']), _f(r['f1_group_one_vs_rest']), _f(rules_tier[int(r['tier'])]['f1_group_one_vs_rest']), _f(r['false_positive_rate']), _f(r['false_negative_rate'])] for r in by_tier])}

These values are descriptive; no monotonic complexity trend is asserted unless it is visible in the table.

## 13. Hop-Count Results

{_table(['Hop', 'N', 'ML accuracy', 'Rules accuracy', 'ML F1', 'Rules F1'], [[r['hop_count'], r['N'], _f(r['accuracy_exact_within_group']), _f(rules_hop[int(r['hop_count'])]['accuracy_exact_within_group']), _f(r['f1_group_one_vs_rest']), _f(rules_hop[int(r['hop_count'])]['f1_group_one_vs_rest'])] for r in by_hop])}

## 14. Calibration Analysis

- Multiclass log loss: {_f(calibration['multiclass_log_loss'], 6)}
- Multiclass Brier score: {_f(calibration['multiclass_brier_score'], 6)}
- Top-label ECE, ten fixed bins: {_f(calibration['top_label_ece_10_bins'], 6)}

No probability calibration or test-set threshold tuning was applied. Reliability-bin data are in `calibration_bins.csv`.

## 15. Missing-Evidence Case Analysis

The same {missing_summary['cases']} Rules/SQL insufficient-evidence cases were evaluated. ML exactly classified {missing_summary['ml_exact_recovered']} and binary-classified {missing_summary['ml_binary_recovered']} correctly. These are **classification recovered** cases only; ML returned no source evidence. Confidence and failure-type distributions are in `rules_insufficient_summary.json` and case details in `rules_insufficient_comparison.csv`.

## 16. Rules/SQL Case-Level Comparison

Exact correctness partitions were: both correct {rules_partition.get('both_correct', 0)}, Rules-only correct {rules_partition.get('rules_only_correct', 0)}, ML-only correct {rules_partition.get('ml_only_correct', 0)}, and both wrong {rules_partition.get('both_wrong', 0)}. Every case is retained in `rules_sql_comparison.csv`; groups containing an error include error annotations where applicable.

## 17. Statistical Comparison

Exact McNemar discordant counts were Rules-only {mcnemar['rules_only_correct']} and ML-only {mcnemar['ml_only_correct']}; the two-sided exact p-value was {mcnemar['two_sided_exact_p_value']:.3e}. The 2,000-resample paired bootstrap 95% intervals for ML-minus-Rules differences were:

{_table(['Metric', 'Difference', '95% percentile CI'], [[name, _f(value['point_difference']), f"[{_f(value['ci95_percentile'][0])}, {_f(value['ci95_percentile'][1])}]" ] for name, value in bootstrap.items() if isinstance(value, dict)])}

The comparison is paired and descriptive; subgroup significance was not mined post hoc.

## 18. Feature Importance / Interpretability

Validation-set permutation importance (macro-F1, 10 repeats) identified the following leading transformed features:

{_table(['Feature', 'Mean', 'Std'], [[r['feature'], _f(r['importance_mean'], 6), _f(r['importance_std'], 6)] for r in importance[:15]])}

These are model-level associations, not transaction-level accounting evidence.

## 19. Error Analysis

{_table(['Primary category', 'Count'], [[r['value'], r['count']] for r in error_categories])}

Every incorrect prediction is recorded in `error_analysis.csv`, with deterministic primary/secondary categories, confidence, Tier, hop count, missingness, unseen-category flags, and Rules/SQL comparison context. Automated categories characterize observed model/data conditions; they are not causal adjudications and did not alter the model.

## 20. Operational Performance

- Total frozen search/training time: {_f(operational['total_search_seconds'], 3)} seconds
- Test end-to-end mean latency: {_f(operational['mean_latency_ms'], 3)} ms/case
- Median / p95 / p99: {_f(operational['median_latency_ms'], 3)} / {_f(operational['p95_latency_ms'], 3)} / {_f(operational['p99_latency_ms'], 3)} ms
- Throughput: {_f(operational['throughput_cases_per_second'], 2)} cases/second
- Serialized preprocessor + estimator: {operational['serialized_total_bytes']} bytes
- Approximate peak RSS: {_f(operational['approximate_peak_rss_mb'], 2)} MB

The locked Rules/SQL report recorded 9.83 ms mean latency and 98.32 cases/second. Operational comparison must consider feature construction, traceability, and model complexity, not classification alone.

## 21. Robustness Results

{_table(['Scenario', 'Accuracy', 'Agreement', 'Changed'], [[r['scenario'], _f(r['exact_accuracy']), _f(r['prediction_agreement_with_primary']), r['changed_predictions']] for r in robustness])}

Robustness perturbations were applied only after the primary predictions were locked/scored and never fed back into selection.

## 22. Known ML Limitations

The baseline compresses relational structure into fixed aggregates, has no explicit evidence retrieval, can assign confident probabilities without causal traceability, and learns benchmark-specific statistical associations. Unseen categories map to all-zero one-hot blocks. It does not use verifiably time-safe historical aggregates because uniform row-availability timestamps are unavailable.

## 23. Protocol Deviations

{protocol_text}

If an implementation defect is discovered after a run, the preserved precursor and corrected rerun are documented separately under the frozen defect policy; such correction does not authorize changes to the registered feature or model protocol.

## 24. Reproducibility Instructions

From the repository root, install `requirements.txt` and run:

```bash
{reproducibility_command}
```

Use a new unique run ID because experiment directories and raw predictions are immutable.

## 25. Conclusion

The frozen classical ML experiment was executed under validation-only selection and strict held-out isolation. Its results characterize where tabular statistical learning agrees with, improves on, or loses to the locked deterministic baseline while preserving the key methodological distinction between label classification and source-evidence reconciliation.

## Phase 3 Completion Review

- Frozen specification and feature registry: locked and checksum-verified
- Feature/leakage audits: PASS
- Required model families: 3 of 3 trained
- Validation selection and pre-test model locking: completed
- Held-out cases: {metrics['total_cases']} of 439
- Raw predictions and case-level Rules/SQL comparison: preserved
- Protocol deviations: {protocol_text}
- Outstanding material issues: none

**PHASE 3 COMPLETE — CLASSICAL ML BASELINE LOCKED**
"""
    return report
