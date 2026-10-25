"""Faithful executable translation of the frozen path-first ranking policy."""

from __future__ import annotations

from typing import Any, Iterable

from .registry_loader import FrozenRegistries


EVENT_RELATIONS = frozenset({"APPROVAL_FOR_INVOICE", "AUDIT_EVENT_FOR_INVOICE"})


class FrozenPathRanker:
    def __init__(self, registries: FrozenRegistries) -> None:
        self.relation_order = registries.relation_order

    def rank_class(self, path: dict[str, Any]) -> tuple[int, str]:
        relations = set(path["relation_sequence"])
        if relations & EVENT_RELATIONS:
            return 5, "approved event/audit context"
        if path["path_length"] == 1:
            return 2, "direct Tier A graph evidence"
        return 3, "complete deterministic Tier A multi-hop paths"

    def key(self, path: dict[str, Any]) -> tuple[Any, ...]:
        priority, _ = self.rank_class(path)
        relation_key = tuple(self.relation_order[value] for value in path["relation_sequence"])
        return (priority, path["path_length"], relation_key, tuple(path["node_sequence"]), path["path_id"])

    def rank(self, paths: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = []
        for row in sorted(paths, key=self.key):
            priority, class_name = self.rank_class(row)
            ranked.append({
                **row,
                "rank_class": class_name,
                "rank_priority": priority,
                "tie_break_fields": {
                    "graph_hops": row["path_length"],
                    "relation_registry_order": [self.relation_order[value] for value in row["relation_sequence"]],
                    "canonical_record_ids": row["node_sequence"],
                },
            })
        return [{**row, "candidate_rank": index} for index, row in enumerate(ranked, start=1)]
