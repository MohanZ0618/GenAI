"""Direct Responses API client and deterministic mock scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from src.direct_llm.config import BaselineConfig
from src.direct_llm.output import DirectLLMPrediction


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def serializable(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ClientCall:
    response_id: str | None
    returned_model: str | None
    timestamp_utc: str
    parsed_payload: DirectLLMPrediction | dict[str, Any] | str | None
    raw_structured_response: dict[str, Any]
    raw_output_text: str | None
    refusal: str | None
    usage: Usage = field(default_factory=Usage)


class DirectClient(Protocol):
    def call(self, *, case_id: str, prompt: str, serialized_packet: str) -> ClientCall: ...


class TransientAPIError(RuntimeError):
    def __init__(self, category: str, detail: dict[str, Any] | None = None):
        super().__init__(category)
        self.category = category
        self.detail = detail or {}


class PermanentAPIError(RuntimeError):
    def __init__(self, category: str, detail: dict[str, Any] | None = None):
        super().__init__(category)
        self.category = category
        self.detail = detail or {}


def _int_attr(value: object | None, name: str) -> int:
    raw = getattr(value, name, 0) if value is not None else 0
    return int(raw or 0)


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


class OpenAIResponsesClient:
    """One request in, one structured result out; no tools or agent loop."""

    def __init__(self, config: BaselineConfig):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - installation failure
            raise RuntimeError("OpenAI Python SDK is required for --execute-api") from exc
        self.config = config
        # The SDK reads OPENAI_API_KEY. The harness never receives or logs its value.
        self.client = OpenAI(timeout=config.request_timeout_seconds, max_retries=0)

    def call(self, *, case_id: str, prompt: str, serialized_packet: str) -> ClientCall:
        try:
            response = self.client.responses.parse(
                model=self.config.model_id,
                instructions=prompt,
                input=[{
                    "role": "user",
                    "content": [{
                        "type": "input_text",
                        "text": "CASE_PACKET_JSON\n" + serialized_packet,
                    }],
                }],
                text_format=DirectLLMPrediction,
                text={"verbosity": self.config.verbosity},
                reasoning={"effort": self.config.reasoning_effort},
                max_output_tokens=self.config.max_output_tokens,
                store=self.config.store,
                truncation=self.config.truncation,
                service_tier=self.config.service_tier,
            )
        except Exception as exc:
            mapped = classify_openai_exception(exc)
            raise mapped from exc
        raw = response.model_dump(mode="json", warnings=False)
        return ClientCall(
            response_id=getattr(response, "id", None),
            returned_model=getattr(response, "model", None),
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            parsed_payload=getattr(response, "output_parsed", None),
            raw_structured_response=raw,
            raw_output_text=getattr(response, "output_text", None),
            refusal=_refusal(response),
            usage=_usage(response),
        )


def _safe_error_text(value: object | None, *, limit: int = 2000) -> str | None:
    """Bound and redact an API error field without retaining request content."""
    if value is None:
        return None
    import re

    text = str(value)[:limit]
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED_API_KEY]", text)
    text = re.sub(r"\borg-[A-Za-z0-9_-]{8,}\b", "[REDACTED_ORG_ID]", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
    return text


def _api_error_detail(exc: Exception) -> dict[str, Any]:
    """Extract only provider error metadata; never headers or request bodies."""
    body = getattr(exc, "body", None)
    body = body if isinstance(body, dict) else {}
    detail = {
        "status_code": getattr(exc, "status_code", None),
        "error_type": _safe_error_text(body.get("type", getattr(exc, "type", None))),
        "error_code": _safe_error_text(body.get("code", getattr(exc, "code", None))),
        "error_param": _safe_error_text(body.get("param", getattr(exc, "param", None))),
        "error_message": _safe_error_text(body.get("message")),
        "request_id": _safe_error_text(getattr(exc, "request_id", None), limit=256),
    }
    return {key: value for key, value in detail.items() if value is not None}


def _non_retryable_rate_limit(detail: dict[str, Any]) -> bool:
    """Identify capacity errors that cannot succeed after waiting and retrying."""
    message = str(detail.get("error_message", "")).lower()
    return (
        detail.get("error_code") == "rate_limit_exceeded"
        and "request too large" in message
        and "must be reduced" in message
    )


def classify_openai_exception(exc: Exception) -> RuntimeError:
    """Map SDK failures while retaining sanitized provider diagnostics."""
    try:
        from openai import APIConnectionError, APITimeoutError, RateLimitError
    except ImportError:  # pragma: no cover
        return PermanentAPIError(type(exc).__name__)
    detail = _api_error_detail(exc)
    if isinstance(exc, APITimeoutError):
        return TransientAPIError("TIMEOUT", detail)
    if isinstance(exc, RateLimitError):
        if _non_retryable_rate_limit(detail):
            return PermanentAPIError("RATE_LIMIT_REQUEST_TOO_LARGE", detail)
        return TransientAPIError("RATE_LIMIT", detail)
    if isinstance(exc, APIConnectionError):
        return TransientAPIError("CONNECTION", detail)
    status = getattr(exc, "status_code", None)
    if status in {408, 409, 429} or (isinstance(status, int) and status >= 500):
        return TransientAPIError(f"HTTP_{status}", detail)
    return PermanentAPIError(f"{type(exc).__name__}:{status or 'NO_STATUS'}", detail)


class MockDirectClient:
    """Scripted mock used to exercise all pipeline outcomes without API calls."""

    def __init__(self, scenarios: list[str] | tuple[str, ...]):
        self.scenarios = list(scenarios)
        self.call_count = 0

    def call(self, *, case_id: str, prompt: str, serialized_packet: str) -> ClientCall:
        del prompt, serialized_packet
        scenario = self.scenarios[min(self.call_count, len(self.scenarios) - 1)]
        self.call_count += 1
        if scenario == "timeout":
            raise TransientAPIError("TIMEOUT")
        if scenario == "rate_limit":
            raise TransientAPIError("RATE_LIMIT")
        if scenario == "server_error":
            raise TransientAPIError("HTTP_500")
        if scenario == "permanent_error":
            raise PermanentAPIError("HTTP_400")
        payload: DirectLLMPrediction | dict[str, Any] | str | None
        refusal: str | None = None
        if scenario == "valid_match":
            payload = DirectLLMPrediction(
                case_id=case_id, status="MATCH", is_anomaly=False,
                predicted_failure_type="NO_FAILURE", evidence_record_ids=[],
                reason="The supplied records reconcile.", confidence=0.91,
            )
        elif scenario == "valid_anomaly":
            payload = {
                "case_id": case_id, "status": "ANOMALY", "is_anomaly": True,
                "predicted_failure_type": "F01_DUPLICATE_INVOICE",
                "evidence_record_ids": ["invoices:INV_TEST"],
                "reason": "Invoices INV_TEST and its peer show a duplicate obligation.",
                "confidence": 0.88,
            }
        elif scenario == "valid_insufficient":
            payload = DirectLLMPrediction(
                case_id=case_id, status="INSUFFICIENT_EVIDENCE", is_anomaly=None,
                predicted_failure_type=None, evidence_record_ids=[],
                reason="The supplied records do not support a determination.", confidence=0.5,
            )
        elif scenario == "malformed_json":
            payload = "{not-json"
        elif scenario == "schema_invalid":
            payload = {"case_id": case_id, "status": "MATCH"}
        elif scenario == "hallucinated_evidence":
            payload = {
                "case_id": case_id, "status": "ANOMALY", "is_anomaly": True,
                "predicted_failure_type": "F01_DUPLICATE_INVOICE",
                "evidence_record_ids": ["invoices:INVENTED"],
                "reason": "Invented evidence.", "confidence": 0.8,
            }
        elif scenario == "refusal":
            payload = None
            refusal = "mock refusal"
        else:
            raise ValueError(f"unknown mock scenario: {scenario}")
        return ClientCall(
            response_id=f"mock-{self.call_count}",
            returned_model="mock-direct-llm",
            timestamp_utc="2026-08-08T00:00:00+00:00",
            parsed_payload=payload,
            raw_structured_response={"mock_scenario": scenario, "payload": payload if isinstance(payload, (dict, str)) else None},
            raw_output_text=payload if isinstance(payload, str) else None,
            refusal=refusal,
            usage=Usage(input_tokens=100, output_tokens=20, reasoning_tokens=5),
        )
