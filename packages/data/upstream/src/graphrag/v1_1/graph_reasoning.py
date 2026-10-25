"""Deterministic, target-blind Graph v1.1 context assembly for the frozen RAG reasoner."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.rag.artifacts import canonical_json, sha256_bytes
from src.rag.corpus import CorpusDocument
from src.rag.leakage import assert_payload_label_blind, assert_route, forbidden_key_paths
from src.rag.reasoner import ReasoningCase, build_reasoning_case


SERIALIZER_VERSION = "graph_v1_1_reasoning_context_v1.0"
INFERENCE_OBJECT_KEYS = frozenset({
    "case_id",
    "primary_entity_type",
    "primary_entity_id",
    "selected_records",
    "selected_paths",
    "serializer_version",
})
RECORD_KEYS = frozenset({
    "record_id",
    "node_type",
    "source_table",
    "selected_rank",
    "minimum_graph_depth",
    "selection_class",
    "is_exact_anchor",
    "document_sha256",
    "canonical_record_text",
})
PATH_KEYS = frozenset({
    "path_rank",
    "graph_depth",
    "selection_class",
    "record_id_sequence",
    "node_type_sequence",
    "relation_direction_sequence",
    "provenance_record_id_sequence",
    "terminal_status",
    "stop_reason",
})


def _path_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    relations = list(row["relation_id_sequence"])
    directions = list(row["direction_sequence"])
    if len(relations) != len(directions):
        raise RuntimeError(f"path relation/direction mismatch: {row.get('path_id')}")
    return {
        "path_rank": int(row["selected_path_rank"]),
        "graph_depth": int(row["depth"]),
        "selection_class": str(row["selection_tier_name"]),
        "record_id_sequence": [str(value) for value in row["record_id_sequence"]],
        "node_type_sequence": [str(value) for value in row["node_type_sequence"]],
        "relation_direction_sequence": [
            f"{relation}:{direction}"
            for relation, direction in zip(relations, directions)
        ],
        "provenance_record_id_sequence": [
            str(item["provenance_record_id"]) for item in row["provenance"]
        ],
        "terminal_status": bool(row["terminal_status"]),
        "stop_reason": str(row["stop_reason"]),
    }


def build_inference_object(
    route: Mapping[str, str],
    selected_records: Sequence[Mapping[str, Any]],
    selected_paths: Sequence[Mapping[str, Any]],
    document_by_id: Mapping[str, CorpusDocument],
    graph_node_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Project frozen retrieval into the only object visible to the reasoner."""

    exact_route = {str(key): str(value) for key, value in route.items()}
    assert_route(exact_route)
    case_id = exact_route["case_id"]
    records = sorted(selected_records, key=lambda row: int(row["selected_record_rank"]))
    paths = sorted(selected_paths, key=lambda row: int(row["selected_path_rank"]))
    if not records:
        raise RuntimeError(f"resolved Graph inference case has no selected records: {case_id}")
    if [int(row["selected_record_rank"]) for row in records] != list(range(1, len(records) + 1)):
        raise RuntimeError(f"noncontiguous Graph selected-record ranks: {case_id}")
    if [int(row["selected_path_rank"]) for row in paths] != list(range(1, len(paths) + 1)):
        raise RuntimeError(f"noncontiguous Graph selected-path ranks: {case_id}")
    if any(str(row["case_id"]) != case_id for row in [*records, *paths]):
        raise RuntimeError(f"cross-case Graph context row: {case_id}")

    projected_records = []
    for row in records:
        record_id = str(row["record_id"])
        document = document_by_id.get(record_id)
        node = graph_node_by_id.get(record_id)
        if document is None or node is None:
            raise RuntimeError(f"selected Graph record absent from frozen corpus/graph: {record_id}")
        if (
            str(node["document_sha256"]) != document.text_sha256
            or str(node["source_table"]) != document.source_table
            or str(node["node_type"]) != str(row["node_type"])
        ):
            raise RuntimeError(f"selected Graph record lineage mismatch: {record_id}")
        projected_records.append({
            "record_id": record_id,
            "node_type": str(row["node_type"]),
            "source_table": document.source_table,
            "selected_rank": int(row["selected_record_rank"]),
            "minimum_graph_depth": int(row["minimum_reachable_depth"]),
            "selection_class": str(row["selection_tier_name"]),
            "is_exact_anchor": int(row["selection_tier"]) == 0,
            "document_sha256": document.text_sha256,
            "canonical_record_text": document.text,
        })
    projected_paths = [_path_projection(row) for row in paths]
    selected_ids = {row["record_id"] for row in projected_records}
    if any(not set(path["record_id_sequence"]) <= selected_ids for path in projected_paths):
        raise RuntimeError(f"selected path refers outside selected Graph record set: {case_id}")

    result = {
        "case_id": case_id,
        "primary_entity_type": exact_route["primary_entity_type"],
        "primary_entity_id": exact_route["primary_entity_id"],
        "selected_records": projected_records,
        "selected_paths": projected_paths,
        "serializer_version": SERIALIZER_VERSION,
    }
    validate_inference_object(result)
    return result


