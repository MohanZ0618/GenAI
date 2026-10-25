"""Split-neutral execution of the frozen Graph v1.1 traversal semantics.

The publication-frozen :mod:`candidate_traversal` runner contains validation-
snapshot assertions for 416 cases, 430 roots, and one exact path-set digest.
Those assertions are useful lineage checks, but they are not traversal rules.
This adapter deliberately reuses the frozen graph, grammar, transition, edge,
anchor, path-identity, provenance, temporal, and candidate-record code while
replacing only the validation-population assertions with split-neutral safety
invariants.  The original module remains byte-for-byte unchanged.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import time
from typing import Any, Sequence

from .candidate_traversal import (
    CandidateTraversalEngine,
    TraversalRun,
    _Frontier,
    candidate_path_id,
    rejection_id,
)


class SplitNeutralTraversalEngine(CandidateTraversalEngine):
    """Run the frozen traversal over any nonempty, unique, exactly resolved split."""

    def run(self, routes: Sequence[dict[str, Any]]) -> TraversalRun:
        case_ids = [str(row.get("case_id", "")) for row in routes]
        if not routes or any(not value for value in case_ids) or len(set(case_ids)) != len(case_ids):
            raise RuntimeError("split-neutral traversal requires nonempty unique case IDs")
        resolutions = sorted(
            (self.resolver.resolve(route) for route in routes), key=lambda row: row["case_id"]
        )
        if any(row["resolution_status"] not in {"EXACT_SINGLE", "EXACT_MULTI"} for row in resolutions):
            raise RuntimeError("split-neutral traversal received a non-exact anchor")

        route_by_case = {str(row["case_id"]): row for row in routes}
        candidate_paths: list[dict[str, Any]] = []
        rejections: list[dict[str, Any]] = []
        case_results: list[dict[str, Any]] = []
        transition_usage: Counter[str] = Counter()
        transition_max_fanout: Counter[str] = Counter()
        paths_by_depth: Counter[str] = Counter()
        rejection_counts: Counter[str] = Counter()
        terminal_stop_counts: Counter[str] = Counter()
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
                        candidate_path_id(
                            case_id,
                            state.records[0],
                            state.transition_ids,
                            state.records,
                            state.edge_ids,
                        )
                        if state.transition_ids
                        else f"ROOT:{case_id}:{state.records[0]}"
                    )

                    # Audit physically present forbidden edges without making them executable.
                    for blocked in self.excluded_by_current.get(current_type, ()):
                        edges = self.graph.raw_edges(
                            current, blocked["relation_id"], blocked["traversal_direction"]
                        )
                        for edge in edges:
                            row = {
                                "rejection_id": rejection_id(
                                    case_id,
                                    state_id,
                                    blocked["excluded_transition_id"],
                                    edge["edge_id"],
                                ),
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
                        edges = self.graph.raw_edges(
                            current,
                            transition["relation_id"],
                            transition["traversal_direction"],
                        )
                        transition_max_fanout[transition["transition_id"]] = max(
                            transition_max_fanout[transition["transition_id"]], len(edges)
                        )
                        for edge in edges:
                            next_id = self.graph.next_record_id(
                                edge, transition["traversal_direction"]
                            )
                            reason = self._edge_rejection(
                                transition, edge, current, next_id, state.records
                            )
                            if reason is not None:
                                row = {
                                    "rejection_id": rejection_id(
                                        case_id,
                                        state_id,
                                        transition["transition_id"],
                                        edge["edge_id"],
                                        reason,
                                    ),
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
                            provenance = (
                                *state.provenance,
                                {
                                    "edge_id": edge["edge_id"],
                                    "provenance_record_id": edge["provenance_record_id"],
                                    "provenance_record_type": edge["provenance_record_type"],
                                    "provenance_fields": edge["provenance_fields"],
                                },
                            )
                            temporal = (
                                *state.temporal,
                                {
                                    "source_node_temporal_eligible": self.graph.nodes[current][
                                        "temporal_eligible"
                                    ],
                                    "target_node_temporal_eligible": self.graph.nodes[next_id][
                                        "temporal_eligible"
                                    ],
                                    "edge_temporal_eligible": edge["temporal_eligible"],
                                    "effective_available_at": edge["effective_available_at"],
                                    "accepted": True,
                                },
                            )
                            terminal = not transition["may_continue_after_transition"]
                            if terminal:
                                stop_reason = (
                                    "TERMINAL_CONTEXT_REACHED"
                                    if transition["transition_class"] == "TERMINAL_CONTEXT"
                                    else "REACHED_GL_ACCOUNTING_CONSEQUENCE"
                                    if transition["terminal_rule"]
                                    == "STOP_AFTER_ACCOUNTING_CONSEQUENCE"
                                    else "TERMINAL_TRANSITION_REACHED"
                                )
                            elif depth == 3:
                                stop_reason = "MAX_DEPTH_REACHED"
                            else:
                                stop_reason = "CONTINUATION_ALLOWED_PREFIX"
                            path_id = candidate_path_id(
                                case_id, records[0], transition_ids, records, edge_ids
                            )
                            path = {
                                "case_id": case_id,
                                "route_anchor_type": route_by_case[case_id][
                                    "primary_entity_type"
                                ],
                                "anchor_record_id": records[0],
                                "root_index": state.root_index,
                                "path_id": path_id,
                                "depth": depth,
                                "node_type_sequence": [
                                    self.graph.nodes[value]["node_type"] for value in records
                                ],
                                "record_id_sequence": list(records),
                                "transition_id_sequence": list(transition_ids),
                                "relation_id_sequence": [
                                    self.transitions[value]["relation_id"]
                                    for value in transition_ids
                                ],
                                "direction_sequence": [
                                    self.transitions[value]["traversal_direction"]
                                    for value in transition_ids
                                ],
                                "transition_class_sequence": [
                                    self.transitions[value]["transition_class"]
                                    for value in transition_ids
                                ],
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
                                expanded.append(
                                    _Frontier(
                                        state.root_index,
                                        records,
                                        transition_ids,
                                        edge_ids,
                                        provenance,
                                        temporal,
                                    )
                                )
                partial = expanded

            candidate_paths.extend(case_paths)
            rejections.extend(case_rejections)
            case_results.append(
                {
                    "case_id": case_id,
                    "route_anchor_type": route_by_case[case_id]["primary_entity_type"],
                    "resolution_status": resolution["resolution_status"],
                    "resolved_root_count": len(resolution["resolved_record_ids"]),
                    "candidate_path_count": len(case_paths),
                    "path_count_by_exact_depth": {
                        str(value): sum(row["depth"] == value for row in case_paths)
                        for value in (1, 2, 3)
                    },
                    "traversal_rejection_count": len(case_rejections),
                }
            )
            case_latencies.append(
                {
                    "case_id": case_id,
                    "candidate_generation_latency_ms": (
                        time.perf_counter_ns() - started_case
                    )
                    / 1_000_000,
                }
            )

        candidate_paths.sort(key=lambda row: row["path_id"])
        if len({row["path_id"] for row in candidate_paths}) != len(candidate_paths):
            raise RuntimeError("duplicate candidate path ID")
        rejections.sort(key=lambda row: row["rejection_id"])
        candidate_records = self._candidate_records(resolutions, candidate_paths)
        records_by_case = Counter(row["case_id"] for row in candidate_records)
        for row in case_results:
            row["candidate_unique_record_count"] = records_by_case[row["case_id"]]
            row["selection_status"] = "NOT_RUN"
            row["retrieval_status"] = "CANDIDATES_READY"
            row["selection_failure_reason"] = None
        case_results.sort(key=lambda row: row["case_id"])

        endpoint_node_types = {row["endpoint_node_type"] for row in candidate_paths}
        if endpoint_node_types & {"VENDOR", "EMPLOYEE", "GL_JOURNAL"}:
            raise RuntimeError("forbidden node entered accepted candidate paths")
        if any(
            not hop.get("accepted")
            for path in candidate_paths
            for hop in path["temporal_eligibility"]
        ):
            raise RuntimeError("noneligible hop entered accepted candidate paths")

        path_set_digest = hashlib.sha256(
            ("\n".join(row["path_id"] for row in candidate_paths) + "\n").encode("utf-8")
        ).hexdigest()
        telemetry = {
            "status": "PASS",
            "candidate_path_count": len(candidate_paths),
            "paths_by_exact_depth": {
                str(depth): paths_by_depth[str(depth)] for depth in (1, 2, 3)
            },
            "candidate_path_set_sha256": path_set_digest,
            "candidate_record_row_count": len(candidate_records),
            "candidate_non_anchor_record_row_count": sum(
                row["minimum_depth"] > 0 for row in candidate_records
            ),
            "resolved_root_count": sum(
                len(row["resolved_record_ids"]) for row in resolutions
            ),
            "transition_path_incidence": dict(sorted(transition_usage.items())),
            "transition_maximum_reachable_frontier_fanout": dict(
                sorted(transition_max_fanout.items())
            ),
            "accepted_path_transition_ids": sorted(transition_usage),
            "accepted_path_transition_count": len(transition_usage),
            "not_present_in_accepted_paths_transition_ids": sorted(
                set(self.transitions) - set(transition_usage)
            ),
            "rejection_counts": dict(sorted(rejection_counts.items())),
            "terminal_stop_counts": dict(sorted(terminal_stop_counts.items())),
            "accepted_post_cutoff_traversal_count": 0,
            "vendor_or_employee_accepted_entry_count": 0,
            "total_candidate_generation_latency_ms": (
                time.perf_counter_ns() - started_all
            )
            / 1_000_000,
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
