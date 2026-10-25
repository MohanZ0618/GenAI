"""Registry-driven graph snapshot construction with fail-closed integrity checks."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from src.rag.artifacts import sha256_file, write_json, write_jsonl
from src.rag.corpus import CorpusDocument, FrozenCorpus

from .config import DECISION_CUTOFF
from .graph_types import GraphEdge, GraphNode, GraphSnapshot, edge_sort_key
from .registry_loader import FrozenRegistries


@dataclass(frozen=True)
class GraphBuild:
    snapshot: GraphSnapshot
    integrity: dict[str, Any]


def _nearest_rank(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _degree_stats(values: Iterable[int]) -> dict[str, float | int]:
    data = list(values)
    return {
        "count": len(data),
        "maximum": max(data, default=0),
        "mean": statistics.fmean(data) if data else 0.0,
        "median": statistics.median(data) if data else 0.0,
        "p95_nearest_rank": _nearest_rank(data, 0.95),
        "p99_nearest_rank": _nearest_rank(data, 0.99),
    }


def _node_availability(document: CorpusDocument, corpus: FrozenCorpus) -> str:
    if document.source_table == "po_lines":
        parents = [row for row in corpus.eligible_rows["purchase_orders"] if row["po_id"] == document.row["po_id"]]
        if len(parents) != 1:
            raise RuntimeError(f"PO_LINE parent availability resolution failed: {document.record_id}")
        return parents[0]["po_date"]
    if document.source_table == "invoice_lines":
        parents = [row for row in corpus.eligible_rows["invoices"] if row["invoice_id"] == document.row["invoice_id"]]
        if len(parents) != 1:
            raise RuntimeError(f"INVOICE_LINE parent availability resolution failed: {document.record_id}")
        return parents[0]["created_at"]
    if document.source_table == "employees":
        return DECISION_CUTOFF
    return document.available_at


def _date_eligible(value: str) -> bool:
    return bool(value) and value[:10] <= DECISION_CUTOFF


def build_nodes(corpus: FrozenCorpus, registries: FrozenRegistries) -> list[GraphNode]:
    definitions = {row["node_type"]: row for row in registries.node["node_types"]}
    frozen_types = set(definitions)
    observed_types = {document.record_type for document in corpus.documents}
    if observed_types != frozen_types:
        raise RuntimeError(f"PHASE 6A BLOCKED: corpus/frozen node types disagree: {sorted(observed_types ^ frozen_types)}")
    nodes: list[GraphNode] = []
    seen: set[str] = set()
    for document in corpus.documents:
        definition = definitions[document.record_type]
        if document.record_id in seen:
            raise RuntimeError(f"duplicate canonical graph node: {document.record_id}")
        seen.add(document.record_id)
        primary = {field: document.row.get(field, "") for field in definition["canonical_primary_key"]}
        if not all(primary.values()):
            raise RuntimeError(f"missing graph primary key: {document.record_id}")
        available_at = _node_availability(document, corpus)
        eligible = _date_eligible(available_at)
        nodes.append(GraphNode(
            record_id=document.record_id,
            node_type=document.record_type,
            source_table=document.source_table,
            primary_key=primary,
            available_at=available_at,
            temporal_eligible=eligible,
            document_ordinal=document.ordinal,
            document_sha256=document.text_sha256,
            identifier_values={field: document.row.get(field, "") for field in definition["important_identifier_fields"]},
            graph_use_values={field: document.row.get(field, "") for field in definition["permitted_graph_use_fields"]},
        ))
    nodes.sort(key=lambda node: node.record_id)
    if len(nodes) != registries.node["total_record_count"] or any(not node.temporal_eligible for node in nodes):
        raise RuntimeError("PHASE 6A BLOCKED: node count or cutoff eligibility failed")
    return nodes


def _edge_id(source: str, relation: str, target: str, provenance: str) -> str:
    raw = "\t".join((source, relation, target, provenance)).encode("utf-8")
    return "EDGE_" + hashlib.sha256(raw).hexdigest()[:24]


def _make_edge(
    relation: dict[str, Any], source: CorpusDocument, target: CorpusDocument,
    provenance: CorpusDocument, node_by_id: dict[str, GraphNode],
) -> GraphEdge:
    participants = (node_by_id[source.record_id], node_by_id[target.record_id], node_by_id[provenance.record_id])
    eligible = all(node.temporal_eligible for node in participants)
    effective = max(node.available_at for node in participants)
    fields = sorted(set(relation["source_fields"]) | set(relation["target_fields"]))
    provenance_fields = {field: provenance.row.get(field, "") for field in fields if field in provenance.row}
    return GraphEdge(
        edge_id=_edge_id(source.record_id, relation["relation_type"], target.record_id, provenance.record_id),
        source_record_id=source.record_id,
        source_node_type=source.record_type,
        relation_type=relation["relation_type"],
        target_record_id=target.record_id,
        target_node_type=target.record_type,
        confidence_tier=relation["confidence_tier"],
        provenance_record_id=provenance.record_id,
        provenance_record_type=provenance.record_type,
        provenance_fields=provenance_fields,
        temporal_eligible=eligible and _date_eligible(effective),
        effective_available_at=effective,
        registry_relation_id=relation["relation_type"],
        traversable=bool(relation["traversable"]),
        reverse_traversal=bool(relation["reverse_traversal"]),
    )


def build_edges(
    corpus: FrozenCorpus, nodes: list[GraphNode], registries: FrozenRegistries,
) -> tuple[list[GraphEdge], dict[str, Any]]:
    docs = corpus.documents
    by_type: dict[str, list[CorpusDocument]] = defaultdict(list)
    lookup: dict[tuple[str, str, str], list[CorpusDocument]] = defaultdict(list)
    for document in docs:
        by_type[document.record_type].append(document)
        for field, value in document.row.items():
            if value:
                lookup[(document.record_type, field, value)].append(document)
    node_by_id = {node.record_id: node for node in nodes}
    edges: list[GraphEdge] = []
    audit: dict[str, Any] = {}
    for relation in registries.relation["frozen_relations"]:
        relation_type = relation["relation_type"]
        resolved = 0
        populated = 0
        unresolved: list[dict[str, Any]] = []
        candidates: list[tuple[CorpusDocument, CorpusDocument, CorpusDocument]] = []

        if relation_type == "PAYMENT_ALLOCATED_TO_INVOICE":
            for provenance in by_type["PAYMENT_ALLOCATION"]:
                values = (provenance.row.get("payment_id", ""), provenance.row.get("invoice_id", ""))
                if not all(values):
                    continue
                populated += 1
                sources = lookup[("PAYMENT", "payment_id", values[0])]
                targets = lookup[("INVOICE", "invoice_id", values[1])]
                if len(sources) == len(targets) == 1:
                    candidates.append((sources[0], targets[0], provenance))
                    resolved += 1
                else:
                    unresolved.append({"provenance_record_id": provenance.record_id, "values": list(values)})
        else:
            constraints = relation.get("constraints", {})
            type_field = None
            permitted: set[str] | None = None
            if "permitted_transaction_types" in constraints:
                type_field, permitted = "transaction_type", set(constraints["permitted_transaction_types"])
            if "permitted_entity_types" in constraints:
                type_field, permitted = "entity_type", set(constraints["permitted_entity_types"])
            for source in by_type[relation["source_node_type"]]:
                if type_field and source.row.get(type_field, "") not in (permitted or set()):
                    continue
                source_values = tuple(source.row.get(field, "") for field in relation["source_fields"] if field != type_field)
                target_fields = tuple(relation["target_fields"])
                if not source_values or not all(source_values):
                    continue
                populated += 1
                if len(source_values) != len(target_fields):
                    raise RuntimeError(f"unsupported frozen composite join: {relation_type}")
                if len(source_values) == 1:
                    matches = lookup[(relation["target_node_type"], target_fields[0], source_values[0])]
                else:
                    matches = [
                        target for target in by_type[relation["target_node_type"]]
                        if all(target.row.get(field, "") == value for field, value in zip(target_fields, source_values))
                    ]
                if len(matches) == 1:
                    candidates.append((source, matches[0], source))
                    resolved += 1
                else:
                    unresolved.append({"source_record_id": source.record_id, "values": list(source_values), "match_count": len(matches)})

        for source, target, provenance in candidates:
            edges.append(_make_edge(relation, source, target, provenance, node_by_id))
        audit[relation_type] = {
            "populated_reference_count": populated,
            "resolved_edge_count": resolved,
            "unresolved_exact_reference_count": len(unresolved),
            "unresolved_examples": unresolved[:10],
        }

    edges.sort(key=edge_sort_key)
    return edges, audit


def validate_graph(nodes: list[GraphNode], edges: list[GraphEdge], relation_audit: dict[str, Any], registries: FrozenRegistries) -> dict[str, Any]:
    frozen = {row["relation_type"]: row for row in registries.relation["frozen_relations"]}
    excluded = {row["relation_type"] for row in registries.relation["excluded_relations"]}
    node_by_id = {node.record_id: node for node in nodes}
    edge_keys = [(edge.source_record_id, edge.relation_type, edge.target_record_id, edge.provenance_record_id) for edge in edges]
    duplicate_count = len(edge_keys) - len(set(edge_keys))
    self_count = sum(edge.source_record_id == edge.target_record_id for edge in edges)
    prohibited = [edge.edge_id for edge in edges if edge.relation_type not in frozen]
    accidentally_excluded = [edge.edge_id for edge in edges if edge.relation_type in excluded]
    orphan = [edge.edge_id for edge in edges if edge.source_record_id not in node_by_id or edge.target_record_id not in node_by_id or edge.provenance_record_id not in node_by_id]
    post_cutoff = [edge.edge_id for edge in edges if not edge.temporal_eligible]
    type_mismatch = [
        edge.edge_id for edge in edges
        if edge.source_node_type != frozen[edge.relation_type]["source_node_type"]
        or edge.target_node_type != frozen[edge.relation_type]["target_node_type"]
        or edge.provenance_record_type != frozen[edge.relation_type]["provenance_record_type"]
    ]
    counts = Counter(edge.relation_type for edge in edges)
    node_counts = Counter(node.node_type for node in nodes)
    out_counts = Counter(edge.source_record_id for edge in edges)
    in_counts = Counter(edge.target_record_id for edge in edges)
    relation_rows: dict[str, Any] = {}
    for relation_type, definition in frozen.items():
        selected = [edge for edge in edges if edge.relation_type == relation_type]
        source_degree = Counter(edge.source_record_id for edge in selected)
        target_degree = Counter(edge.target_record_id for edge in selected)
        relation_rows[relation_type] = {
            **relation_audit[relation_type],
            "edge_count": len(selected),
            "source_node_type": definition["source_node_type"],
            "target_node_type": definition["target_node_type"],
            "source_out_degree": _degree_stats(source_degree.values()),
            "target_in_degree": _degree_stats(target_degree.values()),
            "traversable": definition["traversable"],
            "reverse_traversal": definition["reverse_traversal"],
        }
    blockers = {
        "duplicate_edge_count": duplicate_count,
        "self_edge_count": self_count,
        "orphan_relation_count": len(orphan),
        "post_cutoff_edge_count": len(post_cutoff),
        "prohibited_relation_count": len(prohibited),
        "excluded_relation_count_accidentally_materialized": len(accidentally_excluded),
        "type_or_provenance_mismatch_count": len(type_mismatch),
    }
    if any(blockers.values()):
        raise RuntimeError(f"PHASE 6A GRAPH CONSTRUCTION FAILED: {blockers}")
    if set(counts) != set(frozen):
        missing = sorted(set(frozen) - set(counts))
        raise RuntimeError(f"PHASE 6A GRAPH CONSTRUCTION FAILED: frozen relations with zero materialized edges: {missing}")
    return {
        "status": "PASS",
        "node_count": len(nodes),
        "node_count_by_type": dict(sorted(node_counts.items())),
        "edge_count": len(edges),
        "edge_count_by_relation": dict(sorted(counts.items())),
        "eligible_edge_count": sum(edge.temporal_eligible for edge in edges),
        "excluded_post_cutoff_source_edges": 0,
        "excluded_post_cutoff_target_edges": 0,
        "excluded_provenance_time_violations": 0,
        "global_out_degree": _degree_stats(out_counts.values()),
        "global_in_degree": _degree_stats(in_counts.values()),
        "relations": relation_rows,
        **blockers,
    }


def construct_graph(corpus: FrozenCorpus, registries: FrozenRegistries) -> GraphBuild:
    nodes = build_nodes(corpus, registries)
    edges, relation_audit = build_edges(corpus, nodes, registries)
    integrity = validate_graph(nodes, edges, relation_audit, registries)
    return GraphBuild(GraphSnapshot(nodes, edges), integrity)


def persist_graph(build: GraphBuild, graph_dir: Path, manifest: dict[str, Any]) -> dict[str, str]:
    graph_dir.mkdir(parents=True, exist_ok=False)
    nodes_path = graph_dir / "nodes.jsonl"
    edges_path = graph_dir / "edges.jsonl"
    integrity_path = graph_dir / "graph_integrity.json"
    write_jsonl(nodes_path, (node.artifact_row() for node in sorted(build.snapshot.nodes.values(), key=lambda value: value.record_id)), exclusive=True)
    write_jsonl(edges_path, (edge.artifact_row() for edge in build.snapshot.edges), exclusive=True)
    write_json(integrity_path, build.integrity, exclusive=True)
    complete_manifest = {
        **manifest,
        "node_count": len(build.snapshot.nodes),
        "node_count_by_type": build.integrity["node_count_by_type"],
        "edge_count": len(build.snapshot.edges),
        "edge_count_by_relation": build.integrity["edge_count_by_relation"],
        "nodes_sha256": sha256_file(nodes_path),
        "edges_sha256": sha256_file(edges_path),
        "graph_nodes_sha256": sha256_file(nodes_path),
        "graph_edges_sha256": sha256_file(edges_path),
        "integrity_sha256": sha256_file(integrity_path),
        "serialization": {
            "encoding": "UTF-8",
            "json_key_order": "lexicographic via sort_keys=True",
            "json_separators": [",", ":"],
            "ensure_ascii": False,
            "newline": "LF; exactly one newline per record",
            "node_order": ["record_id"],
            "edge_order": ["source_record_id", "relation_type", "target_record_id", "provenance_record_id", "edge_id"],
        },
        "deterministic_serialization": True,
        "payment_bank_enabled": False,
        "synthetic_gl_journal_enabled": False,
        "tier_b_enabled": False,
        "semantic_fallback_enabled": False,
        "implementation_commit": "NOT_AVAILABLE_WORKSPACE_HAS_NO_GIT_METADATA",
        "python_version": platform.python_version(),
        "relevant_dependency_versions": {},
        "api_calls_made": False,
        "llm_calls_made": False,
        "new_embeddings_created": False,
        "heldout_gold_opened": False,
        "status": "PASS",
    }
    manifest_path = graph_dir / "graph_build_manifest.json"
    write_json(manifest_path, complete_manifest, exclusive=True)
    return {
        "nodes": sha256_file(nodes_path),
        "edges": sha256_file(edges_path),
        "integrity": sha256_file(integrity_path),
        "manifest": sha256_file(manifest_path),
    }


def load_persisted_graph(graph_dir: Path) -> GraphSnapshot:
    """Load the inspectable JSONL snapshot without consulting source tables."""
    manifest = json.loads((graph_dir / "graph_build_manifest.json").read_text(encoding="utf-8"))
    nodes: list[GraphNode] = []
    with (graph_dir / "nodes.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            value = json.loads(line)
            nodes.append(GraphNode(
                record_id=str(value["record_id"]),
                node_type=str(value["node_type"]),
                source_table=str(value["source_table"]),
                primary_key={str(k): str(v) for k, v in value["primary_key"].items()},
                available_at=str(value["available_at"]),
                temporal_eligible=bool(value["temporal_eligible"]),
                document_ordinal=int(value["document_ordinal"]),
                document_sha256=str(value["document_sha256"]),
                identifier_values={str(k): str(v) for k, v in value["identifier_values"].items()},
                graph_use_values={str(k): str(v) for k, v in value["graph_use_values"].items()},
            ))
    edges: list[GraphEdge] = []
    with (graph_dir / "edges.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            value = json.loads(line)
            edges.append(GraphEdge(
                edge_id=str(value["edge_id"]),
                source_record_id=str(value["source_record_id"]),
                source_node_type=str(value["source_node_type"]),
                relation_type=str(value["relation_type"]),
                target_record_id=str(value["target_record_id"]),
                target_node_type=str(value["target_node_type"]),
                confidence_tier=str(value["confidence_tier"]),
                provenance_record_id=str(value["provenance_record_id"]),
                provenance_record_type=str(value["provenance_record_type"]),
                provenance_fields={str(k): str(v) for k, v in value["provenance_fields"].items()},
                temporal_eligible=bool(value["temporal_eligible"]),
                effective_available_at=str(value["effective_available_at"]),
                registry_relation_id=str(value["registry_relation_id"]),
                traversable=bool(value["traversable"]),
                reverse_traversal=bool(value["reverse_traversal"]),
            ))
    snapshot = GraphSnapshot(nodes, edges)
    if len(snapshot.nodes) != int(manifest["node_count"]) or len(snapshot.edges) != int(manifest["edge_count"]):
        raise RuntimeError("persisted graph count verification failed")
    return snapshot
