"""Deterministic, label-blind construction of complete structural case packets."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from src.direct_llm.config import (
    AS_OF_DATE,
    FORBIDDEN_ARTIFACT_NAMES,
    FORBIDDEN_PACKET_KEYS,
    PACKET_VERSION,
)
from src.direct_llm.normalization import norm_reference, norm_status, trim_id
from src.schema import PRIMARY_KEYS, TABLE_SCHEMAS


Route = dict[str, str]


def record_id(table: str, row: dict[str, str]) -> str:
    values = [str(row.get(field, "")) for field in PRIMARY_KEYS[table]]
    return f"{table}:{'|'.join(values)}"


def identity_tokens(canonical_record_id: str) -> set[str]:
    _, key = canonical_record_id.split(":", 1)
    return {value for value in key.split("|") if value}


class OperationalSnapshot:
    """Strict loader for only the 14 delivered operational tables."""

    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.tables: dict[str, list[dict[str, str]]] = {}
        self.opened_paths: list[str] = []
        for table, fields in TABLE_SCHEMAS.items():
            path = (self.directory / f"{table}.csv").resolve()
            if path.name in FORBIDDEN_ARTIFACT_NAMES:
                raise RuntimeError(f"forbidden inference artifact: {path}")
            self.opened_paths.append(str(path))
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != fields:
                    raise ValueError(
                        f"schema mismatch for {table}: expected {fields!r}, got {reader.fieldnames!r}"
                    )
                self.tables[table] = [dict(row) for row in reader]

        self.by_id: dict[str, dict[str, dict[str, str]]] = {}
        for table, keys in PRIMARY_KEYS.items():
            if len(keys) == 1:
                key = keys[0]
                rows: dict[str, dict[str, str]] = {}
                for row in self.tables[table]:
                    value = trim_id(row.get(key)) or ""
                    if value in rows:
                        raise ValueError(f"duplicate primary key in {table}: {value}")
                    rows[value] = row
                self.by_id[table] = rows

        self.by_field: dict[tuple[str, str], dict[str, list[dict[str, str]]]] = {}
        for table, field in (
            ("vendor_change_log", "vendor_id"),
            ("purchase_orders", "vendor_id"),
            ("po_lines", "po_id"),
            ("invoices", "vendor_id"),
            ("invoice_lines", "invoice_id"),
            ("approval_events", "invoice_id"),
            ("payments", "vendor_id"),
            ("payment_allocations", "payment_id"),
            ("payment_allocations", "invoice_id"),
            ("gl_entries", "source_transaction_id"),
            ("gl_entries", "journal_id"),
            ("bank_statements", "bank_account_id"),
            ("audit_log", "entity_id"),
        ):
            grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in self.tables[table]:
                value = trim_id(row.get(field))
                if value:
                    grouped[value].append(row)
            self.by_field[(table, field)] = grouped

        self.payments_by_reference: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables["payments"]:
            if value := norm_reference(row.get("reference_number")):
                self.payments_by_reference[value].append(row)
        self.banks_by_reference: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.banks_by_counterparty: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables["bank_transactions"]:
            if value := norm_reference(row.get("payment_reference")):
                self.banks_by_reference[value].append(row)
            if value := trim_id(row.get("counterparty_token")):
                self.banks_by_counterparty[value].append(row)
        self.vendors_by_bank_token: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.tables["vendors"]:
            if value := trim_id(row.get("bank_account_token")):
                self.vendors_by_bank_token[value].append(row)

    def row(self, table: str, identity: str | None) -> dict[str, str] | None:
        return self.by_id.get(table, {}).get(trim_id(identity) or "")

    def related(self, table: str, field: str, identity: str | None) -> list[dict[str, str]]:
        return self.by_field.get((table, field), {}).get(trim_id(identity) or "", [])

    def audit(self) -> dict[str, Any]:
        prohibited = [
            path for path in self.opened_paths
            if Path(path).name in FORBIDDEN_ARTIFACT_NAMES or "raw_clean" in Path(path).parts
        ]
        expected = sorted(str((self.directory / f"{table}.csv").resolve()) for table in TABLE_SCHEMAS)
        return {
            "status": "PASS" if not prohibited and sorted(self.opened_paths) == expected else "FAIL",
            "opened_paths": self.opened_paths,
            "prohibited_paths_opened": prohibited,
            "expected_operational_paths_only": expected,
        }


def load_whitelisted_routes(split_dir: Path) -> list[Route]:
    """Extract only case/primary routing fields; labels never leave this boundary."""
    routes: dict[str, Route] = {}
    discarded_keys: set[str] = set()
    path = split_dir / "benchmark_questions.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = json.loads(line)
            discarded_keys.update(set(raw) - {"case_id", "primary_entity"})
            primary = raw["primary_entity"]
            route = {
                "case_id": str(raw["case_id"]),
                "primary_entity_type": str(primary["type"]),
                "primary_entity_id": str(primary["id"]),
            }
            previous = routes.setdefault(route["case_id"], route)
            if previous != route:
                raise ValueError(f"inconsistent route for {route['case_id']}")
    ordered = [
        line.strip()
        for line in (split_dir / "case_ids.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if set(ordered) != set(routes):
        raise ValueError("case_ids.txt and route IDs disagree")
    result = [routes[case_id] for case_id in ordered]
    if any(set(route) != {"case_id", "primary_entity_type", "primary_entity_id"} for route in result):
        raise AssertionError(f"route whitelist failure; discarded keys={sorted(discarded_keys)}")
    return result


@dataclass(frozen=True)
class CasePacket:
    route: Route
    value: dict[str, Any]
    serialized: str
    packet_sha256: str
    evidence_record_ids: frozenset[str]
    record_count: int

    def artifact_row(self) -> dict[str, Any]:
        return {
            "case_id": self.route["case_id"],
            "primary_entity_type": self.route["primary_entity_type"],
            "primary_entity_id": self.route["primary_entity_id"],
            "packet_version": PACKET_VERSION,
            "packet_sha256": self.packet_sha256,
            "record_count": self.record_count,
            "evidence_record_ids": sorted(self.evidence_record_ids),
            "serialized_packet": self.serialized,
        }


class CasePacketBuilder:
    """Build structural case closure plus unranked same-vendor peer records."""

    def __init__(self, snapshot: OperationalSnapshot):
        self.snapshot = snapshot

    @staticmethod
    def _identity(row: dict[str, str] | None, field: str) -> str | None:
        return trim_id(row.get(field)) if row else None

    def build(self, route: Route) -> CasePacket:
        allowed = {"case_id", "primary_entity_type", "primary_entity_id"}
        if set(route) != allowed:
            raise ValueError(f"route contains non-whitelisted keys: {sorted(set(route) - allowed)}")

        core_invoices: set[str] = set()
        core_payments: set[str] = set()
        core_banks: set[str] = set()
        primary_journals: set[str] = set()
        entity_type = norm_status(route["primary_entity_type"]) or ""
        primary_id = trim_id(route["primary_entity_id"]) or ""
        if entity_type == "INVOICE":
            core_invoices.add(primary_id)
        elif entity_type == "PAYMENT":
            core_payments.add(primary_id)
        elif entity_type == "BANK_TRANSACTION":
            core_banks.add(primary_id)
        elif entity_type == "GL_JOURNAL":
            primary_journals.add(primary_id)
        else:
            raise ValueError(f"unsupported primary entity type: {entity_type}")

        # Exact bidirectional operational closure: allocation bridges and payment references.
        for _ in range(12):
            before = (len(core_invoices), len(core_payments), len(core_banks))
            for journal_id in primary_journals:
                for entry in self.snapshot.related("gl_entries", "journal_id", journal_id):
                    source = self._identity(entry, "source_transaction_id")
                    kind = norm_status(entry.get("transaction_type")) or ""
                    if source and kind == "PAYMENT":
                        core_payments.add(source)
                    elif source and kind == "INVOICE":
                        core_invoices.add(source)
                    elif source and kind == "BANK_FEE":
                        core_banks.add(source)
            for invoice_id in list(core_invoices):
                for allocation in self.snapshot.related("payment_allocations", "invoice_id", invoice_id):
                    if value := self._identity(allocation, "payment_id"):
                        core_payments.add(value)
            for payment_id in list(core_payments):
                for allocation in self.snapshot.related("payment_allocations", "payment_id", payment_id):
                    if value := self._identity(allocation, "invoice_id"):
                        core_invoices.add(value)
                payment = self.snapshot.row("payments", payment_id)
                reference = norm_reference(payment.get("reference_number")) if payment else None
                for bank in self.snapshot.banks_by_reference.get(reference or "", []):
                    if value := self._identity(bank, "bank_transaction_id"):
                        core_banks.add(value)
            for bank_id in list(core_banks):
                bank = self.snapshot.row("bank_transactions", bank_id)
                reference = norm_reference(bank.get("payment_reference")) if bank else None
                for payment in self.snapshot.payments_by_reference.get(reference or "", []):
                    if value := self._identity(payment, "payment_id"):
                        core_payments.add(value)
            if before == (len(core_invoices), len(core_payments), len(core_banks)):
                break
        else:
            raise RuntimeError(f"core scope did not converge for {route['case_id']}")

        core_pos: set[str] = set()
        core_vendors: set[str] = set()
        for invoice_id in core_invoices:
            invoice = self.snapshot.row("invoices", invoice_id)
            if value := self._identity(invoice, "vendor_id"):
                core_vendors.add(value)
            if value := self._identity(invoice, "po_id"):
                core_pos.add(value)
        for payment_id in core_payments:
            if value := self._identity(self.snapshot.row("payments", payment_id), "vendor_id"):
                core_vendors.add(value)
        for bank_id in core_banks:
            bank = self.snapshot.row("bank_transactions", bank_id)
            token = self._identity(bank, "counterparty_token")
            for vendor in self.snapshot.vendors_by_bank_token.get(token or "", []):
                if value := self._identity(vendor, "vendor_id"):
                    core_vendors.add(value)
        for po_id in list(core_pos):
            if value := self._identity(self.snapshot.row("purchase_orders", po_id), "vendor_id"):
                core_vendors.add(value)

        # Unranked same-vendor peers are included as candidate context, but they do not
        # recursively expand into unrelated journals/workflows. This supports F01/F15
        # and their hard negatives without semantic retrieval or relevance ranking.
        peer_invoices: set[str] = set(core_invoices)
        peer_payments: set[str] = set(core_payments)
        peer_banks: set[str] = set(core_banks)
        for vendor_id in core_vendors:
            for row in self.snapshot.related("invoices", "vendor_id", vendor_id):
                if value := self._identity(row, "invoice_id"):
                    peer_invoices.add(value)
            for row in self.snapshot.related("payments", "vendor_id", vendor_id):
                if value := self._identity(row, "payment_id"):
                    peer_payments.add(value)
            vendor = self.snapshot.row("vendors", vendor_id)
            token = self._identity(vendor, "bank_account_token")
            for row in self.snapshot.banks_by_counterparty.get(token or "", []):
                if value := self._identity(row, "bank_transaction_id"):
                    peer_banks.add(value)
        for payment_id in list(peer_payments):
            payment = self.snapshot.row("payments", payment_id)
            reference = norm_reference(payment.get("reference_number")) if payment else None
            for bank in self.snapshot.banks_by_reference.get(reference or "", []):
                if value := self._identity(bank, "bank_transaction_id"):
                    peer_banks.add(value)
            for allocation in self.snapshot.related("payment_allocations", "payment_id", payment_id):
                if value := self._identity(allocation, "invoice_id"):
                    peer_invoices.add(value)

        included: dict[str, set[str]] = {table: set() for table in TABLE_SCHEMAS}

        def include(table: str, row: dict[str, str] | None) -> None:
            if row is not None:
                included[table].add(record_id(table, row))

        # Headers, lines, workflows, allocation bridges, and procurement support.
        all_pos = set(core_pos)
        all_vendors = set(core_vendors)
        for invoice_id in peer_invoices:
            invoice = self.snapshot.row("invoices", invoice_id)
            include("invoices", invoice)
            if value := self._identity(invoice, "vendor_id"):
                all_vendors.add(value)
            if value := self._identity(invoice, "po_id"):
                all_pos.add(value)
            for row in self.snapshot.related("invoice_lines", "invoice_id", invoice_id):
                include("invoice_lines", row)
            for row in self.snapshot.related("approval_events", "invoice_id", invoice_id):
                include("approval_events", row)
        for po_id in all_pos:
            po = self.snapshot.row("purchase_orders", po_id)
            include("purchase_orders", po)
            if value := self._identity(po, "vendor_id"):
                all_vendors.add(value)
            for row in self.snapshot.related("po_lines", "po_id", po_id):
                include("po_lines", row)
        for payment_id in peer_payments:
            include("payments", self.snapshot.row("payments", payment_id))
            for row in self.snapshot.related("payment_allocations", "payment_id", payment_id):
                include("payment_allocations", row)
        for vendor_id in all_vendors:
            include("vendors", self.snapshot.row("vendors", vendor_id))
            for row in self.snapshot.related("vendor_change_log", "vendor_id", vendor_id):
                include("vendor_change_log", row)
        for bank_id in peer_banks:
            include("bank_transactions", self.snapshot.row("bank_transactions", bank_id))

        # Journals remain tied to the exact core, plus fee journals for core bank rows.
        for journal_id in primary_journals:
            for row in self.snapshot.related("gl_entries", "journal_id", journal_id):
                include("gl_entries", row)
        for source_id in core_invoices | core_payments | core_banks:
            for row in self.snapshot.related("gl_entries", "source_transaction_id", source_id):
                include("gl_entries", row)

        company_accounts = {
            value for bank_id in peer_banks
            if (bank := self.snapshot.row("bank_transactions", bank_id)) is not None
            and (value := self._identity(bank, "bank_account_id"))
        }
        for account_id in company_accounts:
            for row in self.snapshot.related("bank_statements", "bank_account_id", account_id):
                include("bank_statements", row)

        # Operational audit events for every included identity; event time is the only
        # row-level cutoff because it is a genuine event-availability timestamp.
        audited_ids: set[str] = {primary_id, *primary_journals}
        for table, rows in included.items():
            for canonical_id in rows:
                audited_ids.update(identity_tokens(canonical_id))
        for entity_id in audited_ids:
            for event in self.snapshot.related("audit_log", "entity_id", entity_id):
                if str(event.get("timestamp", ""))[:10] <= AS_OF_DATE:
                    include("audit_log", event)

        employee_ids: set[str] = set()
        for table, actor_field in (
            ("approval_events", "approver_id"),
            ("purchase_orders", "created_by"),
            ("vendor_change_log", "changed_by"),
            ("audit_log", "actor_id"),
        ):
            for row in self.snapshot.tables[table]:
                if record_id(table, row) in included[table]:
                    if value := trim_id(row.get(actor_field)):
                        employee_ids.add(value)
        for employee_id in employee_ids:
            include("employees", self.snapshot.row("employees", employee_id))

        records: dict[str, list[dict[str, str]]] = {}
        all_record_ids: set[str] = set()
        for table, fields in TABLE_SCHEMAS.items():
            selected: list[dict[str, str]] = []
            for row in self.snapshot.tables[table]:
                canonical_id = record_id(table, row)
                if canonical_id not in included[table]:
                    continue
                output_row = {"record_id": canonical_id}
                output_row.update((field, row.get(field, "")) for field in fields)
                selected.append(output_row)
                all_record_ids.add(canonical_id)
            selected.sort(key=lambda row: tuple(row[field] for field in PRIMARY_KEYS[table]))
            records[table] = selected

        packet: dict[str, Any] = {
            "packet_version": PACKET_VERSION,
            "case": {
                "case_id": route["case_id"],
                "primary_entity_type": route["primary_entity_type"],
                "primary_entity_id": route["primary_entity_id"],
                "decision_as_of_date": AS_OF_DATE,
            },
            "records": records,
        }
        violations = forbidden_key_paths(packet)
        if violations:
            raise RuntimeError(f"forbidden packet keys: {violations}")
        serialized = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        return CasePacket(
            route=dict(route), value=packet, serialized=serialized,
            packet_sha256=sha256(serialized.encode("utf-8")).hexdigest(),
            evidence_record_ids=frozenset(all_record_ids), record_count=len(all_record_ids),
        )


def forbidden_key_paths(value: Any, prefix: str = "$") -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            if key in FORBIDDEN_PACKET_KEYS:
                result.append(path)
            result.extend(forbidden_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(forbidden_key_paths(child, f"{prefix}[{index}]"))
    return result


def estimated_tokens(*texts: str) -> int:
    """Frozen conservative, provider-independent preflight estimate."""
    return math.ceil(sum(len(value) for value in texts) / 3)


def select_stability_routes(routes: Iterable[Route], size: int, salt: str) -> list[Route]:
    ranked = sorted(
        (sha256(f"{salt}|{route['case_id']}".encode()).hexdigest(), dict(route))
        for route in routes
    )
    return [route for _, route in ranked[:size]]
