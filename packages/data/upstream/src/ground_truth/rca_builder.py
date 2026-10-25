"""Validate that structured RCA labels refer to real benchmark evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.models import FinanceDataset


ENTITY_FIELDS: dict[str, tuple[str, str]] = {
    "vendor": ("vendors", "vendor_id"),
    "vendor_change": ("vendor_change_log", "change_id"),
    "purchase_order": ("purchase_orders", "po_id"),
    "po_line": ("po_lines", "po_line_id"),
    "invoice": ("invoices", "invoice_id"),
    "invoice_line": ("invoice_lines", "invoice_line_id"),
    "approval_event": ("approval_events", "approval_event_id"),
    "payment": ("payments", "payment_id"),
    "gl_journal": ("gl_entries", "journal_id"),
    "gl_entry": ("gl_entries", "journal_line_id"),
    "bank_transaction": ("bank_transactions", "bank_transaction_id"),
    "bank_statement": ("bank_statements", "bank_statement_id"),
    "employee": ("employees", "employee_id"),
    "audit_event": ("audit_log", "event_id"),
}


TABLE_ID_FIELDS: dict[str, tuple[str, ...]] = {
    "vendors": ("vendor_id",),
    "vendor_change_log": ("change_id", "vendor_id"),
    "purchase_orders": ("po_id",),
    "po_lines": ("po_line_id", "po_id"),
    "invoices": ("invoice_id",),
    "invoice_lines": ("invoice_line_id", "invoice_id"),
    "approval_events": ("approval_event_id", "invoice_id"),
    "payments": ("payment_id", "reference_number"),
    "payment_allocations": ("payment_id", "invoice_id"),
    "gl_entries": ("journal_id", "journal_line_id", "source_transaction_id"),
    "bank_transactions": ("bank_transaction_id", "payment_reference", "bank_reference"),
    "bank_statements": ("bank_statement_id",),
    "employees": ("employee_id",),
    "audit_log": ("event_id", "entity_id"),
}


@dataclass
class GroundTruthValidation:
    passed: bool
    issue_count: int
    issues: list[dict[str, str]]
    failure_counts: dict[str, int]


def build_evidence_index(dataset: FinanceDataset) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Index all supported identifiers once for large-benchmark validation and packaging."""
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for table, fields in TABLE_ID_FIELDS.items():
        table_index: dict[str, list[dict[str, Any]]] = {}
        for row in dataset.rows(table):
            for field in fields:
                table_index.setdefault(str(row[field]), []).append(row)
        result[table] = table_index
    return result


def validate_ground_truth(dataset: FinanceDataset, cases: list[dict[str, Any]]) -> GroundTruthValidation:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    required = {
        "case_id", "failure_type", "primary_entity", "affected_entities", "observed_symptom", "root_cause",
        "root_cause_category", "evidence_required", "evidence_ids", "expected_resolution", "reasoning_hops",
        "difficulty", "injected_timestamp", "affected_systems", "split",
    }
    evidence_index = build_evidence_index(dataset)
    entity_index = {
        entity_type: {str(row[field]) for row in dataset.rows(table)}
        for entity_type, (table, field) in ENTITY_FIELDS.items()
    }
    all_evidence_ids = set().union(*(set(table_index) for table_index in evidence_index.values()))
    for case in cases:
        case_id = str(case.get("case_id", ""))
        if case_id in seen:
            issues.append({"case_id": case_id, "issue": "duplicate case_id"})
        seen.add(case_id)
        missing = required - case.keys()
        if missing:
            issues.append({"case_id": case_id, "issue": f"missing fields: {sorted(missing)}"})
        primary = case.get("primary_entity", {})
        if str(primary.get("id", "")) not in entity_index.get(str(primary.get("type", "")), set()):
            issues.append({"case_id": case_id, "issue": "primary entity does not exist"})
        for affected in case.get("affected_entities", []):
            if str(affected.get("id", "")) not in entity_index.get(str(affected.get("type", "")), set()):
                issues.append({"case_id": case_id, "issue": f"affected entity missing: {affected}"})
        for evidence_id in case.get("evidence_ids", []):
            if str(evidence_id) not in all_evidence_ids:
                issues.append({"case_id": case_id, "issue": f"evidence ID missing: {evidence_id}"})
        unknown_tables = set(case.get("evidence_required", [])) - dataset.tables.keys()
        if unknown_tables:
            issues.append({"case_id": case_id, "issue": f"unknown evidence tables: {sorted(unknown_tables)}"})
    counts = Counter(str(case["failure_type"]) for case in cases)
    return GroundTruthValidation(not issues, len(issues), issues, dict(sorted(counts.items())))


def evidence_records(
    dataset: FinanceDataset,
    case: dict[str, Any],
    evidence_index: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
) -> list[dict[str, Any]]:
    """Build a model-visible, case-scoped evidence package without RCA labels."""
    identities = {str(value) for value in case["evidence_ids"]}
    for affected in case["affected_entities"]:
        identities.add(str(affected["id"]))
    index = evidence_index or build_evidence_index(dataset)
    records: list[dict[str, Any]] = []
    for table in case["evidence_required"]:
        seen_rows: set[int] = set()
        for identity in sorted(identities):
            for row in index[table].get(identity, []):
                if id(row) not in seen_rows:
                    seen_rows.add(id(row))
                    records.append({"case_id": case["case_id"], "table": table, "record": row})
    return records
