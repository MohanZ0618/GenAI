from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.rag.config import EMBEDDING_CONFIG
from src.rag.corpus import CorpusDocument
from src.rag.embeddings import (
    MockEmbeddingClient,
    embed_corpus,
    finalize_embedding_matrix,
    normalize_vectors,
)
from src.rag.index import ExactFlatCosineNumpyV1
from src.rag.query import build_query
from src.rag.retriever import retrieve_once
from src.rag.retrieval_runner import run_retrieval


ROUTES = (
    {"case_id": "C_INV", "primary_entity_type": "invoice", "primary_entity_id": "INV_0428002"},
    {"case_id": "C_PAY", "primary_entity_type": "payment", "primary_entity_id": "PAY_0426002"},
    {"case_id": "C_GL", "primary_entity_type": "gl_journal", "primary_entity_id": "JE_0430347"},
    {"case_id": "C_BANK", "primary_entity_type": "bank_transaction", "primary_entity_id": "BT_0426267"},
)


def _document(number: int) -> CorpusDocument:
    return CorpusDocument(
        record_id=f"test:{number}", record_type="TEST", source_table="invoices",
        source_file="test", available_at="2026-01-01", source_system="TEST",
        relational_ids={}, ordinal=number, text=f"document {number}",
        text_sha256=str(number), row={},
    )


@pytest.mark.parametrize("route", ROUTES)
def test_all_four_query_anchors_are_deterministic_and_case_id_free(frozen_corpus, route) -> None:
    first = build_query(route, frozen_corpus)
    second = build_query(dict(route), frozen_corpus)
    assert first.text.encode("utf-8") == second.text.encode("utf-8")
    assert first.sha256 == second.sha256
    assert route["case_id"] not in first.text
    assert not first.text.endswith("\n")
    if route["primary_entity_type"] == "gl_journal":
        expected = sorted(first.anchor_record_ids)
        assert list(first.anchor_record_ids) == expected
        assert len(first.anchor_record_ids) >= 2


def test_missing_and_unsupported_anchors_are_technical_failures(frozen_corpus) -> None:
    with pytest.raises(RuntimeError, match="unsupported"):
        build_query({"case_id": "C", "primary_entity_type": "vendor", "primary_entity_id": "V"}, frozen_corpus)
    with pytest.raises(RuntimeError, match="exactly one"):
        build_query({"case_id": "C", "primary_entity_type": "invoice", "primary_entity_id": "MISSING"}, frozen_corpus)


def test_embedding_batching_validation_checkpoint_and_resume(tmp_path: Path) -> None:
    config = replace(EMBEDDING_CONFIG, dimensions=4, corpus_batch_size=2)
    documents = [_document(value) for value in range(5)]
    first_client = MockEmbeddingClient(dimensions=4)
    first = embed_corpus(documents, client=first_client, output_dir=tmp_path, config=config)
    assert [len(batch) for batch in first_client.calls] == [2, 2, 1]
    assert first["completed_batches"] == 3
    second_client = MockEmbeddingClient(dimensions=4)
    second = embed_corpus(documents, client=second_client, output_dir=tmp_path, config=config)
    assert not second_client.calls
    assert second["skipped_completed_batches"] == 3
    finalized = finalize_embedding_matrix(documents, tmp_path, config=config)
    assert finalized["vector_count"] == 5
    assert finalized["dimensions"] == 4
    with pytest.raises(RuntimeError, match="dimension"):
        normalize_vectors(np.ones((2, 3), dtype=np.float32), 4)
    invalid = np.ones((2, 4), dtype=np.float32)
    invalid[0, 0] = np.nan
    with pytest.raises(RuntimeError, match="nonfinite"):
        normalize_vectors(invalid, 4)


def test_exact_cosine_ties_persistence_and_alignment(tmp_path: Path) -> None:
    vectors = np.asarray([[1, 0], [1, 0], [0, 1]], dtype="<f4")
    index = ExactFlatCosineNumpyV1(vectors, ["b", "a", "c"])
    hits, _ = index.search(np.asarray([1, 0], dtype=np.float32), 3)
    assert [hit.record_id for hit in hits] == ["a", "b", "c"]
    matrix = tmp_path / "embeddings.npy"
    ids = tmp_path / "record_ids.txt"
    with matrix.open("wb") as handle:
        np.save(handle, vectors, allow_pickle=False)
    ids.write_text("b\na\nc\n", encoding="utf-8")
    loaded = ExactFlatCosineNumpyV1.load(matrix, ids)
    assert [hit.record_id for hit in loaded.search(np.asarray([1, 0]), 3)[0]] == ["a", "b", "c"]
    with pytest.raises(RuntimeError, match="alignment"):
        ExactFlatCosineNumpyV1(vectors, ["a"])


def test_one_shot_retrieval_has_no_filters_expansion_or_reranking(frozen_corpus) -> None:
    query = build_query(ROUTES[0], frozen_corpus)
    corpus_vectors = np.zeros((3, 1536), dtype="<f4")
    corpus_vectors[:, 0] = 1
    index = ExactFlatCosineNumpyV1(corpus_vectors, ["a", "b", "c"])
    client = MockEmbeddingClient(dimensions=1536)
    result = retrieve_once(query, client=client, index=index, k=2)
    artifact = result.artifact_row()
    assert len(client.calls) == 1 and len(client.calls[0]) == 1
    assert artifact["retrieval_operations"] == artifact["query_embedding_operations"] == 1
    assert artifact["reranking"] is artifact["metadata_filtering"] is artifact["graph_expansion"] is False
    assert len(artifact["retrieved_record_ids"]) == 2


def test_ineligible_anchor_is_checkpointed_per_case_without_api_call(frozen_corpus, tmp_path: Path) -> None:
    routes = [
        {"case_id": "C_FUTURE", "primary_entity_type": "gl_journal", "primary_entity_id": "JE_0430730"},
        ROUTES[0],
    ]
    corpus_vectors = np.zeros((3, 1536), dtype="<f4")
    corpus_vectors[:, 0] = 1
    index = ExactFlatCosineNumpyV1(corpus_vectors, ["a", "b", "c"])
    client = MockEmbeddingClient(dimensions=1536)
    summary = run_retrieval(
        routes, corpus=frozen_corpus, client=client, index=index, k=2,
        output_dir=tmp_path, index_manifest_sha256="index-sha", sleeper=lambda _: None,
    )
    assert summary.total_cases == 2
    assert summary.successful_cases == 1
    assert summary.anchor_technical_failures == 1
    assert len(client.calls) == 1
    rows = [json.loads(line) for line in (tmp_path / "retrieval_results.jsonl").read_text().splitlines()]
    by_id = {row["case_id"]: row for row in rows}
    assert by_id["C_FUTURE"]["status"] == "ANCHOR_TECHNICAL_FAILURE"
    assert by_id["C_FUTURE"]["query_embedding_operations"] == 0
    assert by_id["C_INV"]["status"] == "SUCCESS"
