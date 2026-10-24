"""Independent invariance and domain checks for read-only modal diagnostics."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from initial_imperfection_material.tian_ma_qu.modal_diagnostics import (
    analyze, common_node_indices, compare_subspaces, complete_cluster_window,
    frequency_clusters, interpolate_span_modes, projection_coverage,
    weighted_basis, weighted_mac_matrix,
)


class ModalGroupAlgebraTests(unittest.TestCase):
    def test_sign_permutation_and_group_rotation_leave_subspace_unchanged(self):
        rng = np.random.default_rng(673)
        a = rng.normal(size=(12, 3))
        w = np.r_[0., np.linspace(.2, 3, 11)]
        rotation, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        b = (a @ rotation)[:, [2, 0, 1]] * [-1, 1, -1]
        result = compare_subspaces(a, b, w)
        np.testing.assert_allclose(result["principal_cosines_squared"], 1, atol=1e-12)
        self.assertTrue(result["same_retained_rank"])
        self.assertLess(result["a_to_b_normalized_projection_residual"], 1e-7)
        self.assertAlmostEqual(result["a"]["weighted_trace"], result["b"]["weighted_trace"], places=12)

    def test_contained_different_rank_subspaces_are_not_declared_equal(self):
        a = np.eye(4)[:, :2]
        b = np.eye(4)[:, :3]
        result = compare_subspaces(a, b, np.ones(4))
        self.assertAlmostEqual(result["minimum_principal_cosine_squared"], 1)
        self.assertFalse(result["same_retained_rank"])
        self.assertEqual(result["unmatched_dimension_count"], 1)
        self.assertAlmostEqual(result["a_to_b_normalized_projection_residual"], 0)
        self.assertAlmostEqual(result["b_to_a_normalized_projection_residual"], np.sqrt(1 / 3))

    def test_rank_deficiency_is_reported_and_energy_selection_is_explicit(self):
        a = np.array([[1., 2., 0.], [0., 0., 1e-12], [0., 0., 0.]])
        _, info = weighted_basis(a, np.ones(3))
        self.assertEqual(info["numerical_rank"], 1)
        self.assertTrue(info["rank_deficient"])
        _, info = weighted_basis(np.diag([1., .01, .001]), np.ones(3), energy_retention=.999)
        self.assertEqual(info["numerical_rank"], 3)
        self.assertEqual(info["retained_rank"], 1)
        self.assertGreater(info["retained_trace_fraction"], .999)

    def test_known_reference_projection_and_mac(self):
        a = np.eye(3)[:, :2]
        ref = np.array([[1., 1.], [2., 0.], [0., 1.]])
        coverage, _ = projection_coverage(a, ref, np.array([2., 1., 2.]))
        np.testing.assert_allclose(coverage, [1., .5])
        mac = weighted_mac_matrix(ref[:, :1], np.column_stack([-3 * ref[:, 0], [1., -1., 0.]]), [2., 1., 2.])
        np.testing.assert_allclose(mac, [[1., 0.]], atol=1e-14)

    def test_invalid_mass_and_zero_vectors_are_rejected(self):
        for weights in ([0., 0.], [1., -1.], [1., float("nan")]):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                weighted_basis(np.eye(2), weights)
        with self.assertRaisesRegex(ValueError, "zero weighted"):
            weighted_basis(np.zeros((2, 1)), [1., 1.])
        with self.assertRaises(ValueError):
            weighted_basis(np.eye(2), [1., 1.], rank_tolerance=0)

    def test_node_mapping_uses_identity_not_order_and_rejects_missing(self):
        np.testing.assert_array_equal(common_node_indices([8, 2], [2, 99, 8]), [2, 0])
        with self.assertRaisesRegex(ValueError, "missing"):
            common_node_indices([8, 3], [2, 99, 8])
        with self.assertRaisesRegex(ValueError, "unique"):
            common_node_indices([8, 8], [8, 2])

    def test_window_includes_complete_edge_clusters(self):
        f = [1., 1.7995, 1.8001, 2.2, 2.6999, 2.7002, 3.]
        selected, info = complete_cluster_window(f, 1.8, 2.7)
        np.testing.assert_array_equal(selected, [1, 2, 3, 4, 5])
        self.assertEqual(info["added_edge_modes"], [2, 6])
        self.assertFalse(info["upper_spectrum_censored"])
        _, info = complete_cluster_window(f[:-1], 1.8, 2.7)
        self.assertTrue(info["upper_spectrum_censored"])
        with self.assertRaises(ValueError):
            frequency_clusters([1., .9])

    def test_linear_span_interpolation_is_exact_for_distinct_meshes(self):
        station = np.linspace(0, 1, 19)
        results = []
        for s in ([0., .2, 1.], [0., .1, .4, .8, 1.]):
            s = np.array(s)
            xyz = np.column_stack([s * 300, s * 0, s * 0])
            v = np.stack([np.column_stack([2 * s, -s, 3 * s + 1]),
                          np.column_stack([-s, s * 0 + 1, s * 0])])
            out, length = interpolate_span_modes(xyz, v, station)
            results.append(out)
            self.assertAlmostEqual(length, 300)
        np.testing.assert_allclose(results[0], results[1], atol=1e-14)

    def test_degenerate_span_and_invalid_stations_rejected(self):
        with self.assertRaises(ValueError):
            interpolate_span_modes(np.zeros((2, 3)), np.ones((1, 2, 3)), [0., 1.])
        with self.assertRaises(ValueError):
            interpolate_span_modes([[0, 0, 0], [1, 0, 0]], np.ones((1, 2, 3)), [.1, 1.])

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "existing"
            output.mkdir()
            (output / "keep.txt").write_text("original")
            with self.assertRaises(FileExistsError):
                analyze(Path(folder) / "missing_source", output)
            self.assertEqual((output / "keep.txt").read_text(), "original")


class ModalGroupSavedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1] / "initial_imperfection_material/tian_ma_qu/followup_results/B1_20261024/modal"
        cls.result = json.loads((cls.root / "summary.json").read_text())

    def test_saved_result_remains_limited_and_uses_original_float_data(self):
        s = self.result
        self.assertEqual(s["new_FE_runs"], 0)
        self.assertEqual(s["new_eigen_solves"], 0)
        self.assertEqual(s["physical_validation"], "unvalidated")
        self.assertEqual(s["common_tower_nodes"], 621)
        self.assertEqual(s["configuration"]["frequency_window_Hz"], [1.8, 2.7])
        for c in s["cases"].values():
            self.assertLess(c["eigen_equation_relative_residual_max"], 1e-6)
            self.assertLess(c["mass_orthogonality_error_max"], 1e-6)
            self.assertEqual(c["window"]["mode_count"], len(c["window"]["modes"]))
        for check in s["mesh_comparisons"]:
            self.assertFalse(check["forced_response_convergence_certified"])

    def test_provenance_and_public_artifacts_are_complete(self):
        for item in self.result["inputs"]:
            self.assertEqual(len(item["sha256"]), 64)
            self.assertGreater(item["size_bytes"], 0)
        for stem in ("tower_modal_group_distribution", "selected_vs_group_tower_participation", "low_frequency_cable_subspace"):
            for extension in ("svg", "png", "pdf"):
                self.assertGreater((self.root / f"{stem}.{extension}").stat().st_size, 100)
        for name in ("candidate_modes.csv", "modal_groups.csv", "subspace_checks.json", "REPORT.md"):
            self.assertTrue((self.root / name).is_file())


if __name__ == "__main__":
    unittest.main()
