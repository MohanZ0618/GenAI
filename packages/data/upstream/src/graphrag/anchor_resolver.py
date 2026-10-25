"""Exact, label-blind operational anchor resolution."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from src.rag.corpus import CorpusDocument


ANCHOR_DOMAINS: dict[str, tuple[str, str, str]] = {
    "invoice": ("INVOICE", "invoice_id", "EXACT_SINGLE"),
    "payment": ("PAYMENT", "payment_id", "EXACT_SINGLE"),
    "bank_transaction": ("BANK_TRANSACTION", "bank_transaction_id", "EXACT_SINGLE"),
    # A journal identifier is a GL_ENTRY grouping attribute, never a node type.
    "gl_journal": ("GL_ENTRY", "journal_id", "EXACT_MULTI"),
}


class ExactAnchorResolver:
    def __init__(self, documents: Iterable[CorpusDocument]) -> None:
        index: dict[tuple[str, str, str], list[CorpusDocument]] = defaultdict(list)
        for document in documents:
            for route_type, (node_type, field, _) in ANCHOR_DOMAINS.items():
                value = document.row.get(field, "")
                if document.record_type == node_type and value:
                    index[(route_type, field, value)].append(document)
        self.index = {
            key: tuple(sorted(value, key=lambda document: document.record_id))
            for key, value in index.items()
        }

    def resolve(self, route: dict[str, str]) -> dict[str, Any]:
        case_id = str(route.get("case_id", ""))
        input_type = str(route.get("primary_entity_type", ""))
        input_id = str(route.get("primary_entity_id", ""))
        base = {
            "case_id": case_id,
            "anchor_input_type": input_type,
            "anchor_input_id": input_id,
            "resolution_method": "EXACT_CANONICAL",
            "technical_error": None,
        }
        if input_type not in ANCHOR_DOMAINS:
            return {**base, "resolution_status": "UNRESOLVED", "resolved_record_ids": [], "resolved_node_types": []}
        node_type, field, expected = ANCHOR_DOMAINS[input_type]
        matches = self.index.get((input_type, field, input_id), ())
        if not matches:
            return {**base, "resolution_status": "UNRESOLVED", "resolved_record_ids": [], "resolved_node_types": []}
        if expected == "EXACT_SINGLE" and len(matches) != 1:
            return {
                **base,
                "resolution_status": "TECHNICAL_FAILURE",
                "resolved_record_ids": [],
                "resolved_node_types": [],
                "technical_error": f"canonical single-valued anchor matched {len(matches)} nodes",
            }
        return {
            **base,
            "resolution_status": "EXACT_MULTI" if expected == "EXACT_MULTI" and len(matches) > 1 else "EXACT_SINGLE",
            "resolved_record_ids": [document.record_id for document in matches],
            "resolved_node_types": sorted({document.record_type for document in matches}),
        }
