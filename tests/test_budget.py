import unittest

from budget import calculate_budget


class BudgetTests(unittest.TestCase):
    def test_reserve_is_removed_before_daily_calculation(self):
        result = calculate_budget(1000, 5, 2)
        self.assertEqual(result["transportation"], 300)
        self.assertEqual(result["destination_budget"], 700)
        self.assertEqual(result["daily_destination_budget"], 140)
        self.assertEqual(result["daily_per_traveler"], 70)

    def test_allocations_reconcile_even_with_rounding(self):
        for total in (0.01, 123.47, 1000):
            for reserve in (0, 30, 100):
                with self.subTest(total=total, reserve=reserve):
                    result = calculate_budget(total, 3, 20, reserve)
                    self.assertAlmostEqual(sum(result["categories"].values()), result["destination_budget"])
                    self.assertAlmostEqual(result["transportation"] + result["destination_budget"], total)
                    self.assertTrue(all(value >= 0 for value in result["categories"].values()))

    def test_invalid_inputs(self):
        for args in ((0, 3, 1), (-1, 3, 1), (float("nan"), 3, 1), (500, 0, 1), (500, 3, 0), (500, 3, 1, 101)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                calculate_budget(*args)
