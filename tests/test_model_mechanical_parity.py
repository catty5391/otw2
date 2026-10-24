import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import openseespy.opensees as ops

from initial_imperfection_material.audit_mechanics import audit_member
from model.mechanical_profile import MechanicalCatalog, MechanicalProfile, Steel02Parameters, local_axes


class ModelMechanicalParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.catalog = MechanicalCatalog(Path(__file__).resolve().parents[1] / "Source/Z30103A6.s2k",
                                        output_dir=cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        ops.wipe()
        cls.directory.cleanup()

    def test_complete_steel_parameters_preserve_legacy_difference(self):
        member = self.catalog.member(877)
        self.assertEqual(member["steel_member"]["a1"], 0)
        self.assertEqual(member["steel_tower"]["a1"], 0.0005)
        self.assertEqual(set(member["steel_tower"]), {"E0", "fy", "b", "R0", "cR1", "cR2", "a1", "a2", "a3", "a4", "sig_init"})

    def test_aligned_profile_is_explicit_and_does_not_mutate_legacy(self):
        aligned = MechanicalProfile(name="aligned_v1")
        self.assertEqual(aligned.steel(family="member", E0=210e9, fy=235e6),
                         aligned.steel(family="tower", E0=210e9, fy=235e6))
        self.assertEqual(MechanicalProfile().steel(family="member", E0=210e9, fy=235e6).a1, 0)

    def test_nonfinite_and_invalid_parameters_rejected(self):
        for arguments in ({"E0": math.nan, "fy": 235e6}, {"E0": 210e9, "fy": -1},
                          {"E0": 210e9, "fy": 235e6, "a2": 0}):
            with self.assertRaises(ValueError):
                Steel02Parameters(**arguments)

    def test_actual_members_cover_three_grades(self):
        identifiers = self.catalog.representative_members()
        self.assertEqual(identifiers[:2], [877, 825])
        self.assertEqual({self.catalog.member(tag)["section"]["material_name"] for tag in identifiers}, {"Q235", "Q345", "Q420"})
        self.assertAlmostEqual(self.catalog.member(877)["length"], 0.85)

    def test_real_opensees_full_tangents_and_rigid_modes(self):
        for member_id in self.catalog.representative_members():
            with self.subTest(member_id=member_id):
                result = audit_member(self.catalog.member(member_id))
                self.assertTrue(result["elastic_implementation_passed"])
                self.assertLess(result["rigid_body_relative_residual"], 1e-12)
                for mode in result["unit_modes"].values():
                    self.assertLess(mode["scaled_reaction_relative_error"], 1e-6)

    def test_uncoupled_model_is_not_reported_as_section_equivalent(self):
        result = audit_member(self.catalog.member(877))
        self.assertGreater(result["uncoupled_bending_relative_difference"], 0.3)
        self.assertNotEqual(result["section_tangent_fiber"][1][2], 0.0)
        self.assertEqual(result["section_tangent_uncoupled"][1][2], 0.0)

    def test_rotated_principal_axis_elastic_prototype_recovers_global_coupling(self):
        for tag in self.catalog.representative_members():
            with self.subTest(member=tag):
                result = audit_member(self.catalog.member(tag))
                self.assertLess(result["principal_axes_global_beam_relative_error"], 1e-6)
                np.testing.assert_allclose(result["beam_tangent_principal_axes_prototype"],
                                           result["beam_tangent_fiber"], rtol=1e-10, atol=1e-6)

    def test_actual_axes_are_right_handed(self):
        for tag in self.catalog.representative_members():
            axes = local_axes(self.catalog.member(tag)["coordinates"])
            np.testing.assert_allclose(axes @ axes.T, np.eye(3), atol=1e-14)
            self.assertAlmostEqual(np.linalg.det(axes), 1.0)

    def test_persisted_directions_are_transverse_and_have_correct_peak(self):
        vectors = self.catalog.imperfection_vectors()
        self.assertEqual(len(vectors), 1528)
        for tag in (877, 825, 878, 828):
            member = self.catalog.member(tag)
            vector = np.array(vectors[tag])
            self.assertAlmostEqual(np.linalg.norm(vector), member["length"] * 0.001)
            self.assertAlmostEqual(np.dot(vector, local_axes(member["coordinates"])[0]), 0.0)
        self.assertEqual(vectors, self.catalog.imperfection_vectors())


if __name__ == "__main__":
    unittest.main()
