"""Frozen case-level feature extraction for the classical ML baseline."""

from __future__ import annotations

import math
from collections import Counter
from datetime import date
from decimal import Decimal
from statistics import fmean
from typing import Any, Iterable

import pandas as pd

from src.classical_ml.data import FinancialSnapshot
from src.classical_ml.normalization import (
    norm_reference,
    norm_status,
    norm_text,
    parse_date,
    parse_decimal,
    parse_integer,
    parse_ts,
    reference_similarity,
    trim_id,
    within_money,
)
from src.classical_ml.registry import AS_OF_DATE, CATEGORICAL_FEATURE_NAMES, FEATURES


AS_OF = date.fromisoformat(AS_OF_DATE)
MISSING_CATEGORY = "__MISSING__"

# Counts of complete relationship sets are zero when the set is empty. NUM044
# is intentionally absent: a vendor-name token count is an entity attribute,
# so an absent vendor must remain numeric-missing for train-median imputation.
ZERO_DEFAULT_COUNT_FEATURES = {
    "invoice_line_count", "po_line_count", "allocation_count", "linked_invoice_count",
    "linked_payment_count", "bank_reference_match_count", "gl_line_count", "gl_journal_count",
    "approval_event_count", "approval_effective_count", "approval_distinct_role_count",
    "approval_missing_employee_actor_count", "vendor_change_count",
    "vendor_change_before_payment_count", "duplicate_same_vendor_count",
    "duplicate_exact_reference_count", "fx_journal_count", "fx_event_count",
    "payment_reference_use_count", "bank_economic_candidate_count",
}


def _float(value: Decimal | int | float | None) -> float:
    return float(value) if value is not None else math.nan


def _sum_decimal(values: Iterable[Decimal | None]) -> Decimal:
    return sum((value for value in values if value is not None), Decimal(0))


def _mode(values: Iterable[str | None]) -> str:
    cleaned = [value for value in values if value]
    if not cleaned:
        return MISSING_CATEGORY
    counts = Counter(cleaned)
    maximum = max(counts.values())
    return sorted(value for value, count in counts.items() if count == maximum)[0]


