import unittest

from invoice import calculate_invoice


class InvoiceTotalsTest(unittest.TestCase):
    def test_calculates_discount_tax_and_total(self) -> None:
        items = [
            {"quantity": 2, "unit_price": "20.00"},
            {"quantity": 1, "unit_price": "10.00", "discount_percent": "10"},
        ]

        self.assertEqual(
            calculate_invoice(items, tax_rate="0.0825"),
            {"subtotal": "49.00", "tax": "4.04", "total": "53.04"},
        )

    def test_empty_invoice(self) -> None:
        self.assertEqual(calculate_invoice([], tax_rate="0.10"), {"subtotal": "0.00", "tax": "0.00", "total": "0.00"})

    def test_rejects_negative_values(self) -> None:
        with self.assertRaises(ValueError):
            calculate_invoice([{"quantity": -1, "unit_price": "1.00"}])
        with self.assertRaises(ValueError):
            calculate_invoice([{"quantity": 1, "unit_price": "1.00", "discount_percent": "-5"}])
        with self.assertRaises(ValueError):
            calculate_invoice([], tax_rate="-0.1")


if __name__ == "__main__":
    unittest.main()
