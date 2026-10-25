"""F14: bank settlement is net of an unrecorded deduction."""

from __future__ import annotations

from src.failures.base import FailureInjector, InjectionContext
from src.utils.money import decimal, money


class BankERPAmountInjector(FailureInjector):
    failure_type = "F14_BANK_ERP_AMOUNT_MISMATCH"
    difficulty = "medium"
    reasoning_hops = 3

    def inject(self, ctx: InjectionContext, case_id: str):
        bank_by_ref = {str(row["payment_reference"]): row for row in ctx.dataset.rows("bank_transactions")
                       if row["transaction_type"] != "bank fee"}
        fee_refs = {str(row["payment_reference"]) for row in ctx.dataset.rows("bank_transactions")
                    if row["transaction_type"] == "bank fee"}
        candidates = [row for row in ctx.dataset.rows("payments") if str(row["reference_number"]) in bank_by_ref
                      and str(row["reference_number"]) not in fee_refs and decimal(row["payment_amount"]) > 100
                      and ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            raise RuntimeError("F14 has no eligible payment")
        payment = ctx.rng.choice(candidates)
        bank = bank_by_ref[str(payment["reference_number"])]
        fee = money(ctx.rng.choice(["15", "20", "25", "35"]), str(payment["payment_currency"]))
        net_amount = money(decimal(payment["payment_amount"]) - decimal(fee), str(payment["payment_currency"]))
        reason = "The processor netted a settlement fee but no fee configuration or accounting entry existed"
        ctx.mutate(case_id, "bank_transactions", bank, "amount", net_amount, reason)
        audit_id = ctx.audit(case_id, "payment", str(payment["payment_id"]), "net_settlement_received",
                             str(bank["posted_date"]) + "T18:00:00", "SYSTEM-PAYMENT-PROCESSOR",
                             "settlement_amount", str(payment["payment_amount"]), str(net_amount), "PaymentProcessor")
        ctx.claim(("payment", str(payment["payment_id"])), ("bank_transaction", str(bank["bank_transaction_id"])))
        return self.case(
            case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
            [("payment", str(payment["payment_id"])), ("bank_transaction", str(bank["bank_transaction_id"])),
             ("audit_event", audit_id)],
            "The matched bank debit is lower than the ERP payment and no corresponding fee journal exists.",
            f"The processor netted a {fee} {payment['payment_currency']} fee that was not configured or posted to the GL.",
            "UNRECORDED_SETTLEMENT_FEE", ["payments", "bank_transactions", "gl_entries", "audit_log"],
            [str(payment["payment_id"]), str(bank["bank_transaction_id"]), audit_id],
            "Record and approve the fee expense/cash entry, correct settlement configuration, and reconcile the net amount.",
            str(bank["posted_date"]) + "T18:00:00", ["ERP-AP", "PaymentProcessor", "Bank", "ERP-GL"], "unrecorded_net_fee",
        )

