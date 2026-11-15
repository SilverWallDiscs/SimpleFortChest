import unittest

from probability import (
    BASE_TOKEN_DENOMINATOR, chance_at_least_one, chests_for_chance,
    mixed_chance, per_chest_probability,
)


class ProbabilityTests(unittest.TestCase):
    def test_official_per_chest_rate(self):
        self.assertAlmostEqual(
            per_chest_probability(BASE_TOKEN_DENOMINATOR) * 100,
            0.0007272727,
            places=9,
        )

    def test_one_thousand_chests(self):
        self.assertAlmostEqual(chance_at_least_one(1000) * 100, 0.7246, places=3)

    def test_half_chance_threshold(self):
        self.assertEqual(chests_for_chance(0.5), 95_308)

    def test_ninety_percent_threshold(self):
        self.assertEqual(chests_for_chance(0.9), 316_605)

    def test_next_chest_does_not_depend_on_history(self):
        next_chest = per_chest_probability(BASE_TOKEN_DENOMINATOR)
        after_a_thousand = per_chest_probability(BASE_TOKEN_DENOMINATOR)
        self.assertEqual(next_chest, after_a_thousand)

    def test_mixed_modes(self):
        counts = {"normal": 1000, "boost_15": 100, "boost_2": 10}
        multipliers = {"normal": 1.0, "boost_15": 1.5, "boost_2": 2.0}
        result = mixed_chance(counts, multipliers)
        self.assertGreater(result, chance_at_least_one(1110))
        self.assertLess(result, 1.0)

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            chance_at_least_one(-1)
        with self.assertRaises(ValueError):
            chests_for_chance(1.0)


if __name__ == "__main__":
    unittest.main()
