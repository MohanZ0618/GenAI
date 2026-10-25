"""Evaluation-only evidence resolution; never imported by primary retrieval paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.ground_truth.rca_builder import TABLE_ID_FIELDS
from src.rag.corpus import CorpusDocument


@dataclass(frozen=True)
class ResolvedEvidence:
    case_id: str
    annotated_ids: frozenset[str]
    required_tables: frozenset[str]
    required_record_ids: frozenset[str]
    observable_tables: frozenset[str]
    absence_only_tables: frozenset[str]
    record_tokens: dict[str, frozenset[str]]
    record_tables: dict[str, str]


def row_identifier_tokens(table: str, row: dict[str, str]) -> frozenset[str]:
    return frozenset(str(row.get(field, "")) for field in TABLE_ID_FIELDS[table] if str(row.get(field, "")))


def resolve_evidence(case: dict[str, Any], documents: Iterable[CorpusDocument]) -> ResolvedEvidence:
    annotated = frozenset(str(value) for value in case.get("evidence_ids", []))
    required_tables = frozenset(str(value) for value in case.get("evidence_required", []))
    required_ids: set[str] = set()
    observable: set[str] = set()
    tokens_by_record: dict[str, frozenset[str]] = {}
    tables_by_record: dict[str, str] = {}
    for document in documents:
        if document.source_table not in required_tables:
            continue
        tokens = row_identifier_tokens(document.source_table, document.row)
        if annotated & tokens:
            required_ids.add(document.record_id)
            observable.add(document.source_table)
            tokens_by_record[document.record_id] = tokens
            tables_by_record[document.record_id] = document.source_table
    if annotated and not required_ids:
        raise RuntimeError(f"no eligible documents resolve annotated evidence for {case.get('case_id')}")
    covered = set().union(*(set(value) for value in tokens_by_record.values())) if tokens_by_record else set()
    if not annotated <= covered:
        raise RuntimeError(f"unresolved annotated evidence IDs for {case.get('case_id')}: {sorted(annotated - covered)}")
    return ResolvedEvidence(
        case_id=str(case["case_id"]),
        annotated_ids=annotated,
        required_tables=required_tables,
        required_record_ids=frozenset(required_ids),
        observable_tables=frozenset(observable),
        absence_only_tables=frozenset(required_tables - observable),
        record_tokens=tokens_by_record,
        record_tables=tables_by_record,
    )
