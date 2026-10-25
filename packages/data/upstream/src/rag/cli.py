"""Safe-by-default command line interface for frozen Standard RAG v1.0."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from src.rag.artifacts import (
    append_jsonl, load_jsonl, sha256_file, sha256_tree, write_checksum_manifest,
    write_json, write_jsonl,
)
from src.rag.audits import (
    corpus_leakage_audit,
    no_graph_audit,
    pre_embedding_gate,
    render_no_graph_markdown,
    render_pre_live_markdown,
    repository_secret_audit,
    verify_frozen_spec,
)
from src.rag.config import (
    EMBEDDING_CONFIG,
    EXPECTED_DOCUMENT_COUNT,
    REASONER_CONFIG,
    QUERY_VERSION,
    SPEC_SHA256,
    VALIDATION_MAX_K,
)
from src.rag.corpus import (
    FrozenCorpus,
    build_frozen_corpus,
    corpus_token_audit,
    load_persisted_corpus,
    persist_corpus,
)
from src.rag.costs import direct_packet_compression, end_to_end_accounting
from src.rag.embeddings import OpenAIEmbeddingClient, embed_corpus, finalize_embedding_matrix
from src.rag.evaluation import (
    aggregate_evidence, aggregate_retrieval, attribute_failure,
    classification_metrics,
    evidence_prediction_metrics,
    evaluate_k_grid,
    load_ground_truth,
    paired_comparison,
    retrieval_case_metrics,
    select_k,
    stratified_results,
)
from src.rag.evidence import resolve_evidence
from src.rag.index import ExactFlatCosineNumpyV1, write_index_manifest
from src.rag.oracle import build_oracle_cases
from src.rag.prompt import load_frozen_prompt, prompt_sha256
from src.rag.query import AnchorResolutionError, build_query
from src.rag.reasoner import (
    OpenAIReasonerClient,
    build_reasoning_case,
    context_preflight,
)
from src.rag.retrieval_runner import run_retrieval
from src.rag.routes import load_routes, prepare_routes
from src.rag.runner import pricing_report, run_reasoning_cases
from src.rag.schemas import canonical_output_schema


ROOT = Path(__file__).resolve().parents[2]


def _run_phase5_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "tests/rag", "-q"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "command": " ".join(command), "returncode": result.returncode,
        "passed": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr,
    }


def _run_repository_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "command": " ".join(command), "returncode": result.returncode,
        "passed": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr,
    }


def _latest_rows(path: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in load_jsonl(path):
        latest[str(row["case_id"])] = row
    return list(latest.values())


def _checkpoint_retrieval_technical_predictions(
    results: dict[str, dict[str, Any]], output_dir: Path
) -> list[str]:
    """Materialize spec-defined terminal predictions for routes with no eligible anchor."""
    path = output_dir / "generation/predictions.jsonl"
    existing = {str(row["case_id"]): row for row in load_jsonl(path)} if path.is_file() else {}
    technical_ids = []
    for case_id, result in results.items():
        if result.get("status") != "ANCHOR_TECHNICAL_FAILURE":
            continue
        technical_ids.append(case_id)
        if case_id in existing:
            if existing[case_id].get("parse_status") != "ANCHOR_TECHNICAL_FAILURE":
                raise RuntimeError(f"retrieval technical prediction changed on resume for {case_id}")
            continue
        append_jsonl(path, {
            "case_id": case_id,
            "method": "rag",
            "status": "TECHNICAL_FAILURE",
            "is_anomaly": None,
            "predicted_failure_type": None,
            "evidence_record_ids": [],
            "reason": str(result.get("error_detail", "ANCHOR_TECHNICAL_FAILURE")),
            "confidence": None,
            "retrieved_record_ids": [],
            "request_hash": result.get("request_hash"),
            "response_id": None,
            "returned_model": None,
            "parse_status": "ANCHOR_TECHNICAL_FAILURE",
            "attempt_count": 0,
            "latency_ms": 0.0,
            "context_assembly_latency_ms": 0.0,
            "usage": {},
        })
    return sorted(technical_ids)


def _load_index(index_dir: Path) -> tuple[FrozenCorpus, ExactFlatCosineNumpyV1, dict[str, Any]]:
    manifest_path = index_dir / "index_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("frozen_spec_sha256") != SPEC_SHA256:
        raise RuntimeError("index was not built under the frozen v1.0 specification")
    corpus = load_persisted_corpus(index_dir / "corpus")
    index = ExactFlatCosineNumpyV1.load(
        index_dir / "embeddings.npy", index_dir / "corpus/record_ids.txt", expected=manifest
    )
    return corpus, index, manifest


def _require_live_flag(args: argparse.Namespace, operation: str) -> None:
    if not args.execute_api:
        raise RuntimeError(f"{operation} makes paid API calls and requires explicit --execute-api")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not present")


def preflight(args: argparse.Namespace) -> int:
    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    frozen = verify_frozen_spec(ROOT)
    if frozen["status"] != "PASS":
        raise RuntimeError("frozen specification verification failed")
    # Run in a subprocess before retaining the full corpus in this process.
    phase5_tests = _run_phase5_tests()
    repository_tests = _run_repository_tests()
    tests = {
        "passed": phase5_tests["passed"] and repository_tests["passed"],
        "phase5": phase5_tests,
        "repository": repository_tests,
    }
    corpus = build_frozen_corpus(Path(args.data_root) / "full")
    corpus_hashes = persist_corpus(corpus, run_dir / "corpus")
    validation_routes, validation_route_audit = prepare_routes(
        Path(args.data_root) / "validation", run_dir / "validation_routes.jsonl"
    )
    test_routes, test_route_audit = prepare_routes(
        Path(args.data_root) / "test", run_dir / "test_routes.jsonl"
    )
    if len(validation_routes) != 416 or len(test_routes) != 439:
        raise RuntimeError(
            f"frozen route counts disagree: validation={len(validation_routes)} test={len(test_routes)}"
        )
    tokens = corpus_token_audit(corpus.documents)
    write_json(run_dir / "corpus_token_audit.json", tokens, exclusive=True)
    gate = pre_embedding_gate(ROOT, corpus, tokens, tests)
    graph = gate["no_graph_audit"]
    write_json(run_dir / "rag_runtime_leakage_audit.json", gate["leakage_audit"], exclusive=True)
    write_json(run_dir / "rag_no_graph_compliance_audit.json", graph, exclusive=True)
    write_json(run_dir / "secret_audit.json", gate["secret_audit"], exclusive=True)
    write_json(run_dir / "test_results.json", tests, exclusive=True)
    write_json(run_dir / "pre_embedding_gate.json", gate, exclusive=True)
    (run_dir / "rag_no_graph_compliance_audit_v1.0.md").write_text(
        render_no_graph_markdown(graph), encoding="utf-8", newline="\n"
    )
    (run_dir / "protocol_deviations.md").write_text(
        "# Protocol Deviations\n\nNONE. Paid embedding, validation retrieval, K selection, held-out inference, and offline evaluation remain pending user authorization and are not deviations.\n",
        encoding="utf-8", newline="\n",
    )
    write_json(run_dir / "run_manifest.json", {
        "run_id": args.run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PRE_EMBEDDING_NO_API",
        "paid_api_calls_made": False,
        "frozen_spec_sha256": SPEC_SHA256,
        "corpus_hashes": corpus_hashes,
        "validation_route_sha256": validation_route_audit["output_sha256"],
        "test_route_sha256": test_route_audit["output_sha256"],
        "validation_route_count": len(validation_routes),
        "test_route_count": len(test_routes),
        "implementation_sha256": sha256_tree(ROOT / "src/rag"),
        "protocol_deviations": "NONE",
        "decision": gate["decision"],
    }, exclusive=True)
    checksum_path = write_checksum_manifest(run_dir)
    print(f"artifact_checksums_sha256={sha256_file(checksum_path)}")
    print(gate["decision"])
    return 0 if gate["status"] == "PASS" else 1


def prepare_route_artifact(args: argparse.Namespace) -> int:
    output = Path(args.output)
    routes, audit = prepare_routes(Path(args.data_root) / args.split, output)
    expected = 416 if args.split == "validation" else 439 if args.split == "test" else None
    if expected is not None and len(routes) != expected:
        raise RuntimeError(f"expected {expected} {args.split} routes, observed {len(routes)}")
    print(json.dumps({"route_count": len(routes), "route_sha256": audit["output_sha256"]}, indent=2))
    return 0


def build_index(args: argparse.Namespace) -> int:
    _require_live_flag(args, "build-index")
    run_dir = Path(args.output_root) / args.run_id
    first_attempt = not run_dir.exists()
    if first_attempt:
        run_dir.mkdir(parents=True, exist_ok=False)
    elif (run_dir / "artifact_checksums.json").is_file():
        raise RuntimeError("index run is complete and immutable")
    frozen = verify_frozen_spec(ROOT)
    if frozen["status"] != "PASS":
        raise RuntimeError("frozen specification verification failed")
    if first_attempt:
        corpus = build_frozen_corpus(Path(args.data_root) / "full")
        token_audit = corpus_token_audit(corpus.documents)
        leakage = corpus_leakage_audit(corpus)
        secrets = repository_secret_audit(ROOT)
        if token_audit["status"] != "PASS" or leakage["status"] != "PASS" or secrets["status"] != "PASS":
            raise RuntimeError("pre-embedding corpus/security gate failed")
        corpus_hashes = persist_corpus(corpus, run_dir / "corpus")
        write_json(run_dir / "corpus_token_audit.json", token_audit, exclusive=True)
    else:
        corpus = load_persisted_corpus(run_dir / "corpus")
        token_audit = json.loads((run_dir / "corpus_token_audit.json").read_text(encoding="utf-8"))
        corpus_hashes = {
            "documents_sha256": sha256_file(run_dir / "corpus/documents.jsonl"),
            "metadata_sha256": sha256_file(run_dir / "corpus/metadata.jsonl"),
            "record_ids_sha256": sha256_file(run_dir / "corpus/record_ids.txt"),
            "text_manifest_sha256": corpus.text_manifest_sha256,
        }
    print(json.dumps({
        "model": EMBEDDING_CONFIG.model_id,
        "document_count": len(corpus.documents), "dimensions": EMBEDDING_CONFIG.dimensions,
        "batch_size": EMBEDDING_CONFIG.corpus_batch_size,
        "specification_sha256": SPEC_SHA256,
        "text_manifest_sha256": corpus.text_manifest_sha256,
        "output_directory": str(run_dir), "api_credentials_present": True,
        "estimated_embedding_input_tokens": token_audit["total_tokens"],
        "estimated_embedding_cost_usd": token_audit["total_tokens"] / 1_000_000 * EMBEDDING_CONFIG.usd_per_million_input_tokens,
    }, indent=2, sort_keys=True))
    summary = embed_corpus(
        corpus.documents, client=OpenAIEmbeddingClient(), output_dir=run_dir
    )
    if (run_dir / "embedding_summary.json").is_file():
        final = json.loads((run_dir / "embedding_summary.json").read_text(encoding="utf-8"))
    else:
        final = finalize_embedding_matrix(corpus.documents, run_dir)
    if (run_dir / "index_manifest.json").is_file():
        manifest = json.loads((run_dir / "index_manifest.json").read_text(encoding="utf-8"))
    else:
        manifest = write_index_manifest(
            run_dir, run_dir / "corpus/record_ids.txt", final, corpus_hashes
        )
    write_json(run_dir / "run_manifest.json", {
        "run_id": args.run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "CORPUS_EMBEDDING_AND_INDEX_API", "paid_api_calls_made": True,
        "embedding_run": summary, "index_manifest_sha256": sha256_file(run_dir / "index_manifest.json"),
    }, exclusive=True)
    write_checksum_manifest(run_dir)
    print(json.dumps({"embedding": summary, "index": manifest}, indent=2, sort_keys=True))
    return 0


def validation_retrieve(args: argparse.Namespace) -> int:
    _require_live_flag(args, "validation-retrieve")
    index_dir = Path(args.index_dir)
    corpus, index, _ = _load_index(index_dir)
    routes = load_routes(Path(args.routes))
    if len(routes) != 416:
        raise RuntimeError(f"validation retrieval requires 416 routes, observed {len(routes)}")
    output_dir = Path(args.output_root) / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    print(json.dumps({
        "model": EMBEDDING_CONFIG.model_id, "case_count": len(routes), "K": VALIDATION_MAX_K,
        "specification_sha256": SPEC_SHA256,
        "index_checksum": sha256_file(index_dir / "index_manifest.json"),
        "route_checksum": sha256_file(Path(args.routes)), "output_directory": str(output_dir),
        "api_credentials_present": True,
        "estimated_query_input_tokens": sum(build_query(route, corpus).token_count for route in routes),
    }, indent=2, sort_keys=True))
    summary = run_retrieval(
        routes, corpus=corpus, client=OpenAIEmbeddingClient(), index=index,
        k=VALIDATION_MAX_K, output_dir=output_dir,
        index_manifest_sha256=sha256_file(index_dir / "index_manifest.json"),
    )
    write_json(output_dir / "run_manifest.json", {
        "run_id": args.run_id, "mode": "VALIDATION_RETRIEVAL_API",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary.serializable(), "K": VALIDATION_MAX_K,
        "index_manifest_sha256": sha256_file(index_dir / "index_manifest.json"),
        "route_sha256": sha256_file(Path(args.routes)),
    }, exclusive=True)
    if summary.failed_cases == 0:
        write_checksum_manifest(output_dir)
    print(json.dumps(summary.serializable(), indent=2, sort_keys=True))
    return 0 if summary.failed_cases == 0 else 1


def lock_selection(args: argparse.Namespace) -> int:
    index_dir = Path(args.index_dir)
    corpus = load_persisted_corpus(index_dir / "corpus")
    retrieval_path = Path(args.retrieval_dir) / "retrieval_results.jsonl"
    rows = _latest_rows(retrieval_path)
    if any(row.get("status") != "SUCCESS" for row in rows):
        raise RuntimeError("validation retrieval is incomplete")
    truth = load_ground_truth(Path(args.data_root) / "validation/rca_ground_truth.jsonl")
    per_k, aggregates = evaluate_k_grid(truth, rows, corpus.documents)
    selection = select_k(aggregates, sha256_file(retrieval_path))
    output = Path(args.output)
    write_json(output, selection, exclusive=True)
    write_json(output.with_name("validation_k_metrics.json"), {str(k): value for k, value in aggregates.items()}, exclusive=True)
    for k, case_rows in per_k.items():
        write_jsonl(output.with_name(f"validation_retrieval_metrics_k{k}.jsonl"), case_rows, exclusive=True)
    print(json.dumps(selection, indent=2, sort_keys=True))
    return 0


def run_primary(args: argparse.Namespace) -> int:
    _require_live_flag(args, "run")
    index_dir = Path(args.index_dir)
    corpus, index, _ = _load_index(index_dir)
    routes = load_routes(Path(args.routes))
    if len(routes) != 439:
        raise RuntimeError(f"primary held-out run requires 439 routes, observed {len(routes)}")
    selection = json.loads(Path(args.selection_manifest).read_text(encoding="utf-8"))
    k = int(selection["selected_k"])
    output_dir = Path(args.output_root) / args.run_id
    first_stage = not output_dir.exists()
    if first_stage:
        output_dir.mkdir(parents=True, exist_ok=False)
    else:
        if (output_dir / "artifact_checksums.json").is_file():
            raise RuntimeError("primary RAG run is complete and immutable")
        stage_manifest_path = output_dir / "pre_live_stage_manifest.json"
        if not stage_manifest_path.is_file():
            raise RuntimeError("existing run directory is not a resumable pre-live RAG run")
        stage_manifest = json.loads(stage_manifest_path.read_text(encoding="utf-8"))
        if stage_manifest.get("decision") != "PHASE 5B READY FOR HELD-OUT RAG RUN":
            raise RuntimeError("pre-live gate is not READY")
    prompt = load_frozen_prompt(ROOT)
    prompt_path = output_dir / "frozen_reasoning_prompt.txt"
    if prompt_path.is_file():
        if prompt_path.read_text(encoding="utf-8") != prompt:
            raise RuntimeError("persisted frozen prompt changed")
    else:
        prompt_path.write_text(prompt, encoding="utf-8", newline="\n")
    query_tokens = 0
    known_anchor_failures = []
    for route in routes:
        try:
            query_tokens += build_query(route, corpus).token_count
        except AnchorResolutionError as exc:
            known_anchor_failures.append({"case_id": route["case_id"], "error": str(exc)})
    print(json.dumps({
        "model": REASONER_CONFIG.model_id, "query_embedding_model": EMBEDDING_CONFIG.model_id,
        "case_count": len(routes), "selected_K": k,
        "prompt_checksum": prompt_sha256(ROOT), "specification_checksum": SPEC_SHA256,
        "index_checksum": sha256_file(index_dir / "index_manifest.json"),
        "route_checksum": sha256_file(Path(args.routes)),
        "selection_checksum": sha256_file(Path(args.selection_manifest)),
        "output_directory": str(output_dir), "api_credentials_present": True,
        "estimated_query_embedding_tokens": query_tokens,
        "routes_with_no_cutoff_eligible_anchor": known_anchor_failures,
    }, indent=2, sort_keys=True))
    retrieval_dir = output_dir / "retrieval"
    retrieval_summary = run_retrieval(
        routes, corpus=corpus, client=OpenAIEmbeddingClient(), index=index, k=k,
        output_dir=retrieval_dir,
        index_manifest_sha256=sha256_file(index_dir / "index_manifest.json"),
    )
    results = {row["case_id"]: row for row in _latest_rows(retrieval_dir / "retrieval_results.jsonl")}
    unsupported_failures = [
        case_id for case_id, row in results.items()
        if row.get("status") not in {"SUCCESS", "ANCHOR_TECHNICAL_FAILURE"}
    ]
    if unsupported_failures:
        raise RuntimeError(
            f"retryable/permanent query-embedding retrieval failures remain: {unsupported_failures}"
        )
    anchor_technical_ids = _checkpoint_retrieval_technical_predictions(results, output_dir)
    documents = corpus.by_record_id()
    cases = []
    for route in routes:
        result = results[route["case_id"]]
        if result.get("status") == "ANCHOR_TECHNICAL_FAILURE":
            continue
        ids = result["retrieved_record_ids"]
        cases.append(build_reasoning_case(route, ids, [documents[value].text for value in ids]))
    context = context_preflight(cases, prompt)
    context["terminal_anchor_technical_failure_count"] = len(anchor_technical_ids)
    context["terminal_anchor_technical_failure_case_ids"] = anchor_technical_ids
    context["all_routes_accounted_for"] = len(cases) + len(anchor_technical_ids) == len(routes)
    context_path = output_dir / "context_size_audit.json"
    if context_path.is_file():
        if json.loads(context_path.read_text(encoding="utf-8")) != context:
            raise RuntimeError("context-size audit changed between paid execution stages")
    else:
        write_json(context_path, context, exclusive=True)
    if context["status"] != "PASS":
        raise RuntimeError("context-size preflight failed; K is unchanged and reasoning is blocked")
    if first_stage:
        graph = no_graph_audit(ROOT)
        leakage = corpus_leakage_audit(corpus)
        secrets = repository_secret_audit(ROOT)
        phase5_tests_status = "FAIL"
        if args.preflight_dir:
            preflight_dir = Path(args.preflight_dir)
            preflight_manifest = json.loads((preflight_dir / "run_manifest.json").read_text(encoding="utf-8"))
            preflight_gate = json.loads((preflight_dir / "pre_embedding_gate.json").read_text(encoding="utf-8"))
            same_implementation = preflight_manifest.get("implementation_sha256") == sha256_tree(ROOT / "src/rag")
            if same_implementation:
                phase5_tests_status = "PASS" if preflight_gate.get("tests", {}).get("phase5", {}).get("passed") else "FAIL"
            else:
                # A documented defect correction invalidates the old code hash.
                phase5_tests_status = "PASS" if _run_phase5_tests()["passed"] else "FAIL"
        else:
            phase5_tests_status = "PASS" if _run_phase5_tests()["passed"] else "FAIL"
        blockers = []
        checks = {
            "context size": context["status"], "no graph": graph["status"],
            "runtime leakage": leakage["status"], "secret": secrets["status"],
            "Phase 5 tests": phase5_tests_status,
            "index vector count": "PASS" if len(index.record_ids) == EXPECTED_DOCUMENT_COUNT else "FAIL",
        }
        checks["retrieval completeness"] = "PASS" if (
            len(results) == 439
            and all(
                (row.get("status") == "SUCCESS" and len(row["retrieved_record_ids"]) == k)
                or (row.get("status") == "ANCHOR_TECHNICAL_FAILURE" and not row["retrieved_record_ids"])
                for row in results.values()
            )
        ) else "FAIL"
        blockers.extend(f"{name}: {status}" for name, status in checks.items() if status != "PASS")
        decision = "PHASE 5B READY FOR HELD-OUT RAG RUN" if not blockers else "PHASE 5B NOT READY FOR HELD-OUT RAG RUN"
        values = {
            "frozen_spec_sha256": SPEC_SHA256,
            "corpus_text_manifest_sha256": corpus.text_manifest_sha256,
            "embedding_matrix_sha256": sha256_file(index_dir / "embeddings.npy"),
            "index_manifest_sha256": sha256_file(index_dir / "index_manifest.json"),
            "selected_k": k, "selection_sha256": sha256_file(Path(args.selection_manifest)),
            "query_version": QUERY_VERSION,
            "query_builder_sha256": sha256_file(ROOT / "src/rag/query.py"),
            "prompt_sha256": prompt_sha256(ROOT), "model_id": REASONER_CONFIG.model_id,
            "context_status": context["status"], "no_graph_status": graph["status"],
            "leakage_status": leakage["status"], "label_isolation_status": "PASS",
            "secret_status": secrets["status"], "phase5_tests_status": phase5_tests_status,
            "api_mocks_status": phase5_tests_status, "protocol_deviations": "NONE",
            "terminal_anchor_technical_failure_count": len(anchor_technical_ids),
            "terminal_anchor_technical_failure_case_ids": anchor_technical_ids,
            "blockers": blockers, "decision": decision,
        }
        write_json(output_dir / "pre_live_audit.json", values, exclusive=True)
        (output_dir / "rag_pre_live_run_audit_v1.0.md").write_text(
            render_pre_live_markdown(values), encoding="utf-8", newline="\n"
        )
        (output_dir / "protocol_deviations.md").write_text(
            "# Protocol Deviations\n\nNONE.\n", encoding="utf-8", newline="\n"
        )
        write_json(output_dir / "pre_live_stage_manifest.json", {
            "run_id": args.run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "PRIMARY_RAG_RETRIEVAL_AND_PRELIVE_API",
            "decision": decision, "generation_api_calls_made": False,
            "retrieval_summary": retrieval_summary.serializable(),
            "terminal_anchor_technical_failure_case_ids": anchor_technical_ids,
            "context_audit_sha256": sha256_file(context_path),
            "pre_live_audit_sha256": sha256_file(output_dir / "pre_live_audit.json"),
            "implementation_sha256": sha256_tree(ROOT / "src/rag"),
        }, exclusive=True)
        print(decision)
        return 0 if not blockers else 1
    reasoning_summary = run_reasoning_cases(
        cases, client=OpenAIReasonerClient(), prompt=prompt, selected_k=k,
        run_dir=output_dir / "generation",
    )
    generation_ledger = _latest_rows(output_dir / "generation/request_ledger.jsonl")
    retryable_remaining = [
        row["case_id"] for row in generation_ledger
        if row.get("status") in {"TRANSIENT_API_ERROR", "TRANSIENT_API_FAILURE_EXHAUSTED"}
    ]
    if retryable_remaining:
        print(json.dumps({
            "reasoning": reasoning_summary.serializable(),
            "retryable_cases_remaining": retryable_remaining,
            "run_finalized": False,
        }, indent=2, sort_keys=True))
        return 1
    predictions = _latest_rows(output_dir / "generation/predictions.jsonl")
    costs = pricing_report(predictions)
    write_json(output_dir / "generation_costs.json", costs, exclusive=True)
    write_json(output_dir / "run_manifest.json", {
        "run_id": args.run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PRIMARY_STANDARD_RAG_API", "frozen_spec_sha256": SPEC_SHA256,
        "selected_k": k, "selection_sha256": sha256_file(Path(args.selection_manifest)),
        "index_manifest_sha256": sha256_file(index_dir / "index_manifest.json"),
        "routes_sha256": sha256_file(Path(args.routes)), "prompt_sha256": prompt_sha256(ROOT),
        "output_schema_sha256": __import__("hashlib").sha256(canonical_output_schema().encode()).hexdigest(),
        "retrieval_summary": retrieval_summary.serializable(),
        "reasoning_summary": reasoning_summary.serializable(),
        "terminal_anchor_technical_failure_case_ids": anchor_technical_ids,
        "primary_ground_truth_sources_opened": [], "oracle_retrieval_used": False,
        "graph_retrieval_used": False, "paid_api_calls_made": True,
        "pre_live_stage_manifest_sha256": sha256_file(output_dir / "pre_live_stage_manifest.json"),
        "generation_began_after_ready_pre_live_gate": True,
    }, exclusive=True)
    write_checksum_manifest(output_dir)
    print(json.dumps({
        "retrieval": retrieval_summary.serializable(),
        "reasoning": reasoning_summary.serializable(), "generation_costs": costs,
    }, indent=2, sort_keys=True))
    return 0


def evaluate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    index_dir = Path(args.index_dir)
    corpus = load_persisted_corpus(index_dir / "corpus")
    truth_path = Path(args.data_root) / "test/rca_ground_truth.jsonl"
    truth = load_ground_truth(truth_path)
    labels = {str(row["case_id"]): str(row["failure_type"]) for row in truth}
    retrieval = _latest_rows(run_dir / "retrieval/retrieval_results.jsonl")
    predictions = _latest_rows(run_dir / "generation/predictions.jsonl")
    if len(predictions) != 439 or len(retrieval) != 439:
        raise RuntimeError("held-out run is incomplete; evaluation refused")
    doc_by_id = corpus.by_record_id()
    retrieval_by_id = {str(row["case_id"]): row for row in retrieval}
    resolved = {str(case["case_id"]): resolve_evidence(case, corpus.documents) for case in truth}
    case_metrics = []
    for case in truth:
        case_id = str(case["case_id"])
        raw = retrieval_by_id[case_id]
        metrics = retrieval_case_metrics(
            resolved[case_id], raw["retrieved_record_ids"], doc_by_id,
        )
        case_metrics.append({
            **metrics,
            "scores": raw.get("scores", []),
            "query_sha256": raw.get("query_sha256"),
            "query_embedding_input_tokens": raw.get("query_embedding_input_tokens", 0),
            "query_embedding_latency_ms": raw.get("query_embedding_latency_ms", 0),
            "index_search_latency_ms": raw.get("index_search_latency_ms", 0),
            "retrieval_latency_ms": raw.get("retrieval_latency_ms", 0),
        })
    output = run_dir / "offline_evaluation"
    output.mkdir(parents=True, exist_ok=False)
    classification = classification_metrics(predictions, labels)
    retrieval_aggregate = aggregate_retrieval(case_metrics)
    prediction_by_id = {str(row["case_id"]): row for row in predictions}
    adjudication_by_id: dict[str, dict[str, Any]] = {}
    if args.evidence_adjudication:
        adjudication_by_id = {
            str(row["case_id"]): row for row in load_jsonl(Path(args.evidence_adjudication))
        }
    evidence_rows = [
        evidence_prediction_metrics(
            case, prediction_by_id[str(case["case_id"])], resolved[str(case["case_id"])], doc_by_id,
            adjudication=adjudication_by_id.get(str(case["case_id"])),
        )
        for case in truth
    ]
    evidence_aggregate = aggregate_evidence(evidence_rows)
    rules_predictions: list[dict[str, Any]] = []
    rules_insufficient_ids: set[str] = set()
    comparisons: dict[str, Any] = {
        "direct_llm": {
            "status": "PENDING",
            "reason": "No valid complete Direct LLM held-out inference exists; partial validation stability is not extrapolated.",
        }
    }
    rules_path = Path(args.rules_predictions) if args.rules_predictions else None
    if rules_path and rules_path.is_file():
        rules_predictions = _latest_rows(rules_path)
        rules_insufficient_ids = {
            str(row["case_id"]) for row in rules_predictions if row.get("status") == "INSUFFICIENT_EVIDENCE"
        }
        if len(rules_insufficient_ids) != 50:
            raise RuntimeError(
                f"authoritative Rules/SQL insufficient subset changed: expected 50, observed {len(rules_insufficient_ids)}"
            )
        comparison, paired_rows = paired_comparison(predictions, rules_predictions, labels, "rules_sql")
        comparisons["rules_sql"] = comparison
        write_jsonl(output / "rules_sql_paired_cases.jsonl", paired_rows, exclusive=True)
    ml_path = Path(args.ml_predictions) if args.ml_predictions else None
    if ml_path and ml_path.is_file():
        ml_predictions = _latest_rows(ml_path)
        comparison, paired_rows = paired_comparison(predictions, ml_predictions, labels, "classical_ml")
        evidence_by_id = {str(row["case_id"]): row for row in evidence_rows}
        ml_by_id = {str(row["case_id"]): row for row in ml_predictions}
        for row in paired_rows:
            case_id = str(row["case_id"])
            row["ml_has_source_evidence"] = bool(ml_by_id[case_id].get("evidence_record_ids"))
            row["rag_observable_grounded"] = evidence_by_id[case_id]["observable_grounded_reconciliation"]
            row["rag_fully_grounded"] = evidence_by_id[case_id]["fully_grounded_reconciliation"]
        comparisons["classical_ml"] = comparison
        write_jsonl(output / "classical_ml_paired_cases.jsonl", paired_rows, exclusive=True)
    strata = stratified_results(truth, predictions, case_metrics, evidence_rows, rules_insufficient_ids)

    oracle_by_id: dict[str, dict[str, Any]] = {}
    if args.oracle_predictions:
        oracle_by_id = {str(row["case_id"]): row for row in _latest_rows(Path(args.oracle_predictions))}
    retrieval_metric_by_id = {str(row["case_id"]): row for row in case_metrics}
    evidence_by_id = {str(row["case_id"]): row for row in evidence_rows}
    attribution_rows = [
        attribute_failure(
            case, prediction_by_id[str(case["case_id"])],
            retrieval_metric_by_id[str(case["case_id"])], evidence_by_id[str(case["case_id"])],
            oracle_by_id.get(str(case["case_id"])),
        )
        for case in truth
    ]
    attribution_summary = dict(sorted(Counter(row["attribution"] for row in attribution_rows).items()))

    embedding_summary = json.loads((index_dir / "embedding_summary.json").read_text(encoding="utf-8"))
    accounting = end_to_end_accounting(retrieval, predictions, embedding_summary)
    write_jsonl(output / "cost_latency_per_case.jsonl", accounting.pop("per_case"), exclusive=True)
    compression: dict[str, Any] = {
        "status": "PENDING", "reason": "No Direct LLM packet artifact supplied."
    }
    direct_packet_path = Path(args.direct_packets) if args.direct_packets else None
    if direct_packet_path and direct_packet_path.is_file():
        compression, compression_rows = direct_packet_compression(case_metrics, load_jsonl(direct_packet_path))
        compression["status"] = "COMPLETE_DETERMINISTIC_PACKET_COMPARISON"
        write_jsonl(output / "direct_llm_context_compression_cases.jsonl", compression_rows, exclusive=True)
    write_jsonl(output / "retrieval_case_metrics.jsonl", case_metrics, exclusive=True)
    write_jsonl(output / "evidence_case_metrics.jsonl", evidence_rows, exclusive=True)
    write_jsonl(output / "failure_attribution.jsonl", attribution_rows, exclusive=True)
    write_json(output / "classification_metrics.json", classification, exclusive=True)
    write_json(output / "retrieval_metrics.json", retrieval_aggregate, exclusive=True)
    write_json(output / "evidence_metrics.json", evidence_aggregate, exclusive=True)
    write_json(output / "stratified_results.json", strata, exclusive=True)
    write_json(output / "failure_attribution_summary.json", attribution_summary, exclusive=True)
    write_json(output / "paired_comparisons.json", comparisons, exclusive=True)
    write_json(output / "cost_latency_summary.json", accounting, exclusive=True)
    write_json(output / "direct_llm_context_compression.json", compression, exclusive=True)
    (output / "protocol_deviations.md").write_text(
        "# Protocol Deviations\n\nNONE.\n", encoding="utf-8", newline="\n"
    )
    write_json(output / "evaluation_manifest.json", {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "api_calls_made": False,
        "ground_truth_sha256": sha256_file(truth_path),
        "predictions_sha256": sha256_file(run_dir / "generation/predictions.jsonl"),
        "retrieval_sha256": sha256_file(run_dir / "retrieval/retrieval_results.jsonl"),
        "classification": classification, "retrieval": retrieval_aggregate,
        "evidence": evidence_aggregate, "failure_attribution": attribution_summary,
        "paired_comparisons": comparisons,
        "direct_llm_accuracy_latency_cost_comparison": "PENDING",
        "manual_evidence_adjudication_status": evidence_aggregate["manual_review_status"],
    }, exclusive=True)
    write_checksum_manifest(output)
    print(json.dumps({
        "classification": classification, "retrieval": retrieval_aggregate,
        "evidence": evidence_aggregate, "attribution": attribution_summary,
        "comparisons": comparisons, "compression": compression,
    }, indent=2, sort_keys=True))
    return 0


def audit_no_graph(args: argparse.Namespace) -> int:
    audit = no_graph_audit(ROOT)
    print(render_no_graph_markdown(audit))
    return 0 if audit["status"] == "PASS" else 1


def oracle_diagnostic(args: argparse.Namespace) -> int:
    _require_live_flag(args, "oracle-diagnostic")
    primary_dir = Path(args.primary_run_dir)
    primary_predictions = primary_dir / "generation/predictions.jsonl"
    primary_manifest = primary_dir / "run_manifest.json"
    if not primary_predictions.is_file() or not primary_manifest.is_file():
        raise RuntimeError("immutable primary RAG outputs must exist before oracle diagnostic")
    primary = json.loads(primary_manifest.read_text(encoding="utf-8"))
    if primary.get("mode") != "PRIMARY_STANDARD_RAG_API":
        raise RuntimeError("oracle diagnostic requires a completed primary Standard RAG run")
    routes = load_routes(Path(args.routes))
    corpus = load_persisted_corpus(Path(args.index_dir) / "corpus")
    truth_path = Path(args.data_root) / "test/rca_ground_truth.jsonl"
    truth = load_ground_truth(truth_path)
    oracle_cases = build_oracle_cases(routes, truth, corpus)
    prompt = load_frozen_prompt(ROOT)
    preflight_audit = context_preflight(
        [value.reasoning_case for value in oracle_cases], prompt
    )
    if preflight_audit["status"] != "PASS":
        raise RuntimeError("oracle context-size preflight failed")
    output_dir = Path(args.output_root) / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "frozen_reasoning_prompt.txt").write_text(
        prompt, encoding="utf-8", newline="\n"
    )
    write_json(output_dir / "context_size_audit.json", preflight_audit, exclusive=True)
    write_jsonl(output_dir / "oracle_context_manifest.jsonl", ({
        "case_id": value.reasoning_case.route["case_id"],
        "required_record_ids": list(value.required_record_ids),
        "absence_only_tables": list(value.absence_only_tables),
        "context_payload_sha256": value.reasoning_case.payload_sha256,
        "failure_label_supplied": False, "synthetic_absence_statement_supplied": False,
    } for value in oracle_cases), exclusive=True)
    print(json.dumps({
        "model": REASONER_CONFIG.model_id, "case_count": len(oracle_cases),
        "method": "oracle_evidence_context_diagnostic",
        "prompt_checksum": prompt_sha256(ROOT), "specification_checksum": SPEC_SHA256,
        "primary_predictions_checksum": sha256_file(primary_predictions),
        "ground_truth_used_only_for_G_i_resolution": True,
        "output_directory": str(output_dir), "api_credentials_present": True,
        "estimated_input_tokens": preflight_audit["total_estimated_input_tokens"],
    }, indent=2, sort_keys=True))
    totals = Counter()
    client = OpenAIReasonerClient()
    for oracle_case in oracle_cases:
        summary = run_reasoning_cases(
            [oracle_case.reasoning_case], client=client, prompt=prompt,
            selected_k=len(oracle_case.required_record_ids), run_dir=output_dir / "generation",
        )
        totals.update(summary.serializable())
    raw_predictions = _latest_rows(output_dir / "generation/predictions.jsonl")
    diagnostic_predictions = []
    for prediction in raw_predictions:
        diagnostic_predictions.append({
            **prediction,
            "model_schema_method": prediction.get("method"),
            "method": "oracle_evidence_context_diagnostic",
        })
    write_jsonl(output_dir / "diagnostic_predictions.jsonl", diagnostic_predictions, exclusive=True)
    write_json(output_dir / "run_manifest.json", {
        "run_id": args.run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "ORACLE_EVIDENCE_CONTEXT_DIAGNOSTIC_API",
        "method": "oracle_evidence_context_diagnostic", "paid_api_calls_made": True,
        "primary_predictions_sha256": sha256_file(primary_predictions),
        "primary_run_manifest_sha256": sha256_file(primary_manifest),
        "ground_truth_sha256": sha256_file(truth_path),
        "prompt_sha256": prompt_sha256(ROOT), "frozen_spec_sha256": SPEC_SHA256,
        "primary_predictions_replaced_or_repaired": False,
        "failure_labels_given_to_reasoner": False,
        "absence_limit_qualified": True,
        "summary": dict(totals),
    }, exclusive=True)
    write_checksum_manifest(output_dir)
    print(json.dumps(dict(totals), indent=2, sort_keys=True))
    return 0 if totals["unresolved_cases"] == 0 else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    sub = value.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight", help="build and audit the frozen corpus without API calls")
    p.add_argument("--data-root", default="data/benchmark")
    p.add_argument("--output-root", default="results/rag")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=preflight)
    p = sub.add_parser("prepare-routes", help="isolate three-field unlabeled routes")
    p.add_argument("--data-root", default="data/benchmark")
    p.add_argument("--split", choices=("validation", "test", "challenge_test"), required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=prepare_route_artifact)
    p = sub.add_parser("build-index", help="make paid immutable corpus embeddings and exact index")
    p.add_argument("--data-root", default="data/benchmark")
    p.add_argument("--output-root", default="results/rag")
    p.add_argument("--run-id", required=True)
    p.add_argument("--execute-api", action="store_true")
    p.set_defaults(func=build_index)
    p = sub.add_parser("validation-retrieve", help="retrieve validation Top-40 using paid query embeddings")
    p.add_argument("--index-dir", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--output-root", default="results/rag")
    p.add_argument("--run-id", required=True)
    p.add_argument("--execute-api", action="store_true")
    p.set_defaults(func=validation_retrieve)
    p = sub.add_parser("select-k", help="evaluate saved validation Top-40 and lock K offline")
    p.add_argument("--data-root", default="data/benchmark")
    p.add_argument("--index-dir", required=True)
    p.add_argument("--retrieval-dir", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=lock_selection)
    p = sub.add_parser("run", help="primary retrieval plus one frozen reasoner call per route")
    p.add_argument("--index-dir", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--selection-manifest", required=True)
    p.add_argument("--preflight-dir", help="immutable no-cost pre-embedding run used to reuse locked test evidence")
    p.add_argument("--output-root", default="results/rag")
    p.add_argument("--run-id", required=True)
    p.add_argument("--execute-api", action="store_true")
    p.set_defaults(func=run_primary)
    p = sub.add_parser("evaluate", help="offline held-out evaluation; never calls an API")
    p.add_argument("--data-root", default="data/benchmark")
    p.add_argument("--index-dir", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--rules-predictions", default="results/rules_sql/phase2_rules_sql_v1_0_20260808T185000Z_auditfix1/predictions.jsonl")
    p.add_argument("--ml-predictions", default="results/classical_ml/phase3_classical_ml_v1_0_20260808T213000Z_auditfix1/predictions.jsonl")
    p.add_argument("--direct-packets", default="results/direct_llm/phase4_direct_llm_preflight_v1_0_20260809T063242Z/test_packets.jsonl")
    p.add_argument("--oracle-predictions")
    p.add_argument("--evidence-adjudication", help="optional two-reviewer adjudication JSONL")
    p.set_defaults(func=evaluate)
    p = sub.add_parser("audit-no-graph", help="static and manual Standard RAG boundary audit")
    p.set_defaults(func=audit_no_graph)
    p = sub.add_parser("oracle-diagnostic", help="separate post-primary paid Oracle Evidence Context Diagnostic")
    p.add_argument("--data-root", default="data/benchmark")
    p.add_argument("--index-dir", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--primary-run-dir", required=True)
    p.add_argument("--output-root", default="results/rag")
    p.add_argument("--run-id", required=True)
    p.add_argument("--execute-api", action="store_true")
    p.set_defaults(func=oracle_diagnostic)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
