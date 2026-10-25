"""Registry-driven deterministic candidate traversal for frozen Graph v1.1."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Iterable, Sequence

from .typed_grammar_loader import EXPECTED_TOPOLOGY_PATH_SET_SHA256, FrozenGrammarBundle


ANCHOR_DOMAINS: dict[str, tuple[str, str, str]] = {
    "invoice": ("INVOICE", "invoice_id", "EXACT_SINGLE"),
    "payment": ("PAYMENT", "payment_id", "EXACT_SINGLE"),
    "bank_transaction": ("BANK_TRANSACTION", "bank_transaction_id", "EXACT_SINGLE"),
    # journal_id is a grouping attribute on GL_ENTRY; GL_JOURNAL is never a node.
    "gl_journal": ("GL_ENTRY", "journal_id", "EXACT_MULTI"),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _hash_parts(*parts: str) -> str:
    return hashlib.sha256("\t".join(parts).encode("utf-8")).hexdigest()


def candidate_path_id(
    case_id: str,
    anchor_id: str,
    transition_ids: Sequence[str],
    record_ids: Sequence[str],
    edge_ids: Sequence[str],
) -> str:
    # Identity is the exact frozen topology identity from Graph v1.1.
    return "GRAMMAR_DIAG_PATH_" + _hash_parts(
        case_id, anchor_id, *transition_ids, *record_ids, *edge_ids
    )[:24]


def rejection_id(*parts: str) -> str:
    return "GRAPH_V1_1_REJECT_" + _hash_parts(*parts)[:24]


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        edge["target_record_id"],
        edge["source_record_id"],
        edge.get("provenance_record_id", ""),
        edge.get("edge_id", ""),
    )


class FrozenGraph:
    """Exact persisted graph with relation/direction-specific indexes only."""

    def __init__(self, nodes: Iterable[dict[str, Any]], edges: Iterable[dict[str, Any]]) -> None:
        node_rows = list(nodes)
        edge_rows = list(edges)
        self.nodes = {row["record_id"]: row for row in node_rows}
        if len(self.nodes) != len(node_rows):
            raise RuntimeError("duplicate graph record_id")
        self.edges = tuple(edge_rows)
        forward: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        reverse: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for edge in self.edges:
            if edge["source_record_id"] not in self.nodes or edge["target_record_id"] not in self.nodes:
                raise RuntimeError(f"orphan persisted graph edge: {edge.get('edge_id')}")
            forward[(edge["source_record_id"], edge["relation_type"])].append(edge)
            reverse[(edge["target_record_id"], edge["relation_type"])].append(edge)
        self.forward = {key: tuple(sorted(value, key=_edge_sort_key)) for key, value in forward.items()}
        self.reverse = {key: tuple(sorted(value, key=_edge_sort_key)) for key, value in reverse.items()}
        node_types = {row["node_type"] for row in node_rows}
        relation_types = {row["relation_type"] for row in edge_rows}
        if len(node_rows) != 155391 or len(node_types) != 14:
            raise RuntimeError(f"persisted node universe mismatch: {len(node_rows)} / {len(node_types)}")
        if len(edge_rows) != 184223 or len(relation_types) != 22:
            raise RuntimeError(f"persisted edge universe mismatch: {len(edge_rows)} / {len(relation_types)}")

    @classmethod
    def load(cls, root: Path) -> tuple["FrozenGraph", float]:
        graph_dir = root / "results/graphrag/phase6a_graph_retrieval_v1_0/graph"
        started = time.perf_counter_ns()
        result = cls(load_jsonl(graph_dir / "nodes.jsonl"), load_jsonl(graph_dir / "edges.jsonl"))
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        return result, elapsed_ms

    def raw_edges(self, record_id: str, relation_id: str, direction: str) -> tuple[dict[str, Any], ...]:
        if direction == "FORWARD":
            return self.forward.get((record_id, relation_id), ())
        if direction == "REVERSE":
            return self.reverse.get((record_id, relation_id), ())
        raise ValueError(f"invalid direction: {direction}")

    @staticmethod
    def next_record_id(edge: dict[str, Any], direction: str) -> str:
        return edge["target_record_id"] if direction == "FORWARD" else edge["source_record_id"]

    def transition_global_maximum(self, transition: dict[str, Any]) -> int:
        relation = transition["relation_id"]
        mapping = self.forward if transition["traversal_direction"] == "FORWARD" else self.reverse
        return max((len(edges) for (record_id, rel), edges in mapping.items() if rel == relation), default=0)


class ExactAnchorResolver:
    def __init__(self, graph: FrozenGraph) -> None:
        index: dict[tuple[str, str], list[str]] = defaultdict(list)
        for record_id, node in graph.nodes.items():
            values = node.get("identifier_values", {})
            for route_type, (node_type, field, _) in ANCHOR_DOMAINS.items():
                if node["node_type"] == node_type and values.get(field):
                    index[(route_type, str(values[field]))].append(record_id)
        self.index = {key: tuple(sorted(values)) for key, values in index.items()}

    def resolve(self, route: dict[str, Any]) -> dict[str, Any]:
        case_id = str(route.get("case_id", ""))
        input_type = str(route.get("primary_entity_type", ""))
        input_id = str(route.get("primary_entity_id", ""))
        base = {
            "case_id": case_id,
            "anchor_input_type": input_type,
            "anchor_input_id": input_id,
            "resolution_method": "EXACT_CANONICAL",
            "technical_error": None,
        }
        if input_type not in ANCHOR_DOMAINS:
            return {**base, "resolution_status": "UNRESOLVED", "resolved_record_ids": [], "resolved_node_types": []}
        node_type, _, expected = ANCHOR_DOMAINS[input_type]
        matches = self.index.get((input_type, input_id), ())
        if not matches:
            return {**base, "resolution_status": "UNRESOLVED", "resolved_record_ids": [], "resolved_node_types": []}
        if expected == "EXACT_SINGLE" and len(matches) != 1:
            return {
                **base,
                "resolution_status": "TECHNICAL_FAILURE",
                "resolved_record_ids": [],
                "resolved_node_types": [],
                "technical_error": f"canonical single-valued anchor matched {len(matches)} nodes",
            }
        return {
            **base,
            "resolution_status": "EXACT_MULTI" if expected == "EXACT_MULTI" and len(matches) > 1 else "EXACT_SINGLE",
            "resolved_record_ids": list(matches),
            "resolved_node_types": [node_type],
        }


@dataclass(frozen=True)
class TraversalRun:
    anchor_resolutions: tuple[dict[str, Any], ...]
    candidate_paths: tuple[dict[str, Any], ...]
    candidate_records: tuple[dict[str, Any], ...]
    rejections: tuple[dict[str, Any], ...]
    case_results: tuple[dict[str, Any], ...]
    telemetry: dict[str, Any]

    def deterministic_components(self) -> dict[str, str]:
        components = {
            "anchor_resolutions": self.anchor_resolutions,
            "candidate_paths": self.candidate_paths,
            "candidate_records": self.candidate_records,
            "traversal_rejections": self.rejections,
            "case_results": self.case_results,
        }
        return {
            name: hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
            for name, value in components.items()
        }


@dataclass(frozen=True)
class _Frontier:
    root_index: int
    records: tuple[str, ...]
    transition_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    provenance: tuple[dict[str, Any], ...]
    temporal: tuple[dict[str, Any], ...]


class CandidateTraversalEngine:
    """Default-deny traversal; graph edges are reachable only through registry rows."""

    def __init__(self, graph: FrozenGraph, bundle: FrozenGrammarBundle) -> None:
        self.graph = graph
        self.bundle = bundle
        self.transitions = {row["transition_id"]: row for row in bundle.transitions}
        by_current: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in bundle.transitions:
            by_current[row["current_node_type"]].append(row)
        self.transitions_by_current = {
            key: tuple(sorted(values, key=lambda value: value["transition_id"]))
            for key, values in by_current.items()
        }
        excluded: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in bundle.forbidden["excluded_frozen_directional_transitions"]:
            excluded[row["current_node_type"]].append(row)
        self.excluded_by_current = {
            key: tuple(sorted(values, key=lambda value: value["excluded_transition_id"]))
            for key, values in excluded.items()
        }
        self.resolver = ExactAnchorResolver(graph)
        self._validate_global_fanout()

    def _validate_global_fanout(self) -> None:
        mismatches = []
        for transition in self.transitions.values():
            observed = self.graph.transition_global_maximum(transition)
            expected = transition["observed_fanout"]["maximum_out_degree"]
            if observed != expected:
                mismatches.append({
                    "transition_id": transition["transition_id"],
                    "expected": expected,
                    "observed": observed,
                })
        if mismatches:
            raise RuntimeError(f"TOPOLOGY_DRIFT_REVIEW_REQUIRED: {mismatches}")

    @staticmethod
    def _transition_allowed(transition: dict[str, Any], depth: int) -> bool:
        if depth == 1 and not transition["allow_as_first_hop"]:
            return False
        if depth > 1 and not transition["allow_as_intermediate_hop"]:
            return False
        if depth == 3 and not transition["allow_as_terminal_hop"]:
            return False
        return depth <= transition["max_transition_depth"]

    def _edge_rejection(
        self,
        transition: dict[str, Any],
        edge: dict[str, Any],
        current: str,
        next_id: str,
        records: tuple[str, ...],
    ) -> str | None:
        direction = transition["traversal_direction"]
        if edge.get("relation_type") != transition["relation_id"] or edge.get("registry_relation_id") != transition["relation_id"]:
            return "EXACT_RELATION_MISMATCH"
        if direction == "FORWARD" and not edge.get("traversable"):
            return "DIRECTION_NOT_EXECUTABLE"
        if direction == "REVERSE" and not edge.get("reverse_traversal"):
            return "DIRECTION_NOT_EXECUTABLE"
        current_edge_type = edge["source_node_type"] if direction == "FORWARD" else edge["target_node_type"]
        next_edge_type = edge["target_node_type"] if direction == "FORWARD" else edge["source_node_type"]
        if (
            current_edge_type != transition["current_node_type"]
            or next_edge_type != transition["next_node_type"]
            or self.graph.nodes[current]["node_type"] != transition["current_node_type"]
            or self.graph.nodes[next_id]["node_type"] != transition["next_node_type"]
        ):
            return "EXACT_TYPE_MISMATCH"
        provenance = transition["operational_field_provenance"]
        if (
            not edge.get("edge_id")
            or not edge.get("provenance_record_id")
            or not edge.get("provenance_record_type")
            or not edge.get("provenance_fields")
            or edge.get("provenance_record_type") != provenance["provenance_record_type"]
        ):
            return "PROVENANCE_MISSING"
        cutoff = self.bundle.grammar["decision_cutoff"]
        if (
            not self.graph.nodes[current].get("temporal_eligible")
            or not self.graph.nodes[next_id].get("temporal_eligible")
            or not edge.get("temporal_eligible")
            or self.graph.nodes[current].get("available_at", "9999")[:10] > cutoff
            or self.graph.nodes[next_id].get("available_at", "9999")[:10] > cutoff
            or edge.get("effective_available_at", "9999")[:10] > cutoff
        ):
            return "TEMPORAL_INELIGIBILITY"
        if next_id in records:
            return "SIMPLE_PATH_VIOLATION"
        return None

    def run(self, routes: Sequence[dict[str, Any]]) -> TraversalRun:
        if len(routes) != 416 or len({str(row["case_id"]) for row in routes}) != 416:
            raise RuntimeError("authorized validation routing set must contain exactly 416 unique cases")
        resolutions = sorted((self.resolver.resolve(route) for route in routes), key=lambda row: row["case_id"])
        if any(row["resolution_status"] not in {"EXACT_SINGLE", "EXACT_MULTI"} for row in resolutions):
            raise RuntimeError("authorized validation routing set contains a non-exact anchor")
        if sum(len(row["resolved_record_ids"]) for row in resolutions) != 430:
            raise RuntimeError("authorized validation routing set did not resolve to 430 roots")
        route_by_case = {str(row["case_id"]): row for row in routes}
        candidate_paths: list[dict[str, Any]] = []
        rejections: list[dict[str, Any]] = []
        case_results: list[dict[str, Any]] = []
        transition_usage = Counter()
        transition_max_fanout = Counter()
        paths_by_depth = Counter()
        rejection_counts = Counter()
        terminal_stop_counts = Counter()
        case_latencies: list[dict[str, Any]] = []
        started_all = time.perf_counter_ns()

        for resolution in resolutions:
            case_id = resolution["case_id"]
            started_case = time.perf_counter_ns()
            partial = [
                _Frontier(index, (anchor,), (), (), (), ())
                for index, anchor in enumerate(resolution["resolved_record_ids"])
            ]
            case_paths: list[dict[str, Any]] = []
            case_rejections: list[dict[str, Any]] = []
            for depth in (1, 2, 3):
                expanded: list[_Frontier] = []
                for state in partial:
                    current = state.records[-1]
                    current_type = self.graph.nodes[current]["node_type"]
                    state_id = (
                        candidate_path_id(case_id, state.records[0], state.transition_ids, state.records, state.edge_ids)
                        if state.transition_ids else f"ROOT:{case_id}:{state.records[0]}"
                    )
                    # Observe prohibited physical edges without exposing them as executable neighbors.
                    for blocked in self.excluded_by_current.get(current_type, ()):
                        edges = self.graph.raw_edges(current, blocked["relation_id"], blocked["traversal_direction"])
                        for edge in edges:
                            row = {
                                "rejection_id": rejection_id(case_id, state_id, blocked["excluded_transition_id"], edge["edge_id"]),
                                "case_id": case_id,
                                "root_index": state.root_index,
                                "frontier_path_id": state_id,
                                "depth_attempted": depth,
                                "current_record_id": current,
                                "current_node_type": current_type,
                                "edge_id": edge["edge_id"],
                                "relation_id": blocked["relation_id"],
                                "direction": blocked["traversal_direction"],
                                "transition_id": blocked["excluded_transition_id"],
                                "rejection_reason": "HUB_PROHIBITED_TRANSITION",
                                "forbidden_reason_code": blocked["reason_code"],
                            }
                            case_rejections.append(row)
                            rejection_counts[row["rejection_reason"]] += 1
                    allowed = [
                        transition
                        for transition in self.transitions_by_current.get(current_type, ())
                        if self._transition_allowed(transition, depth)
                    ]
                    if not allowed:
                        terminal_stop_counts["NO_ALLOWED_OUTGOING_TYPED_TRANSITION"] += 1
                    for transition in allowed:
                        edges = self.graph.raw_edges(current, transition["relation_id"], transition["traversal_direction"])
                        transition_max_fanout[transition["transition_id"]] = max(
                            transition_max_fanout[transition["transition_id"]], len(edges)
                        )
                        for edge in edges:
                            next_id = self.graph.next_record_id(edge, transition["traversal_direction"])
                            reason = self._edge_rejection(transition, edge, current, next_id, state.records)
                            if reason is not None:
                                row = {
                                    "rejection_id": rejection_id(case_id, state_id, transition["transition_id"], edge["edge_id"], reason),
                                    "case_id": case_id,
                                    "root_index": state.root_index,
                                    "frontier_path_id": state_id,
                                    "depth_attempted": depth,
                                    "current_record_id": current,
                                    "current_node_type": current_type,
                                    "candidate_next_record_id": next_id,
                                    "edge_id": edge["edge_id"],
                                    "relation_id": transition["relation_id"],
                                    "direction": transition["traversal_direction"],
                                    "transition_id": transition["transition_id"],
                                    "rejection_reason": reason,
                                }
                                case_rejections.append(row)
                                rejection_counts[reason] += 1
                                continue
                            records = (*state.records, next_id)
                            transition_ids = (*state.transition_ids, transition["transition_id"])
                            edge_ids = (*state.edge_ids, edge["edge_id"])
                            provenance = (*state.provenance, {
                                "edge_id": edge["edge_id"],
                                "provenance_record_id": edge["provenance_record_id"],
                                "provenance_record_type": edge["provenance_record_type"],
                                "provenance_fields": edge["provenance_fields"],
                            })
                            temporal = (*state.temporal, {
                                "source_node_temporal_eligible": self.graph.nodes[current]["temporal_eligible"],
                                "target_node_temporal_eligible": self.graph.nodes[next_id]["temporal_eligible"],
                                "edge_temporal_eligible": edge["temporal_eligible"],
                                "effective_available_at": edge["effective_available_at"],
                                "accepted": True,
                            })
                            terminal = not transition["may_continue_after_transition"]
                            if terminal:
                                stop_reason = (
                                    "TERMINAL_CONTEXT_REACHED"
                                    if transition["transition_class"] == "TERMINAL_CONTEXT"
                                    else "REACHED_GL_ACCOUNTING_CONSEQUENCE"
                                    if transition["terminal_rule"] == "STOP_AFTER_ACCOUNTING_CONSEQUENCE"
                                    else "TERMINAL_TRANSITION_REACHED"
                                )
                            elif depth == 3:
                                stop_reason = "MAX_DEPTH_REACHED"
                            else:
                                stop_reason = "CONTINUATION_ALLOWED_PREFIX"
                            path_id = candidate_path_id(case_id, records[0], transition_ids, records, edge_ids)
                            path = {
                                "case_id": case_id,
                                "route_anchor_type": route_by_case[case_id]["primary_entity_type"],
                                "anchor_record_id": records[0],
                                "root_index": state.root_index,
                                "path_id": path_id,
                                "depth": depth,
                                "node_type_sequence": [self.graph.nodes[value]["node_type"] for value in records],
                                "record_id_sequence": list(records),
                                "transition_id_sequence": list(transition_ids),
                                "relation_id_sequence": [self.transitions[value]["relation_id"] for value in transition_ids],
                                "direction_sequence": [self.transitions[value]["traversal_direction"] for value in transition_ids],
                                "transition_class_sequence": [self.transitions[value]["transition_class"] for value in transition_ids],
                                "edge_id_sequence": list(edge_ids),
                                "provenance": list(provenance),
                                "temporal_eligibility": list(temporal),
                                "endpoint_record_id": next_id,
                                "endpoint_node_type": self.graph.nodes[next_id]["node_type"],
                                "terminal_status": terminal or depth == 3,
                                "continuation_permitted": not terminal and depth < 3,
                                "stop_reason": stop_reason,
                            }
                            case_paths.append(path)
                            paths_by_depth[str(depth)] += 1
                            for value in transition_ids:
                                transition_usage[value] += 1
                            if terminal:
                                terminal_stop_counts[stop_reason] += 1
                            else:
                                expanded.append(_Frontier(
                                    state.root_index, records, transition_ids, edge_ids, provenance, temporal
                                ))
                partial = expanded
            candidate_paths.extend(case_paths)
            rejections.extend(case_rejections)
            case_results.append({
                "case_id": case_id,
                "route_anchor_type": route_by_case[case_id]["primary_entity_type"],
                "resolution_status": resolution["resolution_status"],
                "resolved_root_count": len(resolution["resolved_record_ids"]),
                "candidate_path_count": len(case_paths),
                "path_count_by_exact_depth": {
                    str(depth): sum(row["depth"] == depth for row in case_paths) for depth in (1, 2, 3)
                },
                "traversal_rejection_count": len(case_rejections),
            })
            case_latencies.append({
                "case_id": case_id,
                "candidate_generation_latency_ms": (time.perf_counter_ns() - started_case) / 1_000_000,
            })

        candidate_paths.sort(key=lambda row: row["path_id"])
        if len({row["path_id"] for row in candidate_paths}) != len(candidate_paths):
            raise RuntimeError("duplicate candidate path ID")
        rejections.sort(key=lambda row: row["rejection_id"])
        candidate_records = self._candidate_records(resolutions, candidate_paths)
        records_by_case = Counter(row["case_id"] for row in candidate_records)
        for row in case_results:
            row["candidate_unique_record_count"] = records_by_case[row["case_id"]]
            row["selection_status"] = "NOT_RUN_POLICY_BLOCKED"
            row["retrieval_status"] = "SELECTION_FAILURE"
            row["selection_failure_reason"] = "RANKING_POLICY_AMBIGUOUS"
        case_results.sort(key=lambda row: row["case_id"])
        path_set_digest = hashlib.sha256(
            ("\n".join(row["path_id"] for row in candidate_paths) + "\n").encode("utf-8")
        ).hexdigest()
        if len(candidate_paths) != 13371 or dict(paths_by_depth) != {"1": 3332, "2": 4477, "3": 5562}:
            raise RuntimeError(
                f"TOPOLOGY_DRIFT_REVIEW_REQUIRED: paths={len(candidate_paths)} depth={dict(paths_by_depth)}"
            )
        if path_set_digest != EXPECTED_TOPOLOGY_PATH_SET_SHA256:
            raise RuntimeError(
                f"TOPOLOGY_DRIFT_REVIEW_REQUIRED: path digest {path_set_digest}"
            )
        if len(candidate_records) != 8369:
            raise RuntimeError(f"TOPOLOGY_DRIFT_REVIEW_REQUIRED: candidate records={len(candidate_records)}")
        endpoint_node_types = {row["endpoint_node_type"] for row in candidate_paths}
        if endpoint_node_types & {"VENDOR", "EMPLOYEE"}:
            raise RuntimeError("forbidden Vendor/Employee node entered accepted candidate paths")
        telemetry = {
            "status": "PASS",
            "candidate_path_count": len(candidate_paths),
            "paths_by_exact_depth": {str(depth): paths_by_depth[str(depth)] for depth in (1, 2, 3)},
            "candidate_path_set_sha256": path_set_digest,
            "candidate_record_row_count": len(candidate_records),
            "candidate_non_anchor_record_row_count": sum(row["minimum_depth"] > 0 for row in candidate_records),
            "resolved_root_count": sum(len(row["resolved_record_ids"]) for row in resolutions),
            "transition_path_incidence": dict(sorted(transition_usage.items())),
            "transition_maximum_reachable_frontier_fanout": dict(sorted(transition_max_fanout.items())),
            "accepted_path_transition_ids": sorted(transition_usage),
            "accepted_path_transition_count": len(transition_usage),
            "not_present_in_accepted_paths_transition_ids": sorted(set(self.transitions) - set(transition_usage)),
            "rejection_counts": dict(sorted(rejection_counts.items())),
            "terminal_stop_counts": dict(sorted(terminal_stop_counts.items())),
            "accepted_post_cutoff_traversal_count": 0,
            "vendor_or_employee_accepted_entry_count": 0,
            "total_candidate_generation_latency_ms": (time.perf_counter_ns() - started_all) / 1_000_000,
            "case_latencies": case_latencies,
        }
        return TraversalRun(
            anchor_resolutions=tuple(resolutions),
            candidate_paths=tuple(candidate_paths),
            candidate_records=tuple(candidate_records),
            rejections=tuple(rejections),
            case_results=tuple(case_results),
            telemetry=telemetry,
        )

    def _candidate_records(
        self,
        resolutions: Sequence[dict[str, Any]],
        paths: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        memberships: dict[tuple[str, str], set[str]] = defaultdict(set)
        minimum_depth: dict[tuple[str, str], int] = {}
        root_indices: dict[tuple[str, str], set[int]] = defaultdict(set)
        for resolution in resolutions:
            for index, record_id in enumerate(resolution["resolved_record_ids"]):
                key = (resolution["case_id"], record_id)
                minimum_depth[key] = 0
                root_indices[key].add(index)
        for path in paths:
            case_id = path["case_id"]
            for depth, record_id in enumerate(path["record_id_sequence"]):
                key = (case_id, record_id)
                memberships[key].add(path["path_id"])
                minimum_depth[key] = min(minimum_depth.get(key, depth), depth)
        rows = []
        for case_id, record_id in sorted(minimum_depth):
            node = self.graph.nodes[record_id]
            rows.append({
                "case_id": case_id,
                "record_id": record_id,
                "node_type": node["node_type"],
                "source_table": node["source_table"],
                "document_sha256": node["document_sha256"],
                "minimum_depth": minimum_depth[(case_id, record_id)],
                "is_resolved_anchor": minimum_depth[(case_id, record_id)] == 0,
                "root_indices": sorted(root_indices.get((case_id, record_id), set())),
                "supporting_path_ids": sorted(memberships.get((case_id, record_id), set())),
            })
        return rows
