"""One label-blind query constructed only from the routed operational anchor."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from src.rag.config import DECISION_CUTOFF, QUERY_VERSION
from src.rag.corpus import CorpusDocument, FrozenCorpus
from src.rag.leakage import assert_case_id_not_embedded, assert_payload_label_blind, assert_route
from src.rag.serialization import json_string
from src.rag.tokens import embedding_token_count


ANCHOR_TABLES = {
    "invoice": ("invoices", "invoice_id"),
    "payment": ("payments", "payment_id"),
    "bank_transaction": ("bank_transactions", "bank_transaction_id"),
    "gl_journal": ("gl_entries", "journal_id"),
}


class AnchorResolutionError(RuntimeError):
    """A frozen route cannot resolve to its required cutoff-eligible anchor."""


@dataclass(frozen=True)
class RetrievalQuery:
    case_id: str
    primary_entity_type: str
    primary_entity_id: str
    anchor_record_ids: tuple[str, ...]
    text: str
    sha256: str
    character_count: int
    token_count: int

    def artifact_row(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "primary_entity_type": self.primary_entity_type,
            "primary_entity_id": self.primary_entity_id,
            "query_version": QUERY_VERSION,
            "anchor_record_ids": list(self.anchor_record_ids),
            "query": self.text,
            "query_sha256": self.sha256,
            "query_character_count": self.character_count,
            "query_token_count": self.token_count,
            "case_id_embedded": False,
        }


def _anchor_documents(route: dict[str, str], corpus: FrozenCorpus) -> list[CorpusDocument]:
    entity_type = route["primary_entity_type"]
    if entity_type not in ANCHOR_TABLES:
        raise AnchorResolutionError(f"unsupported primary entity type: {entity_type}")
    table, field = ANCHOR_TABLES[entity_type]
    documents = corpus.primary_lookup(table, field, route["primary_entity_id"])
    if entity_type == "gl_journal":
        documents.sort(key=lambda document: document.row["journal_line_id"])
        if not documents:
            raise AnchorResolutionError(f"missing/ineligible GL journal anchor: {route['primary_entity_id']}")
    elif len(documents) != 1:
        raise AnchorResolutionError(
            f"anchor must resolve to exactly one eligible row: type={entity_type} id={route['primary_entity_id']} count={len(documents)}"
        )
    return documents


def build_query(route: dict[str, str], corpus: FrozenCorpus) -> RetrievalQuery:
    assert_route(route)
    anchors = _anchor_documents(route, corpus)
    lines = [
        "TASK: FINANCIAL_RECONCILIATION_EVIDENCE_RETRIEVAL",
        "REQUEST: Retrieve operational financial records needed to determine whether the anchor matches or has a reconciliation anomaly.",
        f'DECISION_AS_OF_DATE: "{DECISION_CUTOFF}"',
        f"ANCHOR_TYPE: {route['primary_entity_type'].upper()}",
        f"ANCHOR_ID: {json_string(route['primary_entity_id'])}",
        "ANCHOR_RECORDS_BEGIN",
    ]
    for index, document in enumerate(anchors, start=1):
        lines.append(f"--- ANCHOR_RECORD {index} ---")
        lines.append(document.text)
    lines.append("ANCHOR_RECORDS_END")
    text = "\n".join(lines)
    assert_case_id_not_embedded(route["case_id"], text)
    assert_payload_label_blind(text, name=f"query:{route['case_id']}")
    return RetrievalQuery(
        case_id=route["case_id"],
        primary_entity_type=route["primary_entity_type"],
        primary_entity_id=route["primary_entity_id"],
        anchor_record_ids=tuple(document.record_id for document in anchors),
        text=text,
        sha256=sha256(text.encode("utf-8")).hexdigest(),
        character_count=len(text),
        token_count=embedding_token_count(text),
    )
