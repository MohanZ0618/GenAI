"""Leakage-audited model-visible snapshot and whitelisted case routing."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.classical_ml.normalization import norm_reference, trim_id
from src.schema import PRIMARY_KEYS, TABLE_SCHEMAS


FORBIDDEN_FIELDS = {
    ("invoices", "duplicate_reference"), ("vendor_change_log", "change_reason"),
    ("approval_events", "comments"), ("gl_entries", "memo"),
    ("audit_log", "actor_id"), ("audit_log", "field"), ("audit_log", "old_value"), ("audit_log", "new_value"),
}


class FinancialSnapshot:
    def __init__(self, directory: Path):
        self.directory = directory
        self.tables: dict[str, list[dict[str, str]]] = {}
        self.accessed_columns: set[tuple[str, str]] = set()
        self.opened_paths: list[str] = []
        self.issues: list[str] = []
        for table, fields in TABLE_SCHEMAS.items():
            path = directory / f"{table}.csv"
            self.opened_paths.append(str(path))
            if not path.is_file():
                self.tables[table] = []
                self.issues.append(f"missing {path}")
                continue
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != fields:
                    self.issues.append(f"schema mismatch {table}")
                    self.tables[table] = []
                    continue
                self.tables[table] = list(reader)
        self.by_id: dict[str, dict[str, dict[str, str]]] = {}
        for table, keys in PRIMARY_KEYS.items():
            if len(keys) == 1:
                self.by_id[table] = {
                    trim_id(self.get(table, row, keys[0])) or "": row for row in self.tables[table]
                }
        self.invoice_lines_by_invoice = self._group("invoice_lines", "invoice_id")
        self.po_lines_by_po = self._group("po_lines", "po_id")
        self.alloc_by_payment = self._group("payment_allocations", "payment_id")
        self.alloc_by_invoice = self._group("payment_allocations", "invoice_id")
        self.approvals_by_invoice = self._group("approval_events", "invoice_id")
        self.gl_by_source = self._group("gl_entries", "source_transaction_id")
        self.gl_by_journal = self._group("gl_entries", "journal_id")
        self.changes_by_vendor = self._group("vendor_change_log", "vendor_id")
        self.audit_by_entity = self._group("audit_log", "entity_id")
        self.payments_by_reference: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables["payments"]:
            reference = norm_reference(self.get("payments", row, "reference_number"))
            if reference:
                self.payments_by_reference[reference].append(row)
        self.banks_by_reference: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables["bank_transactions"]:
            reference = norm_reference(self.get("bank_transactions", row, "payment_reference"))
            if reference:
                self.banks_by_reference[reference].append(row)

    def get(self, table: str, row: dict[str, str], field: str) -> str | None:
        if field not in TABLE_SCHEMAS[table]:
            raise KeyError(f"undeclared source field {table}.{field}")
        if (table, field) in FORBIDDEN_FIELDS:
            raise RuntimeError(f"forbidden ML feature field requested: {table}.{field}")
        self.accessed_columns.add((table, field))
        value = row.get(field)
        return None if value is None or value == "" else value

    def _group(self, table: str, field: str) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables[table]:
            value = trim_id(self.get(table, row, field))
            if value:
                result[value].append(row)
        return result

    def row(self, table: str, identity: str | None) -> dict[str, str] | None:
        return self.by_id.get(table, {}).get(trim_id(identity) or "")

    def audit(self) -> dict[str, Any]:
        prohibited = sorted(f"{table}.{field}" for table, field in self.accessed_columns & FORBIDDEN_FIELDS)
        prohibited_paths = [
            value for value in self.opened_paths
            if any(part in value for part in ("rca_ground_truth", "failure_manifest", "causal_edges", "mutation_log", "raw_clean", "dataset_quality") )
        ]
        return {
            "status": "PASS" if not self.issues and not prohibited and not prohibited_paths else "FAIL",
            "schema_or_load_issues": self.issues,
            "accessed_columns": [f"{table}.{field}" for table, field in sorted(self.accessed_columns)],
            "prohibited_column_accesses": prohibited,
            "prohibited_artifact_paths_opened": prohibited_paths,
            "opened_paths": self.opened_paths,
        }


def load_routes(split_dir: Path) -> list[dict[str, str]]:
    """Parse question rows but retain only explicitly permitted routing keys."""
    routes: dict[str, dict[str, str]] = {}
    path = split_dir / "benchmark_questions.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = json.loads(line)
            primary = raw["primary_entity"]
            route = {
                "case_id": str(raw["case_id"]),
                "primary_entity_type": str(primary["type"]),
                "primary_entity_id": str(primary["id"]),
            }
            previous = routes.setdefault(route["case_id"], route)
            if previous != route:
                raise ValueError(f"inconsistent routing for {route['case_id']}")
    ordered = [value.strip() for value in (split_dir / "case_ids.txt").read_text(encoding="utf-8").splitlines() if value.strip()]
    if set(ordered) != set(routes):
        raise ValueError("routing and case ID files disagree")
    return [routes[value] for value in ordered]
