# Frozen Classical Machine-Learning Baseline Specification — Version 1.0

## 1. Status, scope, and research objective

This document pre-registers the classical tabular machine-learning baseline for FinRCA-Bench v1. It is frozen before final feature fitting, model training, validation selection, model locking, or held-out test inference. The locked Rules/SQL implementation and run `phase2_rules_sql_v1_0_20260808T185000Z_auditfix1` are read-only comparators and are never model inputs.

The primary experimental question is:

> Can classical statistical learning improve financial reconciliation performance relative to deterministic Rules/SQL when both operate under the same information constraints?

Secondary questions are whether learned nonlinear boundaries benefit specific failure classes; whether ML reduces false positives; whether it classifies cases Rules/SQL marks insufficient; how performance changes by frozen Tier and hop count; whether errors are shared or complementary; and how classification, calibration, evidence limitations, latency, memory, and operational complexity compare.

The goal is an objective, strong classical baseline. This is not Rules/SQL plus a classifier, an LLM, a neural network, a retrieval system, a graph embedding, a hybrid, or a label lookup.

## 2. Prediction task and evaluation unit

The primary task is mutually exclusive 16-class classification over `F01_DUPLICATE_INVOICE` through `F15_INCORRECT_PAYMENT_BANK_MATCH` plus `NO_FAILURE`. FinRCA-Bench v1 supplies one primary label per case. Binary anomaly status is derived from the multiclass argmax: `NO_FAILURE` is negative and every F01–F15 class is positive. No separate binary classifier is trained or optimized.

Inference receives only the harness-permitted `case_id`, primary entity type and ID, and the fourteen model-visible financial CSV tables. `case_id` is retained only for output correlation. It is not a model feature. The analytical cutoff is `2026-06-30`. Bank and permitted audit-event rows after the cutoff are excluded. Other delivered operational states follow the same snapshot-availability convention as the locked deterministic baseline.

The class decision is native estimator `predict_proba` argmax. Estimator class ordering provides deterministic lexical tie resolution. No post-hoc threshold is tuned. Probability calibration is not applied; native probabilities are evaluated as produced.

## 3. Allowed input information

The model may observe the following model-visible information after transformation into the locked registry:

- invoice, PO, payment, bank, vendor, approval, employee, allocation, and ledger numeric attributes;
- low-cardinality operational categories such as currencies, statuses, methods, countries, departments, and accounts;
- normalized reference equality and character-level Levenshtein similarity, without semantic embeddings;
- direct relationship counts, source-link aggregates, differences, match indicators, and explicit missingness;
- the structured `FX_CONVERSION_APPLIED` audit event type only, through the cutoff, as legitimate FX evidence;
- identifiers and bank tokens only transiently for joins, uniqueness counts, and exact equality; their raw values never enter the matrix.

No historical population aggregate is used. The released tables do not provide a uniform row-availability timestamp sufficient to prove time-safe historical eligibility across all entities. Omitting unverifiable history is the frozen, leakage-safe decision. Training-only preprocessing statistics are not historical business features.

## 4. Explicit forbidden-feature registry

The following are prohibited from the model matrix and estimator:

- ground-truth anomaly/failure labels except as training targets;
- `difficulty`, benchmark `reasoning_hops`, Tier labels, root-cause category, split, injection timestamp, adjudication, expected answers, evidence annotations, and resolution text;
- `rca_ground_truth.jsonl`, expected-answer content, `causal_edges.csv`, mutation logs, clean tables, quality reports, failure signatures, or injector code at inference;
- future/test-derived statistics or future bank/audit rows;
- Rules/SQL predictions, statuses, triggered rules, traces, evidence, reasons, metrics, or any derived proxy;
- any LLM, RAG, GraphRAG, graph embedding, learned representation, or neural output;
- `invoices.duplicate_reference`, `vendor_change_log.change_reason`, approval comments, GL memo, source-system fields, and audit fields/types other than the permitted FX event count;
- raw `case_id`, transaction IDs, vendor IDs, employee IDs, references, tax hashes, account tokens, or routing tokens as categorical/numeric values;
- target encoding, label-frequency features, class-conditioned aggregates, post-reconciliation corrections, or manually encoded label lookups.

