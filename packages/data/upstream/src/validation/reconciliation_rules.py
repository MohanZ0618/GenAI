"""Operational-to-ledger and ERP-to-bank reconciliation rules."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.models import FinanceDataset
from src.utils.money import money, sum_money


def validate_operational_gl(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    by_source: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in dataset.rows("gl_entries"):
        by_source[(str(row["transaction_type"]), str(row["source_transaction_id"]))].append(row)
    for invoice in dataset.rows("invoices"):
        rows = by_source.get(("invoice", str(invoice["invoice_id"])), [])
        credits = sum_money((row["credit"] for row in rows if row["gl_account"] == "200000-ACCOUNTS-PAYABLE"))
        if credits != money(invoice["invoice_total"], str(invoice["currency"])):
            issues.append({"rule": "INVOICE_GL_RECONCILIATION", "entity_id": invoice["invoice_id"]})
    for payment in dataset.rows("payments"):
        rows = by_source.get(("payment", str(payment["payment_id"])), [])
        cash_credit = sum_money((row["credit"] for row in rows if row["gl_account"] == "100000-CASH"))
        if cash_credit != money(payment["payment_amount"], str(payment["payment_currency"])):
            issues.append({"rule": "PAYMENT_GL_RECONCILIATION", "entity_id": payment["payment_id"]})
    return issues


def validate_erp_bank(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    bank_by_reference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dataset.rows("bank_transactions"):
        if row["transaction_type"] != "bank fee":
            bank_by_reference[str(row["payment_reference"])].append(row)
    for payment in dataset.rows("payments"):
        if payment["settlement_status"] != "settled":
            continue
        candidates = bank_by_reference.get(str(payment["reference_number"]), [])
        if len(candidates) != 1:
            issues.append({"rule": "ERP_BANK_MATCH_COUNT", "entity_id": payment["payment_id"]})
        elif money(candidates[0]["amount"], str(payment["payment_currency"])) != money(
            payment["payment_amount"], str(payment["payment_currency"])
        ):
            issues.append({"rule": "ERP_BANK_AMOUNT", "entity_id": payment["payment_id"]})
    return issues

