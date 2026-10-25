"""F03: quantity differs while the extended monetary amount remains plausible."""

from __future__ import annotations

from src.failures.base import FailureInjector, InjectionContext
from src.utils.money import decimal, money


def _alternative_quantity(amount, old_quantity: int) -> tuple[int, object] | None:
    for quantity in range(1, 31):
        if quantity == old_quantity:
            continue
        unit = money(decimal(amount) / decimal(quantity))
        if money(decimal(unit) * decimal(quantity)) == money(amount):
            return quantity, unit
    return None


class QuantityMismatchInjector(FailureInjector):
    failure_type = "F03_QUANTITY_MISMATCH"
    difficulty = "easy"
    reasoning_hops = 2

    def inject(self, ctx: InjectionContext, case_id: str):
        allocated = {str(row["invoice_id"]) for row in ctx.dataset.rows("payment_allocations")}
        invoice_by_id = {row["invoice_id"]: row for row in ctx.dataset.rows("invoices")}
        candidates = []
        for line in ctx.dataset.rows("invoice_lines"):
            invoice = invoice_by_id[line["invoice_id"]]
            alternative = _alternative_quantity(line["line_amount"], int(line["quantity"]))
            if line["po_line_id"] and str(invoice["invoice_id"]) not in allocated and alternative \
                    and ctx.available("invoice", str(invoice["invoice_id"])):
                candidates.append((invoice, line, alternative))
        if not candidates:
            raise RuntimeError("F03 has no eligible line")
        invoice, line, (quantity, unit_price) = ctx.rng.choice(candidates)
        reason = "Invoice quantity was keyed incorrectly while unit price was adjusted to preserve the total"
        ctx.mutate(case_id, "invoice_lines", line, "quantity", quantity, reason)
        ctx.mutate(case_id, "invoice_lines", line, "unit_price", unit_price, reason)
        ctx.claim(("invoice", str(invoice["invoice_id"])), ("po_line", str(line["po_line_id"])))
        return self.case(
            case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
            [("invoice", str(invoice["invoice_id"])), ("invoice_line", str(line["invoice_line_id"])),
             ("po_line", str(line["po_line_id"]))],
            "Invoice and PO extended amounts agree, but the billed quantity does not match the ordered quantity.",
            "The invoice quantity was keyed incorrectly and the unit price was changed in a way that concealed the error at total level.",
            "INVOICE_QUANTITY_KEYING", ["po_lines", "invoice_lines"],
            [str(line["po_line_id"]), str(line["invoice_line_id"]), str(invoice["invoice_id"])],
            "Correct the invoice quantity and unit price from supplier documentation, then rerun three-way matching.",
            str(invoice["created_at"]), ["ERP-Procurement", "ERP-AP"], "amount_preserving_quantity",
        )

