from decimal import Decimal

import pytest

from src.rules_sql.engine import ANOMALY, INSUFFICIENT, MATCH, F01Parameters

from tests.rules_sql.helpers import active_invoice, engine, payment, row


def test_f01_date_and_similarity_boundaries(tmp_path) -> None:
    tables = {"invoices": [
        active_invoice("I1", invoice_number="ABCDEFGHIJ", invoice_date="2026-06-01"),
        active_invoice("I2", invoice_number="ABCDEFGHIX", invoice_date="2026-06-15"),
    ]}
    baseline = engine(tmp_path, tables, F01Parameters(14, Decimal("0.90")))
    assert baseline._f01("I1").status == ANOMALY
    baseline.store.row("invoices", "I2")["invoice_date"] = "2026-06-16"
    assert baseline._f01("I1").status == MATCH
    baseline.store.row("invoices", "I2")["invoice_date"] = "2026-06-15"
    baseline.f01 = F01Parameters(14, Decimal("0.95"))
    assert baseline._f01("I1").status == MATCH


@pytest.mark.parametrize("delta,expected", [("1.99", MATCH), ("2.00", MATCH), ("2.01", ANOMALY)])
def test_f02_percent_tolerance_below_at_above(tmp_path, delta, expected) -> None:
    observed = Decimal("100.00") + Decimal(delta)
    tables = {
        "invoices": [active_invoice("I1", po_id="PO1", invoice_total=str(observed), subtotal=str(observed))],
        "purchase_orders": [row("purchase_orders", po_id="PO1", vendor_id="V1", currency="USD", tax="0", shipping="0")],
        "invoice_lines": [row("invoice_lines", invoice_id="I1", invoice_line_id="IL1", po_line_id="PL1", quantity="1", unit_price=str(observed), line_amount=str(observed))],
        "po_lines": [row("po_lines", po_id="PO1", po_line_id="PL1", quantity="1", unit_price="100.00", line_amount="100.00")],
    }
    assert engine(tmp_path, tables)._f02("I1").status == expected


def test_f03_exact_integer_and_fractional_quantity(tmp_path) -> None:
    tables = {
        "invoices": [active_invoice("I1")],
        "invoice_lines": [row("invoice_lines", invoice_id="I1", invoice_line_id="IL1", po_line_id="PL1", quantity="5")],
        "po_lines": [row("po_lines", po_id="PO1", po_line_id="PL1", quantity="5")],
    }
    baseline = engine(tmp_path, tables)
    assert baseline._f03("I1").status == MATCH
    baseline.store.row("po_lines", "PL1")["quantity"] = "6"
    assert baseline._f03("I1").status == ANOMALY
    baseline.store.row("po_lines", "PL1")["quantity"] = "5.5"
    assert baseline._f03("I1").status == INSUFFICIENT


def test_f04_case_sensitive_trimmed_vendor_ids(tmp_path) -> None:
    tables = {
        "invoices": [active_invoice("I1", po_id="PO1", vendor_id=" V1 ")],
        "purchase_orders": [row("purchase_orders", po_id="PO1", vendor_id="V1")],
    }
    baseline = engine(tmp_path, tables)
    assert baseline._f04("I1").status == MATCH
    baseline.store.row("purchase_orders", "PO1")["vendor_id"] = "v1"
    assert baseline._f04("I1").status == ANOMALY


def test_f05_strictly_positive_allocation_boundary(tmp_path) -> None:
    tables = {
        "payments": [payment("P1")],
        "invoices": [active_invoice("I1")],
        "payment_allocations": [row("payment_allocations", payment_id="P1", invoice_id="I1", allocated_amount="0", allocation_date="2026-06-01")],
    }
    baseline = engine(tmp_path, tables)
    assert baseline._f05("P1").status == ANOMALY
    baseline.store.allocations_by_payment["P1"][0]["allocated_amount"] = "0.01"
    assert baseline._f05("P1").status == MATCH


@pytest.mark.parametrize("allocated,f06,f07", [
    ("100.01", MATCH, MATCH),
    ("100.02", ANOMALY, MATCH),
    ("99.99", MATCH, MATCH),
    ("99.98", MATCH, ANOMALY),
])
def test_f06_f07_currency_quantum_boundaries(tmp_path, allocated, f06, f07) -> None:
    tables = {
        "invoices": [active_invoice("I1", status="paid")],
        "payments": [payment("P1", payment_amount=allocated)],
        "payment_allocations": [row("payment_allocations", payment_id="P1", invoice_id="I1", allocated_amount=allocated, allocation_date="2026-06-01")],
    }
    baseline = engine(tmp_path, tables)
    assert baseline._f06("I1").status == f06
    assert baseline._f07("I1").status == f07


