"""Auditable registry for all fifteen frozen Rules/SQL rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    failure_type: str
    tier: int
    hop_count: int
    required_tables: tuple[str, ...]
    required_fields: dict[str, tuple[str, ...]]
    join_path: str
    thresholds: tuple[str, ...]
    evidence_requirement: str
    missing_data_behavior: str

    def serializable(self) -> dict[str, object]:
        return asdict(self)


def _rule(
    number: int,
    name: str,
    tier: int,
    hops: int,
    tables: dict[str, tuple[str, ...]],
    join: str,
    thresholds: tuple[str, ...],
    evidence: str,
    missing: str,
) -> RuleDefinition:
    return RuleDefinition(
        rule_id=f"RSQL_F{number:02d}_V1",
        failure_type=f"F{number:02d}_{name}",
        tier=tier,
        hop_count=hops,
        required_tables=tuple(tables),
        required_fields=tables,
        join_path=join,
        thresholds=thresholds,
        evidence_requirement=evidence,
        missing_data_behavior=missing,
    )


RULES: tuple[RuleDefinition, ...] = (
    _rule(1, "DUPLICATE_INVOICE", 1, 0,
          {"invoices": ("invoice_id", "vendor_id", "invoice_number", "invoice_date", "currency", "invoice_total", "status")},
          "invoices self-join on lexical invoice-id pairs", ("DUPLICATE_DATE_WINDOW_DAYS", "DUPLICATE_REFERENCE_SIMILARITY"),
          "both invoice rows and all compared fields", "missing primary invoice/reference/vendor/currency/amount/date is insufficient"),
    _rule(2, "PO_INVOICE_AMOUNT_MISMATCH", 3, 2,
          {"invoices": ("invoice_id", "po_id", "currency", "tax", "shipping", "status", "invoice_total"),
           "invoice_lines": ("invoice_id", "invoice_line_id", "po_line_id", "quantity", "unit_price", "line_amount"),
           "purchase_orders": ("po_id", "currency", "tax", "shipping"),
           "po_lines": ("po_line_id", "po_id", "quantity", "unit_price", "line_amount")},
          "invoice -> purchase order; invoice -> invoice line -> PO line", ("PO_TOLERANCE_PERCENT", "MONEY_QUANTUM"),
          "invoice, PO, and offending line pair; all lines for header anomaly", "missing PO/line/currency/money/quantity is insufficient"),
    _rule(3, "QUANTITY_MISMATCH", 3, 2,
          {"invoices": ("invoice_id", "status"), "invoice_lines": ("invoice_id", "invoice_line_id", "po_line_id", "quantity"),
           "po_lines": ("po_line_id", "quantity")}, "invoice -> invoice line -> PO line", ("QUANTITY_TOLERANCE",),
          "invoice, offending invoice line, and referenced PO line", "missing invoice/line/referenced PO line/quantity is insufficient"),
    _rule(4, "INCORRECT_VENDOR_ASSOCIATION", 2, 1,
          {"invoices": ("invoice_id", "po_id", "vendor_id", "status"), "purchase_orders": ("po_id", "vendor_id")},
          "invoice -> purchase order", (), "invoice and referenced PO with both vendor IDs", "missing PO or vendor ID is insufficient"),
    _rule(5, "PAYMENT_WITHOUT_VALID_INVOICE", 3, 2,
          {"payments": ("payment_id", "payment_status", "settlement_status", "payment_amount"),
           "payment_allocations": ("payment_id", "invoice_id", "allocated_amount", "allocation_date"), "invoices": ("invoice_id",)},
          "payment -> allocation -> invoice, using left joins", ("MIN_POSITIVE_ALLOCATION",),
          "payment and any invalid allocation rows; anti-join count for absence", "unavailable table is insufficient; complete zero-match is anomaly"),
    _rule(6, "INVOICE_PAID_TWICE", 3, 2,
          {"invoices": ("invoice_id", "currency", "invoice_total", "status"),
           "payment_allocations": ("invoice_id", "payment_id", "allocated_amount", "allocation_date"),
           "payments": ("payment_id", "payment_currency", "payment_status", "settlement_status")},
          "invoice -> allocation -> payment", ("OVERPAYMENT_TOLERANCE",),
          "invoice and every effective payment/allocation in net paid", "missing amount/currency/table or broken contributing relationship is insufficient"),
    _rule(7, "PARTIAL_PAYMENT_RESIDUAL_BALANCE", 3, 2,
          {"invoices": ("invoice_id", "invoice_total", "currency", "status"),
           "payment_allocations": ("invoice_id", "payment_id", "allocated_amount", "allocation_date"),
           "payments": ("payment_id", "payment_currency", "payment_status", "settlement_status")},
          "invoice -> allocation -> payment", ("RESIDUAL_TOLERANCE",),
          "invoice and every effective payment/allocation in net paid", "missing required evidence is insufficient; zero-paid PAID is insufficient"),
    _rule(8, "APPROVAL_WORKFLOW_FAILURE", 3, 4,
          {"payments": ("payment_id", "created_at", "payment_status"),
           "payment_allocations": ("payment_id", "invoice_id", "allocation_date"),
           "invoices": ("invoice_id", "invoice_total", "currency"),
           "approval_events": ("invoice_id", "approval_level", "approver_id", "approver_role", "action", "event_timestamp"),
           "employees": ("employee_id", "role", "approval_limit", "active_status")},
          "payment -> allocation -> invoice -> approval; approval -> employee", ("APPROVAL_POLICY",),
          "payment/allocation/invoice, complete approval sequence, relied-upon employees", "missing required event in complete table is anomaly; unavailable evidence is insufficient"),
    _rule(9, "GL_POSTING_MISMATCH", 2, 1,
          {"payments": ("payment_id", "payment_date", "payment_currency", "payment_amount", "payment_status", "settlement_status"),
           "gl_entries": ("journal_id", "journal_line_id", "transaction_type", "source_transaction_id", "posting_date", "gl_account", "debit", "credit", "currency")},
          "payment -> source-linked PAYMENT journal", ("GL_POSTING_LAG_BUSINESS_DAYS", "MONEY_QUANTUM"),
          "payment and complete source journal; anti-join count for missing posting", "unavailable GL/invalid payment economics is insufficient; complete zero-match is anomaly"),
    _rule(10, "WRONG_ACCOUNTING_PERIOD", 2, 1,
          {"payments": ("payment_id", "payment_date"),
           "gl_entries": ("journal_id", "journal_line_id", "transaction_type", "source_transaction_id", "posting_date", "accounting_period")},
          "payment -> source-linked PAYMENT journal", ("ACCOUNTING_PERIOD_TOLERANCE",),
          "payment date and every source-linked journal line date/period", "missing journal/date/period is insufficient"),
    _rule(11, "VENDOR_MASTER_CHANGE_CONFLICT", 3, 2,
          {"payments": ("payment_id", "vendor_id", "bank_account_id", "created_at", "reference_number", "settlement_status"),
           "vendors": ("vendor_id", "bank_account_token"),
           "vendor_change_log": ("change_id", "vendor_id", "field_changed", "old_value", "new_value", "changed_at"),
           "bank_transactions": ("bank_transaction_id", "payment_reference", "counterparty_token", "status", "posted_date")},
          "payment -> vendor -> change history; payment reference -> bank transaction", (),
          "payment, vendor, decisive changes, and matched bank transaction", "missing reconstruction or bank outcome evidence is insufficient"),
    _rule(12, "ERP_PAYMENT_MISSING_FROM_BANK", 2, 1,
          {"payments": ("payment_id", "payment_date", "payment_method", "payment_status", "settlement_status", "reference_number"),
           "bank_transactions": ("bank_transaction_id", "payment_reference", "transaction_type", "direction", "status", "posted_date")},
          "normalized payment reference left anti-join to bank", ("CLEARING_LIMITS", "AS_OF_DATE"),
          "payment and complete-bank anti-join count", "unavailable bank/null or duplicate reference/invalid date or method is insufficient"),
    _rule(13, "BANK_TRANSACTION_MISSING_FROM_ERP", 2, 1,
          {"bank_transactions": ("bank_transaction_id", "payment_reference", "transaction_type", "direction", "amount", "currency", "status", "posted_date"),
           "payments": ("payment_id", "reference_number"),
           "gl_entries": ("journal_id", "journal_line_id", "transaction_type", "source_transaction_id", "debit", "credit", "currency")},
          "bank reference left anti-join to payment; bank source link to fee GL", ("MONEY_QUANTUM",),
          "bank row and matching-payment count; complete journal for fee exception", "unavailable table is insufficient; complete zero-match is anomaly"),
    _rule(14, "BANK_ERP_AMOUNT_MISMATCH", 3, 2,
          {"payments": ("payment_id", "payment_currency", "payment_amount", "reference_number"),
           "bank_transactions": ("bank_transaction_id", "payment_reference", "currency", "amount", "direction", "status", "posted_date"),
           "gl_entries": ("journal_id", "journal_line_id", "transaction_type", "source_transaction_id", "debit", "credit", "currency"),
           "audit_log": ("event_id", "entity_type", "entity_id", "event_type", "timestamp")},
          "payment -> bank settlement -> fee/FX accounting; parallel structured FX event", ("MONEY_QUANTUM", "AS_OF_DATE"),
          "payment and unique bank; linked journal/event for adjustment decision", "missing/ambiguous bank or cross-currency evidence is insufficient"),
    _rule(15, "INCORRECT_PAYMENT_BANK_MATCH", 3, 3,
          {"payments": ("payment_id", "vendor_id", "bank_account_id", "payment_date", "payment_currency", "payment_amount", "reference_number", "payment_status", "settlement_status"),
           "bank_transactions": ("bank_transaction_id", "counterparty_token", "transaction_date", "posted_date", "currency", "amount", "payment_reference", "direction", "status"),
           "payment_allocations": ("payment_id", "invoice_id", "allocated_amount", "allocation_date"),
           "invoices": ("invoice_id", "vendor_id")},
          "reciprocal bank -> referenced payment -> bank -> referenced payment cycle, plus allocation -> invoice", ("CROSS_MATCH_DATE_WINDOW_DAYS", "CROSS_MATCH_CANDIDATE_COUNT"),
          "both payments/banks and at least one valid allocation/invoice per payment", "missing/nonunique candidates or obligation evidence is insufficient"),
)


RULE_BY_ID = {rule.rule_id: rule for rule in RULES}
RULE_BY_FAILURE = {rule.failure_type: rule for rule in RULES}

PRECEDENCE: tuple[str, ...] = (
    "F15_INCORRECT_PAYMENT_BANK_MATCH",
    "F11_VENDOR_MASTER_CHANGE_CONFLICT",
    "F08_APPROVAL_WORKFLOW_FAILURE",
    "F06_INVOICE_PAID_TWICE",
    "F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE",
    "F05_PAYMENT_WITHOUT_VALID_INVOICE",
    "F01_DUPLICATE_INVOICE",
    "F04_INCORRECT_VENDOR_ASSOCIATION",
    "F03_QUANTITY_MISMATCH",
    "F02_PO_INVOICE_AMOUNT_MISMATCH",
    "F10_WRONG_ACCOUNTING_PERIOD",
    "F09_GL_POSTING_MISMATCH",
    "F14_BANK_ERP_AMOUNT_MISMATCH",
    "F12_ERP_PAYMENT_MISSING_FROM_BANK",
    "F13_BANK_TRANSACTION_MISSING_FROM_ERP",
)

PRECEDENCE_INDEX = {failure: index for index, failure in enumerate(PRECEDENCE)}


FIXED_CONFIG: dict[str, object] = {
    "AS_OF_DATE": "2026-06-30",
    "MONEY_QUANTUM": {"JPY": "1", "USD": "0.01", "EUR": "0.01", "GBP": "0.01", "CAD": "0.01"},
    "PO_TOLERANCE_PERCENT": "2.0",
    "QUANTITY_TOLERANCE": 0,
    "MIN_POSITIVE_ALLOCATION": ">0",
    "OVERPAYMENT_TOLERANCE": "currency_quantum",
    "RESIDUAL_TOLERANCE": "currency_quantum",
    "APPROVAL_POLICY": {"500": ["AUTO"], "10000": ["MANAGER"], "50000": ["MANAGER", "DIRECTOR"],
                        "250000": ["MANAGER", "DIRECTOR", "CONTROLLER"], "above": ["MANAGER", "DIRECTOR", "TREASURY"]},
    "GL_POSTING_LAG_BUSINESS_DAYS": 0,
    "ACCOUNTING_PERIOD_TOLERANCE": 0,
    "CLEARING_LIMITS": {"ACH": 3, "WIRE": 1, "CHECK": 10, "VIRTUAL_CARD": 2},
    "CLEARING_GRACE_BUSINESS_DAYS": 0,
    "CROSS_MATCH_DATE_WINDOW_CALENDAR_DAYS": 7,
    "CROSS_MATCH_CANDIDATE_COUNT": 1,
}

F01_GRID: tuple[tuple[int, str], ...] = tuple(
    (days, similarity)
    for days in (7, 14, 30)
    for similarity in ("0.85", "0.90", "0.95", "1.00")
)
