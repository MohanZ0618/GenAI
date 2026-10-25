from __future__ import annotations

from src.direct_llm.cli import build_parser
from src.direct_llm.evaluation import classification_metrics, mcnemar_exact


def test_classification_metrics_count_unresolved_strictly_incorrect() -> None:
    labels = {"A": "NO_FAILURE", "B": "F01_DUPLICATE_INVOICE", "C": "F02_PO_INVOICE_AMOUNT_MISMATCH"}
    predictions = [
        {"case_id": "A", "status": "MATCH", "parse_status": "PASS", "predicted_failure_type": "NO_FAILURE"},
        {"case_id": "B", "status": "ANOMALY", "parse_status": "PASS", "predicted_failure_type": "F01_DUPLICATE_INVOICE"},
        {"case_id": "C", "status": "PERMANENT_API_ERROR", "parse_status": "PERMANENT_API_ERROR", "predicted_failure_type": None},
    ]
    metrics, confusion = classification_metrics(predictions, labels)
    assert metrics["exact_16_class_accuracy"] == 2 / 3
    assert metrics["binary_accuracy_strict"] == 2 / 3
    assert metrics["api_failure_count"] == 1
    assert sum(row["support"] for row in confusion) == 3


def test_mcnemar_exact_is_paired_and_symmetric() -> None:
    direct = [True, True, False, False]
    other = [True, False, True, False]
    result = mcnemar_exact(direct, other, "test")
    assert result["other_only_correct"] == 1
    assert result["direct_llm_only_correct"] == 1
    assert result["two_sided_exact_p_value"] == 1.0


def test_paid_modes_require_explicit_flag_in_parser() -> None:
    parser = build_parser()
    stability = parser.parse_args([
        "stability", "--preflight-dir", "p", "--run-id", "s",
    ])
    held_out = parser.parse_args([
        "run", "--preflight-dir", "p", "--run-id", "r",
    ])
    probe = parser.parse_args([
        "probe", "--preflight-dir", "p", "--run-id", "d",
    ])
    prepare = parser.parse_args(["prepare", "--run-id", "p"])
    assert stability.execute_api is False
    assert held_out.execute_api is False
    assert probe.execute_api is False
    assert not hasattr(prepare, "execute_api")
