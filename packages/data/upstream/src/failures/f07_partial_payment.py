"""F07: residual invoice balance hidden by an incorrect paid status."""

from __future__ import annotations

from collections import defaultdict

from src.failures.base import FailureInjector, InjectionContext
from src.utils.money import decimal, money


class PartialPaymentInjector(FailureInjector):
    failure_type = "F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE"
    difficulty = "medium"
    reasoning_hops = 3

    def inject(self, ctx: InjectionContext, case_id: str):
        by_invoice: dict[str, list[dict]] = defaultdict(list)
        by_payment: dict[str, list[dict]] = defaultdict(list)
        for row in ctx.dataset.rows("payment_allocations"):
            by_invoice[str(row["invoice_id"])].append(row)
            by_payment[str(row["payment_id"])].append(row)
        candidates = []
        for invoice in ctx.dataset.rows("invoices"):
            allocations = by_invoice.get(str(invoice["invoice_id"]), [])
            if len(allocations) == 1 and len(by_payment[str(allocations[0]["payment_id"])]) == 1 \
                    and ctx.available("invoice", str(invoice["invoice_id"])):
                candidates.append((invoice, allocations[0]))
        if not candidates:
            raise RuntimeError("F07 has no eligible one-to-one payment")
        invoice, allocation = ctx.rng.choice(candidates)
        payment = next(row for row in ctx.dataset.rows("payments") if row["payment_id"] == allocation["payment_id"])
        currency = str(invoice["currency"])
        new_amount = money(decimal(invoice["invoice_total"]) * decimal("0.60"), currency)
        reason = "A partial disbursement was incorrectly treated as full settlement"
        ctx.mutate(case_id, "payment_allocations", allocation, "allocated_amount", new_amount, reason)
        ctx.mutate(case_id, "payments", payment, "payment_amount", new_amount, reason)
        bank = next(row for row in ctx.dataset.rows("bank_transactions") if row["payment_reference"] == payment["reference_number"]
                    and row["transaction_type"] != "bank fee")
        ctx.mutate(case_id, "bank_transactions", bank, "amount", new_amount, reason)
        journal_rows = [row for row in ctx.dataset.rows("gl_entries") if row["transaction_type"] == "payment"
                        and row["source_transaction_id"] == payment["payment_id"]]
        for row in journal_rows:
            field = "debit" if decimal(row["debit"]) else "credit"
            ctx.mutate(case_id, "gl_entries", row, field, new_amount, reason)
        ctx.claim(("invoice", str(invoice["invoice_id"])), ("payment", str(payment["payment_id"])))
        return self.case(
            case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
            [("invoice", str(invoice["invoice_id"])), ("payment", str(payment["payment_id"])),
             ("bank_transaction", str(bank["bank_transaction_id"])), ("gl_journal", str(journal_rows[0]["journal_id"]))],
            "The invoice is marked paid although its successful allocations cover only 60% of the obligation.",
            "A partial disbursement was propagated correctly to bank and GL but the invoice status was not left partially paid.",
            "RESIDUAL_BALANCE_STATUS_ERROR", ["invoices", "payment_allocations", "payments", "gl_entries", "bank_transactions"],
            [str(invoice["invoice_id"]), str(payment["payment_id"]), str(bank["bank_transaction_id"]),
             str(journal_rows[0]["journal_id"])],
            "Restore the residual payable, change invoice status to partially paid, and schedule or formally resolve the balance.",
            str(payment["created_at"]), ["ERP-AP", "ERP-GL", "Bank"], "incorrect_paid_status",
        )

