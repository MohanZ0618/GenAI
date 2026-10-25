from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.rag.audits import no_graph_audit, verify_frozen_spec
from src.rag.cli import main
from src.rag.prompt import load_frozen_prompt, prompt_sha256
from src.rag.reasoner import MockReasonerClient, build_reasoning_case, context_preflight, reasoning_request_hash
from src.rag.runner import run_reasoning_cases
from src.rag.schemas import RAGPrediction, validate_prediction


ROUTE = {"case_id": "C1", "primary_entity_type": "invoice", "primary_entity_id": "INV1"}
IDS = ["invoices:INV1", "invoice_lines:LINE1"]
TEXTS = ["RECORD_TYPE: INVOICE\nRECORD_ID: invoices:INV1", "RECORD_TYPE: INVOICE_LINE\nRECORD_ID: invoice_lines:LINE1"]


def _case():
    return build_reasoning_case(ROUTE, IDS, TEXTS)


def test_prompt_is_extracted_from_checksum_frozen_spec(root: Path) -> None:
    prompt = load_frozen_prompt(root)
    assert prompt.startswith("You are performing one controlled financial-reconciliation classification")
    assert prompt.endswith("Return exactly the structured output required by the enforced schema and no other content.")
    assert prompt_sha256(root) == __import__("hashlib").sha256(prompt.encode()).hexdigest()
    assert verify_frozen_spec(root)["status"] == "PASS"


def test_context_contains_only_ranked_records_and_no_scores_or_extra_anchor(root: Path) -> None:
    case = _case()
    assert case.payload.count("RETRIEVAL_RANK:") == 2
    assert "SIMILARITY" not in case.payload and "SCORE" not in case.payload
    assert case.payload.index(IDS[0]) < case.payload.index(IDS[1])
    audit = context_preflight([case], load_frozen_prompt(root))
    assert audit["status"] == "PASS"


@pytest.mark.parametrize("scenario,status", [("match", "MATCH"), ("anomaly", "ANOMALY"), ("insufficient", "INSUFFICIENT_EVIDENCE")])
def test_mock_valid_outputs_and_cross_field_invariants(scenario: str, status: str) -> None:
    case = _case()
    call = MockReasonerClient([scenario]).call(prompt="p", case_payload=case.payload)
    result = validate_prediction(call.parsed_payload, expected_case_id="C1", expected_retrieved_record_ids=IDS)
    assert result.status == status


@pytest.mark.parametrize("scenario", ["malformed", "wrong_case_id", "invented_evidence", "nonretrieved_evidence", "invalid_class"])
def test_mock_invalid_outputs_are_rejected(scenario: str) -> None:
    case = _case()
    call = MockReasonerClient([scenario]).call(prompt="p", case_payload=case.payload)
    with pytest.raises((ValueError, ValidationError)):
        validate_prediction(
            call.parsed_payload if call.parsed_payload is not None else call.raw_output_text or "",
            expected_case_id="C1", expected_retrieved_record_ids=IDS,
        )


def test_strict_schema_abstention_and_match_requirements() -> None:
    with pytest.raises(ValidationError):
        RAGPrediction(case_id="C1", method="rag", status="INSUFFICIENT_EVIDENCE",
                      is_anomaly=None, predicted_failure_type=None,
                      evidence_record_ids=[IDS[0]], reason="x", confidence=0.2,
                      retrieved_record_ids=IDS)
    with pytest.raises(ValidationError):
        RAGPrediction(case_id="C1", method="rag", status="MATCH", is_anomaly=False,
                      predicted_failure_type="NO_FAILURE", evidence_record_ids=[], reason="x",
                      confidence=0.2, retrieved_record_ids=IDS)


def test_request_hash_changes_for_every_material_request_input(root: Path) -> None:
    prompt = load_frozen_prompt(root)
    case = _case()
    base = reasoning_request_hash(case, selected_k=2, prompt=prompt)
    changed = build_reasoning_case(ROUTE, IDS, [TEXTS[0] + "x", TEXTS[1]])
    assert reasoning_request_hash(changed, selected_k=2, prompt=prompt) != base
    assert reasoning_request_hash(case, selected_k=2, prompt=prompt + "x") != base


def test_runner_retries_only_transient_and_checkpoints_terminal(tmp_path: Path, root: Path) -> None:
    case = _case()
    prompt = load_frozen_prompt(root)
    client = MockReasonerClient(["timeout", "rate_limit", "match"])
    result = run_reasoning_cases([case], client=client, prompt=prompt, selected_k=2,
                                 run_dir=tmp_path, sleeper=lambda _: None)
    assert result.successful_cases == 1 and result.retry_events == 2
    assert client.call_count == 3
    resumed = MockReasonerClient(["anomaly"])
    second = run_reasoning_cases([case], client=resumed, prompt=prompt, selected_k=2,
                                 run_dir=tmp_path, sleeper=lambda _: None)
    assert second.skipped_immutable_cases == 1 and resumed.call_count == 0


@pytest.mark.parametrize("scenario", ["refusal", "malformed", "invented_evidence", "permanent_error"])
def test_terminal_model_and_permanent_failures_are_never_regenerated(tmp_path: Path, root: Path, scenario: str) -> None:
    case = _case()
    prompt = load_frozen_prompt(root)
    first_client = MockReasonerClient([scenario])
    run_reasoning_cases([case], client=first_client, prompt=prompt, selected_k=2,
                        run_dir=tmp_path, sleeper=lambda _: None)
    second_client = MockReasonerClient(["match"])
    result = run_reasoning_cases([case], client=second_client, prompt=prompt, selected_k=2,
                                 run_dir=tmp_path, sleeper=lambda _: None)
    assert result.skipped_immutable_cases == 1 and second_client.call_count == 0


def test_paid_cli_commands_reject_missing_execute_api(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="--execute-api"):
        main(["build-index", "--run-id", "blocked", "--output-root", str(tmp_path)])
    assert not (tmp_path / "blocked").exists()


def test_primary_modules_are_no_graph_and_do_not_import_evaluation(root: Path) -> None:
    assert no_graph_audit(root)["status"] == "PASS"
    for name in ("query.py", "retriever.py", "retrieval_runner.py", "reasoner.py", "runner.py"):
        text = (root / "src/rag" / name).read_text(encoding="utf-8")
        assert "src.rag.evidence" not in text
        assert "rca_ground_truth" not in text
        assert "failure_manifest" not in text


def test_no_secret_is_persisted_in_mock_artifacts(tmp_path: Path, root: Path, monkeypatch) -> None:
    fake_secret = "".join(("s", "k-", "this-is-a-test-secret-value"))
    monkeypatch.setenv("OPENAI_API_KEY", fake_secret)
    case = _case()
    run_reasoning_cases([case], client=MockReasonerClient(["match"]),
                        prompt=load_frozen_prompt(root), selected_k=2, run_dir=tmp_path)
    assert fake_secret not in "".join(
        path.read_text(encoding="utf-8") for path in tmp_path.iterdir() if path.is_file()
    )
