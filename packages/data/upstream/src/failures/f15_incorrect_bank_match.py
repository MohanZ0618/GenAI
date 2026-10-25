"""F15: two bank settlements receive one another's ERP payment references."""

from __future__ import annotations

from collections import defaultdict

from src.failures.base import FailureInjector, InjectionContext
from src.utils.dates import parse_date
from src.utils.money import decimal


class IncorrectBankMatchInjector(FailureInjector):
    failure_type = "F15_INCORRECT_PAYMENT_BANK_MATCH"
    difficulty = "hard"
    reasoning_hops = 5

    def inject(self, ctx: InjectionContext, case_id: str):
        bank_by_ref = {str(row["payment_reference"]): row for row in ctx.dataset.rows("bank_transactions")
                       if row["transaction_type"] != "bank fee"}
        buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for payment in ctx.dataset.rows("payments"):
            if str(payment["reference_number"]) in bank_by_ref and ctx.available("payment", str(payment["payment_id"])):
                bank = bank_by_ref[str(payment["reference_number"])]
                buckets[(str(payment["vendor_id"]), str(bank["bank_account_id"]))].append(payment)
        candidate_pairs: list[tuple[dict, dict]] = []
        fallback: list[tuple[dict, dict]] = []
        for payments in buckets.values():
            payments.sort(key=lambda row: str(row["payment_date"]))
            for first, second in zip(payments, payments[1:]):
                days = abs((parse_date(str(first["payment_date"])) - parse_date(str(second["payment_date"]))).days)
                # Equal-amount swaps are not observably wrong without unavailable processor sequence data.
                if days <= 7 and decimal(first["payment_amount"]) != decimal(second["payment_amount"]):
                    fallback.append((first, second))
                    larger = max(decimal(first["payment_amount"]), decimal(second["payment_amount"]))
                    if larger and abs(decimal(first["payment_amount"]) - decimal(second["payment_amount"])) / larger <= decimal("0.20"):
                        candidate_pairs.append((first, second))
        pairs = candidate_pairs or fallback
        if not pairs:
            raise RuntimeError("F15 has no eligible same-vendor settlement pair")
        first, second = ctx.rng.choice(pairs)
        first_bank = bank_by_ref[str(first["reference_number"])]
        second_bank = bank_by_ref[str(second["reference_number"])]
        first_ref, second_ref = first_bank["payment_reference"], second_bank["payment_reference"]
        reason = "Automated reconciliation assigned two similar settlements to one another's ERP payments"
        ctx.mutate(case_id, "bank_transactions", first_bank, "payment_reference", second_ref, reason)
        ctx.mutate(case_id, "bank_transactions", second_bank, "payment_reference", first_ref, reason)
        audit_id = ctx.audit(case_id, "bank_transaction", str(first_bank["bank_transaction_id"]), "auto_match_applied",
                             str(first_bank["posted_date"]) + "T20:00:00", "SYSTEM-RECON-ENGINE",
                             "payment_reference", str(first_ref), str(second_ref), "ReconciliationPlatform")
        ctx.claim(("payment", str(first["payment_id"])), ("payment", str(second["payment_id"])),
                  ("bank_transaction", str(first_bank["bank_transaction_id"])),
                  ("bank_transaction", str(second_bank["bank_transaction_id"])))
        return self.case(
            case_id, "payment", str(first["payment_id"]), str(first["vendor_id"]),
            [("payment", str(first["payment_id"])), ("payment", str(second["payment_id"])),
             ("bank_transaction", str(first_bank["bank_transaction_id"])),
             ("bank_transaction", str(second_bank["bank_transaction_id"])), ("audit_event", audit_id)],
            "Two nearby same-vendor settlements are linked to the opposite ERP payment references.",
            "Automated reconciliation selected the wrong candidates among similar same-vendor settlements.",
            "AMBIGUOUS_AUTOMATCH", ["payments", "bank_transactions", "payment_allocations", "audit_log"],
            [str(first["payment_id"]), str(second["payment_id"]), str(first_bank["bank_transaction_id"]),
             str(second_bank["bank_transaction_id"]), audit_id],
            "Unmatch both pairs and rematch using reference, amount, date, vendor, and allocation evidence together.",
            str(first_bank["posted_date"]) + "T20:00:00", ["ERP-AP", "Bank", "ReconciliationPlatform"],
            "similar_same_vendor_cross_match",
        )
