"""Graph retrieval and the two pre-specified deterministic ablations."""

from __future__ import annotations

from collections import defaultdict
import time
from typing import Any, Iterable

from src.rag.corpus import CorpusDocument
from src.rag.tokens import conservative_generation_tokens

from .anchor_resolver import ExactAnchorResolver
from .config import MAX_RAW_RECORDS
from .evidence_selector import select_paths_and_records
from .graph_types import GraphSnapshot
from .motif_engine import FrozenMotifEngine
from .path_ranker import FrozenPathRanker
from .registry_loader import FrozenRegistries


class DeterministicRetriever:
    def __init__(self, documents: Iterable[CorpusDocument], snapshot: GraphSnapshot, registries: FrozenRegistries) -> None:
        self.documents = {document.record_id: document for document in documents}
        self.snapshot = snapshot
        self.registries = registries
        self.resolver = ExactAnchorResolver(self.documents.values())
        self.engine = FrozenMotifEngine(snapshot, registries)
        self.ranker = FrozenPathRanker(registries)
        self.relation_order = registries.relation_order

    def _tokens(self, record_ids: Iterable[str]) -> int:
        characters = sum(len(self.documents[value].text) for value in record_ids)
        return conservative_generation_tokens("x" * characters)

    def graph_retrieve(self, route: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        resolution = self.resolver.resolve(route)
        anchor_ids = resolution["resolved_record_ids"]
        paths: list[dict[str, Any]] = []
        candidate_motifs: set[str] = set()
        executed_motifs: set[str] = set()
        hub_events: list[dict[str, Any]] = []
        if resolution["resolution_status"] in {"EXACT_SINGLE", "EXACT_MULTI"}:
            for anchor_id in anchor_ids:
                found, candidates, executed, blocked = self.engine.execute(route["case_id"], anchor_id)
                paths.extend(found)
                candidate_motifs.update(candidates)
                executed_motifs.update(executed)
                hub_events.extend(blocked)
        ranked = self.ranker.rank(paths)
        selection = select_paths_and_records(anchor_ids, ranked, cap=MAX_RAW_RECORDS)
        selected_ids = selection["selected_record_ids"]
        selected_paths = set(selection["selected_path_ids"])
        ledger = []
        for row in ranked:
            selected, exclusion = selection["path_status"][row["path_id"]]
            ledger.append({
                **row,
                "selected": selected,
                "exclusion_reason": exclusion,
                "hub_restriction_events": [],
            })
        result = {
            "ablation": "GRAPH_RAG_DETERMINISTIC_V1",
            "anchor": {
                "input_id": resolution["anchor_input_id"],
                "input_type": resolution["anchor_input_type"],
                "resolution_status": resolution["resolution_status"],
                "resolved_record_ids": anchor_ids,
            },
            "candidate_motif_ids": sorted(candidate_motifs),
            "candidate_path_count": len(ranked),
            "candidate_record_ids": selection["candidate_record_ids"],
            "candidate_unique_record_count": len(selection["candidate_record_ids"]),
            "case_id": route["case_id"],
            "estimated_context_tokens": self._tokens(selected_ids),
            "executed_motif_ids": sorted(executed_motifs),
            "hub_block_events": sorted(hub_events, key=lambda value: tuple(str(value.get(key, "")) for key in sorted(value))),
            "records_dropped_due_to_40_record_budget": selection["records_dropped_due_to_40_record_budget"],
            "selected_path_ids": selection["selected_path_ids"],
            "selected_record_count": len(selected_ids),
            "selected_record_ids": selected_ids,
            "selection_complete": True,
            "status": (
                "TECHNICAL_FAILURE" if resolution["resolution_status"] == "TECHNICAL_FAILURE"
                else "ANCHOR_UNRESOLVED" if resolution["resolution_status"] == "UNRESOLVED"
                else "SUCCESS"
            ),
            "technical_failure": resolution["technical_error"],
            "temporal_exclusions": [],
        }
        packet_paths = [
            {
                "motif_id": row["motif_id"],
                "path_id": row["path_id"],
                "rank": row["candidate_rank"],
                "record_ids": row["records"],
                "relations": row["relation_sequence"],
            }
            for row in ledger if row["path_id"] in selected_paths
        ]
        memberships = {row["record_id"]: row["supporting_path_ids"] for row in selection["record_memberships"]}
        packet = {
            "anchor": result["anchor"],
            "case_id": route["case_id"],
            "estimated_source_tokens": result["estimated_context_tokens"],
            "paths": packet_paths,
            "record_count": len(selected_ids),
            "records": [
                {
                    "node_type": self.documents[record_id].record_type,
                    "rank": rank,
                    "record_id": record_id,
                    "source_text": self.documents[record_id].text,
                    "supporting_path_ids": memberships.get(record_id, []),
                }
                for rank, record_id in enumerate(selected_ids, start=1)
            ],
        }
        return result, ledger, packet, resolution

    def profile_graph_stages(self, route: dict[str, str]) -> list[dict[str, Any]]:
        """Repeat pure stages for local latency telemetry; results are discarded."""
        case_id = route["case_id"]
        rows: list[dict[str, Any]] = []
        start = time.perf_counter_ns()
        resolution = self.resolver.resolve(route)
        rows.append({"case_id": case_id, "latency_ms": (time.perf_counter_ns() - start) / 1_000_000, "system": "exact_anchor_resolution"})
        paths: list[dict[str, Any]] = []
        start = time.perf_counter_ns()
        if resolution["resolution_status"] in {"EXACT_SINGLE", "EXACT_MULTI"}:
            for anchor_id in resolution["resolved_record_ids"]:
                found, _, _, _ = self.engine.execute(case_id, anchor_id)
                paths.extend(found)
        rows.append({"case_id": case_id, "latency_ms": (time.perf_counter_ns() - start) / 1_000_000, "system": "motif_traversal"})
        start = time.perf_counter_ns()
        ranked = self.ranker.rank(paths)
        rows.append({"case_id": case_id, "latency_ms": (time.perf_counter_ns() - start) / 1_000_000, "system": "path_ranking"})
        start = time.perf_counter_ns()
        select_paths_and_records(resolution["resolved_record_ids"], ranked, cap=MAX_RAW_RECORDS)
        rows.append({"case_id": case_id, "latency_ms": (time.perf_counter_ns() - start) / 1_000_000, "system": "evidence_selection"})
        return rows

    def anchor_rag(self, route: dict[str, str], dense_ids: list[str]) -> dict[str, Any]:
        resolution = self.resolver.resolve(route)
        selected: list[str] = []
        for value in [*resolution["resolved_record_ids"], *dense_ids]:
            if value not in selected:
                selected.append(value)
            if len(selected) == MAX_RAW_RECORDS:
                break
        return {
            "ablation": "ANCHOR_RAG",
            "anchor_resolution_status": resolution["resolution_status"],
            "case_id": route["case_id"],
            "estimated_context_tokens": self._tokens(selected),
            "retrieved_record_ids": selected,
            "selected_record_count": len(selected),
            "status": "ANCHOR_UNRESOLVED" if resolution["resolution_status"] == "UNRESOLVED" else "SUCCESS",
        }

    def relational_rag(self, route: dict[str, str]) -> dict[str, Any]:
        resolution = self.resolver.resolve(route)
        selected = list(resolution["resolved_record_ids"])
        neighbors: list[tuple[int, str, str, str]] = []
        hub_events: list[dict[str, Any]] = []
        for anchor_id in resolution["resolved_record_ids"]:
            for relation in self.registries.relation["frozen_relations"]:
                relation_type = relation["relation_type"]
                if relation["traversable"]:
                    for target, _ in self.snapshot.traverse(anchor_id, relation_type, "forward"):
                        neighbors.append((self.relation_order[relation_type], target, relation_type, "forward"))
                if relation["reverse_traversal"]:
                    for target, _ in self.snapshot.traverse(anchor_id, relation_type, "reverse"):
                        neighbors.append((self.relation_order[relation_type], target, relation_type, "reverse"))
                if not relation["traversable"] and (anchor_id, relation_type) in self.snapshot.forward:
                    hub_events.append({"hub_expansion_blocked": True, "reason": "HUB_TRAVERSAL_NOT_PERMITTED", "relation_type": relation_type, "direction": "forward"})
                if not relation["reverse_traversal"] and (anchor_id, relation_type) in self.snapshot.reverse:
                    hub_events.append({"hub_expansion_blocked": True, "reason": "HUB_TRAVERSAL_NOT_PERMITTED", "relation_type": relation_type, "direction": "reverse"})
        selected_relations: dict[str, list[str]] = defaultdict(list)
        for _, record_id, relation_type, direction in sorted(set(neighbors)):
            if record_id not in selected and len(selected) < MAX_RAW_RECORDS:
                selected.append(record_id)
                selected_relations[record_id].append(f"{relation_type}:{direction}")
        return {
            "ablation": "RELATIONAL_RAG",
            "anchor_resolution_status": resolution["resolution_status"],
            "case_id": route["case_id"],
            "estimated_context_tokens": self._tokens(selected),
            "hub_block_events": sorted(hub_events, key=lambda value: tuple(str(value.get(key, "")) for key in sorted(value))),
            "retrieved_record_ids": selected,
            "selected_record_count": len(selected),
            "selected_relation_memberships": dict(sorted(selected_relations.items())),
            "status": "ANCHOR_UNRESOLVED" if resolution["resolution_status"] == "UNRESOLVED" else "SUCCESS",
        }
