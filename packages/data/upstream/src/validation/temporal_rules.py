"""Cross-table chronological consistency validation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.models import FinanceDataset
from src.utils.dates import parse_date


def validate_temporal_order(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    pos = {str(row["po_id"]): row for row in dataset.rows("purchase_orders")}
    invoices = {str(row["invoice_id"]): row for row in dataset.rows("invoices")}
    approvals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in dataset.rows("approval_events"):
        approvals[str(event["invoice_id"])].append(event)
    allocations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dataset.rows("payment_allocations"):
        allocations[str(row["payment_id"])].append(row)

    for invoice_id, invoice in invoices.items():
        invoice_date = parse_date(str(invoice["invoice_date"]))
        received_date = parse_date(str(invoice["received_date"]))
        if received_date < invoice_date:
            issues.append({"rule": "INVOICE_RECEIVED_ORDER", "entity_id": invoice_id})
        if invoice["po_id"]:
            po = pos.get(str(invoice["po_id"]))
            if po is None or parse_date(str(po["po_date"])) > invoice_date:
                issues.append({"rule": "PO_INVOICE_ORDER", "entity_id": invoice_id})
        last_event = received_date
        for event in sorted(approvals.get(invoice_id, []), key=lambda row: str(row["event_timestamp"])):
            event_date = parse_date(str(event["event_timestamp"])[:10])
            if event_date < received_date or event_date < last_event:
                issues.append({"rule": "APPROVAL_EVENT_ORDER", "entity_id": event["approval_event_id"]})
            last_event = event_date

    for payment in dataset.rows("payments"):
        payment_id = str(payment["payment_id"])
        payment_date = parse_date(str(payment["payment_date"]))
        for allocation in allocations.get(payment_id, []):
            invoice_id = str(allocation["invoice_id"])
            approved_events = [
                parse_date(str(event["event_timestamp"])[:10]) for event in approvals.get(invoice_id, [])
                if event["action"] in {"approved", "auto_approved"}
            ]
            if not approved_events or payment_date < max(approved_events):
                issues.append({"rule": "APPROVAL_PAYMENT_ORDER", "entity_id": payment_id})
            if parse_date(str(allocation["allocation_date"])) > payment_date:
                issues.append({"rule": "ALLOCATION_PAYMENT_ORDER", "entity_id": payment_id})

    payments_by_reference = {str(row["reference_number"]): row for row in dataset.rows("payments")}
    for transaction in dataset.rows("bank_transactions"):
        transaction_date = parse_date(str(transaction["transaction_date"]))
        posted_date = parse_date(str(transaction["posted_date"]))
        if posted_date < transaction_date:
            issues.append({"rule": "BANK_POSTING_ORDER", "entity_id": transaction["bank_transaction_id"]})
        payment = payments_by_reference.get(str(transaction["payment_reference"]))
        if payment is not None and transaction["transaction_type"] != "bank fee":
            if transaction_date < parse_date(str(payment["payment_date"])):
                issues.append({"rule": "PAYMENT_BANK_ORDER", "entity_id": transaction["bank_transaction_id"]})
    return issues

