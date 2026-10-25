"""Auditable sequential execution, checkpointing, retries, and resumability."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable

from pydantic import ValidationError

from src.direct_llm.client import (
    ClientCall,
    DirectClient,
    PermanentAPIError,
    TransientAPIError,
)
from src.direct_llm.config import BaselineConfig, PACKET_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from src.direct_llm.output import validate_prediction
from src.direct_llm.packet import CasePacket
from src.direct_llm.request import request_hash


TERMINAL_LEDGER_STATES = {
    "SUCCESS",
    "MALFORMED_RESPONSE",
    "SCHEMA_INVALID_RESPONSE",
    "HALLUCINATED_EVIDENCE",
    "MODEL_REFUSAL",
    "PERMANENT_API_ERROR",
    "TRANSIENT_API_FAILURE_EXHAUSTED",
}


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def load_latest_ledger(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            result[str(row["case_id"])] = row
    return result


def classify_parse_error(exc: Exception) -> str:
    text = str(exc)
    if "hallucinated evidence" in text:
        return "HALLUCINATED_EVIDENCE"
    if isinstance(exc, (json.JSONDecodeError, ValidationError)):
        if "json_invalid" in text or isinstance(exc, json.JSONDecodeError):
            return "MALFORMED_RESPONSE"
    return "SCHEMA_INVALID_RESPONSE"


def _raw_response_row(
    case_id: str,
    req_hash: str,
    call: ClientCall,
    latency_ms: float,
    attempt: int,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "request_hash": req_hash,
        "response_id": call.response_id,
        "returned_model": call.returned_model,
        "timestamp_utc": call.timestamp_utc,
        "raw_structured_response": call.raw_structured_response,
        "raw_output_text": call.raw_output_text,
        "refusal": call.refusal,
        "usage": call.usage.serializable(),
        "latency_ms": latency_ms,
        "attempt": attempt,
    }


def _prediction_failure(
    case_id: str,
    req_hash: str,
    status: str,
    attempt_count: int,
    latency_ms: float,
    call: ClientCall | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "method": "direct_llm",
        "status": status,
        "is_anomaly": None,
        "predicted_failure_type": None,
        "evidence_record_ids": [],
        "reason": call.refusal if call and call.refusal else status,
        "confidence": None,
        "request_hash": req_hash,
        "response_id": call.response_id if call else None,
        "returned_model": call.returned_model if call else None,
        "parse_status": status,
        "attempt_count": attempt_count,
        "latency_ms": latency_ms,
        "usage": call.usage.serializable() if call else {},
    }


@dataclass(frozen=True)
class RunSummary:
    total_cases: int
    skipped_terminal_cases: int
    successful_cases: int
    unresolved_cases: int
    retry_events: int

    def serializable(self) -> dict[str, int]:
        return {
            "total_cases": self.total_cases,
            "skipped_terminal_cases": self.skipped_terminal_cases,
            "successful_cases": self.successful_cases,
            "unresolved_cases": self.unresolved_cases,
            "retry_events": self.retry_events,
        }


def run_cases(
    packets: Iterable[CasePacket],
    *,
    client: DirectClient,
    config: BaselineConfig,
    prompt: str,
    run_dir: Path,
    sleeper: Callable[[float], None] = time.sleep,
) -> RunSummary:
    """Run each packet once, except bounded technical retries."""
    packet_list = list(packets)
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "request_ledger.jsonl"
    raw_path = run_dir / "raw_responses.jsonl"
    predictions_path = run_dir / "predictions.jsonl"
    latest = load_latest_ledger(ledger_path)
    skipped = successful = unresolved = retry_events = 0

    for packet in packet_list:
        case_id = packet.route["case_id"]
        req_hash = request_hash(config, packet.serialized)
        previous = latest.get(case_id)
        if previous:
            if previous["request_hash"] != req_hash:
                raise RuntimeError(f"request hash changed on resume for {case_id}")
            if previous["status"] in TERMINAL_LEDGER_STATES:
                skipped += 1
                successful += int(previous["status"] == "SUCCESS")
                unresolved += int(previous["status"] != "SUCCESS")
                continue
        attempts_before = int(previous.get("attempt_count", 0)) if previous else 0

        for attempt in range(attempts_before + 1, config.max_attempts + 1):
            started = perf_counter()
            try:
                call = client.call(
                    case_id=case_id,
                    prompt=prompt,
                    serialized_packet=packet.serialized,
                )
            except TransientAPIError as exc:
                latency_ms = (perf_counter() - started) * 1000
                exhausted = attempt >= config.max_attempts
                status = "TRANSIENT_API_FAILURE_EXHAUSTED" if exhausted else "TRANSIENT_API_ERROR"
                row = {
                    "case_id": case_id,
                    "request_hash": req_hash,
                    "status": status,
                    "attempt_count": attempt,
                    "response_received": False,
                    "parse_status": "NOT_APPLICABLE",
                    "latency_ms": latency_ms,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "error_category": exc.category,
                    "error_detail": exc.detail,
                    "packet_version": PACKET_VERSION,
                }
                append_jsonl(ledger_path, row)
                latest[case_id] = row
                if exhausted:
                    append_jsonl(
                        predictions_path,
                        _prediction_failure(case_id, req_hash, status, attempt, latency_ms),
                    )
                    unresolved += 1
                    break
                retry_events += 1
                sleeper(config.backoff_seconds[attempt - 1])
                continue
            except PermanentAPIError as exc:
                latency_ms = (perf_counter() - started) * 1000
                status = "PERMANENT_API_ERROR"
                row = {
                    "case_id": case_id,
                    "request_hash": req_hash,
                    "status": status,
                    "attempt_count": attempt,
                    "response_received": False,
                    "parse_status": "NOT_APPLICABLE",
                    "latency_ms": latency_ms,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "error_category": exc.category,
                    "error_detail": exc.detail,
                    "packet_version": PACKET_VERSION,
                }
                append_jsonl(ledger_path, row)
                append_jsonl(
                    predictions_path,
                    _prediction_failure(case_id, req_hash, status, attempt, latency_ms),
                )
                latest[case_id] = row
                unresolved += 1
                break

            latency_ms = (perf_counter() - started) * 1000
            append_jsonl(raw_path, _raw_response_row(case_id, req_hash, call, latency_ms, attempt))
            local_started = perf_counter()
            if call.refusal:
                status = "MODEL_REFUSAL"
                prediction_row = _prediction_failure(
                    case_id, req_hash, status, attempt, latency_ms, call
                )
            else:
                try:
                    prediction = validate_prediction(
                        call.parsed_payload if call.parsed_payload is not None else call.raw_output_text or "",
                        expected_case_id=case_id,
                        permitted_evidence_ids=set(packet.evidence_record_ids),
                    )
                    status = "SUCCESS"
                    prediction_row = {
                        **prediction.model_dump(mode="json"),
                        "method": "direct_llm",
                        "request_hash": req_hash,
                        "response_id": call.response_id,
                        "returned_model": call.returned_model,
                        "parse_status": "PASS",
                        "attempt_count": attempt,
                        "latency_ms": latency_ms,
                        "usage": call.usage.serializable(),
                    }
                except Exception as exc:
                    status = classify_parse_error(exc)
                    prediction_row = _prediction_failure(
                        case_id, req_hash, status, attempt, latency_ms, call
                    )
            local_overhead_ms = (perf_counter() - local_started) * 1000
            prediction_row["local_overhead_ms"] = local_overhead_ms
            append_jsonl(predictions_path, prediction_row)
            row = {
                "case_id": case_id,
                "request_hash": req_hash,
                "status": status,
                "attempt_count": attempt,
                "response_received": True,
                "parse_status": prediction_row["parse_status"],
                "latency_ms": latency_ms,
                "local_overhead_ms": local_overhead_ms,
                "input_tokens": call.usage.input_tokens,
                "output_tokens": call.usage.output_tokens,
                "error_category": None if status == "SUCCESS" else status,
                "packet_version": PACKET_VERSION,
            }
            append_jsonl(ledger_path, row)
            latest[case_id] = row
            successful += int(status == "SUCCESS")
            unresolved += int(status != "SUCCESS")
            break

    return RunSummary(len(packet_list), skipped, successful, unresolved, retry_events)


def pricing_report(predictions: Iterable[dict[str, Any]], config: BaselineConfig) -> dict[str, Any]:
    costs: list[float] = []
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_write_tokens": 0,
    }
    for row in predictions:
        usage = row.get("usage") or {}
        for key in totals:
            totals[key] += int(usage.get(key, 0) or 0)
        uncached = max(0, int(usage.get("input_tokens", 0)) - int(usage.get("cached_input_tokens", 0)))
        cost = (
            uncached * config.input_usd_per_million_tokens
            + int(usage.get("cached_input_tokens", 0)) * config.cached_input_usd_per_million_tokens
            + int(usage.get("output_tokens", 0)) * config.output_usd_per_million_tokens
        ) / 1_000_000
        costs.append(cost)
    ordered = sorted(costs)
    count = len(ordered)
    percentile = lambda q: ordered[min(count - 1, int((count - 1) * q))] if count else 0.0
    return {
        "model_id": config.model_id,
        "pricing_reference_date": config.pricing_reference_date,
        "input_usd_per_million_tokens": config.input_usd_per_million_tokens,
        "cached_input_usd_per_million_tokens": config.cached_input_usd_per_million_tokens,
        "output_usd_per_million_tokens": config.output_usd_per_million_tokens,
        **totals,
        "total_estimated_cost_usd": sum(costs),
        "mean_estimated_cost_usd": sum(costs) / count if count else 0.0,
        "median_estimated_cost_usd": percentile(0.5),
        "p95_estimated_cost_usd": percentile(0.95),
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
    }
