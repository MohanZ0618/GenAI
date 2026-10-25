"""Core accounting and arithmetic validation rules."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.models import FinanceDataset
from src.utils.money import decimal, money, sum_money


def validate_po_math(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    line_totals: dict[str, list[object]] = defaultdict(list)
    for line in dataset.rows("po_lines"):
        line_totals[str(line["po_id"])].append(line["line_amount"])
        expected = money(decimal(line["quantity"]) * decimal(line["unit_price"]))
        if expected != money(line["line_amount"]):
            issues.append({"rule": "PO_LINE_EXTENDED_AMOUNT", "entity_id": line["po_line_id"]})
    for po in dataset.rows("purchase_orders"):
        subtotal = sum_money(line_totals[str(po["po_id"])], str(po["currency"]))
        if subtotal != money(po["subtotal"], str(po["currency"])):
            issues.append({"rule": "PO_SUBTOTAL", "entity_id": po["po_id"]})
        total = money(decimal(po["subtotal"]) + decimal(po["tax"]) + decimal(po["shipping"]), str(po["currency"]))
        if total != money(po["po_total"], str(po["currency"])):
            issues.append({"rule": "PO_TOTAL", "entity_id": po["po_id"]})
    return issues


def validate_invoice_math(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    line_totals: dict[str, list[object]] = defaultdict(list)
    for line in dataset.rows("invoice_lines"):
        line_totals[str(line["invoice_id"])].append(line["line_amount"])
        expected = money(decimal(line["quantity"]) * decimal(line["unit_price"]))
        if expected != money(line["line_amount"]):
            issues.append({"rule": "INVOICE_LINE_EXTENDED_AMOUNT", "entity_id": line["invoice_line_id"]})
    for invoice in dataset.rows("invoices"):
        currency = str(invoice["currency"])
        subtotal = sum_money(line_totals[str(invoice["invoice_id"])], currency)
        if subtotal != money(invoice["subtotal"], currency):
            issues.append({"rule": "INVOICE_SUBTOTAL", "entity_id": invoice["invoice_id"]})
        total = money(decimal(invoice["subtotal"]) + decimal(invoice["tax"]) + decimal(invoice["shipping"]), currency)
        if total != money(invoice["invoice_total"], currency):
            issues.append({"rule": "INVOICE_TOTAL", "entity_id": invoice["invoice_id"]})
    return issues


def validate_payment_allocations(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    by_payment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_invoice: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invoices = {str(row["invoice_id"]): row for row in dataset.rows("invoices")}
    payments = {str(row["payment_id"]): row for row in dataset.rows("payments")}
    for allocation in dataset.rows("payment_allocations"):
        payment_id, invoice_id = str(allocation["payment_id"]), str(allocation["invoice_id"])
        by_payment[payment_id].append(allocation)
        by_invoice[invoice_id].append(allocation)
        if payment_id not in payments or invoice_id not in invoices:
            issues.append({"rule": "ALLOCATION_FOREIGN_KEY", "entity_id": f"{payment_id}:{invoice_id}"})
        elif payments[payment_id]["vendor_id"] != invoices[invoice_id]["vendor_id"]:
            issues.append({"rule": "ALLOCATION_VENDOR", "entity_id": f"{payment_id}:{invoice_id}"})
    for payment_id, payment in payments.items():
        allocations = by_payment.get(payment_id, [])
        allocated = sum_money((row["allocated_amount"] for row in allocations), str(payment["payment_currency"]))
        if allocated != money(payment["payment_amount"], str(payment["payment_currency"])):
            issues.append({"rule": "PAYMENT_ALLOCATION_TOTAL", "entity_id": payment_id})
    for invoice_id, invoice in invoices.items():
        allocated = sum_money((row["allocated_amount"] for row in by_invoice.get(invoice_id, [])), str(invoice["currency"]))
        total = money(invoice["invoice_total"], str(invoice["currency"]))
        if invoice["status"] == "paid" and allocated != total:
            issues.append({"rule": "PAID_INVOICE_BALANCE", "entity_id": invoice_id})
        if allocated > total:
            issues.append({"rule": "INVOICE_OVERPAYMENT", "entity_id": invoice_id})
    return issues


def validate_gl_balance(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    journals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dataset.rows("gl_entries"):
        journals[str(row["journal_id"])].append(row)
    for journal_id, rows in journals.items():
        debit = sum((decimal(row["debit"]) for row in rows), decimal(0))
        credit = sum((decimal(row["credit"]) for row in rows), decimal(0))
        if money(debit) != money(credit):
            issues.append({"rule": "GL_JOURNAL_BALANCE", "entity_id": journal_id})
    return issues


def validate_bank_statements(dataset: FinanceDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    previous_by_account: dict[str, object] = {}
    statements = sorted(dataset.rows("bank_statements"), key=lambda row: (str(row["bank_account_id"]), str(row["statement_date"])))
    for row in statements:
        expected = money(decimal(row["opening_balance"]) + decimal(row["total_credits"]) - decimal(row["total_debits"]))
        if expected != money(row["closing_balance"]):
            issues.append({"rule": "BANK_STATEMENT_MATH", "entity_id": row["bank_statement_id"]})
        account = str(row["bank_account_id"])
        if account in previous_by_account and money(previous_by_account[account]) != money(row["opening_balance"]):
            issues.append({"rule": "BANK_STATEMENT_CONTINUITY", "entity_id": row["bank_statement_id"]})
        previous_by_account[account] = row["closing_balance"]
    return issues