def _abs_diff(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return abs(left - right) if left is not None and right is not None else None


def _rel_diff(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    difference = _abs_diff(left, right)
    if difference is None or right is None:
        return None
    return difference / max(abs(right), Decimal("0.01"))


class FeatureExtractor:
    def __init__(self, snapshot: FinancialSnapshot):
        self.s = snapshot

    def _eligible_bank(self, row: dict[str, str]) -> bool:
        posted = parse_date(self.s.get("bank_transactions", row, "posted_date"))
        return posted is not None and posted <= AS_OF

    def _scope(self, entity_type: str, entity_id: str) -> dict[str, set[str]]:
        entity_type_norm = norm_status(entity_type) or ""
        identity = trim_id(entity_id) or ""
        invoices: set[str] = set()
        payments: set[str] = set()
        banks: set[str] = set()
        if entity_type_norm == "INVOICE":
            invoices.add(identity)
        elif entity_type_norm == "PAYMENT":
            payments.add(identity)
        elif entity_type_norm == "BANK_TRANSACTION":
            bank = self.s.row("bank_transactions", identity)
            if bank is not None and self._eligible_bank(bank):
                banks.add(identity)
        elif entity_type_norm == "GL_JOURNAL":
            for row in self.s.gl_by_journal.get(identity, []):
                if norm_status(self.s.get("gl_entries", row, "transaction_type")) == "PAYMENT":
                    payment_id = trim_id(self.s.get("gl_entries", row, "source_transaction_id"))
                    if payment_id:
                        payments.add(payment_id)
        for _ in range(4):
            before = (len(invoices), len(payments), len(banks))
            for bank_id in list(banks):
                bank = self.s.row("bank_transactions", bank_id)
                reference = norm_reference(self.s.get("bank_transactions", bank, "payment_reference")) if bank else None
                if reference:
                    payments.update(
                        value for row in self.s.payments_by_reference.get(reference, [])
                        if (value := trim_id(self.s.get("payments", row, "payment_id")))
                    )
            for payment_id in list(payments):
                for allocation in self.s.alloc_by_payment.get(payment_id, []):
                    invoice_id = trim_id(self.s.get("payment_allocations", allocation, "invoice_id"))
                    if invoice_id:
                        invoices.add(invoice_id)
                payment = self.s.row("payments", payment_id)
                reference = norm_reference(self.s.get("payments", payment, "reference_number")) if payment else None
                if reference:
                    banks.update(
                        value for row in self.s.banks_by_reference.get(reference, [])
                        if self._eligible_bank(row)
                        and (value := trim_id(self.s.get("bank_transactions", row, "bank_transaction_id")))
                    )
            for invoice_id in list(invoices):
                for allocation in self.s.alloc_by_invoice.get(invoice_id, []):
                    payment_id = trim_id(self.s.get("payment_allocations", allocation, "payment_id"))
                    if payment_id:
                        payments.add(payment_id)
            if before == (len(invoices), len(payments), len(banks)):
                break
        return {"invoices": invoices, "payments": payments, "banks": banks}

    def _representative(
        self,
        table: str,
        identities: set[str],
        primary_type: str,
        primary_id: str,
        expected_type: str,
    ) -> dict[str, str] | None:
        direct = self.s.row(table, primary_id) if primary_type == expected_type else None
        if direct is not None and (table != "bank_transactions" or self._eligible_bank(direct)):
            return direct
        for identity in sorted(identities):
            row = self.s.row(table, identity)
            if row is not None:
                return row
        return None

    def extract(self, route: dict[str, str]) -> dict[str, Any]:
        primary_type = norm_status(route["primary_entity_type"]) or ""
        primary_id = trim_id(route["primary_entity_id"]) or ""
        scope = self._scope(primary_type, primary_id)
        invoice = self._representative("invoices", scope["invoices"], primary_type, primary_id, "INVOICE")
        payment = self._representative("payments", scope["payments"], primary_type, primary_id, "PAYMENT")
        bank = self._representative("bank_transactions", scope["banks"], primary_type, primary_id, "BANK_TRANSACTION")

        values: dict[str, Any] = {}
        for feature in FEATURES:
            if feature.feature_type == "categorical":
                values[feature.name] = MISSING_CATEGORY
            elif feature.feature_id.startswith("MAT"):
                values[feature.name] = -1.0
            elif feature.feature_id.startswith("MIS"):
                values[feature.name] = 1.0
            elif feature.feature_id.startswith("REL") or feature.name in ZERO_DEFAULT_COUNT_FEATURES:
                values[feature.name] = 0.0
            else:
                values[feature.name] = math.nan
        values["primary_entity_type"] = primary_type or MISSING_CATEGORY

        invoice_id = trim_id(self.s.get("invoices", invoice, "invoice_id")) if invoice else None
        payment_id = trim_id(self.s.get("payments", payment, "payment_id")) if payment else None
        bank_id = trim_id(self.s.get("bank_transactions", bank, "bank_transaction_id")) if bank else None

        invoice_lines = self.s.invoice_lines_by_invoice.get(invoice_id or "", [])
        po_id = trim_id(self.s.get("invoices", invoice, "po_id")) if invoice else None
        po = self.s.row("purchase_orders", po_id)
        po_lines = self.s.po_lines_by_po.get(po_id or "", [])
        allocations_map: dict[tuple[str, str, str], dict[str, str]] = {}
        for scoped_payment in scope["payments"]:
            for allocation in self.s.alloc_by_payment.get(scoped_payment, []):
                key = (
                    trim_id(self.s.get("payment_allocations", allocation, "payment_id")) or "",
                    trim_id(self.s.get("payment_allocations", allocation, "invoice_id")) or "",
                    self.s.get("payment_allocations", allocation, "allocation_date") or "",
                )
                allocations_map[key] = allocation
        for scoped_invoice in scope["invoices"]:
            for allocation in self.s.alloc_by_invoice.get(scoped_invoice, []):
                key = (
                    trim_id(self.s.get("payment_allocations", allocation, "payment_id")) or "",
                    trim_id(self.s.get("payment_allocations", allocation, "invoice_id")) or "",
                    self.s.get("payment_allocations", allocation, "allocation_date") or "",
                )
                allocations_map[key] = allocation
        allocations = list(allocations_map.values())
        scoped_invoices = [row for identity in sorted(scope["invoices"]) if (row := self.s.row("invoices", identity)) is not None]
        scoped_payments = [row for identity in sorted(scope["payments"]) if (row := self.s.row("payments", identity)) is not None]
        scoped_banks = [row for identity in sorted(scope["banks"]) if (row := self.s.row("bank_transactions", identity)) is not None and self._eligible_bank(row)]

        invoice_total = invoice_subtotal = invoice_tax = invoice_shipping = None
        invoice_date = received_date = due_date = None
        invoice_currency = None
        invoice_reference = None
        if invoice:
            invoice_total = parse_decimal(self.s.get("invoices", invoice, "invoice_total"))
            invoice_subtotal = parse_decimal(self.s.get("invoices", invoice, "subtotal"))
            invoice_tax = parse_decimal(self.s.get("invoices", invoice, "tax"))
            invoice_shipping = parse_decimal(self.s.get("invoices", invoice, "shipping"))
            invoice_date = parse_date(self.s.get("invoices", invoice, "invoice_date"))
            received_date = parse_date(self.s.get("invoices", invoice, "received_date"))
            due_date = parse_date(self.s.get("invoices", invoice, "due_date"))
            invoice_currency = norm_text(self.s.get("invoices", invoice, "currency"))
            invoice_reference = norm_reference(self.s.get("invoices", invoice, "invoice_number"))
            values.update({
                "invoice_currency": invoice_currency or MISSING_CATEGORY,
                "invoice_status": norm_status(self.s.get("invoices", invoice, "status")) or MISSING_CATEGORY,
                "invoice_payment_terms": norm_status(self.s.get("invoices", invoice, "payment_terms")) or MISSING_CATEGORY,
                "invoice_total": _float(invoice_total), "invoice_subtotal": _float(invoice_subtotal),
                "invoice_tax": _float(invoice_tax), "invoice_shipping": _float(invoice_shipping),
                "invoice_age_calendar_days": _float((AS_OF - invoice_date).days if invoice_date else None),
                "invoice_due_lag_days": _float((due_date - invoice_date).days if due_date and invoice_date else None),
                "invoice_received_delay_days": _float((received_date - invoice_date).days if received_date and invoice_date else None),
                "invoice_reference_present": float(invoice_reference is not None),
            })
        values["missing_invoice"] = float(invoice is None)
        values["missing_invoice_lines"] = float(invoice is not None and not invoice_lines)
        values["invoice_has_po"] = float(po_id is not None) if invoice else -1.0
        values["po_found"] = (float(po is not None) if po_id else -1.0) if invoice else -1.0
        values["missing_po"] = float(po_id is not None and po is None)

        invoice_line_quantities = [parse_integer(self.s.get("invoice_lines", row, "quantity")) for row in invoice_lines]
        invoice_line_amounts = [parse_decimal(self.s.get("invoice_lines", row, "line_amount")) for row in invoice_lines]
        invoice_unit_prices = [parse_decimal(self.s.get("invoice_lines", row, "unit_price")) for row in invoice_lines]
        values.update({
            "invoice_line_count": float(len(invoice_lines)),
            "invoice_line_quantity_sum": _float(sum(value for value in invoice_line_quantities if value is not None)),
            "invoice_line_amount_sum": _float(_sum_decimal(invoice_line_amounts)),
            "invoice_line_unit_price_mean": _float(Decimal(str(fmean(float(value) for value in invoice_unit_prices if value is not None))) if any(value is not None for value in invoice_unit_prices) else None),
            "invoice_department": _mode(norm_text(self.s.get("invoice_lines", row, "department")) for row in invoice_lines),
            "invoice_gl_account": _mode(norm_text(self.s.get("invoice_lines", row, "gl_account")) for row in invoice_lines),
        })

        po_total = po_subtotal = po_tax = po_shipping = None
        po_date = None
        if po:
            po_total = parse_decimal(self.s.get("purchase_orders", po, "po_total"))
            po_subtotal = parse_decimal(self.s.get("purchase_orders", po, "subtotal"))
            po_tax = parse_decimal(self.s.get("purchase_orders", po, "tax"))
            po_shipping = parse_decimal(self.s.get("purchase_orders", po, "shipping"))
            po_date = parse_date(self.s.get("purchase_orders", po, "po_date"))
            values.update({
                "po_currency": norm_text(self.s.get("purchase_orders", po, "currency")) or MISSING_CATEGORY,
                "po_status": norm_status(self.s.get("purchase_orders", po, "status")) or MISSING_CATEGORY,
                "po_department": norm_text(self.s.get("purchase_orders", po, "department")) or MISSING_CATEGORY,
                "po_gl_account": norm_text(self.s.get("purchase_orders", po, "gl_account")) or MISSING_CATEGORY,
                "po_total": _float(po_total), "po_subtotal": _float(po_subtotal), "po_tax": _float(po_tax),
                "po_shipping": _float(po_shipping),
                "po_age_calendar_days": _float((AS_OF - po_date).days if po_date else None),
            })
        values["missing_po_lines"] = float(po is not None and not po_lines)
        po_line_quantities = [parse_integer(self.s.get("po_lines", row, "quantity")) for row in po_lines]
        po_line_amounts = [parse_decimal(self.s.get("po_lines", row, "line_amount")) for row in po_lines]
        values.update({
            "po_line_count": float(len(po_lines)),
            "po_line_quantity_sum": _float(sum(value for value in po_line_quantities if value is not None)),
            "po_line_amount_sum": _float(_sum_decimal(po_line_amounts)),
            "invoice_po_total_abs_diff": _float(_abs_diff(invoice_total, po_total)),
            "invoice_po_total_rel_diff": _float(_rel_diff(invoice_total, po_total)),
            "invoice_po_tax_abs_diff": _float(_abs_diff(invoice_tax, po_tax)),
            "invoice_po_shipping_abs_diff": _float(_abs_diff(invoice_shipping, po_shipping)),
            "invoice_po_line_amount_abs_diff": _float(_abs_diff(_sum_decimal(invoice_line_amounts), _sum_decimal(po_line_amounts)) if invoice_lines and po_lines else None),
            "invoice_po_line_quantity_abs_diff": _float(abs(sum(value for value in invoice_line_quantities if value is not None) - sum(value for value in po_line_quantities if value is not None)) if invoice_lines and po_lines else None),
            "days_po_to_invoice": _float((invoice_date - po_date).days if invoice_date and po_date else None),
        })
        if invoice and po:
            values["invoice_po_vendor_match"] = float(trim_id(self.s.get("invoices", invoice, "vendor_id")) == trim_id(self.s.get("purchase_orders", po, "vendor_id")))
            values["invoice_po_currency_match"] = float(invoice_currency == norm_text(self.s.get("purchase_orders", po, "currency"))) if invoice_currency else -1.0
        if invoice_lines:
            targets = []
            quantity_matches = []
            missing_target = False
            for line in invoice_lines:
                target_id = trim_id(self.s.get("invoice_lines", line, "po_line_id"))
                if not target_id:
                    continue
                target = self.s.row("po_lines", target_id)
                if target is None:
                    missing_target = True
                    continue
                targets.append(target)
                left = parse_integer(self.s.get("invoice_lines", line, "quantity"))
                right = parse_integer(self.s.get("po_lines", target, "quantity"))
                if left is not None and right is not None:
                    quantity_matches.append(left == right)
            values["all_invoice_lines_po_linked"] = float(all(trim_id(self.s.get("invoice_lines", row, "po_line_id")) is None or self.s.row("po_lines", trim_id(self.s.get("invoice_lines", row, "po_line_id"))) is not None for row in invoice_lines))
            values["any_invoice_line_missing_po_target"] = float(missing_target)
            values["invoice_po_quantities_all_equal"] = float(all(quantity_matches)) if quantity_matches else -1.0

        payment_amount = None
        payment_date = None
        payment_time = None
        payment_currency = None
        payment_reference = None
        if payment:
            payment_amount = parse_decimal(self.s.get("payments", payment, "payment_amount"))
            payment_date = parse_date(self.s.get("payments", payment, "payment_date"))
            payment_time = parse_ts(self.s.get("payments", payment, "created_at"))
            payment_currency = norm_text(self.s.get("payments", payment, "payment_currency"))
            payment_reference = norm_reference(self.s.get("payments", payment, "reference_number"))
            values.update({
                "payment_method": norm_status(self.s.get("payments", payment, "payment_method")) or MISSING_CATEGORY,
                "payment_currency": payment_currency or MISSING_CATEGORY,
                "payment_status": norm_status(self.s.get("payments", payment, "payment_status")) or MISSING_CATEGORY,
                "settlement_status": norm_status(self.s.get("payments", payment, "settlement_status")) or MISSING_CATEGORY,
                "payment_amount": _float(payment_amount),
                "payment_age_calendar_days": _float((AS_OF - payment_date).days if payment_date else None),
                "payment_reference_present": float(payment_reference is not None),
            })
        values["missing_payment"] = float(payment is None)
        values["allocation_count"] = float(len(allocations))
        allocated_sum = _sum_decimal(parse_decimal(self.s.get("payment_allocations", row, "allocated_amount")) for row in allocations)
        values["allocated_amount_sum"] = _float(allocated_sum)
        values["payment_has_allocations"] = float(bool(self.s.alloc_by_payment.get(payment_id or "", []))) if payment else -1.0
        values["missing_allocations"] = float(not allocations)
        existing_invoice_ids = {
            identity for allocation in allocations
            if (identity := trim_id(self.s.get("payment_allocations", allocation, "invoice_id")))
            and self.s.row("invoices", identity) is not None
        }
        values["linked_invoice_count"] = float(len(existing_invoice_ids))
        linked_invoice_total = _sum_decimal(parse_decimal(self.s.get("invoices", self.s.row("invoices", identity), "invoice_total")) for identity in existing_invoice_ids)
        values["linked_invoice_total_sum"] = _float(linked_invoice_total)
        values["linked_payment_count"] = float(len({
            identity for allocation in allocations
            if (identity := trim_id(self.s.get("payment_allocations", allocation, "payment_id")))
            and self.s.row("payments", identity) is not None
        }))
        if payment:
            payment_allocations = self.s.alloc_by_payment.get(payment_id or "", [])
            payment_allocated = _sum_decimal(parse_decimal(self.s.get("payment_allocations", row, "allocated_amount")) for row in payment_allocations)
            values["payment_allocated_abs_diff"] = _float(_abs_diff(payment_amount, payment_allocated))
            values["payment_allocated_rel_diff"] = _float(_rel_diff(payment_allocated, payment_amount))
            values["allocations_all_invoices_found"] = float(all(self.s.row("invoices", trim_id(self.s.get("payment_allocations", row, "invoice_id"))) is not None for row in payment_allocations)) if payment_allocations else -1.0
            linked_rows = [self.s.row("invoices", trim_id(self.s.get("payment_allocations", row, "invoice_id"))) for row in payment_allocations]
            linked_rows = [row for row in linked_rows if row is not None]
            values["payment_invoice_currency_all_match"] = float(all(norm_text(self.s.get("invoices", row, "currency")) == payment_currency for row in linked_rows)) if linked_rows and payment_currency else -1.0
            payment_vendor = trim_id(self.s.get("payments", payment, "vendor_id"))
            values["payment_invoice_vendor_all_match"] = float(all(trim_id(self.s.get("invoices", row, "vendor_id")) == payment_vendor for row in linked_rows)) if linked_rows and payment_vendor else -1.0
            reference_count = len(self.s.payments_by_reference.get(payment_reference or "", [])) if payment_reference else 0
            values["payment_reference_use_count"] = float(reference_count)
            values["payment_reference_unique"] = float(reference_count == 1) if payment_reference else -1.0

        effective_paid = Decimal(0)
        if invoice_id:
            for allocation in self.s.alloc_by_invoice.get(invoice_id, []):
                related_payment = self.s.row("payments", trim_id(self.s.get("payment_allocations", allocation, "payment_id")))
                if related_payment is None:
                    continue
                if norm_status(self.s.get("payments", related_payment, "payment_status")) == "COMPLETED" and norm_status(self.s.get("payments", related_payment, "settlement_status")) == "SETTLED":
                    amount = parse_decimal(self.s.get("payment_allocations", allocation, "allocated_amount"))
                    if amount is not None:
                        effective_paid += amount
            values["invoice_paid_abs_diff"] = _float(_abs_diff(invoice_total, effective_paid))
            values["invoice_paid_rel_diff"] = _float(_rel_diff(effective_paid, invoice_total))
        values["days_invoice_to_payment"] = _float((payment_date - invoice_date).days if payment_date and invoice_date else None)

        bank_amount = None
        bank_date = None
        bank_posted = None
        bank_currency = None
        if bank:
            bank_amount = parse_decimal(self.s.get("bank_transactions", bank, "amount"))
            bank_date = parse_date(self.s.get("bank_transactions", bank, "transaction_date"))
            bank_posted = parse_date(self.s.get("bank_transactions", bank, "posted_date"))
            bank_currency = norm_text(self.s.get("bank_transactions", bank, "currency"))
            values.update({
                "bank_transaction_type": norm_status(self.s.get("bank_transactions", bank, "transaction_type")) or MISSING_CATEGORY,
                "bank_currency": bank_currency or MISSING_CATEGORY,
                "bank_direction": norm_status(self.s.get("bank_transactions", bank, "direction")) or MISSING_CATEGORY,
                "bank_status": norm_status(self.s.get("bank_transactions", bank, "status")) or MISSING_CATEGORY,
                "bank_amount": _float(bank_amount),
                "bank_age_calendar_days": _float((AS_OF - bank_posted).days if bank_posted else None),
            })
        values["missing_bank_transaction"] = float(bank is None)
        matching_banks = [row for row in self.s.banks_by_reference.get(payment_reference or "", []) if self._eligible_bank(row)] if payment_reference else []
        values["bank_reference_match_count"] = float(len(matching_banks))
        values["bank_reference_match_found"] = float(bool(matching_banks)) if payment_reference else -1.0
        values["bank_reference_match_unique"] = float(len(matching_banks) == 1) if payment_reference else -1.0
        if payment and bank:
            values["payment_bank_abs_diff"] = _float(_abs_diff(payment_amount, bank_amount))
            values["payment_bank_rel_diff"] = _float(_rel_diff(bank_amount, payment_amount))
            values["payment_bank_currency_match"] = float(payment_currency == bank_currency) if payment_currency and bank_currency else -1.0
            values["payment_bank_token_match"] = float(trim_id(self.s.get("payments", payment, "bank_account_id")) == trim_id(self.s.get("bank_transactions", bank, "counterparty_token")))
            values["days_payment_to_bank"] = _float((bank_date - payment_date).days if bank_date and payment_date else None)

        economic_candidates = 0
        if payment and payment_date and payment_currency and payment_amount is not None:
            payment_token = trim_id(self.s.get("payments", payment, "bank_account_id"))
            for candidate in self.s.tables["bank_transactions"]:
                if not self._eligible_bank(candidate):
                    continue
                candidate_date = parse_date(self.s.get("bank_transactions", candidate, "transaction_date"))
                if (
                    candidate_date is not None and abs((candidate_date - payment_date).days) <= 7
                    and norm_text(self.s.get("bank_transactions", candidate, "currency")) == payment_currency
                    and trim_id(self.s.get("bank_transactions", candidate, "counterparty_token")) == payment_token
                    and within_money(self.s.get("bank_transactions", candidate, "amount"), payment_amount, payment_currency) is True
                ):
                    economic_candidates += 1
        values["bank_economic_candidate_count"] = float(economic_candidates)

        gl_rows: list[dict[str, str]] = []
        for scoped_payment_id in sorted(scope["payments"]):
            gl_rows.extend(self.s.gl_by_source.get(scoped_payment_id, []))
        if primary_type == "GL_JOURNAL":
            gl_rows.extend(self.s.gl_by_journal.get(primary_id, []))
        gl_unique = {trim_id(self.s.get("gl_entries", row, "journal_line_id")) or str(index): row for index, row in enumerate(gl_rows)}
        gl_rows = list(gl_unique.values())
        debits = [parse_decimal(self.s.get("gl_entries", row, "debit")) for row in gl_rows]
        credits = [parse_decimal(self.s.get("gl_entries", row, "credit")) for row in gl_rows]
        gl_debit = _sum_decimal(debits)
        gl_credit = _sum_decimal(credits)
        ap_debit = _sum_decimal(parse_decimal(self.s.get("gl_entries", row, "debit")) for row in gl_rows if norm_text(self.s.get("gl_entries", row, "gl_account")) == "200000-ACCOUNTS-PAYABLE")
        cash_credit = _sum_decimal(parse_decimal(self.s.get("gl_entries", row, "credit")) for row in gl_rows if norm_text(self.s.get("gl_entries", row, "gl_account")) == "100000-CASH")
        values.update({
            "gl_primary_transaction_type": _mode(norm_status(self.s.get("gl_entries", row, "transaction_type")) for row in gl_rows),
            "gl_line_count": float(len(gl_rows)),
            "gl_journal_count": float(len({trim_id(self.s.get("gl_entries", row, "journal_id")) for row in gl_rows if trim_id(self.s.get("gl_entries", row, "journal_id"))})),
            "gl_total_debit": _float(gl_debit), "gl_total_credit": _float(gl_credit),
            "gl_ap_debit": _float(ap_debit), "gl_cash_credit": _float(cash_credit),
            "gl_balance_abs_diff": _float(abs(gl_debit - gl_credit)),
            "payment_ap_debit_abs_diff": _float(_abs_diff(payment_amount, ap_debit) if gl_rows else None),
            "payment_cash_credit_abs_diff": _float(_abs_diff(payment_amount, cash_credit) if gl_rows else None),
            "gl_source_found": float(bool(gl_rows)) if payment else -1.0,
        })
        values["missing_gl"] = float(not gl_rows)
        if gl_rows and payment_currency:
            values["gl_currency_all_match"] = float(all(norm_text(self.s.get("gl_entries", row, "currency")) == payment_currency for row in gl_rows))
        if gl_rows and payment_date:
            expected_period = payment_date.strftime("%Y-%m")
            checks = []
            for row in gl_rows:
                posting = parse_date(self.s.get("gl_entries", row, "posting_date"))
                period = self.s.get("gl_entries", row, "accounting_period")
                checks.append(posting is not None and period == expected_period and posting.strftime("%Y-%m") == period)
            values["gl_period_all_match_payment_month"] = float(all(checks))

        fee_rows = []
        fx_journals: set[str] = set()
        if bank_id:
            for row in self.s.gl_by_source.get(bank_id, []):
                transaction_type = norm_status(self.s.get("gl_entries", row, "transaction_type"))
                if transaction_type == "BANK_FEE":
                    fee_rows.append(row)
                if transaction_type == "FX_SETTLEMENT":
                    journal_id = trim_id(self.s.get("gl_entries", row, "journal_id"))
                    if journal_id:
                        fx_journals.add(journal_id)
        fee_debit = _sum_decimal(parse_decimal(self.s.get("gl_entries", row, "debit")) for row in fee_rows)
        values["bank_fee_debit_total"] = _float(fee_debit)
        values["fx_journal_count"] = float(len(fx_journals))
        values["bank_fee_adjusted_abs_diff"] = _float(abs(abs(payment_amount - bank_amount) - fee_debit) if payment_amount is not None and bank_amount is not None else None)
        fx_events = 0
        if bank_id:
            for event in self.s.audit_by_entity.get(bank_id, []):
                entity_type = norm_status(self.s.get("audit_log", event, "entity_type"))
                event_type = norm_status(self.s.get("audit_log", event, "event_type"))
                if entity_type != "BANK_TRANSACTION" or event_type != "FX_CONVERSION_APPLIED":
                    continue
                timestamp = parse_ts(self.s.get("audit_log", event, "timestamp"))
                if timestamp and timestamp.date() <= AS_OF:
                    fx_events += 1
        values["fx_event_count"] = float(fx_events)

        approval_events: list[dict[str, str]] = []
        for scoped_invoice_id in sorted(scope["invoices"]):
            approval_events.extend(self.s.approvals_by_invoice.get(scoped_invoice_id, []))
        eligible_events: list[tuple[object, int, str, dict[str, str]]] = []
        if payment_time:
            for event in approval_events:
                timestamp = parse_ts(self.s.get("approval_events", event, "event_timestamp"))
                level = parse_integer(self.s.get("approval_events", event, "approval_level"))
                event_id = trim_id(self.s.get("approval_events", event, "approval_event_id")) or ""
                if timestamp is not None and timestamp <= payment_time:
                    eligible_events.append((timestamp, level if level is not None else -1, event_id, event))
        eligible_events.sort(key=lambda item: (item[0], item[1], item[2]))
        effective_events = [item for item in eligible_events if norm_status(self.s.get("approval_events", item[3], "action")) in {"APPROVED", "AUTO_APPROVED"}]
        values.update({
            "approval_event_count": float(len(eligible_events)),
            "approval_effective_count": float(len(effective_events)),
            "approval_max_level": _float(max((item[1] for item in effective_events), default=None)),
            "approval_distinct_role_count": float(len({norm_status(self.s.get("approval_events", item[3], "approver_role")) for item in effective_events if norm_status(self.s.get("approval_events", item[3], "approver_role"))})),
        })
        values["missing_approval"] = float(not eligible_events)
        missing_actors = 0
        final_employee = None
        if effective_events:
            final = effective_events[-1]
            final_event = final[3]
            role = norm_status(self.s.get("approval_events", final_event, "approver_role"))
            actor = trim_id(self.s.get("approval_events", final_event, "approver_id"))
            values["final_approval_role"] = role or MISSING_CATEGORY
            values["final_approval_action"] = norm_status(self.s.get("approval_events", final_event, "action")) or MISSING_CATEGORY
            values["minutes_final_approval_to_payment"] = _float((payment_time - final[0]).total_seconds() / 60 if payment_time else None)
            for item in effective_events:
                event_role = norm_status(self.s.get("approval_events", item[3], "approver_role"))
                event_actor = trim_id(self.s.get("approval_events", item[3], "approver_id"))
                if event_role not in {"AUTO", "WORKFLOW"} and self.s.row("employees", event_actor) is None:
                    missing_actors += 1
            if role not in {"AUTO", "WORKFLOW"}:
                final_employee = self.s.row("employees", actor)
                values["final_approver_employee_found"] = float(final_employee is not None)
                if final_employee:
                    values["final_approver_active"] = float(norm_status(self.s.get("employees", final_employee, "active_status")) == "ACTIVE")
                    values["final_approver_role_match"] = float(norm_status(self.s.get("employees", final_employee, "role")) == role)
        values["approval_missing_employee_actor_count"] = float(missing_actors)
        values["missing_employee"] = float(missing_actors > 0)

        vendor_id = None
        if primary_type == "INVOICE" and invoice:
            vendor_id = trim_id(self.s.get("invoices", invoice, "vendor_id"))
        elif payment:
            vendor_id = trim_id(self.s.get("payments", payment, "vendor_id"))
        elif invoice:
            vendor_id = trim_id(self.s.get("invoices", invoice, "vendor_id"))
        vendor = self.s.row("vendors", vendor_id)
        if vendor:
            vendor_name = norm_text(self.s.get("vendors", vendor, "vendor_name"))
            values.update({
                "vendor_type": norm_status(self.s.get("vendors", vendor, "vendor_type")) or MISSING_CATEGORY,
                "vendor_country": norm_text(self.s.get("vendors", vendor, "country")) or MISSING_CATEGORY,
                "vendor_currency": norm_text(self.s.get("vendors", vendor, "currency")) or MISSING_CATEGORY,
                "vendor_payment_terms": norm_status(self.s.get("vendors", vendor, "payment_terms")) or MISSING_CATEGORY,
                "vendor_default_payment_method": norm_status(self.s.get("vendors", vendor, "default_payment_method")) or MISSING_CATEGORY,
                "vendor_status": norm_status(self.s.get("vendors", vendor, "vendor_status")) or MISSING_CATEGORY,
                "vendor_name_length": _float(len(vendor_name) if vendor_name else None),
                "vendor_name_token_count": _float(len(vendor_name.split()) if vendor_name else None),
            })
        values["missing_vendor"] = float(vendor is None)
        changes = []
        if vendor_id:
            changes = [row for row in self.s.changes_by_vendor.get(vendor_id, []) if norm_status(self.s.get("vendor_change_log", row, "field_changed")) == "BANK_ACCOUNT_TOKEN"]
        values["vendor_change_count"] = float(len(changes))
        values["vendor_bank_history_present"] = float(bool(changes)) if vendor else -1.0
        values["missing_vendor_change_history"] = float(not changes)
        before_count = 0
        if payment_time:
            for change in changes:
                timestamp = parse_ts(self.s.get("vendor_change_log", change, "changed_at"))
                if timestamp and timestamp <= payment_time:
                    before_count += 1
        values["vendor_change_before_payment_count"] = float(before_count)
        if payment and vendor:
            payment_token = trim_id(self.s.get("payments", payment, "bank_account_id"))
            current_token = trim_id(self.s.get("vendors", vendor, "bank_account_token"))
            values["vendor_current_token_match"] = float(payment_token == current_token) if payment_token and current_token else -1.0

        duplicate_candidates = []
        if invoice and vendor_id:
            for candidate in self.s.tables["invoices"]:
                candidate_id = trim_id(self.s.get("invoices", candidate, "invoice_id"))
                if candidate_id == invoice_id or trim_id(self.s.get("invoices", candidate, "vendor_id")) != vendor_id:
                    continue
                status = norm_status(self.s.get("invoices", candidate, "status"))
                total = parse_decimal(self.s.get("invoices", candidate, "invoice_total"))
                if status in {"CANCELED", "CREDIT_APPLIED"} or total is None or total <= 0:
                    continue
                duplicate_candidates.append(candidate)
        values["duplicate_same_vendor_count"] = float(len(duplicate_candidates))
        similarities = []
        date_gaps = []
        amount_gaps = []
        exact_count = 0
        for candidate in duplicate_candidates:
            candidate_reference = norm_reference(self.s.get("invoices", candidate, "invoice_number"))
            similarity = reference_similarity(invoice_reference, candidate_reference)
            if similarity is not None:
                similarities.append(similarity)
            if invoice_reference and candidate_reference == invoice_reference:
                exact_count += 1
            candidate_date = parse_date(self.s.get("invoices", candidate, "invoice_date"))
            if invoice_date and candidate_date:
                date_gaps.append(abs((invoice_date - candidate_date).days))
            if invoice_currency and norm_text(self.s.get("invoices", candidate, "currency")) == invoice_currency:
                candidate_total = parse_decimal(self.s.get("invoices", candidate, "invoice_total"))
                if invoice_total is not None and candidate_total is not None:
                    amount_gaps.append(abs(invoice_total - candidate_total))
        values.update({
            "duplicate_exact_reference_count": float(exact_count),
            "duplicate_best_reference_similarity": max(similarities) if similarities else math.nan,
            "duplicate_min_date_gap_days": _float(min(date_gaps) if date_gaps else None),
            "duplicate_min_amount_gap": _float(min(amount_gaps) if amount_gaps else None),
        })

        economic_record = invoice if primary_type == "INVOICE" else payment if primary_type in {"PAYMENT", "GL_JOURNAL"} else bank
        if primary_type == "INVOICE":
            economic_currency, economic_amount = invoice_currency, invoice_total
            reference_present = invoice_reference is not None
        elif primary_type in {"PAYMENT", "GL_JOURNAL"}:
            economic_currency, economic_amount = payment_currency, payment_amount
            reference_present = payment_reference is not None
        else:
            economic_currency, economic_amount = bank_currency, bank_amount
            reference_present = norm_reference(self.s.get("bank_transactions", bank, "payment_reference")) is not None if bank else False
        values["missing_reference"] = float(not reference_present)
        values["missing_currency"] = float(economic_record is None or economic_currency is None)
        values["missing_amount"] = float(economic_record is None or economic_amount is None)

        values.update({
            "scope_invoice_count": float(len(scope["invoices"])),
            "scope_payment_count": float(len(scope["payments"])),
            "scope_bank_count": float(len(scope["banks"])),
            "scope_distinct_invoice_vendor_count": float(len({trim_id(self.s.get("invoices", row, "vendor_id")) for row in scoped_invoices if trim_id(self.s.get("invoices", row, "vendor_id"))})),
            "scope_distinct_payment_vendor_count": float(len({trim_id(self.s.get("payments", row, "vendor_id")) for row in scoped_payments if trim_id(self.s.get("payments", row, "vendor_id"))})),
        })

        expected = {feature.name for feature in FEATURES}
        if set(values) != expected:
            raise AssertionError(f"feature registry mismatch: missing={sorted(expected-set(values))}, extra={sorted(set(values)-expected)}")
        return {"case_id": route["case_id"], **values}


def extract_frame(snapshot: FinancialSnapshot, routes: list[dict[str, str]]) -> pd.DataFrame:
    rows = [FeatureExtractor(snapshot).extract(route) for route in routes]
    columns = ["case_id"] + [feature.name for feature in FEATURES]
    result = pd.DataFrame(rows, columns=columns)
    if result["case_id"].duplicated().any():
        raise ValueError("duplicate case IDs in feature matrix")
    for name in CATEGORICAL_FEATURE_NAMES:
        result[name] = result[name].fillna(MISSING_CATEGORY).astype(str)
    return result
