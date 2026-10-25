"""F05: completed payment without a valid payable allocation."""

from __future__ import annotations

from datetime import timedelta

from src.failures.base import FailureInjector, InjectionContext, add_payment_gl_and_bank
from src.utils.dates import at_time, parse_date, random_date
from src.utils.money import money


class PaymentWithoutInvoiceInjector(FailureInjector):
    failure_type = "F05_PAYMENT_WITHOUT_VALID_INVOICE"
    difficulty = "medium"
    reasoning_hops = 3
    severity = "high"

    def inject(self, ctx: InjectionContext, case_id: str):
        vendors = [row for row in ctx.dataset.rows("vendors") if row["vendor_status"] == "active"]
        vendor = ctx.rng.choice(vendors)
        date_value = random_date(ctx.rng.py, ctx.config["date_range"]["start"],
                                 parse_date(ctx.config["date_range"]["end"]) - timedelta(days=15))
        payment_id = ctx.ids.next("PAY")
        payment = {
            "payment_id": payment_id,
            "vendor_id": vendor["vendor_id"],
            "payment_date": date_value.isoformat(),
            "payment_method": vendor["default_payment_method"],
            "payment_currency": vendor["currency"],
            "payment_amount": money(ctx.rng.lognormal(2200, 0.9, 75, 45000), str(vendor["currency"])),
            "bank_account_id": vendor["bank_account_token"],
            "payment_status": "completed",
            "settlement_status": "settled",
            "reference_number": f"PMTREF-{ctx.ids.counters['PAY'] + (ctx.config['seed'] % 997):010d}",
            "created_at": at_time(date_value, 8),
            "source_system": "ERP-AP",
        }
        reason = "Ad-hoc payment was released without a valid invoice allocation"
        ctx.add(case_id, "payments", payment, reason)
        journal_id, bank_id = add_payment_gl_and_bank(ctx, case_id, payment, vendor, reason)
        audit_id = ctx.audit(case_id, "payment", payment_id, "manual_payment_created", str(payment["created_at"]),
                             "EMP-MANUAL-AP", "invoice_id", "", "", "ERP-AP")
        ctx.claim(("payment", payment_id))
        return self.case(
            case_id, "payment", payment_id, str(vendor["vendor_id"]),
            [("payment", payment_id), ("gl_journal", journal_id), ("bank_transaction", str(bank_id)),
             ("audit_event", audit_id)],
            "A completed and settled payment has no allocation to a valid invoice obligation.",
            "An ad-hoc AP payment was manually released without a supporting payable record.",
            "UNSUPPORTED_MANUAL_PAYMENT", ["payments", "payment_allocations", "gl_entries", "bank_transactions", "audit_log"],
            [payment_id, journal_id, str(bank_id), audit_id],
            "Escalate the unsupported disbursement, obtain documentation or recover the funds, and correct AP/GL records.",
            str(payment["created_at"]), ["ERP-AP", "ERP-GL", "Bank"], "manual_ad_hoc_payment",
        )

