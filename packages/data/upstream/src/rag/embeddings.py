"""Frozen OpenAI embedding client, batch checkpoints, retries, and persistence."""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Protocol, Sequence

import numpy as np

from src.direct_llm.client import PermanentAPIError, TransientAPIError, classify_openai_exception
from src.rag.artifacts import append_jsonl, canonical_json, sha256_bytes, sha256_file, write_json
from src.rag.config import CORPUS_VERSION, EMBEDDING_CONFIG, SPEC_SHA256, EmbeddingConfig
from src.rag.corpus import CorpusDocument


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: np.ndarray
    input_tokens: int
    response_model: str | None
    request_id: str | None
    latency_ms: float
    organization_id: str | None = None
    project_id: str | None = None


class EmbeddingClient(Protocol):
    def embed(self, texts: Sequence[str]) -> EmbeddingResponse: ...


class OpenAIEmbeddingClient:
    def __init__(self, config: EmbeddingConfig = EMBEDDING_CONFIG):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("OpenAI Python SDK is required for --execute-api") from exc
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required only for --execute-api")
        self.config = config
        self.client = OpenAI(timeout=config.request_timeout_seconds, max_retries=0)

    def embed(self, texts: Sequence[str]) -> EmbeddingResponse:
        started = perf_counter()
        try:
            response = self.client.embeddings.create(
                model=self.config.model_id,
                input=list(texts),
                dimensions=self.config.dimensions,
                encoding_format=self.config.encoding_format,
            )
        except Exception as exc:
            raise classify_openai_exception(exc) from exc
        returned_model = getattr(response, "model", None)
        if returned_model is not None and returned_model != self.config.model_id:
            raise PermanentAPIError(
                "EMBEDDING_MODEL_ID_MISMATCH",
                {"expected_model": self.config.model_id, "returned_model": returned_model},
            )
        vectors = np.asarray([item.embedding for item in response.data], dtype="<f4", order="C")
        usage = getattr(response, "usage", None)
        return EmbeddingResponse(
            vectors=vectors,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            response_model=returned_model,
            request_id=getattr(response, "_request_id", None),
            latency_ms=(perf_counter() - started) * 1000,
        )


class MockEmbeddingClient:
    """Deterministic test client; vectors depend only on input bytes."""

    def __init__(self, dimensions: int = 1536, failures: list[str] | None = None):
        self.dimensions = dimensions
        self.failures = list(failures or [])
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> EmbeddingResponse:
        self.calls.append(list(texts))
        if self.failures:
            failure = self.failures.pop(0)
            if failure == "transient":
                raise TransientAPIError("MOCK_TRANSIENT")
            if failure == "permanent":
                raise PermanentAPIError("MOCK_PERMANENT")
            if failure == "wrong_dimension":
                return EmbeddingResponse(np.ones((len(texts), self.dimensions - 1), dtype="<f4"), 0, "mock", "mock", 0.1)
            if failure == "nonfinite":
                value = np.ones((len(texts), self.dimensions), dtype="<f4")
                value[0, 0] = np.nan
                return EmbeddingResponse(value, 0, "mock", "mock", 0.1)
        vectors = []
        for text in texts:
            seed = int(sha256_bytes(text)[:16], 16)
            generator = np.random.default_rng(seed)
            vectors.append(generator.standard_normal(self.dimensions, dtype=np.float32))
        return EmbeddingResponse(np.asarray(vectors, dtype="<f4", order="C"), sum(len(t) for t in texts), "mock-embedding", "mock-request", 0.1)


def normalize_vectors(vectors: np.ndarray, dimensions: int = 1536) -> np.ndarray:
    value = np.asarray(vectors, dtype="<f4", order="C")
    if value.ndim != 2 or value.shape[1] != dimensions:
        raise RuntimeError(f"embedding dimension mismatch: expected (*,{dimensions}), observed {value.shape}")
    if not np.isfinite(value).all():
        raise RuntimeError("embedding response contains nonfinite values")
    norms = np.linalg.norm(value, axis=1, keepdims=True)
    if np.any(norms == 0) or not np.isfinite(norms).all():
        raise RuntimeError("embedding response contains zero/invalid vectors")
    normalized = np.asarray(value / norms, dtype="<f4", order="C")
    if not normalized.flags.c_contiguous:
        raise AssertionError("normalized embeddings are not C-contiguous")
    return normalized