The executable forbidden registry is `FORBIDDEN_FEATURE_REGISTRY` in `src/classical_ml/registry.py`. The inference feature loader never opens evaluator label artifacts. Split labels are opened by the trainer/evaluator only after feature matrices for that split exist.

## 5. Frozen feature registry

The normative, complete per-feature registry is `docs/ml_feature_registry_v1.0.csv`. It is a component of this specification and is checksum-locked before training. Every row contains Feature ID, name, source tables, exact definition, type, missing handling, temporal safety, and notes. The executable mirror is `src/classical_ml/registry.py`; equality between the CSV and executable registry is tested.

The registry contains 147 engineered pre-encoding features:

| Category | IDs | Count | Representation |
|---|---|---:|---|
| Low-cardinality categorical | CAT001–CAT027 | 27 | normalized string then train-fit one-hot |
| Raw/aggregate numeric | NUM001–NUM054 | 54 | deterministic float after Decimal/date arithmetic |
| Difference/lag numeric | DIF001–DIF020 | 20 | exact formula in registry; relative denominator floor 0.01 |
| Match/mismatch | MAT001–MAT026 | 26 | `1` true, `0` false, `-1` unknown |
| Missingness | MIS001–MIS015 | 15 | observed binary indicator |
| Relational scope aggregates | REL001–REL005 | 5 | deterministic counts |

### 5.1 Case scope and representative records

The primary entity determines the initial scope. Invoice and payment scope expands bidirectionally only through `payment_allocations`; a bank row reaches payments only through normalized reference; a GL journal reaches a payment only through a `PAYMENT` source link. Payment scope reaches as-of bank rows by normalized reference. No graph traversal, embedding, message passing, ground-truth edge, or case evidence package is used.

For singleton fields, the directly supplied primary record is preferred. Otherwise the lexically smallest reachable record ID is the representative. Aggregates use all distinct scoped rows. This deterministic choice is not validation-tuned.

### 5.2 Numeric and difference rules

Money parses through `Decimal`; binary floating-point conversion occurs only after each feature is calculated. Dates/timestamps use strict ISO parsing. Relative differences divide by `max(abs(reference), 0.01)`; missing operands produce missing numeric values. Calendar-day lags may be negative. Count features are zero when the corresponding complete relationship set is empty.

### 5.3 String normalization and similarity

Text uses Unicode NFKC, leading/trailing trim, internal Unicode whitespace collapse, and uppercase. References additionally remove every character outside ASCII `A-Z0-9`; empty becomes missing and leading zeros remain. Similarity is `1 - LevenshteinDistance/max(lengths)` and missing if either normalized reference is empty. No vendor-name identity match or embedding is used; vendor name contributes only normalized length and token count.

### 5.4 Missingness

Missing entities/links have explicit MIS features. Unknown match indicators are `-1`. Missing numeric values are imputed from training medians only. Missing categoricals become `__MISSING__`. The pipeline never treats annotation-package absence as operational missingness.

## 6. Temporal and split safety

- Case IDs are group-split by vendor in the benchmark generator; train, validation, and test case IDs must be disjoint.
- Preprocessing fits on training cases only and is applied unchanged to validation and test.
- Bank rows require `posted_date <= 2026-06-30`; permitted FX audit events require event date through that cutoff.
- Approval features use events at or before payment creation.
- Vendor-change-before-payment counts use `changed_at <= payment.created_at`.
- No population historical statistics, full-snapshot frequency encodings, validation/test imputations, or label-conditioned statistics are used.
- Validation labels may score candidates but never fit preprocessing or estimators. Test labels remain unopened until immutable raw test predictions are saved.

## 7. Preprocessing, categorical, and imbalance policy

One common train-fit `ColumnTransformer` is used for all families:

1. Numeric features: median imputation learned from training, then `StandardScaler` learned from training.
2. Categorical features: constant `__MISSING__` imputation, then full one-hot encoding with `handle_unknown='ignore'`, dense output, and no category dropping.
3. No ordinal coding, frequency encoding, target encoding, feature selection, PCA, resampling, or synthetic oversampling.

