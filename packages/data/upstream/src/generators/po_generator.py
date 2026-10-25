"""Purchase-order and line generation."""

from __future__ import annotations

from datetime import timedelta

from src.generators.context import GenerationContext
from src.generators.vendor_generator import DEPARTMENTS
from src.utils.dates import parse_date, random_date
from src.utils.money import decimal, money, sum_money


GL_BY_DEPARTMENT = {
    "Engineering": "610100-ENGINEERING",
    "Operations": "620100-OPERATIONS",
    "Finance": "630100-FINANCE",
    "Sales": "640100-SALES",
    "Marketing": "650100-MARKETING",
    "People": "660100-PEOPLE",
    "Legal": "670100-LEGAL",
    "IT": "680100-IT",
}
DEPARTMENT_AMOUNT_MEDIAN = {
    "Engineering": 4800,
    "Operations": 3200,
    "Finance": 1800,
    "Sales": 2600,
    "Marketing": 4000,
    "People": 1500,
    "Legal": 6000,
    "IT": 5200,
}
LINE_COUNTS = {1: 0.25, 2: 0.38, 3: 0.25, 4: 0.12}


def generate_purchase_orders(ctx: GenerationContext) -> None:
    count = ctx.config["scale"]["purchase_orders"]
    start = parse_date(ctx.config["date_range"]["start"])
    end = parse_date(ctx.config["date_range"]["end"]) - timedelta(days=45)
    vendors = [row for row in ctx.dataset.rows("vendors") if row["vendor_status"] == "active"]
    all_vendors = ctx.dataset.rows("vendors")
    all_weights = ctx.metadata["vendor_weights"]
    weight_by_id = {vendor["vendor_id"]: weight for vendor, weight in zip(all_vendors, all_weights)}
    vendor_weights = [weight_by_id[row["vendor_id"]] for row in vendors]
    employees = [row for row in ctx.dataset.rows("employees") if row["active_status"] == "active"]

    for po_index in range(count):
        vendor = ctx.rng.py.choices(vendors, weights=vendor_weights, k=1)[0]
        department = ctx.rng.choice(DEPARTMENTS)
        cost_center = f"CC-{DEPARTMENTS.index(department) + 1:02d}-{ctx.rng.py.randint(1, 12):02d}"
        po_date = random_date(ctx.rng.py, start, end)
        line_count = ctx.rng.weighted_choice(LINE_COUNTS)
        currency = str(vendor["currency"])
        po_id = ctx.ids.next("PO")
        line_rows: list[dict[str, object]] = []
        for line_index in range(line_count):
            quantity = ctx.rng.py.randint(1, 24)
            base = ctx.rng.lognormal(
                DEPARTMENT_AMOUNT_MEDIAN[department] / max(line_count, 1), 1.05, 25, 175000
            )
            unit_price = money(base / quantity, currency)
            line_amount = money(unit_price * quantity, currency)
            line_rows.append(
                {
                    "po_id": po_id,
                    "po_line_id": ctx.ids.next("POL"),
                    "item_id": f"ITEM-{ctx.rng.py.randint(1, 650):04d}",
                    "description": f"Synthetic {department.lower()} goods or services line {line_index + 1}",
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_amount": line_amount,
                    "gl_account": GL_BY_DEPARTMENT[department],
                    "department": department,
                    "cost_center": cost_center,
                    "source_system": "ERP-Procurement",
                }
            )
        subtotal = sum_money((row["line_amount"] for row in line_rows), currency)
        tax_rate = ctx.rng.weighted_choice({"0": 0.20, "0.05": 0.10, "0.075": 0.45, "0.10": 0.25})
        tax = money(subtotal * decimal(tax_rate), currency)
        shipping = money(ctx.rng.lognormal(18, 0.8, 0, 750), currency) if ctx.rng.py.random() < 0.35 else money(0, currency)
        total = money(subtotal + tax + shipping, currency)
        row = {
            "po_id": po_id,
            "vendor_id": vendor["vendor_id"],
            "po_date": po_date.isoformat(),
            "currency": currency,
            "subtotal": subtotal,
            "tax": tax,
            "shipping": shipping,
            "po_total": total,
            "department": department,
            "cost_center": cost_center,
            "gl_account": GL_BY_DEPARTMENT[department],
            "status": "issued",
            "expected_delivery_date": (po_date + timedelta(days=ctx.rng.py.randint(7, 45))).isoformat(),
            "created_by": ctx.rng.choice(employees)["employee_id"],
            "source_system": "ERP-Procurement",
        }
        ctx.dataset.add("purchase_orders", row)
        ctx.dataset.extend("po_lines", line_rows)
        ctx.audit("purchase_order", po_id, "created", f"{po_date.isoformat()}T09:00:00", str(row["created_by"]))