def embedding_request_hash(record_ids: Sequence[str], texts: Sequence[str], config: EmbeddingConfig) -> str:
    return sha256_bytes(canonical_json({
        "spec_sha256": SPEC_SHA256,
        "corpus_version": CORPUS_VERSION,
        "model_id": config.model_id,
        "dimensions": config.dimensions,
        "encoding_format": config.encoding_format,
        "record_ids": list(record_ids),
        "text_sha256": [sha256_bytes(text) for text in texts],
    }))


def _save_batch(path: Path, vectors: np.ndarray) -> None:
    temporary = path.with_suffix(".npy.tmp")
    with temporary.open("wb") as handle:
        np.save(handle, vectors, allow_pickle=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _ledger_by_batch(path: Path) -> dict[int, dict[str, Any]]:
    latest: dict[int, dict[str, Any]] = {}
    if not path.is_file():
        return latest
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            latest[int(row["batch_number"])] = row
    return latest


def embed_corpus(
    documents: Sequence[CorpusDocument],
    *,
    client: EmbeddingClient,
    output_dir: Path,
    config: EmbeddingConfig = EMBEDDING_CONFIG,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_dir = output_dir / "embedding_batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "embedding_ledger.jsonl"
    previous = _ledger_by_batch(ledger_path)
    total_batches = math.ceil(len(documents) / config.corpus_batch_size)
    skipped = completed = retries = 0

    for batch_number in range(total_batches):
        start = batch_number * config.corpus_batch_size
        end = min(start + config.corpus_batch_size, len(documents))
        batch = documents[start:end]
        record_ids = [document.record_id for document in batch]
        texts = [document.text for document in batch]
        request_hash = embedding_request_hash(record_ids, texts, config)
        vector_path = batch_dir / f"batch_{batch_number:06d}.npy"
        prior = previous.get(batch_number)
        if prior:
            if prior.get("request_hash") != request_hash:
                raise RuntimeError(f"embedding request hash changed on resume: batch {batch_number}")
            if prior.get("status") == "PERMANENT_API_ERROR":
                raise RuntimeError(f"permanent embedding failure cannot be retried: batch {batch_number}")
        if prior and prior.get("status") == "SUCCESS":
            if not vector_path.is_file() or sha256_file(vector_path) != prior.get("vector_file_sha256"):
                raise RuntimeError(f"persisted embedding batch checksum mismatch: batch {batch_number}")
            skipped += 1
            completed += 1
            continue

        for attempt in range(1, config.max_attempts + 1):
            attempt_started = perf_counter()
            try:
                response = client.embed(texts)
                vectors = normalize_vectors(response.vectors, config.dimensions)
                if vectors.shape[0] != len(batch):
                    raise RuntimeError(
                        f"embedding row count mismatch: expected {len(batch)}, observed {vectors.shape[0]}"
                    )
            except TransientAPIError as exc:
                failed_latency_ms = (perf_counter() - attempt_started) * 1000
                exhausted = attempt == config.max_attempts
                append_jsonl(ledger_path, {
                    "batch_number": batch_number, "document_start": start, "document_end_exclusive": end,
                    "record_ids": record_ids, "request_hash": request_hash,
                    "status": "TRANSIENT_API_FAILURE_EXHAUSTED" if exhausted else "TRANSIENT_API_ERROR",
                    "attempt": attempt, "error_category": exc.category, "error_detail": exc.detail,
                    "latency_ms": failed_latency_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                })
                if exhausted:
                    raise RuntimeError(f"embedding retries exhausted at batch {batch_number}") from exc
                retries += 1
                sleeper(config.backoff_seconds[attempt - 1])
                continue
            except PermanentAPIError as exc:
                failed_latency_ms = (perf_counter() - attempt_started) * 1000
                append_jsonl(ledger_path, {
                    "batch_number": batch_number, "document_start": start, "document_end_exclusive": end,
                    "record_ids": record_ids, "request_hash": request_hash, "status": "PERMANENT_API_ERROR",
                    "attempt": attempt, "error_category": exc.category, "error_detail": exc.detail,
                    "latency_ms": failed_latency_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                })
                raise RuntimeError(f"permanent embedding API failure at batch {batch_number}") from exc
            _save_batch(vector_path, vectors)
            row = {
                "batch_number": batch_number,
                "document_start": start,
                "document_end_exclusive": end,
                "document_count": len(batch),
                "record_ids": record_ids,
                "request_hash": request_hash,
                "returned_dimensions": int(vectors.shape[1]),
                "input_tokens": response.input_tokens,
                "latency_ms": response.latency_ms,
                "request_id": response.request_id,
                "organization_id": response.organization_id,
                "project_id": response.project_id,
                "response_model_id": response.response_model,
                "retry_count": attempt - 1,
                "attempt": attempt,
                "status": "SUCCESS",
                "vector_file": str(vector_path),
                "vector_file_sha256": sha256_file(vector_path),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            append_jsonl(ledger_path, row)
            previous[batch_number] = row
            completed += 1
            break

    return {
        "document_count": len(documents), "batch_size": config.corpus_batch_size,
        "expected_batches": total_batches, "completed_batches": completed,
        "skipped_completed_batches": skipped, "retry_events": retries,
        "ledger_sha256": sha256_file(ledger_path),
    }


def finalize_embedding_matrix(
    documents: Sequence[CorpusDocument], output_dir: Path, config: EmbeddingConfig = EMBEDDING_CONFIG
) -> dict[str, Any]:
    ledger_path = output_dir / "embedding_ledger.jsonl"
    latest = _ledger_by_batch(ledger_path)
    with ledger_path.open("r", encoding="utf-8") as handle:
        all_ledger_rows = [json.loads(line) for line in handle if line.strip()]
    total_batches = math.ceil(len(documents) / config.corpus_batch_size)
    if set(latest) != set(range(total_batches)) or any(row.get("status") != "SUCCESS" for row in latest.values()):
        raise RuntimeError("embedding ledger is incomplete; matrix finalization refused")
    matrix_path = output_dir / "embeddings.npy"
    if matrix_path.exists():
        raise FileExistsError(f"immutable embedding matrix already exists: {matrix_path}")
    matrix = np.lib.format.open_memmap(
        matrix_path, mode="w+", dtype="<f4", shape=(len(documents), config.dimensions), fortran_order=False
    )
    cursor = 0
    total_tokens = 0
    for batch_number in range(total_batches):
        row = latest[batch_number]
        batch_path = output_dir / "embedding_batches" / f"batch_{batch_number:06d}.npy"
        if sha256_file(batch_path) != row["vector_file_sha256"]:
            raise RuntimeError(f"batch checksum mismatch during finalization: {batch_number}")
        batch = np.load(batch_path, allow_pickle=False)
        expected_ids = [document.record_id for document in documents[cursor:cursor + len(batch)]]
        if row["record_ids"] != expected_ids:
            raise RuntimeError(f"record/vector alignment mismatch at batch {batch_number}")
        matrix[cursor:cursor + len(batch)] = batch
        cursor += len(batch)
        total_tokens += int(row.get("input_tokens", 0))
    matrix.flush()
    del matrix
    if cursor != len(documents):
        raise RuntimeError("final vector count mismatch")
    result = {
        "vector_count": cursor,
        "dimensions": config.dimensions,
        "dtype": "<f4",
        "c_contiguous": True,
        "embedding_model": config.model_id,
        "embedding_matrix_sha256": sha256_file(matrix_path),
        "embedding_ledger_sha256": sha256_file(ledger_path),
        "expected_batches": total_batches,
        "embedding_request_count": len(all_ledger_rows),
        "embedding_retry_count": max(0, len(all_ledger_rows) - total_batches),
        "embedding_api_latency_ms": sum(float(row.get("latency_ms", 0) or 0) for row in all_ledger_rows),
        "returned_model_ids": sorted({str(row["response_model_id"]) for row in all_ledger_rows if row.get("response_model_id")}),
        "organization_ids_where_available": sorted({str(row["organization_id"]) for row in all_ledger_rows if row.get("organization_id")}),
        "project_ids_where_available": sorted({str(row["project_id"]) for row in all_ledger_rows if row.get("project_id")}),
        "total_embedding_tokens": total_tokens,
        "corpus_embedding_cost_usd": total_tokens / 1_000_000 * config.usd_per_million_input_tokens,
        "embedding_configuration": config.serializable(),
    }
    write_json(output_dir / "embedding_summary.json", result, exclusive=True)
    return result
