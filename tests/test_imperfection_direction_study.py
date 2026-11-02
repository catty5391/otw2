from pathlib import Path
import tempfile
import unittest

import numpy as np

from initial_imperfection_material.segmented_member_validation.direction_study import (
    build_case_matrix, principal_directions, read_comparison_history, section_orientation_roll,
)
from model.mechanical_profile import MechanicalCatalog, MechanicalProfile, local_axes


class ImperfectionDirectionStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.catalog = MechanicalCatalog(Path("Source/Z30103A6.s2k"), output_dir=Path(cls.tmp.name),
            profile=MechanicalProfile(name="aligned_v1", long_edge_segments=32, short_edge_segments=4))
        cls.member = cls.catalog.member(349)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_weak_bow_and_moment_axis_are_perpendicular_with_correct_inertia(self):
        result = principal_directions(self.member["fibers"])
        displacement = np.array(result["weak_displacement_yz"])
        moment = np.array(result["weak_bending_axis_yz"])
        self.assertAlmostEqual(float(displacement @ moment), 0., places=14)
        np.testing.assert_allclose(moment, [-displacement[1], displacement[0]], atol=1e-14)
        # Equal-angle legs extend along +y and +z: the weak bow lies on y=z.
        np.testing.assert_allclose(displacement, np.ones(2) / np.sqrt(2), atol=1e-12)
        inertia = np.array(result["physical_bending_inertia_yz_m4"])
        self.assertAlmostEqual(float(moment @ inertia @ moment) / result["weak_inertia_m4"], 1.)
        self.assertGreater(float(displacement @ inertia @ displacement), result["weak_inertia_m4"] * 2)

    def test_direction_mapping_preserves_seed_geometry_and_amplitude(self):
        cases = build_case_matrix(self.catalog, [349])
        self.assertEqual(len(cases), 9)
        axes = local_axes(self.member["coordinates"])
        old_vector = np.array(self.catalog.imperfection_vectors()[349])
        for row in cases:
            vector = np.array(row["imperfection_vector_global_m"])
            self.assertAlmostEqual(np.linalg.norm(vector), self.member["length"] * row["imperfection_ratio"], places=13)
            self.assertAlmostEqual(float(vector @ axes[0]), 0., places=13)
            if row["direction"] == "legacy_seed30103" and row["imperfection_ratio"] == .001:
                np.testing.assert_allclose(vector, old_vector, atol=1e-15)
        plus = next(row for row in cases if row["direction"] == "weak_plus" and row["imperfection_ratio"] == .001)
        minus = next(row for row in cases if row["direction"] == "weak_minus" and row["imperfection_ratio"] == .001)
        np.testing.assert_allclose(plus["imperfection_vector_global_m"], -np.array(minus["imperfection_vector_global_m"]), atol=1e-15)

    def test_selection_order_does_not_change_original_random_directions(self):
        a = build_case_matrix(self.catalog, [349, 920], ratios=[.001])
        b = build_case_matrix(self.catalog, [920, 349], ratios=[.001])
        av = {row["key"]: row["imperfection_vector_global_m"] for row in a}
        bv = {row["key"]: row["imperfection_vector_global_m"] for row in b}
        self.assertEqual(av, bv)

    def test_zero_bow_has_zero_reference_roll(self):
        result = section_orientation_roll(self.member, [0, 0, 0], 16)
        self.assertLess(result["maximum_absolute_roll_degrees"], 1e-10)

    def test_fiber_coordinate_origin_does_not_change_principal_direction(self):
        original = principal_directions(self.member["fibers"])
        shifted = principal_directions([dict(f, y=f["y"] + .8, z=f["z"] - .6) for f in self.member["fibers"]])
        np.testing.assert_allclose(original["weak_displacement_yz"], shifted["weak_displacement_yz"], atol=1e-12)
        self.assertAlmostEqual(original["weak_inertia_m4"] / shifted["weak_inertia_m4"], 1., places=12)

    def test_csv_requested_point_false_is_not_treated_as_true(self):
        path = Path(self.tmp.name) / "history.csv"
        path.write_text("target_index,requested_point,strain,force_N\n0,True,0,0\n1,False,-0.001,-1000\n1,True,-0.002,-1500\n", encoding="utf-8")
        rows = read_comparison_history(path)
        self.assertEqual([r["target_index"] for r in rows if r["requested_point"]], [0, 1])
        self.assertEqual([r["force_N"] for r in rows if r["requested_point"]], [0., -1500.])

    def test_invalid_defects_and_degenerate_principal_axes_are_rejected(self):
        with self.assertRaises(ValueError):
            build_case_matrix(self.catalog, [349], ratios=[-1e-3])
        with self.assertRaises(ValueError):
            section_orientation_roll(self.member, local_axes(self.member["coordinates"])[0], 16)
        with self.assertRaises(ValueError):
            principal_directions([{"y": 1, "z": 0, "area": 1}, {"y": -1, "z": 0, "area": 1},
                                  {"y": 0, "z": 1, "area": 1}, {"y": 0, "z": -1, "area": 1}])


if __name__ == "__main__":
    unittest.main()
