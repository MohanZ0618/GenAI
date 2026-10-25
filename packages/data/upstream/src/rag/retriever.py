"""Exactly one query embedding followed by one global exact Top-K search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.rag.config import EMBEDDING_CONFIG
from src.rag.embeddings import EmbeddingClient, normalize_vectors
from src.rag.index import ExactFlatCosineNumpyV1, SearchHit
from src.rag.query import RetrievalQuery


@dataclass(frozen=True)
class RetrievalResult:
    case_id: str
    query_sha256: str
    query_embedding_input_tokens: int
    query_embedding_latency_ms: float
    query_embedding_request_id: str | None
    query_embedding_response_model: str | None
    index_search_latency_ms: float
    hits: tuple[SearchHit, ...]
    created_at_utc: str

    def artifact_row(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "query_sha256": self.query_sha256,
            "query_embedding_input_tokens": self.query_embedding_input_tokens,
            "query_embedding_latency_ms": self.query_embedding_latency_ms,
            "query_embedding_request_id": self.query_embedding_request_id,
            "query_embedding_response_model": self.query_embedding_response_model,
            "index_search_latency_ms": self.index_search_latency_ms,
            "retrieval_latency_ms": self.query_embedding_latency_ms + self.index_search_latency_ms,
            "retrieved_record_ids": [hit.record_id for hit in self.hits],
            "scores": [hit.score for hit in self.hits],
            "hits": [hit.serializable() for hit in self.hits],
            "created_at_utc": self.created_at_utc,
            "retrieval_operations": 1,
            "query_embedding_operations": 1,
            "reranking": False,
            "metadata_filtering": False,
            "graph_expansion": False,
        }


def retrieve_once(
    query: RetrievalQuery,
    *,
    client: EmbeddingClient,
    index: ExactFlatCosineNumpyV1,
    k: int,
) -> RetrievalResult:
    response = client.embed([query.text])
    vectors = normalize_vectors(response.vectors, EMBEDDING_CONFIG.dimensions)
    if vectors.shape[0] != 1:
        raise RuntimeError(f"query batch size must be exactly one, observed {vectors.shape[0]}")
    hits, search_latency = index.search(vectors[0], k)
    return RetrievalResult(
        case_id=query.case_id,
        query_sha256=query.sha256,
        query_embedding_input_tokens=response.input_tokens,
        query_embedding_latency_ms=response.latency_ms,
        query_embedding_request_id=response.request_id,
        query_embedding_response_model=response.response_model,
        index_search_latency_ms=search_latency,
        hits=tuple(hits),
        created_at_utc=datetime.now(timezone.utc).isoformat(),
    )
