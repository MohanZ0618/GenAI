"""Deterministic, checksum-oriented artifact helpers for immutable RAG runs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from src.direct_llm.artifacts import load_jsonl, sha256_file, sha256_tree, write_csv, write_json, write_jsonl

__all__ = [
    "append_jsonl", "canonical_json", "load_jsonl", "sha256_bytes", "sha256_file",
    "sha256_tree", "write_checksum_manifest", "write_csv", "write_json", "write_jsonl",
]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_checksum_manifest(directory: Path, name: str = "artifact_checksums.json") -> Path:
    """Write a final inventory over every existing file in an immutable run directory."""
    path = directory / name
    if path.exists():
        raise FileExistsError(f"checksum manifest already exists: {path}")
    files = []
    for item in sorted(directory.rglob("*")):
        if item.is_file() and item != path:
            files.append({
                "path": item.relative_to(directory).as_posix(),
                "bytes": item.stat().st_size,
                "sha256": sha256_file(item),
            })
    write_json(path, {"algorithm": "SHA-256", "file_count": len(files), "files": files}, exclusive=True)
    return path
