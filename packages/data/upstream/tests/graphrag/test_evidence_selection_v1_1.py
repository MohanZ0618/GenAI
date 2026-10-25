from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import random
from typing import Any, Iterable, Sequence

import pytest

from src.graphrag.v1_1.evidence_selection import (
    SelectionPolicyError,
    load_policy,
    select_all,
    select_case,
)


ROOT = Path(__file__).resolve().parents[2]
FREEZE_DIR = ROOT / "results/graphrag/evidence_selection_freeze_v1_1"
POLICY_PATH = FREEZE_DIR / "evidence_selection_policy_v1_1_draft.json"
GRAMMAR_PATH = ROOT / "results/graphrag/registry_freeze_v1_1/graph_traversal_grammar_v1_1.json"
RELATIONS_PATH = ROOT / "results/graphrag/registry_freeze_v1/graph_relation_registry_v1.json"

INV_GL = "TR_INVOICE__GL_SOURCE_INVOICE__REVERSE__GL_ENTRY"
INV_ALLOC = "TR_INVOICE__ALLOCATION_TO_INVOICE__REVERSE__PAYMENT_ALLOCATION"
ALLOC_PAYMENT = "TR_PAYMENT_ALLOCATION__ALLOCATION_OF_PAYMENT__FORWARD__PAYMENT"
PAY_GL = "TR_PAYMENT__GL_SOURCE_PAYMENT__REVERSE__GL_ENTRY"
INV_PAY_SUPPORTING = "TR_INVOICE__PAYMENT_ALLOCATED_TO_INVOICE__REVERSE__PAYMENT"
PAY_ALLOC = "TR_PAYMENT__ALLOCATION_OF_PAYMENT__REVERSE__PAYMENT_ALLOCATION"
ALLOC_INV = "TR_PAYMENT_ALLOCATION__ALLOCATION_TO_INVOICE__FORWARD__INVOICE"
INV_AUDIT = "TR_INVOICE__AUDIT_EVENT_FOR_INVOICE__REVERSE__AUDIT_EVENT"
APPROVAL_INV = "TR_APPROVAL_EVENT__APPROVAL_FOR_INVOICE__FORWARD__INVOICE"
GL_INV = "TR_GL_ENTRY__GL_SOURCE_INVOICE__FORWARD__INVOICE"
GL_PAY = "TR_GL_ENTRY__GL_SOURCE_PAYMENT__FORWARD__PAYMENT"


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    return load_policy(POLICY_PATH)