The training set has a larger `NO_FAILURE` class. Class weighting is part of the frozen validation search where supported: logistic regression compares none/balanced; random forest compares none/balanced-subsample; histogram gradient boosting uses balanced weights. No resampling occurs in validation or test.

## 8. Frozen model families and search spaces

Exactly three scikit-learn 1.4 classical families are evaluated with seed `314159`. The common preprocessor is fitted once on training and its transformed matrices are reused.

### 8.1 Logistic regression — 6 configurations

- Fixed: multinomial-capable `lbfgs`, L2 penalty, `max_iter=2000`, seed 314159.
- Grid: `C ∈ {0.1,1.0,10.0}` × `class_weight ∈ {None,balanced}`.

### 8.2 Random forest — 8 configurations

- Fixed: 300 trees, `max_features='sqrt'`, bootstrap true, `n_jobs=1`, seed 314159.
- Grid: `max_depth ∈ {None,16}` × `min_samples_leaf ∈ {1,3}` × `class_weight ∈ {None,balanced_subsample}`.

### 8.3 Histogram gradient-boosted trees — 8 configurations

Scikit-learn `HistGradientBoostingClassifier` is selected as the established, repository-compatible gradient-boosting implementation; no other boosting library is searched.

- Fixed: 200 boosting iterations, early stopping false, balanced class weights, seed 314159.
- Grid: `learning_rate ∈ {0.05,0.1}` × `max_leaf_nodes ∈ {15,31}` × `l2_regularization ∈ {0.0,1.0}`.

The exhaustive grid therefore has 22 candidates. It may not be expanded after validation or test observation.

## 9. Validation-only model selection and locking

Candidate estimators fit training labels only. Validation selection uses the following deterministic lexicographic order:

1. highest validation macro F1;
2. highest validation weighted F1;
3. lowest validation false-positive rate;
4. lowest mean validation inference latency;
5. simpler family: logistic regression, then random forest, then histogram gradient boosting;
6. lexicographically smallest canonical parameter JSON.

Also record micro F1, exact accuracy, binary precision/recall/F1, FPR, and latency for every candidate. The winner remains trained on the original training split; neither preprocessor nor estimator is refit on validation. Before test, serialize and hash the preprocessor and estimator, lock feature names/order, class order, parameters, weighting, missing policy, and argmax decision.

## 10. Output contract

Every case produces:

```json
{
  "case_id": "...",
  "method": "classical_ml",
  "model_family": "...",
  "predicted_failure_type": "...",
  "is_anomaly": true,
  "predicted_probability": 0.0,
  "class_probabilities": {},
  "tier": 1,
  "hop_count": 0,
  "status": "MATCH | ANOMALY",
  "evidence_record_ids": [],
  "reason": null
}
```

`tier` and `hop_count` are the frozen registry values for the predicted failure class; both are zero for `NO_FAILURE`. Evidence is always empty and reason is always null. Probabilities or feature importance are not source-record accounting evidence.

## 11. Frozen hypotheses

- **ML-H1 — Nonlinear pattern:** boosted trees may outperform linear and deterministic approaches on combined numeric, temporal, categorical, and missingness patterns.
- **ML-H2 — False positive:** learned combinations may reduce deterministic false positives on legitimate exceptions.
- **ML-H3 — Rare class:** limited-support classes may be harder unless class features separate strongly.
- **ML-H4 — Relational complexity:** fixed aggregates may remain competitive on Tier 2 but degrade where Tier 3 structure is not captured.
- **ML-H5 — Missing evidence:** ML may classify some deterministic insufficient-evidence cases from correlations; these are called “classification recovered,” not evidence-resolved.
- **ML-H6 — Evidence limitation:** classification may be strong while explicit source-evidence traceability remains absent.
- **ML-H7 — Operational:** classical inference should remain much faster than future generative methods and may be competitive with Rules/SQL.

## 12. Frozen evaluation and analysis protocol

Primary held-out metrics are exact 16-class accuracy, macro/micro/weighted F1, binary anomaly accuracy/precision/recall/F1, FPR, and FNR. Report a 16×16 confusion matrix and class support. Report one-vs-rest F01–F15 metrics and frozen Tier/hop aggregates using the locked rule registry; no new hop values are inferred.

