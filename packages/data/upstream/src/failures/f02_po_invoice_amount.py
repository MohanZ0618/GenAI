"""F02: invoice amount exceeds the corresponding purchase order."""

from __future__ import annotations

from src.failures.base import FailureInjector, InjectionContext
from src.utils.money import decimal, money


class POInvoiceAmountInjector(FailureInjector):
    failure_type = "F02_PO_INVOICE_AMOUNT_MISMATCH"
    difficulty = "easy"
    reasoning_hops = 2

    def inject(self, ctx: InjectionContext, case_id: str):
        allocated = {str(row["invoice_id"]) for row in ctx.dataset.rows("payment_allocations")}
        candidates = [row for row in ctx.dataset.rows("invoices") if row["po_id"] and str(row["invoice_id"]) not in allocated
                      and ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            raise RuntimeError("F02 has no eligible PO-backed unpaid invoice")
        invoice = ctx.rng.choice(candidates)
        lines = [row for row in ctx.dataset.rows("invoice_lines") if row["invoice_id"] == invoice["invoice_id"]]
        line = lines[0]
        currency = str(invoice["currency"])
        delta = money(max(decimal(line["line_amount"]) * decimal("0.07"), decimal("12.50")), currency)
        new_line_amount = money(decimal(line["line_amount"]) + delta, currency)
        new_unit = money(new_line_amount / decimal(line["quantity"]), currency)
        new_line_amount = money(decimal(new_unit) * decimal(line["quantity"]), currency)
        delta = money(new_line_amount - decimal(line["line_amount"]), currency)
        reason = "Supplier price variance posted above the authorized PO amount"
        ctx.mutate(case_id, "invoice_lines", line, "unit_price", new_unit, reason)
        ctx.mutate(case_id, "invoice_lines", line, "line_amount", new_line_amount, reason)
        ctx.mutate(case_id, "invoices", invoice, "subtotal", money(decimal(invoice["subtotal"]) + delta, currency), reason)
        ctx.mutate(case_id, "invoices", invoice, "invoice_total", money(decimal(invoice["invoice_total"]) + delta, currency), reason)
        gl_rows = [row for row in ctx.dataset.rows("gl_entries") if row["source_transaction_id"] == invoice["invoice_id"] and row["transaction_type"] == "invoice"]
        debit_row = next(row for row in gl_rows if decimal(row["debit"]) > 0 and row["gl_account"] == line["gl_account"])
        credit_row = next(row for row in gl_rows if row["gl_account"] == "200000-ACCOUNTS-PAYABLE")
        ctx.mutate(case_id, "gl_entries", debit_row, "debit", money(decimal(debit_row["debit"]) + delta, currency), reason)
        ctx.mutate(case_id, "gl_entries", credit_row, "credit", money(decimal(credit_row["credit"]) + delta, currency), reason)
        ctx.claim(("invoice", str(invoice["invoice_id"])), ("purchase_order", str(invoice["po_id"])))
        return self.case(
            case_id, "invoice", str(invoice["invoice_id"]), str(invoice["vendor_id"]),
            [("invoice", str(invoice["invoice_id"])), ("purchase_order", str(invoice["po_id"])),
             ("invoice_line", str(line["invoice_line_id"])), ("gl_journal", str(credit_row["journal_id"]))],
            "The invoiced price exceeds the amount authorized on its purchase order.",
            "A supplier price variance was entered without a corresponding purchase-order amendment.",
            "UNAUTHORIZED_PRICE_VARIANCE", ["purchase_orders", "po_lines", "invoices", "invoice_lines"],
            [str(invoice["po_id"]), str(invoice["invoice_id"]), str(line["invoice_line_id"])],
            "Place the invoice on hold and obtain an approved PO amendment or supplier credit before payment.",
            str(invoice["created_at"]), ["ERP-Procurement", "ERP-AP", "ERP-GL"], "price_variance",
        )

