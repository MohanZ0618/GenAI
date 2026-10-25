"""Shared state for clean generators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.models import FinanceDataset
from src.utils.ids import IDFactory
from src.utils.random_utils import RandomSource


@dataclass
class GenerationContext:
    config: dict[str, Any]
    dataset: FinanceDataset
    rng: RandomSource
    ids: IDFactory
    causal_edges: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def edge(
        self,
        source_type: str,
        source_id: str,
        relationship: str,
        target_type: str,
        target_id: str,
    ) -> None:
        self.causal_edges.append(
            {
                "source_entity_type": source_type,
                "source_entity_id": source_id,
                "relationship": relationship,
                "target_entity_type": target_type,
                "target_entity_id": target_id,
            }
        )

    def audit(
        self,
        entity_type: str,
        entity_id: str,
        event_type: str,
        timestamp: str,
        actor_id: str,
        field: str = "",
        old_value: str = "",
        new_value: str = "",
        source_system: str = "ERP",
    ) -> str:
        event_id = self.ids.next("EVT")
        self.dataset.add(
            "audit_log",
            {
                "event_id": event_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "event_type": event_type,
                "timestamp": timestamp,
                "actor_id": actor_id,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "source_system": source_system,
            },
        )
        self.edge("audit_event", event_id, "records", entity_type, entity_id)
        return event_id

