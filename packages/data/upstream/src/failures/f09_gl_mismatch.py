"""F09: operational payment and a balanced GL journal disagree."""

from __future__ import annotations

from collections import defaultdict

from src.failures.base import FailureInjector, InjectionContext
from src.utils.money import decimal, money


class GLMismatchInjector(FailureInjector):
    failure_type = "F09_GL_POSTING_MISMATCH"
    difficulty = "medium"
    reasoning_hops = 3

    def inject(self, ctx: InjectionContext, case_id: str):
        journals: dict[str, list[dict]] = defaultdict(list)
        for row in ctx.dataset.rows("gl_entries"):
            if row["transaction_type"] == "payment":
                journals[str(row["source_transaction_id"])].append(row)
        candidates = [row for row in ctx.dataset.rows("payments") if len(journals.get(str(row["payment_id"]), [])) == 2
                      and ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            raise RuntimeError("F09 has no eligible payment journal")
        payment = ctx.rng.choice(candidates)
        rows = journals[str(payment["payment_id"])]
        currency = str(payment["payment_currency"])
        wrong_amount = money(decimal(payment["payment_amount"]) * decimal("1.037"), currency)
        reason = "The payment interface posted an incorrect amount to both sides of the GL journal"
        for row in rows:
            field = "debit" if decimal(row["debit"]) else "credit"
            ctx.mutate(case_id, "gl_entries", row, field, wrong_amount, reason)
        ctx.claim(("payment", str(payment["payment_id"])), ("gl_journal", str(rows[0]["journal_id"])))
        return self.case(
            case_id, "payment", str(payment["payment_id"]), str(payment["vendor_id"]),
            [("payment", str(payment["payment_id"])), ("gl_journal", str(rows[0]["journal_id"]))],
            "The balanced payment journal amount differs from the operational payment and bank settlement.",
            "The ERP-to-GL interface posted an incorrect payment amount to both debit and credit lines.",
            "ERP_GL_INTERFACE_AMOUNT", ["payments", "gl_entries", "bank_transactions"],
            [str(payment["payment_id"]), str(rows[0]["journal_id"])],
            "Reverse and repost the journal from the authoritative payment amount, then reconcile cash and AP.",
            str(payment["created_at"]), ["ERP-AP", "ERP-GL", "Bank"], "balanced_wrong_amount",
        )

