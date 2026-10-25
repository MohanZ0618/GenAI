from __future__ import annotations

import unittest

from src.config import load_config
from src.generators import generate_clean_dataset
from src.utils.dates import parse_date
from src.validation.temporal_rules import validate_temporal_order


class TemporalConstraintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset, _, _ = generate_clean_dataset(load_config("config.yaml", scale="small"))

    def test_cross_table_temporal_rules(self) -> None:
        self.assertEqual(validate_temporal_order(self.dataset), [])

    def test_po_invoice_received_order(self) -> None:
        po_dates = {row["po_id"]: parse_date(str(row["po_date"])) for row in self.dataset.rows("purchase_orders")}
        for invoice in self.dataset.rows("invoices"):
            invoice_date = parse_date(str(invoice["invoice_date"]))
            self.assertLessEqual(invoice_date, parse_date(str(invoice["received_date"])))
            if invoice["po_id"]:
                self.assertLessEqual(po_dates[invoice["po_id"]], invoice_date)

    def test_bank_posting_not_before_transaction(self) -> None:
        for row in self.dataset.rows("bank_transactions"):
            self.assertLessEqual(parse_date(str(row["transaction_date"])), parse_date(str(row["posted_date"])))


if __name__ == "__main__":
    unittest.main()

