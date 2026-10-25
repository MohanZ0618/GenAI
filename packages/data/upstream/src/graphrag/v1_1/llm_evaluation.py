"""Held-out Graph v1.1 LLM evaluation and paired Standard RAG comparison."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import binomtest
from sklearn.metrics import f1_score

from src.rag.artifacts import load_jsonl, sha256_file, write_json, write_jsonl
from src.rag.config import ALL_CLASSES, BOOTSTRAP_SEED
from src.rag.corpus import FrozenCorpus, load_persisted_corpus
from src.rag.evaluation import (
    aggregate_evidence,
    aggregate_retrieval,
    classification_metrics,
    evidence_prediction_metrics,
    retrieval_case_metrics,
)
from src.rag.evidence import resolve_evidence
from src.rag.runner import pricing_report


BOOTSTRAP_RESAMPLES = 10_000


def _latest_rows(path: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in load_jsonl(path):
        case_id = str(row["case_id"])
        if case_id not in latest:
            order.append(case_id)
        latest[case_id] = row
    return [latest[case_id] for case_id in order]


def _prediction_label(row: Mapping[str, Any]) -> str:
    value = row.get("predicted_failure_type")
    if row.get("parse_status", "PASS") == "PASS" and value in ALL_CLASSES:
        return str(value)
    return "__UNRESOLVED__"


def _metric_triplet(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    exact = float(np.mean(actual == predicted))
    macro = float(f1_score(actual, predicted, labels=list(ALL_CLASSES), average="macro", zero_division=0))
    truth_binary = actual != "NO_FAILURE"
    prediction_binary = predicted != "NO_FAILURE"
    prediction_binary[predicted == "__UNRESOLVED__"] = False
    tp = int(np.sum(truth_binary & prediction_binary))
    fp = int(np.sum(~truth_binary & prediction_binary))
    fn = int(np.sum(truth_binary & ~prediction_binary))
    binary = float(2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) else 0.0
    return {"exact_accuracy": exact, "macro_f1": macro, "binary_f1": binary}


def paired_bootstrap(
    case_order: Sequence[str],
    labels: Mapping[str, str],
    graph_by_id: Mapping[str, Mapping[str, Any]],
    standard_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    actual = np.asarray([labels[value] for value in case_order], dtype=object)
    graph = np.asarray([_prediction_label(graph_by_id[value]) for value in case_order], dtype=object)
    standard = np.asarray([_prediction_label(standard_by_id[value]) for value in case_order], dtype=object)
    point_graph = _metric_triplet(actual, graph)
    point_standard = _metric_triplet(actual, standard)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    differences = {key: [] for key in point_graph}
    for _ in range(BOOTSTRAP_RESAMPLES):
        indices = rng.integers(0, len(actual), size=len(actual))
        left = _metric_triplet(actual[indices], graph[indices])
        right = _metric_triplet(actual[indices], standard[indices])
        for key in differences:
            differences[key].append(left[key] - right[key])
    return {
        "seed": BOOTSTRAP_SEED,
        "resamples": BOOTSTRAP_RESAMPLES,
        "difference_direction": "graph_v1_1_minus_standard_rag",
        **{
            key: {
                "graph": point_graph[key],
                "standard_rag": point_standard[key],
                "point_difference": point_graph[key] - point_standard[key],
                "ci95_percentile": [
                    float(np.percentile(values, 2.5)),
                    float(np.percentile(values, 97.5)),
                ],
            }
            for key, values in differences.items()
        },
    }


def paired_classification(
    case_order: Sequence[str],
    labels: Mapping[str, str],
    graph_by_id: Mapping[str, Mapping[str, Any]],
    standard_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    counts: Counter[str] = Counter()
    for case_id in case_order:
        graph_label = _prediction_label(graph_by_id[case_id])
        standard_label = _prediction_label(standard_by_id[case_id])
        actual = labels[case_id]
        graph_correct = graph_label == actual
        standard_correct = standard_label == actual
        partition = (
            "both_correct"
            if graph_correct and standard_correct
            else "graph_only_correct"
            if graph_correct
            else "standard_only_correct"
            if standard_correct
            else "both_wrong"
        )
        counts[partition] += 1
        rows.append({
            "case_id": case_id,
            "actual_failure_type": actual,
            "graph_prediction": graph_label,
            "standard_rag_prediction": standard_label,
            "graph_correct": graph_correct,
            "standard_rag_correct": standard_correct,
            "partition": partition,
        })
    graph_only = counts["graph_only_correct"]
    standard_only = counts["standard_only_correct"]
    discordant = graph_only + standard_only
    p_value = (
        float(binomtest(min(graph_only, standard_only), discordant, 0.5).pvalue)
        if discordant
        else 1.0
    )
    return {
        "case_count": len(rows),
        **dict(sorted(counts.items())),
        "discordant_pairs": discordant,
        "mcnemar_exact_two_sided_p_value": p_value,
    }, rows


def _slice_classification(
    group_ids: Sequence[str],
    labels: Mapping[str, str],
    graph_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not group_ids:
        return None
    local_labels = {case_id: labels[case_id] for case_id in group_ids}
    return classification_metrics([graph_by_id[case_id] for case_id in group_ids], local_labels)


def _case_graph_features(
    retrieval_rows: Sequence[Mapping[str, Any]],
    selected_paths: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    paths: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in selected_paths:
        paths[str(row["case_id"])].append(row)
    result = {}
    for row in retrieval_rows:
        case_id = str(row["case_id"])
        case_paths = paths.get(case_id, [])
        result[case_id] = {
            "anchor_type": str(row["route"]["primary_entity_type"]),
            "anchor_status": str(row["status"]),
            "selected_record_count": len(row.get("selected_record_ids", [])),
            "selected_path_count": len(case_paths),
            "maximum_selected_path_depth": max((int(path["depth"]) for path in case_paths), default=0),
            "relation_ids": sorted({
                str(value) for path in case_paths for value in path["relation_id_sequence"]
            }),
            "selection_classes": sorted({
                str(path["selection_tier_name"]) for path in case_paths
            }),
        }
    return result


def evaluate_complete_run(
    *,
    run_dir: Path,
    standard_run_dir: Path,
    corpus_dir: Path,
    ground_truth_path: Path,
) -> dict[str, Any]:
    """Open held-out gold only after the 439 primary predictions are complete."""

    output = run_dir / "evaluation"
    if output.exists():
        raise FileExistsError(f"evaluation directory already exists: {output}")
    graph_predictions = _latest_rows(run_dir / "generation/primary_predictions.jsonl")
    standard_predictions = _latest_rows(standard_run_dir / "generation/predictions.jsonl")
    retrieval_rows = load_jsonl(run_dir / "retrieval/retrieval_results.jsonl")
    candidate_records = load_jsonl(run_dir / "retrieval/candidate_records.jsonl")
    selected_paths = load_jsonl(run_dir / "retrieval/selected_paths.jsonl")
    dropped_records = [
        row for row in load_jsonl(run_dir / "retrieval/drop_ledger.jsonl")
        if row.get("entry_type") == "RECORD"
    ]
    if not all(len(rows) == 439 for rows in (graph_predictions, standard_predictions, retrieval_rows)):
        raise RuntimeError("held-out evaluation requires exactly 439 cases for both methods")

    corpus = load_persisted_corpus(corpus_dir)
    truth = load_jsonl(ground_truth_path)
    case_order = [str(row["case_id"]) for row in truth]
    labels = {str(row["case_id"]): str(row["failure_type"]) for row in truth}
    graph_by_id = {str(row["case_id"]): row for row in graph_predictions}
    standard_by_id = {str(row["case_id"]): row for row in standard_predictions}
    retrieval_by_id = {str(row["case_id"]): row for row in retrieval_rows}
    graph_anchor_failure_ids = {
        case_id
        for case_id, row in graph_by_id.items()
        if row.get("parse_status") == "ANCHOR_TECHNICAL_FAILURE"
    }

    standard_anchor_failure_ids = {
        case_id
        for case_id, row in standard_by_id.items()
        if row.get("parse_status") == "ANCHOR_TECHNICAL_FAILURE"
    }

    if graph_anchor_failure_ids != standard_anchor_failure_ids:
        raise RuntimeError(
            "Graph and Standard RAG anchor technical-failure populations disagree: "
            f"graph={sorted(graph_anchor_failure_ids)}, "
            f"standard={sorted(standard_anchor_failure_ids)}"
        )

    anchor_technical_failure_ids = graph_anchor_failure_ids

    evidence_case_order = [
        case_id
        for case_id in case_order
        if case_id not in anchor_technical_failure_ids
    ]

    evidence_truth = [
        row
        for row in truth
        if str(row["case_id"]) not in anchor_technical_failure_ids
    ]
    if not (
        len(case_order) == len(set(case_order)) == 439
        and set(case_order) == set(graph_by_id) == set(standard_by_id) == set(retrieval_by_id)
    ):
        raise RuntimeError("held-out truth/prediction/retrieval case universes disagree")

    document_by_id = corpus.by_record_id()
    resolved = {
        str(row["case_id"]): resolve_evidence(row, corpus.documents)
        for row in evidence_truth
    }
    graph_retrieval_metrics = []
    standard_retrieval_metrics = []
    standard_retrieval_by_id = {
        str(row["case_id"]): row
        for row in _latest_rows(standard_run_dir / "retrieval/retrieval_results.jsonl")
    }
    candidate_ids_by_case: dict[str, list[str]] = defaultdict(list)
    for row in candidate_records:
        candidate_ids_by_case[str(row["case_id"])].append(str(row["record_id"]))
    candidate_metrics = {}
    for case_id in evidence_case_order:
        selected_ids = [str(value) for value in retrieval_by_id[case_id].get("selected_record_ids", [])]
        graph_row = retrieval_case_metrics(resolved[case_id], selected_ids, document_by_id)
        graph_retrieval_metrics.append(graph_row)
        candidate_metrics[case_id] = retrieval_case_metrics(
            resolved[case_id], candidate_ids_by_case.get(case_id, []), document_by_id
        )
        standard_retrieval_metrics.append(
            retrieval_case_metrics(
                resolved[case_id],
                [str(value) for value in standard_retrieval_by_id[case_id].get("retrieved_record_ids", [])],
                document_by_id,
            )
        )

    graph_evidence_rows = [
        evidence_prediction_metrics(
            row,
            graph_by_id[str(row["case_id"])],
            resolved[str(row["case_id"])],
            document_by_id,
        )
        for row in evidence_truth
    ]
    graph_evidence_by_id = {row["case_id"]: row for row in graph_evidence_rows}
    graph_retrieval_by_id = {row["case_id"]: row for row in graph_retrieval_metrics}
    standard_retrieval_metric_by_id = {row["case_id"]: row for row in standard_retrieval_metrics}
    drop_ids_by_case: dict[str, set[str]] = defaultdict(set)
    for row in dropped_records:
        drop_ids_by_case[str(row["case_id"])].add(str(row["record_id"]))

    attribution_rows = []
    for case_id in evidence_case_order:
        prediction = graph_by_id[case_id]
        selected = graph_retrieval_by_id[case_id]
        candidate = candidate_metrics[case_id]
        class_correct = _prediction_label(prediction) == labels[case_id]
        technical = prediction.get("parse_status", "PASS") != "PASS"
        selected_sufficient = bool(selected["strict_full_contract_coverage"])
        candidate_sufficient = bool(candidate["strict_full_contract_coverage"])
        missing_required = set(selected["missing_required_record_ids"])
        dropped_missing = sorted(missing_required & drop_ids_by_case.get(case_id, set()))
        if technical:
            category = "TECHNICAL_FAILURE"
        elif class_correct and selected_sufficient:
            category = "SUCCESS_WITH_SUFFICIENT_RETRIEVAL"
        elif class_correct:
            category = "SUCCESS_DESPITE_INCOMPLETE_RETRIEVAL"
        elif selected_sufficient:
            category = "REASONING_FAILURE_GIVEN_SUFFICIENT_RETRIEVAL"
        elif candidate_sufficient:
            category = "EVIDENCE_SELECTION_FAILURE"
        else:
            category = "STRUCTURAL_RETRIEVAL_FAILURE"
        relationship_gap = bool(
            not candidate_sufficient
            and labels[case_id] in {
                "F12_ERP_PAYMENT_MISSING_FROM_BANK",
                "F13_BANK_TRANSACTION_MISSING_FROM_ERP",
                "F14_BANK_ERP_AMOUNT_MISMATCH",
                "F15_INCORRECT_PAYMENT_BANK_MATCH",
            }
        )
        attribution_rows.append({
            "case_id": case_id,
            "actual_failure_type": labels[case_id],
            "graph_prediction": _prediction_label(prediction),
            "class_correct": class_correct,
            "primary_attribution": category,
            "selected_retrieval_sufficient": selected_sufficient,
            "candidate_pool_sufficient": candidate_sufficient,
            "missing_required_record_ids": selected["missing_required_record_ids"],
            "missing_required_records_dropped_by_selector": dropped_missing,
            "known_payment_bank_relationship_gap_applicable": relationship_gap,
            "citation_valid": graph_evidence_by_id[case_id]["citation_valid"],
            "reasoning_failure_given_strong_retrieval": bool(
                not class_correct and selected_sufficient and not technical
            ),
        })

    paired_summary, paired_rows = paired_classification(
        case_order, labels, graph_by_id, standard_by_id
    )
    bootstrap = paired_bootstrap(case_order, labels, graph_by_id, standard_by_id)
    retrieval_pair_rows = []
    retrieval_pair_counts: Counter[str] = Counter()
    recall_deltas = []
    for case_id in evidence_case_order:
        graph_row = graph_retrieval_by_id[case_id]
        standard_row = standard_retrieval_metric_by_id[case_id]
        graph_full = bool(graph_row["strict_full_contract_coverage"])
        standard_full = bool(standard_row["strict_full_contract_coverage"])
        partition = (
            "both_sufficient"
            if graph_full and standard_full
            else "graph_only_sufficient"
            if graph_full
            else "standard_only_sufficient"
            if standard_full
            else "both_insufficient"
        )
        retrieval_pair_counts[partition] += 1
        delta = float(graph_row["document_recall"]) - float(standard_row["document_recall"])
        recall_deltas.append(delta)
        retrieval_pair_rows.append({
            "case_id": case_id,
            "graph_document_recall": graph_row["document_recall"],
            "standard_rag_document_recall": standard_row["document_recall"],
            "document_recall_delta": delta,
            "graph_strict_sufficient": graph_full,
            "standard_rag_strict_sufficient": standard_full,
            "partition": partition,
        })

    features = _case_graph_features(retrieval_rows, selected_paths)
    slice_groups: list[tuple[str, str, list[str]]] = []
    for anchor in ("invoice", "payment", "bank_transaction", "gl_journal"):
        slice_groups.append(("anchor_type", anchor, [
            case_id for case_id in case_order if features[case_id]["anchor_type"] == anchor
        ]))
    for depth in range(0, 4):
        slice_groups.append(("maximum_selected_path_depth", str(depth), [
            case_id
            for case_id in case_order
            if features[case_id]["maximum_selected_path_depth"] == depth
        ]))
    for state in (False, True):
        slice_groups.append(("selected_retrieval_sufficient", str(state).lower(), [
            case_id
            for case_id in evidence_case_order
            if bool(graph_retrieval_by_id[case_id]["strict_full_contract_coverage"]) == state
        ]))
    all_relations = sorted({
        relation
        for value in features.values()
        for relation in value["relation_ids"]
    })
    for relation in all_relations:
        slice_groups.append(("selected_relation_present", relation, [
            case_id
            for case_id in case_order
            if relation in features[case_id]["relation_ids"]
        ]))
    all_path_classes = sorted({
        path_class
        for value in features.values()
        for path_class in value["selection_classes"]
    })
    for path_class in all_path_classes:
        slice_groups.append(("selected_path_class_present", path_class, [
            case_id
            for case_id in case_order
            if path_class in features[case_id]["selection_classes"]
        ]))
    slice_groups.append(("prediction_outcome", "correct", [
        case_id
        for case_id in case_order
        if _prediction_label(graph_by_id[case_id]) == labels[case_id]
    ]))
    slice_groups.append(("prediction_outcome", "incorrect_or_unresolved", [
        case_id
        for case_id in case_order
        if _prediction_label(graph_by_id[case_id]) != labels[case_id]
    ]))
    slice_groups.append(("prediction_status", "insufficient_evidence", [
        case_id
        for case_id in case_order
        if graph_by_id[case_id].get("status") == "INSUFFICIENT_EVIDENCE"
    ]))
    slice_groups.append(("prediction_status", "anchor_technical_failure", [
        case_id
        for case_id in case_order
        if case_id in anchor_technical_failure_ids
    ]))
    slice_rows = [
        {
            "dimension": dimension,
            "group": group,
            "N": len(ids),
            "classification": _slice_classification(ids, labels, graph_by_id),
        }
        for dimension, group, ids in slice_groups
    ]

    graph_classification = classification_metrics(graph_predictions, labels)
    standard_classification = classification_metrics(standard_predictions, labels)
    graph_retrieval_aggregate = aggregate_retrieval(graph_retrieval_metrics)
    standard_retrieval_aggregate = aggregate_retrieval(standard_retrieval_metrics)
    evidence_aggregate = aggregate_evidence(graph_evidence_rows)
    graph_cost = pricing_report(graph_predictions)
    standard_cost = pricing_report(standard_predictions)
    graph_model_latencies = [float(row.get("latency_ms", 0) or 0) for row in graph_predictions]
    standard_model_latencies = [float(row.get("latency_ms", 0) or 0) for row in standard_predictions]
    graph_traversal_telemetry = json.loads(
        (run_dir / "retrieval/traversal_telemetry.json").read_text(encoding="utf-8")
    )
    standard_retrieval_latencies = [
        float(row.get("retrieval_latency_ms", 0) or 0)
        for row in standard_retrieval_by_id.values()
    ]
    graph_context_rows = load_jsonl(run_dir / "inference/reasoning_cases.jsonl")
    standard_context_rows = load_jsonl(standard_run_dir / "generation/reasoning_requests.jsonl")
    efficiency = {
        "graph_model_usage_and_cost": graph_cost,
        "standard_rag_model_usage_and_cost": standard_cost,
        "graph_model_latency_ms": {
            "total": float(sum(graph_model_latencies)),
            "mean_over_439_cases": float(sum(graph_model_latencies) / 439),
            "mean_over_437_model_calls": float(sum(graph_model_latencies) / 437),
        },
        "standard_rag_model_latency_ms": {
            "total": float(sum(standard_model_latencies)),
            "mean_over_439_cases": float(sum(standard_model_latencies) / 439),
            "mean_over_437_model_calls": float(sum(standard_model_latencies) / 437),
        },
        "graph_local_traversal": {
            "total_candidate_generation_latency_ms": graph_traversal_telemetry[
                "total_candidate_generation_latency_ms"
            ],
            "case_count": 437,
        },
        "standard_rag_retrieval": {
            "total_retrieval_latency_ms": float(sum(standard_retrieval_latencies)),
            "case_count": 439,
        },
        "serialized_context_characters": {
            "graph_total": sum(len(str(row["case_payload"])) for row in graph_context_rows),
            "standard_rag_total": sum(len(str(row["case_payload"])) for row in standard_context_rows),
            "graph_case_count": len(graph_context_rows),
            "standard_rag_case_count": len(standard_context_rows),
        },
        "qualification": "Graph traversal and Standard RAG embedding/search latency have different execution components; model token/cost comparison uses the identical provider pricing configuration.",
    }
    summary = {
        "status": "COMPLETE",
        "case_count": 439,
        "evidence_evaluable_case_count": len(evidence_case_order),
        "anchor_technical_failure_case_count": len(anchor_technical_failure_ids),
        "anchor_technical_failure_case_ids": sorted(anchor_technical_failure_ids),
        "graph_classification": graph_classification,
        "standard_rag_classification": standard_classification,
        "graph_retrieval": graph_retrieval_aggregate,
        "standard_rag_retrieval": standard_retrieval_aggregate,
        "graph_evidence": evidence_aggregate,
        "paired_classification": paired_summary,
        "paired_bootstrap": bootstrap,
        "paired_retrieval_partitions": dict(sorted(retrieval_pair_counts.items())),
        "mean_document_recall_delta_graph_minus_standard": float(np.mean(recall_deltas)),
        "failure_attribution": dict(sorted(Counter(
            row["primary_attribution"] for row in attribution_rows
        ).items())),
        "efficiency": efficiency,
        "information_extraction_metrics": {
            "status": "NOT_APPLICABLE",
            "reason": "The frozen task is one multiclass RCA classification with citations; no separate structured-field extraction target is required.",
        },
    }

    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(output / "graph_retrieval_case_metrics.jsonl", graph_retrieval_metrics, exclusive=True)
    write_jsonl(output / "standard_rag_retrieval_case_metrics.jsonl", standard_retrieval_metrics, exclusive=True)
    write_jsonl(output / "graph_evidence_case_metrics.jsonl", graph_evidence_rows, exclusive=True)
    write_jsonl(output / "retrieval_reasoning_attribution.jsonl", attribution_rows, exclusive=True)
    write_jsonl(output / "paired_classification_cases.jsonl", paired_rows, exclusive=True)
    write_jsonl(output / "paired_retrieval_cases.jsonl", retrieval_pair_rows, exclusive=True)
    write_json(output / "classification_metrics_graph.json", graph_classification, exclusive=True)
    write_json(output / "classification_metrics_standard_rag.json", standard_classification, exclusive=True)
    write_json(output / "retrieval_metrics_graph.json", graph_retrieval_aggregate, exclusive=True)
    write_json(output / "retrieval_metrics_standard_rag.json", standard_retrieval_aggregate, exclusive=True)
    write_json(output / "evidence_metrics_graph.json", evidence_aggregate, exclusive=True)
    write_json(output / "paired_comparison.json", {**paired_summary, "bootstrap": bootstrap}, exclusive=True)
    write_json(output / "slice_metrics.json", slice_rows, exclusive=True)
    write_json(output / "efficiency_metrics.json", efficiency, exclusive=True)
    write_json(output / "evaluation_summary.json", summary, exclusive=True)
    write_json(output / "evaluation_manifest.json", {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE",
        "ground_truth_sha256": sha256_file(ground_truth_path),
        "graph_primary_predictions_sha256": sha256_file(
            run_dir / "generation/primary_predictions.jsonl"
        ),
        "standard_rag_predictions_sha256": sha256_file(
            standard_run_dir / "generation/predictions.jsonl"
        ),
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "canonical_case_count": len(case_order),
        "evidence_evaluable_case_count": len(evidence_case_order),
        "anchor_technical_failure_case_count": len(anchor_technical_failure_ids),
        "anchor_technical_failure_case_ids": sorted(anchor_technical_failure_ids),
        "manual_review_used": False,
    }, exclusive=True)
    return summary