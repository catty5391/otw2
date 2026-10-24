from pathlib import Path
import tempfile
import unittest

import numpy as np
import openseespy.opensees as ops

from initial_imperfection_material.member_reference_3d import (
    BoundaryPoint, build_member_reference, load_recorded_boundary, replay_boundary_history,
    subdivide_boundary_points,
    run_axial_boundary_case, run_pinned_2d_reference,
)
from model.mechanical_profile import MechanicalCatalog, beam_tangent, fiber_section_tangent, local_axes


class MemberReference3DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.catalog = MechanicalCatalog(Path(__file__).resolve().parents[1] / "Source/Z30103A6.s2k", output_dir=cls.directory.name)
        cls.member = cls.catalog.member(877)

    @classmethod
    def tearDownClass(cls):
        ops.wipe()
        cls.directory.cleanup()

    def points(self, end_i=None, end_j=None):
        return [BoundaryPoint("initial", 0, (0.0,) * 6, (0.0,) * 6),
                BoundaryPoint("test", 1, tuple(np.zeros(6) if end_i is None else end_i),
                              tuple(np.zeros(6) if end_j is None else end_j))]

    def test_linear_six_dof_boundary_replay_matches_coupled_analytic_beam(self):
        displacements = np.array([1e-7, -2e-7, 3e-7, 4e-7, -2e-7, 1e-7,
                                  -2e-7, 3e-7, -1e-7, -1e-7, 2e-7, 3e-7])
        result = replay_boundary_history(self.member, self.points(displacements[:6], displacements[6:]),
                                         elastic_steel=True, transformation="Linear")
        self.assertEqual(result["execution_status"], "completed")
        stiffness = fiber_section_tangent(self.member["fibers"], self.member["steel_tower"]["E0"],
                                          self.member["G"] * self.member["section"]["tors_const"])
        expected = beam_tangent(stiffness, self.member["coordinates"]) @ displacements
        np.testing.assert_allclose(result["states"][-1]["end_global_internal_force"], expected, rtol=1e-9, atol=1e-8)
        self.assertEqual(result["validation_status"], "unvalidated")

    def test_weak_small_cycle_returns_zero_for_pure_elastic_steel(self):
        axis = local_axes(self.member["coordinates"])[0]
        end = tuple(-axis * 1e-5) + (0.0, 0.0, 0.0)
        points = self.points(end_j=end)
        points.append(BoundaryPoint("unload", 1, (0.0,) * 6, (0.0,) * 6))
        vector = self.catalog.imperfection_vectors()[877]
        result = replay_boundary_history(self.member, points, elastic_steel=True, imperfection_vector=vector)
        self.assertEqual(result["completed_steps"], 2)
        self.assertLess(max(abs(value) for value in result["states"][-1]["end_global_internal_force"]), 1e-4)
        self.assertGreater(result["states"][1]["maximum_fiber_abs_stress"], 0)

    def test_rigid_translation_produces_no_force(self):
        shift = (1e-5, -2e-5, 3e-5, 0.0, 0.0, 0.0)
        result = replay_boundary_history(self.member, self.points(shift, shift), elastic_steel=True)
        self.assertEqual(result["execution_status"], "completed")
        self.assertLess(max(abs(value) for value in result["states"][-1]["end_global_internal_force"]), 1e-4)

    def test_refinement_preserves_defect_midpoint(self):
        vector = self.catalog.imperfection_vectors()[877]
        coarse = build_member_reference(self.member, divisions=4, imperfection_vector=vector)
        fine = build_member_reference(self.member, divisions=16, imperfection_vector=vector)
        np.testing.assert_allclose(coarse["coordinates"][2], fine["coordinates"][8], atol=1e-14)

    def test_unknown_missing_history_is_not_fabricated(self):
        with self.assertRaisesRegex(FileNotFoundError, "instrumented run"):
            load_recorded_boundary(Path(self.directory.name) / "not_recorded.jsonl", 877)

    def test_nonzero_initial_state_is_rejected(self):
        points = self.points()
        points[0] = BoundaryPoint("initial", 0, (1e-3,) + (0.0,) * 5, (0.0,) * 6)
        with self.assertRaisesRegex(ValueError, "zero"):
            replay_boundary_history(self.member, points)

    def test_nontransverse_imperfection_is_rejected(self):
        axis = local_axes(self.member["coordinates"])[0]
        with self.assertRaisesRegex(ValueError, "transverse"):
            build_member_reference(self.member, imperfection_vector=axis * 0.001)

    def test_finite_boundary_and_exact_geometry_validation(self):
        with self.assertRaises(ValueError):
            BoundaryPoint("test", 1, (float("nan"),) * 6, (0.0,) * 6)
        with self.assertRaises(ValueError):
            build_member_reference(self.member, exact_coordinates=[[0, 0, 0]] * 5)

    def test_explicit_boundary_substeps_preserve_original_points(self):
        points = self.points(end_j=(0, 0.001, 0, 0, 0, 0))
        dense = subdivide_boundary_points(points, 5)
        self.assertEqual(len(dense), 6)
        self.assertEqual(dense[-1].end_j, points[-1].end_j)
        self.assertAlmostEqual(dense[1].end_j[1], 0.0002)
        with self.assertRaises(ValueError):
            subdivide_boundary_points(points, 0)

    def test_steel02_rigid_translation_with_explicit_substeps_is_reversible(self):
        shift = (0.0, 0.0005, 0.0, 0.0, 0.0, 0.0)
        dense = subdivide_boundary_points(self.points(shift, shift), 10)
        result = replay_boundary_history(self.member, dense)
        self.assertEqual(result["completed_steps"], 10)
        self.assertLess(max(abs(value) for value in result["states"][-1]["end_global_internal_force"]), 1e-4)

    def test_explicit_3d_pinned_clamped_and_spring_boundaries(self):
        vector = self.catalog.imperfection_vectors()[877]
        values = [0, -1e-6, -2e-6, -1e-6, 0]
        results = {}
        for boundary, springs in (("pinned", None), ("clamped", None), ("rotational_springs", [1e3] * 4)):
            result = run_axial_boundary_case(self.member, values, boundary=boundary,
                imperfection_vector=vector, rotational_stiffnesses=springs, elastic_steel=True)
            self.assertEqual(result["execution_status"], "completed")
            self.assertLess(max(abs(value) for value in result["states"][-1]["end_global_internal_force"]), 1e-4)
            results[boundary] = result
        pinned_moments = np.array(results["pinned"]["states"][2]["end_global_internal_force"])[[4, 5, 10, 11]]
        self.assertLess(np.max(np.abs(pinned_moments)), 1e-7)
        self.assertGreater(abs(results["clamped"]["states"][2]["end_global_internal_force"][6]),
                           abs(results["pinned"]["states"][2]["end_global_internal_force"][6]))

    def test_legacy_2d_wrapper_runs_actual_member_with_explicit_profile(self):
        result = run_pinned_2d_reference(self.member, imperfection_ratio=0.001,
                                        maximum_shortening=1e-5, steps=4, divisions=4)
        self.assertTrue(result.converged)
        self.assertEqual(result.completed_steps, 4)
        self.assertFalse(result.solver_settings["relaxes_tolerance"])

    def test_compact_substeps_preserve_all_committed_forces_and_original_details(self):
        points = subdivide_boundary_points(self.points(end_j=(0, 1e-6, 0, 0, 0, 0)), 4)
        result = replay_boundary_history(self.member, points, elastic_steel=True, detail_stride=4)
        self.assertEqual(len(result["states"]), 5)
        self.assertIn("segment_summary", result["states"][1])
        self.assertIn("segments", result["states"][4])
        self.assertTrue(all("node_displacements" in row and "end_global_internal_force" in row for row in result["states"]))

    def test_removed_rigid_translation_preserves_deformation_and_restores_global_output(self):
        left = np.array([0.01, -0.02, 0.03, 1e-6, -1e-6, 2e-6])
        right = left + np.array([2e-6, -1e-6, 1e-6, -1e-6, 2e-6, 0])
        points = self.points(left, right)
        global_frame = replay_boundary_history(self.member, points, elastic_steel=True, transformation="Linear")
        moving_frame = replay_boundary_history(self.member, points, elastic_steel=True, transformation="Linear", remove_rigid_translation=True)
        np.testing.assert_allclose(global_frame["states"][-1]["end_global_internal_force"], moving_frame["states"][-1]["end_global_internal_force"], rtol=1e-8, atol=1e-7)
        np.testing.assert_allclose(moving_frame["states"][-1]["node_displacements"]["1"], left, atol=1e-14)
        np.testing.assert_allclose(moving_frame["states"][-1]["node_displacements"]["5"], right, atol=1e-14)
        self.assertAlmostEqual(global_frame["states"][-1]["chord_strain"], moving_frame["states"][-1]["chord_strain"], places=12)

    def test_arbitrarily_oriented_actual_member_keeps_axial_stiffness_after_frame_change(self):
        member = self.catalog.member(349)
        result = run_axial_boundary_case(member, [0, -1e-6], elastic_steel=True, boundary="pinned")
        expected = -member["steel_tower"]["E0"] * member["section"]["area"] * 1e-6 / member["length"]
        self.assertEqual(result["execution_status"], "completed")
        self.assertAlmostEqual(result["states"][-1]["end_global_internal_force"][6], expected, delta=abs(expected) * 1e-7)


if __name__ == "__main__":
    unittest.main()
