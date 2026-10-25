"""F01: duplicate economic invoice recorded twice."""

from __future__ import annotations

from src.failures.base import FailureInjector, InjectionContext


class DuplicateInvoiceInjector(FailureInjector):
    failure_type = "F01_DUPLICATE_INVOICE"
    difficulty = "easy"
    reasoning_hops = 2

    def inject(self, ctx: InjectionContext, case_id: str):
        allocated = {str(row["invoice_id"]) for row in ctx.dataset.rows("payment_allocations")}
        candidates = [
            row for row in ctx.dataset.rows("invoices")
            if str(row["invoice_id"]) not in allocated and ctx.available("invoice", str(row["invoice_id"]))
        ]
        if not candidates:
            raise RuntimeError("F01 has no eligible unpaid invoice")
        original = ctx.rng.choice(candidates)
        duplicate = dict(original)
        duplicate_id = ctx.ids.next("INV")
        duplicate["invoice_id"] = duplicate_id
        number = str(original["invoice_number"])
        duplicate["invoice_number"] = number.replace("-", "") if "-" in number else f"{number}-A"
        duplicate["duplicate_reference"] = ""
        duplicate["status"] = "received"
        reason = "Second entry of the same economic invoice with normalized punctuation"
        ctx.add(case_id, "invoices", duplicate, reason)
        original_lines = [row for row in ctx.dataset.rows("invoice_lines") if row["invoice_id"] == original["invoice_id"]]
        new_line_ids: list[str] = []
        for line in original_lines:
            cloned = dict(line)
            cloned["invoice_id"] = duplicate_id
            cloned["invoice_line_id"] = ctx.ids.next("INVL")
            new_line_ids.append(str(cloned["invoice_line_id"]))
            ctx.add(case_id, "invoice_lines", cloned, reason)
        ctx.edge("invoice", duplicate_id, "duplicates_economic_obligation", "invoice", str(original["invoice_id"]))
        ctx.claim(("invoice", str(original["invoice_id"])), ("invoice", duplicate_id))
        return self.case(
            case_id, "invoice", duplicate_id, str(original["vendor_id"]),
            [("invoice", str(original["invoice_id"])), ("invoice", duplicate_id)],
            "Two invoice records represent the same vendor obligation despite formatting differences in the invoice number.",
            "The same economic invoice was entered a second time after punctuation in its reference was normalized.",
            "DUPLICATE_AP_ENTRY", ["invoices", "invoice_lines"],
            [str(original["invoice_id"]), duplicate_id, *new_line_ids[:1]],
            "Void the duplicate invoice, retain the original payable, and strengthen normalized duplicate-reference checks.",
            str(duplicate["created_at"]), ["ERP-AP"], "non_exact_reference",
        )

