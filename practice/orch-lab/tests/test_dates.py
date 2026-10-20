import unittest

from src.dates import days_in_month, is_leap_year


class TestDates(unittest.TestCase):
    def test_leap_years(self):
        self.assertTrue(is_leap_year(2024))
        self.assertTrue(is_leap_year(2000))
        self.assertFalse(is_leap_year(2023))
        self.assertFalse(is_leap_year(1900))

    def test_february(self):
        self.assertEqual(days_in_month(2024, 2), 29)
        self.assertEqual(days_in_month(1900, 2), 28)

    def test_other_months(self):
        self.assertEqual(days_in_month(2023, 4), 30)
        self.assertEqual(days_in_month(2023, 1), 31)
