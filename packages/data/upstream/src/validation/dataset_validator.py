"""Aggregate validation with machine-readable results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.models import FinanceDataset
from src.schema import PRIMARY_KEYS, TABLE_SCHEMAS
from src.validation.financial_rules import (
    validate_bank_statements,
    validate_gl_balance,
    validate_invoice_math,
    validate_payment_allocations,
    validate_po_math,
)
from src.validation.reconciliation_rules import validate_erp_bank, validate_operational_gl
from src.validation.temporal_rules import validate_temporal_order


@dataclass
class ValidationReport:
    passed: bool
    issue_count: int
    issues_by_rule: dict[str, int]
    issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _schema_and_ids(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for table, rows in dataset.tables.items():
        expected = set(TABLE_SCHEMAS[table])
        seen: set[tuple[object, ...]] = set()
        keys = PRIMARY_KEYS[table]
        for row in rows:
            if set(row) != expected:
                issues.append({"rule": "SCHEMA", "entity_id": table})
            identity = tuple(row.get(key) for key in keys)
            if identity in seen:
                issues.append({"rule": "DUPLICATE_PRIMARY_KEY", "entity_id": f"{table}:{identity}"})
            seen.add(identity)
    return issues


def validate_dataset(dataset: FinanceDataset, clean: bool = True) -> ValidationReport:
    """Validate structural invariants; clean mode additionally requires cross-system agreement."""
    validators = [
        _schema_and_ids,
        validate_po_math,
        validate_invoice_math,
        validate_payment_allocations,
        validate_gl_balance,
        validate_bank_statements,
        validate_temporal_order,
    ]
    if clean:
        validators.extend((validate_operational_gl, validate_erp_bank))
    issues: list[dict[str, Any]] = []
    for validator in validators:
        issues.extend(validator(dataset))
    counts: dict[str, int] = {}
    for issue in issues:
        rule = str(issue["rule"])
        counts[rule] = counts.get(rule, 0) + 1
    return ValidationReport(not issues, len(issues), dict(sorted(counts.items())), issues)

