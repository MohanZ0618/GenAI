from __future__ import annotations

from dataclasses import replace

import pytest

from src.graphrag.anchor_resolver import ExactAnchorResolver
from src.graphrag.config import CORPUS_DIR, FEATURE_FLAGS
from src.graphrag.evidence_selector import select_paths_and_records
from src.graphrag.graph_builder import construct_graph, validate_graph
from src.graphrag.graph_types import GraphEdge, GraphNode, GraphSnapshot
from src.graphrag.motif_engine import FrozenMotifEngine, TraversalRejected
from src.graphrag.path_ranker import FrozenPathRanker
from src.graphrag.registry_loader import load_frozen_registries
from src.rag.corpus import load_persisted_corpus


@pytest.fixture(scope="session")
def registries():
    return load_frozen_registries()


@pytest.fixture(scope="session")
def corpus():
    return load_persisted_corpus(CORPUS_DIR)


@pytest.fixture(scope="session")
def graph(corpus, registries):
    return construct_graph(corpus, registries)


def test_registry_loading_and_hash_verification(registries) -> None:
    assert registries.node["node_type_count"] == 14
    assert registries.relation["frozen_relation_count"] == 22
    assert registries.motifs["frozen_path_motif_count"] == 8
    assert len(registries.hashes) == 7


def test_node_canonicalization_and_snapshot_counts(graph) -> None:
    assert len(graph.snapshot.nodes) == 155_391
    assert len(graph.snapshot.edges) == 184_223
    assert "GL_JOURNAL" not in {node.node_type for node in graph.snapshot.nodes.values()}
    assert len(set(graph.snapshot.nodes)) == len(graph.snapshot.nodes)


def test_exact_relation_materialization_and_provenance(graph, corpus) -> None:
    documents = {document.record_id: document for document in corpus.documents}
    relation = next(edge for edge in graph.snapshot.edges if edge.relation_type == "LINE_OF_PO")
    assert documents[relation.source_record_id].row["po_id"] == documents[relation.target_record_id].row["po_id"]
    assert relation.provenance_record_id == relation.source_record_id
    assert graph.integrity["relations"]["LINE_OF_PO"]["unresolved_exact_reference_count"] == 0


def test_payment_invoice_requires_allocation_provenance(graph, corpus) -> None:
    documents = {document.record_id: document for document in corpus.documents}
    edge = next(edge for edge in graph.snapshot.edges if edge.relation_type == "PAYMENT_ALLOCATED_TO_INVOICE")
    provenance = documents[edge.provenance_record_id]
    assert provenance.record_type == "PAYMENT_ALLOCATION"
    assert documents[edge.source_record_id].row["payment_id"] == provenance.row["payment_id"]
    assert documents[edge.target_record_id].row["invoice_id"] == provenance.row["invoice_id"]


def test_temporal_cutoff_is_enforced(graph, registries) -> None:
    edge = graph.snapshot.edges[0]
    bad = replace(edge, temporal_eligible=False)
    with pytest.raises(RuntimeError, match="GRAPH CONSTRUCTION FAILED"):
        validate_graph(list(graph.snapshot.nodes.values()), [bad, *graph.snapshot.edges[1:]], {
            key: {
                "populated_reference_count": value["populated_reference_count"],
                "resolved_edge_count": value["resolved_edge_count"],
                "unresolved_exact_reference_count": value["unresolved_exact_reference_count"],
                "unresolved_examples": value["unresolved_examples"],
            } for key, value in graph.integrity["relations"].items()
        }, registries)


def test_gl_transaction_type_resolution_is_exact_and_typed(graph, corpus, registries) -> None:
    documents = {document.record_id: document for document in corpus.documents}
    definitions = {row["relation_type"]: row for row in registries.relation["frozen_relations"]}
    for edge in graph.snapshot.edges:
        if not edge.relation_type.startswith("GL_SOURCE_"):
            continue
        source = documents[edge.source_record_id]
        target = documents[edge.target_record_id]
        definition = definitions[edge.relation_type]
        assert source.row["transaction_type"] in definition["constraints"]["permitted_transaction_types"]
        assert source.row["source_transaction_id"] in target.row.values()
        assert target.record_type == definition["target_node_type"]


def test_audit_event_resolution_is_exact_and_typed(graph, corpus, registries) -> None:
    documents = {document.record_id: document for document in corpus.documents}
    definitions = {row["relation_type"]: row for row in registries.relation["frozen_relations"]}
    for edge in graph.snapshot.edges:
        if not edge.relation_type.startswith("AUDIT_EVENT_FOR_"):
            continue
        source = documents[edge.source_record_id]
        target = documents[edge.target_record_id]
        definition = definitions[edge.relation_type]
        assert source.row["entity_type"] in definition["constraints"]["permitted_entity_types"]
        assert source.row["entity_id"] in target.row.values()


