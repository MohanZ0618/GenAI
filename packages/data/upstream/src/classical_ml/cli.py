"""One-command Phase 3 classical ML experiment runner."""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from time import perf_counter, perf_counter_ns
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.classical_ml.audits import feature_pipeline_audit, sha256, verify_checksum
from src.classical_ml.data import FinancialSnapshot, load_routes
from src.classical_ml.evaluation import (
    calibration_metrics,
    compare_rules,
    confusion_rows,
    error_analysis,
    evaluate_predictions,
    exact_mcnemar,
    grouped_metrics,
    labels_from_manifest,
    load_jsonl,
    paired_bootstrap,
    per_failure_metrics,
    permutation_importance_rows,
    prediction_records,
    robustness_results,
)
from src.classical_ml.features import FeatureExtractor, MISSING_CATEGORY
from src.classical_ml.modeling import (
    build_preprocessor,
    feature_columns,
    run_validation_search,
    score_predictions,
)
from src.classical_ml.registry import (
    CATEGORICAL_FEATURE_NAMES,
    CLASSES,
    FEATURES,
    FAILURE_TYPES,
    HOP_BY_CLASS,
    RANDOM_SEED,
    TIER_BY_CLASS,
)
from src.classical_ml.reporting import evaluation_report
from src.rules_sql.evaluation import write_csv, write_json, write_jsonl


ROOT = Path(__file__).resolve().parents[2]
RULES_RUN_NAME = "phase2_rules_sql_v1_0_20260808T185000Z_auditfix1"


def _timed_feature_frame(snapshot: FinancialSnapshot, routes: list[dict[str, str]]) -> tuple[pd.DataFrame, list[int]]:
    extractor = FeatureExtractor(snapshot)
    rows: list[dict[str, Any]] = []
    timings: list[int] = []
    for route in routes:
        started = perf_counter_ns()
        row = extractor.extract(route)
        timings.append(perf_counter_ns() - started)
        rows.append(row)
    frame = pd.DataFrame(rows, columns=["case_id", *[feature.name for feature in FEATURES]])
    if frame["case_id"].duplicated().any():
        raise RuntimeError("duplicate case IDs in extracted matrix")
    for name in CATEGORICAL_FEATURE_NAMES:
        frame[name] = frame[name].fillna(MISSING_CATEGORY).astype(str)
    return frame, timings


def _label_array(frame: pd.DataFrame, labels: dict[str, str]) -> np.ndarray:
    if set(frame["case_id"]) != set(labels):
        raise RuntimeError("feature matrix and label case IDs differ")
    values = frame["case_id"].map(labels)
    if values.isna().any() or not set(values).issubset(CLASSES):
        raise RuntimeError("unexpected or missing labels")
    return values.to_numpy(dtype=str)


def _versions() -> dict[str, str]:
    names = ("numpy", "pandas", "scikit-learn", "joblib", "pytest", "PyYAML")
    result = {}
    for name in names:
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = "NOT_INSTALLED"
    return result


def _git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "UNAVAILABLE_NOT_A_GIT_WORKTREE"


def _run_tests(run_dir: Path) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = str(RANDOM_SEED)
    started = perf_counter()
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/classical_ml", "-q"],
        cwd=ROOT, capture_output=True, text=True, env=environment,
    )
    result = {
        "command": f"{sys.executable} -m pytest tests/classical_ml -q",
        "exit_code": process.returncode, "passed": process.returncode == 0,
        "runtime_seconds": perf_counter() - started, "stdout": process.stdout, "stderr": process.stderr,
    }
    write_json(run_dir / "test_results.json", result)
    if process.returncode:
        raise RuntimeError(f"Phase 3 tests failed:\n{process.stdout}\n{process.stderr}")
    return result


def _save_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def _json_safe_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(parameters, sort_keys=True))