@pytest.fixture(scope="module")
def grammar() -> dict[str, Any]:
    return json.loads(GRAMMAR_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def relation_order() -> dict[str, int]:
    registry = json.loads(RELATIONS_PATH.read_text(encoding="utf-8"))
    return {row["relation_type"]: index for index, row in enumerate(registry["frozen_relations"])}


def _anchor(
    case_id: str,
    roots: Sequence[str],
    *,
    node_type: str = "INVOICE",
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "resolution_status": status or ("EXACT_MULTI" if len(roots) > 1 else "EXACT_SINGLE"),
        "resolved_record_ids": list(roots),
        "resolved_node_types": [node_type],
    }


def _path(
    grammar: dict[str, Any],
    case_id: str,
    path_id: str,
    records: Sequence[str],
    transition_ids: Sequence[str],
    *,
    root_index: int = 0,
    stop_reason: str | None = None,
) -> dict[str, Any]:
    transitions = {row["transition_id"]: row for row in grammar["transitions"]}
    rows = [transitions[value] for value in transition_ids]
    assert len(records) == len(rows) + 1
    node_types = [rows[0]["current_node_type"], *(row["next_node_type"] for row in rows)]
    assert all(rows[index]["next_node_type"] == rows[index + 1]["current_node_type"] for index in range(len(rows) - 1))
    if stop_reason is None:
        last = rows[-1]
        if last["transition_class"] == "TERMINAL_CONTEXT":
            stop_reason = "TERMINAL_CONTEXT_REACHED"
        elif last["terminal_rule"] == "STOP_AFTER_ACCOUNTING_CONSEQUENCE":
            stop_reason = "REACHED_GL_ACCOUNTING_CONSEQUENCE"
        elif len(rows) == 3:
            stop_reason = "MAX_DEPTH_REACHED"
        else:
            stop_reason = "CONTINUATION_ALLOWED_PREFIX"
    edge_ids = [f"EDGE_{path_id}_{index}" for index in range(len(rows))]
    return {
        "case_id": case_id,
        "route_anchor_type": "synthetic_policy_fixture",
        "anchor_record_id": records[0],
        "root_index": root_index,
        "path_id": path_id,
        "depth": len(rows),
        "node_type_sequence": node_types,
        "record_id_sequence": list(records),
        "transition_id_sequence": list(transition_ids),
        "relation_id_sequence": [row["relation_id"] for row in rows],
        "direction_sequence": [row["traversal_direction"] for row in rows],
        "transition_class_sequence": [row["transition_class"] for row in rows],
        "edge_id_sequence": edge_ids,
        "provenance": [
            {
                "edge_id": edge_id,
                "provenance_record_id": f"PROVENANCE_{path_id}_{index}",
                "provenance_record_type": "SYNTHETIC_STRUCTURAL_FIXTURE",
                "provenance_fields": {"fixture": True},
            }
            for index, edge_id in enumerate(edge_ids)
        ],
        "terminal_status": stop_reason != "CONTINUATION_ALLOWED_PREFIX",
        "stop_reason": stop_reason,
    }


def _records(
    anchor: dict[str, Any],
    paths: Iterable[dict[str, Any]],
    *,
    root_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    path_rows = list(paths)
    case_id = anchor["case_id"]
    roots = list(anchor["resolved_record_ids"])
    types = dict(root_types or {})
    depths = {record_id: 0 for record_id in roots}
    memberships: dict[str, set[str]] = {record_id: set() for record_id in roots}
    for path in path_rows:
        for depth, (record_id, node_type) in enumerate(zip(path["record_id_sequence"], path["node_type_sequence"])):
            if record_id in types:
                assert types[record_id] == node_type
            types[record_id] = node_type
            depths[record_id] = min(depths.get(record_id, depth), depth)
            memberships.setdefault(record_id, set()).add(path["path_id"])
    default_root_type = anchor["resolved_node_types"][0]
    for root in roots:
        types.setdefault(root, default_root_type)
    return [
        {
            "case_id": case_id,
            "record_id": record_id,
            "node_type": types[record_id],
            "minimum_depth": depths[record_id],
            "is_resolved_anchor": record_id in roots,
            "root_indices": [roots.index(record_id)] if record_id in roots else [],
            "supporting_path_ids": sorted(memberships.get(record_id, set())),
            "source_table": "synthetic_structural_fixture",
            "document_sha256": f"sha256-{record_id}",
        }
        for record_id in sorted(types)
    ]


def _run(policy, grammar, relation_order, anchor, paths, records=None):
    path_rows = list(paths)
    return select_case(
        policy,
        grammar,
        relation_order,
        anchor,
        path_rows,
        list(records) if records is not None else _records(anchor, path_rows),
    )


def _gl_fanout(grammar: dict[str, Any], case_id: str, anchor_id: str, count: int) -> list[dict[str, Any]]:
    return [
        _path(grammar, case_id, f"PATH_GL_{index:03d}", [anchor_id, f"gl_entries:GL_{index:03d}"], [INV_GL])
        for index in range(count)
    ]


def test_anchor_only_selects_the_exact_root(policy, grammar, relation_order):
    anchor = _anchor("CASE_ANCHOR_ONLY", ["invoices:ANCHOR"])
    result = _run(policy, grammar, relation_order, anchor, [])
    assert result.summary["selected_record_ids"] == ["invoices:ANCHOR"]
    assert result.summary["selected_path_count"] == 0
    assert result.selected_records[0]["selection_tier_name"] == "MANDATORY_ANCHOR"
    assert result.selected_records[0]["reason_selected"] == "MANDATORY_EXACT_ANCHOR"


def test_select_all_supports_a_valid_anchor_only_case(policy, grammar, relation_order):
    anchor = _anchor("CASE_ANCHOR_ONLY_BATCH", ["invoices:ANCHOR"])
    records = _records(anchor, [])
    result = select_all(policy, grammar, relation_order, [anchor], [], records)
    assert result["case_results"][0]["selected_record_ids"] == ["invoices:ANCHOR"]
    assert result["selected_paths"] == []


@pytest.mark.parametrize("candidate_record_count", [40, 41, 50, 121])
def test_budget_boundaries_and_arbitrary_large_fanout(
    policy, grammar, relation_order, candidate_record_count
):
    case_id = f"CASE_COUNT_{candidate_record_count}"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    paths = _gl_fanout(grammar, case_id, root, candidate_record_count - 1)
    result = _run(policy, grammar, relation_order, anchor, paths)
    expected_count = min(candidate_record_count, 40)
    assert result.summary["selected_record_count"] == expected_count
    assert result.summary["dropped_record_count"] == candidate_record_count - expected_count
    assert result.summary["all_mandatory_anchors_selected"] is True
    assert result.summary["partial_atomic_path_admission_count"] == 0
    assert len({row["record_id"] for row in result.selected_records}) == expected_count
    assert result.selected_records[0]["record_id"] == root


def test_exact_multi_keeps_all_roots_and_merges_paths_by_semantics(
    policy, grammar, relation_order
):
    case_id = "CASE_EXACT_MULTI"
    roots = ["gl_entries:ROOT_A", "gl_entries:ROOT_Z"]
    anchor = _anchor(case_id, roots, node_type="GL_ENTRY", status="EXACT_MULTI")
    paths = [
        _path(grammar, case_id, "PATH_ROOT_A_LIFECYCLE", [roots[0], "invoices:FROM_A"], [GL_INV], root_index=0),
        _path(
            grammar,
            case_id,
            "PATH_ROOT_Z_ACCOUNTING",
            [roots[1], "payments:FROM_Z", "gl_entries:CONSEQUENCE"],
            [GL_PAY, PAY_GL],
            root_index=1,
        ),
    ]
    result = _run(policy, grammar, relation_order, anchor, paths)
    assert result.summary["mandatory_anchor_record_ids"] == sorted(roots)
    assert result.summary["selected_record_ids"][:2] == sorted(roots)
    assert result.summary["selected_path_ids"] == ["PATH_ROOT_Z_ACCOUNTING", "PATH_ROOT_A_LIFECYCLE"]
    assert result.summary["all_mandatory_anchors_selected"] is True


def test_redundant_backbone_prefix_is_suppressed_without_losing_record_provenance(
    policy, grammar, relation_order
):
    case_id = "CASE_PREFIX"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    prefix = _path(grammar, case_id, "PATH_PREFIX", [root, "allocations:A"], [INV_ALLOC])
    maximal = _path(
        grammar,
        case_id,
        "PATH_MAXIMAL",
        [root, "allocations:A", "payments:P"],
        [INV_ALLOC, ALLOC_PAYMENT],
    )
    # Persisted traversal prefixes and their extensions share exact edge identity.
    maximal["edge_id_sequence"][0] = prefix["edge_id_sequence"][0]
    maximal["provenance"][0]["edge_id"] = prefix["edge_id_sequence"][0]
    result = _run(policy, grammar, relation_order, anchor, [prefix, maximal])
    assert result.summary["selected_path_ids"] == ["PATH_MAXIMAL"]
    assert result.path_drop_ledger[0]["path_id"] == "PATH_PREFIX"
    assert result.path_drop_ledger[0]["primary_drop_reason"] == "REDUNDANT_PREFIX"
    allocation = next(row for row in result.selected_records if row["record_id"] == "allocations:A")
    assert allocation["all_supporting_path_ids"] == ["PATH_MAXIMAL", "PATH_PREFIX"]


def test_complete_gl_backbone_precedes_supporting_overlap_and_deduplicates(
    policy, grammar, relation_order
):
    case_id = "CASE_BACKBONE_SUPPORTING"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    backbone = _path(
        grammar,
        case_id,
        "PATH_COMPLETE_BACKBONE",
        [root, "allocations:A", "payments:P", "gl_entries:G"],
        [INV_ALLOC, ALLOC_PAYMENT, PAY_GL],
    )
    supporting = _path(
        grammar,
        case_id,
        "PATH_SUPPORTING",
        [root, "payments:P"],
        [INV_PAY_SUPPORTING],
    )
    result = _run(policy, grammar, relation_order, anchor, [supporting, backbone])
    assert result.summary["selected_path_ids"] == ["PATH_COMPLETE_BACKBONE", "PATH_SUPPORTING"]
    assert [row["selection_tier"] for row in result.selected_paths] == [2, 4]
    assert result.selected_paths[1]["path_new_record_cost_at_admission"] == 0
    payment = next(row for row in result.selected_records if row["record_id"] == "payments:P")
    assert payment["all_supporting_path_ids"] == ["PATH_COMPLETE_BACKBONE", "PATH_SUPPORTING"]
    assert len({row["record_id"] for row in result.selected_records}) == len(result.selected_records)


def test_backbone_and_gl_survive_before_many_terminal_context_records(
    policy, grammar, relation_order
):
    case_id = "CASE_CONTEXT_PRESSURE"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    backbone = _path(
        grammar,
        case_id,
        "PATH_COMPLETE_BACKBONE",
        [root, "allocations:A", "payments:P", "gl_entries:G"],
        [INV_ALLOC, ALLOC_PAYMENT, PAY_GL],
    )
    contexts = [
        _path(grammar, case_id, f"PATH_CONTEXT_{index:03d}", [root, f"audit_events:E_{index:03d}"], [INV_AUDIT])
        for index in range(60)
    ]
    result = _run(policy, grammar, relation_order, anchor, [*reversed(contexts), backbone])
    assert result.summary["selected_record_count"] == 40
    assert result.summary["selected_path_ids"][0] == "PATH_COMPLETE_BACKBONE"
    assert {"allocations:A", "payments:P", "gl_entries:G"} <= set(result.summary["selected_record_ids"])
    assert result.summary["budget_rejected_path_count_by_tier"] == {"5": 24}
    assert all(row["primary_drop_reason"] == "CONTEXT_AFTER_BACKBONE_BUDGET_EXHAUSTED" for row in result.record_drop_ledger)


def test_overlap_allows_path_costing_one_new_slot(policy, grammar, relation_order):
    case_id = "CASE_ONE_SLOT"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    higher = _gl_fanout(grammar, case_id, root, 36)
    lifecycle = _path(
        grammar,
        case_id,
        "PATH_LIFECYCLE",
        [root, "allocations:A", "payments:SHARED"],
        [INV_ALLOC, ALLOC_PAYMENT],
    )
    overlap = _path(
        grammar,
        case_id,
        "PATH_ONE_NEW_SLOT",
        [root, "payments:SHARED", "gl_entries:NEW"],
        [INV_PAY_SUPPORTING, PAY_GL],
    )
    result = _run(policy, grammar, relation_order, anchor, [overlap, lifecycle, *higher])
    admitted = next(row for row in result.selected_paths if row["path_id"] == "PATH_ONE_NEW_SLOT")
    assert admitted["path_new_record_cost_at_admission"] == 1
    assert admitted["introduced_record_ids"] == ["gl_entries:NEW"]
    assert result.summary["selected_record_count"] == 40


def test_three_new_records_are_atomically_rejected_with_two_slots_left(
    policy, grammar, relation_order
):
    case_id = "CASE_ATOMIC_REJECTION"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    higher = _gl_fanout(grammar, case_id, root, 37)
    nonfitting = _path(
        grammar,
        case_id,
        "PATH_THREE_NEW",
        [root, "payments:NEW", "allocations:NEW", "invoices:NEW"],
        [INV_PAY_SUPPORTING, PAY_ALLOC, ALLOC_INV],
    )
    result = _run(policy, grammar, relation_order, anchor, [nonfitting, *higher])
    drop = next(row for row in result.path_drop_ledger if row["path_id"] == "PATH_THREE_NEW")
    assert drop["path_new_record_cost_at_decision"] == 3
    assert drop["remaining_budget_at_decision"] == 2
    assert set(drop["records_not_partially_admitted"]) == {
        "payments:NEW", "allocations:NEW", "invoices:NEW"
    }
    assert not set(drop["records_not_partially_admitted"]) & set(result.summary["selected_record_ids"])
    assert result.summary["selected_record_count"] == 38
    assert result.summary["partial_atomic_path_admission_count"] == 0


def test_all_candidates_below_cap_fit(policy, grammar, relation_order):
    case_id = "CASE_ALL_FIT"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    paths = _gl_fanout(grammar, case_id, root, 16)
    result = _run(policy, grammar, relation_order, anchor, paths)
    assert result.summary["candidate_record_count"] == 17
    assert result.summary["selected_record_count"] == 17
    assert result.summary["dropped_record_count"] == 0
    assert result.summary["budget_pressure_applied"] is False


def test_context_anchor_owner_bridge_is_mandatory(policy, grammar, relation_order):
    case_id = "CASE_OWNER_BRIDGE"
    root = "approval_events:ANCHOR"
    anchor = _anchor(case_id, [root], node_type="APPROVAL_EVENT")
    bridge = _path(grammar, case_id, "PATH_OWNER", [root, "invoices:OWNER"], [APPROVAL_INV])
    result = _run(policy, grammar, relation_order, anchor, [bridge])
    assert result.summary["mandatory_owner_record_ids"] == ["invoices:OWNER"]
    assert result.summary["all_mandatory_owner_bridges_selected"] is True
    assert result.selected_records[1]["selection_tier_name"] == "ANCHOR_OWNER_BRIDGE"


def test_forbidden_signal_fields_cannot_change_membership_or_order(
    policy, grammar, relation_order
):
    case_id = "CASE_POISONED_SIGNALS"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    paths = _gl_fanout(grammar, case_id, root, 45)
    records = _records(anchor, paths)
    baseline = _run(policy, grammar, relation_order, anchor, paths, records).to_dict()
    poisoned_paths = deepcopy(paths)
    poisoned_records = deepcopy(records)
    for index, row in enumerate(poisoned_paths):
        row.update({
            "validation_gold_member": index % 2 == 0,
            "RCA_label": f"FORBIDDEN_{45 - index}",
            "embedding_similarity": float(45 - index),
            "model_score": -float(index),
            "token_count": 100_000 - index,
            "record_text": f"forbidden text {index}",
        })
    for index, row in enumerate(poisoned_records):
        row.update({
            "required_evidence_id": index % 2 == 1,
            "embedding": [float(index)],
            "LLM_score": 1_000_000 - index,
            "token_length": index,
            "expected_answer": f"FORBIDDEN_{index}",
        })
    poisoned = _run(
        policy, grammar, relation_order, anchor, poisoned_paths, poisoned_records
    ).to_dict()
    assert poisoned == baseline
    serialized = json.dumps(poisoned, sort_keys=True)
    assert not any(
        field in serialized
        for field in (
            "validation_gold_member", "RCA_label", "embedding_similarity",
            "model_score", "token_count", "record_text", "required_evidence_id",
            "embedding", "LLM_score", "token_length", "expected_answer",
        )
    )


def test_shuffled_candidate_input_is_byte_semantically_deterministic(
    policy, grammar, relation_order
):
    case_id = "CASE_SHUFFLE"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    paths = [
        *_gl_fanout(grammar, case_id, root, 42),
        _path(grammar, case_id, "PATH_CONTEXT", [root, "audit_events:E"], [INV_AUDIT]),
        _path(
            grammar,
            case_id,
            "PATH_SUPPORTING",
            [root, "payments:P"],
            [INV_PAY_SUPPORTING],
        ),
    ]
    records = _records(anchor, paths)
    first = _run(policy, grammar, relation_order, anchor, paths, records).to_dict()
    shuffled_paths = deepcopy(paths)
    shuffled_records = deepcopy(records)
    random.Random(81173).shuffle(shuffled_paths)
    random.Random(91283).shuffle(shuffled_records)
    second = _run(policy, grammar, relation_order, anchor, shuffled_paths, shuffled_records).to_dict()
    assert second == first


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transition_id_sequence", ["TR_SYNTHETIC_PAYMENT_BANK"]),
        ("relation_id_sequence", ["PAYMENT_CANDIDATE_BANK_TRANSACTION"]),
        ("node_type_sequence", ["INVOICE", "GL_JOURNAL"]),
        ("node_type_sequence", ["INVOICE", "VENDOR"]),
        ("node_type_sequence", ["INVOICE", "EMPLOYEE"]),
    ],
)
def test_unregistered_or_forbidden_transition_metadata_fails_closed(
    policy, grammar, relation_order, field, value
):
    case_id = f"CASE_FORBIDDEN_{value[-1]}"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    path = _path(grammar, case_id, "PATH_INVALID", [root, "gl_entries:G"], [INV_GL])
    path[field] = value
    records = _records(anchor, [path], root_types={root: "INVOICE"})
    with pytest.raises(SelectionPolicyError):
        _run(policy, grammar, relation_order, anchor, [path], records)


