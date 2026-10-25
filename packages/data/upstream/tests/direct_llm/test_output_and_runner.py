from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.direct_llm.client import (
    MockDirectClient,
    OpenAIResponsesClient,
    PermanentAPIError,
    _non_retryable_rate_limit,
    classify_openai_exception,
)
from src.direct_llm.config import BASELINE_CONFIG
from src.direct_llm.output import DirectLLMPrediction, validate_prediction
from src.direct_llm.packet import CasePacket
from src.direct_llm.runner import load_latest_ledger, run_cases


def packet(case_id: str = "CASE_1", serialized: str = '{"case":"CASE_1"}') -> CasePacket:
    return CasePacket(
        route={"case_id": case_id, "primary_entity_type": "invoice", "primary_entity_id": "INV_TEST"},
        value={"case": {"case_id": case_id}},
        serialized=serialized,
        packet_sha256="unused",
        evidence_record_ids=frozenset({"invoices:INV_TEST"}),
        record_count=1,
    )


@pytest.mark.parametrize("value", [
    {
        "case_id": "C", "status": "MATCH", "is_anomaly": False,
        "predicted_failure_type": "NO_FAILURE", "evidence_record_ids": [],
        "reason": "Records reconcile.", "confidence": 0.9,
    },
    {
        "case_id": "C", "status": "ANOMALY", "is_anomaly": True,
        "predicted_failure_type": "F01_DUPLICATE_INVOICE",
        "evidence_record_ids": ["invoices:INV_TEST"], "reason": "Duplicate.", "confidence": 0.8,
    },
    {
        "case_id": "C", "status": "INSUFFICIENT_EVIDENCE", "is_anomaly": None,
        "predicted_failure_type": None, "evidence_record_ids": [], "reason": "Missing.", "confidence": 0.5,
    },
])
def test_valid_output_states(value: dict[str, object]) -> None:
    parsed = validate_prediction(value, expected_case_id="C", permitted_evidence_ids={"invoices:INV_TEST"})
    assert isinstance(parsed, DirectLLMPrediction)