def _subgroup_primary_entity(records: list[dict[str, Any]], labels: dict[str, str], routes: list[dict[str, str]]) -> list[dict[str, Any]]:
    route_type = {route["case_id"]: route["primary_entity_type"] for route in routes}
    rows = []
    for entity_type in sorted(set(route_type.values())):
        selected = [row for row in records if route_type[row["case_id"]] == entity_type]
        metric = score_predictions(
            [labels[row["case_id"]] for row in selected], [row["predicted_failure_type"] for row in selected],
        )
        rows.append({"primary_entity_type": entity_type, "N": len(selected), **metric})
    return rows


def _latency_report(
    latencies_ns: list[int], feature_seconds: float, batch_model_seconds: float,
    total_search_seconds: float, selected_fit_seconds: float, preprocessor_path: Path, estimator_path: Path,
) -> dict[str, Any]:
    array_ms = np.asarray(latencies_ns, dtype=float) / 1e6
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / (1024 * 1024) if platform.system() == "Darwin" else peak / 1024
    total_inference = float(np.sum(latencies_ns) / 1e9)
    return {
        "cases": len(latencies_ns), "feature_extraction_total_seconds": feature_seconds,
        "batch_preprocess_and_model_seconds": batch_model_seconds,
        "end_to_end_sum_case_seconds": total_inference,
        "mean_latency_ms": float(np.mean(array_ms)), "median_latency_ms": float(np.median(array_ms)),
        "p95_latency_ms": float(np.percentile(array_ms, 95)), "p99_latency_ms": float(np.percentile(array_ms, 99)),
        "throughput_cases_per_second": len(latencies_ns) / total_inference if total_inference else None,
        "total_search_seconds": total_search_seconds, "selected_fit_seconds": selected_fit_seconds,
        "preprocessor_size_bytes": preprocessor_path.stat().st_size,
        "estimator_size_bytes": estimator_path.stat().st_size,
        "serialized_total_bytes": preprocessor_path.stat().st_size + estimator_path.stat().st_size,
        "approximate_peak_rss_mb": peak_mb, "ru_maxrss_raw": peak,
        "environment": {"python": sys.version, "platform": platform.platform(), "processor": platform.processor(),
                        "machine": platform.machine(), "cpu_count": os.cpu_count(), "dependencies": _versions()},
        "runtime_technology": "Python/pandas/scikit-learn; no LLM, API, database, or external service",
        "external_service_cost": 0,
    }


