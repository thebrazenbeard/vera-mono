"""Source-level inquiry-choice negatives; no model behavior is implied."""
import unittest

from vera_assurance.inquiry_choice import InquiryCandidate, select_inquiry


def candidate(gap, uncertainty=0.8, gain=0.6, cost=2):
    return InquiryCandidate(gap, "Why is this prediction uncertain?", uncertainty, gain, cost)


class InquiryChoiceTests(unittest.TestCase):
    def test_selects_best_utility_and_is_order_independent(self):
        a, b = candidate("a"), candidate("b", 0.9, 0.9, 1)
        first = select_inquiry((a, b), probe_budget=2)
        second = select_inquiry((b, a), probe_budget=2)
        self.assertEqual(first, second)
        self.assertEqual(first.selected_gap_id, "b")
        self.assertEqual(first.authorization_effect, "NONE")
        self.assertFalse(first.self_inquiry_verified)

    def test_tie_is_deterministic(self):
        self.assertEqual(select_inquiry((candidate("z"), candidate("a")),
                                        probe_budget=2).selected_gap_id, "a")

    def test_disarmed_by_budget_and_threshold(self):
        self.assertIsNone(select_inquiry((candidate("a"),), probe_budget=1).selected_gap_id)
        self.assertIsNone(select_inquiry((candidate("a"),),
                                         probe_budget=2, minimum_utility=1).selected_gap_id)
        self.assertIsNone(select_inquiry((), probe_budget=2).selected_gap_id)

    def test_invalid_or_forged_budget_and_inputs_fail(self):
        for budget in (-1, 129, True, 1.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                select_inquiry((), probe_budget=budget)
        for bad in (float("nan"), float("inf"), -0.1, 1.1, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                select_inquiry((candidate("a", uncertainty=bad),), probe_budget=2)
        for bad in (0, -1, True, 1.5):
            with self.subTest(cost=bad), self.assertRaises(ValueError):
                select_inquiry((candidate("a", cost=bad),), probe_budget=2)
        with self.assertRaises(ValueError):
            select_inquiry((candidate("a"), candidate("a")), probe_budget=2)
        with self.assertRaises(ValueError):
            select_inquiry((candidate("a"),), probe_budget=2,
                           minimum_utility=float("nan"))
        with self.assertRaises(ValueError):
            select_inquiry(tuple(candidate(str(i)) for i in range(33)), probe_budget=2)


if __name__ == "__main__":
    unittest.main()
