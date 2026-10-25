"""Immutable Phase 6A paths, expected lineage, and feature flags."""

from __future__ import annotations

from pathlib import Path


PHASE6A_VERSION = "1.0"
RUN_ID = "phase6a_graph_retrieval_v1_0"
CREATED_AT_UTC = "2026-08-13T00:00:00Z"
DECISION_CUTOFF = "2026-06-30"
MAX_RAW_RECORDS = 40

FREEZE_DIR = Path("results/graphrag/registry_freeze_v1")
INDEX_DIR = Path("results/rag/phase5_rag_index_v1_0_20260810T000000Z")
CORPUS_DIR = INDEX_DIR / "corpus"
ROUTES_PATH = Path("results/rag/phase5_rag_validation_routes_v1_0_20260812T040938Z/validation_routes.jsonl")
DENSE_RESULTS_PATH = Path("results/rag/phase5_rag_validation_retrieval_v1_0_20260812T040938Z/retrieval_results.jsonl")
VALIDATION_GOLD_PATH = Path("data/benchmark/validation/rca_ground_truth.jsonl")
OUTPUT_DIR = Path("results/graphrag/phase6a_graph_retrieval_v1_0")

EXPECTED_FREEZE_HASHES = {
    "graph_node_registry_v1.json": "4c17ff5c863ed446418fbc2b3b407704519862feddc5f0c81546c210f8e91d10",
    "graph_relation_registry_v1.json": "f8c61e2117c09921d001c4d476ef80d138f362c2ac084850544fc56077a7b0c3",
    "graph_path_motifs_v1.json": "36dd0b0d491dd6ef5f46c1dcd38cfe5e9e2ab61c632038b89cdc6ed9e0ec58ef",
    "graph_ranking_policy_v1.json": "85a167767f6147c2a51db9cdab47d7157731bb2126ca2cf2c452f4e9bde602f0",
    "graph_freeze_manifest_v1.json": "8097eb64accec2c076d07ed9ae4604d2202d1ca83578cf8557b40f034b7cad76",
    "graph_freeze_hashes_v1.json": "7a43c7802f2b89781ccc3bead7f5f5fed501d2fe5e5706addaed30e02966db70",
    "GRAPH_RAG_REGISTRY_FREEZE_REVIEW.md": "566736f0d14b238679c78d366b393f341f293531446632b21e6d9e14f1a270c3",
}
EXPECTED_PHASE5 = {
    "index_manifest_sha256": "527b5980f1544dda5eab4581f8cb9c498e2a8e7633e4c061dd232b8cff05e3a6",
    "text_manifest_sha256": "8842865bd6e688f824a0b16450301fb547c62c4ba495099d605753ebaf2ff00d",
    "documents.jsonl": "43fe8841d3cbfc64c403349c2336c631c9f6ca9dc35f3e86af1c4ae993441b8c",
    "metadata.jsonl": "e30183ea1e17af182ad24a3177e776a869ed55718872ba6cc1a169506b4f96fb",
    "record_ids.txt": "1850249832dbb9c75ddddfa8e82615dd1db138cdd83cb2dc455029035e1b0058",
    "document_count": 155391,
    "vector_count": 155391,
    "dimensions": 1536,
}
EXPECTED_ROUTE_SHA256 = "08ceeaf3a7c569ca94a87b0c0830d0fb90784daac66dd959de3fee1561b94b44"
EXPECTED_DENSE_SHA256 = "3eaae4b34b2dbe3ae0a3cd13980a69421737f2a9194c72e77077a352bc28b372"

FEATURE_FLAGS = {
    "payment_bank_enabled": False,
    "synthetic_gl_journal_enabled": False,
    "conditional_employee_edges_enabled": False,
    "tier_b_enabled": False,
    "semantic_fallback_enabled": False,
    "unrestricted_bfs_enabled": False,
    "llm_enabled": False,
}
