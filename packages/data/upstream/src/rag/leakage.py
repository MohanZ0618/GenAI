"""Runtime source, path, payload, case-ID, and secret isolation controls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.rag.config import FORBIDDEN_ARTIFACT_NAMES, FORBIDDEN_KEYS, ROUTE_KEYS
from src.schema import TABLE_SCHEMAS


@dataclass
class OpenedPathAudit:
    purpose: str
    paths: list[str] = field(default_factory=list)

    def record(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved.name in FORBIDDEN_ARTIFACT_NAMES and self.purpose not in {
            "route_preparation", "offline_evaluation", "oracle_diagnostic"
        }:
            raise RuntimeError(f"forbidden primary RAG artifact opened: {resolved}")
        if "raw_clean" in resolved.parts:
            raise RuntimeError(f"pre-mutation source is prohibited: {resolved}")
        self.paths.append(str(resolved))

    def serializable(self) -> dict[str, Any]:
        forbidden = [path for path in self.paths if Path(path).name in FORBIDDEN_ARTIFACT_NAMES]
        allowed_boundary = self.purpose in {"route_preparation", "offline_evaluation", "oracle_diagnostic"}
        return {
            "purpose": self.purpose,
            "opened_paths": self.paths,
            "forbidden_named_paths": forbidden,
            "status": "PASS" if not forbidden or allowed_boundary else "FAIL",
        }


def assert_source_registry(table: str, observed_fields: list[str] | None) -> None:
    expected = TABLE_SCHEMAS[table]
    if observed_fields != expected:
        raise RuntimeError(
            f"field registry mismatch for {table}: expected={expected!r}, observed={observed_fields!r}"
        )


def forbidden_key_paths(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_KEYS:
                findings.append(child_path)
            findings.extend(forbidden_key_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(forbidden_key_paths(child, f"{path}[{index}]"))
    return findings


_SERIALIZED_FORBIDDEN = re.compile(
    r"(?im)^(?:" + "|".join(re.escape(key.upper()) for key in sorted(FORBIDDEN_KEYS)) + r")\s*:"
)


def assert_payload_label_blind(value: Any, *, name: str) -> None:
    findings = forbidden_key_paths(value)
    if isinstance(value, str) and _SERIALIZED_FORBIDDEN.search(value):
        findings.append(f"{name}:serialized_forbidden_field")
    if findings:
        raise RuntimeError(f"forbidden target/evaluation fields in {name}: {findings[:20]}")


def assert_route(route: dict[str, str]) -> None:
    if set(route) != ROUTE_KEYS:
        raise RuntimeError(f"route keys are not exactly whitelisted: {sorted(route)}")
    assert_payload_label_blind(route, name="route")


def assert_case_id_not_embedded(case_id: str, query: str) -> None:
    if case_id and case_id in query:
        raise RuntimeError(f"case_id leaked into embedded query: {case_id}")


def forbidden_import_hits(paths: Iterable[Path]) -> list[dict[str, str]]:
    patterns = {
        "graph_library": re.compile(r"(?m)^\s*(?:from|import)\s+(?:neo4j|networkx|igraph|dgl|torch_geometric)\b"),
        "framework": re.compile(r"(?m)^\s*(?:from|import)\s+(?:langchain|llama_index)\b"),
        "graph_query": re.compile(r"\b(?:MATCH\s*\(|CYPHER|shortest_path|shortestPath)\b", re.I),
    }
    hits: list[dict[str, str]] = []
    for path in paths:
        if not path.is_file() or path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8")
        for category, pattern in patterns.items():
            if pattern.search(text):
                hits.append({"file": str(path), "category": category})
    return hits


def secret_audit(paths: Iterable[Path]) -> dict[str, Any]:
    key = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
    findings: list[str] = []
    inspected: list[str] = []
    for path in paths:
        if not path.is_file() or path.suffix in {".pyc", ".npy", ".npz"}:
            continue
        inspected.append(str(path))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if key.search(text):
            findings.append(str(path))
    return {"status": "PASS" if not findings else "FAIL", "findings": findings, "inspected": inspected}
