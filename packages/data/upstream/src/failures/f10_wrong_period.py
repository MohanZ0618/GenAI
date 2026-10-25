"""F10: an otherwise correct journal is posted in the wrong period."""

from __future__ import annotations

from collections import defaultdict

from src.failures.base import FailureInjector, InjectionContext, shift_month
from src.utils.dates import accounting_period


class WrongPeriodInjector(FailureInjector):
    failure_type = "F10_WRONG_ACCOUNTING_PERIOD"
    difficulty = "hard"
    reasoning_hops = 4

    def inject(self, ctx: InjectionContext, case_id: str):
        journals: dict[str, list[dict]] = defaultdict(list)
        for row in ctx.dataset.rows("gl_entries"):
            if row["transaction_type"] == "payment":
                journals[str(row["source_transaction_id"])].append(row)
        candidates = [row for row in ctx.dataset.rows("payments") if journals.get(str(row["payment_id"]))
                      and ctx.available("payment", str(row["payment_id"]))]
        if not candidates:
            raise RuntimeError("F10 has no eligible payment")
        payment = ctx.rng.choice(candidates)
        rows = journals[str(payment["payment_id"])]
        shifted_date = shift_month(str(payment["payment_date"]), 1)
        shifted_period = accounting_period(shifted_date)
        reason = "A period-close interface queued the payment journal into the following accounting period"
        for row in rows:
            ctx.mutate(case_id, "gl_entries", row, "posting_date", shifted_date, reason)
            ctx.mutate(case_id, "gl_entries", row, "accounting_period", shifted_period, reason)
        audit_id = ctx.audit(case_id, "gl_journal", str(rows[0]["journal_id"]), "interface_queue_released", shifted_date + "T01:15:00",
                             "SYSTEM-GL-INTERFACE", "accounting_period", accounting_period(str(payment["payment_date"])),
                             shifted_period, "ERP-GL")
        ctx.claim(("payment", str(payment["payment_id"])), ("gl_journal", str(rows[0]["journal_id"])))
        return self.case(
            case_id, "gl_journal", str(rows[0]["journal_id"]), str(payment["vendor_id"]),
            [("payment", str(payment["payment_id"])), ("gl_journal", str(rows[0]["journal_id"])),
             ("audit_event", audit_id)],
            "The payment journal is balanced and correctly valued but appears in the month after the economic event.",
            "A period-close interface queue released the payment journal into the following accounting period.",
            "PERIOD_CLOSE_INTERFACE_TIMING", ["payments", "gl_entries", "audit_log"],
            [str(payment["payment_id"]), str(rows[0]["journal_id"]), audit_id],
            "Move the journal to the payment's economic period using the organization's period-adjustment policy.",
            shifted_date + "T01:15:00", ["ERP-AP", "ERP-GL"], "next_period_queue",
        )

