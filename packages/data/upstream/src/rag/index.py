"""Exact, exhaustive, deterministic flat cosine index."""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Sequence

import numpy as np

from src.rag.artifacts import sha256_file, write_json
from src.rag.config import EMBEDDING_CONFIG, INDEX_VERSION, SPEC_SHA256


@dataclass(frozen=True)
class SearchHit:
    record_id: str
    rank: int
    score: float
    ordinal: int

    def serializable(self) -> dict[str, Any]:
        return {"record_id": self.record_id, "rank": self.rank, "score": self.score, "ordinal": self.ordinal}


class ExactFlatCosineNumpyV1:
    def __init__(self, vectors: np.ndarray, record_ids: Sequence[str]):
        self.vectors = np.asarray(vectors, dtype="<f4", order="C")
        self.record_ids = tuple(str(value) for value in record_ids)
        if self.vectors.ndim != 2 or self.vectors.shape[0] != len(self.record_ids):
            raise RuntimeError("record/vector alignment failure")
        if len(set(self.record_ids)) != len(self.record_ids):
            raise RuntimeError("duplicate record ID in index")
        if not np.isfinite(self.vectors).all():
            raise RuntimeError("index contains nonfinite vectors")
        norms = np.linalg.norm(self.vectors, axis=1)
        if not np.allclose(norms, 1.0, atol=2e-5, rtol=0):
            raise RuntimeError("index vectors are not L2-normalized")

    @classmethod
    def load(cls, matrix_path: Path, record_ids_path: Path, expected: dict[str, str] | None = None):
        if expected:
            for path, key in ((matrix_path, "embedding_matrix_sha256"), (record_ids_path, "record_ids_sha256")):
                if sha256_file(path) != expected[key]:
                    raise RuntimeError(f"index artifact checksum mismatch: {path}")
        vectors = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
        record_ids = [line.strip() for line in record_ids_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return cls(vectors, record_ids)

    def search(self, query_vector: np.ndarray, k: int) -> tuple[list[SearchHit], float]:
        if not 1 <= k <= len(self.record_ids):
            raise ValueError(f"invalid K={k} for corpus size {len(self.record_ids)}")
        query = np.asarray(query_vector, dtype="<f4").reshape(-1)
        if query.shape != (self.vectors.shape[1],) or not np.isfinite(query).all():
            raise RuntimeError(f"invalid query vector shape/value: {query.shape}")
        norm = np.linalg.norm(query)
        if not np.isfinite(norm) or norm == 0:
            raise RuntimeError("zero/invalid query embedding")
        query = np.asarray(query / norm, dtype="<f4")
        started = perf_counter_ns()
        scores = np.asarray(self.vectors @ query, dtype=np.float32)
        # Full lexicographic ordering makes exact-score ties platform-stable.
        ids = np.asarray(self.record_ids, dtype=object)
        order = np.lexsort((ids, -scores))[:k]
        elapsed_ms = (perf_counter_ns() - started) / 1_000_000
        hits = [
            SearchHit(self.record_ids[int(index)], rank, float(scores[int(index)]), int(index))
            for rank, index in enumerate(order, start=1)
        ]
        return hits, elapsed_ms


def environment_manifest() -> dict[str, Any]:
    try:
        import openai
        openai_version = openai.__version__
    except ImportError:
        openai_version = "NOT_INSTALLED"
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "numpy": np.__version__,
        "openai_sdk": openai_version,
        "blas_configuration": str(np.__config__.CONFIG),
        "thread_environment": {
            key: __import__("os").environ.get(key) for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }


def write_index_manifest(index_dir: Path, record_ids_path: Path, embedding_summary: dict[str, Any], corpus: dict[str, Any]) -> dict[str, Any]:
    manifest = {
        "index_version": INDEX_VERSION,
        "frozen_spec_sha256": SPEC_SHA256,
        "vector_count": embedding_summary["vector_count"],
        "dimensions": embedding_summary["dimensions"],
        "dtype": embedding_summary["dtype"],
        "similarity": "cosine via normalized float32 inner product",
        "search": "exhaustive exact flat",
        "tie_break": "ascending record_id for exact float32 score ties",
        "embedding_matrix_sha256": embedding_summary["embedding_matrix_sha256"],
        "embedding_ledger_sha256": embedding_summary["embedding_ledger_sha256"],
        "embedding_configuration": EMBEDDING_CONFIG.serializable(),
        "embedding_summary": embedding_summary,
        "record_ids_sha256": sha256_file(record_ids_path),
        "index_size_bytes": (index_dir / "embeddings.npy").stat().st_size,
        "corpus": corpus,
        "environment": environment_manifest(),
        "graph_retrieval": False,
        "approximate_search": False,
    }
    write_json(index_dir / "index_manifest.json", manifest, exclusive=True)
    return manifest
