"""Orchestration of the valid baseline financial world."""

from __future__ import annotations

from typing import Any

from src.generators.approval_generator import generate_approvals
from src.generators.bank_generator import generate_bank_transactions
from src.generators.context import GenerationContext
from src.generators.gl_generator import generate_gl_entries
from src.generators.invoice_generator import generate_invoices
from src.generators.payment_generator import generate_payments
from src.generators.po_generator import generate_purchase_orders
from src.generators.vendor_generator import generate_employees, generate_vendors
from src.models import FinanceDataset
from src.utils.ids import IDFactory
from src.utils.random_utils import RandomSource


def generate_clean_dataset(config: dict[str, Any]) -> tuple[FinanceDataset, list[dict[str, str]], IDFactory]:
    """Generate a fully consistent world before any benchmark mutation."""
    seed = int(config["seed"])
    ctx = GenerationContext(config, FinanceDataset(), RandomSource(seed), IDFactory(seed))
    generate_employees(ctx)
    generate_vendors(ctx)
    generate_purchase_orders(ctx)
    generate_invoices(ctx)
    generate_approvals(ctx)
    generate_payments(ctx)
    generate_gl_entries(ctx)
    generate_bank_transactions(ctx)
    return ctx.dataset, ctx.causal_edges, ctx.ids

