from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.graphrag.v1_1.candidate_traversal import CandidateTraversalEngine, FrozenGraph, canonical_json
from src.graphrag.v1_1.graph_reasoning import (
    SERIALIZER_VERSION,
    build_inference_object,
    build_reasoning_case_from_inference_object,
    deterministic_preflight_case_ids,
    inference_object_sha256,
    validate_inference_object,
)
from src.graphrag.v1_1.llm_evaluation import paired_bootstrap, paired_classification
from src.graphrag.v1_1.split_neutral_traversal import SplitNeutralTraversalEngine
from src.graphrag.v1_1.typed_grammar_loader import load_verified_grammar
from src.rag.config import REASONER_CONFIG
from src.rag.corpus import CorpusDocument
from src.rag.reasoner import MockReasonerClient
from src.rag.schemas import validate_prediction


def _document(record_id: str, node_type: str, source_table: str) -> CorpusDocument:
    text = f"RECORD_TYPE: {node_type}\nRECORD_ID: {record_id}\nID: \"X\""
    digest = __import__("hashlib").sha256(text.encode()).hexdigest()
    return CorpusDocument(
        record_id=record_id,
        record_type=node_type,
        source_table=source_table,
        source_file=f"data/benchmark/full/{source_table}.csv",
        available_at="2026-01-01",
        source_system="ERP",
        relational_ids={},
        ordinal=0,
        text=text,
        text_sha256=digest,
        row={"id": "X"},
    )


def _fixture_object():
    invoice = _document("invoices:INV1", "INVOICE", "invoices")
    line = _document("invoice_lines:LINE1", "INVOICE_LINE", "invoice_lines")
    documents = {value.record_id: value for value in (invoice, line)}
    nodes = {
        value.record_id: {
            "record_id": value.record_id,
            "node_type": value.record_type,
            "source_table": value.source_table,
            "document_sha256": value.text_sha256,
        }
        for value in (invoice, line)
    }
    records = [
        {
            "case_id": "C1",
            "record_id": invoice.record_id,
            "selected_record_rank": 1,
            "node_type": "INVOICE",
            "minimum_reachable_depth": 0,
            "selection_tier_name": "MANDATORY_ANCHOR",
            "selection_tier": 0,
        },
        {
            "case_id": "C1",
            "record_id": line.record_id,
            "selected_record_rank": 2,
            "node_type": "INVOICE_LINE",
            "minimum_reachable_depth": 1,
            "selection_tier_name": "MAXIMAL_BACKBONE_LIFECYCLE_PATH",
            "selection_tier": 3,
        },
    ]
    paths = [{
        "case_id": "C1",
        "selected_path_rank": 1,
        "depth": 1,
        "selection_tier_name": "MAXIMAL_BACKBONE_LIFECYCLE_PATH",
        "record_id_sequence": [invoice.record_id, line.record_id],
        "node_type_sequence": ["INVOICE", "INVOICE_LINE"],
        "relation_id_sequence": ["LINE_OF_INVOICE"],
        "direction_sequence": ["REVERSE"],
        "provenance": [{"provenance_record_id": line.record_id}],
        "terminal_status": False,
        "stop_reason": "CONTINUATION_ALLOWED_PREFIX",
    }]
    return build_inference_object(
        {"case_id": "C1", "primary_entity_type": "invoice", "primary_entity_id": "INV1"},
        records,
        paths,
        documents,
        nodes,
    )


def test_graph_inference_projection_and_serializer_are_deterministic() -> None:
    value = _fixture_object()
    validate_inference_object(value)
    assert value["serializer_version"] == SERIALIZER_VERSION
    assert inference_object_sha256(value) == inference_object_sha256(json.loads(json.dumps(value)))
    case = build_reasoning_case_from_inference_object(value)
    assert case.retrieved_record_ids == ("invoices:INV1", "invoice_lines:LINE1")
    assert "GRAPH_PATH_SUMMARIES_BEGIN" in case.payload
    assert "LINE_OF_INVOICE:REVERSE" in case.payload
    assert case.payload.index("invoices:INV1") < case.payload.index("invoice_lines:LINE1")


