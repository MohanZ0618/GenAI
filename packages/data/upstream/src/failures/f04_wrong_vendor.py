"""F04: invoice is associated with the wrong vendor."""

from __future__ import annotations

from src.failures.base import FailureInjector, InjectionContext


class WrongVendorInjector(FailureInjector):
    failure_type = "F04_INCORRECT_VENDOR_ASSOCIATION"
    difficulty = "medium"
    reasoning_hops = 3

    def inject(self, ctx: InjectionContext, case_id: str):
        allocated = {str(row["invoice_id"]) for row in ctx.dataset.rows("payment_allocations")}
        po_by_id = {row["po_id"]: row for row in ctx.dataset.rows("purchase_orders")}
        vendors = ctx.dataset.rows("vendors")
        candidates = [row for row in ctx.dataset.rows("invoices") if row["po_id"] and str(row["invoice_id"]) not in allocated
                      and ctx.available("invoice", str(row["invoice_id"]))]
        if not candidates:
            raise RuntimeError("F04 has no eligible invoice")
        invoice = ctx.rng.choice(candidates)
        original_vendor = str(invoice["vendor_id"])
        alternatives = [row for row in vendors if row["vendor_id"] != original_vendor and row["currency"] == invoice["currency"]
                        and row["vendor_type"] == next(v["vendor_type"] for v in vendors if v["vendor_id"] == original_vendor)]
        if not alternatives:
            alternatives = [row for row in vendors if row["vendor_id"] != original_vendor and row["currency"] == invoice["currency"]]
        wrong_vendor = ctx.rng.choice(alternatives)
        reason = "Invoice was selected under a similarly profiled but incorrect vendor master record"
        ctx.mutate(case_id, "invoices", invoice, "vendor_id", wrong_vendor["vendor_id"], reason)
        audit_id = ctx.audit(case_id, "invoice", str(invoice["invoice_id"]), "vendor_selected", str(invoice["created_at"]),
                             "SYSTEM-AP-INGEST", "vendor_id", "", str(wrong_vendor["vendor_id"]), "ERP-AP")
        po = po_by_id[invoice["po_id"]]
        ctx.claim(("invoice", str(invoice["invoice_id"])), ("vendor", original_vendor), ("vendor", str(wrong_vendor["vendor_id"])))
        return self.case(
            case_id, "invoice", str(invoice["invoice_id"]), original_vendor,
            [("invoice", str(invoice["invoice_id"])), ("purchase_order", str(po["po_id"])),
             ("vendor", original_vendor), ("vendor", str(wrong_vendor["vendor_id"])), ("audit_event", audit_id)],
            "The invoice vendor conflicts with the vendor named on the referenced purchase order.",
            "AP ingestion selected a similarly profiled but incorrect vendor master record.",
            "VENDOR_SELECTION_ERROR", ["invoices", "purchase_orders", "vendors", "audit_log"],
            [str(invoice["invoice_id"]), str(po["po_id"]), original_vendor, str(wrong_vendor["vendor_id"]), audit_id],
            "Reassign the invoice to the PO vendor, revalidate tax and banking attributes, and repeat approval.",
            str(invoice["created_at"]), ["ERP-AP", "ERP-Procurement", "VendorManagement"], "similar_vendor_profile",
        )

