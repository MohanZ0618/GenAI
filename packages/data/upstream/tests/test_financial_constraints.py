from __future__ import annotations

import unittest
from collections import defaultdict

from src.config import load_config
from src.generators import generate_clean_dataset
from src.utils.money import money, sum_money
from src.validation import validate_dataset
from src.validation.financial_rules import (
    validate_bank_statements,
    validate_gl_balance,
    validate_invoice_math,
    validate_payment_allocations,
    validate_po_math,
)
from src.validation.reconciliation_rules import validate_erp_bank, validate_operational_gl


class FinancialConstraintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config("config.yaml", scale="small")
        cls.dataset, cls.edges, _ = generate_clean_dataset(cls.config)

    def test_clean_quality_gate(self) -> None:
        report = validate_dataset(self.dataset, clean=True)
        self.assertTrue(report.passed, report.issues[:10])

    def test_core_financial_rules(self) -> None:
        self.assertEqual(validate_po_math(self.dataset), [])
        self.assertEqual(validate_invoice_math(self.dataset), [])
        self.assertEqual(validate_payment_allocations(self.dataset), [])
        self.assertEqual(validate_gl_balance(self.dataset), [])
        self.assertEqual(validate_bank_statements(self.dataset), [])

    def test_cross_system_reconciliation(self) -> None:
        self.assertEqual(validate_operational_gl(self.dataset), [])
        self.assertEqual(validate_erp_bank(self.dataset), [])

    def test_multi_invoice_and_split_payments_exist(self) -> None:
        by_payment: dict[str, list[dict]] = defaultdict(list)
        by_invoice: dict[str, list[dict]] = defaultdict(list)
        for allocation in self.dataset.rows("payment_allocations"):
            by_payment[str(allocation["payment_id"])].append(allocation)
            by_invoice[str(allocation["invoice_id"])].append(allocation)
        self.assertTrue(any(len(rows) > 1 for rows in by_payment.values()))
        self.assertTrue(any(len(rows) > 1 for rows in by_invoice.values()))
        payments = {str(row["payment_id"]): row for row in self.dataset.rows("payments")}
        for payment_id, allocations in by_payment.items():
            self.assertEqual(
                sum_money(row["allocated_amount"] for row in allocations),
                money(payments[payment_id]["payment_amount"]),
            )

    def test_sensitive_identifiers_are_tokenized(self) -> None:
        for vendor in self.dataset.rows("vendors"):
            self.assertTrue(str(vendor["bank_account_token"]).startswith("BA_TKN_"))
            self.assertTrue(str(vendor["bank_routing_token"]).startswith("BR_TKN_"))
            self.assertEqual(len(str(vendor["tax_id_hash"])), 24)
            self.assertTrue(str(vendor["vendor_name"]).startswith("Synthetic "))


if __name__ == "__main__":
    unittest.main()

