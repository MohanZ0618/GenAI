"""Case-local checks proving that each injected primary failure is observable."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from src.models import FinanceDataset
from src.utils.dates import accounting_period
from src.utils.money import decimal, money, sum_money


def _normalized_reference(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _signature_index(dataset: FinanceDataset) -> dict[str, Any]:
    allocations_by_invoice: dict[str, list[dict[str, Any]]] = defaultdict(list)
    allocations_by_payment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dataset.rows("payment_allocations"):
        allocations_by_invoice[str(row["invoice_id"])].append(row)
        allocations_by_payment[str(row["payment_id"])].append(row)
    return {
        "invoices": {str(row["invoice_id"]): row for row in dataset.rows("invoices")},
        "pos": {str(row["po_id"]): row for row in dataset.rows("purchase_orders")},
        "payments": {str(row["payment_id"]): row for row in dataset.rows("payments")},
        "bank_ids": {str(row["bank_transaction_id"]): row for row in dataset.rows("bank_transactions")},
        "allocations_by_invoice": allocations_by_invoice,
        "allocations_by_payment": allocations_by_payment,
    }


def verify_failure_case(dataset: FinanceDataset, case: dict[str, Any], index: dict[str, Any] | None = None) -> bool:
    failure_type = str(case["failure_type"])
    if failure_type == "NO_FAILURE":
        return True
    primary_id = str(case["primary_entity"]["id"])
    view = index or _signature_index(dataset)
    invoices = view["invoices"]
    pos = view["pos"]
    payments = view["payments"]
    bank_ids = view["bank_ids"]
    allocations_by_invoice = view["allocations_by_invoice"]
    allocations_by_payment = view["allocations_by_payment"]

    if failure_type == "F01_DUPLICATE_INVOICE":
        duplicate = invoices.get(primary_id)
        return bool(duplicate and any(
            row["invoice_id"] != primary_id and row["vendor_id"] == duplicate["vendor_id"]
            and money(row["invoice_total"], str(row["currency"])) == money(duplicate["invoice_total"], str(duplicate["currency"]))
            and _normalized_reference(row["invoice_number"]) == _normalized_reference(duplicate["invoice_number"])
            for row in invoices.values()
        ))
    if failure_type == "F02_PO_INVOICE_AMOUNT_MISMATCH":
        invoice = invoices[primary_id]
        return money(invoice["invoice_total"], str(invoice["currency"])) > money(pos[str(invoice["po_id"])]["po_total"], str(invoice["currency"]))
    if failure_type == "F03_QUANTITY_MISMATCH":
        line_by_id = {str(row["po_line_id"]): row for row in dataset.rows("po_lines")}
        return any(row["invoice_id"] == primary_id and row["po_line_id"]
                   and row["quantity"] != line_by_id[str(row["po_line_id"])]["quantity"]
                   and money(row["line_amount"]) == money(line_by_id[str(row["po_line_id"])]["line_amount"])
                   for row in dataset.rows("invoice_lines"))
    if failure_type == "F04_INCORRECT_VENDOR_ASSOCIATION":
        invoice = invoices[primary_id]
        return invoice["vendor_id"] != pos[str(invoice["po_id"])]["vendor_id"]
    if failure_type == "F05_PAYMENT_WITHOUT_VALID_INVOICE":
        return primary_id in payments and not allocations_by_payment.get(primary_id)
    if failure_type == "F06_INVOICE_PAID_TWICE":
        invoice = invoices[primary_id]
        allocated = sum_money((row["allocated_amount"] for row in allocations_by_invoice[primary_id]), str(invoice["currency"]))
        return allocated > money(invoice["invoice_total"], str(invoice["currency"]))
    if failure_type == "F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE":
        invoice = invoices[primary_id]
        allocated = sum_money((row["allocated_amount"] for row in allocations_by_invoice[primary_id]), str(invoice["currency"]))
        return invoice["status"] == "paid" and allocated < money(invoice["invoice_total"], str(invoice["currency"]))
    if failure_type == "F08_APPROVAL_WORKFLOW_FAILURE":
        affected_invoice_ids = [str(entity["id"]) for entity in case["affected_entities"] if entity["type"] == "invoice"]
        if not affected_invoice_ids:
            return False
        invoice = invoices[affected_invoice_ids[0]]
        amount = decimal(invoice["invoice_total"])
        required = 1 if amount <= 10000 else 2 if amount <= 50000 else 3
        approvals = [row for row in dataset.rows("approval_events") if row["invoice_id"] == invoice["invoice_id"]
                     and row["action"] in {"approved", "auto_approved"}]
        return len(approvals) < required
    if failure_type == "F09_GL_POSTING_MISMATCH":
        payment = payments[primary_id]
        rows = [row for row in dataset.rows("gl_entries") if row["transaction_type"] == "payment"
                and row["source_transaction_id"] == primary_id]
        debit = sum_money((row["debit"] for row in rows))
        credit = sum_money((row["credit"] for row in rows))
        return debit == credit and debit != money(payment["payment_amount"])
    if failure_type == "F10_WRONG_ACCOUNTING_PERIOD":
        rows = [row for row in dataset.rows("gl_entries") if row["journal_id"] == primary_id]
        payment = payments[str(rows[0]["source_transaction_id"])] if rows else None
        return bool(rows and payment and all(row["accounting_period"] != accounting_period(str(payment["payment_date"])) for row in rows))
    if failure_type == "F11_VENDOR_MASTER_CHANGE_CONFLICT":
        payment = payments[primary_id]
        vendor = next(row for row in dataset.rows("vendors") if row["vendor_id"] == payment["vendor_id"])
        changes = [row for row in dataset.rows("vendor_change_log") if row["vendor_id"] == vendor["vendor_id"]
                   and row["field_changed"] == "bank_account_token" and row["old_value"] == payment["bank_account_id"]]
        banks = [row for row in dataset.rows("bank_transactions") if row["payment_reference"] == payment["reference_number"]]
        return bool(changes and banks and payment["bank_account_id"] != vendor["bank_account_token"] and banks[0]["status"] == "returned")
    if failure_type == "F12_ERP_PAYMENT_MISSING_FROM_BANK":
        payment = payments[primary_id]
        return not any(row["payment_reference"] == payment["reference_number"] and row["transaction_type"] != "bank fee"
                       for row in dataset.rows("bank_transactions"))
    if failure_type == "F13_BANK_TRANSACTION_MISSING_FROM_ERP":
        bank = bank_ids[primary_id]
        return not any(row["reference_number"] == bank["payment_reference"] for row in payments.values())
    if failure_type == "F14_BANK_ERP_AMOUNT_MISMATCH":
        payment = payments[primary_id]
        banks = [row for row in dataset.rows("bank_transactions") if row["payment_reference"] == payment["reference_number"]
                 and row["transaction_type"] != "bank fee"]
        return bool(banks and money(banks[0]["amount"], str(payment["payment_currency"])) != money(payment["payment_amount"], str(payment["payment_currency"]))
                    and not any(row["transaction_type"] == "bank_fee" and row["source_transaction_id"] == banks[0]["bank_transaction_id"]
                                for row in dataset.rows("gl_entries")))
    if failure_type == "F15_INCORRECT_PAYMENT_BANK_MATCH":
        affected_payments = [entity["id"] for entity in case["affected_entities"] if entity["type"] == "payment"]
        affected_banks = [bank_ids[entity["id"]] for entity in case["affected_entities"] if entity["type"] == "bank_transaction"]
        if len(affected_payments) != 2 or len(affected_banks) != 2:
            return False
        expected_refs = {str(payments[value]["reference_number"]) for value in affected_payments}
        actual_refs = {str(row["payment_reference"]) for row in affected_banks}
        return expected_refs == actual_refs and all(
            not any(row["payment_reference"] == payments[value]["reference_number"]
                    and money(row["amount"], str(payments[value]["payment_currency"])) == money(payments[value]["payment_amount"], str(payments[value]["payment_currency"]))
                    for row in affected_banks) for value in affected_payments
        )
    return False


def validate_failure_signatures(dataset: FinanceDataset, cases: list[dict[str, Any]]) -> dict[str, Any]:
    index = _signature_index(dataset)
    failed = [str(case["case_id"]) for case in cases if case["failure_type"] != "NO_FAILURE"
              and not verify_failure_case(dataset, case, index)]
    return {"passed": not failed, "checked": sum(case["failure_type"] != "NO_FAILURE" for case in cases), "failed_case_ids": failed}
