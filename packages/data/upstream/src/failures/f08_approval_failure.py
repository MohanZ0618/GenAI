"""F08: payment occurs after a required approval level is omitted."""

from __future__ import annotations

from collections import defaultdict

from src.failures.base import FailureInjector, InjectionContext


class ApprovalFailureInjector(FailureInjector):
    failure_type = "F08_APPROVAL_WORKFLOW_FAILURE"
    difficulty = "medium"
    reasoning_hops = 3
    severity = "high"

    def inject(self, ctx: InjectionContext, case_id: str):
        events: dict[str, list[dict]] = defaultdict(list)
        payments_by_invoice: dict[str, list[dict]] = defaultdict(list)
        payment_by_id = {str(row["payment_id"]): row for row in ctx.dataset.rows("payments")}
        for row in ctx.dataset.rows("approval_events"):
            events[str(row["invoice_id"])].append(row)
        for allocation in ctx.dataset.rows("payment_allocations"):
            payments_by_invoice[str(allocation["invoice_id"])].append(payment_by_id[str(allocation["payment_id"])])
        candidates = [row for row in ctx.dataset.rows("invoices") if payments_by_invoice.get(str(row["invoice_id"]))
                      and len(events.get(str(row["invoice_id"]), [])) >= 2
                      and ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            raise RuntimeError("F08 has no eligible paid invoice")
        invoice = ctx.rng.choice(candidates)
        approved = [row for row in events[str(invoice["invoice_id"])] if row["action"] in {"approved", "auto_approved"}]
        removed = max(approved, key=lambda row: int(row["approval_level"]))
        reason = "Required final approval was absent when the payment run released the invoice"
        ctx.remove(case_id, "approval_events", removed, reason)
        payment = payments_by_invoice[str(invoice["invoice_id"])][0]
        remaining_ids = [str(row["approval_event_id"]) for row in events[str(invoice["invoice_id"])] if row is not removed]
        audit_id = ctx.audit(case_id, "payment", str(payment["payment_id"]), "workflow_override", str(payment["created_at"]),
                             "SYSTEM-PAYMENT-RUN", "approval_gate", "required", "bypassed", "ERP-Workflow")
        ctx.claim(("invoice", str(invoice["invoice_id"])), ("payment", str(payment["payment_id"])))
        return self.case(
            case_id, "payment", str(payment["payment_id"]), str(invoice["vendor_id"]),
            [("invoice", str(invoice["invoice_id"])), ("payment", str(payment["payment_id"])),
             ("audit_event", audit_id)],
            "A paid invoice's event history does not contain the final approval required for its amount.",
            "The payment workflow bypassed the invoice's required final approval gate.",
            "APPROVAL_GATE_BYPASS", ["invoices", "approval_events", "payments", "payment_allocations", "audit_log", "employees"],
            [str(invoice["invoice_id"]), str(payment["payment_id"]), audit_id, *remaining_ids[-2:]],
            "Escalate the unauthorized disbursement, obtain retrospective review, and repair the payment approval gate.",
            str(payment["created_at"]), ["ERP-Workflow", "ERP-AP"], "missing_final_approval",
        )