def test_graph_context_uses_unchanged_parser_and_citation_contract() -> None:
    case = build_reasoning_case_from_inference_object(_fixture_object())
    call = MockReasonerClient(["anomaly"]).call(prompt="same", case_payload=case.payload)
    parsed = validate_prediction(
        call.parsed_payload,
        expected_case_id="C1",
        expected_retrieved_record_ids=list(case.retrieved_record_ids),
    )
    assert parsed.evidence_record_ids == ["invoices:INV1"]
    assert parsed.predicted_failure_type == "F01_DUPLICATE_INVOICE"


def test_inference_projection_rejects_target_fields() -> None:
    value = _fixture_object()
    value["failure_type"] = "F01_DUPLICATE_INVOICE"
    with pytest.raises(RuntimeError, match="key drift"):
        validate_inference_object(value)


def test_preflight_case_selection_is_label_blind_and_order_independent() -> None:
    ids = [f"C{value:03d}" for value in range(30)]
    assert deterministic_preflight_case_ids(ids, 16) == deterministic_preflight_case_ids(reversed(ids), 16)
    assert len(deterministic_preflight_case_ids(ids, 16)) == 16


def test_exact_standard_reasoner_identity_is_retained() -> None:
    assert REASONER_CONFIG.model_id == "gpt-5.6-sol"
    assert REASONER_CONFIG.reasoning_effort == "medium"
    assert REASONER_CONFIG.max_output_tokens == 1000
    assert REASONER_CONFIG.verbosity == "low"
    assert REASONER_CONFIG.max_attempts == 4


def test_paired_statistics_are_deterministic_and_count_discordance() -> None:
    ids = ["C1", "C2", "C3", "C4"]
    labels = {"C1": "NO_FAILURE", "C2": "F01_DUPLICATE_INVOICE", "C3": "NO_FAILURE", "C4": "F02_PO_INVOICE_AMOUNT_MISMATCH"}
    graph_labels = ["NO_FAILURE", "F01_DUPLICATE_INVOICE", "F01_DUPLICATE_INVOICE", "F02_PO_INVOICE_AMOUNT_MISMATCH"]
    standard_labels = ["F01_DUPLICATE_INVOICE", "F01_DUPLICATE_INVOICE", "NO_FAILURE", "F03_QUANTITY_MISMATCH"]
    def rows(values):
        return {
            case_id: {
                "case_id": case_id,
                "predicted_failure_type": value,
                "parse_status": "PASS",
            }
            for case_id, value in zip(ids, values)
        }
    graph, standard = rows(graph_labels), rows(standard_labels)
    summary, paired = paired_classification(ids, labels, graph, standard)
    assert summary["graph_only_correct"] == 2
    assert summary["standard_only_correct"] == 1
    assert len(paired) == 4
    first = paired_bootstrap(ids, labels, graph, standard)
    second = paired_bootstrap(ids, labels, graph, standard)
    assert first == second and first["resamples"] == 10_000


def test_split_neutral_adapter_exactly_matches_frozen_validation() -> None:
    root = Path.cwd()
    bundle = load_verified_grammar(root)
    graph, _ = FrozenGraph.load(root)
    routes = [
        json.loads(line)
        for line in (root / "results/rag/phase5_rag_validation_routes_v1_0_20260812T040938Z/validation_routes.jsonl").read_text().splitlines()
        if line
    ]
    frozen = CandidateTraversalEngine(graph, bundle).run(routes)
    adapted = SplitNeutralTraversalEngine(graph, bundle).run(routes)
    for name in ("anchor_resolutions", "candidate_paths", "candidate_records", "rejections"):
        assert canonical_json(getattr(frozen, name)) == canonical_json(getattr(adapted, name))
    assert adapted.telemetry["candidate_path_set_sha256"] == "89d7f799f60149a8e6665bf59a484131f450ec2ab435e9a891e1eec3efbb2944"
