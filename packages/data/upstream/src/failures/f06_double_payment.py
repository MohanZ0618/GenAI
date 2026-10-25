"""F06: a valid invoice obligation is paid twice."""

from __future__ import annotations

from datetime import timedelta

from src.failures.base import FailureInjector, InjectionContext, add_payment_gl_and_bank
from src.utils.dates import at_time, parse_date


class DoublePaymentInjector(FailureInjector):
    failure_type = "F06_INVOICE_PAID_TWICE"
    difficulty = "medium"
    reasoning_hops = 3
    severity = "high"

    def inject(self, ctx: InjectionContext, case_id: str):
        allocations_by_invoice: dict[str, list[dict]] = {}
        for row in ctx.dataset.rows("payment_allocations"):
            allocations_by_invoice.setdefault(str(row["invoice_id"]), []).append(row)
        payments = {str(row["payment_id"]): row for row in ctx.dataset.rows("payments")}
        candidates = [row for row in ctx.dataset.rows("invoices") if row["status"] == "paid"
                      and allocations_by_invoice.get(str(row["invoice_id"]))
                      and ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            raise RuntimeError("F06 has no eligible paid invoice")
        invoice = ctx.rng.choice(candidates)
        prior_allocations = allocations_by_invoice[str(invoice["invoice_id"])]
        last_payment = max((payments[str(row["payment_id"])] for row in prior_allocations), key=lambda row: str(row["payment_date"]))
        end = parse_date(ctx.config["date_range"]["end"])
        payment_date = min(parse_date(str(last_payment["payment_date"])) + timedelta(days=ctx.rng.py.randint(2, 7)), end)
        vendor = next(row for row in ctx.dataset.rows("vendors") if row["vendor_id"] == invoice["vendor_id"])
        payment_id = ctx.ids.next("PAY")
        payment = dict(last_payment)
        payment.update(
            {
                "payment_id": payment_id,
                "payment_date": payment_date.isoformat(),
                "payment_amount": invoice["invoice_total"],
                "reference_number": f"PMTREF-{ctx.ids.counters['PAY'] + (ctx.config['seed'] % 997):010d}",
                "created_at": at_time(payment_date, 8),
            }
        )
        reason = "A second payment run selected an invoice whose obligation had already been fully settled"
        ctx.add(case_id, "payments", payment, reason)
        ctx.add(
            case_id,
            "payment_allocations",
            {
                "payment_id": payment_id,
                "invoice_id": invoice["invoice_id"],
                "allocated_amount": invoice["invoice_total"],
                "allocation_date": payment_date.isoformat(),
                "source_system": "ERP-AP",
            },
            reason,
        )
        journal_id, bank_id = add_payment_gl_and_bank(ctx, case_id, payment, vendor, reason)
        first_payment_id = str(prior_allocations[0]["payment_id"])
        ctx.edge("payment", payment_id, "settles", "invoice", str(invoice["invoice_id"]))
        ctx.claim(("invoice", str(invoice["invoice_id"])), ("payment", first_payment_id), ("payment", payment_id))
        return self.case(
            case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
            [("invoice", str(invoice["invoice_id"])), ("payment", first_payment_id), ("payment", payment_id),
             ("bank_transaction", str(bank_id)), ("gl_journal", journal_id)],
            "Successful payment allocations exceed the invoice obligation by one full invoice amount.",
            "A second payment run did not recognize that the invoice had already been fully settled.",
            "DUPLICATE_DISBURSEMENT", ["invoices", "payment_allocations", "payments", "bank_transactions"],
            [str(invoice["invoice_id"]), first_payment_id, payment_id, str(bank_id)],
            "Stop or recover the second payment, reverse its allocation and journal, and repair paid-status controls.",
            str(payment["created_at"]), ["ERP-AP", "ERP-GL", "Bank"], "separate_payment_runs",
        )

