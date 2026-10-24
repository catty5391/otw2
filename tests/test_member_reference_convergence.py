import tempfile
import hashlib
import json
from pathlib import Path
import unittest

import numpy as np

from initial_imperfection_material.member_reference_convergence import (
    infer_half_sine_vector, matched_history_metrics, run_mesh_study,
    validate_reference_manifest, lightweight_original_states,
)
from initial_imperfection_material.member_reference_fiber_sensitivity import require_verified_legacy_case, load_original_points


class MemberReferenceConvergenceTests(unittest.TestCase):
    def test_recovers_same_transverse_peak_without_new_randomness(self):
        s = np.linspace(0, 1, 5)
        points = np.array([s, np.sin(np.pi * s) * 0.003, s * 0]).T
        np.testing.assert_allclose(infer_half_sine_vector(points), [0, 0.003, 0], atol=1e-15)

    def test_non_half_sine_geometry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "half-sine"):
            infer_half_sine_vector([[0, 0, 0], [1, 0.1, 0], [2, 0.2, 0], [3, 0, 0], [4, 0, 0]])

    def history(self):
        return [{"source_step": i, "stage_id": "cycle", "stage_progress": i / 3,
                 "chord_shortening_m": value / 10000,
                 "end_global_internal_force": [0] * 6 + [-value, 0, 0, 0, 0, 0]}
                for i, value in enumerate([0, 100, 50, 0])]

    def test_identical_cyclic_histories_preserve_reversal(self):
        result = matched_history_metrics(self.history(), self.history(), original_axis=[1, 0, 0])
        self.assertTrue(result["passed"])
        self.assertEqual(result["reference_peak_source_step"], 1)
        self.assertEqual(result["equal_stage_progress_weighted_nrmse"], 0)

    def test_partial_curve_and_stage_mismatch_cannot_pass(self):
        self.assertFalse(matched_history_metrics(self.history(), self.history()[:2], original_axis=[1, 0, 0])["passed"])
        wrong = self.history()
        wrong[2]["stage_id"] = "wrong"
        with self.assertRaises(ValueError):
            matched_history_metrics(self.history(), wrong, original_axis=[1, 0, 0])

    def test_rejects_missing_completed_source_manifest_before_running(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "manifest"):
                run_mesh_study(Path("Source/Z30103A6.s2k"), Path(directory) / "states.jsonl", Path(directory) / "out")

    def test_light_index_retains_original_point_mechanics_not_large_detail(self):
        states = self.history()
        for state in states:
            state.update({"maximum_fiber_abs_stress": 1, "maximum_fiber_abs_strain": 2, "segments": ["large detail"]})
        light = lightweight_original_states(states)
        self.assertNotIn("segments", light[0])
        self.assertEqual(light[1]["source_step"], 1)
        self.assertEqual(light[1]["end_global_internal_force"], states[1]["end_global_internal_force"])

    def test_fiber_refinement_requires_separate_completed_matching_gate(self):
        case = {"divisions": 16, "execution_status": "completed"}
        study = {"history_sha256": "h", "source_sha256": "s", "profile": {"long_edge_segments": 8, "short_edge_segments": 1},
            "members": [{"member_id": 877, "mesh_thresholds_passed": True, "stop_reason": None,
                         "cases": [{"divisions": 4, "matching_mesh_passed": True}, case]}]}
        self.assertIs(require_verified_legacy_case(study, member_id=877, divisions=16, history_sha256="h", source_sha256="s"), case)
        with self.assertRaisesRegex(ValueError, "identical"):
            require_verified_legacy_case(study, member_id=877, divisions=16, history_sha256="wrong", source_sha256="s")
        study["members"][0]["cases"][0]["matching_mesh_passed"] = False
        with self.assertRaisesRegex(ValueError, "Matching"):
            require_verified_legacy_case(study, member_id=877, divisions=16, history_sha256="h", source_sha256="s")

    def test_small_original_point_index_is_checked_against_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "points.json").write_text(json.dumps({"source_state_file": "states.json.gz", "states": self.history()}), encoding="utf-8")
            case = {"original_points_file": "points.json", "state_file": "states.json.gz"}
            self.assertEqual(load_original_points(root, case, 8), self.history())
            case["state_file"] = "wrong.json.gz"
            with self.assertRaisesRegex(ValueError, "different"):
                load_original_points(root, case, 8)

    def test_derived_prefix_checks_scope_hash_and_complete_six_stage_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            rows = [{"accepted_step": 0, "committed": True, "stage_id": "initial", "stage_progress": 0},
                    {"accepted_step": 1, "committed": True, "stage_id": "gravity", "stage_progress": 1}]
            stages = [f"target_{index}" for index in range(1, 7)]
            for stage in stages:
                for progress in (0, 1):
                    rows.append({"accepted_step": len(rows), "committed": True, "stage_id": stage, "stage_progress": progress})
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            path.with_suffix(".metadata.json").write_text("{}", encoding="utf-8")
            manifest = {"status": "completed", "artifact_type": "derived_committed_prefix",
                "scope": {"requested_target_count": 6, "completed_target_count": 6, "source_requested_target_count": 9,
                          "starts_from_unloaded": True, "includes_complete_gravity": True, "target_stage_ids": stages},
                "derivation": {"method": "committed_prefix_from_initial_not_restart", "source_run_id": "source_run",
                               "source_run_status_at_snapshot": "running", "last_included_accepted_step": len(rows) - 1,
                               "source_history_prefix_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "source_metadata_sha256": hashlib.sha256(path.with_suffix('.metadata.json').read_bytes()).hexdigest()}}
            result = validate_reference_manifest(manifest, path)
            self.assertFalse(result["parent_protocol_completed"])
            manifest["scope"]["completed_target_count"] = 5
            with self.assertRaises(ValueError):
                validate_reference_manifest(manifest, path)
            manifest["scope"]["completed_target_count"] = 6
            manifest["derivation"]["source_history_prefix_sha256"] = "wrong"
            with self.assertRaisesRegex(ValueError, "hash"):
                validate_reference_manifest(manifest, path)


if __name__ == "__main__":
    unittest.main()
