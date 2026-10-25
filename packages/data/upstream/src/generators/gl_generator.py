"""Balanced double-entry journal generation."""

from __future__ import annotations

from src.generators.context import GenerationContext
from src.utils.dates import accounting_period
from src.utils.money import money


def _line(
    ctx: GenerationContext,
    journal_id: str,
    transaction_type: str,
    source_id: str,
    posting_date: str,
    account: str,
    debit,
    credit,
    currency: str,
    department: str,
    cost_center: str,
    memo: str,
) -> dict[str, object]:
    return {
        "journal_id": journal_id,
        "journal_line_id": ctx.ids.next("JEL"),
        "transaction_type": transaction_type,
        "source_transaction_id": source_id,
        "posting_date": posting_date,
        "accounting_period": accounting_period(posting_date),
        "gl_account": account,
        "debit": money(debit, currency),
        "credit": money(credit, currency),
        "currency": currency,
        "department": department,
        "cost_center": cost_center,
        "memo": memo,
        "source_system": "ERP-GL",
    }


def generate_gl_entries(ctx: GenerationContext) -> None:
    invoice_lines: dict[str, list[dict[str, object]]] = {}
    for row in ctx.dataset.rows("invoice_lines"):
        invoice_lines.setdefault(str(row["invoice_id"]), []).append(row)
    invoice_by_id = {row["invoice_id"]: row for row in ctx.dataset.rows("invoices")}

    for invoice in ctx.dataset.rows("invoices"):
        invoice_id = str(invoice["invoice_id"])
        currency = str(invoice["currency"])
        journal_id = ctx.ids.next("JE")
        for source_line in invoice_lines[invoice_id]:
            ctx.dataset.add(
                "gl_entries",
                _line(
                    ctx, journal_id, "invoice", invoice_id, str(invoice["received_date"]),
                    str(source_line["gl_account"]), source_line["line_amount"], 0, currency,
                    str(source_line["department"]), str(source_line["cost_center"]), "Invoice expense recognition",
                ),
            )
        representative = invoice_lines[invoice_id][0]
        if invoice["tax"]:
            ctx.dataset.add(
                "gl_entries",
                _line(ctx, journal_id, "invoice", invoice_id, str(invoice["received_date"]), "141000-RECOVERABLE-TAX",
                      invoice["tax"], 0, currency, str(representative["department"]), str(representative["cost_center"]),
                      "Invoice tax recognition"),
            )
        if invoice["shipping"]:
            ctx.dataset.add(
                "gl_entries",
                _line(ctx, journal_id, "invoice", invoice_id, str(invoice["received_date"]), "625000-FREIGHT",
                      invoice["shipping"], 0, currency, str(representative["department"]),
                      str(representative["cost_center"]), "Invoice freight recognition"),
            )
        ctx.dataset.add(
            "gl_entries",
            _line(ctx, journal_id, "invoice", invoice_id, str(invoice["received_date"]), "200000-ACCOUNTS-PAYABLE",
                  0, invoice["invoice_total"], currency, str(representative["department"]),
                  str(representative["cost_center"]), "Invoice payable recognition"),
        )
        ctx.edge("invoice", invoice_id, "generates", "gl_journal", journal_id)

    for payment in ctx.dataset.rows("payments"):
        payment_id = str(payment["payment_id"])
        currency = str(payment["payment_currency"])
        journal_id = ctx.ids.next("JE")
        ctx.dataset.add(
            "gl_entries",
            _line(ctx, journal_id, "payment", payment_id, str(payment["payment_date"]), "200000-ACCOUNTS-PAYABLE",
                  payment["payment_amount"], 0, currency, "Finance", "CC-03-01", "Payment clears payable"),
        )
        ctx.dataset.add(
            "gl_entries",
            _line(ctx, journal_id, "payment", payment_id, str(payment["payment_date"]), "100000-CASH",
                  0, payment["payment_amount"], currency, "Finance", "CC-03-01", "Payment cash disbursement"),
        )
        ctx.edge("payment", payment_id, "generates", "gl_journal", journal_id)

