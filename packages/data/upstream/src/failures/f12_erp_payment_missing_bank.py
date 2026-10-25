"""F12: ERP reports a completed payment without bank settlement."""

from __future__ import annotations

from src.failures.base import FailureInjector, InjectionContext


class ERPPaymentMissingBankInjector(FailureInjector):
    failure_type = "F12_ERP_PAYMENT_MISSING_FROM_BANK"
    difficulty = "hard"
    reasoning_hops = 4
    severity = "high"

    def inject(self, ctx: InjectionContext, case_id: str):
        by_reference = {str(row["payment_reference"]): row for row in ctx.dataset.rows("bank_transactions")
                        if row["transaction_type"] != "bank fee"}
        candidates = [row for row in ctx.dataset.rows("payments") if str(row["reference_number"]) in by_reference
                      and ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            raise RuntimeError("F12 has no eligible settled payment")
        payment = ctx.rng.choice(candidates)
        bank = by_reference[str(payment["reference_number"])]
        variant_index = int(case_id.rsplit("_", 1)[-1]) % 3
        variants = [
            ("payment_file_not_transmitted", "PAYMENT_TRANSMISSION_FAILURE",
             "The ERP marked the payment complete, but the outbound payment file was never transmitted to the bank."),
            ("processor_batch_rejected", "PROCESSOR_BATCH_REJECTION",
             "The payment processor rejected the outbound batch before a bank instruction was created."),
            ("release_queue_timeout", "PAYMENT_RELEASE_QUEUE_TIMEOUT",
             "The released payment timed out in the treasury transmission queue and never reached the bank."),
        ]
        variant, category, root = variants[variant_index]
        reason = root
        ctx.remove(case_id, "bank_transactions", bank, reason)
        audit_id = ctx.audit(case_id, "payment", str(payment["payment_id"]), variant,
                             str(payment["payment_date"]) + "T23:30:00", "SYSTEM-PAYMENT-PROCESSOR",
                             "transmission_status", "queued", "failed", "PaymentProcessor")
        ctx.claim(("payment", str(payment["payment_id"])), ("bank_transaction", str(bank["bank_transaction_id"])))
        return self.case(
            case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
            [("payment", str(payment["payment_id"])), ("audit_event", audit_id)],
            "ERP shows a completed, settled payment beyond its clearing window, but no bank debit exists.",
            root, category, ["payments", "bank_transactions", "audit_log", "gl_entries"],
            [str(payment["payment_id"]), audit_id],
            "Reopen the ERP settlement, correct the transmission failure, and resubmit only after confirming no bank debit exists.",
            str(payment["created_at"]), ["ERP-AP", "ERP-GL", "PaymentProcessor", "Bank"], variant,
        )