def validate_inference_object(value: Mapping[str, Any]) -> None:
    if set(value) != INFERENCE_OBJECT_KEYS:
        raise RuntimeError(f"Graph inference object key drift: {sorted(value)}")
    records = value.get("selected_records")
    paths = value.get("selected_paths")
    if not isinstance(records, list) or not records or not isinstance(paths, list):
        raise RuntimeError("Graph inference object records/paths malformed")
    if any(set(row) != RECORD_KEYS for row in records):
        raise RuntimeError("Graph inference record projection key drift")
    if any(set(row) != PATH_KEYS for row in paths):
        raise RuntimeError("Graph inference path projection key drift")
    if forbidden_key_paths(value):
        raise RuntimeError("target/evaluation field entered Graph inference object")
    assert_payload_label_blind(value, name=f"graph_inference_object:{value.get('case_id')}")


def inference_object_sha256(value: Mapping[str, Any]) -> str:
    validate_inference_object(value)
    return sha256_bytes(canonical_json(value))


def _path_summary_block(paths: Sequence[Mapping[str, Any]]) -> str:
    lines = ["GRAPH_PATH_SUMMARIES_BEGIN", f"GRAPH_PATH_COUNT: {len(paths)}"]
    for path in paths:
        # Canonical JSON is unambiguous and preserves the explicit frozen order.
        lines.append("GRAPH_PATH: " + canonical_json(path))
    lines.append("GRAPH_PATH_SUMMARIES_END")
    return "\n".join(lines)


def build_reasoning_case_from_inference_object(value: Mapping[str, Any]) -> ReasoningCase:
    """Serialize graph records into the unchanged Standard RAG request envelope.

    Graph structure is appended to the first ranked record as one explicit,
    deterministic metadata block.  This keeps record citation semantics and the
    frozen Standard RAG parser/request-hash machinery unchanged while ensuring
    the model receives graph-selected context rather than IDs alone.
    """

    validate_inference_object(value)
    route = {
        "case_id": str(value["case_id"]),
        "primary_entity_type": str(value["primary_entity_type"]),
        "primary_entity_id": str(value["primary_entity_id"]),
    }
    records = list(value["selected_records"])
    texts = [str(row["canonical_record_text"]) for row in records]
    texts[0] = texts[0] + "\n" + _path_summary_block(value["selected_paths"])
    case = build_reasoning_case(
        route,
        [str(row["record_id"]) for row in records],
        texts,
    )
    assert_payload_label_blind(case.payload, name=f"graph_reasoning_payload:{route['case_id']}")
    return case


def deterministic_preflight_case_ids(case_ids: Iterable[str], count: int = 16) -> list[str]:
    values = sorted({str(value) for value in case_ids})
    if len(values) < count:
        raise RuntimeError("insufficient cases for deterministic preflight")
    return sorted(
        values,
        key=lambda value: (hashlib.sha256(value.encode("utf-8")).hexdigest(), value),
    )[:count]
