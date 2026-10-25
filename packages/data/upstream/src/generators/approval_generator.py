"""Event-sourced invoice approval workflows."""

from __future__ import annotations

from datetime import timedelta

from src.generators.context import GenerationContext
from src.utils.dates import at_time, parse_date
from src.utils.money import decimal


def _required_roles(total) -> list[str]:
    amount = decimal(total)
    if amount <= decimal("500"):
        return ["auto"]
    if amount <= decimal("10000"):
        return ["manager"]
    if amount <= decimal("50000"):
        return ["manager", "director"]
    if amount <= decimal("250000"):
        return ["manager", "director", "controller"]
    return ["manager", "director", "treasury"]


def generate_approvals(ctx: GenerationContext) -> None:
    employees_by_role: dict[str, list[dict[str, object]]] = {}
    for employee in ctx.dataset.rows("employees"):
        if employee["active_status"] == "active":
            employees_by_role.setdefault(str(employee["role"]), []).append(employee)

    for invoice in ctx.dataset.rows("invoices"):
        received = parse_date(str(invoice["received_date"]))
        submitted_id = ctx.ids.next("APR")
        ctx.dataset.add(
            "approval_events",
            {
                "approval_event_id": submitted_id,
                "invoice_id": invoice["invoice_id"],
                "approval_level": 0,
                "approver_id": "SYSTEM-WORKFLOW",
                "approver_role": "workflow",
                "action": "submitted",
                "event_timestamp": at_time(received, 9),
                "previous_status": "received",
                "new_status": "submitted",
                "comments": "Invoice submitted to configured approval policy",
                "source_system": "ERP-Workflow",
            },
        )
        ctx.edge("invoice", str(invoice["invoice_id"]), "submitted_to", "approval_event", submitted_id)
        previous = "submitted"
        roles = _required_roles(invoice["invoice_total"])
        for level, role in enumerate(roles, 1):
            event_date = received + timedelta(days=level)
            action = "auto_approved" if role == "auto" else "approved"
            actor = "SYSTEM-AUTO-APPROVAL" if role == "auto" else str(ctx.rng.choice(employees_by_role[role])["employee_id"])
            new_status = "approved" if level == len(roles) else f"pending_level_{level + 1}"
            event_id = ctx.ids.next("APR")
            ctx.dataset.add(
                "approval_events",
                {
                    "approval_event_id": event_id,
                    "invoice_id": invoice["invoice_id"],
                    "approval_level": level,
                    "approver_id": actor,
                    "approver_role": role,
                    "action": action,
                    "event_timestamp": at_time(event_date, 10 + min(level, 6)),
                    "previous_status": previous,
                    "new_status": new_status,
                    "comments": "Approved within delegated authority",
                    "source_system": "ERP-Workflow",
                },
            )
            ctx.edge("invoice", str(invoice["invoice_id"]), "approved_by", "approval_event", event_id)
            previous = new_status
        invoice["status"] = "approved"
        ctx.audit(
            "invoice", str(invoice["invoice_id"]), "approval_completed", at_time(received + timedelta(days=len(roles)), 17),
            "SYSTEM-WORKFLOW", "status", "received", "approved", "ERP-Workflow"
        )

