"""Offline-only evaluation of preserved Direct LLM predictions."""

from __future__ import annotations

import csv
import json
import math
import random
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from sklearn.metrics import precision_recall_fscore_support

from src.direct_llm.artifacts import load_jsonl, write_csv, write_json
from src.direct_llm.audits import percentile
from src.direct_llm.config import ALL_CLASSES, BASELINE_CONFIG, FAILURE_TYPES
from src.direct_llm.runner import pricing_report
from src.ground_truth.rca_builder import TABLE_ID_FIELDS
from src.rules_sql.registry import RULE_BY_FAILURE


UNRESOLVED = "__UNRESOLVED__"


def _division(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_evaluation_inputs(data_root: Path) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    manifest = _load_csv(data_root / "test/failure_manifest.csv")
    labels = {row["case_id"]: row["failure_type"] for row in manifest}
    truth = {row["case_id"]: row for row in load_jsonl(data_root / "test/rca_ground_truth.jsonl")}
    if set(labels) != set(truth) or len(labels) != 439:
        raise ValueError("held-out labels/ground truth do not describe exactly 439 identical cases")
    return labels, truth


def _parsed_class(row: dict[str, Any]) -> str:
    value = row.get("predicted_failure_type")
    return str(value) if row.get("parse_status") == "PASS" and value in ALL_CLASSES else UNRESOLVED


def classification_metrics(
    predictions: list[dict[str, Any]], labels: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_id = {row["case_id"]: row for row in predictions}
    ordered_ids = list(labels)
    actual = [labels[case_id] for case_id in ordered_ids]
    predicted = [_parsed_class(by_id[case_id]) for case_id in ordered_ids]
    precision_macro, recall_macro, macro_f1, _ = precision_recall_fscore_support(
        actual, predicted, labels=list(ALL_CLASSES), average="macro", zero_division=0
    )
    _, _, micro_f1, _ = precision_recall_fscore_support(
        actual, predicted, labels=list(ALL_CLASSES), average="micro", zero_division=0
    )
    _, _, weighted_f1, _ = precision_recall_fscore_support(
        actual, predicted, labels=list(ALL_CLASSES), average="weighted", zero_division=0
    )
    actual_binary = [value != "NO_FAILURE" for value in actual]
    predicted_binary: list[bool | None] = []
    for value in predicted:
        predicted_binary.append(None if value == UNRESOLVED else value != "NO_FAILURE")
    tp = sum(a and p is True for a, p in zip(actual_binary, predicted_binary))
    tn = sum(not a and p is False for a, p in zip(actual_binary, predicted_binary))
    fp = sum(not a and p is True for a, p in zip(actual_binary, predicted_binary))
    fn = sum(a and p is not True for a, p in zip(actual_binary, predicted_binary))
    unresolved_normal = sum(not a and p is None for a, p in zip(actual_binary, predicted_binary))
    binary_precision = _division(tp, tp + fp)
    binary_recall = _division(tp, tp + fn)
    status_counts = Counter(str(row.get("status")) for row in predictions)
    parse_counts = Counter(str(row.get("parse_status")) for row in predictions)
    metrics = {
        "total_cases": len(actual),
        "successfully_parsed_cases": sum(value != UNRESOLVED for value in predicted),
        "exact_16_class_accuracy": _division(sum(a == p for a, p in zip(actual, predicted)), len(actual)),
        "binary_accuracy_strict": _division(tp + tn, len(actual)),
        "binary_precision": binary_precision,
        "binary_recall": binary_recall,
        "binary_f1": _division(2 * binary_precision * binary_recall, binary_precision + binary_recall),
        "macro_f1_16_classes": macro_f1,
        "micro_f1_16_classes": micro_f1,
        "weighted_f1_16_classes": weighted_f1,
        "macro_precision_16_classes": precision_macro,
        "macro_recall_16_classes": recall_macro,
        "false_positive_rate": _division(fp, sum(not value for value in actual_binary)),
        "false_negative_rate": _division(fn, sum(actual_binary)),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "unresolved_normal_cases_counted_incorrect": unresolved_normal,
        "status_counts": dict(sorted(status_counts.items())),
        "parse_status_counts": dict(sorted(parse_counts.items())),
        "match_count": status_counts.get("MATCH", 0),
        "anomaly_count": status_counts.get("ANOMALY", 0),
        "insufficient_evidence_count": status_counts.get("INSUFFICIENT_EVIDENCE", 0),
        "malformed_output_count": parse_counts.get("MALFORMED_RESPONSE", 0) + parse_counts.get("SCHEMA_INVALID_RESPONSE", 0),
        "refusal_count": parse_counts.get("MODEL_REFUSAL", 0),
        "api_failure_count": parse_counts.get("PERMANENT_API_ERROR", 0) + parse_counts.get("TRANSIENT_API_FAILURE_EXHAUSTED", 0),
    }
    confusion_rows = []
    columns = [*ALL_CLASSES, UNRESOLVED]
    for actual_class in ALL_CLASSES:
        selected = [pred for truth_value, pred in zip(actual, predicted) if truth_value == actual_class]
        row: dict[str, Any] = {"actual_failure_type": actual_class, "support": len(selected)}
        row.update({column: selected.count(column) for column in columns})
        confusion_rows.append(row)
    return metrics, confusion_rows


def per_failure_metrics(predictions: list[dict[str, Any]], labels: dict[str, str]) -> list[dict[str, Any]]:
    by_id = {row["case_id"]: row for row in predictions}
    result = []
    for failure in FAILURE_TYPES:
        actual = [value == failure for value in labels.values()]
        predicted = [_parsed_class(by_id[case_id]) == failure for case_id in labels]
        tp = sum(a and p for a, p in zip(actual, predicted))
        fp = sum(not a and p for a, p in zip(actual, predicted))
        fn = sum(a and not p for a, p in zip(actual, predicted))
        precision = _division(tp, tp + fp)
        recall = _division(tp, tp + fn)
        result.append({
            "failure_type": failure,
            "N": sum(actual),
            "precision": precision,
            "recall": recall,
            "f1": _division(2 * precision * recall, precision + recall),
            "FP": fp,
            "FN": fn,
        })
    return result


def grouped_metrics(
    predictions: list[dict[str, Any]], labels: dict[str, str], truth: dict[str, dict[str, Any]], group: str
) -> list[dict[str, Any]]:
    by_id = {row["case_id"]: row for row in predictions}
    groups: dict[str, list[str]] = {}
    for case_id, actual in labels.items():
        if actual == "NO_FAILURE":
            continue
        key = str(RULE_BY_FAILURE[actual].tier) if group == "tier" else str(truth[case_id]["reasoning_hops"])
        groups.setdefault(key, []).append(case_id)
    rows = []
    for key in sorted(groups, key=lambda value: int(value)):
        case_ids = groups[key]
        exact = sum(_parsed_class(by_id[case_id]) == labels[case_id] for case_id in case_ids)
        actual_group = set(case_ids)
        predicted_group = {
            case_id for case_id in labels
            if (predicted := _parsed_class(by_id[case_id])) in FAILURE_TYPES
            and (
                (group == "tier" and str(RULE_BY_FAILURE[predicted].tier) == key)
                or (group == "hop_count" and str(RULE_BY_FAILURE[predicted].hop_count) == key)
            )
        }
        tp = len(actual_group & predicted_group)
        fp = len(predicted_group - actual_group)
        fn = len(actual_group - predicted_group)
        precision = _division(tp, tp + fp)
        recall = _division(tp, tp + fn)
        insufficient = sum(by_id[case_id].get("status") == "INSUFFICIENT_EVIDENCE" for case_id in case_ids)
        evidence_valid = [
            bool(by_id[case_id].get("evidence_valid")) for case_id in case_ids
            if by_id[case_id].get("status") == "ANOMALY"
        ]
        rows.append({
            group: int(key),
            "N": len(case_ids),
            "accuracy": _division(exact, len(case_ids)),
            "precision": precision,
            "recall": recall,
            "f1": _division(2 * precision * recall, precision + recall),
            "false_positive_rate": _division(fp, len(labels) - len(actual_group)),
            "false_negative_rate": _division(fn, len(actual_group)),
            "insufficient_evidence_rate": _division(insufficient, len(case_ids)),
            "evidence_accuracy": _division(sum(evidence_valid), len(evidence_valid)),
        })
    return rows


def _packet_records(packet_row: dict[str, Any]) -> tuple[set[str], dict[str, tuple[str, dict[str, str]]]]:
    packet = json.loads(packet_row["serialized_packet"])
    record_map: dict[str, tuple[str, dict[str, str]]] = {}
    for table, rows in packet["records"].items():
        for row in rows:
            record_map[row["record_id"]] = (table, row)
    return set(record_map), record_map


def _row_identifier_tokens(table: str, row: dict[str, str]) -> set[str]:
    fields = TABLE_ID_FIELDS.get(table, ())
    return {str(row.get(field, "")) for field in fields if str(row.get(field, ""))}


def evidence_evaluation(
    predictions: list[dict[str, Any]],
    labels: dict[str, str],
    truth: dict[str, dict[str, Any]],
    packet_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    packets = {row["case_id"]: _packet_records(row) for row in packet_rows}
    prediction_by_id = {row["case_id"]: row for row in predictions}
    rows = []
    anomaly_outputs = hallucinated_outputs = contract_passes = complete_count = fully_grounded = 0
    correct_class_incorrect_evidence = 0
    returned_total = expected_total = overlap_total = 0
    enriched: dict[str, dict[str, Any]] = {}
    for case_id, actual in labels.items():
        prediction = prediction_by_id[case_id]
        packet_ids, record_map = packets[case_id]
        cited = [str(value) for value in prediction.get("evidence_record_ids", [])]
        invalid = sorted(set(cited) - packet_ids)
        valid = not invalid
        cited_tables: set[str] = set()
        returned_tokens: set[str] = set()
        for value in cited:
            if value in record_map:
                table, row = record_map[value]
                cited_tables.add(table)
                returned_tokens.update(_row_identifier_tokens(table, row))
        expected = {str(value) for value in truth[case_id].get("evidence_ids", [])}
        expected_required = set(truth[case_id].get("evidence_required", []))
        expected_tables_present: set[str] = set()
        packet_tokens: set[str] = set()
        for _, (table, row) in record_map.items():
            tokens = _row_identifier_tokens(table, row)
            packet_tokens.update(tokens)
            if expected & tokens:
                expected_tables_present.add(table)
        observable_required = expected_required & expected_tables_present
        packet_coverage = expected <= packet_tokens
        contract = valid and observable_required <= cited_tables
        complete = expected <= returned_tokens
        overlap = expected & returned_tokens
        classification_correct = _parsed_class(prediction) == actual
        is_anomaly_output = prediction.get("status") == "ANOMALY"
        is_classification_decision = prediction.get("status") in {"ANOMALY", "MATCH"}
        if is_anomaly_output:
            anomaly_outputs += 1
            hallucinated_outputs += bool(invalid)
            contract_passes += contract
            complete_count += complete
            returned_total += len(returned_tokens)
            expected_total += len(expected)
            overlap_total += len(overlap)
        evidence_grounded = classification_correct and is_classification_decision and contract and complete
        fully_grounded += evidence_grounded
        if classification_correct and actual != "NO_FAILURE" and not (contract and complete):
            correct_class_incorrect_evidence += 1
        row = {
            "case_id": case_id,
            "actual_failure_type": actual,
            "predicted_failure_type": prediction.get("predicted_failure_type"),
            "classification_correct": classification_correct,
            "evidence_valid": valid,
            "invalid_evidence_record_ids": "|".join(invalid),
            "evidence_contract_correct": contract if is_classification_decision else None,
            "evidence_complete": complete if is_classification_decision else None,
            "packet_ground_truth_coverage": packet_coverage,
            "expected_ids": "|".join(sorted(expected)),
            "returned_identifier_tokens": "|".join(sorted(returned_tokens)),
            "required_tables_with_observable_annotations": "|".join(sorted(observable_required)),
            "cited_tables": "|".join(sorted(cited_tables)),
            "id_precision": _division(len(overlap), len(returned_tokens)),
            "id_recall": _division(len(overlap), len(expected)),
            "fully_evidence_grounded": evidence_grounded,
        }
        rows.append(row)
        enriched[case_id] = row
    summary = {
        "anomaly_outputs": anomaly_outputs,
        "evidence_validity_rate": _division(anomaly_outputs - hallucinated_outputs, anomaly_outputs),
        "evidence_contract_accuracy": _division(contract_passes, anomaly_outputs),
        "evidence_completeness_rate": _division(complete_count, anomaly_outputs),
        "hallucinated_evidence_rate": _division(hallucinated_outputs, anomaly_outputs),
        "evidence_id_micro_precision": _division(overlap_total, returned_total),
        "evidence_id_micro_recall": _division(overlap_total, expected_total),
        "correct_class_incorrect_or_incomplete_evidence_count": correct_class_incorrect_evidence,
        "fully_evidence_grounded_reconciliation_count": fully_grounded,
        "packet_ground_truth_coverage_rate_offline_only": _division(sum(row["packet_ground_truth_coverage"] for row in rows), len(rows)),
    }
    return summary, rows, enriched


_ID_LIKE = re.compile(r"\b[A-Z][A-Z0-9]{1,20}_[A-Z0-9_]+\b")
_AMOUNT = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+\.\d{1,4}(?![A-Za-z0-9_])")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def explanation_faithfulness(
    predictions: list[dict[str, Any]], packet_rows: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    packets = {row["case_id"]: json.loads(row["serialized_packet"]) for row in packet_rows}
    rows = []
    for prediction in predictions:
        case_id = prediction["case_id"]
        reason = str(prediction.get("reason") or "")
        values: set[str] = set()
        id_values: set[str] = set()
        amount_values: set[str] = set()
        date_values: set[str] = set()
        for table_rows in packets[case_id]["records"].values():
            for row in table_rows:
                for key, raw in row.items():
                    value = str(raw)
                    values.add(value)
                    if key.endswith("_id") or key in {"record_id", "journal_id", "source_transaction_id"}:
                        id_values.add(value)
                    if key in {"subtotal", "tax", "shipping", "po_total", "unit_price", "line_amount", "invoice_total", "approval_limit", "payment_amount", "allocated_amount", "debit", "credit", "amount", "opening_balance", "closing_balance", "total_debits", "total_credits"}:
                        amount_values.add(value)
                    if key.endswith("date") or key in {"posting_date", "statement_date"}:
                        date_values.add(value)
        invented_ids = sorted(value for value in set(_ID_LIKE.findall(reason)) if value not in values and value not in {"NO_FAILURE"})
        invented_amounts = sorted(value for value in set(_AMOUNT.findall(reason)) if value not in amount_values)
        invented_dates = sorted(value for value in set(_DATE.findall(reason)) if value not in date_values)
        flags = []
        if invented_ids:
            flags.append("INVENTED_ID_OR_TOKEN")
        if invented_amounts:
            flags.append("INVENTED_AMOUNT")
        if invented_dates:
            flags.append("INVENTED_DATE")
        rows.append({
            "case_id": case_id,
            "invented_ids_or_tokens": "|".join(invented_ids),
            "invented_amounts": "|".join(invented_amounts),
            "invented_dates": "|".join(invented_dates),
            "deterministic_flag_count": len(flags),
            "flags": "|".join(flags),
            "manual_unsupported_assertion_review_required": bool(reason) and prediction.get("parse_status") == "PASS",
        })
    return {
        "cases_with_deterministic_faithfulness_flags": sum(bool(row["flags"]) for row in rows),
        "invented_id_case_count": sum(bool(row["invented_ids_or_tokens"]) for row in rows),
        "invented_amount_case_count": sum(bool(row["invented_amounts"]) for row in rows),
        "invented_date_case_count": sum(bool(row["invented_dates"]) for row in rows),
        "unsupported_assertion_policy": "Deterministic flags are primary; semantic assertions require separate manual review and are not judged solely by another LLM.",
    }, rows


def compare_methods(
    predictions: list[dict[str, Any]], labels: dict[str, str], baseline: list[dict[str, Any]], baseline_name: str
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    direct = {row["case_id"]: _parsed_class(row) for row in predictions}
    other = {row["case_id"]: row.get("predicted_failure_type") for row in baseline}
    rows = []
    counts = Counter()
    for case_id, actual in labels.items():
        direct_correct = direct[case_id] == actual
        other_correct = other[case_id] == actual
        group = (
            f"{baseline_name}_correct_direct_correct" if other_correct and direct_correct else
            f"{baseline_name}_correct_direct_wrong" if other_correct else
            f"{baseline_name}_wrong_direct_correct" if direct_correct else
            f"{baseline_name}_wrong_direct_wrong"
        )
        counts[group] += 1
        actual_binary = actual != "NO_FAILURE"
        direct_binary = None if direct[case_id] == UNRESOLVED else direct[case_id] != "NO_FAILURE"
        other_value = other[case_id]
        other_binary = None if other_value is None else other_value != "NO_FAILURE"
        rows.append({
            "case_id": case_id,
            "actual_failure_type": actual,
            f"{baseline_name}_prediction": other_value,
            "direct_llm_prediction": None if direct[case_id] == UNRESOLVED else direct[case_id],
            f"{baseline_name}_exact_correct": other_correct,
            "direct_llm_exact_correct": direct_correct,
            "exact_partition": group,
            f"{baseline_name}_binary_correct": other_binary == actual_binary,
            "direct_llm_binary_correct": direct_binary == actual_binary,
        })
    return dict(counts), rows


def three_way_intersection(
    predictions: list[dict[str, Any]], labels: dict[str, str], rules: list[dict[str, Any]], ml: list[dict[str, Any]]
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    direct = {row["case_id"]: _parsed_class(row) for row in predictions}
    rules_by = {row["case_id"]: row.get("predicted_failure_type") for row in rules}
    ml_by = {row["case_id"]: row.get("predicted_failure_type") for row in ml}
    names = {
        (True, True, True): "all_three_correct",
        (True, False, False): "only_rules_correct",
        (False, True, False): "only_ml_correct",
        (False, False, True): "only_direct_llm_correct",
        (True, True, False): "rules_and_ml_correct",
        (True, False, True): "rules_and_direct_llm_correct",
        (False, True, True): "ml_and_direct_llm_correct",
        (False, False, False): "all_three_wrong",
    }
    counts = Counter()
    rows = []
    for case_id, actual in labels.items():
        key = (rules_by[case_id] == actual, ml_by[case_id] == actual, direct[case_id] == actual)
        group = names[key]
        counts[group] += 1
        rows.append({
            "case_id": case_id, "actual_failure_type": actual,
            "rules_prediction": rules_by[case_id], "ml_prediction": ml_by[case_id],
            "direct_llm_prediction": None if direct[case_id] == UNRESOLVED else direct[case_id],
            "rules_correct": key[0], "ml_correct": key[1], "direct_llm_correct": key[2],
            "intersection": group,
        })
    return dict(counts), rows


def mcnemar_exact(direct_correct: list[bool], other_correct: list[bool], comparison: str) -> dict[str, Any]:
    other_only = sum(o and not d for d, o in zip(direct_correct, other_correct))
    direct_only = sum(d and not o for d, o in zip(direct_correct, other_correct))
    n = other_only + direct_only
    lower = min(other_only, direct_only)
    probability = min(1.0, 2 * sum(math.comb(n, k) for k in range(lower + 1)) * (0.5 ** n)) if n else 1.0
    return {
        "comparison": comparison,
        "other_only_correct": other_only,
        "direct_llm_only_correct": direct_only,
        "discordant_total": n,
        "two_sided_exact_p_value": probability,
    }


def paired_bootstrap_accuracy_difference(
    direct_correct: list[bool], other_correct: list[bool], comparison: str, repetitions: int = 2000
) -> dict[str, Any]:
    rng = random.Random(314159)
    n = len(direct_correct)
    observed = statistics.mean(direct_correct) - statistics.mean(other_correct)
    samples = []
    for _ in range(repetitions):
        indexes = [rng.randrange(n) for _ in range(n)]
        samples.append(
            statistics.mean(direct_correct[index] for index in indexes)
            - statistics.mean(other_correct[index] for index in indexes)
        )
    return {
        "comparison": comparison,
        "metric": "exact_accuracy_direct_minus_other",
        "observed_difference": observed,
        "repetitions": repetitions,
        "percentile_95_ci": [percentile(samples, 0.025), percentile(samples, 0.975)],
        "seed": 314159,
    }


def operational_reports(predictions: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    latency = [float(row.get("latency_ms", 0)) for row in predictions]
    local = [float(row.get("local_overhead_ms", 0)) for row in predictions if "local_overhead_ms" in row]
    latency_report = {
        "case_count": len(latency),
        "mean_api_latency_ms": statistics.mean(latency) if latency else 0.0,
        "median_api_latency_ms": statistics.median(latency) if latency else 0.0,
        "p95_api_latency_ms": percentile(latency, 0.95),
        "p99_api_latency_ms": percentile(latency, 0.99),
        "minimum_api_latency_ms": min(latency, default=0.0),
        "maximum_api_latency_ms": max(latency, default=0.0),
        "mean_local_overhead_ms_if_recorded": statistics.mean(local) if local else None,
        "sequential_throughput_cases_per_second": _division(1000.0, statistics.mean(latency)) if latency else 0.0,
        "architectural_note": "Remote sequential API latency is not directly equivalent to local Rules/SQL or ML latency.",
    }
    usage_rows = [row.get("usage") or {} for row in predictions]
    input_tokens = [int(row.get("input_tokens", 0) or 0) for row in usage_rows]
    output_tokens = [int(row.get("output_tokens", 0) or 0) for row in usage_rows]
    totals = [left + right for left, right in zip(input_tokens, output_tokens)]
    token_report = {
        "total_input_tokens": sum(input_tokens),
        "total_output_tokens": sum(output_tokens),
        "total_cached_input_tokens": sum(int(row.get("cached_input_tokens", 0) or 0) for row in usage_rows),
        "total_reasoning_tokens": sum(int(row.get("reasoning_tokens", 0) or 0) for row in usage_rows),
        "total_cache_write_tokens": sum(int(row.get("cache_write_tokens", 0) or 0) for row in usage_rows),
        "mean_total_tokens_per_case": statistics.mean(totals) if totals else 0.0,
        "median_total_tokens_per_case": statistics.median(totals) if totals else 0.0,
        "p95_total_tokens_per_case": percentile(totals, 0.95),
    }
    return latency_report, token_report, pricing_report(predictions, BASELINE_CONFIG)


def insufficient_comparison(
    predictions: list[dict[str, Any]], labels: dict[str, str], rules: list[dict[str, Any]],
    ml: list[dict[str, Any]], evidence: dict[str, dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    direct = {row["case_id"]: row for row in predictions}
    rules_by = {row["case_id"]: row for row in rules}
    ml_by = {row["case_id"]: row for row in ml}
    case_ids = [case_id for case_id, row in rules_by.items() if row.get("status") == "INSUFFICIENT_EVIDENCE"]
    rows = []
    for case_id in case_ids:
        direct_class = _parsed_class(direct[case_id])
        correct = direct_class == labels[case_id]
        grounded = bool(evidence[case_id]["fully_evidence_grounded"])
        rows.append({
            "case_id": case_id,
            "ground_truth": labels[case_id],
            "rules_status": rules_by[case_id].get("status"),
            "ml_prediction": ml_by[case_id].get("predicted_failure_type"),
            "ml_correct": ml_by[case_id].get("predicted_failure_type") == labels[case_id],
            "direct_llm_prediction": None if direct_class == UNRESOLVED else direct_class,
            "direct_llm_correct": correct,
            "direct_llm_evidence_valid": evidence[case_id]["evidence_valid"],
            "direct_llm_evidence_contract_correct": evidence[case_id]["evidence_contract_correct"],
            "direct_llm_evidence_complete": evidence[case_id]["evidence_complete"],
            "direct_llm_evidence_grounded_resolution": grounded,
            "direct_llm_abstained": direct[case_id].get("status") == "INSUFFICIENT_EVIDENCE",
        })
    summary = {
        "case_count": len(rows),
        "correctly_classified": sum(row["direct_llm_correct"] for row in rows),
        "evidence_grounded_correctly_resolved": sum(row["direct_llm_evidence_grounded_resolution"] for row in rows),
        "incorrect": sum(not row["direct_llm_correct"] for row in rows),
        "direct_llm_abstained": sum(row["direct_llm_abstained"] for row in rows),
    }
    return summary, rows


def error_analysis(
    predictions: list[dict[str, Any]], labels: dict[str, str], truth: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]], faithfulness: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for prediction in predictions:
        case_id = prediction["case_id"]
        actual = labels[case_id]
        predicted = _parsed_class(prediction)
        if predicted == actual:
            continue
        parse = prediction.get("parse_status")
        if parse in {"PERMANENT_API_ERROR", "TRANSIENT_API_FAILURE_EXHAUSTED"}:
            primary = "TECHNICAL_API_FAILURE"
        elif parse in {"MALFORMED_RESPONSE", "SCHEMA_INVALID_RESPONSE"}:
            primary = "OUTPUT_SCHEMA_FAILURE"
        elif parse == "MODEL_REFUSAL":
            primary = "MODEL_REFUSAL"
        elif parse == "HALLUCINATED_EVIDENCE":
            primary = "HALLUCINATED_EVIDENCE"
        elif prediction.get("status") == "INSUFFICIENT_EVIDENCE":
            primary = "INSUFFICIENT_EVIDENCE_ABSTENTION"
        elif actual == "NO_FAILURE":
            primary = "FALSE_POSITIVE"
        elif predicted == "NO_FAILURE":
            primary = "FALSE_NEGATIVE"
        else:
            primary = "WRONG_FAILURE_CLASS"
        secondary = []
        if not evidence[case_id]["evidence_valid"]:
            secondary.append("HALLUCINATED_EVIDENCE")
        if faithfulness[case_id]["flags"]:
            secondary.append("UNSUPPORTED_EXPLANATION")
        if int(truth[case_id].get("reasoning_hops", 0)) >= 3:
            secondary.append("MULTI_HOP_REASONING_FAILURE")
        rows.append({
            "case_id": case_id,
            "actual_failure_type": actual,
            "predicted_failure_type": None if predicted == UNRESOLVED else predicted,
            "status": prediction.get("status"),
            "primary_category": primary,
            "secondary_categories": "|".join(sorted(set(secondary))),
            "reasoning_hops": truth[case_id].get("reasoning_hops"),
            "difficulty": truth[case_id].get("difficulty"),
            "automated_category_note": "Deterministic output/evidence metadata; deeper semantic causes require manual adjudication.",
        })
    return rows


def evaluate_run(
    *, data_root: Path, run_dir: Path, preflight_dir: Path,
    rules_run_dir: Path, ml_run_dir: Path,
) -> dict[str, Any]:
    # This function is the only Phase 4 path that opens held-out labels.
    labels, truth = load_evaluation_inputs(data_root)
    predictions = load_jsonl(run_dir / "predictions.jsonl")
    if len(predictions) != 439 or {row["case_id"] for row in predictions} != set(labels):
        raise ValueError("predictions must account for exactly the same 439 held-out cases")
    packet_rows = load_jsonl(preflight_dir / "test_packets.jsonl")
    rules = load_jsonl(rules_run_dir / "predictions.jsonl")
    ml = load_jsonl(ml_run_dir / "predictions.jsonl")

    overall, confusion = classification_metrics(predictions, labels)
    failure_rows = per_failure_metrics(predictions, labels)
    evidence_summary, evidence_rows, evidence_by_id = evidence_evaluation(
        predictions, labels, truth, packet_rows
    )
    for prediction in predictions:
        prediction.update({
            "evidence_valid": evidence_by_id[prediction["case_id"]]["evidence_valid"],
            "evidence_contract_correct": evidence_by_id[prediction["case_id"]]["evidence_contract_correct"],
        })
    tier_rows = grouped_metrics(predictions, labels, truth, "tier")
    hop_rows = grouped_metrics(predictions, labels, truth, "hop_count")
    faith_summary, faith_rows = explanation_faithfulness(predictions, packet_rows)
    faith_by_id = {row["case_id"]: row for row in faith_rows}
    rules_summary, rules_rows = compare_methods(predictions, labels, rules, "rules")
    ml_summary, ml_rows = compare_methods(predictions, labels, ml, "ml")
    three_summary, three_rows = three_way_intersection(predictions, labels, rules, ml)
    insufficient_summary, insufficient_rows = insufficient_comparison(
        predictions, labels, rules, ml, evidence_by_id
    )
    errors = error_analysis(predictions, labels, truth, evidence_by_id, faith_by_id)
    latency, tokens, cost = operational_reports(predictions)

    direct_correct = [_parsed_class({row["case_id"]: row for row in predictions}[case_id]) == actual for case_id, actual in labels.items()]
    rules_by = {row["case_id"]: row.get("predicted_failure_type") for row in rules}
    ml_by = {row["case_id"]: row.get("predicted_failure_type") for row in ml}
    rules_correct = [rules_by[case_id] == actual for case_id, actual in labels.items()]
    ml_correct = [ml_by[case_id] == actual for case_id, actual in labels.items()]
    statistics_report = {
        "mcnemar": [
            mcnemar_exact(direct_correct, rules_correct, "direct_llm_vs_rules_sql"),
            mcnemar_exact(direct_correct, ml_correct, "direct_llm_vs_classical_ml"),
        ],
        "paired_bootstrap": [
            paired_bootstrap_accuracy_difference(direct_correct, rules_correct, "direct_llm_vs_rules_sql"),
            paired_bootstrap_accuracy_difference(direct_correct, ml_correct, "direct_llm_vs_classical_ml"),
        ],
    }
    outputs = {
        "metrics.json": overall,
        "evidence_metrics.json": evidence_summary,
        "explanation_faithfulness.json": faith_summary,
        "rules_comparison_summary.json": rules_summary,
        "ml_comparison_summary.json": ml_summary,
        "three_way_summary.json": three_summary,
        "rules_insufficient_summary.json": insufficient_summary,
        "statistical_comparisons.json": statistics_report,
        "latency.json": latency,
        "token_usage.json": tokens,
        "cost_report.json": cost,
    }
    for filename, value in outputs.items():
        write_json(run_dir / filename, value)
    write_csv(run_dir / "confusion_matrix.csv", confusion)
    write_csv(run_dir / "metrics_by_failure_type.csv", failure_rows)
    write_csv(run_dir / "metrics_by_tier.csv", tier_rows)
    write_csv(run_dir / "metrics_by_hop_count.csv", hop_rows)
    write_csv(run_dir / "evidence_analysis.csv", evidence_rows)
    write_csv(run_dir / "explanation_faithfulness.csv", faith_rows)
    write_csv(run_dir / "rules_comparison.csv", rules_rows)
    write_csv(run_dir / "ml_comparison.csv", ml_rows)
    write_csv(run_dir / "three_way_comparison.csv", three_rows)
    write_csv(run_dir / "rules_insufficient_comparison.csv", insufficient_rows)
    write_csv(run_dir / "error_analysis.csv", errors)
    return {
        "overall": overall,
        "per_failure": failure_rows,
        "tier": tier_rows,
        "hop": hop_rows,
        "evidence": evidence_summary,
        "faithfulness": faith_summary,
        "rules_comparison": rules_summary,
        "ml_comparison": ml_summary,
        "three_way": three_summary,
        "rules_insufficient": insufficient_summary,
        "statistics": statistics_report,
        "latency": latency,
        "tokens": tokens,
        "cost": cost,
        "error_count": len(errors),
    }
