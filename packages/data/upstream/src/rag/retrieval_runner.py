"""Checkpointed one-shot query embedding and exact retrieval execution."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Callable, Sequence

from src.direct_llm.client import PermanentAPIError, TransientAPIError
from src.rag.artifacts import append_jsonl, canonical_json, sha256_bytes
from src.rag.config import EMBEDDING_CONFIG, SPEC_SHA256, EmbeddingConfig
from src.rag.corpus import FrozenCorpus
from src.rag.embeddings import EmbeddingClient
from src.rag.index import ExactFlatCosineNumpyV1
from src.rag.query import AnchorResolutionError, build_query
from src.rag.retriever import retrieve_once


def _latest(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                rows[str(row["case_id"])] = row
    return rows


@dataclass(frozen=True)
class RetrievalRunSummary:
    total_cases: int
    successful_cases: int
    skipped_successes: int
    failed_cases: int
    retry_events: int
    anchor_technical_failures: int

    def serializable(self) -> dict[str, int]:
        return self.__dict__.copy()


def run_retrieval(
    routes: Sequence[dict[str, str]],
    *,
    corpus: FrozenCorpus,
    client: EmbeddingClient,
    index: ExactFlatCosineNumpyV1,
    k: int,
    output_dir: Path,
    index_manifest_sha256: str,
    config: EmbeddingConfig = EMBEDDING_CONFIG,
    sleeper: Callable[[float], None] = time.sleep,
) -> RetrievalRunSummary:
    output_dir.mkdir(parents=True, exist_ok=True)
    queries_path = output_dir / "queries.jsonl"
    results_path = output_dir / "retrieval_results.jsonl"
    ledger_path = output_dir / "retrieval_ledger.jsonl"
    prior_queries = _latest(queries_path)
    prior = _latest(ledger_path)
    successful = skipped = failed = retries = anchor_failures = 0

    for route in routes:
        query_started = perf_counter_ns()
        case_id = route["case_id"]
        try:
            query = build_query(route, corpus)
        except AnchorResolutionError as exc:
            failure_hash = sha256_bytes(canonical_json({
                "spec_sha256": SPEC_SHA256,
                "route": route,
                "index_manifest_sha256": index_manifest_sha256,
                "K": k,
                "status": "ANCHOR_TECHNICAL_FAILURE",
                "error": str(exc),
            }))
            previous = prior.get(case_id)
            if previous:
                if previous.get("request_hash") != failure_hash:
                    raise RuntimeError(f"anchor failure identity changed on resume for {case_id}")
                if previous.get("status") == "ANCHOR_TECHNICAL_FAILURE":
                    failed += 1
                    anchor_failures += 1
                    continue
            append_jsonl(queries_path, {
                "case_id": case_id,
                "primary_entity_type": route["primary_entity_type"],
                "primary_entity_id": route["primary_entity_id"],
                "query": None,
                "query_sha256": None,
                "query_build_status": "ANCHOR_TECHNICAL_FAILURE",
                "error": str(exc),
                "case_id_embedded": False,
            })
            failure_row = {
                "case_id": case_id, "request_hash": failure_hash,
                "status": "ANCHOR_TECHNICAL_FAILURE", "attempt_count": 0,
                "error_category": "ANCHOR_TECHNICAL_FAILURE", "error_detail": str(exc),
                "query_embedding_operations": 0, "retrieval_operations": 0,
                "retrieved_record_ids": [], "scores": [],
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            append_jsonl(ledger_path, failure_row)
            append_jsonl(results_path, failure_row)
            prior[case_id] = failure_row
            failed += 1
            anchor_failures += 1
            continue
        query_construction_latency_ms = (perf_counter_ns() - query_started) / 1_000_000
        request_hash = sha256_bytes(canonical_json({
            "spec_sha256": SPEC_SHA256,
            "query_sha256": query.sha256,
            "embedding_configuration": config.serializable(),
            "index_manifest_sha256": index_manifest_sha256,
            "K": k,
            "operations": ["one_query_embedding", "one_global_exact_flat_cosine_search"],
        }))
        previous_query = prior_queries.get(case_id)
        if previous_query:
            if previous_query.get("query_sha256") != query.sha256:
                raise RuntimeError(f"query changed on resume for {case_id}")
        else:
            append_jsonl(queries_path, query.artifact_row())
        previous = prior.get(case_id)
        if previous:
            if previous.get("request_hash") != request_hash:
                raise RuntimeError(f"retrieval request changed on resume for {case_id}")
            if previous.get("status") == "SUCCESS":
                skipped += 1
                successful += 1
                continue
            if previous.get("status") in {"PERMANENT_API_ERROR", "ANCHOR_TECHNICAL_FAILURE"}:
                failed += 1
                anchor_failures += int(previous.get("status") == "ANCHOR_TECHNICAL_FAILURE")
                continue
        prior_attempts = int(previous.get("attempt_count", 0)) if previous else 0
        for local_attempt in range(1, config.max_attempts + 1):
            attempt = prior_attempts + local_attempt
            try:
                result = retrieve_once(query, client=client, index=index, k=k)
            except TransientAPIError as exc:
                exhausted = local_attempt == config.max_attempts
                status = "TRANSIENT_API_FAILURE_EXHAUSTED" if exhausted else "TRANSIENT_API_ERROR"
                row = {
                    "case_id": case_id, "request_hash": request_hash, "status": status,
                    "attempt_count": attempt, "error_category": exc.category,
                    "error_detail": exc.detail,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
                append_jsonl(ledger_path, row)
                prior[case_id] = row
                if exhausted:
                    append_jsonl(results_path, {
                        "case_id": case_id, "status": status, "request_hash": request_hash,
                        "retrieved_record_ids": [], "scores": [], "attempt_count": attempt,
                    })
                    failed += 1
                    break
                retries += 1
                sleeper(config.backoff_seconds[local_attempt - 1])
                continue
            except PermanentAPIError as exc:
                row = {
                    "case_id": case_id, "request_hash": request_hash,
                    "status": "PERMANENT_API_ERROR", "attempt_count": attempt,
                    "error_category": exc.category, "error_detail": exc.detail,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
                append_jsonl(ledger_path, row)
                append_jsonl(results_path, {
                    "case_id": case_id, "status": "PERMANENT_API_ERROR",
                    "request_hash": request_hash, "retrieved_record_ids": [],
                    "scores": [], "attempt_count": attempt,
                })
                prior[case_id] = row
                failed += 1
                break
            result_row = {
                **result.artifact_row(), "status": "SUCCESS", "request_hash": request_hash,
                "attempt_count": attempt,
                "query_construction_latency_ms": query_construction_latency_ms,
                "retrieval_latency_ms": query_construction_latency_ms
                + result.query_embedding_latency_ms + result.index_search_latency_ms,
            }
            append_jsonl(results_path, result_row)
            row = {
                "case_id": case_id, "request_hash": request_hash, "status": "SUCCESS",
                "attempt_count": attempt, "query_embedding_input_tokens": result.query_embedding_input_tokens,
                "query_embedding_latency_ms": result.query_embedding_latency_ms,
                "index_search_latency_ms": result.index_search_latency_ms,
                "query_construction_latency_ms": query_construction_latency_ms,
                "retrieved_record_ids": [hit.record_id for hit in result.hits],
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            append_jsonl(ledger_path, row)
            prior[case_id] = row
            successful += 1
            break
    return RetrievalRunSummary(
        len(routes), successful, skipped, failed, retries, anchor_failures
    )
