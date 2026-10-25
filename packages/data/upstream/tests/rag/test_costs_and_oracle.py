from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.cli import main
from src.rag.corpus import CorpusDocument, FrozenCorpus
from src.rag.costs import direct_packet_compression, end_to_end_accounting
from src.rag.leakage import OpenedPathAudit
from src.rag.oracle import build_oracle_cases


def test_component_costs_remain_separate() -> None:
    retrieval = [{
        "case_id": "C", "query_embedding_input_tokens": 10,
        "query_embedding_latency_ms": 2, "index_search_latency_ms": 3,
        "retrieval_latency_ms": 6,
    }]
    predictions = [{
        "case_id": "C", "latency_ms": 10, "context_assembly_latency_ms": 1,
        "usage": {"input_tokens": 100, "cached_input_tokens": 20,
                  "output_tokens": 10, "reasoning_tokens": 5},
    }]
    report = end_to_end_accounting(
        retrieval, predictions,
        {"total_embedding_tokens": 1000, "corpus_embedding_cost_usd": 0.00002,
         "expected_batches": 2, "embedding_retry_count": 0},
    )
    assert report["corpus_indexing"]["one_time_cost_usd"] == 0.00002
    assert report["per_case"][0]["end_to_end_latency_ms"] == 17
    assert report["per_case"][0]["marginal_cost_usd"] > 0


def test_direct_packet_compression_is_paired_and_deterministic() -> None:
    summary, rows = direct_packet_compression(
        [{"case_id": "C", "retrieved_context_characters": 30, "retrieval_set_size": 2}],
        [{"case_id": "C", "serialized_packet": "x" * 300, "record_count": 20}],
    )
    assert rows[0]["context_reduction"] == 0.9
    assert rows[0]["record_count_reduction"] == 0.9
    assert summary["case_count"] == 1


def test_oracle_context_contains_only_resolved_operational_G_i() -> None:
    document = CorpusDocument(
        record_id="invoices:INV1", record_type="INVOICE", source_table="invoices",
        source_file="test", available_at="2026-01-01", source_system="ERP",
        relational_ids={"invoice_id": "INV1"}, ordinal=0,
        text='RECORD_TYPE: INVOICE\nRECORD_ID: invoices:INV1\nINVOICE_ID: "INV1"',
        text_sha256="x", row={"invoice_id": "INV1"},
    )
    corpus = FrozenCorpus(
        [document], {"invoices": [document.row]}, {"invoices": [document.row]},
        {"status": "PASS"}, "x", OpenedPathAudit("oracle_diagnostic"),
    )
    route = {"case_id": "C", "primary_entity_type": "invoice", "primary_entity_id": "INV1"}
    truth = {"case_id": "C", "evidence_ids": ["INV1"], "evidence_required": ["invoices"],
             "failure_type": "F01_DUPLICATE_INVOICE", "root_cause": "must not leak"}
    cases = build_oracle_cases([route], [truth], corpus)
    assert cases[0].required_record_ids == (document.record_id,)
    assert "F01_DUPLICATE_INVOICE" not in cases[0].reasoning_case.payload
    assert "must not leak" not in cases[0].reasoning_case.payload


def test_oracle_cli_requires_separate_explicit_authorization(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="--execute-api"):
        main([
            "oracle-diagnostic", "--index-dir", str(tmp_path), "--routes", str(tmp_path / "routes"),
            "--primary-run-dir", str(tmp_path / "primary"), "--run-id", "oracle",
        ])
