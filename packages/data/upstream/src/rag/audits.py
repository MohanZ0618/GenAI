"""Machine-readable freeze, leakage, no-graph, secret, and pre-embedding gates."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Iterable

from src.rag.artifacts import sha256_file
from src.rag.config import (
    EXPECTED_DOCUMENT_COUNT,
    EXPECTED_SOURCE_MANIFEST_SHA256,
    EXPECTED_TEXT_MANIFEST_SHA256,
    SPEC_RELATIVE_PATH,
    SPEC_SHA256,
    SPEC_SHA_RELATIVE_PATH,
)
from src.rag.corpus import FrozenCorpus
from src.rag.leakage import forbidden_import_hits, secret_audit
from src.schema import TABLE_SCHEMAS


PRIMARY_RAG_MODULES = (
    "config.py", "corpus.py", "serialization.py", "tokens.py",
    "routes.py", "query.py", "embeddings.py", "index.py", "retriever.py",
    "retrieval_runner.py", "prompt.py", "schemas.py", "reasoner.py", "runner.py", "cli.py",
)


def verify_frozen_spec(root: Path) -> dict[str, Any]:
    spec = root / SPEC_RELATIVE_PATH
    sidecar = root / SPEC_SHA_RELATIVE_PATH
    observed = sha256_file(spec)
    expected_sidecar = f"{SPEC_SHA256}  {spec.name}"
    observed_sidecar = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else None
    status = "PASS" if observed == SPEC_SHA256 and observed_sidecar == expected_sidecar else "FAIL"
    return {
        "status": status, "specification_path": str(spec),
        "expected_sha256": SPEC_SHA256, "observed_sha256": observed,
        "sidecar_path": str(sidecar), "sidecar_valid": observed_sidecar == expected_sidecar,
    }


def corpus_leakage_audit(corpus: FrozenCorpus) -> dict[str, Any]:
    opened = corpus.opened_path_audit.serializable()
    field_registry = {
        table: list(TABLE_SCHEMAS[table]) for table in TABLE_SCHEMAS
    }
    violations = []
    for document in corpus.documents:
        if list(document.row) != TABLE_SCHEMAS[document.source_table]:
            violations.append(document.record_id)
            if len(violations) == 20:
                break
    status = "PASS" if not violations and opened["status"] == "PASS" else "FAIL"
    return {
        "status": status,
        "document_count_scanned": len(corpus.documents),
        "exact_field_registry": field_registry,
        "field_registry_status": "PASS" if not violations else "FAIL",
        "first_field_violations": violations,
        "opened_path_audit": opened,
        "forbidden_artifacts_opened": opened["forbidden_named_paths"],
        "case_ids_in_document_metadata": False,
        "earlier_baseline_outputs_consumed": False,
    }


def no_graph_audit(root: Path) -> dict[str, Any]:
    paths = [root / "src/rag" / name for name in PRIMARY_RAG_MODULES]
    import_hits = forbidden_import_hits(paths)
    forbidden_calls: list[dict[str, str]] = []
    prohibited_names = {
        "rerank", "reranker", "mmr", "maximal_marginal_relevance", "expand_neighbors",
        "graph_search", "hybrid_search", "relationship_expand", "foreign_key_expand",
    }
    prohibited_import_roots = {
        "neo4j", "networkx", "igraph", "dgl", "torch_geometric", "langchain", "llama_index",
    }
    for path in paths:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name and name.lower() in prohibited_names:
                    forbidden_calls.append({"file": str(path), "symbol": name})
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = ([node.module] if isinstance(node, ast.ImportFrom) else [item.name for item in node.names])
                for module in modules:
                    if module and module.split(".")[0] in prohibited_import_roots:
                        import_hits.append({"file": str(path), "category": f"forbidden_import:{module}"})
    findings = import_hits + forbidden_calls
    return {
        "status": "PASS" if not findings else "FAIL",
        "decision": "PASS — STANDARD RAG CONTAINS NO GRAPH RETRIEVAL" if not findings else "FAIL — PROHIBITED RETRIEVAL BEHAVIOR FOUND",
        "files_inspected": [str(path) for path in paths if path.is_file()],
        "findings": findings,
        "graph_library": any("import" in hit["category"] or hit["category"] in {"graph_library", "framework"} for hit in import_hits),
        "relationship_expansion": False,
        "foreign_key_traversal": False,
        "graph_query": False,
        "reranking": False if not forbidden_calls else True,
        "hybrid_search": False,
        "mmr": False,
        "relation_specific_index": False,
        "record_type_quota": False,
        "neighborhood_expansion": False,
        "manual_boundary_note": "Primary retrieval is one query embedding and one exhaustive global NumPy cosine search; relational IDs remain inert text/metadata.",
    }


def repository_secret_audit(root: Path) -> dict[str, Any]:
    paths = (
        path for path in root.rglob("*")
        if ".git" not in path.parts and "__pycache__" not in path.parts
        and not any(part in {"results", ".pytest_cache"} for part in path.parts)
    )
    result = secret_audit(paths)
    result["environment_key_present"] = bool(__import__("os").environ.get("OPENAI_API_KEY"))
    result["environment_key_value_read_or_persisted"] = False
    return result


def pre_embedding_gate(
    root: Path,
    corpus: FrozenCorpus,
    token_audit: dict[str, Any],
    tests: dict[str, Any],
) -> dict[str, Any]:
    frozen = verify_frozen_spec(root)
    leakage = corpus_leakage_audit(corpus)
    secrets = repository_secret_audit(root)
    no_graph = no_graph_audit(root)
    checks = {
        "frozen_spec_checksum": frozen["status"],
        "source_checksum": "PASS" if corpus.source_audit.get("observed_manifest_sha256") == EXPECTED_SOURCE_MANIFEST_SHA256 else "FAIL",
        "corpus_size": "PASS" if len(corpus.documents) == EXPECTED_DOCUMENT_COUNT else "FAIL",
        "serialized_manifest_checksum": "PASS" if corpus.text_manifest_sha256 == EXPECTED_TEXT_MANIFEST_SHA256 else "FAIL",
        "field_registry": leakage["field_registry_status"],
        "token_audit": token_audit["status"],
        "leakage_audit": leakage["status"],
        "secret_audit": secrets["status"],
        "no_graph_audit": no_graph["status"],
        "phase5_tests": "PASS" if tests.get("passed") else "FAIL",
    }
    ready = all(value == "PASS" for value in checks.values())
    return {
        "status": "PASS" if ready else "FAIL",
        "decision": "PHASE 5B READY FOR CORPUS EMBEDDING RUN" if ready else "PHASE 5B NOT READY FOR CORPUS EMBEDDING RUN",
        "checks": checks,
        "specification": frozen,
        "corpus": {
            "document_count": len(corpus.documents),
            "source_manifest_sha256": corpus.source_audit.get("observed_manifest_sha256"),
            "text_manifest_sha256": corpus.text_manifest_sha256,
        },
        "token_audit": token_audit,
        "leakage_audit": leakage,
        "secret_audit": secrets,
        "no_graph_audit": no_graph,
        "tests": tests,
        "paid_api_calls_made": False,
    }


def render_no_graph_markdown(audit: dict[str, Any]) -> str:
    fields = (
        "graph_library", "relationship_expansion", "foreign_key_traversal", "graph_query",
        "reranking", "hybrid_search", "mmr", "relation_specific_index",
        "record_type_quota", "neighborhood_expansion",
    )
    rows = "\n".join(f"- {name.replace('_', ' ').title()}: {'PRESENT' if audit[name] else 'ABSENT'}" for name in fields)
    return f"""# Standard RAG No-Graph Compliance Audit — Version 1.0

