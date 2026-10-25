"""PO-backed and non-PO invoice generation."""

from __future__ import annotations

from datetime import timedelta

from src.generators.context import GenerationContext
from src.generators.po_generator import DEPARTMENT_AMOUNT_MEDIAN, GL_BY_DEPARTMENT, LINE_COUNTS
from src.generators.vendor_generator import DEPARTMENTS
from src.utils.dates import at_time, parse_date, random_date
from src.utils.money import decimal, money, sum_money


TERM_DAYS = {"DUE_ON_RECEIPT": 0, "NET15": 15, "NET30": 30, "NET45": 45, "NET60": 60}


def _invoice_header(
    ctx: GenerationContext,
    vendor: dict[str, object],
    po_id: str,
    invoice_date,
    subtotal,
    tax,
    shipping,
    sequence: int,
) -> dict[str, object]:
    received = invoice_date + timedelta(days=ctx.rng.py.randint(0, 5))
    terms = str(vendor["payment_terms"])
    total = money(subtotal + tax + shipping, str(vendor["currency"]))
    return {
        "invoice_id": ctx.ids.next("INV"),
        "vendor_id": vendor["vendor_id"],
        "po_id": po_id,
        "invoice_number": f"SYN-{str(vendor['vendor_id'])[-4:]}-{sequence:06d}",
        "invoice_date": invoice_date.isoformat(),
        "received_date": received.isoformat(),
        "due_date": (invoice_date + timedelta(days=TERM_DAYS[terms])).isoformat(),
        "currency": vendor["currency"],
        "subtotal": subtotal,
        "tax": tax,
        "shipping": shipping,
        "invoice_total": total,
        "payment_terms": terms,
        "status": "received",
        "duplicate_reference": "",
        "created_at": at_time(received, 8, ctx.rng.py.randint(0, 59)),
        "source_system": "ERP-AP",
    }