def test_f07_zero_paid_special_insufficient_branch(tmp_path) -> None:
    baseline = engine(tmp_path, {"invoices": [active_invoice("I1", status="paid")]})
    assert baseline._f07("I1").status == INSUFFICIENT


def test_f08_policy_amount_boundaries() -> None:
    from src.rules_sql.engine import FrozenRulesBaseline
    assert FrozenRulesBaseline._required_roles(Decimal("500")) == ["AUTO"]
    assert FrozenRulesBaseline._required_roles(Decimal("500.01")) == ["MANAGER"]
    assert FrozenRulesBaseline._required_roles(Decimal("10000")) == ["MANAGER"]
    assert FrozenRulesBaseline._required_roles(Decimal("10000.01")) == ["MANAGER", "DIRECTOR"]
    assert FrozenRulesBaseline._required_roles(Decimal("50000.01"))[-1] == "CONTROLLER"
    assert FrozenRulesBaseline._required_roles(Decimal("250000.01"))[-1] == "TREASURY"


@pytest.mark.parametrize("journal_amount,expected", [("100.01", MATCH), ("100.02", ANOMALY)])
def test_f09_money_boundary(tmp_path, journal_amount, expected) -> None:
    tables = {
        "payments": [payment("P1")],
        "gl_entries": [
            row("gl_entries", journal_id="J1", journal_line_id="G1", transaction_type="payment", source_transaction_id="P1", posting_date="2026-06-01", accounting_period="2026-06", gl_account="200000-ACCOUNTS-PAYABLE", debit=journal_amount, credit="0", currency="USD"),
            row("gl_entries", journal_id="J1", journal_line_id="G2", transaction_type="payment", source_transaction_id="P1", posting_date="2026-06-01", accounting_period="2026-06", gl_account="100000-CASH", debit="0", credit=journal_amount, currency="USD"),
        ],
    }
    assert engine(tmp_path, tables)._f09("P1").status == expected


def test_f10_month_boundary_and_invalid_period(tmp_path) -> None:
    tables = {
        "payments": [payment("P1", payment_date="2026-01-31")],
        "gl_entries": [row("gl_entries", journal_id="J1", journal_line_id="G1", transaction_type="payment", source_transaction_id="P1", posting_date="2026-01-31", accounting_period="2026-01")],
    }
    baseline = engine(tmp_path, tables)
    assert baseline._f10("P1").status == MATCH
    baseline.store.row("gl_entries", "G1")["posting_date"] = "2026-02-01"
    baseline.store.row("gl_entries", "G1")["accounting_period"] = "2026-02"
    assert baseline._f10("P1").status == ANOMALY
    baseline.store.row("gl_entries", "G1")["accounting_period"] = "2026-13"
    assert baseline._f10("P1").status == INSUFFICIENT


def test_f11_effective_token_and_return_outcome(tmp_path) -> None:
    tables = {
        "vendors": [row("vendors", vendor_id="V1", bank_account_token="NEW")],
        "vendor_change_log": [row("vendor_change_log", change_id="C1", vendor_id="V1", field_changed="bank_account_token", old_value="OLD", new_value="NEW", changed_at="2026-05-01T00:00:00")],
        "payments": [payment("P1", bank_account_id="OLD", reference_number="REF1", settlement_status="failed", created_at="2026-06-01T10:00:00")],
        "bank_transactions": [row("bank_transactions", bank_transaction_id="B1", payment_reference="REF1", counterparty_token="OLD", status="returned", posted_date="2026-06-02")],
    }
    baseline = engine(tmp_path, tables)
    assert baseline._f11("P1").status == ANOMALY
    baseline.store.row("payments", "P1")["bank_account_id"] = "NEW"
    assert baseline._f11("P1").status == MATCH


@pytest.mark.parametrize("payment_date,expected", [("2026-06-25", MATCH), ("2026-06-24", ANOMALY)])
def test_f12_business_day_clearing_boundary(tmp_path, payment_date, expected) -> None:
    baseline = engine(tmp_path, {"payments": [payment("P1", payment_date=payment_date, payment_method="ACH", reference_number="UNIQUE")]})
    assert baseline._f12("P1").status == expected


