"""Frozen validation selection, held-out metrics, and research artifact writers."""

from __future__ import annotations

import csv
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

from src.rules_sql.engine import F01Parameters, FrozenRulesBaseline
from src.rules_sql.registry import F01_GRID, FIXED_CONFIG, RULES, RULE_BY_FAILURE
from src.rules_sql.store import load_case_routes


TRUE_CLASSES = [rule.failure_type for rule in RULES] + ["NO_FAILURE"]


def write_json(path: Path, value: Any, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]], exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_ground_truth(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            result[str(row["case_id"])] = row
    return result


def _division(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = _division(tp, tp + fp)
    recall = _division(tp, tp + fn)
    f1 = _division(2 * precision * recall, precision + recall)
    return precision, recall, f1


def macro_f1(actual: list[str], predicted: list[str | None]) -> float:
    values: list[float] = []
    for label in TRUE_CLASSES:
        tp = sum(a == label and p == label for a, p in zip(actual, predicted))
        fp = sum(a != label and p == label for a, p in zip(actual, predicted))
        fn = sum(a == label and p != label for a, p in zip(actual, predicted))
        values.append(_prf(tp, fp, fn)[2])
    return statistics.fmean(values)


def run_inference(
    data_dir: Path,
    split_dir: Path,
    f01: F01Parameters,
) -> tuple[list[dict[str, Any]], FrozenRulesBaseline, float]:
    routes = load_case_routes(split_dir)
    engine = FrozenRulesBaseline(data_dir, f01)
    started = perf_counter()
    predictions = [
        engine.predict_case(route["case_id"], route["primary_entity_type"], route["primary_entity_id"]).serializable()
        for route in routes
    ]
    return predictions, engine, perf_counter() - started


def run_validation_search(data_dir: Path, validation_dir: Path, output_path: Path) -> tuple[F01Parameters, list[dict[str, Any]], dict[str, Any]]:
    # All predictions for a configuration are produced before evaluator-only labels are loaded.
    labels = None
    results: list[dict[str, Any]] = []
    for days, similarity_text in F01_GRID:
        parameters = F01Parameters(days, Decimal(similarity_text))
        predictions, _, runtime = run_inference(data_dir, validation_dir, parameters)
        if labels is None:
            labels = {row["case_id"]: row["failure_type"] for row in load_manifest(validation_dir / "failure_manifest.csv")}
        actual = [labels[row["case_id"]] for row in predictions]
        predicted = [row["predicted_failure_type"] for row in predictions]
        exact = sum(left == right for left, right in zip(actual, predicted))
        results.append({
            "duplicate_date_window_days": days,
            "duplicate_reference_similarity": similarity_text,
            "validation_cases": len(actual),
            "validation_macro_f1_16_classes": macro_f1(actual, predicted),
            "validation_exact_accuracy": _division(exact, len(actual)),
            "insufficient_evidence": sum(value is None for value in predicted),
            "runtime_seconds": runtime,
            "selected": False,
        })
    # Frozen tie break: objective descending, similarity descending, days ascending.
    ranked = sorted(
        results,
        key=lambda row: (
            -row["validation_macro_f1_16_classes"],
            -Decimal(row["duplicate_reference_similarity"]),
            row["duplicate_date_window_days"],
            0 if (row["duplicate_date_window_days"] == 14 and row["duplicate_reference_similarity"] == "0.90") else 1,
        ),
    )
    selected = ranked[0]
    for row in results:
        row["selected"] = row is selected
    best_score = selected["validation_macro_f1_16_classes"]
    tied_objective = [row for row in results if math.isclose(row["validation_macro_f1_16_classes"], best_score, rel_tol=0.0, abs_tol=1e-15)]
    decision = {
        "objective": "maximize macro-F1 over all 16 output classes",
        "tested_configurations": len(results),
        "objective_tie_count": len(tied_objective),
        "tie_break_order": ["higher similarity", "shorter date window", "initial value if still tied"],
        "selected_duplicate_date_window_days": selected["duplicate_date_window_days"],
        "selected_duplicate_reference_similarity": selected["duplicate_reference_similarity"],
        "selected_validation_macro_f1": best_score,
        "decision": (
            f"Selected similarity {selected['duplicate_reference_similarity']} and window "
            f"{selected['duplicate_date_window_days']} by the frozen objective/tie-break ordering."
        ),
    }
    write_csv(output_path, results)
    write_json(output_path.with_suffix(".selection.json"), decision)
    return F01Parameters(selected["duplicate_date_window_days"], Decimal(selected["duplicate_reference_similarity"])), results, decision


def classification_metrics(predictions: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any]:
    actual = [labels[row["case_id"]] for row in predictions]
    predicted = [row["predicted_failure_type"] for row in predictions]
    exact_correct = sum(left == right for left, right in zip(actual, predicted))
    actual_anomaly = [value != "NO_FAILURE" for value in actual]
    predicted_anomaly = [row["status"] == "ANOMALY" for row in predictions]
    tp = sum(left and right for left, right in zip(actual_anomaly, predicted_anomaly))
    fp = sum(not left and right for left, right in zip(actual_anomaly, predicted_anomaly))
    fn = sum(left and not right for left, right in zip(actual_anomaly, predicted_anomaly))
    tn = sum(not left and not right and predictions[index]["status"] == "MATCH" for index, (left, right) in enumerate(zip(actual_anomaly, predicted_anomaly)))
    precision, recall, f1 = _prf(tp, fp, fn)
    per_class: list[tuple[int, int, int, int]] = []
    for label in TRUE_CLASSES:
        class_tp = sum(a == label and p == label for a, p in zip(actual, predicted))
        class_fp = sum(a != label and p == label for a, p in zip(actual, predicted))
        class_fn = sum(a == label and p != label for a, p in zip(actual, predicted))
        support = sum(a == label for a in actual)
        per_class.append((class_tp, class_fp, class_fn, support))
    macro = statistics.fmean(_prf(tp_, fp_, fn_)[2] for tp_, fp_, fn_, _ in per_class)
    weighted = _division(sum(_prf(tp_, fp_, fn_)[2] * support for tp_, fp_, fn_, support in per_class), len(actual))
    sum_tp = sum(row[0] for row in per_class)
    sum_fp = sum(row[1] for row in per_class)
    sum_fn = sum(row[2] for row in per_class)
    micro = _prf(sum_tp, sum_fp, sum_fn)[2]
    return {
        "total_cases": len(actual),
        "exact_failure_type_accuracy": _division(exact_correct, len(actual)),
        "binary_anomaly_accuracy_with_abstentions_incorrect": _division(tp + tn, len(actual)),
        "binary_precision": precision,
        "binary_recall": recall,
        "binary_f1": f1,
        "false_positive_rate": _division(fp, sum(not value for value in actual_anomaly)),
        "false_negative_rate_including_insufficient_as_missed": _division(fn, sum(actual_anomaly)),
        "macro_f1_16_classes": macro,
        "micro_f1_16_classes": micro,
        "weighted_f1_16_classes": weighted,
        "binary_counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "insufficient_evidence": sum(row["status"] == "INSUFFICIENT_EVIDENCE" for row in predictions),
    }


def per_failure_metrics(predictions: list[dict[str, Any]], labels: dict[str, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for rule in RULES:
        actual_positive = {case_id for case_id, label in labels.items() if label == rule.failure_type}
        predicted_positive = {row["case_id"] for row in predictions if row["predicted_failure_type"] == rule.failure_type}
        tp = len(actual_positive & predicted_positive)
        fp = len(predicted_positive - actual_positive)
        fn = len(actual_positive - predicted_positive)
        precision, recall, f1 = _prf(tp, fp, fn)
        insufficient = sum(row["case_id"] in actual_positive and row["status"] == "INSUFFICIENT_EVIDENCE" for row in predictions)
        result.append({
            "rule": rule.rule_id,
            "failure_type": rule.failure_type,
            "N": len(actual_positive),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "FP": fp,
            "FN": fn,
            "insufficient_evidence": insufficient,
        })
    return result


def grouped_metrics(predictions: list[dict[str, Any]], labels: dict[str, str], attribute: str) -> list[dict[str, Any]]:
    if attribute == "tier":
        groups: dict[int, set[str]] = defaultdict(set)
        for rule in RULES:
            groups[rule.tier].add(rule.failure_type)
    elif attribute == "hop_count":
        groups = defaultdict(set)
        for rule in RULES:
            groups[rule.hop_count].add(rule.failure_type)
    else:
        raise ValueError(attribute)
    result: list[dict[str, Any]] = []
    for group, failures in sorted(groups.items()):
        actual_positive = {case_id for case_id, label in labels.items() if label in failures}
        predicted_positive = {row["case_id"] for row in predictions if row["predicted_failure_type"] in failures}
        tp = len(actual_positive & predicted_positive)
        fp = len(predicted_positive - actual_positive)
        fn = len(actual_positive - predicted_positive)
        tn = len(labels) - tp - fp - fn
        precision, recall, f1 = _prf(tp, fp, fn)
        exact = sum(
            row["case_id"] in actual_positive and row["predicted_failure_type"] == labels[row["case_id"]]
            for row in predictions
        )
        insufficient = sum(row["case_id"] in actual_positive and row["status"] == "INSUFFICIENT_EVIDENCE" for row in predictions)
        result.append({
            attribute: group,
            "N": len(actual_positive),
            "accuracy_exact_within_group": _division(exact, len(actual_positive)),
            "precision_group_one_vs_rest": precision,
            "recall_group_one_vs_rest": recall,
            "f1_group_one_vs_rest": f1,
            "false_positive_rate": _division(fp, fp + tn),
            "false_negative_rate": _division(fn, tp + fn),
            "insufficient_evidence_rate": _division(insufficient, len(actual_positive)),
        })
    return result


def tri_state_analysis(predictions: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any]:
    overall = Counter(row["status"] for row in predictions)
    by_failure: dict[str, Counter[str]] = defaultdict(Counter)
    by_tier: dict[str, Counter[str]] = defaultdict(Counter)
    by_hop: dict[str, Counter[str]] = defaultdict(Counter)
    for row in predictions:
        label = labels[row["case_id"]]
        by_failure[label][row["status"]] += 1
        rule = RULE_BY_FAILURE.get(label)
        if rule:
            by_tier[f"Tier {rule.tier}"][row["status"]] += 1
            by_hop[str(rule.hop_count)][row["status"]] += 1
        else:
            by_tier["NO_FAILURE"][row["status"]] += 1
            by_hop["NO_FAILURE"][row["status"]] += 1
    return {
        "overall": dict(overall),
        "by_failure_type": {key: dict(value) for key, value in sorted(by_failure.items())},
        "by_tier": {key: dict(value) for key, value in sorted(by_tier.items())},
        "by_hop_count": {key: dict(value) for key, value in sorted(by_hop.items())},
    }


def _returned_identity_tokens(evidence_record_ids: list[str]) -> set[str]:
    result: set[str] = set()
    for record_id in evidence_record_ids:
        _, key = record_id.split(":", 1)
        result.add(key)
        result.update(part for part in key.split("|") if part)
    return result


def evidence_metrics(predictions: list[dict[str, Any]], truth: dict[str, dict[str, Any]], labels: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    total_tp_ids = total_returned_ids = total_expected_ids = 0
    anomaly_outputs = 0
    contract_passes = 0
    correct_anomaly = 0
    correct_complete = 0
    for prediction in predictions:
        case_id = prediction["case_id"]
        expected = {str(value) for value in truth[case_id].get("evidence_ids", [])}
        returned = _returned_identity_tokens(prediction["evidence_record_ids"])
        overlap = expected & returned
        expected_tables = set(truth[case_id].get("evidence_required", []))
        returned_tables = {value.split(":", 1)[0] for value in prediction["evidence_record_ids"]}
        trace = next((value for value in prediction["rule_traces"] if value["rule_id"] == prediction["triggered_rule_id"]), None)
        contract_pass = bool(trace and trace["evidence_contract_pass"]) if prediction["status"] == "ANOMALY" else None
        if prediction["status"] == "ANOMALY":
            anomaly_outputs += 1
            contract_passes += bool(contract_pass)
            total_tp_ids += len(overlap)
            total_returned_ids += len(returned)
            total_expected_ids += len(expected)
        classification_correct = prediction["predicted_failure_type"] == labels[case_id]
        if classification_correct and prediction["status"] == "ANOMALY":
            correct_anomaly += 1
            if contract_pass and expected <= returned:
                correct_complete += 1
        rows.append({
            "case_id": case_id,
            "classification_correct": classification_correct,
            "evidence_contract_pass": contract_pass,
            "ground_truth_evidence_ids": "|".join(sorted(expected)),
            "returned_identity_tokens": "|".join(sorted(returned)),
            "id_precision": _division(len(overlap), len(returned)),
            "id_recall": _division(len(overlap), len(expected)),
            "required_tables": "|".join(sorted(expected_tables)),
            "returned_tables": "|".join(sorted(returned_tables)),
            "required_table_coverage": _division(len(expected_tables & returned_tables), len(expected_tables)),
        })
    unavailable_errors = sum(
        prediction["status"] == "INSUFFICIENT_EVIDENCE" and prediction["predicted_failure_type"] != labels[prediction["case_id"]]
        for prediction in predictions
    )
    summary = {
        "anomaly_decisions": anomaly_outputs,
        "evidence_contract_accuracy": _division(contract_passes, anomaly_outputs),
        "evidence_id_micro_precision_if_definable": _division(total_tp_ids, total_returned_ids),
        "evidence_id_micro_recall_if_definable": _division(total_tp_ids, total_expected_ids),
        "correct_anomaly_predictions": correct_anomaly,
        "percentage_correct_anomaly_predictions_with_correct_complete_evidence": _division(correct_complete, correct_anomaly),
        "percentage_correct_anomaly_predictions_with_incomplete_evidence": _division(correct_anomaly - correct_complete, correct_anomaly),
        "percentage_all_incorrect_predictions_caused_by_unavailable_evidence": _division(
            unavailable_errors,
            sum(prediction["predicted_failure_type"] != labels[prediction["case_id"]] for prediction in predictions),
        ),
        "evidence_id_metric_note": "IDs compare returned record primary-key tokens with benchmark evidence IDs; classification and internal frozen evidence-contract checks are reported separately.",
    }
    return summary, rows


def error_analysis(predictions: list[dict[str, Any]], labels: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for prediction in predictions:
        case_id = prediction["case_id"]
        actual = labels[case_id]
        predicted = prediction["predicted_failure_type"]
        if predicted == actual:
            continue
        actual_rule = RULE_BY_FAILURE.get(actual)
        predicted_rule = RULE_BY_FAILURE.get(predicted or "")
        expected_trace = next((trace for trace in prediction["rule_traces"] if trace["failure_type"] == actual), None)
        secondary: list[str] = []
        if prediction["status"] == "INSUFFICIENT_EVIDENCE":
            primary = "MISSING_EVIDENCE"
            secondary.append("FALSE_NEGATIVE" if actual != "NO_FAILURE" else "AMBIGUOUS_CASE")
        elif predicted == "NO_FAILURE" and actual != "NO_FAILURE":
            primary = "FALSE_NEGATIVE"
            secondary.append("RULE_LIMITATION")
        elif actual == "NO_FAILURE" and predicted != "NO_FAILURE":
            primary = "FALSE_POSITIVE"
            secondary.append("RULE_LIMITATION")
        elif expected_trace and expected_trace["status"] == "ANOMALY" and prediction["collision"]["precedence_rule_applied"]:
            primary = "COLLISION_OR_PRECEDENCE"
            secondary.extend(("FALSE_POSITIVE", "FALSE_NEGATIVE"))
        else:
            primary = "FALSE_POSITIVE"
            secondary.extend(("FALSE_NEGATIVE", "RULE_LIMITATION"))
        if actual in {"F01_DUPLICATE_INVOICE", "F02_PO_INVOICE_AMOUNT_MISMATCH", "F12_ERP_PAYMENT_MISSING_FROM_BANK", "F15_INCORRECT_PAYMENT_BANK_MATCH"}:
            secondary.append("THRESHOLD_LIMITATION")
        if expected_trace is None and actual != "NO_FAILURE":
            secondary.append("INCORRECT_JOIN_OR_RELATIONSHIP")
        rows.append({
            "case_id": case_id,
            "actual_failure_type": actual,
            "predicted_failure_type": predicted or "",
            "status": prediction["status"],
            "tier": actual_rule.tier if actual_rule else "",
            "hop_count": actual_rule.hop_count if actual_rule else "",
            "primary_cause": primary,
            "secondary_causes": "|".join(dict.fromkeys(secondary)),
            "expected_rule_trace_status": expected_trace["status"] if expected_trace else "NOT_APPLICABLE",
            "selected_reason": prediction["reason"],
        })
    return rows


def aggregate_errors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[Any, ...]] = Counter()
    for row in rows:
        counts[(row["actual_failure_type"], row["tier"], row["hop_count"], row["primary_cause"])] += 1
    return [
        {"failure_type": key[0], "tier": key[1], "hop_count": key[2], "error_category": key[3], "count": count}
        for key, count in sorted(counts.items(), key=lambda item: tuple(str(value) for value in item[0]))
    ]


def latency_metrics(predictions: list[dict[str, Any]], total_runtime: float) -> dict[str, Any]:
    values = sorted(row["latency_ns"] / 1_000_000 for row in predictions)
    def percentile(fraction: float) -> float | None:
        if not values:
            return None
        index = max(0, min(len(values) - 1, math.ceil(fraction * len(values)) - 1))
        return values[index]
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak if platform.system() == "Darwin" else peak * 1024
    return {
        "total_evaluation_runtime_seconds": total_runtime,
        "case_latency_sum_seconds": sum(values) / 1000,
        "mean_latency_ms": statistics.fmean(values) if values else None,
        "median_latency_ms": statistics.median(values) if values else None,
        "p95_latency_ms": percentile(0.95),
        "p99_latency_ms": percentile(0.99) if len(values) >= 100 else None,
        "throughput_cases_per_second": _division(len(values), total_runtime),
        "case_count": len(values),
        "runtime_technology": f"CPython {platform.python_version()} standard-library in-memory relational indexes",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "not reported",
        "logical_cpu_count": os.cpu_count(),
        "peak_process_rss_bytes_approximate": peak_bytes,
        "external_services": "none",
        "llm_or_api_cost": 0,
    }


def run_test_suite(repo_root: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "tests/rules_sql", "-q"]
    result = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, check=False)
    return {
        "command": " ".join(command),
        "return_code": result.returncode,
        "passed": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def dependency_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for package in ("numpy", "yaml", "pytest"):
        try:
            module = __import__(package)
            versions[package] = str(getattr(module, "__version__", "unknown"))
        except ImportError:
            versions[package] = "not installed"
    return versions
