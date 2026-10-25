from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.graphrag.v1_1.candidate_traversal import (
    CandidateTraversalEngine,
    FrozenGraph,
    candidate_path_id,
    load_jsonl,
)
from src.graphrag.v1_1.preflight import (
    EvidenceSelectionBlocked,
    assess_ranking_compatibility,
    select_top40,
)
from src.graphrag.v1_1.typed_grammar_loader import load_verified_grammar


ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "results/rag/phase5_rag_validation_routes_v1_0_20260812T040938Z/validation_routes.jsonl"


@pytest.fixture(scope="module")
def bundle():
    return load_verified_grammar(ROOT)


@pytest.fixture(scope="module")
def graph():
    return FrozenGraph.load(ROOT)[0]


@pytest.fixture(scope="module")
def engine(graph, bundle):
    return CandidateTraversalEngine(graph, bundle)


def _transition(bundle, transition_id: str):
    return next(row for row in bundle.transitions if row["transition_id"] == transition_id)


def _edge_for_transition(graph, transition):
    mapping = graph.forward if transition["traversal_direction"] == "FORWARD" else graph.reverse
    for (record_id, relation_id), edges in mapping.items():
        if relation_id == transition["relation_id"] and graph.nodes[record_id]["node_type"] == transition["current_node_type"]:
            edge = dict(edges[0])
            next_id = graph.next_record_id(edge, transition["traversal_direction"])
            return record_id, next_id, edge
    raise AssertionError("no persisted edge found for frozen transition")


def test_freeze_hash_verification_and_grammar_counts(bundle):
    assert bundle.input_verification["status"] == "PASS"
    assert bundle.grammar["transition_count"] == 30
    assert bundle.grammar["transition_count_by_class"] == {
        "BACKBONE": 18,
        "CONTEXT": 5,
        "SUPPORTING": 2,
        "TERMINAL_CONTEXT": 5,
    }
    assert bundle.grammar["relation_type_count"] == 15


def test_default_deny_and_forbidden_node_types(engine):
    assert engine.transitions_by_current.get("VENDOR", ()) == ()
    assert engine.transitions_by_current.get("EMPLOYEE", ()) == ()
    assert engine.transitions_by_current.get("BANK_STATEMENT", ()) == ()
    assert engine.transitions_by_current.get("VENDOR_CHANGE", ()) == ()
    assert "GL_JOURNAL" not in engine.transitions_by_current
    assert all(row["relation_id"] != "PAYMENT_CANDIDATE_BANK_TRANSACTION" for row in engine.transitions.values())


def test_forbidden_registry_covers_required_negative_patterns(bundle):
    ids = {row["forbidden_id"] for row in bundle.forbidden["forbidden_patterns"]}
    assert {
        "FT_DEFAULT_DENY_BFS", "FT_DEPTH_GT_3", "FT_REPEATED_RECORD",
        "FT_VENDOR_BRIDGE", "FT_EMPLOYEE_BRIDGE", "FT_PAYMENT_BANK",
        "FT_SAME_AMOUNT", "FT_SAME_DATE", "FT_SAME_CURRENCY",
        "FT_SEMANTIC_SIMILARITY", "FT_SYNTHETIC_GL_JOURNAL",
        "FT_POST_CUTOFF", "FT_PROVENANCE_MISSING",
    } <= ids


def test_hop_position_depth_context_and_gl_termination(bundle):
    context = _transition(bundle, "TR_APPROVAL_EVENT__APPROVAL_FOR_INVOICE__FORWARD__INVOICE")
    terminal_context = _transition(bundle, "TR_INVOICE__APPROVAL_FOR_INVOICE__REVERSE__APPROVAL_EVENT")
    reached_gl = _transition(bundle, "TR_INVOICE__GL_SOURCE_INVOICE__REVERSE__GL_ENTRY")
    gl_anchor_exit = _transition(bundle, "TR_GL_ENTRY__GL_SOURCE_INVOICE__FORWARD__INVOICE")
    assert CandidateTraversalEngine._transition_allowed(context, 1)
    assert not CandidateTraversalEngine._transition_allowed(context, 2)
    assert not CandidateTraversalEngine._transition_allowed(context, 4)
    assert terminal_context["may_continue_after_transition"] is False
    assert reached_gl["may_continue_after_transition"] is False
    assert CandidateTraversalEngine._transition_allowed(gl_anchor_exit, 1)
    assert not CandidateTraversalEngine._transition_allowed(gl_anchor_exit, 2)


