"""Retrieved-only reasoning requests, exact hashing, clients, mocks, and preflight."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import Any, Protocol, Sequence

from src.direct_llm.client import (
    PermanentAPIError,
    TransientAPIError,
    Usage,
    classify_openai_exception,
)
from src.rag.artifacts import canonical_json, sha256_bytes
from src.rag.config import (
    DECISION_CUTOFF,
    OUTPUT_SCHEMA_VERSION,
    REASONER_CONFIG,
    SPEC_SHA256,
    ReasonerConfig,
)
from src.rag.leakage import assert_payload_label_blind, assert_route
from src.rag.schemas import RAGPrediction, canonical_output_schema
from src.rag.tokens import conservative_generation_tokens


@dataclass(frozen=True)
class ReasoningCase:
    route: dict[str, str]
    retrieved_record_ids: tuple[str, ...]
    retrieved_record_texts: tuple[str, ...]
    payload: str
    payload_sha256: str
    context_assembly_latency_ms: float


@dataclass
class ReasonerCall:
    response_id: str | None
    returned_model: str | None
    timestamp_utc: str
    parsed_payload: RAGPrediction | dict[str, Any] | str | None
    raw_structured_response: dict[str, Any]
    raw_output_text: str | None
    refusal: str | None
    usage: Usage = field(default_factory=Usage)


class ReasonerClient(Protocol):
    def call(self, *, prompt: str, case_payload: str) -> ReasonerCall: ...


def build_reasoning_case(
    route: dict[str, str],
    retrieved_record_ids: Sequence[str],
    retrieved_record_texts: Sequence[str],
) -> ReasoningCase:
    started = perf_counter_ns()
    assert_route(route)
    ids = tuple(str(value) for value in retrieved_record_ids)
    texts = tuple(str(value) for value in retrieved_record_texts)
    if not ids or len(ids) != len(texts) or len(ids) != len(set(ids)):
        raise RuntimeError("retrieved reasoning context requires aligned, unique, nonempty records")
    lines = [
        f"CASE_ID: {route['case_id']}",
        f"PRIMARY_ENTITY_TYPE: {route['primary_entity_type']}",
        f"PRIMARY_ENTITY_ID: {route['primary_entity_id']}",
        f"DECISION_CUTOFF: {DECISION_CUTOFF}",
        "RETRIEVED_RECORD_IDS_IN_RANK_ORDER:",
        *(f"- {record_id}" for record_id in ids),
        "RETRIEVED_RECORDS_BEGIN",
    ]
    for rank, text in enumerate(texts, start=1):
        lines.extend((f"RETRIEVAL_RANK: {rank}", text))
    lines.append("RETRIEVED_RECORDS_END")
    payload = "\n".join(lines)
    assert_payload_label_blind(payload, name=f"reasoner_payload:{route['case_id']}")
    return ReasoningCase(
        dict(route), ids, texts, payload, sha256_bytes(payload),
        (perf_counter_ns() - started) / 1_000_000,
    )


def reasoning_request_hash(
    case: ReasoningCase,
    *,
    selected_k: int,
    prompt: str,
    config: ReasonerConfig = REASONER_CONFIG,
) -> str:
    if selected_k != len(case.retrieved_record_ids):
        raise RuntimeError("selected K differs from retrieved context length")
    return sha256_bytes(canonical_json({
        "frozen_spec_sha256": SPEC_SHA256,
        "selected_k": selected_k,
        "model_id": config.model_id,
        "generation_configuration": config.serializable(),
        "prompt": prompt,
        "case_metadata": case.route,
        "retrieved_record_ids": list(case.retrieved_record_ids),
        "exact_record_payload": list(case.retrieved_record_texts),
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "output_schema": json.loads(canonical_output_schema()),
    }))


def context_preflight(
    cases: Sequence[ReasoningCase], prompt: str, config: ReasonerConfig = REASONER_CONFIG
) -> dict[str, Any]:
    rows = []
    for case in cases:
        # Includes the complete instructions, user payload, and schema sent by parse().
        complete = prompt + "\n" + case.payload + "\n" + canonical_output_schema()
        estimate = conservative_generation_tokens(complete)
        fits = estimate + config.reserved_output_tokens <= config.context_window_tokens
        rows.append({
            "case_id": case.route["case_id"],
            "input_characters": len(complete),
            "estimated_input_tokens": estimate,
            "reserved_output_tokens": config.reserved_output_tokens,
            "fits": fits,
        })
    failures = [row for row in rows if not row["fits"]]
    return {
        "status": "PASS" if not failures else "FAIL",
        "estimator": "ceil(Unicode characters / 3)",
        "context_window_tokens": config.context_window_tokens,
        "reserved_output_tokens": config.reserved_output_tokens,
        "case_count": len(rows),
        "maximum_estimated_input_tokens": max((row["estimated_input_tokens"] for row in rows), default=0),
        "total_estimated_input_tokens": sum(row["estimated_input_tokens"] for row in rows),
        "failing_cases": failures,
        "cases": rows,
    }


def _int_attr(value: object | None, name: str) -> int:
    return int((getattr(value, name, 0) if value is not None else 0) or 0)


def _usage(response: object) -> Usage:
    usage = getattr(response, "usage", None)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return Usage(
        input_tokens=_int_attr(usage, "input_tokens"),
        output_tokens=_int_attr(usage, "output_tokens"),
        cached_input_tokens=_int_attr(input_details, "cached_tokens"),
        reasoning_tokens=_int_attr(output_details, "reasoning_tokens"),
        cache_write_tokens=_int_attr(input_details, "cache_write_tokens"),
    )


def _refusal(response: object) -> str | None:
    for output in getattr(response, "output", []) or []:
        if getattr(output, "type", None) != "message":
            continue
        for content in getattr(output, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return str(getattr(content, "refusal", "model refusal"))
    return None


class OpenAIReasonerClient:
    def __init__(self, config: ReasonerConfig = REASONER_CONFIG):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("OpenAI Python SDK is required for --execute-api") from exc
        self.config = config
        self.client = OpenAI(timeout=config.request_timeout_seconds, max_retries=0)

    def call(self, *, prompt: str, case_payload: str) -> ReasonerCall:
        try:
            response = self.client.responses.parse(
                model=self.config.model_id,
                instructions=prompt,
                input=[{"role": "user", "content": [{"type": "input_text", "text": case_payload}]}],
                text_format=RAGPrediction,
                text={"verbosity": self.config.verbosity},
                reasoning={"effort": self.config.reasoning_effort},
                max_output_tokens=self.config.max_output_tokens,
                store=self.config.store,
                truncation=self.config.truncation,
                service_tier=self.config.service_tier,
            )
        except Exception as exc:
            raise classify_openai_exception(exc) from exc
        returned_model = getattr(response, "model", None)
        if returned_model is not None and returned_model != self.config.model_id:
            raise PermanentAPIError(
                "REASONER_MODEL_ID_MISMATCH",
                {"expected_model": self.config.model_id, "returned_model": returned_model},
            )
        raw = response.model_dump(mode="json", warnings=False)
        return ReasonerCall(
            response_id=getattr(response, "id", None),
            returned_model=returned_model,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            parsed_payload=getattr(response, "output_parsed", None),
            raw_structured_response=raw,
            raw_output_text=getattr(response, "output_text", None),
            refusal=_refusal(response),
            usage=_usage(response),
        )


class MockReasonerClient:
    """Scripted no-cost client covering successful and terminal/technical outcomes."""

    def __init__(self, scenarios: Sequence[str]):
        if not scenarios:
            raise ValueError("at least one mock scenario is required")
        self.scenarios = list(scenarios)
        self.call_count = 0

    def call(self, *, prompt: str, case_payload: str) -> ReasonerCall:
        del prompt
        scenario = self.scenarios[min(self.call_count, len(self.scenarios) - 1)]
        self.call_count += 1
        if scenario in {"timeout", "rate_limit", "transient_error"}:
            raise TransientAPIError(scenario.upper())
        if scenario == "permanent_error":
            raise PermanentAPIError("MOCK_PERMANENT")
        case_id = case_payload.split("CASE_ID: ", 1)[1].split("\n", 1)[0]
        ids_block = case_payload.split("RETRIEVED_RECORD_IDS_IN_RANK_ORDER:\n", 1)[1].split(
            "\nRETRIEVED_RECORDS_BEGIN", 1
        )[0]
        ids = [line[2:] for line in ids_block.splitlines() if line.startswith("- ")]
        base = {
            "case_id": case_id, "method": "rag", "retrieved_record_ids": ids,
            "reason": f"Retrieved record {ids[0]} supports the mock decision.", "confidence": 0.9,
        }
        refusal = None
        if scenario == "match":
            payload: Any = {**base, "status": "MATCH", "is_anomaly": False,
                            "predicted_failure_type": "NO_FAILURE", "evidence_record_ids": [ids[0]]}
        elif scenario == "anomaly":
            payload = {**base, "status": "ANOMALY", "is_anomaly": True,
                       "predicted_failure_type": "F01_DUPLICATE_INVOICE", "evidence_record_ids": [ids[0]]}
        elif scenario == "insufficient":
            payload = {**base, "status": "INSUFFICIENT_EVIDENCE", "is_anomaly": None,
                       "predicted_failure_type": None, "evidence_record_ids": []}
        elif scenario == "malformed":
            payload = "{not-json"
        elif scenario == "wrong_case_id":
            payload = {**base, "case_id": "WRONG", "status": "MATCH", "is_anomaly": False,
                       "predicted_failure_type": "NO_FAILURE", "evidence_record_ids": [ids[0]]}
        elif scenario in {"invented_evidence", "nonretrieved_evidence"}:
            payload = {**base, "status": "ANOMALY", "is_anomaly": True,
                       "predicted_failure_type": "F01_DUPLICATE_INVOICE",
                       "evidence_record_ids": ["invoices:INVENTED"]}
        elif scenario == "invalid_class":
            payload = {**base, "status": "ANOMALY", "is_anomaly": True,
                       "predicted_failure_type": "F99_UNKNOWN", "evidence_record_ids": [ids[0]]}
        elif scenario == "refusal":
            payload = None
            refusal = "mock refusal"
        else:
            raise ValueError(f"unknown mock scenario: {scenario}")
        return ReasonerCall(
            response_id=f"mock-rag-{self.call_count}", returned_model="mock-rag",
            timestamp_utc="2026-08-09T00:00:00+00:00", parsed_payload=payload,
            raw_structured_response={"mock_scenario": scenario},
            raw_output_text=payload if isinstance(payload, str) else None,
            refusal=refusal, usage=Usage(input_tokens=100, output_tokens=20, reasoning_tokens=5),
        )