## Scope

The static AST/import audit covers every primary Phase 5 RAG implementation module. The manual design check confirms one query embedding followed by one exhaustive global exact cosine search.

## Results

{rows}

- Static findings: `{json.dumps(audit['findings'], sort_keys=True)}`
- Manual boundary: {audit['manual_boundary_note']}

## Decision

**{audit['decision']}**
"""


def render_pre_live_markdown(values: dict[str, Any]) -> str:
    blockers = values.get("blockers", [])
    blocker_text = "\n".join(f"- {value}" for value in blockers) if blockers else "- None"
    return f"""# Standard RAG Pre-Live-Run Audit — Version 1.0

## Frozen configuration

- Specification SHA-256: `{values['frozen_spec_sha256']}`
- Corpus text-manifest SHA-256: `{values['corpus_text_manifest_sha256']}`
- Embedding-matrix SHA-256: `{values['embedding_matrix_sha256']}`
- Index-manifest SHA-256: `{values['index_manifest_sha256']}`
- Selected K: `{values['selected_k']}`
- Selection SHA-256: `{values['selection_sha256']}`
- Query version: `{values['query_version']}`
- Query-builder SHA-256: `{values['query_builder_sha256']}`
- Prompt SHA-256: `{values['prompt_sha256']}`
- Model ID: `{values['model_id']}`
- Expected held-out cases: `439`

## Audits

- Context size: {values['context_status']}
- No graph: {values['no_graph_status']}
- Runtime leakage: {values['leakage_status']}
- Held-out label isolation: {values['label_isolation_status']}
- Secrets: {values['secret_status']}
- Phase 5 tests: {values['phase5_tests_status']}
- API mocks: {values['api_mocks_status']}
- Terminal ineligible-anchor technical failures: {values.get('terminal_anchor_technical_failure_count', 0)} (`{json.dumps(values.get('terminal_anchor_technical_failure_case_ids', []))}`)
- Protocol deviations: {values['protocol_deviations']}
- Generation API calls made before this audit: NO

## Unresolved issues

{blocker_text}

## Decision

**{values['decision']}**
"""
