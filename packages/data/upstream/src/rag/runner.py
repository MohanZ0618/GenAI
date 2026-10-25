"""Sequential frozen reasoner execution with append-only checkpoints and safe resume."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Sequence

from pydantic import ValidationError

from src.direct_llm.client import PermanentAPIError, TransientAPIError
from src.rag.artifacts import append_jsonl, sha256_bytes
from src.rag.config import OUTPUT_SCHEMA_VERSION, REASONER_CONFIG, ReasonerConfig
from src.rag.reasoner import ReasonerCall, ReasonerClient, ReasoningCase, reasoning_request_hash
from src.rag.schemas import validate_prediction


# Retry-exhausted transient errors are deliberately absent: a later explicit resume may retry them.
IMMUTABLE_STATES = frozenset({
    "SUCCESS",
    "MALFORMED_RESPONSE",
    "SCHEMA_INVALID_RESPONSE",
    "NONRETRIEVED_EVIDENCE",
    "MODEL_REFUSAL",
    "PERMANENT_API_ERROR",
})


def load_latest_ledger(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                result[str(row["case_id"])] = row
    return result


def _parse_failure(exc: Exception) -> str:
    text = str(exc).lower()
    if "nonretrieved evidence" in text:
        return "NONRETRIEVED_EVIDENCE"
    if isinstance(exc, json.JSONDecodeError) or "json_invalid" in text:
        return "MALFORMED_RESPONSE"
    return "SCHEMA_INVALID_RESPONSE"


def _failure_envelope(
    case: ReasoningCase,
    request_hash: str,
    status: str,
    attempt_count: int,
    latency_ms: float,
    call: ReasonerCall | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case.route["case_id"],
        "method": "rag",
        "status": status,
        "is_anomaly": None,
        "predicted_failure_type": None,
        "evidence_record_ids": [],
        "reason": call.refusal if call and call.refusal else status,
        "confidence": None,
        "retrieved_record_ids": list(case.retrieved_record_ids),
        "request_hash": request_hash,
        "response_id": call.response_id if call else None,
        "returned_model": call.returned_model if call else None,
        "parse_status": status,
        "attempt_count": attempt_count,
        "latency_ms": latency_ms,
        "context_assembly_latency_ms": case.context_assembly_latency_ms,
        "usage": call.usage.serializable() if call else {},
    }


@dataclass(frozen=True)
class RunSummary:
    total_cases: int
    skipped_immutable_cases: int
    successful_cases: int
    unresolved_cases: int
    retry_events: int

    def serializable(self) -> dict[str, int]:
        return self.__dict__.copy()


def run_reasoning_cases(
    cases: Sequence[ReasoningCase],
    *,
    client: ReasonerClient,
    prompt: str,
    selected_k: int,
    run_dir: Path,
    config: ReasonerConfig = REASONER_CONFIG,
    sleeper: Callable[[float], None] = time.sleep,
) -> RunSummary:
    """Call the reasoner once per case, except frozen bounded technical retries."""
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "request_ledger.jsonl"
    raw_path = run_dir / "raw_responses.jsonl"
    predictions_path = run_dir / "predictions.jsonl"
    requests_path = run_dir / "reasoning_requests.jsonl"
    latest = load_latest_ledger(ledger_path)
    prior_requests = load_latest_ledger(requests_path)
    skipped = successful = unresolved = retry_events = 0

    for case in cases:
        case_id = case.route["case_id"]
        request_hash = reasoning_request_hash(
            case, selected_k=selected_k, prompt=prompt, config=config
        )
        prior_request = prior_requests.get(case_id)
        if prior_request:
            if prior_request.get("request_hash") != request_hash:
                raise RuntimeError(f"persisted reasoning request changed on resume for {case_id}")
        else:
            request_row = {
                "case_id": case_id, "request_hash": request_hash,
                "selected_k": selected_k, "prompt_sha256": sha256_bytes(prompt),
                "route": case.route, "retrieved_record_ids": list(case.retrieved_record_ids),
                "retrieved_record_text_sha256": [sha256_bytes(value) for value in case.retrieved_record_texts],
                "case_payload": case.payload, "case_payload_sha256": case.payload_sha256,
                "context_assembly_latency_ms": case.context_assembly_latency_ms,
            }
            append_jsonl(requests_path, request_row)
            prior_requests[case_id] = request_row
        previous = latest.get(case_id)
        if previous:
            if previous["request_hash"] != request_hash:
                raise RuntimeError(f"request hash changed on resume for {case_id}")
            if previous["status"] in IMMUTABLE_STATES:
                skipped += 1
                successful += int(previous["status"] == "SUCCESS")
                unresolved += int(previous["status"] != "SUCCESS")
                continue
        prior_attempts = int(previous.get("attempt_count", 0)) if previous else 0

        for local_attempt in range(1, config.max_attempts + 1):
            attempt = prior_attempts + local_attempt
            started = perf_counter()
            try:
                call = client.call(prompt=prompt, case_payload=case.payload)
            except TransientAPIError as exc:
                latency_ms = (perf_counter() - started) * 1000
                exhausted = local_attempt == config.max_attempts
                status = "TRANSIENT_API_FAILURE_EXHAUSTED" if exhausted else "TRANSIENT_API_ERROR"
                row = {
                    "case_id": case_id, "request_hash": request_hash, "status": status,
                    "attempt_count": attempt, "response_received": False,
                    "parse_status": "NOT_APPLICABLE", "latency_ms": latency_ms,
                    "error_category": exc.category, "error_detail": exc.detail,
                    "output_schema_version": OUTPUT_SCHEMA_VERSION,
                }
                append_jsonl(ledger_path, row)
                latest[case_id] = row
                if exhausted:
                    append_jsonl(
                        predictions_path,
                        _failure_envelope(case, request_hash, status, attempt, latency_ms),
                    )
                    unresolved += 1
                    break
                retry_events += 1
                sleeper(config.backoff_seconds[local_attempt - 1])
                continue
            except PermanentAPIError as exc:
                latency_ms = (perf_counter() - started) * 1000
                status = "PERMANENT_API_ERROR"
                row = {
                    "case_id": case_id, "request_hash": request_hash, "status": status,
                    "attempt_count": attempt, "response_received": False,
                    "parse_status": "NOT_APPLICABLE", "latency_ms": latency_ms,
                    "error_category": exc.category, "error_detail": exc.detail,
                    "output_schema_version": OUTPUT_SCHEMA_VERSION,
                }
                append_jsonl(ledger_path, row)
                append_jsonl(
                    predictions_path,
                    _failure_envelope(case, request_hash, status, attempt, latency_ms),
                )
                latest[case_id] = row
                unresolved += 1
                break

            latency_ms = (perf_counter() - started) * 1000
            append_jsonl(raw_path, {
                "case_id": case_id, "request_hash": request_hash,
                "response_id": call.response_id, "returned_model": call.returned_model,
                "timestamp_utc": call.timestamp_utc,
                "raw_structured_response": call.raw_structured_response,
                "raw_output_text": call.raw_output_text, "refusal": call.refusal,
                "usage": call.usage.serializable(), "latency_ms": latency_ms,
                "attempt": attempt,
            })
            if call.refusal:
                status = "MODEL_REFUSAL"
                prediction_row = _failure_envelope(
                    case, request_hash, status, attempt, latency_ms, call
                )
            else:
                try:
                    prediction = validate_prediction(
                        call.parsed_payload
                        if call.parsed_payload is not None
                        else call.raw_output_text or "",
                        expected_case_id=case_id,
                        expected_retrieved_record_ids=list(case.retrieved_record_ids),
                    )
                    status = "SUCCESS"
                    prediction_row = {
                        **prediction.model_dump(mode="json"),
                        "request_hash": request_hash, "response_id": call.response_id,
                        "returned_model": call.returned_model, "parse_status": "PASS",
                        "attempt_count": attempt, "latency_ms": latency_ms,
                        "context_assembly_latency_ms": case.context_assembly_latency_ms,
                        "usage": call.usage.serializable(),
                    }
                except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                    status = _parse_failure(exc)
                    prediction_row = _failure_envelope(
                        case, request_hash, status, attempt, latency_ms, call
                    )
                    prediction_row["validation_error"] = str(exc)[:4000]
            append_jsonl(predictions_path, prediction_row)
            row = {
                "case_id": case_id, "request_hash": request_hash, "status": status,
                "attempt_count": attempt, "response_received": True,
                "parse_status": prediction_row["parse_status"], "latency_ms": latency_ms,
                "input_tokens": call.usage.input_tokens,
                "cached_input_tokens": call.usage.cached_input_tokens,
                "output_tokens": call.usage.output_tokens,
                "reasoning_tokens": call.usage.reasoning_tokens,
                "error_category": None if status == "SUCCESS" else status,
                "context_assembly_latency_ms": case.context_assembly_latency_ms,
                "output_schema_version": OUTPUT_SCHEMA_VERSION,
            }
            append_jsonl(ledger_path, row)
            latest[case_id] = row
            successful += int(status == "SUCCESS")
            unresolved += int(status != "SUCCESS")
            break

    return RunSummary(len(cases), skipped, successful, unresolved, retry_events)


def pricing_report(
    predictions: Sequence[dict[str, Any]], config: ReasonerConfig = REASONER_CONFIG
) -> dict[str, Any]:
    totals = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
    costs: list[float] = []
    for row in predictions:
        usage = row.get("usage") or {}
        for key in totals:
            totals[key] += int(usage.get(key, 0) or 0)
        cached = int(usage.get("cached_input_tokens", 0) or 0)
        uncached = max(0, int(usage.get("input_tokens", 0) or 0) - cached)
        costs.append((
            uncached * config.input_usd_per_million_tokens
            + cached * config.cached_input_usd_per_million_tokens
            + int(usage.get("output_tokens", 0) or 0) * config.output_usd_per_million_tokens
        ) / 1_000_000)
    return {
        "model_id": config.model_id,
        "pricing_reference_date": config.pricing_reference_date,
        **totals,
        "request_count": len(predictions),
        "total_estimated_generation_cost_usd": sum(costs),
        "mean_estimated_generation_cost_usd": sum(costs) / len(costs) if costs else 0.0,
    }