Native probability evaluation includes multiclass log loss, multiclass Brier score `mean(sum((p-y)^2))`, and top-label expected calibration error with ten fixed equal-width confidence bins `[0,.1),…,[.9,1]`. No test calibration or threshold tuning occurs.

Rules/SQL comparison joins the preserved locked predictions by `case_id` and partitions exact and binary correctness into both correct, Rules-only correct, ML-only correct, and both wrong. The same 50 deterministic insufficient cases receive a separate classification-recovery analysis.

Paired exact correctness uses two-sided exact McNemar testing. Metric-difference uncertainty uses 2,000 paired bootstrap resamples with seed 314159 and percentile 95% intervals for exact accuracy, macro F1, and binary F1. Subgroup tests are descriptive; no unregistered post-hoc significance claims are made.

Incorrect ML predictions receive one primary category from FEATURE_INSUFFICIENCY, MISSING_INFORMATION, CLASS_CONFUSION, RARE_CLASS, DISTRIBUTION_SHIFT, UNSEEN_CATEGORY, RELATIONAL_COMPLEXITY, TEMPORAL_PATTERN_FAILURE, NORMALIZATION_FAILURE, THRESHOLD_OR_BOUNDARY, AMBIGUOUS_CASE, DATA_QUALITY, MODEL_UNDERFIT, MODEL_OVERFIT, BENCHMARK_OR_LABEL_ISSUE, or IMPLEMENTATION_DEFECT, plus optional secondary causes. Automated categories are based on missingness, training support, Tier, unseen categories, confidence, and class confusion; they do not alter the model.

Selected-model interpretability uses validation-set permutation importance with macro-F1 scoring, 10 repeats, and seed 314159. It is model analysis, not transaction evidence.

Operational metrics include total training/search time, selected fit time, serialized sizes, inference mean/median/p95/p99, throughput, environment, CPU, and approximate peak RSS. Latency includes feature extraction, preprocessing, and estimator inference per case; batch model-only latency is also retained.

## 13. Frozen robustness protocol

After primary test predictions are saved and scored, apply the locked pipeline without retraining to four separate feature-space perturbations:

1. optional tax/shipping numeric values set missing;
2. vendor category changed to unseen valid token `ZZ_UNSEEN`;
3. optional vendor categorical fields set `__MISSING__`;
4. invoice/payment/bank amount features increased by the native 0.01 perturbation where present.

Report each perturbed exact accuracy and prediction-agreement rate separately. These results never replace or tune the primary held-out result.

## 14. Leakage audit, implementation-defect policy, and reproducibility

Every registry feature must pass source availability, future-information, target-proxy, post-reconciliation, split-statistic, Rules-output, and real-time availability checks. FAIL features are removed; REVIEW features must be resolved before model locking. Tests fail on forbidden feature names/source fields, split overlap, test-label access during fitting, validation/test preprocessing refit, future event inclusion, or registry/matrix mismatch.

If held-out evaluation exposes a software defect, preserve the original run, cite this specification, create a new run ID, correct only the violation, and retain both results. Features, preprocessing, model family, hyperparameters, weighting, and decision rules may not change due to test performance.

The one-command runner must verify specification and registry hashes, run tests/audits, create train/validation feature matrices, execute all 22 validation candidates, lock/hash the winner, create a pre-test audit, save immutable test predictions before labels are opened, compute all analyses, and refuse to overwrite a run directory.

## 15. Pre-freeze review

- Prediction target and binary derivation: fixed.
- Allowed/forbidden information: fixed.
- Complete feature registry and formulas: fixed.
- Temporal, missing, categorical, and class-imbalance policies: fixed.
- Three model families and 22 configurations: fixed.
- Validation objective and tie-break: fixed.
- Probability, calibration, statistical, interpretability, robustness, and operational protocols: fixed.
- ML evidence limitation: explicit.
- Test-set labels prohibited before immutable predictions: explicit.
- Rules/SQL output prohibited as features: explicit.

**READY TO FREEZE**
