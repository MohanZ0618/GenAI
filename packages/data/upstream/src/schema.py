"""Canonical, ordered schemas for every model-visible table."""

from __future__ import annotations


TABLE_SCHEMAS: dict[str, list[str]] = {
    "vendors": [
        "vendor_id", "vendor_name", "vendor_type", "tax_id_hash", "country", "currency",
        "payment_terms", "default_payment_method", "bank_account_token", "bank_routing_token",
        "vendor_status", "created_at", "updated_at", "source_system",
    ],
    "vendor_change_log": [
        "change_id", "vendor_id", "field_changed", "old_value", "new_value", "changed_at",
        "changed_by", "change_reason", "source_system",
    ],
    "purchase_orders": [
        "po_id", "vendor_id", "po_date", "currency", "subtotal", "tax", "shipping", "po_total",
        "department", "cost_center", "gl_account", "status", "expected_delivery_date", "created_by",
        "source_system",
    ],
    "po_lines": [
        "po_id", "po_line_id", "item_id", "description", "quantity", "unit_price", "line_amount",
        "gl_account", "department", "cost_center", "source_system",
    ],
    "invoices": [
        "invoice_id", "vendor_id", "po_id", "invoice_number", "invoice_date", "received_date",
        "due_date", "currency", "subtotal", "tax", "shipping", "invoice_total", "payment_terms",
        "status", "duplicate_reference", "created_at", "source_system",
    ],
    "invoice_lines": [
        "invoice_id", "invoice_line_id", "po_line_id", "item_id", "quantity", "unit_price",
        "line_amount", "gl_account", "department", "cost_center", "source_system",
    ],
    "approval_events": [
        "approval_event_id", "invoice_id", "approval_level", "approver_id", "approver_role", "action",
        "event_timestamp", "previous_status", "new_status", "comments", "source_system",
    ],
    "payments": [
        "payment_id", "vendor_id", "payment_date", "payment_method", "payment_currency",
        "payment_amount", "bank_account_id", "payment_status", "settlement_status", "reference_number",
        "created_at", "source_system",
    ],
    "payment_allocations": [
        "payment_id", "invoice_id", "allocated_amount", "allocation_date", "source_system",
    ],
    "gl_entries": [
        "journal_id", "journal_line_id", "transaction_type", "source_transaction_id", "posting_date",
        "accounting_period", "gl_account", "debit", "credit", "currency", "department", "cost_center",
        "memo", "source_system",
    ],
    "bank_transactions": [
        "bank_transaction_id", "bank_account_id", "transaction_date", "posted_date", "transaction_type",
        "amount", "currency", "direction", "bank_reference", "counterparty_token", "payment_reference",
        "status", "source_system",
    ],
    "bank_statements": [
        "bank_statement_id", "bank_account_id", "statement_date", "opening_balance", "closing_balance",
        "total_debits", "total_credits", "source_system",
    ],
    "employees": [
        "employee_id", "role", "department", "approval_limit", "active_status", "source_system",
    ],
    "audit_log": [
        "event_id", "entity_type", "entity_id", "event_type", "timestamp", "actor_id", "field",
        "old_value", "new_value", "source_system",
    ],
}


PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "vendors": ("vendor_id",),
    "vendor_change_log": ("change_id",),
    "purchase_orders": ("po_id",),
    "po_lines": ("po_line_id",),
    "invoices": ("invoice_id",),
    "invoice_lines": ("invoice_line_id",),
    "approval_events": ("approval_event_id",),
    "payments": ("payment_id",),
    "payment_allocations": ("payment_id", "invoice_id", "allocation_date"),
    "gl_entries": ("journal_line_id",),
    "bank_transactions": ("bank_transaction_id",),
    "bank_statements": ("bank_statement_id",),
    "employees": ("employee_id",),
    "audit_log": ("event_id",),
}


MONEY_FIELDS: dict[str, tuple[str, ...]] = {
    "purchase_orders": ("subtotal", "tax", "shipping", "po_total"),
    "po_lines": ("unit_price", "line_amount"),
    "invoices": ("subtotal", "tax", "shipping", "invoice_total"),
    "invoice_lines": ("unit_price", "line_amount"),
    "employees": ("approval_limit",),
    "payments": ("payment_amount",),
    "payment_allocations": ("allocated_amount",),
    "gl_entries": ("debit", "credit"),
    "bank_transactions": ("amount",),
    "bank_statements": ("opening_balance", "closing_balance", "total_debits", "total_credits"),
}


def assert_row_schema(table: str, row: dict[str, object]) -> None:
    """Raise when a generator emits missing or undeclared model-visible fields."""
    expected = set(TABLE_SCHEMAS[table])
    actual = set(row)
    if actual != expected:
        raise ValueError(
            f"Schema mismatch for {table}: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )

