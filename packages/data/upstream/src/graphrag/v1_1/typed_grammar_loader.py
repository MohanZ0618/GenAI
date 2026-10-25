"""Fail-closed loading for the frozen Graph v1.1 grammar and lineage."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


FREEZE_INVENTORY_SHA256 = "9c5e57374928e2f3f0c6bb503f85aaf8c4cd4db7654eae70787a0e7a6351d29c"
GRAMMAR_SHA256 = "2222def5dc3fd18628731949697087c6c96d7cdf1bb6c4cf2d16a1a58da6c8dc"
GRAPH_NODES_SHA256 = "87f80fa5e91675b192dd051598a9197c0703650f4daf09c2a7619c031295a167"
GRAPH_EDGES_SHA256 = "ee364fa677abeda3b25119d5c3c2f1aea5bc8902a28e7f7ecefcddd38a77d9ed"
EXPECTED_TOPOLOGY_PATH_SET_SHA256 = "89d7f799f60149a8e6665bf59a484131f450ec2ab435e9a891e1eec3efbb2944"
EXPECTED_TRANSITION_CLASSES = {
    "BACKBONE": 18,
    "SUPPORTING": 2,
    "CONTEXT": 5,
    "TERMINAL_CONTEXT": 5,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class FrozenGrammarBundle:
    root: Path
    grammar: dict[str, Any]
    forbidden: dict[str, Any]
    ranking: dict[str, Any]
    relation_registry: dict[str, Any]
    freeze_manifest: dict[str, Any]
    freeze_inventory: dict[str, Any]
    input_verification: dict[str, Any]

    @property
    def transitions(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.grammar["transitions"])


def _verify_file(path: Path, expected_sha256: str, expected_bytes: int | None = None) -> dict[str, Any]:
    observed = sha256_file(path)
    size = path.stat().st_size
    passed = observed == expected_sha256 and (expected_bytes is None or size == expected_bytes)
    return {
        "path": path.as_posix(),
        "expected_sha256": expected_sha256,
        "observed_sha256": observed,
        "expected_bytes": expected_bytes,
        "observed_bytes": size,
        "status": "PASS" if passed else "FAIL",
    }


def load_verified_grammar(root: Path) -> FrozenGrammarBundle:
    root = root.resolve()
    freeze = root / "results/graphrag/registry_freeze_v1_1"
    graph = root / "results/graphrag/phase6a_graph_retrieval_v1_0/graph"
    registry_v1 = root / "results/graphrag/registry_freeze_v1"
    inventory_path = freeze / "graph_v1_1_freeze_hashes.json"
    checks = [_verify_file(inventory_path, FREEZE_INVENTORY_SHA256)]
    inventory = load_json(inventory_path)
    for name, metadata in sorted(inventory["artifacts"].items()):
        checks.append(_verify_file(freeze / name, metadata["sha256"], metadata["bytes"]))
    script = inventory["analysis_script"]
    checks.append(_verify_file(freeze / script["path"], script["sha256"], script["bytes"]))
    for row in inventory["parent_input_verification"]["checks"]:
        checks.append(_verify_file(root / row["path"], row["expected_sha256"], row.get("expected_bytes")))
    checks.extend([
        _verify_file(freeze / "graph_traversal_grammar_v1_1.json", GRAMMAR_SHA256),
        _verify_file(graph / "nodes.jsonl", GRAPH_NODES_SHA256),
        _verify_file(graph / "edges.jsonl", GRAPH_EDGES_SHA256),
    ])
    failed = [row for row in checks if row["status"] != "PASS"]
    if failed:
        raise RuntimeError(f"BLOCKED — GRAPH v1.1 FREEZE LINEAGE FAILURE: {failed}")

    grammar = load_json(freeze / "graph_traversal_grammar_v1_1.json")
    forbidden = load_json(freeze / "forbidden_traversals_v1_1.json")
    ranking = load_json(registry_v1 / "graph_ranking_policy_v1.json")
    relation_registry = load_json(registry_v1 / "graph_relation_registry_v1.json")
    manifest = load_json(freeze / "graph_v1_1_freeze_manifest.json")
    semantic_diff = load_json(freeze / "draft_to_final_semantic_diff_v1_1.json")
    topology = load_json(freeze / "grammar_topology_simulation_v1_1.json")

    transitions = grammar.get("transitions", [])
    class_counts = Counter(row.get("transition_class") for row in transitions)
    relation_types = {row.get("relation_id") for row in transitions}
    invariants = {
        "freeze_status": manifest.get("freeze_status") == "FROZEN_GRAPH_V1_1_TYPED_GRAMMAR",
        "grammar_status": grammar.get("status") == "FROZEN",
        "transition_count": len(transitions) == grammar.get("transition_count") == 30,
        "unique_transition_ids": len({row.get("transition_id") for row in transitions}) == 30,
        "transition_class_counts": dict(class_counts) == EXPECTED_TRANSITION_CLASSES,
        "relation_type_count": len(relation_types) == grammar.get("relation_type_count") == 15,
        "max_path_depth": grammar.get("max_path_depth") == 3,
        "simple_path_only": grammar.get("simple_path_only") is True,
        "default_deny": grammar.get("default_deny") is True,
        "semantic_transition_diff": semantic_diff.get("semantic_transition_diff_count") == 0,
        "topology_digest": topology.get("candidate_path_set_sha256") == EXPECTED_TOPOLOGY_PATH_SET_SHA256,
        "forbidden_direction_count": forbidden.get("excluded_frozen_directional_transition_count") == 14,
        "generic_bfs_disabled": grammar.get("generic_bfs_enabled") is False,
        "payment_bank_disabled": grammar.get("payment_bank_enabled") is False,
        "synthetic_gl_journal_disabled": grammar.get("synthetic_gl_journal_enabled") is False,
        "tier_b_disabled": grammar.get("tier_b_enabled") is False,
        "semantic_fallback_disabled": grammar.get("semantic_fallback_enabled") is False,
    }
    if not all(invariants.values()):
        raise RuntimeError(f"BLOCKED — GRAPH v1.1 FROZEN GRAMMAR INVARIANT FAILURE: {invariants}")
    if any(row.get("status") != "FROZEN" for row in transitions):
        raise RuntimeError("BLOCKED — non-frozen transition found in Graph v1.1 registry")

    relative_checks = []
    for row in checks:
        copy = dict(row)
        try:
            copy["path"] = Path(row["path"]).relative_to(root).as_posix()
        except ValueError:
            pass
        relative_checks.append(copy)
    verification = {
        "status": "PASS",
        "check_count": len(relative_checks),
        "distinct_path_count": len({row["path"] for row in relative_checks}),
        "checks": relative_checks,
        "grammar_invariants": invariants,
    }
    return FrozenGrammarBundle(
        root=root,
        grammar=grammar,
        forbidden=forbidden,
        ranking=ranking,
        relation_registry=relation_registry,
        freeze_manifest=manifest,
        freeze_inventory=inventory,
        input_verification=verification,
    )
