"""Legitimate exceptions and hard negatives with no reconciliation failure."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Callable

from src.failures.base import InjectionContext
from src.generators.bank_generator import rebuild_bank_statements
from src.utils.dates import accounting_period, parse_date
from src.utils.money import decimal, money


class HardNegativeGenerator:
    """Generate case-balanced examples that defeat simplistic mismatch rules."""

    def __init__(self, ctx: InjectionContext):
        self.ctx = ctx

    def generate(self, start_number: int, count: int) -> list[dict[str, Any]]:
        builders: list[Callable[[str], dict[str, Any] | None]] = [
            self._exact_po_match,
            self._batch_payment,
            self._split_payment,
            self._weekend_settlement,
            self._po_tolerance,
            self._check_clearing,
            self._accounted_bank_fee,
            self._paid_on_due_date,
            self._recent_pending_settlement,
            self._net_fee_with_accounting,
            self._credit_memo,
            self._invoice_cancellation,
            self._payment_reversal,
            self._foreign_exchange_settlement,
            self._payment_terms_change,
            self._split_cost_center_accounting,
        ]
        cases: list[dict[str, Any]] = []
        for offset in range(count):
            case_id = f"RCA_{start_number + offset:06d}"
            preferred = offset % len(builders)
            case = builders[preferred](case_id)
            if case is None:
                for builder in builders:
                    case = builder(case_id)
                    if case is not None:
                        break
            if case is None:
                case = self._generic_valid_payment(case_id)
            cases.append(case)
        rebuild_bank_statements(self.ctx.dataset, self.ctx.config, self.ctx.ids)
        return cases

    def _case(
        self,
        case_id: str,
        primary_type: str,
        primary_id: str,
        vendor_id: str,
        affected: list[tuple[str, str]],
        symptom: str,
        explanation: str,
        category: str,
        evidence_tables: list[str],
        evidence_ids: list[str],
        timestamp: str,
        systems: list[str],
        difficulty: str,
        hops: int,
    ) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "failure_type": "NO_FAILURE",
            "severity": "none",
            "primary_entity": {"type": primary_type, "id": primary_id},
            "affected_entities": [{"type": kind, "id": identity} for kind, identity in affected],
            "observed_symptom": symptom,
            "root_cause": explanation,
            "root_cause_category": category,
            "evidence_required": evidence_tables,
            "evidence_ids": evidence_ids,
            "expected_resolution": "No reconciliation failure exists; retain the evidence and allow normal processing.",
            "reasoning_hops": hops,
            "difficulty": difficulty,
            "injected_timestamp": timestamp,
            "affected_systems": systems,
            "scenario_variant": category.lower(),
            "group_vendor_id": vendor_id,
        }

    def _payment_maps(self):
        by_payment: dict[str, list[dict]] = defaultdict(list)
        by_invoice: dict[str, list[dict]] = defaultdict(list)
        for row in self.ctx.dataset.rows("payment_allocations"):
            by_payment[str(row["payment_id"])].append(row)
            by_invoice[str(row["invoice_id"])].append(row)
        bank = {str(row["payment_reference"]): row for row in self.ctx.dataset.rows("bank_transactions")
                if row["transaction_type"] != "bank fee"}
        return by_payment, by_invoice, bank

    def _exact_po_match(self, case_id: str):
        po_by_id = {str(row["po_id"]): row for row in self.ctx.dataset.rows("purchase_orders")}
        candidates = [row for row in self.ctx.dataset.rows("invoices") if row["po_id"]
                      and money(row["invoice_total"], str(row["currency"])) == money(po_by_id[str(row["po_id"])]["po_total"], str(row["currency"]))
                      and self.ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            return None
        invoice = self.ctx.rng.choice(candidates)
        po = po_by_id[str(invoice["po_id"])]
        self.ctx.claim(("invoice", str(invoice["invoice_id"])), ("purchase_order", str(po["po_id"])))
        return self._case(case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
                          [("invoice", str(invoice["invoice_id"])), ("purchase_order", str(po["po_id"]))],
                          "The invoice resembles other PO variance cases but matches the authorized PO amount and lines.",
                          "The PO-backed invoice is fully within authorization and has no amount or quantity exception.",
                          "LEGITIMATE_EXACT_PO_MATCH", ["invoices", "invoice_lines", "purchase_orders", "po_lines"],
                          [str(invoice["invoice_id"]), str(po["po_id"])], str(invoice["created_at"]),
                          ["ERP-AP", "ERP-Procurement"], "easy", 2)

    def _batch_payment(self, case_id: str):
        by_payment, _, bank = self._payment_maps()
        payments = {str(row["payment_id"]): row for row in self.ctx.dataset.rows("payments")}
        candidates = [payments[payment_id] for payment_id, rows in by_payment.items() if len(rows) > 1 and payment_id in payments
                      and str(payments[payment_id]["reference_number"]) in bank
                      and self.ctx.available("payment", payment_id)]
        if not candidates:
            return None
        payment = self.ctx.rng.choice(candidates)
        allocations = by_payment[str(payment["payment_id"])]
        bank_row = bank[str(payment["reference_number"])]
        invoice_ids = [str(row["invoice_id"]) for row in allocations]
        self.ctx.claim(("payment", str(payment["payment_id"])), *(("invoice", value) for value in invoice_ids))
        return self._case(case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"])), *(("invoice", value) for value in invoice_ids),
                           ("bank_transaction", str(bank_row["bank_transaction_id"]))],
                          "One bank debit is larger than either linked invoice because it settles multiple invoices as a batch.",
                          "The allocations sum exactly to a legitimate multi-invoice payment and its bank settlement.",
                          "LEGITIMATE_BATCH_PAYMENT", ["payments", "payment_allocations", "invoices", "bank_transactions"],
                          [str(payment["payment_id"]), *invoice_ids, str(bank_row["bank_transaction_id"])],
                          str(bank_row["posted_date"]), ["ERP-AP", "Bank"], "easy", 2)

    def _split_payment(self, case_id: str):
        by_payment, by_invoice, bank = self._payment_maps()
        invoices = {str(row["invoice_id"]): row for row in self.ctx.dataset.rows("invoices")}
        payments = {str(row["payment_id"]): row for row in self.ctx.dataset.rows("payments")}
        candidates = [invoices[invoice_id] for invoice_id, rows in by_invoice.items() if len(rows) > 1 and invoice_id in invoices
                      and self.ctx.available("invoice", invoice_id)]
        if not candidates:
            return None
        invoice = self.ctx.rng.choice(candidates)
        payment_ids = [str(row["payment_id"]) for row in by_invoice[str(invoice["invoice_id"])]]
        if any(value not in payments or str(payments[value]["reference_number"]) not in bank for value in payment_ids):
            return None
        self.ctx.claim(("invoice", str(invoice["invoice_id"])), *(("payment", value) for value in payment_ids))
        bank_ids = [str(bank[str(payments[value]["reference_number"])]["bank_transaction_id"]) for value in payment_ids]
        return self._case(case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
                          [("invoice", str(invoice["invoice_id"])), *(("payment", value) for value in payment_ids)],
                          "Multiple smaller bank debits relate to one invoice, which can resemble duplicate payment activity.",
                          "The scheduled split payments are distinct and their allocations sum exactly to the invoice obligation.",
                          "LEGITIMATE_SPLIT_PAYMENT", ["invoices", "payment_allocations", "payments", "bank_transactions"],
                          [str(invoice["invoice_id"]), *payment_ids, *bank_ids], max(str(payments[value]["created_at"]) for value in payment_ids),
                          ["ERP-AP", "Bank"], "easy", 2)

    def _weekend_settlement(self, case_id: str):
        _, _, bank = self._payment_maps()
        candidates = []
        for payment in self.ctx.dataset.rows("payments"):
            transaction = bank.get(str(payment["reference_number"]))
            if transaction and payment["payment_method"] == "ACH" and self.ctx.available("payment", str(payment["payment_id"])):
                elapsed = (parse_date(str(transaction["posted_date"])) - parse_date(str(payment["payment_date"]))).days
                if elapsed > 3:
                    candidates.append((payment, transaction))
        if not candidates:
            return None
        payment, transaction = self.ctx.rng.choice(candidates)
        self.ctx.claim(("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"])))
        return self._case(case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"]))],
                          "The ACH bank posting occurs several calendar days after ERP initiation.",
                          "Weekend days extend calendar elapsed time, while settlement remains within the configured business-day window.",
                          "LEGITIMATE_WEEKEND_CLEARING", ["payments", "bank_transactions"],
                          [str(payment["payment_id"]), str(transaction["bank_transaction_id"])], str(transaction["posted_date"]),
                          ["ERP-AP", "Bank"], "medium", 3)

    def _po_tolerance(self, case_id: str):
        allocated = {str(row["invoice_id"]) for row in self.ctx.dataset.rows("payment_allocations")}
        candidates = [row for row in self.ctx.dataset.rows("invoices") if row["po_id"] and str(row["invoice_id"]) not in allocated
                      and self.ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            return None
        invoice = self.ctx.rng.choice(candidates)
        lines = [row for row in self.ctx.dataset.rows("invoice_lines") if row["invoice_id"] == invoice["invoice_id"]]
        line = lines[0]
        currency = str(invoice["currency"])
        target_delta = money(decimal(line["line_amount"]) * decimal("0.01"), currency)
        new_unit = money((decimal(line["line_amount"]) + target_delta) / decimal(line["quantity"]), currency)
        new_amount = money(decimal(new_unit) * decimal(line["quantity"]), currency)
        delta = money(new_amount - decimal(line["line_amount"]), currency)
        if delta <= 0:
            return None
        reason = "Approved invoice price variance remains inside the configured two-percent PO tolerance"
        self.ctx.mutate(case_id, "invoice_lines", line, "unit_price", new_unit, reason)
        self.ctx.mutate(case_id, "invoice_lines", line, "line_amount", new_amount, reason)
        self.ctx.mutate(case_id, "invoices", invoice, "subtotal", money(decimal(invoice["subtotal"]) + delta, currency), reason)
        self.ctx.mutate(case_id, "invoices", invoice, "invoice_total", money(decimal(invoice["invoice_total"]) + delta, currency), reason)
        gl_rows = [row for row in self.ctx.dataset.rows("gl_entries") if row["transaction_type"] == "invoice"
                   and row["source_transaction_id"] == invoice["invoice_id"]]
        debit = next(row for row in gl_rows if decimal(row["debit"]) and row["gl_account"] == line["gl_account"])
        credit = next(row for row in gl_rows if row["gl_account"] == "200000-ACCOUNTS-PAYABLE")
        self.ctx.mutate(case_id, "gl_entries", debit, "debit", money(decimal(debit["debit"]) + delta, currency), reason)
        self.ctx.mutate(case_id, "gl_entries", credit, "credit", money(decimal(credit["credit"]) + delta, currency), reason)
        self.ctx.claim(("invoice", str(invoice["invoice_id"])), ("purchase_order", str(invoice["po_id"])))
        return self._case(case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
                          [("invoice", str(invoice["invoice_id"])), ("purchase_order", str(invoice["po_id"]))],
                          "The invoice is slightly above its PO, resembling an amount-mismatch failure.",
                          "The variance is one percent and is explicitly permitted by the configured two-percent PO tolerance.",
                          "LEGITIMATE_PO_TOLERANCE", ["invoices", "invoice_lines", "purchase_orders", "po_lines"],
                          [str(invoice["invoice_id"]), str(invoice["po_id"])], str(invoice["created_at"]),
                          ["ERP-AP", "ERP-Procurement", "ERP-GL"], "easy", 2)

    def _check_clearing(self, case_id: str):
        _, _, bank = self._payment_maps()
        candidates = [(row, bank[str(row["reference_number"])]) for row in self.ctx.dataset.rows("payments")
                      if row["payment_method"] == "check" and str(row["reference_number"]) in bank
                      and self.ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            return None
        payment, transaction = self.ctx.rng.choice(candidates)
        self.ctx.claim(("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"])))
        return self._case(case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"]))],
                          "The check clears much later than electronic payments in the same period.",
                          "The posting occurs inside the configured ten-business-day check-clearing window.",
                          "LEGITIMATE_CHECK_CLEARING", ["payments", "bank_transactions"],
                          [str(payment["payment_id"]), str(transaction["bank_transaction_id"])], str(transaction["posted_date"]),
                          ["ERP-AP", "Bank"], "medium", 3)

    def _accounted_bank_fee(self, case_id: str):
        fees = [row for row in self.ctx.dataset.rows("bank_transactions") if row["transaction_type"] == "bank fee"
                and self.ctx.available("bank_transaction", str(row["bank_transaction_id"]))]
        if not fees:
            return None
        fee = self.ctx.rng.choice(fees)
        journal = next((row for row in self.ctx.dataset.rows("gl_entries") if row["transaction_type"] == "bank_fee"
                        and row["source_transaction_id"] == fee["bank_transaction_id"]), None)
        payment = next((row for row in self.ctx.dataset.rows("payments") if row["reference_number"] == fee["payment_reference"]), None)
        if journal is None or payment is None or not self.ctx.available("payment", str(payment["payment_id"])):
            return None
        self.ctx.claim(("payment", str(payment["payment_id"])), ("bank_transaction", str(fee["bank_transaction_id"])))
        return self._case(case_id, "bank_transaction", str(fee["bank_transaction_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"])), ("bank_transaction", str(fee["bank_transaction_id"])),
                           ("gl_journal", str(journal["journal_id"]))],
                          "A bank debit has no ERP payment record and superficially resembles an unrecorded disbursement.",
                          "The debit is a separately identified bank fee with a balanced fee-expense journal.",
                          "LEGITIMATE_ACCOUNTED_BANK_FEE", ["bank_transactions", "gl_entries", "payments"],
                          [str(fee["bank_transaction_id"]), str(journal["journal_id"]), str(payment["payment_id"])],
                          str(fee["posted_date"]), ["Bank", "ERP-GL", "ERP-AP"], "medium", 3)

    def _paid_on_due_date(self, case_id: str):
        _, _, bank = self._payment_maps()
        invoice_by_id = {str(row["invoice_id"]): row for row in self.ctx.dataset.rows("invoices")}
        payment_by_id = {str(row["payment_id"]): row for row in self.ctx.dataset.rows("payments")}
        candidates = []
        for allocation in self.ctx.dataset.rows("payment_allocations"):
            payment = payment_by_id.get(str(allocation["payment_id"]))
            invoice = invoice_by_id.get(str(allocation["invoice_id"]))
            if payment and invoice and payment["payment_date"] == invoice["due_date"] \
                    and str(payment["reference_number"]) in bank and self.ctx.available("payment", str(payment["payment_id"])):
                candidates.append((invoice, payment, bank[str(payment["reference_number"])]))
        if not candidates:
            return None
        invoice, payment, transaction = self.ctx.rng.choice(candidates)
        self.ctx.claim(("invoice", str(invoice["invoice_id"])), ("payment", str(payment["payment_id"])))
        return self._case(case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
                          [("invoice", str(invoice["invoice_id"])), ("payment", str(payment["payment_id"])),
                           ("bank_transaction", str(transaction["bank_transaction_id"]))],
                          "The payment was initiated exactly on the contractual due date.",
                          "Due-date payment complies with the invoice terms, approval timeline, allocation, and bank settlement.",
                          "LEGITIMATE_DUE_DATE_PAYMENT", ["invoices", "approval_events", "payments", "bank_transactions"],
                          [str(invoice["invoice_id"]), str(payment["payment_id"]), str(transaction["bank_transaction_id"])],
                          str(payment["created_at"]), ["ERP-Workflow", "ERP-AP", "Bank"], "easy", 2)

    def _recent_pending_settlement(self, case_id: str):
        by_payment, _, bank = self._payment_maps()
        candidates = [row for row in self.ctx.dataset.rows("payments") if str(row["reference_number"]) in bank
                      and len(by_payment.get(str(row["payment_id"]), [])) == 1
                      and self.ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            return None
        payment = self.ctx.rng.choice(candidates)
        transaction = bank[str(payment["reference_number"])]
        new_date = parse_date(self.ctx.config["date_range"]["end"]) - timedelta(days=1)
        reason = "Payment was initiated at the observation cutoff and remains inside its normal clearing window"
        self.ctx.remove(case_id, "bank_transactions", transaction, reason)
        self.ctx.mutate(case_id, "payments", payment, "payment_date", new_date.isoformat(), reason)
        self.ctx.mutate(case_id, "payments", payment, "created_at", new_date.isoformat() + "T08:00:00", reason)
        self.ctx.mutate(case_id, "payments", payment, "payment_status", "submitted", reason)
        self.ctx.mutate(case_id, "payments", payment, "settlement_status", "pending", reason)
        allocation = by_payment[str(payment["payment_id"])][0]
        self.ctx.mutate(case_id, "payment_allocations", allocation, "allocation_date", new_date.isoformat(), reason)
        for row in self.ctx.dataset.rows("gl_entries"):
            if row["transaction_type"] == "payment" and row["source_transaction_id"] == payment["payment_id"]:
                self.ctx.mutate(case_id, "gl_entries", row, "posting_date", new_date.isoformat(), reason)
                self.ctx.mutate(case_id, "gl_entries", row, "accounting_period", accounting_period(new_date), reason)
        self.ctx.claim(("payment", str(payment["payment_id"])))
        return self._case(case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"]))],
                          "A newly submitted ERP payment has no bank transaction at the dataset cutoff.",
                          "Only one day has elapsed and the payment remains pending inside its method-specific clearing window.",
                          "LEGITIMATE_PENDING_SETTLEMENT", ["payments", "bank_transactions", "payment_allocations"],
                          [str(payment["payment_id"])], str(payment["created_at"]), ["ERP-AP", "Bank"], "medium", 3)

    def _net_fee_with_accounting(self, case_id: str):
        _, _, bank = self._payment_maps()
        fee_refs = {str(row["payment_reference"]) for row in self.ctx.dataset.rows("bank_transactions")
                    if row["transaction_type"] == "bank fee"}
        candidates = [row for row in self.ctx.dataset.rows("payments") if str(row["reference_number"]) in bank
                      and str(row["reference_number"]) not in fee_refs and decimal(row["payment_amount"]) > 100
                      and self.ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            return None
        payment = self.ctx.rng.choice(candidates)
        transaction = bank[str(payment["reference_number"])]
        currency = str(payment["payment_currency"])
        fee = money("25", currency)
        net = money(decimal(payment["payment_amount"]) - decimal(fee), currency)
        reason = "A documented net-settlement fee has a corresponding approved bank-fee journal"
        self.ctx.mutate(case_id, "bank_transactions", transaction, "amount", net, reason)
        journal_id = self.ctx.ids.next("JE")
        for account, debit, credit in (("710000-BANK-FEES", fee, 0), ("100000-CASH", 0, fee)):
            self.ctx.add(
                case_id, "gl_entries",
                {
                    "journal_id": journal_id,
                    "journal_line_id": self.ctx.ids.next("JEL"),
                    "transaction_type": "bank_fee",
                    "source_transaction_id": transaction["bank_transaction_id"],
                    "posting_date": transaction["posted_date"],
                    "accounting_period": accounting_period(str(transaction["posted_date"])),
                    "gl_account": account,
                    "debit": money(debit, currency),
                    "credit": money(credit, currency),
                    "currency": currency,
                    "department": "Finance",
                    "cost_center": "CC-03-01",
                    "memo": "Documented net settlement fee",
                    "source_system": "ERP-GL",
                }, reason,
            )
        self.ctx.claim(("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"])))
        return self._case(case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"])),
                           ("gl_journal", journal_id)],
                          "The bank settlement is 25 units below the ERP payment, matching anomalous amount-mismatch cases.",
                          "A documented 25-unit net-settlement fee has a valid balanced fee journal, so the difference is reconciled.",
                          "LEGITIMATE_NET_FEE_ACCOUNTING", ["payments", "bank_transactions", "gl_entries"],
                          [str(payment["payment_id"]), str(transaction["bank_transaction_id"]), journal_id],
                          str(transaction["posted_date"]), ["ERP-AP", "Bank", "ERP-GL"], "medium", 4)

    def _generic_valid_payment(self, case_id: str):
        _, _, bank = self._payment_maps()
        candidates = [row for row in self.ctx.dataset.rows("payments") if str(row["reference_number"]) in bank
                      and self.ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            # Reuse is allowed only as a last-resort development-scale context case.
            candidates = [row for row in self.ctx.dataset.rows("payments") if str(row["reference_number"]) in bank]
        if not candidates:
            raise RuntimeError("No valid payment remains for a non-failure case")
        payment = self.ctx.rng.choice(candidates)
        transaction = bank[str(payment["reference_number"])]
        self.ctx.claim(("payment", str(payment["payment_id"])))
        return self._case(case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"]))],
                          "The payment appears in a reconciliation review sample.",
                          "Payment amount, allocation, journal, approval, and bank settlement reconcile exactly.",
                          "LEGITIMATE_FULL_RECONCILIATION", ["payments", "payment_allocations", "gl_entries", "bank_transactions"],
                          [str(payment["payment_id"]), str(transaction["bank_transaction_id"])],
                          str(transaction["posted_date"]), ["ERP-AP", "ERP-GL", "Bank"], "easy", 2)

    def _credit_memo(self, case_id: str):
        allocated = {str(row["invoice_id"]) for row in self.ctx.dataset.rows("payment_allocations")}
        candidates = [row for row in self.ctx.dataset.rows("invoices") if str(row["invoice_id"]) not in allocated
                      and decimal(row["invoice_total"]) > 0 and self.ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            return None
        original = self.ctx.rng.choice(candidates)
        original_lines = [row for row in self.ctx.dataset.rows("invoice_lines") if row["invoice_id"] == original["invoice_id"]]
        credit = dict(original)
        credit_id = self.ctx.ids.next("INV")
        credit.update(
            {
                "invoice_id": credit_id,
                "po_id": "",
                "invoice_number": f"CM-{str(original['invoice_number'])[-10:]}",
                "subtotal": -decimal(original["subtotal"]),
                "tax": -decimal(original["tax"]),
                "shipping": -decimal(original["shipping"]),
                "invoice_total": -decimal(original["invoice_total"]),
                "status": "credit_applied",
                "duplicate_reference": str(original["invoice_id"]),
            }
        )
        reason = "Supplier credit memo reverses a documented invoice obligation"
        self.ctx.add(case_id, "invoices", credit, reason)
        credit_line_ids: list[str] = []
        for line in original_lines:
            cloned = dict(line)
            cloned.update(
                {
                    "invoice_id": credit_id,
                    "invoice_line_id": self.ctx.ids.next("INVL"),
                    "po_line_id": "",
                    "unit_price": -decimal(line["unit_price"]),
                    "line_amount": -decimal(line["line_amount"]),
                }
            )
            credit_line_ids.append(str(cloned["invoice_line_id"]))
            self.ctx.add(case_id, "invoice_lines", cloned, reason)
        journal_id = self.ctx.ids.next("JE")
        currency = str(original["currency"])
        entries = [("200000-ACCOUNTS-PAYABLE", original["invoice_total"], 0, "Credit memo reduces payable")]
        entries.extend((str(line["gl_account"]), 0, line["line_amount"], "Credit memo reverses expense") for line in original_lines)
        if decimal(original["tax"]):
            entries.append(("141000-RECOVERABLE-TAX", 0, original["tax"], "Credit memo reverses tax"))
        if decimal(original["shipping"]):
            entries.append(("625000-FREIGHT", 0, original["shipping"], "Credit memo reverses freight"))
        for account, debit, credit_amount, memo in entries:
            self.ctx.add(
                case_id, "gl_entries",
                {
                    "journal_id": journal_id,
                    "journal_line_id": self.ctx.ids.next("JEL"),
                    "transaction_type": "credit_memo",
                    "source_transaction_id": credit_id,
                    "posting_date": credit["received_date"],
                    "accounting_period": accounting_period(str(credit["received_date"])),
                    "gl_account": account,
                    "debit": money(debit, currency),
                    "credit": money(credit_amount, currency),
                    "currency": currency,
                    "department": str(original_lines[0]["department"]),
                    "cost_center": str(original_lines[0]["cost_center"]),
                    "memo": memo,
                    "source_system": "ERP-GL",
                }, reason,
            )
        self.ctx.edge("invoice", credit_id, "credits", "invoice", str(original["invoice_id"]))
        self.ctx.claim(("invoice", str(original["invoice_id"])), ("invoice", credit_id))
        return self._case(case_id, "invoice", credit_id, str(original["vendor_id"]),
                          [("invoice", str(original["invoice_id"])), ("invoice", credit_id), ("gl_journal", journal_id)],
                          "A negative invoice-like record could be mistaken for an impossible amount or data error.",
                          "It is a documented supplier credit memo with a balanced journal that reverses the original payable and expense.",
                          "LEGITIMATE_CREDIT_MEMO", ["invoices", "invoice_lines", "gl_entries"],
                          [str(original["invoice_id"]), credit_id, journal_id, *credit_line_ids[:1]], str(credit["created_at"]),
                          ["ERP-AP", "ERP-GL"], "medium", 3)

    def _invoice_cancellation(self, case_id: str):
        allocated = {str(row["invoice_id"]) for row in self.ctx.dataset.rows("payment_allocations")}
        candidates = [row for row in self.ctx.dataset.rows("invoices") if str(row["invoice_id"]) not in allocated
                      and decimal(row["invoice_total"]) > 0 and self.ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            return None
        invoice = self.ctx.rng.choice(candidates)
        reason = "Invoice was canceled before payment and its accounting was explicitly reversed"
        self.ctx.mutate(case_id, "invoices", invoice, "status", "canceled", reason)
        journal_id = self.ctx.ids.next("JE")
        currency = str(invoice["currency"])
        for account, debit, credit_amount, memo in (
            ("200000-ACCOUNTS-PAYABLE", invoice["invoice_total"], 0, "Canceled invoice clears payable"),
            ("699999-CANCELLED-INVOICE-CLEARING", 0, invoice["invoice_total"], "Canceled invoice reversal"),
        ):
            self.ctx.add(
                case_id, "gl_entries",
                {
                    "journal_id": journal_id,
                    "journal_line_id": self.ctx.ids.next("JEL"),
                    "transaction_type": "invoice_cancellation",
                    "source_transaction_id": invoice["invoice_id"],
                    "posting_date": invoice["received_date"],
                    "accounting_period": accounting_period(str(invoice["received_date"])),
                    "gl_account": account,
                    "debit": money(debit, currency),
                    "credit": money(credit_amount, currency),
                    "currency": currency,
                    "department": "Finance",
                    "cost_center": "CC-03-01",
                    "memo": memo,
                    "source_system": "ERP-GL",
                }, reason,
            )
        audit_id = self.ctx.audit(case_id, "invoice", str(invoice["invoice_id"]), "invoice_canceled",
                                  str(invoice["received_date"]) + "T18:00:00", "SYSTEM-AP-WORKFLOW",
                                  "status", "approved", "canceled", "ERP-AP")
        self.ctx.claim(("invoice", str(invoice["invoice_id"])), ("gl_journal", journal_id))
        return self._case(case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
                          [("invoice", str(invoice["invoice_id"])), ("gl_journal", journal_id), ("audit_event", audit_id)],
                          "An approved invoice has no payment and no future settlement.",
                          "The invoice was legitimately canceled before payment and a balanced reversal journal records the cancellation.",
                          "LEGITIMATE_INVOICE_CANCELLATION", ["invoices", "payments", "gl_entries", "audit_log"],
                          [str(invoice["invoice_id"]), journal_id, audit_id], str(invoice["received_date"]) + "T18:00:00",
                          ["ERP-AP", "ERP-GL"], "medium", 3)

    def _payment_reversal(self, case_id: str):
        by_payment, _, bank = self._payment_maps()
        candidates = [row for row in self.ctx.dataset.rows("payments") if str(row["reference_number"]) in bank
                      and self.ctx.available("payment", str(row["payment_id"]))
                      and all(self.ctx.available("invoice", str(allocation["invoice_id"]))
                              for allocation in by_payment.get(str(row["payment_id"]), []))]
        if not candidates:
            return None
        payment = self.ctx.rng.choice(candidates)
        original_bank = bank[str(payment["reference_number"])]
        reason = "A posted payment was fully reversed with matching bank and GL evidence"
        self.ctx.mutate(case_id, "payments", payment, "payment_status", "reversed", reason)
        self.ctx.mutate(case_id, "payments", payment, "settlement_status", "reversed", reason)
        for allocation in by_payment[str(payment["payment_id"])]:
            invoice = next(row for row in self.ctx.dataset.rows("invoices") if row["invoice_id"] == allocation["invoice_id"])
            self.ctx.mutate(case_id, "invoices", invoice, "status", "approved", reason)
        reversal_id = self.ctx.ids.next("BT")
        posted = (parse_date(str(original_bank["posted_date"])) + timedelta(days=1)).isoformat()
        reversal = dict(original_bank)
        reversal.update(
            {
                "bank_transaction_id": reversal_id,
                "transaction_date": posted,
                "posted_date": posted,
                "transaction_type": "payment reversal",
                "direction": "credit",
                "bank_reference": f"REVERSAL-{self.ctx.ids.counters['BT']:010d}",
                "status": "posted",
            }
        )
        self.ctx.add(case_id, "bank_transactions", reversal, reason)
        journal_id = self.ctx.ids.next("JE")
        currency = str(payment["payment_currency"])
        for account, debit, credit_amount in (
            ("100000-CASH", payment["payment_amount"], 0),
            ("200000-ACCOUNTS-PAYABLE", 0, payment["payment_amount"]),
        ):
            self.ctx.add(
                case_id, "gl_entries",
                {
                    "journal_id": journal_id,
                    "journal_line_id": self.ctx.ids.next("JEL"),
                    "transaction_type": "payment_reversal",
                    "source_transaction_id": payment["payment_id"],
                    "posting_date": posted,
                    "accounting_period": accounting_period(posted),
                    "gl_account": account,
                    "debit": money(debit, currency),
                    "credit": money(credit_amount, currency),
                    "currency": currency,
                    "department": "Finance",
                    "cost_center": "CC-03-01",
                    "memo": "Documented payment reversal",
                    "source_system": "ERP-GL",
                }, reason,
            )
        self.ctx.claim(("payment", str(payment["payment_id"])), ("bank_transaction", str(original_bank["bank_transaction_id"])),
                       ("bank_transaction", reversal_id))
        return self._case(case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"])), ("bank_transaction", str(original_bank["bank_transaction_id"])),
                           ("bank_transaction", reversal_id), ("gl_journal", journal_id)],
                          "A bank debit is followed by an equal credit and the invoices are no longer marked paid.",
                          "The payment was legitimately reversed, with matching bank credit and balanced GL reversal evidence.",
                          "LEGITIMATE_PAYMENT_REVERSAL", ["payments", "payment_allocations", "invoices", "bank_transactions", "gl_entries"],
                          [str(payment["payment_id"]), str(original_bank["bank_transaction_id"]), reversal_id, journal_id], posted,
                          ["ERP-AP", "ERP-GL", "Bank"], "hard", 4)

    def _foreign_exchange_settlement(self, case_id: str):
        _, _, bank = self._payment_maps()
        rates = {"EUR": decimal("1.08"), "GBP": decimal("1.27"), "CAD": decimal("0.74"), "JPY": decimal("0.0068")}
        candidates = [row for row in self.ctx.dataset.rows("payments") if row["payment_currency"] in rates
                      and str(row["reference_number"]) in bank and self.ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            return None
        payment = self.ctx.rng.choice(candidates)
        transaction = bank[str(payment["reference_number"])]
        rate = rates[str(payment["payment_currency"])]
        usd_amount = money(decimal(payment["payment_amount"]) * rate, "USD")
        reason = "Bank settled the foreign-currency payment in USD using a documented conversion rate"
        self.ctx.mutate(case_id, "bank_transactions", transaction, "amount", usd_amount, reason)
        self.ctx.mutate(case_id, "bank_transactions", transaction, "currency", "USD", reason)
        audit_id = self.ctx.audit(case_id, "bank_transaction", str(transaction["bank_transaction_id"]), "fx_conversion_applied",
                                  str(transaction["posted_date"]) + "T17:00:00", "SYSTEM-BANK-FX",
                                  "fx_rate", "", str(rate), "Bank")
        journal_id = self.ctx.ids.next("JE")
        for account, debit, credit_amount in (("799100-FX-SETTLEMENT", "1.00", 0), ("799199-FX-CLEARING", 0, "1.00")):
            self.ctx.add(
                case_id, "gl_entries",
                {
                    "journal_id": journal_id,
                    "journal_line_id": self.ctx.ids.next("JEL"),
                    "transaction_type": "fx_settlement",
                    "source_transaction_id": transaction["bank_transaction_id"],
                    "posting_date": transaction["posted_date"],
                    "accounting_period": accounting_period(str(transaction["posted_date"])),
                    "gl_account": account,
                    "debit": money(debit, "USD"),
                    "credit": money(credit_amount, "USD"),
                    "currency": "USD",
                    "department": "Finance",
                    "cost_center": "CC-03-01",
                    "memo": "Documented FX settlement clearing",
                    "source_system": "ERP-GL",
                }, reason,
            )
        self.ctx.claim(("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"])))
        return self._case(case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
                          [("payment", str(payment["payment_id"])), ("bank_transaction", str(transaction["bank_transaction_id"])),
                           ("gl_journal", journal_id), ("audit_event", audit_id)],
                          "ERP and bank values/currencies differ, resembling an unexplained amount mismatch.",
                          f"The bank applied a documented {rate} USD/{payment['payment_currency']} conversion and the FX clearing evidence is balanced.",
                          "LEGITIMATE_FX_SETTLEMENT", ["payments", "bank_transactions", "gl_entries", "audit_log"],
                          [str(payment["payment_id"]), str(transaction["bank_transaction_id"]), journal_id, audit_id],
                          str(transaction["posted_date"]) + "T17:00:00", ["ERP-AP", "Bank", "ERP-GL"], "hard", 4)

    def _payment_terms_change(self, case_id: str):
        candidates = [row for row in self.ctx.dataset.rows("invoices") if self.ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            return None
        invoice = self.ctx.rng.choice(candidates)
        terms = ["NET15", "NET30", "NET45", "NET60"]
        new_terms = str(invoice["payment_terms"])
        old_terms = next(value for value in terms if value != new_terms)
        changed = parse_date(str(invoice["invoice_date"])) - timedelta(days=10)
        vendor = next(row for row in self.ctx.dataset.rows("vendors") if row["vendor_id"] == invoice["vendor_id"])
        employee = next(row for row in self.ctx.dataset.rows("employees") if row["active_status"] == "active")
        change_id = self.ctx.ids.next("CHG")
        reason = "Payment terms were validly amended before the invoice was created"
        self.ctx.add(
            case_id, "vendor_change_log",
            {
                "change_id": change_id,
                "vendor_id": vendor["vendor_id"],
                "field_changed": "payment_terms",
                "old_value": old_terms,
                "new_value": new_terms,
                "changed_at": changed.isoformat() + "T11:00:00",
                "changed_by": employee["employee_id"],
                "change_reason": "Contractual payment terms amendment",
                "source_system": "VendorManagement",
            }, reason,
        )
        self.ctx.edge("vendor_change", change_id, "governs", "invoice", str(invoice["invoice_id"]))
        self.ctx.claim(("invoice", str(invoice["invoice_id"])), ("vendor", str(vendor["vendor_id"])))
        return self._case(case_id, "invoice", str(invoice["invoice_id"]), str(vendor["vendor_id"]),
                          [("invoice", str(invoice["invoice_id"])), ("vendor", str(vendor["vendor_id"])),
                           ("vendor_change", change_id)],
                          "Invoice terms differ from an older vendor-master value.",
                          "The history shows the new terms became effective ten days before invoice creation, so the invoice is correct.",
                          "LEGITIMATE_PRE_INVOICE_TERMS_CHANGE", ["invoices", "vendors", "vendor_change_log"],
                          [str(invoice["invoice_id"]), str(vendor["vendor_id"]), change_id], changed.isoformat() + "T11:00:00",
                          ["VendorManagement", "ERP-AP"], "easy", 2)

    def _split_cost_center_accounting(self, case_id: str):
        lines_by_invoice: dict[str, list[dict]] = defaultdict(list)
        for line in self.ctx.dataset.rows("invoice_lines"):
            lines_by_invoice[str(line["invoice_id"])].append(line)
        invoices = {str(row["invoice_id"]): row for row in self.ctx.dataset.rows("invoices")}
        candidates = [invoices[invoice_id] for invoice_id, lines in lines_by_invoice.items() if len(lines) >= 2
                      and invoice_id in invoices and self.ctx.available("invoice", invoice_id)]
        if not candidates:
            return None
        invoice = self.ctx.rng.choice(candidates)
        line = lines_by_invoice[str(invoice["invoice_id"])][1]
        old_cost = str(line["cost_center"])
        new_cost = "CC-ALLOC-02" if old_cost != "CC-ALLOC-02" else "CC-ALLOC-03"
        reason = "Approved invoice accounting is split across benefiting cost centers"
        self.ctx.mutate(case_id, "invoice_lines", line, "cost_center", new_cost, reason)
        gl_candidates = [row for row in self.ctx.dataset.rows("gl_entries") if row["transaction_type"] == "invoice"
                         and row["source_transaction_id"] == invoice["invoice_id"] and row["gl_account"] == line["gl_account"]
                         and money(row["debit"]) == money(line["line_amount"]) and row["cost_center"] == old_cost]
        if gl_candidates:
            self.ctx.mutate(case_id, "gl_entries", gl_candidates[0], "cost_center", new_cost, reason)
            journal_id = str(gl_candidates[0]["journal_id"])
        else:
            journal_id = next(str(row["journal_id"]) for row in self.ctx.dataset.rows("gl_entries")
                              if row["source_transaction_id"] == invoice["invoice_id"])
        self.ctx.claim(("invoice", str(invoice["invoice_id"])), ("gl_journal", journal_id))
        return self._case(case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
                          [("invoice", str(invoice["invoice_id"])), ("invoice_line", str(line["invoice_line_id"])),
                           ("gl_journal", journal_id)],
                          "One invoice posts expense lines to more than one cost center.",
                          "The split is a legitimate allocation across benefiting cost centers and the journal remains balanced.",
                          "LEGITIMATE_SPLIT_COST_CENTER", ["invoices", "invoice_lines", "gl_entries"],
                          [str(invoice["invoice_id"]), str(line["invoice_line_id"]), journal_id], str(invoice["created_at"]),
                          ["ERP-AP", "ERP-GL"], "easy", 2)


def generate_hard_negatives(ctx: InjectionContext, start_number: int) -> list[dict[str, Any]]:
    count = int(ctx.config["scale"]["non_failure_cases"])
    return HardNegativeGenerator(ctx).generate(start_number, count)