def test_f13_operational_absence_and_balanced_fee_exception(tmp_path) -> None:
    operational = row("bank_transactions", bank_transaction_id="B1", payment_reference="MISSING", transaction_type="ACH debit", direction="debit", amount="10", currency="USD", status="posted", posted_date="2026-06-01")
    baseline = engine(tmp_path, {"bank_transactions": [operational]})
    assert baseline._f13("B1").status == ANOMALY
    tables = {
        "bank_transactions": [row("bank_transactions", bank_transaction_id="BF", payment_reference="FEE", transaction_type="bank fee", direction="debit", amount="10", currency="USD", status="posted", posted_date="2026-06-01")],
        "gl_entries": [
            row("gl_entries", journal_id="JF", journal_line_id="GF1", transaction_type="bank fee", source_transaction_id="BF", debit="10", credit="0", currency="USD"),
            row("gl_entries", journal_id="JF", journal_line_id="GF2", transaction_type="bank fee", source_transaction_id="BF", debit="0", credit="10", currency="USD"),
        ],
    }
    assert engine(tmp_path, tables)._f13("BF").status == MATCH


@pytest.mark.parametrize("bank_amount,expected", [("100.01", MATCH), ("100.02", ANOMALY)])
def test_f14_amount_delta_boundary(tmp_path, bank_amount, expected) -> None:
    tables = {
        "payments": [payment("P1", reference_number="R1")],
        "bank_transactions": [row("bank_transactions", bank_transaction_id="B1", payment_reference="R1", transaction_type="ACH debit", direction="debit", status="posted", posted_date="2026-06-02", amount=bank_amount, currency="USD")],
    }
    assert engine(tmp_path, tables)._f14("P1").status == expected


def test_f14_ignores_non_fx_audit_event_timestamp(tmp_path) -> None:
    tables = {
        "payments": [payment("P1", reference_number="R1", payment_currency="USD")],
        "bank_transactions": [row("bank_transactions", bank_transaction_id="B1", payment_reference="R1", transaction_type="ACH debit", direction="debit", status="posted", posted_date="2026-06-02", amount="90", currency="EUR")],
        "gl_entries": [
            row("gl_entries", journal_id="JFX", journal_line_id="GX1", transaction_type="fx settlement", source_transaction_id="B1", debit="90", credit="0", currency="EUR"),
            row("gl_entries", journal_id="JFX", journal_line_id="GX2", transaction_type="fx settlement", source_transaction_id="B1", debit="0", credit="90", currency="EUR"),
        ],
        "audit_log": [
            row("audit_log", event_id="BAD", entity_type="bank_transaction", entity_id="B1", event_type="workflow_override", timestamp="not-a-timestamp"),
            row("audit_log", event_id="FX", entity_type="bank_transaction", entity_id="B1", event_type="fx_conversion_applied", timestamp="2026-06-02T08:00:00"),
        ],
    }
    assert engine(tmp_path, tables)._f14("P1").status == MATCH


@pytest.mark.parametrize("bank_date,expected", [("2026-06-08", ANOMALY), ("2026-06-09", INSUFFICIENT)])
def test_f15_cross_match_seven_day_boundary(tmp_path, bank_date, expected) -> None:
    tables = {
        "vendors": [row("vendors", vendor_id="V1")],
        "invoices": [active_invoice("I1", vendor_id="V1"), active_invoice("I2", vendor_id="V1")],
        "payments": [
            payment("P1", vendor_id="V1", payment_date="2026-06-01", payment_amount="100", bank_account_id="T1", reference_number="R1"),
            payment("P2", vendor_id="V1", payment_date="2026-06-01", payment_amount="200", bank_account_id="T2", reference_number="R2"),
        ],
        "payment_allocations": [
            row("payment_allocations", payment_id="P1", invoice_id="I1", allocated_amount="100", allocation_date="2026-06-01"),
            row("payment_allocations", payment_id="P2", invoice_id="I2", allocated_amount="200", allocation_date="2026-06-01"),
        ],
        "bank_transactions": [
            row("bank_transactions", bank_transaction_id="B1", counterparty_token="T1", transaction_date=bank_date, posted_date=bank_date, currency="USD", amount="100", payment_reference="R2", direction="debit", status="posted"),
            row("bank_transactions", bank_transaction_id="B2", counterparty_token="T2", transaction_date=bank_date, posted_date=bank_date, currency="USD", amount="200", payment_reference="R1", direction="debit", status="posted"),
        ],
    }
    assert engine(tmp_path, tables)._f15(["P1"]).status == expected