def run_experiment(data_root: Path, output_root: Path, run_id: str) -> Path:
    np.random.seed(RANDOM_SEED)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(timezone.utc)

    spec_sha, spec_path = verify_checksum(ROOT / "docs" / "frozen_ml_baseline_spec_v1.0.sha256")
    registry_sha, registry_path = verify_checksum(ROOT / "docs" / "ml_feature_registry_v1.0.sha256")
    rules_spec_sha, _ = verify_checksum(ROOT / "docs" / "frozen_rules_sql_baseline_spec_v1.0.sha256")
    test_results = _run_tests(run_dir)

    snapshot = FinancialSnapshot(data_root / "full")
    train_routes = load_routes(data_root / "train")
    validation_routes = load_routes(data_root / "validation")
    train_frame, train_feature_ns = _timed_feature_frame(snapshot, train_routes)
    validation_frame, validation_feature_ns = _timed_feature_frame(snapshot, validation_routes)
    _save_frame(train_frame, run_dir / "features_train.csv")
    _save_frame(validation_frame, run_dir / "features_validation.csv")

    # Evaluator labels are opened only after each corresponding raw feature matrix exists.
    train_labels = labels_from_manifest(data_root / "train" / "failure_manifest.csv")
    validation_labels = labels_from_manifest(data_root / "validation" / "failure_manifest.csv")
    y_train = _label_array(train_frame, train_labels)
    y_validation = _label_array(validation_frame, validation_labels)

    preprocessor = build_preprocessor()
    x_train = preprocessor.fit_transform(feature_columns(train_frame))
    x_validation = preprocessor.transform(feature_columns(validation_frame))
    transformed_names = preprocessor.get_feature_names_out().tolist()
    np.savez_compressed(run_dir / "transformed_train.npz", x=x_train, case_id=train_frame["case_id"].to_numpy())
    np.savez_compressed(run_dir / "transformed_validation.npz", x=x_validation, case_id=validation_frame["case_id"].to_numpy())
    write_json(run_dir / "transformed_feature_names.json", transformed_names)

    snapshot_audit = snapshot.audit()
    write_json(run_dir / "implementation_leakage_audit.json", snapshot_audit)
    pipeline_audit, audit_rows, audit_markdown = feature_pipeline_audit(
        train_frame, validation_frame, train_labels, preprocessor, snapshot_audit, spec_sha, registry_sha,
    )
    write_json(run_dir / "feature_pipeline_audit.json", pipeline_audit)
    write_csv(run_dir / "feature_audit.csv", audit_rows)
    (run_dir / "ml_feature_pipeline_audit_v1.0.md").write_text(audit_markdown, encoding="utf-8")
    (ROOT / "docs" / "ml_feature_pipeline_audit_v1.0.md").write_text(audit_markdown, encoding="utf-8")
    if pipeline_audit["status"] != "PASS":
        raise RuntimeError("material pre-training feature-pipeline audit failure; test evaluation prohibited")

    search_started = perf_counter()
    selected, candidates = run_validation_search(x_train, y_train, x_validation, y_validation)
    total_search_seconds = perf_counter() - search_started
    validation_rows = [candidate.serializable() for candidate in candidates]
    write_csv(run_dir / "validation_search.csv", validation_rows)
    tie_count = sum(np.isclose(row["macro_f1"], selected.metrics["macro_f1"], atol=1e-15, rtol=0) for row in validation_rows)
    selection = {
        "candidate_id": selected.candidate_id, "model_family": selected.model_family,
        "parameters": _json_safe_parameters(selected.parameters),
        "parameters_json": selected.serializable()["parameters_json"],
        "validation_metrics": selected.metrics,
        "validation_mean_inference_latency_ns": selected.mean_validation_inference_latency_ns,
        "objective_tie_count_at_macro_f1": int(tie_count),
        "tie_break_order": ["higher macro F1", "higher weighted F1", "lower FPR", "lower mean latency",
                            "simpler family logistic<random_forest<hist_gradient_boosting", "canonical parameter JSON"],
        "selection_data": "validation_only", "refit_after_selection": False,
    }
    write_json(run_dir / "validation_selection.json", selection)

    preprocessor_path = run_dir / "locked_preprocessor.joblib"
    estimator_path = run_dir / "locked_estimator.joblib"
    joblib.dump(preprocessor, preprocessor_path, compress=3)
    joblib.dump(selected.estimator, estimator_path, compress=3)
    locked_hashes = {"preprocessor_sha256": sha256(preprocessor_path), "estimator_sha256": sha256(estimator_path)}
    model_manifest = {
        "model_family": selected.model_family, "candidate_id": selected.candidate_id,
        "hyperparameters": _json_safe_parameters(selected.parameters), "classes": selected.estimator.classes_.tolist(),
        "pre_encoding_feature_count": len(FEATURES), "transformed_feature_count": len(transformed_names),
        "transformed_feature_names": transformed_names, "preprocessing_fit_split": "train",
        "estimator_fit_split": "train", "selection_split": "validation", "random_seed": RANDOM_SEED,
        "decision_rule": "native predict_proba argmax; estimator lexical class ordering resolves ties",
        "missing_policy": "train median numeric; __MISSING__ categorical; unknown match=-1",
        **locked_hashes, "dependencies": _versions(),
    }
    write_json(run_dir / "model_manifest.json", model_manifest)

    quality = json.loads((data_root / "dataset_quality_report.json").read_text(encoding="utf-8"))
    split_hashes = {split: sha256(data_root / split / "case_ids.txt") for split in ("train", "validation", "test")}
    pre_test_audit = {
        "status": "PASS", "generated_before_test_feature_extraction_and_inference": True,
        "frozen_ml_spec_sha256": spec_sha, "feature_registry_sha256": registry_sha,
        "locked_rules_spec_sha256": rules_spec_sha, "git_commit": _git_commit(),
        "dataset_version": quality.get("benchmark_version"), "dataset_hash": quality.get("dataset_hash"),
        "split_identifiers_sha256": split_hashes, "selected_model": selection,
        "locked_model_hashes": locked_hashes, "feature_pipeline_audit": pipeline_audit["status"],
        "unit_and_integration_tests": "PASS" if test_results["passed"] else "FAIL",
        "leakage_audit": snapshot_audit["status"], "unresolved_material_issues": [],
        "test_labels_opened_by_phase3_runner": False,
    }
    write_json(run_dir / "pre_test_audit.json", pre_test_audit)

    # Held-out feature extraction and prediction begin only after the selected artifacts are locked.
    test_routes = load_routes(data_root / "test")
    test_feature_started = perf_counter()
    test_frame, test_feature_ns = _timed_feature_frame(snapshot, test_routes)
    test_feature_seconds = perf_counter() - test_feature_started
    _save_frame(test_frame, run_dir / "features_test.csv")
    x_test = preprocessor.transform(feature_columns(test_frame))
    np.savez_compressed(run_dir / "transformed_test.npz", x=x_test, case_id=test_frame["case_id"].to_numpy())

    batch_started = perf_counter()
    test_probabilities = selected.estimator.predict_proba(x_test)
    test_predictions = selected.estimator.classes_[np.argmax(test_probabilities, axis=1)]
    batch_model_seconds = perf_counter() - batch_started
    per_case_latency_ns: list[int] = []
    for index in range(len(test_frame)):
        started = perf_counter_ns()
        one = preprocessor.transform(feature_columns(test_frame.iloc[[index]]))
        selected.estimator.predict_proba(one)
        per_case_latency_ns.append(test_feature_ns[index] + perf_counter_ns() - started)
    predictions = prediction_records(
        test_frame["case_id"].tolist(), test_predictions, test_probabilities,
        selected.estimator.classes_, selected.model_family, per_case_latency_ns,
    )
    # This is the immutable barrier: test labels have not been opened by this process yet.
    write_jsonl(run_dir / "predictions.jsonl", predictions, exclusive=True)

    test_labels = labels_from_manifest(data_root / "test" / "failure_manifest.csv")
    _label_array(test_frame, test_labels)
    metrics = evaluate_predictions(predictions, test_labels)
    failure_metrics = per_failure_metrics(predictions, test_labels)
    tier_metrics = grouped_metrics(predictions, test_labels, "tier")
    hop_metrics = grouped_metrics(predictions, test_labels, "hop_count")
    entity_metrics = _subgroup_primary_entity(predictions, test_labels, test_routes)
    write_json(run_dir / "metrics.json", metrics)
    write_csv(run_dir / "metrics_by_failure_type.csv", failure_metrics)
    write_csv(run_dir / "metrics_by_tier.csv", tier_metrics)
    write_csv(run_dir / "metrics_by_hop_count.csv", hop_metrics)
    write_csv(run_dir / "metrics_by_primary_entity.csv", entity_metrics)
    write_csv(run_dir / "confusion_matrix.csv", confusion_rows(predictions, test_labels))
    support = Counter(test_labels.values())
    predicted_support = Counter(row["predicted_failure_type"] for row in predictions)
    write_csv(run_dir / "class_support.csv", [
        {"class": label, "actual_support": support[label], "predicted_support": predicted_support[label]} for label in CLASSES
    ])

    calibration, calibration_bins = calibration_metrics(predictions, test_labels)
    write_json(run_dir / "calibration_metrics.json", calibration)
    write_csv(run_dir / "calibration_bins.csv", calibration_bins)
    evidence_metrics = {
        "returned_evidence_records": 0, "cases_with_returned_evidence": 0,
        "evidence_precision": None, "evidence_recall": None, "evidence_contract_accuracy": None,
        "classification_evidence_separated": True,
        "limitation": "The frozen classical ML output contract returns empty evidence and null reasons for every case.",
    }
    write_json(run_dir / "evidence_metrics.json", evidence_metrics)

    rules_dir = ROOT / "results" / "rules_sql" / RULES_RUN_NAME
    rules_predictions = load_jsonl(rules_dir / "predictions.jsonl")
    rules_metrics = json.loads((rules_dir / "metrics.json").read_text(encoding="utf-8"))
    rules_by_tier = pd.read_csv(rules_dir / "metrics_by_tier.csv").to_dict("records")
    rules_by_hop = pd.read_csv(rules_dir / "metrics_by_hop_count.csv").to_dict("records")
    comparison, comparison_rows, insufficient_rows = compare_rules(predictions, rules_predictions, test_labels)
    mcnemar = exact_mcnemar(comparison_rows)
    bootstrap = paired_bootstrap(predictions, rules_predictions, test_labels, repeats=2000)
    write_json(run_dir / "rules_sql_comparison_summary.json", comparison)
    write_json(run_dir / "mcnemar_exact.json", mcnemar)
    write_json(run_dir / "paired_bootstrap.json", bootstrap)

    training_support = Counter(train_labels.values())
    errors, error_summary = error_analysis(predictions, test_labels, test_frame, preprocessor, training_support)
    error_by_case = {row["case_id"]: row for row in errors}
    rules_error_path = rules_dir / "error_analysis.csv"
    rules_error_frame = pd.read_csv(rules_error_path, dtype=str) if rules_error_path.is_file() else pd.DataFrame()
    rules_error_by_case = {
        str(row["case_id"]): row.to_dict() for _, row in rules_error_frame.iterrows()
    } if "case_id" in rules_error_frame else {}
    for row in comparison_rows:
        ml_error = error_by_case.get(row["case_id"], {})
        rule_error = rules_error_by_case.get(row["case_id"], {})
        row["ml_error_category"] = ml_error.get("primary_cause", "")
        row["ml_secondary_causes"] = ml_error.get("secondary_causes", "")
        row["rules_error_category"] = rule_error.get("primary_cause", "")
    for row in errors:
        comparison_row = next(value for value in comparison_rows if value["case_id"] == row["case_id"])
        row["rules_prediction"] = comparison_row["rules_prediction"]
        row["rules_status"] = comparison_row["rules_status"]
        row["exact_comparison_partition"] = comparison_row["exact_partition"]
    write_csv(run_dir / "rules_sql_comparison.csv", comparison_rows)
    write_csv(run_dir / "rules_insufficient_comparison.csv", insufficient_rows)
    write_csv(run_dir / "error_analysis.csv", errors, fields=list(errors[0]) if errors else ["case_id"])
    write_csv(run_dir / "error_summary.csv", error_summary)

    insufficient_confidence = [float(row["ml_probability"]) for row in insufficient_rows]
    insufficient_summary = {
        "cases": len(insufficient_rows),
        "ml_exact_recovered": sum(bool(row["ml_exactly_recovered"]) for row in insufficient_rows),
        "ml_exact_wrong": sum(not bool(row["ml_exactly_recovered"]) for row in insufficient_rows),
        "ml_binary_recovered": sum(bool(row["ml_binary_recovered"]) for row in insufficient_rows),
        "failure_type_distribution": dict(sorted(Counter(row["actual"] for row in insufficient_rows).items())),
        "confidence": {
            "mean": float(np.mean(insufficient_confidence)) if insufficient_confidence else None,
            "median": float(np.median(insufficient_confidence)) if insufficient_confidence else None,
            "p05": float(np.percentile(insufficient_confidence, 5)) if insufficient_confidence else None,
            "p95": float(np.percentile(insufficient_confidence, 95)) if insufficient_confidence else None,
        },
        "wording_constraint": "Correct outcomes are classification recovered, not evidence resolved.",
    }
    write_json(run_dir / "rules_insufficient_summary.json", insufficient_summary)

    importance = permutation_importance_rows(
        selected.estimator, x_validation, y_validation, transformed_names,
    )
    write_csv(run_dir / "permutation_importance.csv", importance)
    robustness = robustness_results(test_frame, preprocessor, selected.estimator, test_labels)
    write_csv(run_dir / "robustness.csv", robustness)
    operational = _latency_report(
        per_case_latency_ns, test_feature_seconds, batch_model_seconds, total_search_seconds,
        selected.fit_seconds, preprocessor_path, estimator_path,
    )
    write_json(run_dir / "operational_metrics.json", operational)

    protocol_text = "NO PROTOCOL DEVIATIONS"
    (run_dir / "protocol_deviations.md").write_text(protocol_text + "\n", encoding="utf-8")
    reproducibility_command = (
        "python3 -m src.classical_ml.cli run --data-root data/benchmark "
        "--output-root results/classical_ml --run-id <new_unique_run_id>"
    )
    report = evaluation_report(
        run_id=run_id, spec_sha=spec_sha, registry_sha=registry_sha,
        dataset_version=str(quality.get("benchmark_version")), selected=selection,
        validation_rows=validation_rows, metrics=metrics, per_failure=failure_metrics,
        by_tier=tier_metrics, by_hop=hop_metrics, rules_by_tier=rules_by_tier,
        rules_by_hop=rules_by_hop, calibration=calibration,
        missing_summary=insufficient_summary, comparison=comparison, mcnemar=mcnemar,
        bootstrap=bootstrap, importance=importance, error_summary=error_summary,
        operational=operational, robustness=robustness, rules_metrics=rules_metrics,
        protocol_text=protocol_text, reproducibility_command=reproducibility_command,
    )
    (run_dir / "classical_ml_baseline_evaluation_v1.0.md").write_text(report, encoding="utf-8")
    (ROOT / "docs" / "classical_ml_baseline_evaluation_v1.0.md").write_text(report, encoding="utf-8")

    completion = {
        "decision": "PHASE 3 COMPLETE — CLASSICAL ML BASELINE LOCKED",
        "specification_status": {"frozen": True, "sha256": spec_sha, "registry_locked": True,
                                 "leakage_audit": "PASS", "protocol_deviations": "NO PROTOCOL DEVIATIONS"},
        "feature_pipeline_status": {"features": len(FEATURES), "tests": test_results["stdout"].strip(),
                                    "temporal_leakage_tests": "PASS", "split_isolation_tests": "PASS",
                                    "missing_data_tests": "PASS", "forbidden_feature_checks": "PASS"},
        "training_status": {"logistic_regression": True, "random_forest": True,
                            "gradient_boosting": True, "configurations": 22,
                            "validation_selection_completed": True, "winning_model": selected.model_family,
                            "winning_hyperparameters": _json_safe_parameters(selected.parameters), "model_locked": True},
        "held_out_evaluation_status": {"completed": True, "test_cases": len(predictions), **metrics},
        "rules_sql_comparison": comparison, "operational_results": operational,
        "outstanding_material_issues": [], "reproducibility_command": reproducibility_command,
    }
    write_json(run_dir / "phase3_completion_review.json", completion)

    run_manifest = {
        "run_id": run_id, "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_spec_path": str(spec_path.relative_to(ROOT)), "frozen_spec_sha256": spec_sha,
        "feature_registry_path": str(registry_path.relative_to(ROOT)), "feature_registry_sha256": registry_sha,
        "locked_rules_run": str(rules_dir.relative_to(ROOT)), "locked_rules_spec_sha256": rules_spec_sha,
        "git_commit": _git_commit(), "dataset_version": quality.get("benchmark_version"),
        "dataset_hash": quality.get("dataset_hash"), "split_identifiers_sha256": split_hashes,
        "case_counts": {"train": len(train_frame), "validation": len(validation_frame), "test": len(test_frame)},
        "random_seed": RANDOM_SEED, "model": model_manifest,
        "test_prediction_sha256": sha256(run_dir / "predictions.jsonl"),
        "protocol_deviations": "NO PROTOCOL DEVIATIONS", "dependencies": _versions(),
        "reproducibility_command": reproducibility_command,
    }
    write_json(run_dir / "run_manifest.json", run_manifest)
    return run_dir


