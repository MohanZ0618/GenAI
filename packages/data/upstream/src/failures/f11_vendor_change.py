"""F11: payment uses a superseded vendor bank-account version."""

from __future__ import annotations

from datetime import timedelta

from src.failures.base import FailureInjector, InjectionContext
from src.utils.dates import at_time, parse_date


class VendorChangeConflictInjector(FailureInjector):
    failure_type = "F11_VENDOR_MASTER_CHANGE_CONFLICT"
    difficulty = "hard"
    reasoning_hops = 5
    severity = "high"

    def inject(self, ctx: InjectionContext, case_id: str):
        bank_by_ref = {str(row["payment_reference"]): row for row in ctx.dataset.rows("bank_transactions")
                       if row["transaction_type"] != "bank fee"}
        candidates = [row for row in ctx.dataset.rows("payments") if str(row["reference_number"]) in bank_by_ref
                      and ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            raise RuntimeError("F11 has no eligible settled payment")
        payment = ctx.rng.choice(candidates)
        vendor = next(row for row in ctx.dataset.rows("vendors") if row["vendor_id"] == payment["vendor_id"])
        bank = bank_by_ref[str(payment["reference_number"])]
        old_token = f"BA_TKN_SUPERSEDED_{ctx.ids.counters['CHG'] + 1:07d}"
        current_token = str(vendor["bank_account_token"])
        change_date = parse_date(str(payment["payment_date"])) - timedelta(days=2)
        reason = "Payment instructions were snapshotted before a verified vendor banking change and not refreshed"
        ctx.mutate(case_id, "payments", payment, "bank_account_id", old_token, reason)
        ctx.mutate(case_id, "payments", payment, "settlement_status", "failed", reason)
        ctx.mutate(case_id, "bank_transactions", bank, "counterparty_token", old_token, reason)
        ctx.mutate(case_id, "bank_transactions", bank, "status", "returned", reason)
        change_id = ctx.ids.next("CHG")
        employee = next(row for row in ctx.dataset.rows("employees") if row["active_status"] == "active")
        ctx.add(
            case_id,
            "vendor_change_log",
            {
                "change_id": change_id,
                "vendor_id": vendor["vendor_id"],
                "field_changed": "bank_account_token",
                "old_value": old_token,
                "new_value": current_token,
                "changed_at": at_time(change_date, 14),
                "changed_by": employee["employee_id"],
                "change_reason": "Vendor-verified banking update",
                "source_system": "VendorManagement",
            },
            reason,
        )
        audit_id = ctx.audit(case_id, "payment", str(payment["payment_id"]), "processor_return_received",
                             str(bank["posted_date"]) + "T16:00:00", "SYSTEM-PAYMENT-PROCESSOR",
                             "settlement_status", "submitted", "failed", "PaymentProcessor")
        ctx.edge("vendor_change", change_id, "affects", "payment", str(payment["payment_id"]))
        ctx.claim(("payment", str(payment["payment_id"])), ("vendor", str(vendor["vendor_id"])),
                  ("bank_transaction", str(bank["bank_transaction_id"])))
        return self.case(
            case_id, "payment", str(payment["payment_id"]), str(vendor["vendor_id"]),
            [("vendor", str(vendor["vendor_id"])), ("vendor_change", change_id),
             ("payment", str(payment["payment_id"])), ("bank_transaction", str(bank["bank_transaction_id"])),
             ("audit_event", audit_id)],
            "A payment failed after using bank instructions that the vendor history shows were superseded before payment creation.",
            "The payment system retained a stale vendor bank-account snapshot after a verified master-data change.",
            "STALE_VENDOR_BANK_VERSION", ["vendors", "vendor_change_log", "payments", "bank_transactions", "audit_log"],
            [str(vendor["vendor_id"]), change_id, str(payment["payment_id"]), str(bank["bank_transaction_id"]), audit_id],
            "Regenerate the payment with the effective vendor bank token, retain return evidence, and refresh payment snapshots on master changes.",
            at_time(change_date, 14), ["VendorManagement", "ERP-AP", "PaymentProcessor", "Bank"], "bank_change_before_payment",
        )