def generate_invoices(ctx: GenerationContext) -> None:
    count = ctx.config["scale"]["invoices"]
    po_rate = float(ctx.config["generation"]["po_backed_invoice_rate"])
    po_backed_count = min(round(count * po_rate), len(ctx.dataset.rows("purchase_orders")))
    start = parse_date(ctx.config["date_range"]["start"])
    end = parse_date(ctx.config["date_range"]["end"]) - timedelta(days=20)
    vendors = ctx.dataset.rows("vendors")
    vendor_by_id = {row["vendor_id"]: row for row in vendors}
    vendor_weights = ctx.metadata["vendor_weights"]
    pos = ctx.rng.shuffled(ctx.dataset.rows("purchase_orders"))[:po_backed_count]
    po_lines_by_po: dict[str, list[dict[str, object]]] = {}
    for line in ctx.dataset.rows("po_lines"):
        po_lines_by_po.setdefault(str(line["po_id"]), []).append(line)

    for sequence, po in enumerate(pos, 1):
        vendor = vendor_by_id[po["vendor_id"]]
        earliest = parse_date(str(po["po_date"]))
        invoice_date = min(earliest + timedelta(days=ctx.rng.py.randint(0, 30)), end)
        row = _invoice_header(
            ctx, vendor, str(po["po_id"]), invoice_date, po["subtotal"], po["tax"], po["shipping"], sequence
        )
        ctx.dataset.add("invoices", row)
        for po_line in po_lines_by_po[str(po["po_id"])]:
            invoice_line_id = ctx.ids.next("INVL")
            ctx.dataset.add(
                "invoice_lines",
                {
                    "invoice_id": row["invoice_id"],
                    "invoice_line_id": invoice_line_id,
                    "po_line_id": po_line["po_line_id"],
                    "item_id": po_line["item_id"],
                    "quantity": po_line["quantity"],
                    "unit_price": po_line["unit_price"],
                    "line_amount": po_line["line_amount"],
                    "gl_account": po_line["gl_account"],
                    "department": po_line["department"],
                    "cost_center": po_line["cost_center"],
                    "source_system": "ERP-AP",
                },
            )
            ctx.edge("invoice_line", invoice_line_id, "matches", "po_line", str(po_line["po_line_id"]))
        ctx.edge("invoice", str(row["invoice_id"]), "references", "purchase_order", str(po["po_id"]))
        ctx.edge("vendor", str(vendor["vendor_id"]), "bills_via", "invoice", str(row["invoice_id"]))
        ctx.audit("invoice", str(row["invoice_id"]), "received", str(row["created_at"]), "SYSTEM-AP-INGEST")

    remaining = count - po_backed_count
    recurring_pool: list[tuple[dict[str, object], list[dict[str, object]]]] = []
    for offset in range(remaining):
        sequence = po_backed_count + offset + 1
        make_recurring = bool(recurring_pool) and ctx.rng.py.random() < float(
            ctx.config["generation"]["recurring_invoice_rate"]
        )
        if make_recurring:
            template, template_lines = ctx.rng.choice(recurring_pool)
            vendor = vendor_by_id[template["vendor_id"]]
            previous_date = parse_date(str(template["invoice_date"]))
            invoice_date = min(previous_date + timedelta(days=ctx.rng.py.choice([28, 30, 31])), end)
            row = _invoice_header(
                ctx,
                vendor,
                "",
                invoice_date,
                template["subtotal"],
                template["tax"],
                template["shipping"],
                sequence,
            )
            ctx.dataset.add("invoices", row)
            new_lines: list[dict[str, object]] = []
            for template_line in template_lines:
                new_line = dict(template_line)
                new_line["invoice_id"] = row["invoice_id"]
                new_line["invoice_line_id"] = ctx.ids.next("INVL")
                new_lines.append(new_line)
                ctx.dataset.add("invoice_lines", new_line)
            ctx.audit("invoice", str(row["invoice_id"]), "received_recurring", str(row["created_at"]), "SYSTEM-AP-INGEST")
        else:
            vendor = ctx.rng.py.choices(vendors, weights=vendor_weights, k=1)[0]
            invoice_date = random_date(ctx.rng.py, start, end)
            department = ctx.rng.choice(DEPARTMENTS)
            cost_center = f"CC-{DEPARTMENTS.index(department) + 1:02d}-{ctx.rng.py.randint(1, 12):02d}"
            currency = str(vendor["currency"])
            line_count = ctx.rng.weighted_choice(LINE_COUNTS)
            provisional: list[dict[str, object]] = []
            for line_index in range(line_count):
                quantity = ctx.rng.py.randint(1, 12)
                unit_price = money(
                    ctx.rng.lognormal(DEPARTMENT_AMOUNT_MEDIAN[department] / line_count, 1.0, 20, 125000)
                    / quantity,
                    currency,
                )
                provisional.append(
                    {
                        "invoice_id": "",
                        "invoice_line_id": "",
                        "po_line_id": "",
                        "item_id": f"SVC-{ctx.rng.py.randint(1, 400):04d}",
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "line_amount": money(quantity * unit_price, currency),
                        "gl_account": GL_BY_DEPARTMENT[department],
                        "department": department,
                        "cost_center": cost_center,
                        "source_system": "ERP-AP",
                    }
                )
            subtotal = sum_money((line["line_amount"] for line in provisional), currency)
            tax = money(
                subtotal * decimal(ctx.rng.weighted_choice({"0": 0.35, "0.075": 0.45, "0.10": 0.20})),
                currency,
            )
            shipping = money(0, currency)
            row = _invoice_header(ctx, vendor, "", invoice_date, subtotal, tax, shipping, sequence)
            ctx.dataset.add("invoices", row)
            new_lines = []
            for provisional_line in provisional:
                provisional_line["invoice_id"] = row["invoice_id"]
                provisional_line["invoice_line_id"] = ctx.ids.next("INVL")
                new_lines.append(provisional_line)
                ctx.dataset.add("invoice_lines", provisional_line)
            recurring_pool.append((row, new_lines))
            ctx.audit("invoice", str(row["invoice_id"]), "received", str(row["created_at"]), "SYSTEM-AP-INGEST")
        ctx.edge("vendor", str(vendor["vendor_id"]), "bills_via", "invoice", str(row["invoice_id"]))
