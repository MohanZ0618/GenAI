"""Locked, label-blind Graph v1.1 path-first evidence selection."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


POLICY_SHA256 = "db509ca1442b832b0c8b4bc401b8902cfec8f4fbd337a00f4ec12a62bf8cfcf8"
MEANINGFUL_STOP_REASONS = frozenset({
    "TERMINAL_CONTEXT_REACHED",
    "REACHED_GL_ACCOUNTING_CONSEQUENCE",
    "MAX_DEPTH_REACHED",
})
CLASS_RANK = {"BACKBONE": 0, "SUPPORTING": 1, "TERMINAL_CONTEXT": 2, "CONTEXT": 3}
TIER_NAMES = {
    0: "MANDATORY_ANCHOR",
    1: "ANCHOR_OWNER_BRIDGE",
    2: "COMPLETE_BACKBONE_ACCOUNTING_PATH",
    3: "MAXIMAL_BACKBONE_LIFECYCLE_PATH",
    4: "BACKBONE_PLUS_SUPPORTING_PATH",
    5: "LOCAL_TERMINAL_CONTEXT_PATH",
}
_POLICY_STATUSES = frozenset({
    "PREREGISTERED_DRAFT",
    "FROZEN_GRAPH_V1_1_EVIDENCE_SELECTION_POLICY",
})
_STOP_REASONS = frozenset({
    "CONTINUATION_ALLOWED_PREFIX",
    "MAX_DEPTH_REACHED",
    "REACHED_GL_ACCOUNTING_CONSEQUENCE",
    "TERMINAL_CONTEXT_REACHED",
})
_PATH_ORDER_KEYS = (
    "selection_tier",
    "terminal_completeness_rank",
    "transition_class_rank_sequence",
    "path_depth_within_semantic_tier",
    "frozen_relation_registry_ordinal_sequence",
    "direction_then_transition_id_sequence",
    "record_id_sequence",
    "anchor_record_id",
    "root_index",
    "edge_id_sequence",
    "path_id",
)


class SelectionPolicyError(RuntimeError):
    """Fail-closed policy or structural-input violation."""


def _validate_policy(policy: Mapping[str, Any]) -> None:
    tiers = {
        int(row.get("selection_tier", -1)): row.get("machine_name")
        for row in policy.get("path_priority_tiers", ())
    }
    order_keys = tuple(row.get("key") for row in policy.get("tie_break_policy", {}).get("path_order_keys", ()))
    exact_multi = policy.get("exact_multi_policy", {})
    atomic = policy.get("atomic_path_admission", {})
    canonicalization = policy.get("path_canonicalization_policy", {})
    multi_root = policy.get("multi_root_path_policy", {})
    if (
        policy.get("status") not in _POLICY_STATUSES
        or policy.get("max_selected_records") != 40
        or tiers != TIER_NAMES
        or order_keys != _PATH_ORDER_KEYS
        or policy.get("tie_break_policy", {}).get("transition_class_rank") != CLASS_RANK
        or set(canonicalization.get("independently_meaningful_stop_reasons", ())) != MEANINGFUL_STOP_REASONS
        or atomic.get("partial_admission_allowed") is not False
        or atomic.get("continue_after_nonfitting_path") is not True
        or atomic.get("admit_zero_cost_paths") is not True
        or exact_multi.get("all_roots_mandatory") is not True
        or exact_multi.get("collapse_roots") is not False
        or exact_multi.get("global_budget") != 40
        or multi_root.get("round_robin") is not False
        or multi_root.get("single_root_exhaustion_phase") is not False
    ):
        raise SelectionPolicyError("selection policy semantics differ from the locked interpreter contract")
    gold = policy.get("gold_access_policy", {})
    if any(bool(value) for value in gold.values()):
        raise SelectionPolicyError("gold access is enabled by the supplied selection policy")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_policy(path: str | Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    policy_path = Path(path)
    expected = expected_sha256 or POLICY_SHA256
    observed = _sha256_file(policy_path)
    if observed != expected:
        raise SelectionPolicyError(f"locked selection policy hash mismatch: expected={expected} observed={observed}")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    _validate_policy(policy)
    if policy.get("status") == "PREREGISTERED_DRAFT" and policy.get(
        "policy_preregistered_before_case_level_simulation"
    ) is not True:
        raise SelectionPolicyError("locked selection policy invariants failed")
    return policy


def _validate_grammar(grammar: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    prohibited_flags = (
        "bank_statement_membership_enabled",
        "generic_bfs_enabled",
        "payment_bank_enabled",
        "semantic_fallback_enabled",
        "synthetic_gl_journal_enabled",
        "tier_b_enabled",
        "new_graph_edges_created",
        "new_node_types_created",
        "new_relation_types_created",
    )
    if (
        grammar.get("max_path_depth") != 3
        or grammar.get("simple_path_only") is not True
        or grammar.get("default_deny") is not True
        or any(grammar.get(name) is not False for name in prohibited_flags)
    ):
        raise SelectionPolicyError("frozen Graph v1.1 grammar safety invariants failed")
    rows = grammar.get("transitions")
    if not isinstance(rows, list) or not rows:
        raise SelectionPolicyError("frozen grammar transition registry is absent")
    transitions = {str(row.get("transition_id", "")): row for row in rows}
    if "" in transitions or len(transitions) != len(rows):
        raise SelectionPolicyError("duplicate or empty frozen transition ID")
    return transitions


def _is_owner_bridge(path: Mapping[str, Any]) -> bool:
    return (
        path["depth"] == 1
        and path["node_type_sequence"][0] in {"APPROVAL_EVENT", "AUDIT_EVENT"}
        and path["transition_class_sequence"] == ["CONTEXT"]
    )


def _normalized_classes(path: Mapping[str, Any]) -> tuple[str, ...]:
    classes = tuple(path["transition_class_sequence"])
    if (
        len(classes) > 1
        and path["node_type_sequence"][0] in {"APPROVAL_EVENT", "AUDIT_EVENT"}
        and classes[0] == "CONTEXT"
    ):
        return classes[1:]
    return classes


def _semantic_family(path: Mapping[str, Any]) -> str:
    if _is_owner_bridge(path):
        return "ANCHOR_OWNER_BRIDGE"
    if path["transition_class_sequence"][-1] == "TERMINAL_CONTEXT":
        if path["stop_reason"] != "TERMINAL_CONTEXT_REACHED":
            raise SelectionPolicyError(f"terminal-context stop mismatch: {path['path_id']}")
        return "TERMINAL_CONTEXT_FAMILY"
    classes = _normalized_classes(path)
    if classes and all(value == "BACKBONE" for value in classes):
        return "BACKBONE_FAMILY"
    if classes and set(classes) <= {"BACKBONE", "SUPPORTING"} and "SUPPORTING" in classes:
        return "SUPPORTING_FAMILY"
    raise SelectionPolicyError(
        f"UNHANDLED_FROZEN_PATH_CLASS_COMBINATION: {path['path_id']} {list(classes)}"
    )


def _strict_prefix(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if (
        left["case_id"] != right["case_id"]
        or left["anchor_record_id"] != right["anchor_record_id"]
        or left["depth"] >= right["depth"]
    ):
        return False
    for field in (
        "record_id_sequence", "transition_id_sequence", "relation_id_sequence",
        "direction_sequence", "edge_id_sequence",
    ):
        values = left[field]
        if values != right[field][: len(values)]:
            return False
    return True


def _project_path(path: Mapping[str, Any], transitions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    required = (
        "case_id", "anchor_record_id", "root_index", "path_id", "depth",
        "node_type_sequence", "record_id_sequence", "transition_id_sequence",
        "relation_id_sequence", "direction_sequence", "transition_class_sequence",
        "edge_id_sequence", "provenance", "terminal_status", "stop_reason",
    )
    missing = [field for field in required if field not in path]
    if missing:
        raise SelectionPolicyError(f"candidate path missing fields {missing}")
    depth = int(path["depth"])
    if depth < 1 or depth > 3:
        raise SelectionPolicyError(f"path depth outside frozen range: {path['path_id']}")
    records = tuple(str(value) for value in path["record_id_sequence"])
    nodes = tuple(str(value) for value in path["node_type_sequence"])
    transition_ids = tuple(str(value) for value in path["transition_id_sequence"])
    relations = tuple(str(value) for value in path["relation_id_sequence"])
    directions = tuple(str(value) for value in path["direction_sequence"])
    classes = tuple(str(value) for value in path["transition_class_sequence"])
    edge_ids = tuple(str(value) for value in path["edge_id_sequence"])
    provenance_rows = path["provenance"]
    if not isinstance(provenance_rows, list) or len(provenance_rows) != depth:
        raise SelectionPolicyError(f"candidate path provenance length mismatch: {path['path_id']}")
    if len(records) != depth + 1 or len(set(records)) != len(records):
        raise SelectionPolicyError(f"candidate path violates simple-path shape: {path['path_id']}")
    if len(nodes) != depth + 1 or any(len(values) != depth for values in (transition_ids, relations, directions, classes, edge_ids)):
        raise SelectionPolicyError(f"candidate path sequence length mismatch: {path['path_id']}")
    if nodes[0] in {"VENDOR", "EMPLOYEE"} or set(nodes[1:]) & {"VENDOR", "EMPLOYEE", "GL_JOURNAL"}:
        raise SelectionPolicyError(f"forbidden node type in candidate path: {path['path_id']}")
    provenance_ids = []
    for index, transition_id in enumerate(transition_ids):
        transition = transitions.get(transition_id)
        if transition is None:
            raise SelectionPolicyError(f"unregistered transition: {transition_id}")
        if (
            transition["current_node_type"] != nodes[index]
            or transition["next_node_type"] != nodes[index + 1]
            or transition["relation_id"] != relations[index]
            or transition["traversal_direction"] != directions[index]
            or transition["transition_class"] != classes[index]
        ):
            raise SelectionPolicyError(f"frozen transition metadata mismatch: {path['path_id']}")
        if relations[index] in {
            "PAYMENT_CANDIDATE_BANK_TRANSACTION", "BANK_STATEMENT_CONTAINS_TRANSACTION",
            "GL_JOURNAL_GROUPING",
        }:
            raise SelectionPolicyError(f"forbidden relation in candidate path: {path['path_id']}")
        provenance = provenance_rows[index]
        if not isinstance(provenance, Mapping) or str(provenance.get("edge_id", "")) != edge_ids[index]:
            raise SelectionPolicyError(f"edge/provenance mismatch: {path['path_id']}")
        provenance_id = str(provenance.get("provenance_record_id", ""))
        if not provenance_id:
            raise SelectionPolicyError(f"missing provenance ID: {path['path_id']}")
        provenance_ids.append(provenance_id)
    path_id = str(path["path_id"])
    case_id = str(path["case_id"])
    anchor_record_id = str(path["anchor_record_id"])
    stop_reason = str(path["stop_reason"])
    terminal_status = bool(path["terminal_status"])
    if not path_id or not case_id or not anchor_record_id or records[0] != anchor_record_id:
        raise SelectionPolicyError(f"candidate path root identity mismatch: {path_id}")
    if int(path["root_index"]) < 0:
        raise SelectionPolicyError(f"negative root index: {path_id}")
    if any(value == "CONTEXT" for value in classes[1:]):
        raise SelectionPolicyError(f"CONTEXT transition appears after hop 1: {path_id}")
    if classes[0] == "CONTEXT" and nodes[0] not in {"APPROVAL_EVENT", "AUDIT_EVENT"}:
        raise SelectionPolicyError(f"CONTEXT path lacks an event root: {path_id}")
    if any(value == "TERMINAL_CONTEXT" for value in classes[:-1]):
        raise SelectionPolicyError(f"TERMINAL_CONTEXT transition is nonterminal: {path_id}")
    if stop_reason not in _STOP_REASONS:
        raise SelectionPolicyError(f"unknown frozen stop reason: {path_id}/{stop_reason}")
    last_rule = transitions[transition_ids[-1]]["terminal_rule"]
    if stop_reason == "CONTINUATION_ALLOWED_PREFIX":
        valid_stop = not terminal_status and depth < 3 and last_rule not in {
            "STOP_AFTER_ACCOUNTING_CONSEQUENCE", "STOP_AFTER_LOCAL_CONTEXT_NODE",
        }
    elif stop_reason == "MAX_DEPTH_REACHED":
        valid_stop = terminal_status and depth == 3 and last_rule not in {
            "STOP_AFTER_ACCOUNTING_CONSEQUENCE", "STOP_AFTER_LOCAL_CONTEXT_NODE",
        }
    elif stop_reason == "REACHED_GL_ACCOUNTING_CONSEQUENCE":
        valid_stop = (
            terminal_status
            and nodes[-1] == "GL_ENTRY"
            and last_rule == "STOP_AFTER_ACCOUNTING_CONSEQUENCE"
        )
    else:
        valid_stop = (
            terminal_status
            and classes[-1] == "TERMINAL_CONTEXT"
            and last_rule == "STOP_AFTER_LOCAL_CONTEXT_NODE"
        )
    if not valid_stop:
        raise SelectionPolicyError(f"terminal state/grammar mismatch: {path_id}/{stop_reason}")
    return {
        "case_id": case_id,
        "anchor_record_id": anchor_record_id,
        "root_index": int(path["root_index"]),
        "path_id": path_id,
        "depth": depth,
        "node_type_sequence": list(nodes),
        "record_id_sequence": list(records),
        "transition_id_sequence": list(transition_ids),
        "relation_id_sequence": list(relations),
        "direction_sequence": list(directions),
        "transition_class_sequence": list(classes),
        "edge_id_sequence": list(edge_ids),
        "provenance_record_id_sequence": provenance_ids,
        "provenance": deepcopy(provenance_rows),
        "terminal_status": terminal_status,
        "stop_reason": stop_reason,
        "endpoint_node_type": nodes[-1],
        "endpoint_record_id": records[-1],
    }


def _canonicalize(paths: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    families = {path["path_id"]: _semantic_family(path) for path in paths}
    redundant: list[dict[str, Any]] = []
    canonical: list[dict[str, Any]] = []
    for path in paths:
        extensions = []
        if not _is_owner_bridge(path) and path["stop_reason"] not in MEANINGFUL_STOP_REASONS:
            extensions = sorted(
                other["path_id"]
                for other in paths
                if families[other["path_id"]] == families[path["path_id"]] and _strict_prefix(path, other)
            )
        if extensions:
            redundant.append({
                "entry_type": "PATH",
                "case_id": path["case_id"],
                "path_id": path["path_id"],
                "semantic_family": families[path["path_id"]],
                "record_id_sequence": path["record_id_sequence"],
                "primary_drop_reason": "REDUNDANT_PREFIX",
                "structural_tags": [],
                "canonical_extension_path_ids": extensions,
                "resurrection_allowed": False,
            })
        else:
            canonical.append({**path, "semantic_family": families[path["path_id"]]})
    return canonical, redundant


def _classify_tier(path: Mapping[str, Any], transitions: Mapping[str, Mapping[str, Any]]) -> tuple[int, str]:
    if _is_owner_bridge(path):
        return 1, TIER_NAMES[1]
    if path["transition_class_sequence"][-1] == "TERMINAL_CONTEXT":
        if path["stop_reason"] != "TERMINAL_CONTEXT_REACHED":
            raise SelectionPolicyError(f"terminal context mismatch: {path['path_id']}")
        return 5, TIER_NAMES[5]
    classes = _normalized_classes(path)
    last_transition = transitions[path["transition_id_sequence"][-1]]
    if (
        classes
        and all(value == "BACKBONE" for value in classes)
        and last_transition["terminal_rule"] == "STOP_AFTER_ACCOUNTING_CONSEQUENCE"
        and path["endpoint_node_type"] == "GL_ENTRY"
        and path["stop_reason"] == "REACHED_GL_ACCOUNTING_CONSEQUENCE"
    ):
        return 2, TIER_NAMES[2]
    if classes and all(value == "BACKBONE" for value in classes):
        return 3, TIER_NAMES[3]
    if classes and set(classes) <= {"BACKBONE", "SUPPORTING"} and "SUPPORTING" in classes:
        return 4, TIER_NAMES[4]
    raise SelectionPolicyError(f"UNHANDLED_FROZEN_PATH_CLASS_COMBINATION: {path['path_id']}")


def _terminal_rank(path: Mapping[str, Any]) -> int:
    if _is_owner_bridge(path) or path["stop_reason"] == "REACHED_GL_ACCOUNTING_CONSEQUENCE":
        return 0
    if path["stop_reason"] == "MAX_DEPTH_REACHED":
        return 1
    if path["stop_reason"] == "TERMINAL_CONTEXT_REACHED":
        return 2
    return 3


def _path_key(path: Mapping[str, Any], relation_order: Mapping[str, int]) -> tuple[Any, ...]:
    missing_relations = sorted(set(path["relation_id_sequence"]) - set(relation_order))
    if missing_relations:
        raise SelectionPolicyError(f"relation registry ordinal absent: {missing_relations}")
    return (
        path["selection_tier"],
        _terminal_rank(path),
        tuple(CLASS_RANK[value] for value in path["transition_class_sequence"]),
        -path["depth"],
        tuple(relation_order[value] for value in path["relation_id_sequence"]),
        tuple(zip(path["direction_sequence"], path["transition_id_sequence"])),
        tuple(path["record_id_sequence"]),
        path["anchor_record_id"],
        path["root_index"],
        tuple(path["edge_id_sequence"]),
        path["path_id"],
    )


def _project_record(record: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "case_id", "record_id", "node_type", "minimum_depth", "is_resolved_anchor",
        "root_indices", "supporting_path_ids",
    }
    if not required <= record.keys():
        raise SelectionPolicyError(f"candidate record missing fields: {sorted(required - record.keys())}")
    return {
        "case_id": str(record["case_id"]),
        "record_id": str(record["record_id"]),
        "node_type": str(record["node_type"]),
        "minimum_reachable_depth": int(record["minimum_depth"]),
        "is_resolved_anchor": bool(record["is_resolved_anchor"]),
        "root_indices": sorted({int(value) for value in record["root_indices"]}),
        "all_supporting_path_ids": sorted({str(value) for value in record["supporting_path_ids"]}),
    }


@dataclass(frozen=True)
class SelectionCaseResult:
    case_id: str
    selected_paths: tuple[dict[str, Any], ...]
    selected_records: tuple[dict[str, Any], ...]
    path_drop_ledger: tuple[dict[str, Any], ...]
    record_drop_ledger: tuple[dict[str, Any], ...]
    summary: dict[str, Any]

    def summary_dict(self) -> dict[str, Any]:
        return dict(self.summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "selected_paths": list(self.selected_paths),
            "selected_records": list(self.selected_records),
            "path_drop_ledger": list(self.path_drop_ledger),
            "record_drop_ledger": list(self.record_drop_ledger),
            "summary": self.summary_dict(),
        }


def select_case(
    policy: Mapping[str, Any],
    grammar: Mapping[str, Any],
    relation_order: Mapping[str, int],
    anchor_row: Mapping[str, Any],
    candidate_paths: Iterable[Mapping[str, Any]],
    candidate_records: Iterable[Mapping[str, Any]],
) -> SelectionCaseResult:
    _validate_policy(policy)
    max_records = int(policy["max_selected_records"])
    if max_records != 40:
        raise SelectionPolicyError("selection budget differs from locked 40-record maximum")
    case_id = str(anchor_row["case_id"])
    resolution_status = str(anchor_row.get("resolution_status", ""))
    if resolution_status not in {"EXACT_SINGLE", "EXACT_MULTI"}:
        raise SelectionPolicyError(f"selector requires an exact anchor resolution: {case_id}")
    raw_roots = [str(value) for value in anchor_row["resolved_record_ids"]]
    if not raw_roots or len(raw_roots) != len(set(raw_roots)):
        raise SelectionPolicyError(f"empty or duplicate exact roots: {case_id}")
    roots = sorted(raw_roots)
    if resolution_status == "EXACT_SINGLE" and len(roots) != 1:
        raise SelectionPolicyError(f"EXACT_SINGLE root cardinality mismatch: {case_id}")
    transitions = _validate_grammar(grammar)
    if not relation_order or len(set(relation_order.values())) != len(relation_order):
        raise SelectionPolicyError("relation registry ordinals are empty or non-unique")
    paths = [_project_path(row, transitions) for row in candidate_paths]
    records = [_project_record(row) for row in candidate_records]
    if any(row["case_id"] != case_id for row in [*paths, *records]):
        raise SelectionPolicyError(f"cross-case candidate input supplied for {case_id}")
    if len({row["path_id"] for row in paths}) != len(paths):
        raise SelectionPolicyError(f"duplicate candidate path ID for {case_id}")
    record_by_id = {row["record_id"]: row for row in records}
    if len(record_by_id) != len(records):
        raise SelectionPolicyError(f"duplicate candidate record for {case_id}")
    if not set(roots) <= set(record_by_id):
        raise SelectionPolicyError(f"mandatory root absent from candidate records for {case_id}")
    if any(path["anchor_record_id"] not in roots for path in paths):
        raise SelectionPolicyError(f"candidate path root not authoritative for {case_id}")
    for path in paths:
        expected_index = roots.index(path["anchor_record_id"])
        if path["root_index"] != expected_index:
            raise SelectionPolicyError(f"candidate path root index mismatch: {path['path_id']}")
    all_path_ids = {path["path_id"] for path in paths}
    memberships: dict[str, set[str]] = defaultdict(set)
    minimum_depths: dict[str, int] = {root: 0 for root in roots}
    observed_node_types: dict[str, set[str]] = defaultdict(set)
    paths_by_id = {path["path_id"]: path for path in paths}
    for path in paths:
        for depth_index, (record_id, node_type) in enumerate(zip(
            path["record_id_sequence"], path["node_type_sequence"]
        )):
            if record_id not in record_by_id:
                raise SelectionPolicyError(f"path record absent from candidate pool: {record_id}")
            memberships[record_id].add(path["path_id"])
            observed_node_types[record_id].add(node_type)
            minimum_depths[record_id] = min(minimum_depths.get(record_id, depth_index), depth_index)
    for record_id, record in record_by_id.items():
        if set(record["all_supporting_path_ids"]) != memberships.get(record_id, set()):
            raise SelectionPolicyError(f"supporting path membership mismatch: {case_id}/{record_id}")
        if not set(record["all_supporting_path_ids"]) <= all_path_ids:
            raise SelectionPolicyError(f"unknown supporting path: {case_id}/{record_id}")
        if record_id not in roots and not memberships.get(record_id):
            raise SelectionPolicyError(f"non-anchor candidate record lacks a frozen path: {case_id}/{record_id}")
        if observed_node_types.get(record_id, {record["node_type"]}) != {record["node_type"]}:
            raise SelectionPolicyError(f"candidate record node type mismatch: {case_id}/{record_id}")
        if record["minimum_reachable_depth"] != minimum_depths.get(record_id, 0):
            raise SelectionPolicyError(f"candidate record minimum depth mismatch: {case_id}/{record_id}")
        root_index = roots.index(record_id) if record_id in roots else None
        if record["is_resolved_anchor"] != (record_id in roots):
            raise SelectionPolicyError(f"candidate anchor marker mismatch: {case_id}/{record_id}")
        if root_index is not None and root_index not in record["root_indices"]:
            raise SelectionPolicyError(f"candidate root-index membership mismatch: {case_id}/{record_id}")

    paths_by_root: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        paths_by_root[path["anchor_record_id"]].append(path)
    for root in roots:
        if record_by_id[root]["node_type"] not in {"APPROVAL_EVENT", "AUDIT_EVENT"}:
            continue
        root_paths = paths_by_root[root]
        longer_owner_routes = [
            path for path in root_paths
            if path["depth"] > 1 and path["transition_class_sequence"][0] == "CONTEXT"
        ]
        direct_bridges = [path for path in root_paths if _is_owner_bridge(path)]
        for longer in longer_owner_routes:
            if not any(_strict_prefix(bridge, longer) for bridge in direct_bridges):
                raise SelectionPolicyError(f"required ANCHOR_OWNER_BRIDGE prefix absent: {longer['path_id']}")

    canonical, redundant = _canonicalize(paths)
    classified = []
    for path in canonical:
        tier, name = _classify_tier(path, transitions)
        classified.append({**path, "selection_tier": tier, "selection_tier_name": name})
    classified.sort(key=lambda path: _path_key(path, relation_order))
    canonical_by_id = {path["path_id"]: path for path in classified}
    redundant_ids = {row["path_id"] for row in redundant}
    owner_paths = [path for path in classified if path["selection_tier"] == 1]
    owner_records = sorted({path["endpoint_record_id"] for path in owner_paths})
    mandatory = []
    for record_id in [*roots, *owner_records]:
        if record_id not in mandatory:
            mandatory.append(record_id)
    if len(mandatory) > max_records:
        raise SelectionPolicyError(f"MANDATORY_SET_EXCEEDS_BUDGET: {case_id}")

    selected_order: list[str] = []
    selected_set: set[str] = set()
    first_selection: dict[str, dict[str, Any]] = {}
    admitted_paths: list[dict[str, Any]] = []
    budget_drops: list[dict[str, Any]] = []

    def introduce(record_id: str, tier: int, path_id: str | None, reason: str) -> None:
        if record_id in selected_set:
            return
        if record_id not in record_by_id:
            raise SelectionPolicyError(f"selector attempted out-of-pool record: {record_id}")
        selected_set.add(record_id)
        selected_order.append(record_id)
        first_selection[record_id] = {
            "selection_tier": tier,
            "selection_tier_name": TIER_NAMES[tier],
            "first_selected_through_path_id": path_id,
            "reason_selected": reason,
        }

    for record_id in roots:
        introduce(record_id, 0, None, "MANDATORY_EXACT_ANCHOR")

    path_rank = 0
    for path in classified:
        if path["selection_tier"] == 1:
            new_records = [value for value in path["record_id_sequence"] if value not in selected_set]
            if len(selected_set) + len(set(new_records)) > max_records:
                raise SelectionPolicyError(f"MANDATORY_SET_EXCEEDS_BUDGET: {case_id}")
            path_rank += 1
            introduced = []
            for record_id in new_records:
                if record_id not in selected_set:
                    introduce(record_id, 1, path["path_id"], "MANDATORY_ANCHOR_OWNER_BRIDGE")
                    introduced.append(record_id)
            admitted_paths.append({
                **path,
                "selected_path_rank": path_rank,
                "path_new_record_cost_at_admission": len(introduced),
                "introduced_record_ids": introduced,
                "selection_reason": "MANDATORY_ANCHOR_OWNER_BRIDGE",
            })

    for path in classified:
        if path["selection_tier"] == 1:
            continue
        new_records = []
        for record_id in path["record_id_sequence"]:
            if record_id not in selected_set and record_id not in new_records:
                new_records.append(record_id)
        remaining = max_records - len(selected_set)
        if len(new_records) <= remaining:
            path_rank += 1
            for record_id in new_records:
                introduce(
                    record_id,
                    path["selection_tier"],
                    path["path_id"],
                    f"ATOMIC_PATH_ADMITTED_{path['selection_tier_name']}",
                )
            admitted_paths.append({
                **path,
                "selected_path_rank": path_rank,
                "path_new_record_cost_at_admission": len(new_records),
                "introduced_record_ids": new_records,
                "selection_reason": (
                    "PROVENANCE_ONLY_ZERO_COST_PATH_ADMITTED"
                    if not new_records else f"ATOMIC_PATH_ADMITTED_{path['selection_tier_name']}"
                ),
            })
        else:
            tags = ["LOWER_TIE_BREAK_ORDER"]
            if path["selection_tier"] == 5:
                tags.extend(["LOWER_SEMANTIC_TIER_BUDGET_EXHAUSTED", "CONTEXT_AFTER_BACKBONE_BUDGET_EXHAUSTED"])
            budget_drops.append({
                "entry_type": "PATH",
                "case_id": case_id,
                "path_id": path["path_id"],
                "semantic_family": path["semantic_family"],
                "selection_tier": path["selection_tier"],
                "selection_tier_name": path["selection_tier_name"],
                "record_id_sequence": path["record_id_sequence"],
                "primary_drop_reason": "ATOMIC_PATH_DOES_NOT_FIT_REMAINING_BUDGET",
                "structural_tags": tags,
                "path_new_record_cost_at_decision": len(new_records),
                "remaining_budget_at_decision": remaining,
                "records_not_partially_admitted": new_records,
            })

    if len(selected_order) != len(selected_set) or len(selected_order) > max_records:
        raise SelectionPolicyError(f"selected set invariant failed: {case_id}")
    admitted_ids = {path["path_id"] for path in admitted_paths}
    selected_record_rows = []
    for rank, record_id in enumerate(selected_order, start=1):
        record = record_by_id[record_id]
        supporting = record["all_supporting_path_ids"]
        transition_paths = []
        root_associations = set()
        involved_classes = set()
        all_path_classes = set()
        for path_id in supporting:
            path = paths_by_id[path_id]
            root_associations.add((path["anchor_record_id"], path["root_index"]))
            involved_classes.update(path["transition_class_sequence"])
            selector_path_class = (
                canonical_by_id[path_id]["selection_tier_name"]
                if path_id in canonical_by_id else "REDUNDANT_PREFIX"
            )
            all_path_classes.add(selector_path_class)
            transition_paths.append({
                "path_id": path_id,
                "semantic_family": _semantic_family(path),
                "selector_path_class": selector_path_class,
                "canonicalization_status": (
                    "REDUNDANT_PREFIX" if path_id in redundant_ids else "CANONICAL"
                ),
                "transition_id_sequence": path["transition_id_sequence"],
                "transition_class_sequence": path["transition_class_sequence"],
                "relation_id_sequence": path["relation_id_sequence"],
                "direction_sequence": path["direction_sequence"],
                "edge_id_sequence": path["edge_id_sequence"],
                "provenance_record_id_sequence": path["provenance_record_id_sequence"],
            })
        if record_id in roots:
            root_associations.add((record_id, roots.index(record_id)))
        selected_record_rows.append({
            "case_id": case_id,
            "record_id": record_id,
            "selected_record_rank": rank,
            **first_selection[record_id],
            "node_type": record["node_type"],
            "minimum_reachable_depth": record["minimum_reachable_depth"],
            "all_supporting_path_ids": supporting,
            "admitted_supporting_path_ids": sorted(set(supporting) & admitted_ids),
            "all_transition_paths": sorted(transition_paths, key=lambda value: value["path_id"]),
            "all_path_classes": sorted(all_path_classes),
            "transition_classes_involved": sorted(involved_classes, key=lambda value: CLASS_RANK[value]),
            "anchor_root_associations": [
                {"anchor_record_id": anchor, "root_index": index}
                for anchor, index in sorted(root_associations)
            ],
        })

    dropped_ids = sorted(set(record_by_id) - selected_set)
    record_drops = []
    for record_id in dropped_ids:
        record = record_by_id[record_id]
        eligible_paths = [canonical_by_id[path_id] for path_id in record["all_supporting_path_ids"] if path_id in canonical_by_id]
        best_tier = min((path["selection_tier"] for path in eligible_paths), default=None)
        path_reasons = []
        budget_by_id = {row["path_id"]: row for row in budget_drops}
        redundant_by_id = {row["path_id"]: row for row in redundant}
        for path_id in record["all_supporting_path_ids"]:
            if path_id in budget_by_id:
                reason = budget_by_id[path_id]["primary_drop_reason"]
            elif path_id in redundant_by_id:
                reason = redundant_by_id[path_id]["primary_drop_reason"]
            elif path_id in admitted_ids:
                reason = "ADMITTED_PATH_DID_NOT_INTRODUCE_RECORD_UNEXPECTED"
            else:
                reason = "NONCANONICAL_SUPPORTING_PATH"
            path_reasons.append({"path_id": path_id, "structural_reason": reason})
        primary = (
            "CONTEXT_AFTER_BACKBONE_BUDGET_EXHAUSTED"
            if best_tier == 5 else "LOWER_SEMANTIC_TIER_BUDGET_EXHAUSTED"
        )
        record_drops.append({
            "entry_type": "RECORD",
            "case_id": case_id,
            "record_id": record_id,
            "node_type": record["node_type"],
            "minimum_reachable_depth": record["minimum_reachable_depth"],
            "best_structural_selection_tier": best_tier,
            "best_structural_selection_tier_name": TIER_NAMES.get(best_tier),
            "primary_drop_reason": primary,
            "all_supporting_path_ids": record["all_supporting_path_ids"],
            "all_path_classes": sorted({
                (
                    canonical_by_id[path_id]["selection_tier_name"]
                    if path_id in canonical_by_id else "REDUNDANT_PREFIX"
                )
                for path_id in record["all_supporting_path_ids"]
            }),
            "supporting_path_structural_reasons": path_reasons,
            "diagnostic_attribution_only": True,
        })

    all_drop_paths = sorted(
        [*redundant, *budget_drops],
        key=lambda row: (
            0 if row["primary_drop_reason"] == "REDUNDANT_PREFIX" else 1,
            row.get("selection_tier", 99),
            row["path_id"],
        ),
    )
    selected_tiers = Counter(str(row["selection_tier"]) for row in admitted_paths)
    budget_drop_tiers = Counter(str(row["selection_tier"]) for row in budget_drops)
    selected_record_tiers = Counter(str(row["selection_tier"]) for row in selected_record_rows)
    dropped_record_tiers = Counter(str(row["best_structural_selection_tier"]) for row in record_drops)
    summary = {
        "case_id": case_id,
        "status": "SUCCESS",
        "resolution_status": str(anchor_row["resolution_status"]),
        "mandatory_anchor_record_ids": roots,
        "mandatory_anchor_count": len(roots),
        "mandatory_owner_record_ids": owner_records,
        "candidate_path_count": len(paths),
        "redundant_prefix_path_count": len(redundant),
        "canonical_path_count": len(classified),
        "selected_path_count": len(admitted_paths),
        "dropped_path_count": len(all_drop_paths),
        "budget_rejected_path_count": len(budget_drops),
        "candidate_record_count": len(records),
        "selected_record_count": len(selected_order),
        "dropped_record_count": len(record_drops),
        "selected_record_ids": selected_order,
        "selected_path_ids": [row["path_id"] for row in admitted_paths],
        "selected_path_count_by_tier": dict(sorted(selected_tiers.items())),
        "budget_rejected_path_count_by_tier": dict(sorted(budget_drop_tiers.items())),
        "selected_record_count_by_tier": dict(sorted(selected_record_tiers.items())),
        "dropped_record_count_by_tier": dict(sorted(dropped_record_tiers.items())),
        "all_mandatory_anchors_selected": set(roots) <= selected_set,
        "all_mandatory_owner_bridges_selected": set(owner_records) <= selected_set,
        "all_mandatory_owner_paths_selected": {
            path["path_id"] for path in owner_paths
        } <= admitted_ids,
        "partial_atomic_path_admission_count": 0,
        "maximum_selected_records": max_records,
        "budget_pressure_applied": bool(budget_drops),
    }
    return SelectionCaseResult(
        case_id=case_id,
        selected_paths=tuple(admitted_paths),
        selected_records=tuple(selected_record_rows),
        path_drop_ledger=tuple(all_drop_paths),
        record_drop_ledger=tuple(record_drops),
        summary=summary,
    )


def select_all(
    policy: Mapping[str, Any],
    grammar: Mapping[str, Any],
    relation_order: Mapping[str, int],
    anchor_rows: Iterable[Mapping[str, Any]],
    candidate_paths: Iterable[Mapping[str, Any]],
    candidate_records: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    anchor_list = list(anchor_rows)
    anchors = {str(row["case_id"]): row for row in anchor_list}
    if len(anchors) != len(anchor_list):
        raise SelectionPolicyError("duplicate anchor-resolution case ID")
    paths_by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    records_by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in candidate_paths:
        paths_by_case[str(row["case_id"])].append(row)
    for row in candidate_records:
        records_by_case[str(row["case_id"])].append(row)
    if not set(paths_by_case) <= set(anchors) or set(anchors) != set(records_by_case):
        raise SelectionPolicyError("anchor/path/record case universes differ")
    outputs = {
        "selected_paths": [],
        "selected_records": [],
        "path_drop_ledger": [],
        "record_drop_ledger": [],
        "case_results": [],
    }
    for case_id in sorted(anchors):
        result = select_case(
            policy,
            grammar,
            relation_order,
            anchors[case_id],
            paths_by_case[case_id],
            records_by_case[case_id],
        )
        outputs["selected_paths"].extend(result.selected_paths)
        outputs["selected_records"].extend(result.selected_records)
        outputs["path_drop_ledger"].extend(result.path_drop_ledger)
        outputs["record_drop_ledger"].extend(result.record_drop_ledger)
        outputs["case_results"].append(result.summary_dict())
    return outputs