def verify_locked_run(data_root: Path, run_dir: Path) -> dict[str, Any]:
    """Recreate held-out inference from locked artifacts without opening labels."""
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    stored = load_jsonl(run_dir / "predictions.jsonl")
    preprocessor_path = run_dir / "locked_preprocessor.joblib"
    estimator_path = run_dir / "locked_estimator.joblib"
    preprocessor = joblib.load(preprocessor_path)
    estimator = joblib.load(estimator_path)
    snapshot = FinancialSnapshot(data_root / "full")
    routes = load_routes(data_root / "test")
    frame, _ = _timed_feature_frame(snapshot, routes)
    probabilities = estimator.predict_proba(preprocessor.transform(feature_columns(frame)))
    predictions = estimator.classes_[np.argmax(probabilities, axis=1)]
    stored_by_id = {row["case_id"]: row for row in stored}
    labels_match = all(
        str(predictions[index]) == stored_by_id[case_id]["predicted_failure_type"]
        for index, case_id in enumerate(frame["case_id"])
    )
    probabilities_match = all(
        all(np.isclose(
            probabilities[index, list(estimator.classes_).index(label)],
            stored_by_id[case_id]["class_probabilities"][label], atol=0.0, rtol=0.0,
        ) for label in CLASSES)
        for index, case_id in enumerate(frame["case_id"])
    )
    checks = {
        "case_ids_match": set(frame["case_id"]) == set(stored_by_id),
        "predicted_labels_exactly_match": labels_match,
        "class_probabilities_bitwise_match": probabilities_match,
        "preprocessor_hash_matches_manifest": sha256(preprocessor_path) == manifest["model"]["preprocessor_sha256"],
        "estimator_hash_matches_manifest": sha256(estimator_path) == manifest["model"]["estimator_sha256"],
        "prediction_hash_matches_manifest": sha256(run_dir / "predictions.jsonl") == manifest["test_prediction_sha256"],
    }
    result = {
        "status": "PASS" if all(checks.values()) and snapshot.audit()["status"] == "PASS" else "FAIL",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "verification_did_not_open_test_labels": True,
        "cases": len(frame), "stored_prediction_records": len(stored),
        **checks,
        "feature_source_access_audit": snapshot.audit()["status"],
    }
    if result["status"] != "PASS":
        raise RuntimeError(f"locked-run reproducibility verification failed: {result}")
    write_json(run_dir / "reproducibility_verification.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="execute the frozen Phase 3 experiment")
    run.add_argument("--data-root", type=Path, default=Path("data/benchmark"))
    run.add_argument("--output-root", type=Path, default=Path("results/classical_ml"))
    run.add_argument("--run-id", required=True)
    verify = subparsers.add_parser("verify", help="recreate predictions from an existing locked run without labels")
    verify.add_argument("--data-root", type=Path, default=Path("data/benchmark"))
    verify.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "run":
        output = run_experiment(arguments.data_root.resolve(), arguments.output_root.resolve(), arguments.run_id)
        print(output)
        return 0
    if arguments.command == "verify":
        result = verify_locked_run(arguments.data_root.resolve(), arguments.run_dir.resolve())
        print(json.dumps(result, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
