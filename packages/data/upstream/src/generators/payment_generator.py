"""Payment and allocation generation, including batching and split payments."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from src.generators.context import GenerationContext
from src.utils.dates import at_time, parse_date
from src.utils.money import money, split_money, sum_money


def _latest_approval_dates(ctx: GenerationContext) -> dict[str, object]:
    result: dict[str, object] = {}
    for event in ctx.dataset.rows("approval_events"):
        if event["action"] in {"approved", "auto_approved"}:
            event_date = parse_date(str(event["event_timestamp"])[:10])
            invoice_id = str(event["invoice_id"])
            result[invoice_id] = max(result.get(invoice_id, event_date), event_date)
    return result


def _build_payment_plans(ctx: GenerationContext, invoices: list[dict[str, object]]) -> list[dict[str, object]]:
    plans = [{"allocations": [(invoice, invoice["invoice_total"])]} for invoice in invoices]
    target_batches = round(len(plans) * 0.18)
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, plan in enumerate(plans):
        invoice = plan["allocations"][0][0]
        groups[(str(invoice["vendor_id"]), str(invoice["currency"]))].append(index)

    paired: set[int] = set()
    combined: list[dict[str, object]] = []
    for indices in groups.values():
        ctx.rng.py.shuffle(indices)
        while len(indices) >= 2 and len(combined) < target_batches:
            first, second = indices.pop(), indices.pop()
            paired.update((first, second))
            combined.append(
                {"allocations": plans[first]["allocations"] + plans[second]["allocations"], "kind": "batch"}
            )
        if len(combined) >= target_batches:
            break
    unpaired = [plan for index, plan in enumerate(plans) if index not in paired]
    merged = unpaired + combined

    split_count = len(combined)
    eligible = [index for index, plan in enumerate(merged) if len(plan["allocations"]) == 1]
    ctx.rng.py.shuffle(eligible)
    to_split = set(eligible[:split_count])
    final: list[dict[str, object]] = []
    for index, plan in enumerate(merged):
        if index not in to_split:
            final.append(plan)
            continue
        invoice, total = plan["allocations"][0]
        first, second = split_money(total, [60, 40], str(invoice["currency"]))
        final.append({"allocations": [(invoice, first)], "kind": "split_first"})
        final.append({"allocations": [(invoice, second)], "kind": "split_second"})
    if len(final) != len(invoices):
        raise RuntimeError("Payment plan construction failed to preserve the configured payment count")
    return final


def generate_payments(ctx: GenerationContext) -> None:
    target = min(ctx.config["scale"]["payments"], len(ctx.dataset.rows("invoices")))
    end = parse_date(ctx.config["date_range"]["end"])
    cutoff = end - timedelta(days=15)
    approvals = _latest_approval_dates(ctx)
    eligible = [
        invoice for invoice in ctx.dataset.rows("invoices")
        if str(invoice["invoice_id"]) in approvals and approvals[str(invoice["invoice_id"])] <= cutoff
    ]
    if len(eligible) < target:
        raise ValueError(f"Only {len(eligible)} invoices are eligible for {target} requested payments")
    chosen = ctx.rng.shuffled(eligible)[:target]
    plans = _build_payment_plans(ctx, chosen)
    vendor_by_id = {row["vendor_id"]: row for row in ctx.dataset.rows("vendors")}
    paid_invoice_ids: set[str] = set()

    for plan in plans:
        allocations = plan["allocations"]
        first_invoice = allocations[0][0]
        vendor = vendor_by_id[first_invoice["vendor_id"]]
        currency = str(first_invoice["currency"])
        latest_approval = max(approvals[str(invoice["invoice_id"])] for invoice, _ in allocations)
        latest_due = max(parse_date(str(invoice["due_date"])) for invoice, _ in allocations)
        base_date = max(latest_approval + timedelta(days=1), min(latest_due, cutoff))
        if plan.get("kind") == "split_second":
            base_date = min(base_date + timedelta(days=3), cutoff)
        method = str(vendor["default_payment_method"])
        payment_id = ctx.ids.next("PAY")
        reference = f"PMTREF-{ctx.ids.counters['PAY'] + (ctx.config['seed'] % 997):010d}"
        total = sum_money((amount for _, amount in allocations), currency)
        ctx.dataset.add(
            "payments",
            {
                "payment_id": payment_id,
                "vendor_id": vendor["vendor_id"],
                "payment_date": base_date.isoformat(),
                "payment_method": method,
                "payment_currency": currency,
                "payment_amount": total,
                "bank_account_id": vendor["bank_account_token"],
                "payment_status": "completed",
                "settlement_status": "settled",
                "reference_number": reference,
                "created_at": at_time(base_date, 8),
                "source_system": "ERP-AP",
            },
        )
        for invoice, allocated_amount in allocations:
            invoice_id = str(invoice["invoice_id"])
            ctx.dataset.add(
                "payment_allocations",
                {
                    "payment_id": payment_id,
                    "invoice_id": invoice_id,
                    "allocated_amount": money(allocated_amount, currency),
                    "allocation_date": base_date.isoformat(),
                    "source_system": "ERP-AP",
                },
            )
            ctx.edge("payment", payment_id, "settles", "invoice", invoice_id)
            paid_invoice_ids.add(invoice_id)
        ctx.audit("payment", payment_id, "payment_created", at_time(base_date, 8), "SYSTEM-PAYMENT-RUN")

    for invoice in ctx.dataset.rows("invoices"):
        if str(invoice["invoice_id"]) in paid_invoice_ids:
            invoice["status"] = "paid"

