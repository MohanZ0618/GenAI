"""Frozen validation retrieval selection and offline RAG evaluation primitives."""

from __future__ import annotations

import csv
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from scipy.stats import binomtest
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from src.rag.artifacts import canonical_json, sha256_bytes
from src.rag.config import (
    ALL_CLASSES, BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, FAILURE_TYPES, K_GRID,
)
from src.rag.corpus import CorpusDocument
from src.rag.evidence import ResolvedEvidence, resolve_evidence, row_identifier_tokens
from src.rag.tokens import conservative_generation_tokens, percentile
from src.rules_sql.registry import RULE_BY_FAILURE


def _division(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def load_ground_truth(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def retrieval_case_metrics(
    evidence: ResolvedEvidence,
    retrieved_ids: Sequence[str],
    document_by_id: dict[str, CorpusDocument],
) -> dict[str, Any]:
    retrieved = list(retrieved_ids)
    retrieved_set = set(retrieved)
    relevant = evidence.required_record_ids & retrieved_set
    covered_ids: set[str] = set()
    covered_tables: set[str] = set()
    for record_id in relevant:
        document = document_by_id[record_id]
        covered_ids.update(evidence.annotated_ids & row_identifier_tokens(document.source_table, document.row))
        covered_tables.add(document.source_table)
    first_rank = next((index for index, record_id in enumerate(retrieved, start=1) if record_id in evidence.required_record_ids), None)
    full = evidence.required_record_ids <= retrieved_set
    observable_satisfied = full and evidence.annotated_ids <= covered_ids and evidence.observable_tables <= covered_tables
    strict = observable_satisfied and not evidence.absence_only_tables
    irrelevant = [record_id for record_id in retrieved if record_id not in evidence.required_record_ids]
    context_characters = sum(len(document_by_id[record_id].text) for record_id in retrieved)
    return {
        "case_id": evidence.case_id,
        "K": len(retrieved),
        "required_annotated_ids": sorted(evidence.annotated_ids),
        "resolved_required_record_ids": sorted(evidence.required_record_ids),
        "retrieved_record_ids": retrieved,
        "relevant_retrieved_record_ids": [record_id for record_id in retrieved if record_id in relevant],
        "covered_annotated_ids": sorted(covered_ids),
        "missing_annotated_ids": sorted(evidence.annotated_ids - covered_ids),
        "missing_required_record_ids": sorted(evidence.required_record_ids - retrieved_set),
        "irrelevant_record_ids": irrelevant,
        "required_tables": sorted(evidence.required_tables),
        "observable_tables": sorted(evidence.observable_tables),
        "covered_observable_tables": sorted(covered_tables),
        "absence_only_tables": sorted(evidence.absence_only_tables),
        "document_recall": _division(len(relevant), len(evidence.required_record_ids)),
        "document_precision": _division(len(relevant), len(retrieved)),
        "hit": bool(relevant),
        "full_evidence_coverage": full,
        "evidence_id_recall": _division(len(covered_ids), len(evidence.annotated_ids)),
        "observable_table_coverage": _division(len(covered_tables), len(evidence.observable_tables)),
        "observable_contract_satisfied": observable_satisfied,
        "strict_full_contract_coverage": strict,
        "mrr": _division(1, first_rank or 0),
        "irrelevant_record_count": len(irrelevant),
        "retrieval_set_size": len(retrieved),
        "retrieved_context_characters": context_characters,
        "retrieved_context_tokens": conservative_generation_tokens("x" * context_characters),
    }


def _bootstrap_mean(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"lower_95": 0.0, "upper_95": 0.0}
    generator = random.Random(BOOTSTRAP_SEED)
    samples = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        samples.append(statistics.fmean(values[generator.randrange(len(values))] for _ in values))
    return {"lower_95": percentile(samples, 0.025), "upper_95": percentile(samples, 0.975)}


def aggregate_retrieval(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    metrics = (
        "document_recall", "document_precision", "hit", "full_evidence_coverage",
        "evidence_id_recall", "observable_table_coverage", "observable_contract_satisfied",
        "strict_full_contract_coverage", "mrr", "irrelevant_record_count", "retrieval_set_size",
        "retrieved_context_tokens",
    )
    macro: dict[str, Any] = {}
    for metric in metrics:
        values = [float(row[metric]) for row in rows]
        macro[metric] = statistics.fmean(values) if values else 0.0
        if metric in {"document_recall", "document_precision", "full_evidence_coverage", "strict_full_contract_coverage"}:
            macro[f"{metric}_ci"] = _bootstrap_mean(values)
    relevant = sum(len(row["relevant_retrieved_record_ids"]) for row in rows)
    required = sum(len(row["resolved_required_record_ids"]) for row in rows)
    retrieved = sum(row["retrieval_set_size"] for row in rows)
    return {
        "case_count": len(rows),
        "K": rows[0]["K"] if rows else None,
        "macro": macro,
        "micro": {
            "document_recall": _division(relevant, required),
            "document_precision": _division(relevant, retrieved),
            "relevant_documents": relevant,
            "required_documents": required,
            "retrieved_documents": retrieved,
        },
    }


def evaluate_k_grid(
    truth: Sequence[dict[str, Any]],
    retrieval_rows: Sequence[dict[str, Any]],
    documents: Sequence[CorpusDocument],
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, dict[str, Any]]]:
    truth_by_id = {str(row["case_id"]): row for row in truth}
    retrieval_by_id = {str(row["case_id"]): row for row in retrieval_rows}
    if set(truth_by_id) != set(retrieval_by_id):
        raise RuntimeError("validation truth and saved retrieval case IDs disagree")
    document_by_id = {document.record_id: document for document in documents}
    resolved = {case_id: resolve_evidence(case, documents) for case_id, case in truth_by_id.items()}
    per_k: dict[int, list[dict[str, Any]]] = {}
    aggregates: dict[int, dict[str, Any]] = {}
    for k in K_GRID:
        rows = []
        for case_id in truth_by_id:
            ranked = retrieval_by_id[case_id]["retrieved_record_ids"]
            if len(ranked) < max(K_GRID):
                raise RuntimeError(f"saved validation retrieval is not K=40: {case_id}")
            rows.append(retrieval_case_metrics(resolved[case_id], ranked[:k], document_by_id))
        per_k[k] = rows
        aggregates[k] = aggregate_retrieval(rows)
    return per_k, aggregates


def select_k(aggregates: dict[int, dict[str, Any]], retrieval_manifest_sha256: str) -> dict[str, Any]:
    def key(k: int) -> tuple[float, float, float, float, float, int]:
        macro = aggregates[k]["macro"]
        return (
            -float(macro["document_recall"]),
            -float(macro["strict_full_contract_coverage"]),
            -float(macro["observable_table_coverage"]),
            float(macro["irrelevant_record_count"]),
            float(macro["retrieved_context_tokens"]),
            k,
        )
    ordered = sorted(K_GRID, key=key)
    selected = ordered[0]
    result = {
        "candidate_k_values": list(K_GRID),
        "unrounded_results": {str(k): aggregates[k] for k in K_GRID},
        "selected_k": selected,
        "selection_hierarchy": [
            "max macro document_recall", "max strict_full_contract_coverage",
            "max observable_table_coverage", "min irrelevant_record_count",
            "min retrieved_context_tokens", "min K",
        ],
        "candidate_order": ordered,
        "selection_reason": f"K={selected} is lexicographically first under the frozen six-level hierarchy",
        "retrieval_manifest_sha256": retrieval_manifest_sha256,
    }
    result["selection_content_sha256"] = sha256_bytes(canonical_json(result))
    return result


def classification_metrics(predictions: Sequence[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any]:
    by_id = {str(row["case_id"]): row for row in predictions}
    if set(by_id) != set(labels):
        raise RuntimeError("prediction/label case IDs disagree")
    actual = [labels[case_id] for case_id in labels]
    predicted: list[str] = []
    for case_id in labels:
        row = by_id[case_id]
        value = row.get("predicted_failure_type")
        predicted.append(str(value) if row.get("parse_status", "PASS") == "PASS" and value in ALL_CLASSES else "__UNRESOLVED__")
    macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(actual, predicted, labels=list(ALL_CLASSES), average="macro", zero_division=0)
    # In single-label multiclass scoring, strict micro F1 equals strict accuracy when
    # unresolved outcomes are retained as wrong rather than dropped.
    micro_f1 = _division(sum(a == p for a, p in zip(actual, predicted)), len(actual))
    _, _, weighted_f1, _ = precision_recall_fscore_support(actual, predicted, labels=list(ALL_CLASSES), average="weighted", zero_division=0)
    per_p, per_r, per_f1, support = precision_recall_fscore_support(
        actual, predicted, labels=list(ALL_CLASSES), average=None, zero_division=0
    )
    cm_labels = [*ALL_CLASSES, "__UNRESOLVED__"]
    matrix = confusion_matrix(actual, predicted, labels=cm_labels)
    actual_binary = [value != "NO_FAILURE" for value in actual]
    predicted_binary = [None if value == "__UNRESOLVED__" else value != "NO_FAILURE" for value in predicted]
    tp = sum(a and p is True for a, p in zip(actual_binary, predicted_binary))
    tn = sum(not a and p is False for a, p in zip(actual_binary, predicted_binary))
    fp = sum(not a and p is True for a, p in zip(actual_binary, predicted_binary))
    fn = sum(a and p is not True for a, p in zip(actual_binary, predicted_binary))
    precision, recall = _division(tp, tp + fp), _division(tp, tp + fn)
    accuracy_values = [float(a == p) for a, p in zip(actual, predicted)]
    per_class = {}
    for index, label in enumerate(ALL_CLASSES):
        tp_class = int(matrix[index, index])
        fp_class = int(matrix[:, index].sum() - tp_class)
        fn_class = int(matrix[index, :].sum() - tp_class)
        per_class[label] = {
            "precision": float(per_p[index]), "recall": float(per_r[index]),
            "f1": float(per_f1[index]), "support": int(support[index]),
            "tp": tp_class, "fp": fp_class, "fn": fn_class,
        }
    technical = Counter(
        str(row.get("parse_status", "PASS")) for row in predictions
        if row.get("parse_status", "PASS") != "PASS"
    )
    result = {
        "total_cases": len(actual),
        "exact_16_class_accuracy": micro_f1,
        "exact_16_class_accuracy_ci": _bootstrap_mean(accuracy_values),
        "binary_accuracy_strict": _division(tp + tn, len(actual)),
        "binary_precision": precision, "binary_recall": recall,
        "binary_f1": _division(2 * precision * recall, precision + recall),
        "macro_precision_16_classes": macro_p, "macro_recall_16_classes": macro_r,
        "macro_f1_16_classes": macro_f1, "micro_f1_16_classes": micro_f1,
        "weighted_f1_16_classes": weighted_f1,
        "false_positive_rate": _division(fp, sum(not value for value in actual_binary)),
        "false_negative_rate": _division(fn, sum(actual_binary)),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "insufficient_evidence_count": sum(row.get("status") == "INSUFFICIENT_EVIDENCE" for row in predictions),
        "insufficient_evidence_rate": _division(sum(row.get("status") == "INSUFFICIENT_EVIDENCE" for row in predictions), len(actual)),
        "technical_failure_count": sum(row.get("parse_status", "PASS") != "PASS" for row in predictions),
        "technical_failure_rate": _division(sum(row.get("parse_status", "PASS") != "PASS" for row in predictions), len(actual)),
        "technical_outcomes": dict(sorted(technical.items())),
        "per_class": per_class,
        "confusion_matrix": {
            "actual_labels": list(ALL_CLASSES),
            "predicted_labels": cm_labels,
            "rows": matrix[:len(ALL_CLASSES), :].tolist(),
        },
    }
    return result


def evidence_prediction_metrics(
    truth: dict[str, Any],
    prediction: dict[str, Any],
    evidence: ResolvedEvidence,
    document_by_id: dict[str, CorpusDocument],
    *,
    adjudication: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic citation/contract checks plus optional two-reviewer judgments."""
    retrieved = [str(value) for value in prediction.get("retrieved_record_ids", [])]
    cited = [str(value) for value in prediction.get("evidence_record_ids", [])]
    nonretrieved = sorted(set(cited) - set(retrieved))
    nonexistent = sorted(set(cited) - set(document_by_id))
    citation_valid = not nonretrieved and not nonexistent and prediction.get("parse_status", "PASS") != "NONRETRIEVED_EVIDENCE"
    covered_ids: set[str] = set()
    covered_tables: set[str] = set()
    for record_id in cited:
        document = document_by_id.get(record_id)
        if document is None or document.source_table not in evidence.required_tables:
            continue
        covered_ids.update(evidence.annotated_ids & row_identifier_tokens(document.source_table, document.row))
        covered_tables.add(document.source_table)
    annotated_complete = evidence.annotated_ids <= covered_ids
    documents_complete = evidence.required_record_ids <= set(cited)
    observable = annotated_complete and evidence.observable_tables <= covered_tables
    strict = observable and not evidence.absence_only_tables
    class_correct = (
        prediction.get("parse_status", "PASS") == "PASS"
        and prediction.get("predicted_failure_type") == truth.get("failure_type")
    )
    citation_support: bool | None = None
    unsupported_explanation: bool | None = None
    if adjudication is not None:
        citation_support = bool(adjudication["citation_support"])
        unsupported_explanation = bool(adjudication["unsupported_explanation"])
    nonabstaining = prediction.get("status") in {"MATCH", "ANOMALY"}
    fully_grounded = None if citation_support is None else bool(
        class_correct and nonabstaining and citation_valid and citation_support
        and annotated_complete and documents_complete and strict and not unsupported_explanation
    )
    return {
        "case_id": str(truth["case_id"]),
        "actual_failure_type": str(truth["failure_type"]),
        "class_correct": class_correct,
        "nonabstaining": nonabstaining,
        "cited_record_ids": cited,
        "nonretrieved_citations": nonretrieved,
        "nonexistent_citations": nonexistent,
        "citation_valid": citation_valid,
        "citation_support": citation_support,
        "citation_support_review_status": "TWO_REVIEWER_COMPLETE" if adjudication is not None else "PENDING_TWO_REVIEWER_ADJUDICATION",
        "covered_annotated_ids": sorted(covered_ids),
        "annotated_id_completeness": annotated_complete,
        "resolved_document_completeness": documents_complete,
        "covered_observable_tables": sorted(covered_tables),
        "observable_evidence_contract_accuracy": observable,
        "strict_evidence_contract_accuracy": strict,
        "absence_only_tables": sorted(evidence.absence_only_tables),
        "hallucinated_evidence": bool(nonretrieved or nonexistent or prediction.get("parse_status") == "NONRETRIEVED_EVIDENCE"),
        "correct_class_incorrect_or_incomplete_evidence": bool(class_correct and not (citation_valid and documents_complete and strict)),
        "unsupported_explanation": unsupported_explanation,
        "fully_grounded_reconciliation": fully_grounded,
        "observable_grounded_reconciliation": None if citation_support is None else bool(
            class_correct and nonabstaining and citation_valid and citation_support and observable
            and not unsupported_explanation
        ),
    }


def aggregate_evidence(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    rate = lambda key: _division(sum(bool(row[key]) for row in rows), count)
    reviewed = [row for row in rows if row["citation_support"] is not None]
    return {
        "case_count": count,
        "citation_validity": rate("citation_valid"),
        "annotated_id_completeness": rate("annotated_id_completeness"),
        "resolved_document_completeness": rate("resolved_document_completeness"),
        "observable_evidence_contract_accuracy": rate("observable_evidence_contract_accuracy"),
        "strict_evidence_contract_accuracy": rate("strict_evidence_contract_accuracy"),
        "hallucinated_evidence_rate": rate("hallucinated_evidence"),
        "correct_class_incorrect_or_incomplete_evidence_rate": rate("correct_class_incorrect_or_incomplete_evidence"),
        "two_reviewer_adjudicated_cases": len(reviewed),
        "citation_support_rate": _division(sum(bool(row["citation_support"]) for row in reviewed), len(reviewed)) if reviewed else None,
        "explanation_unsupported_assertion_rate": _division(sum(bool(row["unsupported_explanation"]) for row in reviewed), len(reviewed)) if reviewed else None,
        "fully_grounded_reconciliation_rate": _division(sum(bool(row["fully_grounded_reconciliation"]) for row in reviewed), len(reviewed)) if reviewed else None,
        "observable_grounded_reconciliation_rate": _division(sum(bool(row["observable_grounded_reconciliation"]) for row in reviewed), len(reviewed)) if reviewed else None,
        "manual_review_status": "COMPLETE" if len(reviewed) == count else "PENDING",
    }


def attribute_failure(
    truth: dict[str, Any],
    prediction: dict[str, Any],
    retrieval: dict[str, Any],
    evidence_metrics: dict[str, Any],
    oracle_prediction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply the frozen high-level precedence without post-hoc retaxonomizing."""
    technical = prediction.get("parse_status", "PASS") != "PASS"
    class_correct = bool(evidence_metrics["class_correct"])
    complete = bool(retrieval["strict_full_contract_coverage"])
    oracle_available = oracle_prediction is not None and oracle_prediction.get("parse_status", "PASS") == "PASS"
    oracle_correct = bool(
        oracle_available and oracle_prediction.get("predicted_failure_type") == truth.get("failure_type")
    )
    if technical:
        category = "TECHNICAL_FAILURE"
        unresolved = False
    elif class_correct and not (
        evidence_metrics["citation_valid"] and evidence_metrics["strict_evidence_contract_accuracy"]
    ):
        category = "EVIDENCE_CITATION_FAILURE"
        unresolved = False
    elif class_correct:
        category = "NO_FAILURE"
        unresolved = False
    elif complete:
        category = "REASONING_FAILURE"
        unresolved = False
    elif oracle_available and not oracle_correct:
        category = "MIXED_FAILURE"
        unresolved = False
    else:
        category = "RETRIEVAL_FAILURE"
        unresolved = not oracle_available
    return {
        "case_id": str(truth["case_id"]), "attribution": category,
        "attribution_unresolved": unresolved,
        "primary_class_correct": class_correct,
        "strict_retrieval_contract_satisfied": complete,
        "citation_valid": evidence_metrics["citation_valid"],
        "oracle_available": oracle_available, "oracle_correct": oracle_correct if oracle_available else None,
    }


def paired_comparison(
    rag_predictions: Sequence[dict[str, Any]],
    other_predictions: Sequence[dict[str, Any]],
    labels: dict[str, str],
    other_name: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    counts, rows = paired_correctness(rag_predictions, other_predictions, labels, other_name)
    rag_only = counts.get("rag_only", 0)
    other_only = counts.get(f"{other_name}_only", 0)
    discordant = rag_only + other_only
    p_value = float(binomtest(min(rag_only, other_only), discordant, 0.5).pvalue) if discordant else 1.0
    gaps = [float(row["rag_correct"]) - float(row[f"{other_name}_correct"]) for row in rows]
    return {
        "other_method": other_name, "case_count": len(rows), **counts,
        "paired_accuracy_gap_rag_minus_other": statistics.fmean(gaps) if gaps else 0.0,
        "paired_accuracy_gap_ci": _bootstrap_mean(gaps),
        "mcnemar_exact_two_sided_p_value": p_value,
        "discordant_pairs": discordant,
    }, rows


def stratified_results(
    truth: Sequence[dict[str, Any]],
    predictions: Sequence[dict[str, Any]],
    retrieval_rows: Sequence[dict[str, Any]],
    evidence_rows: Sequence[dict[str, Any]],
    rules_insufficient_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Report every frozen class/tier/hop/anchor/subset bin, including empty bins."""
    truth_by_id = {str(row["case_id"]): row for row in truth}
    prediction_by_id = {str(row["case_id"]): row for row in predictions}
    retrieval_by_id = {str(row["case_id"]): row for row in retrieval_rows}
    evidence_by_id = {str(row["case_id"]): row for row in evidence_rows}
    all_ids = set(truth_by_id)
    if not (all_ids == set(prediction_by_id) == set(retrieval_by_id) == set(evidence_by_id)):
        raise RuntimeError("stratified input case IDs disagree")

    groups: list[tuple[str, str, set[str]]] = [("overall", "ALL", all_ids)]
    for label in ALL_CLASSES:
        groups.append(("failure_class", label, {case_id for case_id, row in truth_by_id.items() if row["failure_type"] == label}))
    for tier in (1, 2, 3):
        groups.append(("tier", str(tier), {
            case_id for case_id, row in truth_by_id.items()
            if row["failure_type"] != "NO_FAILURE" and RULE_BY_FAILURE[row["failure_type"]].tier == tier
        }))
    for hop in range(0, 6):
        groups.append(("exact_reasoning_hop", str(hop), {
            case_id for case_id, row in truth_by_id.items() if int(row.get("reasoning_hops", -1)) == hop
        }))
    for anchor in ("invoice", "payment", "bank_transaction", "gl_journal"):
        groups.append(("primary_anchor_type", anchor, {
            case_id for case_id, row in truth_by_id.items()
            if str(row.get("primary_entity", {}).get("type")) == anchor
        }))
    groups.append(("predefined_subset", "rules_sql_insufficient_50", rules_insufficient_ids or set()))

    output = []
    for dimension, group, ids in groups:
        ordered_ids = [case_id for case_id in truth_by_id if case_id in ids]
        if not ordered_ids:
            output.append({"dimension": dimension, "group": group, "N": 0, "classification": None, "retrieval": None, "evidence": None})
            continue
        labels = {case_id: str(truth_by_id[case_id]["failure_type"]) for case_id in ordered_ids}
        output.append({
            "dimension": dimension, "group": group, "N": len(ordered_ids),
            "classification": classification_metrics([prediction_by_id[value] for value in ordered_ids], labels),
            "retrieval": aggregate_retrieval([retrieval_by_id[value] for value in ordered_ids]),
            "evidence": aggregate_evidence([evidence_by_id[value] for value in ordered_ids]),
        })
    return output


def paired_correctness(
    rag_predictions: Sequence[dict[str, Any]], other_predictions: Sequence[dict[str, Any]], labels: dict[str, str], other_name: str
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    rag = {row["case_id"]: row for row in rag_predictions}
    other = {row["case_id"]: row for row in other_predictions}
    if set(rag) != set(labels) or set(other) != set(labels):
        raise RuntimeError(f"{other_name}/RAG comparison case IDs disagree")
    counts = Counter()
    rows = []
    for case_id, actual in labels.items():
        rag_correct = rag[case_id].get("predicted_failure_type") == actual and rag[case_id].get("parse_status", "PASS") == "PASS"
        other_correct = other[case_id].get("predicted_failure_type") == actual
        category = "both_correct" if rag_correct and other_correct else f"{other_name}_only" if other_correct else "rag_only" if rag_correct else "both_wrong"
        counts[category] += 1
        rows.append({"case_id": case_id, "actual_failure_type": actual, "rag_correct": rag_correct, f"{other_name}_correct": other_correct, "partition": category})
    return dict(counts), rows
