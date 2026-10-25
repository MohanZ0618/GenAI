from __future__ import annotations

import copy

import pytest

from src.rag.corpus import CorpusDocument
from src.rag.evaluation import (
    aggregate_evidence, attribute_failure, classification_metrics,
    evidence_prediction_metrics, paired_comparison, select_k,
)
from src.rag.evidence import ResolvedEvidence


def _aggregates():
    return {
        k: {"macro": {
            "document_recall": 0.5,
            "strict_full_contract_coverage": 0.4,
            "observable_table_coverage": 0.6,
            "irrelevant_record_count": 10.0,
            "retrieved_context_tokens": 100.0,
        }}
        for k in (5, 10, 20, 40)
    }


@pytest.mark.parametrize(
    "metric,winner,winner_value",
    [
        ("document_recall", 40, 0.6),
        ("strict_full_contract_coverage", 20, 0.5),
        ("observable_table_coverage", 10, 0.7),
        ("irrelevant_record_count", 40, 9.0),
        ("retrieved_context_tokens", 20, 90.0),
    ],
)
def test_k_selection_each_metric_level(metric: str, winner: int, winner_value: float) -> None:
    values = _aggregates()
    values[winner]["macro"][metric] = winner_value
    # Equalize every earlier hierarchy level so this metric is decisive.
    hierarchy = ["document_recall", "strict_full_contract_coverage", "observable_table_coverage",
                 "irrelevant_record_count", "retrieved_context_tokens"]
    for earlier in hierarchy[:hierarchy.index(metric)]:
        for k in values:
            values[k]["macro"][earlier] = values[winner]["macro"][earlier]
    assert select_k(values, "abc")["selected_k"] == winner


def test_k_selection_final_tie_prefers_lower_k_and_hash_is_stable() -> None:
    first = select_k(_aggregates(), "abc")
    second = select_k(copy.deepcopy(_aggregates()), "abc")
    assert first["selected_k"] == 5
    assert first["selection_content_sha256"] == second["selection_content_sha256"]


def test_strict_classification_scoring_counts_abstention_as_wrong() -> None:
    labels = {"a": "NO_FAILURE", "b": "F01_DUPLICATE_INVOICE"}
    predictions = [
        {"case_id": "a", "status": "MATCH", "predicted_failure_type": "NO_FAILURE", "parse_status": "PASS"},
        {"case_id": "b", "status": "INSUFFICIENT_EVIDENCE", "predicted_failure_type": None, "parse_status": "PASS"},
    ]
    metrics = classification_metrics(predictions, labels)
    assert metrics["exact_16_class_accuracy"] == 0.5
    assert metrics["insufficient_evidence_count"] == 1
    assert metrics["fn"] == 1
    assert metrics["micro_f1_16_classes"] == 0.5
    assert metrics["confusion_matrix"]["predicted_labels"][-1] == "__UNRESOLVED__"


def _invoice_document() -> CorpusDocument:
    return CorpusDocument(
        record_id="invoices:INV1", record_type="INVOICE", source_table="invoices",
        source_file="test", available_at="2026-01-01", source_system="ERP",
        relational_ids={"invoice_id": "INV1"}, ordinal=0,
        text='RECORD_TYPE: INVOICE\nRECORD_ID: invoices:INV1\nINVOICE_ID: "INV1"',
        text_sha256="x", row={"invoice_id": "INV1"},
    )


def test_evidence_metrics_and_frozen_attribution_precedence() -> None:
    document = _invoice_document()
    evidence = ResolvedEvidence(
        case_id="C", annotated_ids=frozenset({"INV1"}), required_tables=frozenset({"invoices"}),
        required_record_ids=frozenset({document.record_id}), observable_tables=frozenset({"invoices"}),
        absence_only_tables=frozenset(), record_tokens={document.record_id: frozenset({"INV1"})},
        record_tables={document.record_id: "invoices"},
    )
    truth = {"case_id": "C", "failure_type": "NO_FAILURE"}
    prediction = {
        "case_id": "C", "status": "MATCH", "parse_status": "PASS",
        "predicted_failure_type": "NO_FAILURE", "retrieved_record_ids": [document.record_id],
        "evidence_record_ids": [document.record_id],
    }
    row = evidence_prediction_metrics(
        truth, prediction, evidence, {document.record_id: document},
        adjudication={"citation_support": True, "unsupported_explanation": False},
    )
    assert row["citation_valid"] and row["strict_evidence_contract_accuracy"]
    assert row["fully_grounded_reconciliation"] is True
    assert aggregate_evidence([row])["fully_grounded_reconciliation_rate"] == 1.0
    retrieval = {"strict_full_contract_coverage": True}
    assert attribute_failure(truth, prediction, retrieval, row)["attribution"] == "NO_FAILURE"
    wrong = {**prediction, "predicted_failure_type": "F01_DUPLICATE_INVOICE", "status": "ANOMALY"}
    wrong_row = {**row, "class_correct": False}
    assert attribute_failure(truth, wrong, retrieval, wrong_row)["attribution"] == "REASONING_FAILURE"


def test_paired_comparison_includes_exact_mcnemar_and_bootstrap() -> None:
    labels = {"a": "NO_FAILURE", "b": "F01_DUPLICATE_INVOICE"}
    rag = [
        {"case_id": "a", "predicted_failure_type": "NO_FAILURE", "parse_status": "PASS"},
        {"case_id": "b", "predicted_failure_type": "NO_FAILURE", "parse_status": "PASS"},
    ]
    other = [
        {"case_id": "a", "predicted_failure_type": "F01_DUPLICATE_INVOICE"},
        {"case_id": "b", "predicted_failure_type": "F01_DUPLICATE_INVOICE"},
    ]
    summary, rows = paired_comparison(rag, other, labels, "other")
    assert len(rows) == 2 and summary["discordant_pairs"] == 2
    assert 0 <= summary["mcnemar_exact_two_sided_p_value"] <= 1
