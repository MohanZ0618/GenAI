"""Normalize and deduplicate exact causal lineage edges."""

from __future__ import annotations

from typing import Any


CAUSAL_EDGE_FIELDS = [
    "source_entity_type", "source_entity_id", "relationship", "target_entity_type", "target_entity_id"
]


def build_causal_graph(edges: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, ...]] = set()
    result: list[dict[str, str]] = []
    for edge in edges:
        normalized = {field: str(edge[field]) for field in CAUSAL_EDGE_FIELDS}
        identity = tuple(normalized[field] for field in CAUSAL_EDGE_FIELDS)
        if identity not in seen:
            seen.add(identity)
            result.append(normalized)
    return result

