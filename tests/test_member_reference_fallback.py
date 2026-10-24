from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import openseespy.opensees as ops

from initial_imperfection_material.member_reference_3d import BoundaryPoint, replay_boundary_history
from model.mechanical_profile import MechanicalCatalog, local_axes


class MemberReferenceFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.member = MechanicalCatalog(Path(__file__).resolve().parents[1] / "Source/Z30103A6.s2k", output_dir=cls.directory.name).member(877)
        cls.points = [BoundaryPoint("initial", 0, (0.0,) * 6, (0.0,) * 6),
            BoundaryPoint("test", 1, (0.0,) * 6, tuple(local_axes(cls.member["coordinates"])[0] * 1e-6) + (0.0,) * 3)]

    @classmethod
    def tearDownClass(cls):
        ops.wipe()
        cls.directory.cleanup()

    def test_default_is_newton_only_and_records_actual_attempt(self):
        result = replay_boundary_history(self.member, self.points, elastic_steel=True, transformation="Linear")
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["solver_algorithms"], ["Newton"])
        self.assertEqual([row["algorithm"] for row in result["attempts"]], ["Newton"])
        self.assertEqual(result["attempts"][0]["tolerance"], 1e-10)

    def test_real_forced_failure_then_fallback_matches_small_elastic_control(self):
        control = replay_boundary_history(self.member, self.points, elastic_steel=True, transformation="Linear")
        actual_analyze = ops.analyze
        calls = 0
        def force_first_real_failure(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                # Test-only stricter one-iteration condition; real OpenSees failure.
                ops.test("NormDispIncr", 1e-30, 1)
            return actual_analyze(*args)
        with patch("initial_imperfection_material.member_reference_3d.ops.analyze", side_effect=force_first_real_failure):
            result = replay_boundary_history(self.member, self.points, elastic_steel=True, transformation="Linear",
                algorithms=("Newton", "KrylovNewton", "NewtonLineSearch(0.8)"))
        self.assertEqual(result["execution_status"], "completed")
        self.assertNotEqual(result["attempts"][0]["return_code"], 0)
        self.assertTrue(result["attempts"][0]["failed_time_reverted"])
        self.assertEqual(result["attempts"][1]["algorithm"], "KrylovNewton")
        self.assertEqual(result["attempts"][1]["tolerance"], 1e-10)
        np.testing.assert_allclose(result["states"][-1]["end_global_internal_force"], control["states"][-1]["end_global_internal_force"], atol=1e-8)
        self.assertEqual(ops.getTime(), 1)

    def test_unknown_algorithm_and_failed_time_guard_stop_before_more_attempts(self):
        with self.assertRaisesRegex(ValueError, "algorithm"):
            replay_boundary_history(self.member, self.points, algorithms=("Unknown",))
        def failed_with_changed_time(*args):
            ops.setTime(0.5)
            return -3
        with patch("initial_imperfection_material.member_reference_3d.ops.analyze", side_effect=failed_with_changed_time):
            result = replay_boundary_history(self.member, self.points, elastic_steel=True,
                algorithms=("Newton", "KrylovNewton"))
        self.assertEqual(result["execution_status"], "not_converged")
        self.assertEqual(len(result["attempts"]), 1)
        self.assertFalse(result["attempts"][0]["failed_time_reverted"])
        self.assertEqual(result["completed_steps"], 0)


if __name__ == "__main__":
    unittest.main()
