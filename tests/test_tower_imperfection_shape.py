import math
import unittest

from model.tower_model_with_buckling import OpenSeesModelWithBuckling


class TowerImperfectionShapeTests(unittest.TestCase):
    def test_all_internal_nodes_follow_one_half_sine(self) -> None:
        model = object.__new__(OpenSeesModelWithBuckling)
        model.member_divisions = 8
        node_i = {"x": 0.0, "y": 0.0, "z": 0.0}
        node_j = {"x": 8.0, "y": 0.0, "z": 0.0}
        vector = (0.0, 0.08, 0.0)

        coordinates = [
            model._get_breakpoint_coord(node_i, node_j, station, vector)
            for station in range(1, 8)
        ]

        for station, (x, y, z) in enumerate(coordinates, start=1):
            self.assertAlmostEqual(x, float(station))
            self.assertAlmostEqual(y, 0.08 * math.sin(math.pi * station / 8.0))
            self.assertAlmostEqual(z, 0.0)
        self.assertAlmostEqual(coordinates[3][1], 0.08)
        self.assertAlmostEqual(coordinates[0][1], coordinates[-1][1])

    def test_two_segments_still_receive_midspan_imperfection(self) -> None:
        model = object.__new__(OpenSeesModelWithBuckling)
        model.member_divisions = 2
        node_i = {"x": 0.0, "y": 0.0, "z": 0.0}
        node_j = {"x": 2.0, "y": 0.0, "z": 0.0}
        self.assertEqual(
            model._get_breakpoint_coord(node_i, node_j, 1, (0.0, 0.02, 0.0)),
            (1.0, 0.02, 0.0),
        )


if __name__ == "__main__":
    unittest.main()
