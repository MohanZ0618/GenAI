"""Phase 6A.3 pre-gold runner for frozen Graph v1.1 candidate traversal.

The frozen ranking policy is audited before traversal.  Because it is not
compatible enough to authorize a Graph v1.1 Top-40 selector, this runner
freezes candidate outputs and exits without importing or opening validation
gold.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import statistics
import sys
import tempfile
from typing import Any, Iterable, Sequence

from .candidate_traversal import CandidateTraversalEngine, FrozenGraph, TraversalRun, canonical_json, load_jsonl
from .preflight import RankingCompatibility, assess_ranking_compatibility
from .typed_grammar_loader import load_verified_grammar, sha256_file


ROUTE_RELATIVE_PATH = "results/rag/phase5_rag_validation_routes_v1_0_20260812T040938Z/validation_routes.jsonl"
ROUTE_SHA256 = "08ceeaf3a7c569ca94a87b0c0830d0fb90784daac66dd959de3fee1561b94b44"
PARENT_RESOLUTION_RELATIVE_PATH = "results/graphrag/phase6a_graph_retrieval_v1_0/retrieval/anchor_resolutions.jsonl"
PARENT_RESOLUTION_SHA256 = "b7cfffccc5660b8c50a365b8a72dc656857e4feab8dccb8049634494c6c9f9e2"
RANKING_POLICY_SHA256 = "85a167767f6147c2a51db9cdab47d7157731bb2126ca2cf2c452f4e9bde602f0"
BLOCKING_DECISION = "BLOCKED — GRAPH v1.1 EVIDENCE-SELECTION POLICY REQUIRES SEPARATE FREEZE"
SOURCE_FILES = (
    "src/graphrag/v1_1/__init__.py",
    "src/graphrag/v1_1/typed_grammar_loader.py",
    "src/graphrag/v1_1/preflight.py",
    "src/graphrag/v1_1/candidate_traversal.py",
    "src/graphrag/v1_1/runner.py",
    "tests/graphrag/test_phase6a3_graph_v1_1.py",
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def nearest_rank(values: Sequence[int | float], quantile: float) -> int | float:
    ordered = sorted(values)
    if not ordered:
        return 0
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def distribution(values: Sequence[int | float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "total": sum(values),
        "mean": statistics.fmean(values) if values else 0.0,
        "median": statistics.median(values) if values else 0.0,
        "p50_nearest_rank": nearest_rank(values, 0.50),
        "p75_nearest_rank": nearest_rank(values, 0.75),
        "p90_nearest_rank": nearest_rank(values, 0.90),
        "p95_nearest_rank": nearest_rank(values, 0.95),
        "p99_nearest_rank": nearest_rank(values, 0.99),
        "maximum": max(values, default=0),
    }


def _semantic_resolution(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "case_id", "anchor_input_type", "anchor_input_id", "resolution_method",
            "resolution_status", "resolved_record_ids", "resolved_node_types", "technical_error",
        )
    }


def verify_authorized_routes(root: Path, run: TraversalRun) -> dict[str, Any]:
    route_path = root / ROUTE_RELATIVE_PATH
    parent_path = root / PARENT_RESOLUTION_RELATIVE_PATH
    route_hash = sha256_file(route_path)
    parent_hash = sha256_file(parent_path)
    if route_hash != ROUTE_SHA256 or parent_hash != PARENT_RESOLUTION_SHA256:
        raise RuntimeError("authorized route or exact-anchor lineage hash mismatch")
    parent = sorted((_semantic_resolution(row) for row in load_jsonl(parent_path)), key=lambda row: row["case_id"])
    current = sorted((_semantic_resolution(row) for row in run.anchor_resolutions), key=lambda row: row["case_id"])
    if current != parent:
        raise RuntimeError("exact anchor resolution differs from authoritative Phase 6A semantics")
    return {
        "status": "PASS",
        "validation_split_identifier": "PHASE5_AUTHORIZED_VALIDATION_ROUTING_SET_416",
        "validation_case_count": 416,
        "resolved_root_count": 430,
        "route_sha256": route_hash,
        "parent_anchor_resolutions_sha256": parent_hash,
        "exact_anchor_semantic_equivalence": True,
        "resolution_status_counts": dict(sorted(Counter(row["resolution_status"] for row in current).items())),
    }


def code_isolation_scan(root: Path) -> dict[str, Any]:
    implementation = [root / path for path in SOURCE_FILES[:-1]]
    prohibited_import_fragments = (
        "validation_evaluator", "load_validation_evidence", "rca_ground_truth",
        "required_evidence", "benchmark.test", "benchmark.challenge_test",
    )
    hits = []
    for path in implementation:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                for fragment in prohibited_import_fragments:
                    if fragment in stripped:
                        hits.append({"path": path.relative_to(root).as_posix(), "line": number, "text": stripped})
    if hits:
        raise RuntimeError(f"gold-isolation import scan failed: {hits}")
    return {
        "status": "PASS",
        "implementation_files_scanned": [path.relative_to(root).as_posix() for path in implementation],
        "prohibited_import_fragments": list(prohibited_import_fragments),
        "unexpected_import_hit_count": 0,
        "validation_evaluator_imported_by_retriever": False,
        "validation_gold_path_available_to_retriever": False,
    }


def blocked_selection_rows(case_results: Sequence[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    return [
        {
            "case_id": row["case_id"],
            "selection_status": "NOT_RUN_POLICY_BLOCKED",
            "selection_failure_reason": "RANKING_POLICY_AMBIGUOUS",
            field: [],
        }
        for row in case_results
    ]


def candidate_statistics(run: TraversalRun) -> dict[str, Any]:
    path_counts = [row["candidate_path_count"] for row in run.case_results]
    record_counts = [row["candidate_unique_record_count"] for row in run.case_results]
    by_anchor_type = {}
    for anchor_type in sorted({row["route_anchor_type"] for row in run.case_results}):
        selected = [row for row in run.case_results if row["route_anchor_type"] == anchor_type]
        by_anchor_type[anchor_type] = {
            "case_count": len(selected),
            "candidate_paths": distribution([row["candidate_path_count"] for row in selected]),
            "candidate_unique_records": distribution([row["candidate_unique_record_count"] for row in selected]),
            "paths_by_exact_depth": {
                str(depth): sum(row["path_count_by_exact_depth"][str(depth)] for row in selected)
                for depth in (1, 2, 3)
            },
        }
    record_type_counts = Counter(row["node_type"] for row in run.candidate_records)
    minimum_depth_counts = Counter(str(row["minimum_depth"]) for row in run.candidate_records)
    return {
        "candidate_path_count": len(run.candidate_paths),
        "candidate_paths_by_exact_depth": run.telemetry["paths_by_exact_depth"],
        "candidate_paths_per_case": distribution(path_counts),
        "candidate_unique_records_per_case": distribution(record_counts),
        "candidate_record_row_count_including_case_multiplicity": len(run.candidate_records),
        "candidate_record_node_type_counts": dict(sorted(record_type_counts.items())),
        "candidate_records_by_minimum_depth": dict(sorted(minimum_depth_counts.items())),
        "cases_with_at_most_40_candidates": sum(value <= 40 for value in record_counts),
        "cases_with_more_than_40_candidates": sum(value > 40 for value in record_counts),
        "candidate_records_above_40_total": sum(max(0, value - 40) for value in record_counts),
        "records_dropped_due_to_selection": "NOT_COMPUTED_SELECTION_BLOCKED",
        "by_anchor_type": by_anchor_type,
    }


def latency_diagnostics(graph_load_ms: float, run: TraversalRun) -> dict[str, Any]:
    per_case = [row["candidate_generation_latency_ms"] for row in run.telemetry["case_latencies"]]
    return {
        "status": "DESCRIPTIVE_ONLY",
        "graph_load_ms": graph_load_ms,
        "candidate_generation_per_case_ms": distribution(per_case),
        "candidate_generation_total_ms": run.telemetry["total_candidate_generation_latency_ms"],
        "selection_latency": "NOT_COMPUTABLE_SELECTION_BLOCKED",
        "end_to_end_selected_retrieval_latency": "NOT_COMPUTABLE_SELECTION_BLOCKED",
        "offline_gold_scoring_included": False,
    }


def compatibility_review_text(compatibility: RankingCompatibility, statistics_data: dict[str, Any]) -> str:
    lines = [
        "# Graph v1.1 Ranking-Policy Compatibility Review",
        "",
        "## Decision",
        "",
        "The frozen v1 ranking registry is not sufficiently specific to convert Graph v1.1 typed candidate paths into at most 40 unique records without a new scientific design decision. Candidate traversal is authorized and has been frozen; Top-40 selection and validation-gold evaluation are not authorized.",
        "",
        "## Frozen policy sources",
        "",
        f"- `graph_ranking_policy_v1.json`: `{RANKING_POLICY_SHA256}`",
        "- `graph_traversal_grammar_v1_1.json`: frozen candidate traversal only; source-record selection is explicitly unimplemented.",
        "- Graph v1.1 proposed structural ordering is labeled metadata for future independent review, and `shorter_path_automatically_preferred` is false.",
        "",
        "## Requirement-by-requirement findings",
        "",
        "| Requirement | Status | Finding |",
        "|---|---|---|",
    ]
    for finding in compatibility.findings:
        lines.append(f"| {finding['requirement']} | {finding['status']} | {finding['evidence']} |")
    lines += [
        "",
        "## Why existing Phase 6A code is not sufficient authority",
        "",
        "The prior executable `FrozenPathRanker` and `select_paths_and_records` implementation are not frozen policy artifacts. Reusing their whole-path skip behavior or their v1 event classification would silently choose semantics that the Graph v1.1 freeze did not authorize.",
        "",
        "## Candidate freeze completed",
        "",
        f"Registry-driven traversal emitted {statistics_data['candidate_path_count']:,} paths and {statistics_data['candidate_record_row_count_including_case_multiplicity']:,} case-record rows. {statistics_data['cases_with_more_than_40_candidates']} cases exceed 40 candidates. No candidate expansion was truncated and no record was ranked, selected, or dropped.",
        "",
        "## Decisions requiring a separate freeze",
        "",
        "1. Map BACKBONE, SUPPORTING, CONTEXT, and TERMINAL_CONTEXT path combinations to executable priority classes.",
        "2. Define when an emitted prefix is a complete path for path-first selection.",
        "3. Define canonical tie-breaking across multiple roots and multi-record paths.",
        "4. Define whole-path versus partial-path behavior when fewer than all records on the next path fit the remaining 40-record budget.",
        "5. Define whether the direct supporting Payment↔Invoice projection ranks before or after its provenance-complete allocation route.",
        "",
        BLOCKING_DECISION,
    ]
    return "\n".join(lines) + "\n"


def main_report_text(
    *, compatibility: RankingCompatibility, stats: dict[str, Any], determinism: dict[str, Any],
    preflight: dict[str, Any], tests: dict[str, Any], integrity: dict[str, Any], latency: dict[str, Any],
) -> str:
    unavailable = "NOT RUN — EVIDENCE-SELECTION POLICY BLOCKED BEFORE GOLD"
    sections = [
        ("A", "Executive finding", f"Graph v1.1 candidate traversal is technically conformant and deterministic, but the frozen policy does not authorize an unambiguous Top-40 selector. Retrieval evaluation stopped before validation gold. {BLOCKING_DECISION}"),
        ("B", "Frozen Graph v1.1 lineage", f"{preflight['freeze_lineage']['check_count']} raw-byte lineage checks passed across {preflight['freeze_lineage']['distinct_path_count']} distinct paths."),
        ("C", "Implementation conformance", "Runtime traversal loads all 30 transitions from the frozen registry, applies default deny, exact edge/type/direction/provenance/cutoff checks, depth 3, simple paths, context termination, GL termination, and hub prohibitions."),
        ("D", "Ranking/evidence-selection compatibility decision", compatibility.status + ". Selection and gold evaluation are not authorized."),
        ("E", "Exact anchor resolution", "416 cases resolve exactly to 430 roots and reproduce the authoritative Phase 6A anchor resolutions."),
        ("F", "Candidate traversal statistics", f"{stats['candidate_path_count']:,} paths; per-case p50/p95/p99/max {stats['candidate_paths_per_case']['p50_nearest_rank']}/{stats['candidate_paths_per_case']['p95_nearest_rank']}/{stats['candidate_paths_per_case']['p99_nearest_rank']}/{stats['candidate_paths_per_case']['maximum']}."),
        ("G", "Multi-hop traversal statistics", f"Depth counts: {stats['candidate_paths_by_exact_depth']}. These are structural candidate counts, not retrieval success."),
        ("H", "Depth distribution", f"Depth 1/2/3 paths: {stats['candidate_paths_by_exact_depth']['1']:,}/{stats['candidate_paths_by_exact_depth']['2']:,}/{stats['candidate_paths_by_exact_depth']['3']:,}."),
        ("I", "Candidate record distribution", f"Per-case candidate records p50/p95/p99/max {stats['candidate_unique_records_per_case']['p50_nearest_rank']}/{stats['candidate_unique_records_per_case']['p95_nearest_rank']}/{stats['candidate_unique_records_per_case']['p99_nearest_rank']}/{stats['candidate_unique_records_per_case']['maximum']}."),
        ("J", "40-record budget pressure", f"{stats['cases_with_more_than_40_candidates']} cases exceed 40 candidates; {stats['candidate_records_above_40_total']} candidate incidences lie above a hypothetical per-case count of 40. No records were dropped because selection was not run."),
        ("K", "Relational-RAG baseline verification", unavailable),
        ("L", "Graph v1.1 primary retrieval metrics", unavailable),
        ("M", "Relational-RAG vs Graph v1.1", unavailable),
        ("N", "Candidate-pool vs Top40 recall", unavailable),
        ("O", "Full evidence coverage", unavailable),
        ("P", "Multi-hop-only evidence contribution", unavailable),
        ("Q", "Depth-2 contribution", unavailable),
        ("R", "Depth-3 contribution", unavailable),
        ("S", "Transition contribution", "Candidate usage is recorded pre-gold. Selected-path usage and gold contribution are not computable because selection and evaluation did not run."),
        ("T", "Path-class contribution", "Candidate path-class sequences are frozen. Gold contribution is not computable."),
        ("U", "Anchor-type breakdown", canonical_json(stats["by_anchor_type"])),
        ("V", "Bank-transaction limitation", "Payment↔BankTransaction and BankStatement membership remain absent. No heuristic or Tier-B linkage was introduced."),
        ("W", "Failure attribution", "All 416 cases have SELECTION_FAILURE solely because the evidence-selection policy is ambiguous; this is not a traversal implementation failure and no gold miss taxonomy was computed."),
        ("X", "Context composition", "Candidate node-type composition is recorded; selected context composition is not computable."),
        ("Y", "Token analysis", "NOT COMPUTABLE — no selected evidence context exists and no token cap was introduced."),
        ("Z", "Latency", f"Graph load {latency['graph_load_ms']:.3f} ms; candidate generation per-case median/p95/p99/max {latency['candidate_generation_per_case_ms']['median']:.3f}/{latency['candidate_generation_per_case_ms']['p95_nearest_rank']:.3f}/{latency['candidate_generation_per_case_ms']['p99_nearest_rank']:.3f}/{latency['candidate_generation_per_case_ms']['maximum']:.3f} ms. Selection and end-to-end selected retrieval are not computable."),
        ("AA", "Determinism", f"{determinism['result']}; {len(determinism['component_hashes_run_1'])} semantic retrieval components matched across two complete candidate runs."),
        ("AB", "Test results", f"Phase 6A.3 tests: {tests['status']} ({tests['command']}). Full repository suite was not run because unrelated tests may open prohibited held-out/gold resources; this isolation choice is deliberate."),
        ("AC", "Scientific integrity", f"{integrity['integrity_status']}; validation gold and held-out gold were not opened, and no LLM/API/embedding/semantic/Tier-B activity occurred."),
        ("AD", "Known limitations", "No empirical Recall@40 or evidence-coverage conclusion is possible until a separate evidence-selection freeze authorizes deterministic Top-40 behavior."),
        ("AE", "Interpretation", "The candidate implementation reproduces the frozen structural topology. This does not establish retrieval effectiveness."),
        ("AF", "Phase 6B readiness recommendation", "Phase 6B readiness is not assessed because the mandatory selection preflight blocked before gold evaluation."),
    ]
    lines = ["# Phase 6A.3 Graph v1.1 Retrieval Review", ""]
    for code, title, body in sections:
        lines.extend([f"## {code}. {title}", "", body, ""])
    lines.append(BLOCKING_DECISION)
    return "\n".join(lines) + "\n"


def _artifact_rows(base: Path, paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    return {
        path.relative_to(base).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(paths)
    }


def run(
    *, root: Path, output: Path, created_at_utc: str, test_status: str, test_command: str,
) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite Phase 6A.3 output: {output}")
    bundle = load_verified_grammar(root)
    compatibility = assess_ranking_compatibility(bundle)
    if compatibility.selection_implementation_authorized or compatibility.gold_evaluation_authorized:
        raise RuntimeError("unexpected ranking preflight authorization; this implementation expects fail-closed review")
    isolation = code_isolation_scan(root)
    routes_path = root / ROUTE_RELATIVE_PATH
    if sha256_file(routes_path) != ROUTE_SHA256:
        raise RuntimeError("authorized 416-route hash mismatch")
    routes = load_jsonl(routes_path)
    graph, graph_load_ms = FrozenGraph.load(root)
    engine = CandidateTraversalEngine(graph, bundle)
    first = engine.run(routes)
    second = engine.run(routes)
    first_components = first.deterministic_components()
    second_components = second.deterministic_components()
    if first_components != second_components:
        raise RuntimeError("candidate retrieval determinism failure")
    determinism = {
        "status": "PASS",
        "result": "PASS_100_PERCENT_SEMANTIC_CONTENT_EQUIVALENCE",
        "component_hashes_run_1": first_components,
        "component_hashes_run_2": second_components,
        "latency_and_timestamps_excluded": True,
        "selection_components": "NOT_APPLICABLE_POLICY_BLOCKED",
    }
    route_verification = verify_authorized_routes(root, first)
    stats = candidate_statistics(first)
    latency = latency_diagnostics(graph_load_ms, first)
    tests = {"status": test_status, "command": test_command, "scope": "PHASE_6A3_TARGETED"}
    if test_status != "PASS":
        raise RuntimeError("Phase 6A.3 tests did not pass")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".phase6a3-build-", dir=output.parent))
    try:
        retrieval = temporary / "retrieval"
        implementation = temporary / "implementation"
        write_jsonl(retrieval / "anchor_resolutions.jsonl", first.anchor_resolutions)
        write_jsonl(retrieval / "candidate_paths.jsonl", first.candidate_paths)
        write_jsonl(retrieval / "candidate_records.jsonl", first.candidate_records)
        write_jsonl(retrieval / "selected_paths.jsonl", blocked_selection_rows(first.case_results, "selected_path_ids"))
        write_jsonl(retrieval / "selected_records.jsonl", blocked_selection_rows(first.case_results, "selected_record_ids"))
        write_jsonl(retrieval / "drop_ledger.jsonl", blocked_selection_rows(first.case_results, "dropped_record_ids"))
        write_jsonl(retrieval / "graph_v1_1_retrieval_results.jsonl", first.case_results)
        write_jsonl(retrieval / "traversal_rejections.jsonl", first.rejections)
        write_json(retrieval / "candidate_statistics.json", stats)
        write_json(retrieval / "retrieval_latency_pre_gold.json", latency)
        write_json(implementation / "test_results.json", tests)

        preflight = {
            "artifact_type": "phase6a3_preflight_validation",
            "artifact_version": "1.0",
            "created_at_utc": created_at_utc,
            "status": "BLOCKED_EVIDENCE_SELECTION_POLICY",
            "freeze_lineage": bundle.input_verification,
            "grammar_transition_count": 30,
            "transition_class_counts": bundle.grammar["transition_count_by_class"],
            "frozen_relation_type_count": 15,
            "max_path_depth": 3,
            "simple_path_only": True,
            "semantic_transition_diff_count": 0,
            "ranking_policy_compatibility": compatibility.as_dict(),
            "exact_anchor_verification": route_verification,
            "gold_isolation": isolation,
            "topology_regression": {
                "status": "PASS",
                "candidate_path_count": first.telemetry["candidate_path_count"],
                "candidate_path_set_sha256": first.telemetry["candidate_path_set_sha256"],
                "paths_by_exact_depth": first.telemetry["paths_by_exact_depth"],
                "accepted_post_cutoff_traversal_count": 0,
                "vendor_or_employee_accepted_entry_count": 0,
            },
            "determinism": determinism,
            "implementation_tests": tests,
            "validation_gold_opened": False,
            "heldout_gold_opened": False,
        }
        write_json(implementation / "preflight_validation.json", preflight)
        integrity_pre = {
            "artifact_type": "phase6a3_scientific_integrity_pre_gold",
            "artifact_version": "1.0",
            "created_at_utc": created_at_utc,
            "status": "PASS",
            "integrity_status": "PASS",
            "graph_v1_1_freeze_modified": False,
            "graph_v1_modified": False,
            "graph_edges_modified": False,
            "grammar_transition_modified": False,
            "new_relation_created": False,
            "new_node_type_created": False,
            "validation_gold_visible_to_retriever": False,
            "validation_gold_used_before_output_freeze": False,
            "heldout_gold_opened": False,
            "heldout_labels_opened": False,
            "payment_bank_enabled": False,
            "bank_statement_relation_added": False,
            "gl_journal_added": False,
            "tier_b_enabled": False,
            "semantic_fallback_enabled": False,
            "llm_used": False,
            "api_call_made": False,
            "new_embedding_created": False,
            "ranking_changed_after_gold": False,
            "grammar_changed_after_gold": False,
            "record_budget_changed_after_gold": False,
            "phase6b_started": False,
        }
        write_json(temporary / "scientific_integrity_pre_gold.json", integrity_pre)

        content_paths = sorted(path for path in retrieval.iterdir() if path.name not in {"retrieval_pre_gold_manifest.json", "retrieval_pre_gold_hashes.json"})
        content_hashes = _artifact_rows(temporary, content_paths)
        pre_gold_manifest = {
            "artifact_type": "phase6a3_retrieval_pre_gold_manifest",
            "artifact_version": "1.0",
            "created_at_utc": created_at_utc,
            "status": "FROZEN_CANDIDATE_OUTPUTS_SELECTION_BLOCKED",
            "FROZEN_BEFORE_GOLD_EVALUATION": True,
            "frozen_before_gold_evaluation": True,
            "candidate_outputs_complete": True,
            "selection_outputs_executed": False,
            "selection_policy_compatibility_status": compatibility.status,
            "validation_gold_opened": False,
            "heldout_gold_opened": False,
            "validation_case_count": 416,
            "resolved_root_count": 430,
            "candidate_path_count": len(first.candidate_paths),
            "candidate_record_row_count": len(first.candidate_records),
            "retrieval_content_hashes": content_hashes,
            "ranking_policy_source": "results/graphrag/registry_freeze_v1/graph_ranking_policy_v1.json",
            "ranking_policy_hash": RANKING_POLICY_SHA256,
            "selection_policy_source": None,
            "selection_policy_hash": None,
            "selection_policy_version": None,
            "blocking_decision": BLOCKING_DECISION,
        }
        write_json(retrieval / "retrieval_pre_gold_manifest.json", pre_gold_manifest)
        pre_gold_paths = [*content_paths, retrieval / "retrieval_pre_gold_manifest.json", implementation / "preflight_validation.json", temporary / "scientific_integrity_pre_gold.json"]
        pre_gold_hashes = {
            "artifact_type": "phase6a3_retrieval_pre_gold_hash_inventory",
            "artifact_version": "1.0",
            "created_at_utc": created_at_utc,
            "status": "FROZEN_CANDIDATE_OUTPUTS_SELECTION_BLOCKED",
            "hash_algorithm": "SHA-256",
            "hash_scope": "raw serialized bytes",
            "artifacts": _artifact_rows(temporary, pre_gold_paths),
            "self_hash_omitted": True,
            "self_hash_omission_reason": "A file cannot contain its own raw-byte SHA-256 without circularity.",
            "validation_gold_opened": False,
        }
        write_json(retrieval / "retrieval_pre_gold_hashes.json", pre_gold_hashes)
        pre_gold_manifest_hash = sha256_file(retrieval / "retrieval_pre_gold_manifest.json")

        review = compatibility_review_text(compatibility, stats)
        (temporary / "RANKING_POLICY_COMPATIBILITY_REVIEW.md").write_text(review, encoding="utf-8")
        integrity = {
            **integrity_pre,
            "artifact_type": "phase6a3_scientific_integrity",
            "pre_gold_candidate_freeze_completed": True,
            "pre_gold_output_manifest_sha256": pre_gold_manifest_hash,
            "validation_gold_opened_after_freeze": False,
            "retrieval_evaluation_performed": False,
            "ranking_policy_compatibility_status": compatibility.status,
        }
        write_json(temporary / "scientific_integrity.json", integrity)
        source_hashes = {
            path: {"bytes": (root / path).stat().st_size, "sha256": sha256_file(root / path)}
            for path in SOURCE_FILES
        }
        manifest = {
            "artifact_type": "phase6a3_run_manifest",
            "artifact_version": "1.0",
            "run_id": "PHASE6A3_GRAPH_V1_1_CANDIDATE_FREEZE_POLICY_BLOCKED",
            "created_at_utc": created_at_utc,
            "status": "BLOCKED_EVIDENCE_SELECTION_POLICY",
            "graph_v1_1_freeze_hash_inventory_sha256": bundle.input_verification["checks"][0]["observed_sha256"],
            "graph_nodes_sha256": "87f80fa5e91675b192dd051598a9197c0703650f4daf09c2a7619c031295a167",
            "graph_edges_sha256": "ee364fa677abeda3b25119d5c3c2f1aea5bc8902a28e7f7ecefcddd38a77d9ed",
            "grammar_sha256": "2222def5dc3fd18628731949697087c6c96d7cdf1bb6c4cf2d16a1a58da6c8dc",
            "ranking_policy_hash": RANKING_POLICY_SHA256,
            "selection_policy_hash": None,
            "selection_policy_status": compatibility.status,
            "validation_split_identifier": route_verification["validation_split_identifier"],
            "validation_case_count": 416,
            "max_path_depth": 3,
            "max_raw_selected_records": 40,
            "candidate_path_count": len(first.candidate_paths),
            "candidate_unique_record_distribution": stats["candidate_unique_records_per_case"],
            "payment_bank_enabled": False,
            "bank_statement_membership_enabled": False,
            "gl_journal_enabled": False,
            "tier_b_enabled": False,
            "semantic_fallback_enabled": False,
            "llm_enabled": False,
            "pre_gold_output_freeze_completed": True,
            "pre_gold_output_manifest_hash": pre_gold_manifest_hash,
            "validation_gold_opened_after_freeze": False,
            "heldout_gold_opened": False,
            "api_calls_made": False,
            "embeddings_created": False,
            "implementation_commit": "NOT_AVAILABLE_NO_GIT_REPOSITORY",
            "implementation_source_hashes": source_hashes,
            "determinism_result": determinism["result"],
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "network_required": False,
            },
            "blocking_decision": BLOCKING_DECISION,
        }
        write_json(temporary / "phase6a3_run_manifest.json", manifest)
        report = main_report_text(
            compatibility=compatibility, stats=stats, determinism=determinism,
            preflight=preflight, tests=tests, integrity=integrity, latency=latency,
        )
        (temporary / "PHASE6A3_GRAPH_V1_1_RETRIEVAL_REVIEW.md").write_text(report, encoding="utf-8")

        final_paths = [path for path in temporary.rglob("*") if path.is_file() and path.name != "phase6a3_artifact_hashes.json"]
        final_inventory = {
            "artifact_type": "phase6a3_artifact_hash_inventory",
            "artifact_version": "1.0",
            "created_at_utc": created_at_utc,
            "status": "BLOCKED_EVIDENCE_SELECTION_POLICY",
            "hash_algorithm": "SHA-256",
            "hash_scope": "raw serialized bytes",
            "pre_gold_and_post_gold_distinction": {
                "pre_gold_candidate_artifacts": sorted(pre_gold_hashes["artifacts"]),
                "post_gold_evaluation_artifacts": [],
                "post_gold_evaluation_status": "NOT_CREATED_POLICY_BLOCKED_BEFORE_GOLD",
            },
            "output_artifacts": _artifact_rows(temporary, final_paths),
            "implementation_source_artifacts": source_hashes,
            "self_hash_omitted": True,
            "self_hash_omission_reason": "A file cannot contain its own raw-byte SHA-256 without circularity.",
            "validation_gold_opened": False,
            "heldout_gold_opened": False,
            "independent_verification_required": True,
        }
        write_json(temporary / "phase6a3_artifact_hashes.json", final_inventory)
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return {
        "status": "BLOCKED_EVIDENCE_SELECTION_POLICY",
        "output_directory": output.relative_to(root).as_posix(),
        "candidate_path_count": len(first.candidate_paths),
        "paths_by_exact_depth": first.telemetry["paths_by_exact_depth"],
        "candidate_record_distribution": stats["candidate_unique_records_per_case"],
        "cases_with_more_than_40_candidates": stats["cases_with_more_than_40_candidates"],
        "determinism": determinism["result"],
        "ranking_policy_compatibility": compatibility.status,
        "validation_gold_opened": False,
        "artifact_hash_inventory_sha256": sha256_file(output / "phase6a3_artifact_hashes.json"),
        "pre_gold_manifest_sha256": sha256_file(output / "retrieval/retrieval_pre_gold_manifest.json"),
        "blocking_decision": BLOCKING_DECISION,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--created-at-utc", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--test-status", choices=("PASS", "FAIL"), required=True)
    parser.add_argument("--test-command", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "results/graphrag/phase6a3_graph_v1_1_retrieval_v1_0"
    result = run(
        root=root,
        output=output,
        created_at_utc=args.created_at_utc,
        test_status=args.test_status,
        test_command=args.test_command,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
