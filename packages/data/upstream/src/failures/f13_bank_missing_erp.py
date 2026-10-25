"""F13: outgoing bank transaction has no ERP payment."""

from __future__ import annotations

from datetime import timedelta

from src.failures.base import FailureInjector, InjectionContext
from src.utils.dates import add_business_days, parse_date, random_date
from src.utils.money import money


class BankMissingERPInjector(FailureInjector):
    failure_type = "F13_BANK_TRANSACTION_MISSING_FROM_ERP"
    difficulty = "hard"
    reasoning_hops = 4
    severity = "high"

    def inject(self, ctx: InjectionContext, case_id: str):
        vendor = ctx.rng.choice(ctx.dataset.rows("vendors"))
        transaction_date = random_date(
            ctx.rng.py,
            ctx.config["date_range"]["start"],
            parse_date(ctx.config["date_range"]["end"]) - timedelta(days=5),
        )
        bank_id = ctx.ids.next("BT")
        amount = money(ctx.rng.lognormal(4800, 0.8, 125, 85000), str(vendor["currency"]))
        accounts = ctx.config["generation"]["bank_accounts"]
        account = accounts[-1] if vendor["currency"] != "USD" else accounts[ctx.ids.counters["BT"] % 2]
        reason = "A treasury user initiated a manual bank-portal transfer outside the ERP payment workflow"
        ctx.add(
            case_id,
            "bank_transactions",
            {
                "bank_transaction_id": bank_id,
                "bank_account_id": account,
                "transaction_date": transaction_date.isoformat(),
                "posted_date": add_business_days(transaction_date, 1).isoformat(),
                "transaction_type": "wire debit",
                "amount": amount,
                "currency": vendor["currency"],
                "direction": "debit",
                "bank_reference": f"MANUAL-{ctx.ids.counters['BT']:011d}",
                "counterparty_token": vendor["bank_account_token"],
                "payment_reference": f"BANKPORTAL-{ctx.ids.counters['BT']:09d}",
                "status": "posted",
                "source_system": "Bank",
            },
            reason,
        )
        audit_id = ctx.audit(case_id, "bank_transaction", bank_id, "bank_portal_manual_transfer",
                             transaction_date.isoformat() + "T14:20:00", "TREASURY-PORTAL-USER",
                             "origin", "", "manual_bank_portal", "Bank")
        ctx.claim(("bank_transaction", bank_id), ("vendor", str(vendor["vendor_id"])))
        return self.case(
            case_id, "bank_transaction", bank_id, str(vendor["vendor_id"]),
            [("bank_transaction", bank_id), ("vendor", str(vendor["vendor_id"])), ("audit_event", audit_id)],
            "An outgoing non-fee bank debit cannot be linked to any ERP payment or payment journal.",
            reason, "MANUAL_BANK_PORTAL_PAYMENT", ["bank_transactions", "payments", "gl_entries", "audit_log", "vendors"],
            [bank_id, str(vendor["vendor_id"]), audit_id],
            "Investigate and authorize or recover the transfer, then record the approved payable/payment and balanced journal if valid.",
            transaction_date.isoformat() + "T14:20:00", ["Bank", "ERP-AP", "ERP-GL"], "manual_treasury_transfer",
        )