def test_exact_edge_direction_type_and_cycle_checks(engine, graph, bundle):
    transition = _transition(bundle, "TR_INVOICE__INVOICE_REFERENCES_PO__FORWARD__PURCHASE_ORDER")
    current, next_id, edge = _edge_for_transition(graph, transition)
    assert engine._edge_rejection(transition, edge, current, next_id, (current,)) is None
    assert engine._edge_rejection(transition, edge, current, next_id, (current, next_id)) == "SIMPLE_PATH_VIOLATION"
    bad_direction = {**edge, "traversable": False}
    assert engine._edge_rejection(transition, bad_direction, current, next_id, (current,)) == "DIRECTION_NOT_EXECUTABLE"
    bad_type = {**edge, "target_node_type": "PAYMENT"}
    assert engine._edge_rejection(transition, bad_type, current, next_id, (current,)) == "EXACT_TYPE_MISMATCH"


def test_temporal_and_provenance_rejection(engine, graph, bundle):
    transition = _transition(bundle, "TR_INVOICE__INVOICE_REFERENCES_PO__FORWARD__PURCHASE_ORDER")
    current, next_id, edge = _edge_for_transition(graph, transition)
    post_cutoff = {**edge, "effective_available_at": "2026-07-01T00:00:00", "temporal_eligible": False}
    assert engine._edge_rejection(transition, post_cutoff, current, next_id, (current,)) == "TEMPORAL_INELIGIBILITY"
    no_provenance = {**edge, "provenance_fields": {}}
    assert engine._edge_rejection(transition, no_provenance, current, next_id, (current,)) == "PROVENANCE_MISSING"


def test_multiplicity_is_not_collapsed(engine):
    transition = engine.transitions["TR_INVOICE__GL_SOURCE_INVOICE__REVERSE__GL_ENTRY"]
    assert engine.graph.transition_global_maximum(transition) == 8
    assert transition["multiplicity_policy"]["transition_local_cap"] is None


def test_candidate_path_id_is_deterministic():
    arguments = (
        "CASE", "invoices:INV", ["TR_A"], ["invoices:INV", "payments:PAY"], ["EDGE_1"]
    )
    assert candidate_path_id(*arguments) == candidate_path_id(*arguments)
    assert candidate_path_id(*arguments).startswith("GRAMMAR_DIAG_PATH_")


def test_ranking_preflight_blocks_selection_and_gold(bundle):
    compatibility = assess_ranking_compatibility(bundle)
    assert compatibility.status == "BLOCKED_AMBIGUOUS"
    assert not compatibility.selection_implementation_authorized
    assert not compatibility.gold_evaluation_authorized
    assert sum(row["status"] == "AMBIGUOUS" for row in compatibility.findings) >= 6
    with pytest.raises(EvidenceSelectionBlocked):
        select_top40([])


def test_complete_candidate_traversal_and_dedup(engine):
    routes = load_jsonl(ROUTES)
    run = engine.run(routes)
    assert len(run.anchor_resolutions) == 416
    assert sum(len(row["resolved_record_ids"]) for row in run.anchor_resolutions) == 430
    assert len(run.candidate_paths) == 13371
    assert run.telemetry["paths_by_exact_depth"] == {"1": 3332, "2": 4477, "3": 5562}
    assert run.telemetry["candidate_path_set_sha256"] == "89d7f799f60149a8e6665bf59a484131f450ec2ab435e9a891e1eec3efbb2944"
    assert len(run.candidate_records) == 8369
    assert len({(row["case_id"], row["record_id"]) for row in run.candidate_records}) == 8369
    assert all(row["supporting_path_ids"] == sorted(set(row["supporting_path_ids"])) for row in run.candidate_records)
    assert run.telemetry["accepted_post_cutoff_traversal_count"] == 0
    assert run.telemetry["vendor_or_employee_accepted_entry_count"] == 0
    assert len(run.telemetry["not_present_in_accepted_paths_transition_ids"]) == 8
    assert all(row["retrieval_status"] == "SELECTION_FAILURE" for row in run.case_results)


def test_retriever_module_has_no_gold_evaluator_dependency():
    source_paths = [
        ROOT / "src/graphrag/v1_1/typed_grammar_loader.py",
        ROOT / "src/graphrag/v1_1/candidate_traversal.py",
        ROOT / "src/graphrag/v1_1/preflight.py",
    ]
    import_lines = [
        line.strip()
        for path in source_paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("validation_evaluator" in line or "validation" in line and "v1_1" not in line for line in import_lines)


def test_runner_freezes_candidates_before_gold_by_construction():
    source = (ROOT / "src/graphrag/v1_1/runner.py").read_text(encoding="utf-8")
    assert '"FROZEN_BEFORE_GOLD_EVALUATION": True' in source
    assert '"validation_gold_opened": False' in source
    assert "validation_evaluator" not in "\n".join(
        line for line in source.splitlines() if line.strip().startswith(("import ", "from "))
    )
