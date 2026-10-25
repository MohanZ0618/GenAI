from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from src.rules_sql.engine import F01Parameters, FrozenRulesBaseline
from src.schema import TABLE_SCHEMAS


def row(table: str, **values: Any) -> dict[str, str]:
    result = {field: "" for field in TABLE_SCHEMAS[table]}
    result.update({key: str(value) for key, value in values.items()})
    return result


def engine(tmp_path: Path, tables: dict[str, list[dict[str, str]]] | None = None, f01: F01Parameters | None = None) -> FrozenRulesBaseline:
    tables = tables or {}
    for table, fields in TABLE_SCHEMAS.items():
        path = tmp_path / f"{table}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(tables.get(table, []))
    return FrozenRulesBaseline(tmp_path, f01)


def active_invoice(invoice_id: str = "I1", **values: Any) -> dict[str, str]:
    defaults: dict[str, Any] = {
        "invoice_id": invoice_id,
        "vendor_id": "V1",
        "invoice_number": f"REF-{invoice_id}",
        "invoice_date": "2026-06-01",
        "received_date": "2026-06-01",
        "due_date": "2026-06-30",
        "currency": "USD",
        "subtotal": "100.00",
        "tax": "0.00",
        "shipping": "0.00",
        "invoice_total": "100.00",
        "payment_terms": "NET30",
        "status": "approved",
        "created_at": "2026-06-01T08:00:00",
    }
    defaults.update(values)
    return row("invoices", **defaults)


def payment(payment_id: str = "P1", **values: Any) -> dict[str, str]:
    defaults: dict[str, Any] = {
        "payment_id": payment_id,
        "vendor_id": "V1",
        "payment_date": "2026-06-01",
        "payment_method": "ACH",
        "payment_currency": "USD",
        "payment_amount": "100.00",
        "bank_account_id": "TOKEN1",
        "payment_status": "completed",
        "settlement_status": "settled",
        "reference_number": f"REF-{payment_id}",
        "created_at": "2026-06-01T10:00:00",
    }
    defaults.update(values)
    return row("payments", **defaults)