def test_missing_root_and_out_of_pool_path_record_fail_closed(policy, grammar, relation_order):
    case_id = "CASE_MISSING_POOL"
    root = "invoices:ANCHOR"
    anchor = _anchor(case_id, [root])
    path = _path(grammar, case_id, "PATH_GL", [root, "gl_entries:G"], [INV_GL])
    records = _records(anchor, [path])
    with pytest.raises(SelectionPolicyError, match="mandatory root absent"):
        _run(policy, grammar, relation_order, anchor, [path], [row for row in records if row["record_id"] != root])
    with pytest.raises(SelectionPolicyError, match="path record absent"):
        _run(
            policy,
            grammar,
            relation_order,
            anchor,
            [path],
            [row for row in records if row["record_id"] != "gl_entries:G"],
        )


def test_more_than_40_exact_roots_fails_instead_of_collapsing_or_partial_selection(
    policy, grammar, relation_order
):
    roots = [f"gl_entries:ROOT_{index:03d}" for index in range(41)]
    anchor = _anchor("CASE_MANDATORY_OVERFLOW", roots, node_type="GL_ENTRY", status="EXACT_MULTI")
    records = _records(anchor, [], root_types={root: "GL_ENTRY" for root in roots})
    with pytest.raises(SelectionPolicyError, match="MANDATORY_SET_EXCEEDS_BUDGET"):
        _run(policy, grammar, relation_order, anchor, [], records)
