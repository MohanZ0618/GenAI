"""Evaluation and comparison functions for the frozen classical ML baseline."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import confusion_matrix, log_loss

from src.classical_ml.modeling import score_predictions
from src.classical_ml.registry import (
    CATEGORICAL_FEATURE_NAMES,
    CLASSES,
    FAILURE_TYPES,
    HOP_BY_CLASS,
    MISSING_FEATURES,
    RANDOM_SEED,
    TIER_BY_CLASS,
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def labels_from_manifest(path: Path) -> dict[str, str]:
    frame = pd.read_csv(path, usecols=["case_id", "failure_type"], dtype=str)
    if frame["case_id"].duplicated().any():
        raise ValueError(f"duplicate labels in {path}")
    return dict(zip(frame["case_id"], frame["failure_type"]))


def prediction_records(
    case_ids: list[str],
    predicted: np.ndarray,
    probabilities: np.ndarray,
    estimator_classes: np.ndarray,
    family: str,
    per_case_latency_ns: list[int],
) -> list[dict[str, Any]]:
    class_positions = {str(label): index for index, label in enumerate(estimator_classes)}
    records: list[dict[str, Any]] = []
    for row_index, (case_id, prediction) in enumerate(zip(case_ids, predicted)):
        label = str(prediction)
        class_probabilities = {
            class_name: float(probabilities[row_index, class_positions[class_name]])
            for class_name in CLASSES
        }
        records.append({
            "case_id": case_id,
            "method": "classical_ml",
            "model_family": family,
            "predicted_failure_type": label,
            "is_anomaly": label != "NO_FAILURE",
            "predicted_probability": class_probabilities[label],
            "class_probabilities": class_probabilities,
            "tier": TIER_BY_CLASS.get(label, 0),
            "hop_count": HOP_BY_CLASS.get(label, 0),
            "status": "MATCH" if label == "NO_FAILURE" else "ANOMALY",
            "evidence_record_ids": [],
            "reason": None,
            "latency_ns": int(per_case_latency_ns[row_index]),
        })
    return records


def evaluate_predictions(records: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any]:
    actual = [labels[row["case_id"]] for row in records]
    predicted = [row["predicted_failure_type"] for row in records]
    result = score_predictions(actual, predicted)
    result["total_cases"] = len(actual)
    result["model_output_states"] = dict(sorted(Counter(row["status"] for row in records).items()))
    result["evidence_contract_accuracy"] = None
    result["evidence_limitation"] = "Classical ML does not return transaction evidence; evidence_record_ids are empty by contract."
    return result


def per_failure_metrics(records: list[dict[str, Any]], labels: dict[str, str]) -> list[dict[str, Any]]:
    actual = np.asarray([labels[row["case_id"]] for row in records], dtype=object)
    predicted = np.asarray([row["predicted_failure_type"] for row in records], dtype=object)
    rows: list[dict[str, Any]] = []
    for failure in FAILURE_TYPES:
        truth = actual == failure
        output = predicted == failure
        tp, fp, fn = int(np.sum(truth & output)), int(np.sum(~truth & output)), int(np.sum(truth & ~output))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        rows.append({
            "rule": failure.split("_", 1)[0], "failure_type": failure, "N": int(np.sum(truth)),
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "FP": fp, "FN": fn, "insufficient_evidence": 0,
        })
    return rows


def grouped_metrics(records: list[dict[str, Any]], labels: dict[str, str], kind: str) -> list[dict[str, Any]]:
    mapping = TIER_BY_CLASS if kind == "tier" else HOP_BY_CLASS
    groups = sorted(set(mapping.values()))
    rows: list[dict[str, Any]] = []
    for group in groups:
        relevant = {label for label, value in mapping.items() if value == group}
        selected = [row for row in records if labels[row["case_id"]] in relevant]
        actual = [labels[row["case_id"]] for row in selected]
        predicted = [row["predicted_failure_type"] for row in selected]
        exact = sum(left == right for left, right in zip(actual, predicted))
        all_actual = np.asarray([labels[row["case_id"]] for row in records], dtype=object)
        all_predicted = np.asarray([row["predicted_failure_type"] for row in records], dtype=object)
        truth = np.isin(all_actual, list(relevant))
        output = np.isin(all_predicted, list(relevant))
        tp, fp, fn, tn = (
            int(np.sum(truth & output)), int(np.sum(~truth & output)),
            int(np.sum(truth & ~output)), int(np.sum(~truth & ~output)),
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        rows.append({
            kind: group, "N": len(selected), "accuracy_exact_within_group": exact / len(selected) if selected else 0.0,
            "precision_group_one_vs_rest": precision, "recall_group_one_vs_rest": recall,
            "f1_group_one_vs_rest": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
            "false_negative_rate": fn / (fn + tp) if fn + tp else 0.0,
            "insufficient_evidence_rate": 0.0,
        })
    return rows


def confusion_rows(records: list[dict[str, Any]], labels: dict[str, str]) -> list[dict[str, Any]]:
    actual = [labels[row["case_id"]] for row in records]
    predicted = [row["predicted_failure_type"] for row in records]
    matrix = confusion_matrix(actual, predicted, labels=list(CLASSES))
    return [
        {"actual": label, **{predicted_label: int(matrix[index, column]) for column, predicted_label in enumerate(CLASSES)}}
        for index, label in enumerate(CLASSES)
    ]


def calibration_metrics(records: list[dict[str, Any]], labels: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actual = [labels[row["case_id"]] for row in records]
    probabilities = np.asarray([[row["class_probabilities"][label] for label in CLASSES] for row in records])
    targets = np.zeros_like(probabilities)
    positions = {label: index for index, label in enumerate(CLASSES)}
    for index, label in enumerate(actual):
        targets[index, positions[label]] = 1.0
    confidence = np.max(probabilities, axis=1)
    correctness = np.asarray([row["predicted_failure_type"] == actual[index] for index, row in enumerate(records)], dtype=float)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    for bin_index in range(10):
        lower, upper = bin_index / 10, (bin_index + 1) / 10
        mask = (confidence >= lower) & (confidence < upper if bin_index < 9 else confidence <= upper)
        count = int(np.sum(mask))
        accuracy = float(np.mean(correctness[mask])) if count else None
        mean_confidence = float(np.mean(confidence[mask])) if count else None
        if count:
            ece += count / len(records) * abs(accuracy - mean_confidence)
        bins.append({"bin": bin_index + 1, "lower_inclusive": lower, "upper_exclusive_except_last": upper,
                     "count": count, "accuracy": accuracy, "mean_confidence": mean_confidence})
    return {
        "multiclass_log_loss": float(log_loss(actual, probabilities, labels=list(CLASSES))),
        "multiclass_brier_score": float(np.mean(np.sum((probabilities - targets) ** 2, axis=1))),
        "top_label_ece_10_bins": float(ece),
    }, bins


def compare_rules(
    ml_records: list[dict[str, Any]],
    rules_records: list[dict[str, Any]],
    labels: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    rules = {row["case_id"]: row for row in rules_records}
    if set(rules) != {row["case_id"] for row in ml_records}:
        raise ValueError("locked Rules/SQL predictions do not match ML test case IDs")
    partitions = Counter()
    binary_partitions = Counter()
    comparison_rows: list[dict[str, Any]] = []
    insufficient_rows: list[dict[str, Any]] = []
    for ml in ml_records:
        case_id, actual = ml["case_id"], labels[ml["case_id"]]
        rule = rules[case_id]
        ml_exact = ml["predicted_failure_type"] == actual
        rule_exact = rule["predicted_failure_type"] == actual
        key = "both_correct" if ml_exact and rule_exact else "rules_only_correct" if rule_exact else "ml_only_correct" if ml_exact else "both_wrong"
        partitions[key] += 1
        truth_binary = actual != "NO_FAILURE"
        ml_binary = bool(ml["is_anomaly"])
        rule_binary_correct = (rule["status"] == "ANOMALY") == truth_binary and rule["status"] != "INSUFFICIENT_EVIDENCE"
        ml_binary_correct = ml_binary == truth_binary
        binary_key = "both_correct" if ml_binary_correct and rule_binary_correct else "rules_only_correct" if rule_binary_correct else "ml_only_correct" if ml_binary_correct else "both_wrong"
        binary_partitions[binary_key] += 1
        row = {
            "case_id": case_id, "actual": actual,
            "rules_prediction": rule["predicted_failure_type"], "rules_status": rule["status"],
            "ml_prediction": ml["predicted_failure_type"], "ml_probability": ml["predicted_probability"],
            "tier": TIER_BY_CLASS.get(actual, 0), "hop_count": HOP_BY_CLASS.get(actual, 0),
            "failure_type": actual, "exact_partition": key, "binary_partition": binary_key,
        }
        comparison_rows.append(row)
        if rule["status"] == "INSUFFICIENT_EVIDENCE":
            insufficient_rows.append({**row, "ml_exactly_recovered": ml_exact, "ml_binary_recovered": ml_binary_correct})
    summary = {
        "exact_correctness_partition": dict(partitions),
        "binary_correctness_partition": dict(binary_partitions),
        "rules_insufficient_cases": len(insufficient_rows),
        "rules_insufficient_ml_exact_recovered": sum(row["ml_exactly_recovered"] for row in insufficient_rows),
        "rules_insufficient_ml_binary_recovered": sum(row["ml_binary_recovered"] for row in insufficient_rows),
        "interpretation": "Recovery is classification-only; the ML evidence contract remains empty.",
    }
    return summary, comparison_rows, insufficient_rows


def exact_mcnemar(comparison_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rules_only = sum(row["exact_partition"] == "rules_only_correct" for row in comparison_rows)
    ml_only = sum(row["exact_partition"] == "ml_only_correct" for row in comparison_rows)
    discordant = rules_only + ml_only
    if discordant == 0:
        p_value = 1.0
    else:
        lower = min(rules_only, ml_only)
        one_tail = sum(math.comb(discordant, value) for value in range(lower + 1)) / (2 ** discordant)
        p_value = min(1.0, 2 * one_tail)
    return {"rules_only_correct": rules_only, "ml_only_correct": ml_only,
            "discordant_pairs": discordant, "two_sided_exact_p_value": p_value}


def paired_bootstrap(
    ml_records: list[dict[str, Any]], rules_records: list[dict[str, Any]], labels: dict[str, str], repeats: int = 2000,
) -> dict[str, Any]:
    rules_by_id = {row["case_id"]: row for row in rules_records}
    actual = np.asarray([labels[row["case_id"]] for row in ml_records], dtype=object)
    ml = np.asarray([row["predicted_failure_type"] for row in ml_records], dtype=object)
    rules = np.asarray([
        rules_by_id[row["case_id"]]["predicted_failure_type"] or "INSUFFICIENT_EVIDENCE"
        for row in ml_records
    ], dtype=object)
    rules_anomaly = np.asarray([rules_by_id[row["case_id"]]["status"] == "ANOMALY" for row in ml_records], dtype=bool)

    def binary_f1(actual_values: np.ndarray, predicted_values: np.ndarray) -> float:
        truth = actual_values != "NO_FAILURE"
        tp = int(np.sum(truth & predicted_values))
        fp = int(np.sum(~truth & predicted_values))
        fn = int(np.sum(truth & ~predicted_values))
        return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
    rng = np.random.default_rng(RANDOM_SEED)
    differences = {name: [] for name in ("exact_accuracy", "macro_f1", "binary_f1")}
    for _ in range(repeats):
        indices = rng.integers(0, len(actual), size=len(actual))
        ml_metrics = score_predictions(actual[indices], ml[indices])
        rules_metrics = score_predictions(actual[indices], rules[indices])
        differences["exact_accuracy"].append(ml_metrics["exact_accuracy"] - rules_metrics["exact_accuracy"])
        differences["macro_f1"].append(ml_metrics["macro_f1"] - rules_metrics["macro_f1"])
        differences["binary_f1"].append(
            binary_f1(actual[indices], ml[indices] != "NO_FAILURE") - binary_f1(actual[indices], rules_anomaly[indices])
        )
    result: dict[str, Any] = {"resamples": repeats, "seed": RANDOM_SEED, "difference_direction": "classical_ml_minus_rules_sql"}
    for name, values in differences.items():
        point = (
            binary_f1(actual, ml != "NO_FAILURE") - binary_f1(actual, rules_anomaly)
            if name == "binary_f1"
            else score_predictions(actual, ml)[name] - score_predictions(actual, rules)[name]
        )
        result[name] = {"point_difference": point, "ci95_percentile": [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]}
    return result


def unseen_category_flags(frame: pd.DataFrame, preprocessor: Any) -> dict[str, list[str]]:
    encoder = preprocessor.named_transformers_["categorical"].named_steps["one_hot"]
    known = {name: set(map(str, categories)) for name, categories in zip(CATEGORICAL_FEATURE_NAMES, encoder.categories_)}
    flags: dict[str, list[str]] = {}
    for _, row in frame.iterrows():
        flags[str(row["case_id"])] = [name for name in CATEGORICAL_FEATURE_NAMES if str(row[name]) not in known[name]]
    return flags


def error_analysis(
    records: list[dict[str, Any]], labels: dict[str, str], frame: pd.DataFrame,
    preprocessor: Any, training_support: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    features = frame.set_index("case_id")
    unseen = unseen_category_flags(frame, preprocessor)
    missing_names = [feature.name for feature in MISSING_FEATURES]
    relevant_missing = {
        "F01_DUPLICATE_INVOICE": {"missing_invoice", "missing_reference", "missing_vendor"},
        "F02_PO_INVOICE_AMOUNT_MISMATCH": {"missing_invoice", "missing_po", "missing_invoice_lines", "missing_po_lines"},
        "F03_QUANTITY_MISMATCH": {"missing_invoice", "missing_po", "missing_invoice_lines", "missing_po_lines"},
        "F04_INCORRECT_VENDOR_ASSOCIATION": {"missing_invoice", "missing_po", "missing_vendor"},
        "F05_PAYMENT_WITHOUT_VALID_INVOICE": {"missing_payment", "missing_allocations"},
        "F06_INVOICE_PAID_TWICE": {"missing_invoice", "missing_payment", "missing_allocations"},
        "F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE": {"missing_invoice", "missing_payment", "missing_allocations"},
        "F08_APPROVAL_WORKFLOW_FAILURE": {"missing_payment", "missing_approval", "missing_employee"},
        "F09_GL_POSTING_MISMATCH": {"missing_payment", "missing_gl"},
        "F10_WRONG_ACCOUNTING_PERIOD": {"missing_payment", "missing_gl"},
        "F11_VENDOR_MASTER_CHANGE_CONFLICT": {"missing_payment", "missing_vendor", "missing_vendor_change_history"},
        "F12_ERP_PAYMENT_MISSING_FROM_BANK": {"missing_payment", "missing_bank_transaction"},
        "F13_BANK_TRANSACTION_MISSING_FROM_ERP": {"missing_bank_transaction", "missing_payment"},
        "F14_BANK_ERP_AMOUNT_MISMATCH": {"missing_payment", "missing_bank_transaction"},
        "F15_INCORRECT_PAYMENT_BANK_MATCH": {"missing_payment", "missing_bank_transaction"},
    }
    rows: list[dict[str, Any]] = []
    for prediction in records:
        case_id, actual = prediction["case_id"], labels[prediction["case_id"]]
        if prediction["predicted_failure_type"] == actual:
            continue
        active_missing = [name for name in missing_names if float(features.loc[case_id, name]) == 1.0]
        missing_relevant_to_decision = relevant_missing.get(actual, set()) | relevant_missing.get(prediction["predicted_failure_type"], set())
        secondary: list[str] = ["CLASS_CONFUSION"]
        if unseen[case_id]:
            primary = "UNSEEN_CATEGORY"
        elif set(active_missing) & missing_relevant_to_decision:
            primary = "MISSING_INFORMATION"
        elif training_support.get(actual, 0) < 50:
            primary = "RARE_CLASS"
        elif HOP_BY_CLASS.get(actual, 0) >= 3:
            primary = "RELATIONAL_COMPLEXITY"
        elif prediction["predicted_probability"] < 0.5:
            primary = "AMBIGUOUS_CASE"
        else:
            primary = "CLASS_CONFUSION"
            secondary = []
        rows.append({
            "case_id": case_id, "actual": actual, "predicted": prediction["predicted_failure_type"],
            "predicted_probability": prediction["predicted_probability"],
            "tier": TIER_BY_CLASS.get(actual, 0), "hop_count": HOP_BY_CLASS.get(actual, 0),
            "primary_cause": primary, "secondary_causes": "|".join(value for value in secondary if value != primary),
            "active_missing_features": "|".join(active_missing), "unseen_categories": "|".join(unseen[case_id]),
        })
    aggregates = [
        {"dimension": dimension, "value": str(value), "count": count}
        for dimension, getter in (
            ("failure_type", lambda row: row["actual"]), ("tier", lambda row: row["tier"]),
            ("hop_count", lambda row: row["hop_count"]), ("error_category", lambda row: row["primary_cause"]),
        )
        for value, count in sorted(Counter(getter(row) for row in rows).items(), key=lambda item: str(item[0]))
    ]
    confidence_bands = Counter(
        "[0,0.5)" if row["predicted_probability"] < 0.5
        else "[0.5,0.8)" if row["predicted_probability"] < 0.8
        else "[0.8,1.0]"
        for row in rows
    )
    aggregates.extend({"dimension": "confidence_band", "value": band, "count": confidence_bands.get(band, 0)}
                      for band in ("[0,0.5)", "[0.5,0.8)", "[0.8,1.0]"))
    return rows, aggregates


def permutation_importance_rows(estimator: Any, x_validation: np.ndarray, y_validation: np.ndarray, names: Iterable[str]) -> list[dict[str, Any]]:
    result = permutation_importance(estimator, x_validation, y_validation, scoring="f1_macro", n_repeats=10,
                                    random_state=RANDOM_SEED, n_jobs=1)
    rows = [{"feature": str(name), "importance_mean": float(mean), "importance_std": float(std)}
            for name, mean, std in zip(names, result.importances_mean, result.importances_std)]
    return sorted(rows, key=lambda row: (-row["importance_mean"], row["feature"]))


def robustness_results(frame: pd.DataFrame, preprocessor: Any, estimator: Any, labels: dict[str, str]) -> list[dict[str, Any]]:
    case_ids = frame["case_id"].tolist()
    original_features = frame.drop(columns=["case_id"])
    original = estimator.predict(preprocessor.transform(original_features))
    scenarios: list[tuple[str, pd.DataFrame]] = []
    optional_money = [name for name in ("invoice_tax", "invoice_shipping", "po_tax", "po_shipping") if name in frame]
    changed = original_features.copy(); changed.loc[:, optional_money] = np.nan
    scenarios.append(("optional_tax_shipping_missing", changed))
    changed = original_features.copy(); changed.loc[:, "vendor_country"] = "ZZ_UNSEEN"
    scenarios.append(("vendor_category_unseen", changed))
    vendor_categories = [name for name in CATEGORICAL_FEATURE_NAMES if name.startswith("vendor_")]
    changed = original_features.copy(); changed.loc[:, vendor_categories] = "__MISSING__"
    scenarios.append(("optional_vendor_categories_missing", changed))
    changed = original_features.copy()
    amount_names = [name for name in changed if name.startswith(("invoice_", "payment_", "bank_")) and "amount" in name]
    for name in amount_names:
        changed[name] = changed[name].where(changed[name].isna(), changed[name] + 0.01)
    scenarios.append(("native_amount_plus_0_01", changed))
    actual = np.asarray([labels[case_id] for case_id in case_ids], dtype=object)
    rows = []
    for name, changed in scenarios:
        prediction = estimator.predict(preprocessor.transform(changed))
        rows.append({"scenario": name, "cases": len(case_ids), "exact_accuracy": float(np.mean(prediction == actual)),
                     "prediction_agreement_with_primary": float(np.mean(prediction == original)),
                     "changed_predictions": int(np.sum(prediction != original))})
    return rows
