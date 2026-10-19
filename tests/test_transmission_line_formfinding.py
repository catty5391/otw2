import unittest

from model.transmission_line_formfinding import TransmissionLineFormFinder


class TransmissionLineFormFindingTests(unittest.TestCase):
    def test_solver_reaches_target_sag(self) -> None:
        finder = TransmissionLineFormFinder(
            horizontal_span=100.0,
            start_elevation=30.0,
            end_elevation=30.0,
            axial_stiffness=2.8e7,
            mass_per_length=1.5103,
            n_seg=20,
            initial_sag=3.0,
            load_steps=30,
        )

        result = finder.solve(
            target_sag=3.0,
            force_lower=20.0,
            force_upper=30000.0,
            tolerance=0.005,
            max_iterations=20,
        )

        self.assertLessEqual(abs(result.error), 0.005)
        self.assertGreater(result.initial_force, 0.0)
        self.assertEqual(len(result.axial_forces), 20)
        self.assertEqual(result.final_coords.shape, (21, 3))


if __name__ == "__main__":
    unittest.main()
