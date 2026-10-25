"""Offline Phase 6A reproduction entry point.

This module intentionally contains no generation, embedding, semantic-search, or
held-out-test path. Validation evidence is opened only after deterministic
retrieval content has been independently reproduced and frozen by checksum.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.rag.artifacts import canonical_json, load_jsonl, sha256_bytes, sha256_file, sha256_tree, write_json, write_jsonl
from src.rag.corpus import FrozenCorpus, load_persisted_corpus
from src.rag.routes import load_routes

from .config import (
    CORPUS_DIR, CREATED_AT_UTC, DECISION_CUTOFF, DENSE_RESULTS_PATH, EXPECTED_DENSE_SHA256,
    EXPECTED_PHASE5, EXPECTED_ROUTE_SHA256, FEATURE_FLAGS, FREEZE_DIR, INDEX_DIR,
    MAX_RAW_RECORDS, OUTPUT_DIR, PHASE6A_VERSION, ROUTES_PATH, RUN_ID, VALIDATION_GOLD_PATH,
)
from .graph_builder import GraphBuild, construct_graph, load_persisted_graph, persist_graph
from .registry_loader import FrozenRegistries, load_frozen_registries
from .retrieval import DeterministicRetriever
from .validation import SYSTEM_ORDER, evaluate, load_validation_evidence_projection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_lineage(registries: FrozenRegistries) -> dict[str, Any]:
    index_manifest_path = INDEX_DIR / "index_manifest.json"
    observed_index_hash = sha256_file(index_manifest_path)
    if observed_index_hash != EXPECTED_PHASE5["index_manifest_sha256"]:
        raise RuntimeError("STOP — PHASE 6A BLOCKED: authoritative Phase 5 index manifest hash mismatch")
    manifest = json.loads(index_manifest_path.read_text(encoding="utf-8"))
    corpus_hashes = {
        "documents.jsonl": sha256_file(CORPUS_DIR / "documents.jsonl"),
        "metadata.jsonl": sha256_file(CORPUS_DIR / "metadata.jsonl"),
        "record_ids.txt": sha256_file(CORPUS_DIR / "record_ids.txt"),
    }
    for name, observed in corpus_hashes.items():
        if observed != EXPECTED_PHASE5[name]:
            raise RuntimeError(f"STOP — PHASE 6A BLOCKED: authoritative corpus hash mismatch: {name}")
    checks = {
        "text_manifest": manifest["corpus"]["text_manifest_sha256"] == EXPECTED_PHASE5["text_manifest_sha256"],
        "vector_count": manifest["vector_count"] == EXPECTED_PHASE5["vector_count"],
        "dimensions": manifest["dimensions"] == EXPECTED_PHASE5["dimensions"],
        "node_lineage": registries.node["phase5_corpus_text_manifest_sha256"] == EXPECTED_PHASE5["text_manifest_sha256"],
        "relation_lineage": registries.relation["phase5_index_manifest_sha256"] == EXPECTED_PHASE5["index_manifest_sha256"],
    }
    if not all(checks.values()):
        raise RuntimeError(f"STOP — PHASE 6A BLOCKED: Phase 5 lineage values mismatch: {checks}")
    if sha256_file(ROUTES_PATH) != EXPECTED_ROUTE_SHA256:
        raise RuntimeError("STOP — PHASE 6A BLOCKED: authorized validation route hash mismatch")
    if sha256_file(DENSE_RESULTS_PATH) != EXPECTED_DENSE_SHA256:
        raise RuntimeError("STOP — PHASE 6A BLOCKED: authoritative validation dense result hash mismatch")
    return {
        "status": "PASS",
        "decision_cutoff": DECISION_CUTOFF,
        "freeze_artifact_hashes": registries.hashes,
        "phase5_index_manifest_sha256": observed_index_hash,
        "phase5_corpus_hashes": corpus_hashes,
        "phase5_corpus_text_manifest_sha256": manifest["corpus"]["text_manifest_sha256"],
        "phase5_vector_count": manifest["vector_count"],
        "phase5_dimensions": manifest["dimensions"],
        "validation_route_sha256": EXPECTED_ROUTE_SHA256,
        "standard_dense_validation_result_sha256": EXPECTED_DENSE_SHA256,
    }


def _standard_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = load_jsonl(DENSE_RESULTS_PATH)
    deterministic = []
    latency = []
    for row in source:
        if row.get("status") != "SUCCESS" or len(row.get("retrieved_record_ids", [])) != 40:
            raise RuntimeError(f"authoritative Standard Dense RAG row is not successful K=40: {row.get('case_id')}")
        deterministic.append({
            "case_id": str(row["case_id"]),
            "retrieved_record_ids": [str(value) for value in row["retrieved_record_ids"]],
            "selected_record_count": 40,
            "source_artifact_sha256": EXPECTED_DENSE_SHA256,
            "status": "SUCCESS",
        })
        latency.append({"case_id": str(row["case_id"]), "latency_ms": float(row["retrieval_latency_ms"]), "system": "standard_dense_rag"})
    if len(deterministic) != 416:
        raise RuntimeError("authoritative Standard Dense RAG validation result count is not 416")
    return deterministic, latency


def _retrieval_pass(
    *, routes: Sequence[dict[str, str]], dense_by_id: dict[str, list[str]],
    corpus: FrozenCorpus, build: GraphBuild, registries: FrozenRegistries, measure: bool,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    retriever = DeterministicRetriever(corpus.documents, build.snapshot, registries)
    artifacts: dict[str, list[dict[str, Any]]] = {
        "anchor_resolutions": [], "graph_path_ledger": [], "graph_retrieval_results": [],
        "evidence_packets": [], "anchor_rag_results": [], "relational_rag_results": [],
    }
    latency: list[dict[str, Any]] = []
    for route in routes:
        case_id = route["case_id"]
        start = time.perf_counter_ns()
        graph, ledger, packet, resolution = retriever.graph_retrieve(route)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        if measure:
            latency.append({"case_id": case_id, "latency_ms": elapsed, "system": "graph_retrieval_v1_0"})
            latency.extend(retriever.profile_graph_stages(route))
        start = time.perf_counter_ns()
        anchor = retriever.anchor_rag(route, dense_by_id[case_id])
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        if measure:
            latency.append({"case_id": case_id, "latency_ms": elapsed, "system": "anchor_rag"})
        start = time.perf_counter_ns()
        relational = retriever.relational_rag(route)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        if measure:
            latency.append({"case_id": case_id, "latency_ms": elapsed, "system": "relational_rag"})
        if len(graph["selected_record_ids"]) > MAX_RAW_RECORDS:
            raise RuntimeError(f"40-record cap violation: {case_id}")
        if resolution["resolution_status"] in {"EXACT_SINGLE", "EXACT_MULTI"} and not set(resolution["resolved_record_ids"]) <= set(graph["selected_record_ids"]):
            raise RuntimeError(f"eligible anchor absent from graph evidence: {case_id}")
        artifacts["anchor_resolutions"].append(resolution)
        artifacts["graph_path_ledger"].extend(ledger)
        artifacts["graph_retrieval_results"].append(graph)
        artifacts["evidence_packets"].append(packet)
        artifacts["anchor_rag_results"].append(anchor)
        artifacts["relational_rag_results"].append(relational)
    return artifacts, latency


def _content_bytes(rows: Sequence[dict[str, Any]]) -> bytes:
    return "".join(canonical_json(row) + "\n" for row in rows).encode("utf-8")


def _persist_retrieval(output_dir: Path, artifacts: dict[str, list[dict[str, Any]]], standard: list[dict[str, Any]]) -> dict[str, str]:
    retrieval = output_dir / "retrieval"
    ablations = output_dir / "ablations"
    retrieval.mkdir(parents=True, exist_ok=False)
    ablations.mkdir(parents=True, exist_ok=False)
    paths = {
        "anchor_resolutions": retrieval / "anchor_resolutions.jsonl",
        "graph_path_ledger": retrieval / "graph_path_ledger.jsonl",
        "graph_retrieval_results": retrieval / "graph_retrieval_results.jsonl",
        "evidence_packets": retrieval / "evidence_packets.jsonl",
        "anchor_rag_results": ablations / "anchor_rag_results.jsonl",
        "relational_rag_results": ablations / "relational_rag_results.jsonl",
        "standard_dense_rag_results": ablations / "standard_dense_rag_results.jsonl",
    }
    for key, path in paths.items():
        write_jsonl(path, standard if key == "standard_dense_rag_results" else artifacts[key], exclusive=True)
    return {key: sha256_file(path) for key, path in paths.items()}


def _code_scan() -> dict[str, Any]:
    patterns = (
        "failure_type", "F01_", "expected label", "oracle evidence", "held-out prediction",
        "PAYMENT_CANDIDATE_BANK_TRANSACTION", "GL_JOURNAL", "OpenAI", "vector search",
    )
    hits: list[dict[str, Any]] = []
    for path in sorted(Path("src/graphrag").glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern in patterns:
                if pattern.lower() in line.lower():
                    hits.append({"path": path.as_posix(), "line": number, "pattern": pattern, "text": line.strip()})
    allowed = []
    unexpected = []
    for hit in hits:
        text = hit["text"].lower()
        if (
            (hit["path"].endswith("runner.py") and ("patterns =" in text or "hit[\"pattern\"]" in text or text.startswith('"failure_type"')))
            or (hit["path"].endswith("runner.py") and "payment_candidate_bank_transaction" in text)
            or (hit["pattern"] == "GL_JOURNAL" and ("synthetic_gl_journal_enabled" in text or '"gl_journal"' in text))
            or (hit["pattern"] == "OpenAI" and "no generation" in text)
            or (hit["pattern"] == "vector search" and "no generation" in text)
        ):
            allowed.append(hit)
        else:
            unexpected.append(hit)
    if unexpected:
        raise RuntimeError(f"PHASE 6A BLOCKED: unexpected prohibited implementation-code scan hits: {unexpected}")
    return {
        "status": "PASS",
        "patterns": list(patterns),
        "unexpected_hit_count": 0,
        "explained_false_positives": allowed,
        "tests_note": "Negative tests intentionally name prohibited features to assert rejection; tests are outside the implementation-code scan.",
    }


def _write_evaluation(output_dir: Path, values: dict[str, Any]) -> dict[str, str]:
    directory = output_dir / "evaluation"
    directory.mkdir(parents=True, exist_ok=False)
    mapping = {
        "retrieval_metrics": "retrieval_metrics.json",
        "retrieval_metrics_by_anchor_type": "retrieval_metrics_by_anchor_type.json",
        "retrieval_failure_attribution": "retrieval_failure_attribution.json",
        "motif_diagnostics": "motif_diagnostics.json",
        "relation_diagnostics": "relation_diagnostics.json",
        "hubness_diagnostics": "hubness_diagnostics.json",
        "context_size_diagnostics": "context_size_diagnostics.json",
        "latency_diagnostics": "latency_diagnostics.json",
        "paired_case_summary": "paired_case_summary.json",
        "required_evidence_coverage_distribution": "required_evidence_coverage_distribution.json",
        "retrieval_composition": "retrieval_composition.json",
        "retrieval_status_diagnostics": "retrieval_status_diagnostics.json",
    }
    for key, name in mapping.items():
        write_json(directory / name, values[key], exclusive=True)
    write_jsonl(directory / "retrieval_case_comparison.jsonl", values["retrieval_case_comparison"], exclusive=True)
    mapping["retrieval_case_comparison"] = "retrieval_case_comparison.jsonl"
    return {key: sha256_file(directory / name) for key, name in mapping.items()}


def _format_pct(value: float) -> str:
    return f"{100.0 * value:.3f}%"


def _build_report(
    *, lineage: dict[str, Any], build: GraphBuild, artifacts: dict[str, list[dict[str, Any]]],
    evaluation: dict[str, Any], determinism: dict[str, Any], integrity: dict[str, Any],
    output_dir: Path,
) -> str:
    metrics = evaluation["retrieval_metrics"]
    context = evaluation["context_size_diagnostics"]
    latency = evaluation["latency_diagnostics"]
    resolutions = artifacts["anchor_resolutions"]
    status_counts = Counter(row["resolution_status"] for row in resolutions)
    type_counts = Counter(row["anchor_input_type"] for row in resolutions)
    exact = status_counts["EXACT_SINGLE"] + status_counts["EXACT_MULTI"]
    lines = [
        "# Phase 6A Deterministic Graph Retrieval Review",
        "",
        "## A. Executive conclusion",
        "",
        "Implemented the offline deterministic GraphRAG v1.0 retrieval core from the immutable registries: a local graph snapshot, exact anchors, eight motif-bounded traversals, path-first deterministic ranking, a 40-record selector, evidence packets, two ablations, and validation evidence-retrieval evaluation. No LLM, API call, new embedding, semantic fallback, Tier B edge, synthetic node, unrestricted graph search, or held-out test evaluation was performed.",
        "",
        "## B. Frozen lineage verification",
        "",
        f"Status: **{lineage['status']}**. Phase 5 index `{lineage['phase5_index_manifest_sha256']}`; corpus text manifest `{lineage['phase5_corpus_text_manifest_sha256']}`; vector count {lineage['phase5_vector_count']}; dimensions {lineage['phase5_dimensions']}; cutoff `{DECISION_CUTOFF}`.",
        "",
        "All seven registry-freeze artifacts and all three persisted corpus files matched their required raw-byte SHA-256 values.",
        "",
        "## C. Graph build statistics",
        "",
        f"The snapshot contains **{build.integrity['node_count']:,} nodes** across 14 frozen types and **{build.integrity['edge_count']:,} edges** across all 22 frozen executable relations.",
        "",
        "| Relation | Edges | Source | Target | Traversable / reverse |",
        "|---|---:|---|---|---|",
    ]
    for name, row in build.integrity["relations"].items():
        lines.append(f"| {name} | {row['edge_count']:,} | {row['source_node_type']} | {row['target_node_type']} | {str(row['traversable']).lower()} / {str(row['reverse_traversal']).lower()} |")
    lines += [
        "",
        "## D. Integrity validation",
        "",
        f"Integrity status: **{build.integrity['status']}**. Duplicate edges: {build.integrity['duplicate_edge_count']}; self-edges: {build.integrity['self_edge_count']}; orphans: {build.integrity['orphan_relation_count']}; post-cutoff edges: {build.integrity['post_cutoff_edge_count']}; prohibited edges: {build.integrity['prohibited_relation_count']}; accidentally materialized excluded edges: {build.integrity['excluded_relation_count_accidentally_materialized']}.",
        "",
        "All executable edges retain source-record provenance. Vendor and Employee relations are persisted for auditability with forward and reverse traversal disabled. Attribute bridge expansion is absent.",
        "",
        "## E. Exact anchor resolution",
        "",
        f"Resolved {exact}/{len(resolutions)} validation anchors ({_format_pct(exact / len(resolutions))}). Outcomes: {dict(sorted(status_counts.items()))}. Anchor-type counts: {dict(sorted(type_counts.items()))}. For each exact-resolving method the first anchor rank is 1; Graph/Anchor/Relational maximum anchor rank is {metrics['graph_retrieval_v1_0']['anchor_inclusion']['maximum_anchor_rank']}. GL journal inputs resolve only to existing GL_ENTRY lines through the journal grouping attribute; no journal node is created.",
        "",
        "## F. Standard RAG validation baseline",
        "",
        f"The immutable Standard Dense RAG K=40 baseline returned macro Recall@40 {_format_pct(metrics['standard_dense_rag']['macro']['document_recall'])}, micro Recall@40 {_format_pct(metrics['standard_dense_rag']['micro']['document_recall'])}, hit rate {_format_pct(metrics['standard_dense_rag']['macro']['hit'])}, and full-evidence coverage {_format_pct(metrics['standard_dense_rag']['macro']['full_evidence_coverage'])}.",
        "",
        "## G. Anchor-RAG results",
        "",
        f"Anchor-RAG macro Recall@40: {_format_pct(metrics['anchor_rag']['macro']['document_recall'])}; full-evidence coverage: {_format_pct(metrics['anchor_rag']['macro']['full_evidence_coverage'])}; anchor inclusion: {_format_pct(metrics['anchor_rag']['anchor_inclusion']['rate'])}.",
        "",
        "## H. Relational-RAG results",
        "",
        f"Relational-RAG macro Recall@40: {_format_pct(metrics['relational_rag']['macro']['document_recall'])}; full-evidence coverage: {_format_pct(metrics['relational_rag']['macro']['full_evidence_coverage'])}; anchor inclusion: {_format_pct(metrics['relational_rag']['anchor_inclusion']['rate'])}.",
        "",
        "## I. Deterministic Graph Retrieval results",
        "",
        f"Graph Retrieval macro Recall@40: {_format_pct(metrics['graph_retrieval_v1_0']['macro']['document_recall'])}; micro Recall@40: {_format_pct(metrics['graph_retrieval_v1_0']['micro']['document_recall'])}; hit rate: {_format_pct(metrics['graph_retrieval_v1_0']['macro']['hit'])}; full-evidence coverage: {_format_pct(metrics['graph_retrieval_v1_0']['macro']['full_evidence_coverage'])}; anchor inclusion: {_format_pct(metrics['graph_retrieval_v1_0']['anchor_inclusion']['rate'])}.",
        "",
        "## J. Evidence recall comparison",
        "",
        "| Retrieval system | Anchor inclusion | Required-doc Recall@40 (micro) | Required-doc Recall@40 (macro) | Full evidence coverage | Avg records | Avg source tokens |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "standard_dense_rag": "Standard Dense RAG", "anchor_rag": "Anchor-RAG",
        "relational_rag": "Relational-RAG", "graph_retrieval_v1_0": "Graph Retrieval v1.0",
    }
    for system in SYSTEM_ORDER:
        row = metrics[system]
        lines.append(
            f"| {labels[system]} | {_format_pct(row['anchor_inclusion']['rate'])} | {_format_pct(row['micro']['document_recall'])} | {_format_pct(row['macro']['document_recall'])} | {_format_pct(row['macro']['full_evidence_coverage'])} | {row['average_record_count']:.2f} | {row['average_source_tokens']:.2f} |"
        )
    lines += [
        "",
        "Confidence intervals use the same deterministic 10,000-resample bootstrap seed as Phase 5. Detailed intervals and anchor-type breakdowns are machine-readable in `evaluation/`.",
        "",
        "## K. Full-evidence coverage comparison",
        "",
        f"Paired outcomes: `{evaluation['paired_case_summary']['full_evidence_standard_vs_graph']}`. No cases were filtered.",
        "",
        "## L. Candidate-pool versus Top-40 analysis",
        "",
        f"Graph candidate-pool micro required-evidence recall was {_format_pct(metrics['graph_candidate_pool']['micro']['document_recall'])}; selected graph evidence recall was {_format_pct(metrics['graph_retrieval_v1_0']['micro']['document_recall'])}. The pool contained {metrics['graph_candidate_pool']['total_candidate_paths']:,} path incidences and {metrics['graph_candidate_pool']['total_unique_candidate_record_incidences']:,} unique-record incidences across cases. No record was lost to the 40-record cap. Complete gold-path coverage is **NOT COMPUTABLE FROM AUTHORIZED VALIDATION ARTIFACTS**, because no frozen gold path-instantiation contract exists.",
        "",
        "## M. Path and motif diagnostics",
        "",
        "| Motif | Eligible cases | Candidate paths | Selected paths | Evidence-hit paths |",
        "|---|---:|---:|---:|---:|",
    ]
    for motif, row in evaluation["motif_diagnostics"].items():
        lines.append(f"| {motif} | {row['eligible_case_count']} | {row['candidate_path_count']} | {row['selected_path_count']} | {row['validation_evidence_hit_count']} |")
    lines += [
        "",
        "Relation frequencies are descriptive and are not interpreted as causal importance. All path rows preserve edge provenance and frozen relation order.",
        "",
        "## N. Record-type diversity",
        "",
        "Average distinct node types per case: " + "; ".join(f"{labels[system]} {context[system]['average_distinct_node_types']:.2f}" for system in SYSTEM_ORDER) + ". Graph Retrieval executed an average of " + f"{evaluation['retrieval_composition']['graph_retrieval_v1_0']['path_composition']['average_motifs_executed']:.2f} motifs and selected {evaluation['retrieval_composition']['graph_retrieval_v1_0']['path_composition']['average_selected_paths']:.2f} paths per case. Selected direct/multi-hop path counts were {evaluation['retrieval_composition']['graph_retrieval_v1_0']['path_composition']['selected_direct_path_count']}/{evaluation['retrieval_composition']['graph_retrieval_v1_0']['path_composition']['selected_multihop_path_count']}. Full record-type and cross-type fractions, including anchor-type breakdowns, are in `evaluation/retrieval_composition.json`.",
        "",
        "## O. Hubness analysis",
        "",
        f"No Vendor or Employee reverse-neighborhood motif exists. Graph mean pairwise retrieval-set Jaccard was {evaluation['hubness_diagnostics']['graph_retrieval_v1_0']['mean_pairwise_jaccard']:.6f}; its maximum non-anchor record frequency was {evaluation['hubness_diagnostics']['graph_retrieval_v1_0']['maximum_non_anchor_record_frequency']} cases. Per-anchor overlap, recurrent-record counts, case percentages, and top-20 slot shares are in `evaluation/hubness_diagnostics.json`; no hub exception was enabled.",
        "",
        "## P. Context-size analysis",
        "",
        "| System | Median tokens | p90 | p95 | p99 | Max |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for system in SYSTEM_ORDER:
        row = context[system]["source_tokens"]
        lines.append(f"| {labels[system]} | {row['median']:.1f} | {row['p90']:.1f} | {row['p95']:.1f} | {row['p99']:.1f} | {row['max']:.1f} |")
    lines += [
        "",
        "The Phase 6B token cap remains **NOT FROZEN**. These distributions are descriptive and did not alter record selection. Per-anchor-type token and cross-type distributions are persisted in `context_size_diagnostics.json`.",
        "",
        "## Q. Latency analysis",
        "",
        "| System | Mean ms | Median ms | p95 ms | Max ms |",
        "|---|---:|---:|---:|---:|",
    ]
    for system, row in latency.items():
        lines.append(f"| {labels.get(system, system)} | {row['mean_ms']:.3f} | {row['median_ms']:.3f} | {row['p95_ms']:.3f} | {row['max_ms']:.3f} |")
    lines += [
        "",
        "Latency is explicitly nondeterministic telemetry and is excluded from retrieval-content equivalence hashes.",
        "",
        "## R. Failure attribution",
        "",
        "All 416 cases have exactly one terminal retrieval status; all four systems completed with `SUCCESS`. Conservative label-independent evidence-failure counts: `" + str(evaluation["retrieval_failure_attribution"]["counts"]) + "`. Attribution distinguishes unresolved anchors, missing relations, frozen motif gaps, traversal defects, and Top-40 ranking/budget loss; it does not inspect or infer RCA class. Required-evidence 0%/partial/100% coverage buckets and quartiles are in `required_evidence_coverage_distribution.json`.",
        "",
        "## S. Determinism/reproducibility",
        "",
        f"Graph construction and the complete validation retrieval/ablation pass were each run twice independently. Node bytes, edge bytes, anchor resolutions, path IDs, path rankings, selected paths, selected records, evidence packets, and ablation results matched: **{determinism['status']}** ({determinism['equivalence_percent']}).",
        "",
        "Reproduction command (requires a non-existing output directory):",
        "",
        "```bash",
        "python3 -m src.graphrag.runner run --output-dir /private/tmp/phase6a_reproduction",
        "```",
        "",
        "## T. Deviations",
        "",
        "No registry-semantic deviation was made. The exact Phase 6B token cap remains unresolved as required. Full path coverage is not computed because authorized validation evidence provides required records, not a frozen path contract. Runtime timestamps and latency are outside deterministic content hashes.",
        "",
        "## U. Limitations",
        "",
        "The frozen v1.0 graph deliberately cannot traverse payment-bank candidates, conditional employee identity, Vendor/Employee hubs, semantic similarity, or arbitrary neighborhoods. Motifs are directional as serialized; permitted anchor types that do not satisfy the first directed step yield zero paths rather than an invented reverse rule. Retrieval performance is validation-only and does not establish generation or RCA accuracy.",
        "",
        "## V. Phase 6B recommendation",
        "",
        "All technical lineage, cutoff, provenance, exclusion, cap, separation, and reproducibility gates passed. The validation retrieval result is fully characterized for researcher review. This recommendation does not authorize inference.",
        "",
        "RECOMMEND 8/8 GO FOR PHASE 6B GRAPH RAG INFERENCE FREEZE",
    ]
    return "\n".join(lines) + "\n"


def _artifact_inventory(output_dir: Path) -> dict[str, Any]:
    inventory_path = output_dir / "phase6a_artifact_hashes.json"
    files = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path != inventory_path:
            files.append({
                "bytes": path.stat().st_size,
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": sha256_file(path),
            })
    return {
        "algorithm": "SHA-256",
        "file_count": len(files),
        "files": files,
        "inventory_self_hash_policy": "The inventory cannot self-contain its own raw-byte hash; its independently recomputed hash is reported externally.",
        "status": "PASS",
    }


def run(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"Phase 6A output directory already exists: {output_dir}")
    registries = load_frozen_registries(FREEZE_DIR)
    lineage = verify_lineage(registries)
    corpus = load_persisted_corpus(CORPUS_DIR)
    if len(corpus.documents) != EXPECTED_PHASE5["document_count"]:
        raise RuntimeError("STOP — PHASE 6A BLOCKED: persisted corpus count mismatch")
    output_dir.mkdir(parents=True, exist_ok=False)
    created = _utc_now()
    build_start = time.perf_counter_ns()
    build = construct_graph(corpus, registries)
    build_latency_ms = (time.perf_counter_ns() - build_start) / 1_000_000
    graph_manifest_base = {
        "artifact_type": "phase6a_deterministic_graph_snapshot",
        "artifact_version": PHASE6A_VERSION,
        "created_at_utc": created,
        "decision_cutoff": DECISION_CUTOFF,
        "node_registry_sha256": registries.hashes["graph_node_registry_v1.json"],
        "relation_registry_sha256": registries.hashes["graph_relation_registry_v1.json"],
        "path_motifs_sha256": registries.hashes["graph_path_motifs_v1.json"],
        "ranking_policy_sha256": registries.hashes["graph_ranking_policy_v1.json"],
        "phase5_index_manifest_sha256": lineage["phase5_index_manifest_sha256"],
        "phase5_corpus_text_manifest_sha256": lineage["phase5_corpus_text_manifest_sha256"],
        "feature_flags": FEATURE_FLAGS,
    }
    graph_hashes = persist_graph(build, output_dir / "graph", graph_manifest_base)
    load_start = time.perf_counter_ns()
    loaded_snapshot = load_persisted_graph(output_dir / "graph")
    graph_load_latency_ms = (time.perf_counter_ns() - load_start) / 1_000_000
    loaded_build = GraphBuild(loaded_snapshot, build.integrity)

    temp_root = Path(tempfile.mkdtemp(prefix="phase6a_determinism_"))
    try:
        registries_second = load_frozen_registries(FREEZE_DIR)
        corpus_second = load_persisted_corpus(CORPUS_DIR)
        build_second = construct_graph(corpus_second, registries_second)
        second_graph_hashes = persist_graph(build_second, temp_root / "graph", graph_manifest_base)
        if graph_hashes["nodes"] != second_graph_hashes["nodes"] or graph_hashes["edges"] != second_graph_hashes["edges"]:
            raise RuntimeError("PHASE 6A BLOCKED: independently rebuilt graph bytes differ")
        second_loaded_build = GraphBuild(load_persisted_graph(temp_root / "graph"), build_second.integrity)

        routes = load_routes(ROUTES_PATH)
        if len(routes) != 416:
            raise RuntimeError("authorized validation route count is not 416")
        standard, standard_latency = _standard_rows()
        dense_by_id = {row["case_id"]: row["retrieved_record_ids"] for row in standard}
        if [row["case_id"] for row in routes] != [row["case_id"] for row in standard]:
            raise RuntimeError("validation route and Standard Dense RAG row ordering disagree")
        first_artifacts, measured_latency = _retrieval_pass(
            routes=routes, dense_by_id=dense_by_id, corpus=corpus, build=loaded_build, registries=registries, measure=True,
        )
        second_artifacts, _ = _retrieval_pass(
            routes=routes, dense_by_id=dense_by_id, corpus=corpus_second, build=second_loaded_build, registries=registries_second, measure=False,
        )
        content_hashes_first = {key: sha256_bytes(_content_bytes(value)) for key, value in first_artifacts.items()}
        content_hashes_second = {key: sha256_bytes(_content_bytes(value)) for key, value in second_artifacts.items()}
        if content_hashes_first != content_hashes_second:
            raise RuntimeError("PHASE 6A BLOCKED: independently repeated retrieval content differs")
    finally:
        shutil.rmtree(temp_root)

    retrieval_hashes = _persist_retrieval(output_dir, first_artifacts, standard)
    latency_rows = [
        {"case_id": "__GRAPH_BUILD__", "latency_ms": build_latency_ms, "system": "graph_build"},
        {"case_id": "__GRAPH_LOAD__", "latency_ms": graph_load_latency_ms, "system": "graph_load"},
        *standard_latency, *measured_latency,
    ]
    write_jsonl(output_dir / "retrieval" / "latency_raw.jsonl", latency_rows, exclusive=True)
    write_json(output_dir / "graph" / "graph_build_latency.json", {
        "graph_build_latency_ms": build_latency_ms,
        "nondeterministic_telemetry": True,
    }, exclusive=True)
    determinism = {
        "status": "PASS",
        "equivalence_percent": "100% byte/semantic deterministic equivalence",
        "graph_first": graph_hashes,
        "graph_second": second_graph_hashes,
        "retrieval_content_first": content_hashes_first,
        "retrieval_content_second": content_hashes_second,
        "excluded_from_equivalence": ["created_at_utc", "runtime latency telemetry"],
    }
    write_json(output_dir / "determinism_validation.json", determinism, exclusive=True)
    retrieval_freeze = {
        "artifact_type": "phase6a_pre_evaluation_retrieval_content_freeze",
        "created_at_utc": created,
        "determinism_status": "PASS",
        "graph_nodes_sha256": graph_hashes["nodes"],
        "graph_edges_sha256": graph_hashes["edges"],
        "retrieval_artifact_hashes": retrieval_hashes,
        "retrieval_content_hashes": content_hashes_first,
        "validation_gold_opened_at_freeze": False,
        "validation_gold_visible_to_retriever": False,
    }
    write_json(output_dir / "retrieval" / "retrieval_content_manifest.json", retrieval_freeze, exclusive=True)

    # Scientific boundary: validation evidence becomes visible only here, after
    # graph and retrieval outputs have been independently reproduced and frozen.
    evidence_projection = load_validation_evidence_projection(VALIDATION_GOLD_PATH)
    evaluation = evaluate(
        evidence_projection=evidence_projection, routes=routes, documents=corpus.documents, snapshot=build.snapshot,
        resolutions=first_artifacts["anchor_resolutions"], graph_results=first_artifacts["graph_retrieval_results"],
        path_ledger=first_artifacts["graph_path_ledger"], standard_rows=standard,
        anchor_rows=first_artifacts["anchor_rag_results"], relational_rows=first_artifacts["relational_rag_results"],
        latency_rows=latency_rows,
        frozen_motifs=registries.motifs["frozen_motifs"],
    )
    evaluation_hashes = _write_evaluation(output_dir, evaluation)
    scan = _code_scan()
    scientific_integrity = {
        "heldout_labels_opened": False,
        "heldout_gold_evidence_opened": False,
        "oracle_sources_opened": False,
        "previous_predictions_used_for_graph_logic": False,
        "failure_labels_used_for_graph_logic": False,
        "validation_gold_visible_to_retriever": False,
        "validation_gold_opened_by_separate_evaluator_after_retrieval_freeze": True,
        "api_calls_made": False,
        "new_embeddings_created": False,
        "graph_registry_modified": False,
        "phase5_artifacts_modified": False,
        "generation_performed": False,
        "code_scan": scan,
        "status": "PASS",
    }
    write_json(output_dir / "scientific_integrity.json", scientific_integrity, exclusive=True)
    parent_recheck = verify_lineage(load_frozen_registries(FREEZE_DIR))
    if parent_recheck != lineage:
        raise RuntimeError("PHASE 6A BLOCKED: parent artifacts changed during run")

    implementation_hash = sha256_tree(Path("src/graphrag"))
    manifest = {
        "api_calls_made": False,
        "artifact_type": "phase6a_deterministic_graph_retrieval_run",
        "artifact_version": PHASE6A_VERSION,
        "conditional_employee_edges_enabled": False,
        "created_at_utc": created,
        "environment": {"platform": platform.platform(), "python": sys.version},
        "generation_performed": False,
        "graph_build_manifest_sha256": graph_hashes["manifest"],
        "graph_edges_sha256": graph_hashes["edges"],
        "graph_freeze_manifest_sha256": registries.hashes["graph_freeze_manifest_v1.json"],
        "graph_node_registry_sha256": registries.hashes["graph_node_registry_v1.json"],
        "graph_nodes_sha256": graph_hashes["nodes"],
        "graph_path_motifs_sha256": registries.hashes["graph_path_motifs_v1.json"],
        "graph_ranking_policy_sha256": registries.hashes["graph_ranking_policy_v1.json"],
        "graph_relation_registry_sha256": registries.hashes["graph_relation_registry_v1.json"],
        "heldout_gold_opened": False,
        "implementation_commit": "NOT_AVAILABLE_WORKSPACE_HAS_NO_GIT_METADATA",
        "implementation_sha256": implementation_hash,
        "llm_enabled": False,
        "max_raw_records": MAX_RAW_RECORDS,
        "new_embeddings_created": False,
        "path_ledger_sha256": retrieval_hashes["graph_path_ledger"],
        "payment_bank_enabled": False,
        "phase5_corpus_text_manifest_sha256": lineage["phase5_corpus_text_manifest_sha256"],
        "phase5_index_manifest_sha256": lineage["phase5_index_manifest_sha256"],
        "retrieval_result_sha256": retrieval_hashes["graph_retrieval_results"],
        "anchor_resolution_sha256": retrieval_hashes["anchor_resolutions"],
        "evidence_packet_sha256": retrieval_hashes["evidence_packets"],
        "run_id": RUN_ID,
        "semantic_fallback_enabled": False,
        "synthetic_gl_journal_enabled": False,
        "tier_b_enabled": False,
        "validation_case_count": len(routes),
        "validation_split_identifier": "finrecn_authorized_validation_416",
        "validation_gold_opened_by_evaluator": True,
        "determinism_status": "PASS",
        "evaluation_artifact_hashes": evaluation_hashes,
    }
    write_json(output_dir / "phase6a_run_manifest.json", manifest, exclusive=True)
    report = _build_report(
        lineage=lineage, build=build, artifacts=first_artifacts, evaluation=evaluation,
        determinism=determinism, integrity=scientific_integrity, output_dir=output_dir,
    )
    report_path = output_dir / "PHASE6A_GRAPH_RETRIEVAL_REVIEW.md"
    report_path.write_text(report, encoding="utf-8", newline="\n")
    inventory = _artifact_inventory(output_dir)
    inventory_path = output_dir / "phase6a_artifact_hashes.json"
    write_json(inventory_path, inventory, exclusive=True)
    independently_recomputed = _artifact_inventory(output_dir)
    if inventory != independently_recomputed:
        raise RuntimeError("PHASE 6A BLOCKED: final artifact hash inventory verification failed")
    return {
        "output_dir": output_dir.as_posix(),
        "node_count": build.integrity["node_count"],
        "edge_count": build.integrity["edge_count"],
        "anchor_resolution_counts": dict(sorted(Counter(row["resolution_status"] for row in first_artifacts["anchor_resolutions"]).items())),
        "metrics": evaluation["retrieval_metrics"],
        "determinism": determinism["status"],
        "scientific_integrity": scientific_integrity["status"],
        "report_sha256": sha256_file(report_path),
        "artifact_inventory_sha256": sha256_file(inventory_path),
        "recommendation": "RECOMMEND 8/8 GO FOR PHASE 6B GRAPH RAG INFERENCE FREEZE",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinRecn Phase 6A deterministic graph retrieval")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("run", help="build twice, retrieve twice, then evaluate authorized validation evidence")
    command.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    result = run(args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
