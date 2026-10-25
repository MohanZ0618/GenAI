"""Small immutable graph types used by build and retrieval."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class GraphNode:
    record_id: str
    node_type: str
    source_table: str
    primary_key: dict[str, str]
    available_at: str
    temporal_eligible: bool
    document_ordinal: int
    document_sha256: str
    identifier_values: dict[str, str]
    graph_use_values: dict[str, str]

    def artifact_row(self) -> dict[str, Any]:
        return {
            "available_at": self.available_at,
            "document_ordinal": self.document_ordinal,
            "document_sha256": self.document_sha256,
            "graph_use_values": self.graph_use_values,
            "identifier_values": self.identifier_values,
            "node_type": self.node_type,
            "primary_key": self.primary_key,
            "record_id": self.record_id,
            "source_table": self.source_table,
            "temporal_eligible": self.temporal_eligible,
        }


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    source_record_id: str
    source_node_type: str
    relation_type: str
    target_record_id: str
    target_node_type: str
    confidence_tier: str
    provenance_record_id: str
    provenance_record_type: str
    provenance_fields: dict[str, str]
    temporal_eligible: bool
    effective_available_at: str
    registry_relation_id: str
    traversable: bool
    reverse_traversal: bool

    def artifact_row(self) -> dict[str, Any]:
        return {
            "confidence_tier": self.confidence_tier,
            "edge_id": self.edge_id,
            "effective_available_at": self.effective_available_at,
            "provenance_fields": self.provenance_fields,
            "provenance_record_id": self.provenance_record_id,
            "provenance_record_type": self.provenance_record_type,
            "registry_relation_id": self.registry_relation_id,
            "relation_type": self.relation_type,
            "reverse_traversal": self.reverse_traversal,
            "source_node_type": self.source_node_type,
            "source_record_id": self.source_record_id,
            "target_node_type": self.target_node_type,
            "target_record_id": self.target_record_id,
            "temporal_eligible": self.temporal_eligible,
            "traversable": self.traversable,
        }


class GraphSnapshot:
    """In-memory deterministic adjacency over persisted canonical nodes and edges."""

    def __init__(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> None:
        self.nodes = {node.record_id: node for node in nodes}
        self.edges = tuple(sorted(edges, key=edge_sort_key))
        self.forward: dict[tuple[str, str], tuple[GraphEdge, ...]] = {}
        self.reverse: dict[tuple[str, str], tuple[GraphEdge, ...]] = {}
        fwd: dict[tuple[str, str], list[GraphEdge]] = defaultdict(list)
        rev: dict[tuple[str, str], list[GraphEdge]] = defaultdict(list)
        for edge in self.edges:
            fwd[(edge.source_record_id, edge.relation_type)].append(edge)
            rev[(edge.target_record_id, edge.relation_type)].append(edge)
        self.forward = {key: tuple(sorted(value, key=edge_sort_key)) for key, value in fwd.items()}
        self.reverse = {key: tuple(sorted(value, key=edge_sort_key)) for key, value in rev.items()}

    def traverse(self, record_id: str, relation_type: str, direction: str) -> tuple[tuple[str, GraphEdge], ...]:
        if direction == "forward":
            edges = self.forward.get((record_id, relation_type), ())
            return tuple((edge.target_record_id, edge) for edge in edges if edge.traversable)
        if direction == "reverse":
            edges = self.reverse.get((record_id, relation_type), ())
            return tuple((edge.source_record_id, edge) for edge in edges if edge.reverse_traversal)
        raise ValueError(f"invalid traversal direction: {direction}")


def edge_sort_key(edge: GraphEdge) -> tuple[str, str, str, str, str]:
    return (
        edge.source_record_id,
        edge.relation_type,
        edge.target_record_id,
        edge.provenance_record_id,
        edge.edge_id,
    )