@pytest.mark.parametrize("value,match", [
    ({"case_id": "C", "status": "MATCH", "is_anomaly": True, "predicted_failure_type": "NO_FAILURE", "evidence_record_ids": [], "reason": "x", "confidence": .5}, "MATCH requires"),
    ({"case_id": "C", "status": "ANOMALY", "is_anomaly": True, "predicted_failure_type": "F99", "evidence_record_ids": ["invoices:INV_TEST"], "reason": "x", "confidence": .5}, "literal_error"),
    ({"case_id": "C", "status": "ANOMALY", "is_anomaly": True, "predicted_failure_type": "F01_DUPLICATE_INVOICE", "evidence_record_ids": [], "reason": "x", "confidence": .5}, "at least one"),
])
def test_invalid_output_contracts(value: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        DirectLLMPrediction.model_validate(value)


def test_case_and_evidence_constraints() -> None:
    valid = {
        "case_id": "WRONG", "status": "ANOMALY", "is_anomaly": True,
        "predicted_failure_type": "F01_DUPLICATE_INVOICE",
        "evidence_record_ids": ["invoices:INVENTED"], "reason": "x", "confidence": .7,
    }
    with pytest.raises(ValueError, match="case_id mismatch"):
        validate_prediction(valid, expected_case_id="C", permitted_evidence_ids=set())
    valid["case_id"] = "C"
    with pytest.raises(ValueError, match="hallucinated evidence"):
        validate_prediction(valid, expected_case_id="C", permitted_evidence_ids=set())


def test_transient_failure_retries_then_checkpoints_success(tmp_path: Path) -> None:
    client = MockDirectClient(["timeout", "valid_match"])
    summary = run_cases(
        [packet()], client=client, config=BASELINE_CONFIG, prompt="prompt",
        run_dir=tmp_path, sleeper=lambda _: None,
    )
    assert client.call_count == 2
    assert summary.successful_cases == 1
    assert summary.retry_events == 1
    latest = load_latest_ledger(tmp_path / "request_ledger.jsonl")
    assert latest["CASE_1"]["status"] == "SUCCESS"
    assert latest["CASE_1"]["attempt_count"] == 2


def test_completed_case_is_never_rerun(tmp_path: Path) -> None:
    first = MockDirectClient(["valid_match"])
    run_cases([packet()], client=first, config=BASELINE_CONFIG, prompt="p", run_dir=tmp_path)
    second = MockDirectClient(["valid_anomaly"])
    summary = run_cases([packet()], client=second, config=BASELINE_CONFIG, prompt="p", run_dir=tmp_path)
    assert second.call_count == 0
    assert summary.skipped_terminal_cases == 1
    assert len((tmp_path / "predictions.jsonl").read_text().splitlines()) == 1


def test_changed_request_hash_is_rejected_on_resume(tmp_path: Path) -> None:
    run_cases([packet()], client=MockDirectClient(["valid_match"]), config=BASELINE_CONFIG, prompt="p", run_dir=tmp_path)
    with pytest.raises(RuntimeError, match="request hash changed"):
        run_cases([packet(serialized='{"changed":true}')], client=MockDirectClient(["valid_match"]), config=BASELINE_CONFIG, prompt="p", run_dir=tmp_path)


@pytest.mark.parametrize("scenario,expected", [
    ("malformed_json", "MALFORMED_RESPONSE"),
    ("schema_invalid", "SCHEMA_INVALID_RESPONSE"),
    ("hallucinated_evidence", "HALLUCINATED_EVIDENCE"),
    ("refusal", "MODEL_REFUSAL"),
    ("permanent_error", "PERMANENT_API_ERROR"),
])
def test_valid_but_bad_or_permanent_outcome_never_regenerates(
    tmp_path: Path, scenario: str, expected: str
) -> None:
    client = MockDirectClient([scenario, "valid_match"])
    run_cases([packet()], client=client, config=BASELINE_CONFIG, prompt="p", run_dir=tmp_path)
    assert client.call_count == 1
    row = json.loads((tmp_path / "predictions.jsonl").read_text().splitlines()[0])
    assert row["status"] == expected


def test_all_transient_categories_are_bounded(tmp_path: Path) -> None:
    client = MockDirectClient(["rate_limit", "server_error", "timeout", "server_error"])
    summary = run_cases(
        [packet()], client=client, config=BASELINE_CONFIG, prompt="p",
        run_dir=tmp_path, sleeper=lambda _: None,
    )
    assert client.call_count == BASELINE_CONFIG.max_attempts
    assert summary.unresolved_cases == 1
    assert load_latest_ledger(tmp_path / "request_ledger.jsonl")["CASE_1"]["status"] == "TRANSIENT_API_FAILURE_EXHAUSTED"


def test_raw_response_has_no_environment_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value-never-written")
    run_cases([packet()], client=MockDirectClient(["valid_match"]), config=BASELINE_CONFIG, prompt="p", run_dir=tmp_path)
    combined = "".join(path.read_text() for path in tmp_path.iterdir() if path.is_file())
    assert "test-secret-value-never-written" not in combined


def test_openai_request_is_direct_structured_and_tool_free() -> None:
    captured = {}

    class Response:
        id = "resp_test"
        model = "gpt-5.6-sol"
        output = []
        output_text = '{"case_id":"C"}'
        output_parsed = DirectLLMPrediction(
            case_id="C", status="MATCH", is_anomaly=False,
            predicted_failure_type="NO_FAILURE", evidence_record_ids=[],
            reason="Records reconcile.", confidence=0.9,
        )
        usage = None

        @staticmethod
        def model_dump(**_: object) -> dict[str, object]:
            return {"id": "resp_test", "model": "gpt-5.6-sol"}

    class Responses:
        @staticmethod
        def parse(**kwargs: object) -> Response:
            captured.update(kwargs)
            return Response()

    class SDK:
        responses = Responses()

    client = object.__new__(OpenAIResponsesClient)
    client.config = BASELINE_CONFIG
    client.client = SDK()
    result = client.call(case_id="C", prompt="frozen prompt", serialized_packet='{"case":"C"}')
    assert result.response_id == "resp_test"
    assert captured["model"] == "gpt-5.6-sol"
    assert captured["text_format"] is DirectLLMPrediction
    assert captured["text"] == {"verbosity": "low"}
    assert captured["store"] is False
    assert captured["truncation"] == "disabled"
    assert "verbosity" not in captured
    assert "tools" not in captured
    assert "tool_choice" not in captured
    assert "temperature" not in captured
    assert "top_p" not in captured


def test_openai_bad_request_retains_only_sanitized_diagnostics() -> None:
    key_shaped_value = "sk-" + "1234567890abcdef"
    org_shaped_value = "org-" + "1234567890abcdef"

    class FakeBadRequest(Exception):
        status_code = 400
        request_id = "req_test"
        body = {
            "type": "invalid_request_error",
            "code": "unsupported_parameter",
            "param": "verbosity",
            "message": f"Bad key {key_shaped_value} for {org_shaped_value} in request",
        }

    mapped = classify_openai_exception(FakeBadRequest())
    assert isinstance(mapped, PermanentAPIError)
    assert mapped.category == "FakeBadRequest:400"
    assert mapped.detail["error_param"] == "verbosity"
    assert mapped.detail["request_id"] == "req_test"
    assert key_shaped_value not in mapped.detail["error_message"]
    assert org_shaped_value not in mapped.detail["error_message"]


def test_oversized_tpm_request_is_not_retryable() -> None:
    assert _non_retryable_rate_limit({
        "error_code": "rate_limit_exceeded",
        "error_message": (
            "Request too large for gpt-5.6-sol on tokens per min (TPM): "
            "Limit 500000, Requested 690145. The input or output tokens must be reduced."
        ),
    })
    assert not _non_retryable_rate_limit({
        "error_code": "rate_limit_exceeded",
        "error_message": "Rate limit reached. Please retry after 2 seconds.",
    })
