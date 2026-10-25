"""Exact frozen-motif traversal; intentionally no generic graph search API."""

from __future__ import annotations

import hashlib
from typing import Any

from .graph_types import GraphEdge, GraphSnapshot
from .registry_loader import FrozenRegistries


class TraversalRejected(RuntimeError):
    pass


def _path_id(case_id: str, anchor: str, motif: str, records: list[str], edges: list[GraphEdge]) -> str:
    raw = "\t".join([case_id, anchor, motif, *records, *(edge.edge_id for edge in edges)]).encode("utf-8")
    return "PATH_" + hashlib.sha256(raw).hexdigest()[:24]


class FrozenMotifEngine:
    def __init__(self, snapshot: GraphSnapshot, registries: FrozenRegistries) -> None:
        self.snapshot = snapshot
        self.registries = registries
        self.relations = {row["relation_type"]: row for row in registries.relation["frozen_relations"]}
        self.motifs = tuple(registries.motifs["frozen_motifs"])

    def _steps(self, motif: dict[str, Any]) -> list[tuple[tuple[str, ...], str]]:
        result = []
        for raw in motif["edge_sequence"]:
            relation_expression, direction = raw.rsplit(":", 1)
            if "{" in relation_expression:
                relation_types = tuple(motif["resolved_relation_types"])
            else:
                relation_types = (relation_expression,)
            if direction not in {"forward", "reverse"}:
                raise TraversalRejected(f"invalid frozen direction: {raw}")
            for relation_type in relation_types:
                if relation_type not in self.relations:
                    raise TraversalRejected(f"RELATION_NOT_EXECUTABLE: {relation_type}")
            result.append((relation_types, direction))
        return result

    def execute(self, case_id: str, anchor_record_id: str) -> tuple[list[dict[str, Any]], list[str], list[str], list[dict[str, Any]]]:
        node = self.snapshot.nodes[anchor_record_id]
        candidate_motifs = [motif for motif in self.motifs if node.node_type in motif["permitted_anchor_types"]]
        paths: list[dict[str, Any]] = []
        hub_events: list[dict[str, Any]] = []
        if node.node_type in {"VENDOR", "EMPLOYEE"}:
            incident = [edge for edge in self.snapshot.edges if edge.source_record_id == anchor_record_id or edge.target_record_id == anchor_record_id]
            hub_events.append({
                "anchor_record_id": anchor_record_id,
                "hub_expansion_blocked": True,
                "incident_frozen_edge_count": len(incident),
                "reason": f"{node.node_type}_HUB_TRAVERSAL_NOT_PERMITTED",
            })
        for motif in candidate_motifs:
            partial: list[tuple[list[str], list[GraphEdge]]] = [([anchor_record_id], [])]
            for relation_types, direction in self._steps(motif):
                expanded: list[tuple[list[str], list[GraphEdge]]] = []
                for records, edges in partial:
                    current = records[-1]
                    for relation_type in relation_types:
                        definition = self.relations[relation_type]
                        permitted = definition["traversable"] if direction == "forward" else definition["reverse_traversal"]
                        if not permitted:
                            hub_events.append({
                                "anchor_record_id": anchor_record_id,
                                "hub_expansion_blocked": True,
                                "reason": "HUB_TRAVERSAL_NOT_PERMITTED",
                                "relation_type": relation_type,
                                "direction": direction,
                            })
                            continue
                        for next_id, edge in self.snapshot.traverse(current, relation_type, direction):
                            if not edge.temporal_eligible or not self.snapshot.nodes[next_id].temporal_eligible:
                                continue
                            expanded.append(([*records, next_id], [*edges, edge]))
                partial = sorted(expanded, key=lambda item: (item[0], [edge.edge_id for edge in item[1]]))
            for records, edges in partial:
                relation_sequence = [edge.relation_type for edge in edges]
                paths.append({
                    "anchor_record_id": anchor_record_id,
                    "case_id": case_id,
                    "complete_motif": True,
                    "edges": [edge.artifact_row() for edge in edges],
                    "hub_blocked": False,
                    "motif_id": motif["motif_id"],
                    "node_sequence": records,
                    "path_id": _path_id(case_id, anchor_record_id, motif["motif_id"], records, edges),
                    "path_length": len(edges),
                    "records": records,
                    "relation_sequence": relation_sequence,
                    "temporal_valid": True,
                    "traversal_priority": motif["traversal_priority"],
                })
        paths.sort(key=lambda row: (row["motif_id"], row["node_sequence"], row["path_id"]))
        ids = [motif["motif_id"] for motif in candidate_motifs]
        return paths, ids, ids, sorted(hub_events, key=lambda row: tuple(str(row.get(k, "")) for k in sorted(row)))

    def reject_relation(self, relation_type: str) -> None:
        if relation_type not in self.relations:
            raise TraversalRejected(f"RELATION_NOT_EXECUTABLE: {relation_type}")
