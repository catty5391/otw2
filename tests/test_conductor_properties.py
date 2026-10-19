import math
import unittest

from model.conductor_properties import resolve_conductor_mass, tributary_lengths


class ConductorMassPropertiesTests(unittest.TestCase):
    def test_catalog_mass_and_weight_for_one_subconductor(self) -> None:
        result = resolve_conductor_mass(
            {"conductor": {"model": "JL/G1A-400/50", "bundle_count": 1}},
            gravity=9.81,
        )

        self.assertAlmostEqual(result.subconductor_mass_per_length, 1.5103)
        self.assertAlmostEqual(result.mass_per_length, 1.5103)
        self.assertAlmostEqual(result.weight_per_length, 1.5103 * 9.81)
        self.assertAlmostEqual(result.diameter_m or 0.0, 0.0276)

    def test_bundle_count_scales_total_mass(self) -> None:
        result = resolve_conductor_mass(
            {"conductor": {"model": "JL/G1A-400/50", "bundle_count": 4}},
            gravity=9.81,
        )

        self.assertAlmostEqual(result.mass_per_length, 4.0 * 1.5103)
        self.assertAlmostEqual(result.weight_per_length, 4.0 * 1.5103 * 9.81)

    def test_legacy_weight_is_converted_to_mass(self) -> None:
        result = resolve_conductor_mass({"q_g": 15.0}, gravity=9.81)

        self.assertAlmostEqual(result.mass_per_length, 15.0 / 9.81)
        self.assertAlmostEqual(result.weight_per_length, 15.0)

    def test_conflicting_mass_and_legacy_weight_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不一致"):
            resolve_conductor_mass(
                {
                    "conductor": {"model": "JL/G1A-400/50"},
                    "q_g": 25.0,
                },
                gravity=9.81,
            )

    def test_tributary_lengths_follow_sagged_polyline(self) -> None:
        coords = [(0.0, 0.0, 0.0), (3.0, 0.0, -4.0), (6.0, 0.0, 0.0)]
        lengths = tributary_lengths(coords)

        self.assertEqual(lengths, [2.5, 5.0, 2.5])
        self.assertAlmostEqual(sum(lengths), 10.0)
        self.assertAlmostEqual(sum(lengths), sum(math.dist(a, b) for a, b in zip(coords, coords[1:])))


if __name__ == "__main__":
    unittest.main()
