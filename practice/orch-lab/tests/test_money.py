import unittest

from src.money import add_tax, format_cents


class TestMoney(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(format_cents(1250), "$12.50")
        self.assertEqual(format_cents(1205), "$12.05")
        self.assertEqual(format_cents(7), "$0.07")

    def test_add_tax(self):
        self.assertEqual(add_tax(1000, 0.2), 1200)
