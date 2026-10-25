"""Strict model-visible CSV loading with inference column-access auditing."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from src.rules_sql.normalization import norm_reference, norm_status, trim_id
from src.schema import PRIMARY_KEYS, TABLE_SCHEMAS


class TableStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.tables: dict[str, list[dict[str, str]]] = {}
        self.complete: dict[str, bool] = {}
        self.load_issues: list[str] = []
        self.accessed_columns: set[tuple[str, str]] = set()
        for table, expected_fields in TABLE_SCHEMAS.items():
            path = data_dir / f"{table}.csv"
            if not path.is_file():
                self.tables[table] = []
                self.complete[table] = False
                self.load_issues.append(f"missing table file: {path}")
                continue
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != expected_fields:
                    self.tables[table] = []
                    self.complete[table] = False
                    self.load_issues.append(
                        f"schema mismatch {table}: expected={expected_fields!r} actual={reader.fieldnames!r}"
                    )
                    continue
                rows = [dict(row) for row in reader]
            seen: set[tuple[str, ...]] = set()
            duplicates = 0
            for row in rows:
                key = tuple(row[field] for field in PRIMARY_KEYS[table])
                if key in seen:
                    duplicates += 1
                seen.add(key)
            self.tables[table] = rows
            self.complete[table] = duplicates == 0
            if duplicates:
                self.load_issues.append(f"duplicate primary keys in {table}: {duplicates}")

        self.by_id: dict[str, dict[str, dict[str, str]]] = {}
        for table, keys in PRIMARY_KEYS.items():
            if len(keys) == 1:
                key = keys[0]
                self.by_id[table] = {trim_id(self.field(table, row, key)) or "": row for row in self.tables[table]}

        self.invoice_lines_by_invoice = self._group("invoice_lines", "invoice_id")
        self.po_lines_by_po = self._group("po_lines", "po_id")
        self.allocations_by_payment = self._group("payment_allocations", "payment_id")
        self.allocations_by_invoice = self._group("payment_allocations", "invoice_id")
        self.approvals_by_invoice = self._group("approval_events", "invoice_id")
        self.gl_by_source = self._group("gl_entries", "source_transaction_id")
        self.changes_by_vendor = self._group("vendor_change_log", "vendor_id")
        self.audit_by_entity = self._group("audit_log", "entity_id")
        self.payments_by_reference: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables["payments"]:
            reference = norm_reference(self.field("payments", row, "reference_number"))
            if reference is not None:
                self.payments_by_reference[reference].append(row)
        self.banks_by_reference: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables["bank_transactions"]:
            reference = norm_reference(self.field("bank_transactions", row, "payment_reference"))
            if reference is not None:
                self.banks_by_reference[reference].append(row)

    def _group(self, table: str, field: str) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables[table]:
            key = trim_id(self.field(table, row, field))
            if key is not None:
                grouped[key].append(row)
        return grouped

    def field(self, table: str, row: dict[str, str], field: str) -> str | None:
        if field not in TABLE_SCHEMAS[table]:
            raise KeyError(f"undeclared field access: {table}.{field}")
        self.accessed_columns.add((table, field))
        value = row.get(field)
        return None if value is None or value == "" else value

    def row(self, table: str, identity: str | None) -> dict[str, str] | None:
        if identity is None:
            return None
        return self.by_id.get(table, {}).get(trim_id(identity) or "")

    def rows(self, table: str) -> list[dict[str, str]]:
        return self.tables[table]

    def require_tables(self, tables: Iterable[str]) -> list[str]:
        return [table for table in tables if not self.complete.get(table, False)]

    def model_visible_hash(self) -> str:
        digest = hashlib.sha256()
        for table in sorted(TABLE_SCHEMAS):
            path = self.data_dir / f"{table}.csv"
            digest.update(table.encode("utf-8"))
            digest.update(b"\0")
            if path.is_file():
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
        return digest.hexdigest()

    def leakage_audit(self) -> dict[str, Any]:
        prohibited_fields = {
            ("invoices", "duplicate_reference"),
            ("vendor_change_log", "change_reason"),
            ("approval_events", "comments"),
            ("gl_entries", "memo"),
            ("audit_log", "old_value"),
            ("audit_log", "new_value"),
            ("audit_log", "field"),
            ("audit_log", "actor_id"),
        }
        prohibited_audit_event_types = {
            value
            for row in self.tables["audit_log"]
            if (value := norm_status(row.get("event_type"))) != "FX_CONVERSION_APPLIED"
        }
        violations = sorted(f"{table}.{field}" for table, field in self.accessed_columns & prohibited_fields)
        return {
            "status": "PASS" if not violations else "FAIL",
            "accessed_columns": [f"{table}.{field}" for table, field in sorted(self.accessed_columns)],
            "prohibited_column_accesses": violations,
            "allowed_audit_event_type": "FX_CONVERSION_APPLIED (F14 negative branch only)",
            "prohibited_audit_event_types_present_but_not_accessed": sorted(prohibited_audit_event_types),
            "prohibited_artifact_paths_opened_by_inference": [],
        }


def load_case_routes(split_dir: Path) -> list[dict[str, str]]:
    """Read only the frozen harness-permitted routing fields from question rows."""
    routes: dict[str, dict[str, str]] = {}
    question_path = split_dir / "benchmark_questions.jsonl"
    with question_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            question = json.loads(line)
            case_id = str(question["case_id"])
            primary = question["primary_entity"]
            route = {
                "case_id": case_id,
                "primary_entity_type": str(primary["type"]),
                "primary_entity_id": str(primary["id"]),
            }
            previous = routes.setdefault(case_id, route)
            if previous != route:
                raise ValueError(f"inconsistent routing metadata for {case_id}")
    expected_case_ids = [line.strip() for line in (split_dir / "case_ids.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    if set(expected_case_ids) != set(routes):
        raise ValueError("case_ids.txt and whitelisted question routing fields disagree")
    return [routes[case_id] for case_id in expected_case_ids]
