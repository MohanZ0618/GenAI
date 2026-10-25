"""Synthetic vendor, employee, and vendor-history generation."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

from src.generators.context import GenerationContext
from src.utils.dates import at_time, parse_date, random_date
from src.utils.money import money


DEPARTMENTS = ["Engineering", "Operations", "Finance", "Sales", "Marketing", "People", "Legal", "IT"]
VENDOR_TYPES = {"supplier": 0.34, "services": 0.28, "software": 0.18, "logistics": 0.10, "professional": 0.10}
TERMS = {"NET30": 0.53, "NET45": 0.18, "NET60": 0.10, "NET15": 0.12, "DUE_ON_RECEIPT": 0.07}
ADJECTIVES = ["Amber", "Atlas", "Blue", "Cedar", "Cobalt", "Delta", "Evergreen", "Harbor", "North", "Quartz", "Silver", "Summit"]
NOUNS = ["Components", "Consulting", "Logistics", "Systems", "Supply", "Services", "Networks", "Works", "Partners", "Solutions"]
COUNTRY_BY_CURRENCY = {"USD": "US", "EUR": "DE", "GBP": "GB", "CAD": "CA", "JPY": "JP"}


def generate_employees(ctx: GenerationContext) -> None:
    count = ctx.config["scale"]["employees"]
    roles = [
        ("requester", "2500"),
        ("manager", "10000"),
        ("director", "50000"),
        ("controller", "250000"),
        ("treasury", "1000000"),
        ("ap_specialist", "5000"),
    ]
    for index in range(count):
        role, limit = roles[index % len(roles)]
        ctx.dataset.add(
            "employees",
            {
                "employee_id": ctx.ids.next("EMP", 5),
                "role": role,
                "department": DEPARTMENTS[index % len(DEPARTMENTS)],
                "approval_limit": money(limit),
                "active_status": "active" if index % 29 else "inactive",
                "source_system": "HRIS",
            },
        )


def generate_vendors(ctx: GenerationContext) -> None:
    config = ctx.config
    count = config["scale"]["vendors"]
    start = parse_date(config["date_range"]["start"])
    currencies = config["generation"]["currencies"]
    payment_methods = config["generation"]["payment_methods"]
    vendors: list[dict[str, object]] = []
    for index in range(count):
        vendor_id = ctx.ids.next("VND", 6)
        currency = ctx.rng.weighted_choice(currencies)
        created = random_date(ctx.rng.py, start - timedelta(days=1460), start - timedelta(days=30))
        row = {
            "vendor_id": vendor_id,
            "vendor_name": f"Synthetic {ctx.rng.choice(ADJECTIVES)} {ctx.rng.choice(NOUNS)} {index + 1:04d}",
            "vendor_type": ctx.rng.weighted_choice(VENDOR_TYPES),
            "tax_id_hash": sha256(f"finrca-synthetic-{ctx.config['seed']}-{vendor_id}".encode()).hexdigest()[:24],
            "country": COUNTRY_BY_CURRENCY[currency],
            "currency": currency,
            "payment_terms": ctx.rng.weighted_choice(TERMS),
            "default_payment_method": ctx.rng.weighted_choice(payment_methods),
            "bank_account_token": f"BA_TKN_{ctx.config['seed'] % 1000:03d}_{index + 1:07d}",
            "bank_routing_token": f"BR_TKN_{(index % 97) + 1:04d}",
            "vendor_status": "active" if index % 37 else "on_hold",
            "created_at": at_time(created, 10),
            "updated_at": at_time(created, 10),
            "source_system": "VendorManagement",
        }
        ctx.dataset.add("vendors", row)
        vendors.append(row)

    weights = ctx.rng.pareto_weights(count, shape=1.25)
    # Randomize which named vendor receives each concentration weight.
    ctx.rng.py.shuffle(weights)
    ctx.metadata["vendor_weights"] = weights

    change_count = round(count * float(config["generation"]["vendor_change_rate"]))
    employees = [row for row in ctx.dataset.rows("employees") if row["active_status"] == "active"]
    fields = ["payment_terms", "bank_account_token", "vendor_status", "currency"]
    for vendor in ctx.rng.shuffled(vendors)[:change_count]:
        field = ctx.rng.choice(fields)
        old_value = str(vendor[field])
        if field == "payment_terms":
            candidates = [value for value in TERMS if value != old_value]
            new_value = ctx.rng.choice(candidates)
            reason = "Commercial terms amendment"
        elif field == "bank_account_token":
            new_value = f"BA_TKN_{ctx.config['seed'] % 1000:03d}_{ctx.ids.counters['CHG'] + count + 1:07d}"
            reason = "Vendor-verified banking update"
        elif field == "vendor_status":
            new_value = "active" if old_value != "active" else "on_hold"
            reason = "Periodic vendor compliance review"
        else:
            candidates = [value for value in currencies if value != old_value]
            new_value = ctx.rng.choice(candidates)
            reason = "Contracting entity currency update"
        changed = random_date(ctx.rng.py, start, start + timedelta(days=45))
        actor = ctx.rng.choice(employees)["employee_id"]
        change_id = ctx.ids.next("CHG")
        ctx.dataset.add(
            "vendor_change_log",
            {
                "change_id": change_id,
                "vendor_id": vendor["vendor_id"],
                "field_changed": field,
                "old_value": old_value,
                "new_value": new_value,
                "changed_at": at_time(changed, 11),
                "changed_by": actor,
                "change_reason": reason,
                "source_system": "VendorManagement",
            },
        )
        vendor[field] = new_value
        vendor["updated_at"] = at_time(changed, 11)
        ctx.edge("vendor_change", change_id, "updates", "vendor", str(vendor["vendor_id"]))
        ctx.audit(
            "vendor",
            str(vendor["vendor_id"]),
            "master_data_changed",
            at_time(changed, 11),
            str(actor),
            field,
            old_value,
            str(new_value),
            "VendorManagement",
        )

