"""Frozen component-separated token, latency, cost, and context-compression accounting."""

from __future__ import annotations

import statistics
from typing import Any, Sequence

from src.rag.config import EMBEDDING_CONFIG, REASONER_CONFIG
from src.rag.tokens import percentile


def numeric_summary(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "total": sum(ordered),
        "mean": statistics.fmean(ordered) if ordered else 0.0,
        "median": percentile(ordered, 0.5) if ordered else 0.0,
        "p95": percentile(ordered, 0.95) if ordered else 0.0,
        "p99": percentile(ordered, 0.99) if ordered else 0.0,
        "minimum": min(ordered, default=0.0),
        "maximum": max(ordered, default=0.0),
    }


def end_to_end_accounting(
    retrieval_rows: Sequence[dict[str, Any]],
    prediction_rows: Sequence[dict[str, Any]],
    embedding_summary: dict[str, Any],
) -> dict[str, Any]:
    retrieval_by_id = {str(row["case_id"]): row for row in retrieval_rows}
    prediction_by_id = {str(row["case_id"]): row for row in prediction_rows}
    if set(retrieval_by_id) != set(prediction_by_id):
        raise RuntimeError("retrieval/generation cases disagree for cost accounting")
    per_case = []
    for case_id in retrieval_by_id:
        retrieval = retrieval_by_id[case_id]
        prediction = prediction_by_id[case_id]
        query_tokens = int(retrieval.get("query_embedding_input_tokens", 0) or 0)
        usage = prediction.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        cached_tokens = int(usage.get("cached_input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        query_cost = query_tokens * EMBEDDING_CONFIG.usd_per_million_input_tokens / 1_000_000
        generation_cost = (
            max(0, input_tokens - cached_tokens) * REASONER_CONFIG.input_usd_per_million_tokens
            + cached_tokens * REASONER_CONFIG.cached_input_usd_per_million_tokens
            + output_tokens * REASONER_CONFIG.output_usd_per_million_tokens
        ) / 1_000_000
        retrieval_latency = float(retrieval.get("retrieval_latency_ms", 0) or 0)
        generation_latency = float(prediction.get("latency_ms", 0) or 0)
        assembly_latency = float(prediction.get("context_assembly_latency_ms", 0) or 0)
        per_case.append({
            "case_id": case_id,
            "query_embedding_input_tokens": query_tokens,
            "query_embedding_cost_usd": query_cost,
            "query_api_latency_ms": float(retrieval.get("query_embedding_latency_ms", 0) or 0),
            "local_index_latency_ms": float(retrieval.get("index_search_latency_ms", 0) or 0),
            "retrieval_latency_ms": retrieval_latency,
            "generation_input_tokens": input_tokens,
            "generation_cached_input_tokens": cached_tokens,
            "generation_output_tokens": output_tokens,
            "generation_reasoning_tokens": int(usage.get("reasoning_tokens", 0) or 0),
            "generation_cost_usd": generation_cost,
            "generation_latency_ms": generation_latency,
            "context_assembly_latency_ms": assembly_latency,
            "marginal_cost_usd": query_cost + generation_cost,
            "end_to_end_latency_ms": retrieval_latency + assembly_latency + generation_latency,
        })
    case_count = len(per_case)
    embedding_cost = float(embedding_summary.get("corpus_embedding_cost_usd", 0) or 0)
    return {
        "pricing": {
            "embedding_reference_date": EMBEDDING_CONFIG.pricing_reference_date,
            "embedding_usd_per_million_input_tokens": EMBEDDING_CONFIG.usd_per_million_input_tokens,
            "generation_reference_date": REASONER_CONFIG.pricing_reference_date,
            "generation_input_usd_per_million_tokens": REASONER_CONFIG.input_usd_per_million_tokens,
            "generation_cached_input_usd_per_million_tokens": REASONER_CONFIG.cached_input_usd_per_million_tokens,
            "generation_output_usd_per_million_tokens": REASONER_CONFIG.output_usd_per_million_tokens,
        },
        "corpus_indexing": {
            "input_tokens": int(embedding_summary.get("total_embedding_tokens", 0) or 0),
            "request_count": int(embedding_summary.get("expected_batches", embedding_summary.get("request_count", 0)) or 0),
            "retry_count": int(embedding_summary.get("retry_events", 0) or 0),
            "one_time_cost_usd": embedding_cost,
            "amortization_case_count": case_count,
            "amortized_cost_per_case_usd": embedding_cost / case_count if case_count else 0.0,
        },
        "query_embedding_tokens": numeric_summary([row["query_embedding_input_tokens"] for row in per_case]),
        "query_embedding_cost_usd": numeric_summary([row["query_embedding_cost_usd"] for row in per_case]),
        "query_api_latency_ms": numeric_summary([row["query_api_latency_ms"] for row in per_case]),
        "local_index_latency_ms": numeric_summary([row["local_index_latency_ms"] for row in per_case]),
        "retrieval_latency_ms": numeric_summary([row["retrieval_latency_ms"] for row in per_case]),
        "generation_latency_ms": numeric_summary([row["generation_latency_ms"] for row in per_case]),
        "context_assembly_latency_ms": numeric_summary([row["context_assembly_latency_ms"] for row in per_case]),
        "end_to_end_latency_ms": numeric_summary([row["end_to_end_latency_ms"] for row in per_case]),
        "marginal_cost_usd": numeric_summary([row["marginal_cost_usd"] for row in per_case]),
        "sequential_throughput_cases_per_second": (
            case_count / (sum(row["end_to_end_latency_ms"] for row in per_case) / 1000)
            if per_case and sum(row["end_to_end_latency_ms"] for row in per_case) else 0.0
        ),
        "per_case": per_case,
    }


def direct_packet_compression(
    retrieved_context: Sequence[dict[str, Any]], direct_packets: Sequence[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    packet_by_id = {str(row["case_id"]): row for row in direct_packets}
    rows = []
    for context in retrieved_context:
        case_id = str(context["case_id"])
        if case_id not in packet_by_id:
            raise RuntimeError(f"Direct LLM packet missing for RAG case {case_id}")
        packet = packet_by_id[case_id]
        rag_chars = int(context["retrieved_context_characters"])
        rag_tokens = (rag_chars + 2) // 3
        packet_chars = len(str(packet["serialized_packet"]))
        packet_tokens = (packet_chars + 2) // 3
        rag_records = int(context["retrieval_set_size"])
        direct_records = int(packet["record_count"])
        rows.append({
            "case_id": case_id, "rag_context_characters": rag_chars,
            "rag_context_estimated_tokens": rag_tokens,
            "direct_packet_characters": packet_chars,
            "direct_packet_estimated_tokens": packet_tokens,
            "rag_record_count": rag_records, "direct_packet_record_count": direct_records,
            "context_reduction": 1 - rag_tokens / packet_tokens if packet_tokens else 0.0,
            "record_count_reduction": 1 - rag_records / direct_records if direct_records else 0.0,
        })
    return {
        "case_count": len(rows), "estimator": "ceil(Unicode characters / 3)",
        "rag_context_estimated_tokens": numeric_summary([row["rag_context_estimated_tokens"] for row in rows]),
        "direct_packet_estimated_tokens": numeric_summary([row["direct_packet_estimated_tokens"] for row in rows]),
        "context_reduction": numeric_summary([row["context_reduction"] for row in rows]),
        "record_count_reduction": numeric_summary([row["record_count_reduction"] for row in rows]),
    }, rows
