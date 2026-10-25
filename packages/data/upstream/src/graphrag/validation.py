"""Evaluation-only validation evidence scoring, isolated from retrieval code."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.rag.corpus import CorpusDocument
from src.rag.evaluation import _bootstrap_mean, aggregate_retrieval, retrieval_case_metrics
from src.rag.evidence import ResolvedEvidence, resolve_evidence
from src.rag.tokens import percentile

from .graph_types import GraphSnapshot


SYSTEM_ORDER = ("standard_dense_rag", "anchor_rag", "relational_rag", "graph_retrieval_v1_0")


def load_validation_evidence_projection(path: Path) -> list[dict[str, Any]]:
    """Open authorized validation gold and retain only the evidence contract projection."""
    projected: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            source = json.loads(line)
            projected.append({
                "case_id": str(source["case_id"]),
                "evidence_ids": [str(value) for value in source.get("evidence_ids", [])],
                "evidence_required": [str(value) for value in source.get("evidence_required", [])],
            })
            del source
    if len(projected) != 416 or len({row["case_id"] for row in projected}) != 416:
        raise RuntimeError("authorized validation evidence projection is not 416 unique cases")
    return projected


def _token_distribution(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {key: 0.0 for key in ("median", "p75", "p90", "p95", "p99", "max")}
    return {
        "median": statistics.median(values),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


def _anchor_inclusion(results: dict[str, list[str]], resolutions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        case_id for case_id in results
        if resolutions[case_id]["resolution_status"] in {"EXACT_SINGLE", "EXACT_MULTI"}
    ]
    included = [case_id for case_id in eligible if set(resolutions[case_id]["resolved_record_ids"]) <= set(results[case_id])]
    first_ranks = []
    all_anchor_ranks = []
    for case_id in included:
        ranks = [results[case_id].index(record_id) + 1 for record_id in resolutions[case_id]["resolved_record_ids"]]
        first_ranks.append(min(ranks))
        all_anchor_ranks.extend(ranks)
    return {
        "eligible_case_count": len(eligible),
        "included_case_count": len(included),
        "rate": len(included) / len(eligible) if eligible else 0.0,
        "first_anchor_rank_mean": statistics.fmean(first_ranks) if first_ranks else None,
        "first_anchor_rank_median": statistics.median(first_ranks) if first_ranks else None,
        "maximum_anchor_rank": max(all_anchor_ranks, default=None),
    }


def _coverage_distribution(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["document_recall"]) for row in rows]
    buckets = Counter(
        "0_percent" if value == 0
        else "greater_than_0_less_than_50_percent" if value < 0.5
        else "at_least_50_less_than_100_percent" if value < 1.0
        else "100_percent"
        for value in values
    )
    return {
        "buckets": {key: buckets.get(key, 0) for key in (
            "0_percent", "greater_than_0_less_than_50_percent",
            "at_least_50_less_than_100_percent", "100_percent",
        )},
        "mean": statistics.fmean(values) if values else 0.0,
        "median": statistics.median(values) if values else 0.0,
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
    }


def _aggregate(rows: list[dict[str, Any]], result_ids: dict[str, list[str]], resolutions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    value = aggregate_retrieval(rows)
    value["K_cap"] = 40
    value["macro"]["hit_ci"] = _bootstrap_mean([float(row["hit"]) for row in rows])
    value["anchor_inclusion"] = _anchor_inclusion(result_ids, resolutions)
    value["context_token_distribution"] = _token_distribution([float(row["retrieved_context_tokens"]) for row in rows])
    value["average_record_count"] = statistics.fmean(row["retrieval_set_size"] for row in rows) if rows else 0.0
    value["average_source_tokens"] = statistics.fmean(row["retrieved_context_tokens"] for row in rows) if rows else 0.0
    value["required_evidence_coverage_distribution"] = _coverage_distribution(rows)
    return value


def _hubness(
    system_results: dict[str, dict[str, list[str]]], routes: dict[str, dict[str, str]],
    resolutions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    def summarize(by_case: dict[str, list[str]]) -> dict[str, Any]:
        cases = sorted(by_case)
        frequency = Counter(record_id for values in by_case.values() for record_id in set(values))
        non_anchor_frequency = Counter(
            record_id for case_id, values in by_case.items() for record_id in set(values)
            if record_id not in set(resolutions[case_id]["resolved_record_ids"])
        )
        intersections = 0.0
        pairs = 0
        for left_index, left_case in enumerate(cases):
            left = set(by_case[left_case])
            for right_case in cases[left_index + 1:]:
                right = set(by_case[right_case])
                union = left | right
                intersections += len(left & right) / len(union) if union else 0.0
                pairs += 1
        total_slots = sum(len(values) for values in by_case.values())
        return {
            "case_pair_count": pairs,
            "mean_pairwise_jaccard": intersections / pairs if pairs else 0.0,
            "maximum_case_frequency": max(frequency.values(), default=0),
            "maximum_case_frequency_rate": max(frequency.values(), default=0) / len(cases) if cases else 0.0,
            "maximum_non_anchor_record_frequency": max(non_anchor_frequency.values(), default=0),
            "maximum_non_anchor_record_frequency_rate": max(non_anchor_frequency.values(), default=0) / len(cases) if cases else 0.0,
            "top_20_records": [
                {"record_id": record_id, "case_count": count, "case_percentage": 100.0 * count / len(cases) if cases else 0.0}
                for record_id, count in frequency.most_common(20)
            ],
            "top_20_slot_share": sum(value for _, value in frequency.most_common(20)) / total_slots if total_slots else 0.0,
        }
    output: dict[str, Any] = {}
    for system, by_case in system_results.items():
        output[system] = summarize(by_case)
        output[system]["by_anchor_type"] = {
            anchor_type: summarize({case_id: values for case_id, values in by_case.items() if routes[case_id]["primary_entity_type"] == anchor_type})
            for anchor_type in sorted({routes[case_id]["primary_entity_type"] for case_id in by_case})
        }
    return output


def _context_diagnostics(
    system_results: dict[str, dict[str, list[str]]], documents: dict[str, CorpusDocument],
    routes: dict[str, dict[str, str]], resolutions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {}
    for system, by_case in system_results.items():
        counts = [len(value) for value in by_case.values()]
        tokens = [float((sum(len(documents[record_id].text) for record_id in value) + 2) // 3) for value in by_case.values()]
        type_diversity = [len({documents[record_id].record_type for record_id in value}) for value in by_case.values()]
        output[system] = {
            "record_count": _token_distribution([float(value) for value in counts]),
            "source_tokens": _token_distribution(tokens),
            "average_record_count": statistics.fmean(counts) if counts else 0.0,
            "average_source_tokens": statistics.fmean(tokens) if tokens else 0.0,
            "average_distinct_node_types": statistics.fmean(type_diversity) if type_diversity else 0.0,
            "distinct_node_type_distribution": dict(sorted(Counter(type_diversity).items())),
            "by_anchor_type": {},
        }
        for anchor_type in sorted({routes[case_id]["primary_entity_type"] for case_id in by_case}):
            ids = [case_id for case_id in by_case if routes[case_id]["primary_entity_type"] == anchor_type]
            type_counts = [len({documents[value].record_type for value in by_case[case_id]}) for case_id in ids]
            token_counts = [float((sum(len(documents[value].text) for value in by_case[case_id]) + 2) // 3) for case_id in ids]
            cross_type = []
            for case_id in ids:
                anchor_types = set(resolutions[case_id]["resolved_node_types"])
                values = by_case[case_id]
                cross_type.append(sum(documents[value].record_type not in anchor_types for value in values) / len(values) if values else 0.0)
            output[system]["by_anchor_type"][anchor_type] = {
                "case_count": len(ids),
                "source_tokens": _token_distribution(token_counts),
                "distinct_record_types_mean": statistics.fmean(type_counts) if type_counts else 0.0,
                "distinct_record_types_median": statistics.median(type_counts) if type_counts else 0.0,
                "distinct_record_types_p95": percentile([float(value) for value in type_counts], 0.95),
                "cross_type_record_fraction_mean": statistics.fmean(cross_type) if cross_type else 0.0,
            }
    return output


def _retrieval_composition(
    system_results: dict[str, dict[str, list[str]]], documents: dict[str, CorpusDocument],
    routes: dict[str, dict[str, str]], resolutions: dict[str, dict[str, Any]],
    graph_results: Sequence[dict[str, Any]], path_ledger: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for system, by_case in system_results.items():
        counts = Counter(documents[record_id].record_type for values in by_case.values() for record_id in values)
        distinct = [len({documents[record_id].record_type for record_id in values}) for values in by_case.values()]
        cross = []
        for case_id, values in by_case.items():
            anchor_types = set(resolutions[case_id]["resolved_node_types"])
            cross.append(sum(documents[value].record_type not in anchor_types for value in values) / len(values) if values else 0.0)
        output[system] = {
            "record_count_by_type": dict(sorted(counts.items())),
            "average_record_count_by_type": {key: value / len(by_case) for key, value in sorted(counts.items())},
            "distinct_record_types_in_top40": {
                "mean": statistics.fmean(distinct) if distinct else 0.0,
                "median": statistics.median(distinct) if distinct else 0.0,
                "p95": percentile([float(value) for value in distinct], 0.95),
            },
            "cross_type_record_fraction_mean": statistics.fmean(cross) if cross else 0.0,
            "by_anchor_type": {},
        }
        for anchor_type in sorted({routes[case_id]["primary_entity_type"] for case_id in by_case}):
            ids = [case_id for case_id in by_case if routes[case_id]["primary_entity_type"] == anchor_type]
            per_type = Counter(documents[value].record_type for case_id in ids for value in by_case[case_id])
            output[system]["by_anchor_type"][anchor_type] = {
                "case_count": len(ids),
                "record_count_by_type": dict(sorted(per_type.items())),
            }
    selected_paths = [row for row in path_ledger if row["selected"]]
    graph_case_count = len(graph_results)
    output["graph_retrieval_v1_0"]["path_composition"] = {
        "candidate_path_count": len(path_ledger),
        "selected_path_count": len(selected_paths),
        "average_candidate_paths": len(path_ledger) / graph_case_count if graph_case_count else 0.0,
        "average_motifs_executed": statistics.fmean(len(row["executed_motif_ids"]) for row in graph_results) if graph_results else 0.0,
        "average_selected_paths": len(selected_paths) / graph_case_count if graph_case_count else 0.0,
        "average_selected_path_length": statistics.fmean(row["path_length"] for row in selected_paths) if selected_paths else 0.0,
        "selected_direct_path_count": sum(row["path_length"] == 1 for row in selected_paths),
        "selected_multihop_path_count": sum(row["path_length"] > 1 for row in selected_paths),
        "selected_record_attributions_direct_paths": sum(len(set(row["records"])) for row in selected_paths if row["path_length"] == 1),
        "selected_record_attributions_multihop_paths": sum(len(set(row["records"])) for row in selected_paths if row["path_length"] > 1),
        "path_count_by_motif": dict(sorted(Counter(row["motif_id"] for row in path_ledger).items())),
    }
    return output


def evaluate(
    *, evidence_projection: Sequence[dict[str, Any]], routes: Sequence[dict[str, str]],
    documents: Sequence[CorpusDocument], snapshot: GraphSnapshot,
    resolutions: Sequence[dict[str, Any]], graph_results: Sequence[dict[str, Any]],
    path_ledger: Sequence[dict[str, Any]], standard_rows: Sequence[dict[str, Any]],
    anchor_rows: Sequence[dict[str, Any]], relational_rows: Sequence[dict[str, Any]],
    latency_rows: Sequence[dict[str, Any]], frozen_motifs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    document_by_id = {document.record_id: document for document in documents}
    route_by_id = {row["case_id"]: row for row in routes}
    truth_by_id = {row["case_id"]: row for row in evidence_projection}
    if set(route_by_id) != set(truth_by_id):
        raise RuntimeError("validation routes/evidence projection case IDs disagree")
    resolution_by_id = {row["case_id"]: row for row in resolutions}
    graph_by_id = {row["case_id"]: row for row in graph_results}
    raw_results = {
        "standard_dense_rag": {row["case_id"]: list(row["retrieved_record_ids"]) for row in standard_rows},
        "anchor_rag": {row["case_id"]: list(row["retrieved_record_ids"]) for row in anchor_rows},
        "relational_rag": {row["case_id"]: list(row["retrieved_record_ids"]) for row in relational_rows},
        "graph_retrieval_v1_0": {row["case_id"]: list(row["selected_record_ids"]) for row in graph_results},
    }
    resolved: dict[str, ResolvedEvidence] = {
        case_id: resolve_evidence(truth_by_id[case_id], documents) for case_id in route_by_id
    }
    case_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    metrics: dict[str, Any] = {}
    for system in SYSTEM_ORDER:
        rows = [retrieval_case_metrics(resolved[case_id], raw_results[system][case_id], document_by_id) for case_id in route_by_id]
        case_metrics[system] = {row["case_id"]: row for row in rows}
        metrics[system] = _aggregate(rows, raw_results[system], resolution_by_id)

    candidate_rows = [
        retrieval_case_metrics(resolved[case_id], graph_by_id[case_id]["candidate_record_ids"], document_by_id)
        for case_id in route_by_id
    ]
    candidate_metrics = aggregate_retrieval(candidate_rows)
    candidate_metrics["K"] = "PRE_BUDGET_CANDIDATE_POOL"
    candidate_metrics["total_candidate_paths"] = sum(row["candidate_path_count"] for row in graph_results)
    candidate_metrics["total_unique_candidate_record_incidences"] = sum(row["candidate_unique_record_count"] for row in graph_results)
    candidate_metrics["mean_unique_candidate_records_per_case"] = statistics.fmean(row["candidate_unique_record_count"] for row in graph_results)
    candidate_metrics["macro"]["hit_ci"] = _bootstrap_mean([float(row["hit"]) for row in candidate_rows])
    candidate_metrics["full_path_coverage"] = "NOT COMPUTABLE FROM AUTHORIZED VALIDATION ARTIFACTS"
    metrics["graph_candidate_pool"] = candidate_metrics

    by_anchor: dict[str, Any] = {}
    for anchor_type in sorted({row["primary_entity_type"] for row in routes}):
        ids = [row["case_id"] for row in routes if row["primary_entity_type"] == anchor_type]
        by_anchor[anchor_type] = {
            system: _aggregate([case_metrics[system][case_id] for case_id in ids], {case_id: raw_results[system][case_id] for case_id in ids}, resolution_by_id)
            for system in SYSTEM_ORDER
        }

    comparisons: list[dict[str, Any]] = []
    paired = {
        "graph_document_recall_vs_standard": Counter(),
        "full_evidence_standard_vs_graph": Counter(),
    }
    for case_id in route_by_id:
        standard = case_metrics["standard_dense_rag"][case_id]
        graph = case_metrics["graph_retrieval_v1_0"][case_id]
        delta = graph["document_recall"] - standard["document_recall"]
        paired["graph_document_recall_vs_standard"]["improves" if delta > 0 else "worse" if delta < 0 else "equal"] += 1
        status = (
            "standard_fail_graph_success" if not standard["full_evidence_coverage"] and graph["full_evidence_coverage"]
            else "both_success" if standard["full_evidence_coverage"] and graph["full_evidence_coverage"]
            else "standard_success_graph_fail" if standard["full_evidence_coverage"] and not graph["full_evidence_coverage"]
            else "both_fail"
        )
        paired["full_evidence_standard_vs_graph"][status] += 1
        comparisons.append({
            "anchor_type": route_by_id[case_id]["primary_entity_type"],
            "case_id": case_id,
            "candidate_pool_document_recall": next(row["document_recall"] for row in candidate_rows if row["case_id"] == case_id),
            "graph_minus_standard_document_recall": delta,
            "systems": {
                system: {
                    "document_recall": case_metrics[system][case_id]["document_recall"],
                    "full_evidence_coverage": case_metrics[system][case_id]["full_evidence_coverage"],
                    "hit": case_metrics[system][case_id]["hit"],
                    "record_count": case_metrics[system][case_id]["retrieval_set_size"],
                } for system in SYSTEM_ORDER
            },
        })

    ledger_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in path_ledger:
        ledger_by_case[row["case_id"]].append(row)
    motif_ids = sorted({row["motif_id"] for row in frozen_motifs})
    motif_diagnostics: dict[str, Any] = {}
    for motif_id in motif_ids:
        eligible = [row for row in graph_results if motif_id in row["candidate_motif_ids"]]
        executed = [row for row in graph_results if motif_id in row["executed_motif_ids"]]
        paths = [row for row in path_ledger if row["motif_id"] == motif_id]
        selected_paths = [row for row in paths if row["selected"]]
        contributed = [len(set(row["records"])) for row in selected_paths]
        evidence_hits = sum(bool(set(row["records"]) & set(resolved[row["case_id"]].required_record_ids)) for row in selected_paths)
        motif_diagnostics[motif_id] = {
            "eligible_case_count": len(eligible),
            "execution_count": len(executed),
            "candidate_path_count": len(paths),
            "selected_path_count": len(selected_paths),
            "average_selected_records_contributed": statistics.fmean(contributed) if contributed else 0.0,
            "validation_evidence_hit_count": evidence_hits,
        }

    relation_diagnostics: dict[str, Any] = {}
    relation_ids = sorted({edge.relation_type for edge in snapshot.edges})
    for relation_type in relation_ids:
        selected_paths = [row for row in path_ledger if row["selected"] and relation_type in row["relation_sequence"]]
        selected_records = sum(len(set(row["records"])) for row in selected_paths)
        successful_cases = {
            row["case_id"] for row in selected_paths
            if case_metrics["graph_retrieval_v1_0"][row["case_id"]]["full_evidence_coverage"]
        }
        relation_diagnostics[relation_type] = {
            "materialized_edge_count": sum(edge.relation_type == relation_type for edge in snapshot.edges),
            "selected_path_count": len(selected_paths),
            "selected_path_record_attributions": selected_records,
            "full_evidence_success_case_count_containing_relation": len(successful_cases),
            "causal_importance_claimed": False,
        }

    direct_neighbors: dict[str, set[str]] = defaultdict(set)
    for edge in snapshot.edges:
        if edge.traversable:
            direct_neighbors[edge.source_record_id].add(edge.target_record_id)
        if edge.reverse_traversal:
            direct_neighbors[edge.target_record_id].add(edge.source_record_id)
    failure_rows = []
    for case_id in route_by_id:
        required = set(resolved[case_id].required_record_ids)
        selected = set(raw_results["graph_retrieval_v1_0"][case_id])
        candidate = set(graph_by_id[case_id]["candidate_record_ids"])
        anchors = set(resolution_by_id[case_id]["resolved_record_ids"])
        if required <= selected:
            category = "FULL_RETRIEVAL_SUCCESS"
        elif resolution_by_id[case_id]["resolution_status"] == "UNRESOLVED":
            category = "ANCHOR_UNRESOLVED"
        elif required <= candidate:
            category = "RANKING_BUDGET_LOSS"
        elif any((required - candidate) & direct_neighbors[anchor] for anchor in anchors):
            category = "MOTIF_COVERAGE_GAP"
        else:
            category = "REQUIRED_RELATION_NOT_IN_FROZEN_GRAPH" if not required & candidate else "AMBIGUOUS_NOT_ATTRIBUTABLE"
        failure_rows.append({
            "case_id": case_id,
            "category": category,
            "candidate_missing_required_record_ids": sorted(required - candidate),
            "selected_missing_required_record_ids": sorted(required - selected),
        })

    latency_values: dict[str, list[float]] = defaultdict(list)
    for row in latency_rows:
        latency_values[row["system"]].append(float(row["latency_ms"]))
    latency = {
        system: {
            "case_count": len(values),
            "mean_ms": statistics.fmean(values) if values else 0.0,
            "median_ms": statistics.median(values) if values else 0.0,
            "p95_ms": percentile(values, 0.95) if values else 0.0,
            "p99_ms": percentile(values, 0.99) if values else 0.0,
            "max_ms": max(values, default=0.0),
        } for system, values in sorted(latency_values.items())
    }

    status_sources = {
        "standard_dense_rag": standard_rows,
        "anchor_rag": anchor_rows,
        "relational_rag": relational_rows,
        "graph_retrieval_v1_0": graph_results,
    }
    status_diagnostics = {
        system: {
            "counts": dict(sorted(Counter(str(row.get("status", "SUCCESS")) for row in rows).items())),
            "all_cases_have_one_terminal_status": len(rows) == len({row["case_id"] for row in rows}) == 416,
        } for system, rows in status_sources.items()
    }

    coverage = {
        system: metrics[system]["required_evidence_coverage_distribution"] for system in SYSTEM_ORDER
    }
    composition = _retrieval_composition(raw_results, document_by_id, route_by_id, resolution_by_id, graph_results, path_ledger)
    failure_categories = (
        "ANCHOR_UNRESOLVED", "REQUIRED_NODE_ABSENT_FROM_CORPUS",
        "REQUIRED_RELATION_NOT_IN_FROZEN_GRAPH", "MOTIF_COVERAGE_GAP",
        "TRAVERSAL_FAILURE", "RANKING_BUDGET_LOSS", "FULL_RETRIEVAL_SUCCESS",
        "AMBIGUOUS_NOT_ATTRIBUTABLE",
    )
    observed_failure_counts = Counter(row["category"] for row in failure_rows)

    return {
        "retrieval_metrics": metrics,
        "retrieval_metrics_by_anchor_type": by_anchor,
        "retrieval_case_comparison": comparisons,
        "paired_case_summary": {key: dict(sorted(value.items())) for key, value in paired.items()},
        "motif_diagnostics": motif_diagnostics,
        "relation_diagnostics": relation_diagnostics,
        "retrieval_failure_attribution": {
            "counts": {key: observed_failure_counts.get(key, 0) for key in failure_categories},
            "cases": failure_rows,
            "taxonomy": list(failure_categories),
            "label_or_rca_class_used": False,
        },
        "required_evidence_coverage_distribution": coverage,
        "retrieval_composition": composition,
        "retrieval_status_diagnostics": status_diagnostics,
        "hubness_diagnostics": _hubness(raw_results, route_by_id, resolution_by_id),
        "context_size_diagnostics": _context_diagnostics(raw_results, document_by_id, route_by_id, resolution_by_id),
        "latency_diagnostics": latency,
    }
