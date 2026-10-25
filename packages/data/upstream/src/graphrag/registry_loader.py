"""Fail-closed loading and hash verification of frozen graph registries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.rag.artifacts import sha256_file

from .config import EXPECTED_FREEZE_HASHES, FEATURE_FLAGS, FREEZE_DIR


@dataclass(frozen=True)
class FrozenRegistries:
    node: dict[str, Any]
    relation: dict[str, Any]
    motifs: dict[str, Any]
    ranking: dict[str, Any]
    manifest: dict[str, Any]
    hashes: dict[str, str]

    @property
    def relation_order(self) -> dict[str, int]:
        return {row["relation_type"]: index for index, row in enumerate(self.relation["frozen_relations"])}


def load_frozen_registries(base: Path = FREEZE_DIR) -> FrozenRegistries:
    observed: dict[str, str] = {}
    payloads: dict[str, Any] = {}
    for name, expected in EXPECTED_FREEZE_HASHES.items():
        path = base / name
        digest = sha256_file(path)
        observed[name] = digest
        if digest != expected:
            raise RuntimeError(f"PHASE 6A BLOCKED: frozen artifact hash mismatch: {name} expected={expected} observed={digest}")
        if path.suffix == ".json":
            payloads[name] = json.loads(path.read_text(encoding="utf-8"))
    node = payloads["graph_node_registry_v1.json"]
    relation = payloads["graph_relation_registry_v1.json"]
    motifs = payloads["graph_path_motifs_v1.json"]
    ranking = payloads["graph_ranking_policy_v1.json"]
    if node["node_type_count"] != 14 or node["total_record_count"] != 155391 or node["synthetic_node_types"]:
        raise RuntimeError("PHASE 6A BLOCKED: frozen node registry invariants failed")
    if relation["frozen_relation_count"] != 22 or len(relation["frozen_relations"]) != 22:
        raise RuntimeError("PHASE 6A BLOCKED: frozen executable relation count is not 22")
    if motifs["frozen_path_motif_count"] != 8 or motifs["unrestricted_bfs_permitted"]:
        raise RuntimeError("PHASE 6A BLOCKED: motif count/BFS policy mismatch")
    if motifs["global_raw_source_record_cap"] != 40 or ranking["context_budget"]["maximum_raw_source_records"] != 40:
        raise RuntimeError("PHASE 6A BLOCKED: raw record cap mismatch")
    flags = relation["feature_flags"] | ranking["feature_flags"]
    if any(bool(flags.get(key)) for key in flags):
        raise RuntimeError("PHASE 6A BLOCKED: a frozen future feature is enabled")
    if any(FEATURE_FLAGS.values()):
        raise RuntimeError("PHASE 6A BLOCKED: local prohibited feature flag enabled")
    if ranking["trained_reranker"] or ranking["scoring_weights"] is not None:
        raise RuntimeError("PHASE 6A BLOCKED: learned/weighted ranking found")
    return FrozenRegistries(
        node=node,
        relation=relation,
        motifs=motifs,
        ranking=ranking,
        manifest=payloads["graph_freeze_manifest_v1.json"],
        hashes=observed,
    )