def test_vendor_and_employee_hub_restrictions(graph, registries) -> None:
    engine = FrozenMotifEngine(graph.snapshot, registries)
    for node_type in ("VENDOR", "EMPLOYEE"):
        node = next(node for node in graph.snapshot.nodes.values() if node.node_type == node_type)
        paths, _, _, events = engine.execute("CASE", node.record_id)
        assert paths == []
        assert events and events[0]["hub_expansion_blocked"] is True


def test_exact_anchor_resolution_single_and_gl_multi(corpus) -> None:
    resolver = ExactAnchorResolver(corpus.documents)
    invoice = next(document for document in corpus.documents if document.record_type == "INVOICE")
    single = resolver.resolve({"case_id": "C1", "primary_entity_type": "invoice", "primary_entity_id": invoice.row["invoice_id"]})
    assert single["resolution_status"] == "EXACT_SINGLE"
    gl_entries = [document for document in corpus.documents if document.record_type == "GL_ENTRY"]
    journal_counts = {}
    for document in gl_entries:
        journal_counts[document.row["journal_id"]] = journal_counts.get(document.row["journal_id"], 0) + 1
    journal_id = next(value for value, count in journal_counts.items() if count > 1)
    multi = resolver.resolve({"case_id": "C2", "primary_entity_type": "gl_journal", "primary_entity_id": journal_id})
    assert multi["resolution_status"] == "EXACT_MULTI"
    assert set(multi["resolved_node_types"]) == {"GL_ENTRY"}


def test_motif_matching_directionality_and_path_completeness(graph, registries) -> None:
    edge = next(edge for edge in graph.snapshot.edges if edge.relation_type == "APPROVAL_FOR_INVOICE")
    engine = FrozenMotifEngine(graph.snapshot, registries)
    paths, _, _, _ = engine.execute("CASE", edge.target_record_id)
    matching = [row for row in paths if row["motif_id"] == "INVOICE_APPROVALS" and edge.source_record_id in row["records"]]
    assert matching and all(row["complete_motif"] and row["path_length"] == 1 for row in matching)
    # The serialized motif is reverse-directed; starting at its source does not silently invert it.
    source_paths, _, _, _ = engine.execute("CASE2", edge.source_record_id)
    assert not [row for row in source_paths if row["motif_id"] == "INVOICE_APPROVALS"]


def test_path_ranking_and_deterministic_tie_break(registries) -> None:
    ranker = FrozenPathRanker(registries)
    base = {
        "case_id": "C", "anchor_record_id": "A", "motif_id": "M", "path_length": 1,
        "records": ["A", "Z"], "node_sequence": ["A", "Z"], "edges": [],
        "relation_sequence": ["LINE_OF_PO"], "complete_motif": True, "hub_blocked": False,
        "temporal_valid": True, "traversal_priority": 1,
    }
    ranked = ranker.rank([{**base, "path_id": "P2"}, {**base, "path_id": "P1"}])
    assert [row["path_id"] for row in ranked] == ["P1", "P2"]
    assert [row["candidate_rank"] for row in ranked] == [1, 2]


def test_record_deduplication_path_completeness_and_40_cap() -> None:
    paths = []
    for index in range(45):
        paths.append({"path_id": f"P{index:02d}", "records": ["A", f"R{index:02d}"]})
    selected = select_paths_and_records(["A"], paths, cap=40)
    assert len(selected["selected_record_ids"]) == 40
    assert selected["selected_record_ids"].count("A") == 1
    assert len(selected["selected_path_ids"]) == 39
    assert selected["records_dropped_due_to_40_record_budget"]


def test_negative_payment_bank_and_non_executable_relation(graph, registries) -> None:
    engine = FrozenMotifEngine(graph.snapshot, registries)
    with pytest.raises(TraversalRejected, match="RELATION_NOT_EXECUTABLE"):
        engine.reject_relation("PAYMENT_CANDIDATE_BANK_TRANSACTION")
    assert not registries.motifs["payment_bank_motifs_enabled"]


def test_negative_synthetic_journal_tier_b_semantic_and_generic_search(graph, registries) -> None:
    frozen_types = {row["node_type"] for row in registries.node["node_types"]}
    assert "GL_JOURNAL" not in frozen_types
    assert FEATURE_FLAGS["synthetic_gl_journal_enabled"] is False
    assert FEATURE_FLAGS["tier_b_enabled"] is False
    assert FEATURE_FLAGS["semantic_fallback_enabled"] is False
    assert FEATURE_FLAGS["unrestricted_bfs_enabled"] is False
    assert not hasattr(FrozenMotifEngine, "bfs")
    assert not hasattr(FrozenMotifEngine, "dfs")
    assert not hasattr(FrozenMotifEngine, "semantic_search")


def test_graph_has_no_excluded_or_prohibited_edges(graph, registries) -> None:
    frozen = {row["relation_type"] for row in registries.relation["frozen_relations"]}
    excluded = {row["relation_type"] for row in registries.relation["excluded_relations"]}
    observed = {edge.relation_type for edge in graph.snapshot.edges}
    assert observed == frozen
    assert not observed & excluded
    assert all(edge.temporal_eligible and edge.provenance_record_id for edge in graph.snapshot.edges)
