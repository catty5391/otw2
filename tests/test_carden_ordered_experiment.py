import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from initial_imperfection_material.tian_ma_qu.carden_ordered_experiment import (
    path_points, turning_points, manifest_from_vector, NOMINAL_AREA, NOMINAL_LENGTH, X_MM_PER_PT, Y_N_PER_PT,
)
from initial_imperfection_material.tian_ma_qu.grouped_identification import admission_reasons, require_admitted, stage_residual, phase_mask
from initial_imperfection_material.tian_ma_qu.carden_angle_identification import published_features, fit_capacity
from py_view.results_dashboard.server import DashboardData, TMQ_CARDEN_ROOT
from tests.test_tmq_grouped_identification import fixture

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/"literature/tmq_ordered_history_20261026/raw"
OUTPUT = ROOT/"initial_imperfection_material/tian_ma_qu"/TMQ_CARDEN_ROOT


class CardenSourceContractTests(unittest.TestCase):
    def test_continuous_pdf_moves_preserve_duplicates_and_reversals(self):
        p = path_points("0 0 m -1 -2 l -1 -2 m 1 3 l 0 0 l")
        self.assertEqual([x[:2] for x in p], [(0.,0.),(-1.,-2.),(-1.,-2.),(1.,3.),(0.,0.)])
        for bad in ("0 0 m -1 -2 l 4 4 m 1 3 l", "0 0 m 1 2 3 4 5 6 c", "0 0 l 1 2 l 2 3 l"):
            with self.assertRaises(ValueError): path_points(bad)

    def test_turning_extraction_keeps_small_quantization_without_sorting(self):
        u = np.array([0.,-1.,-2.,-1.95,-3.,-2.,0.,2.,1.9,3.,2.,0.])
        before = u.copy()
        self.assertEqual(turning_points(u, -1, .5), [4,9])
        np.testing.assert_array_equal(u, before)

    def test_nominal_geometry_is_explicitly_conditional_and_never_waives_measured_E(self):
        _, m = fixture()
        m["verification"]["geometry"]["basis"] = "reported_nominal"
        m["conditions"] = ["nominal area, not a measured specimen"]
        self.assertTrue(admission_reasons(m))
        self.assertFalse(admission_reasons(m, evidence_policy="conditional_nominal_geometry"))
        m["verification"]["E"]["basis"] = "assumed_200GPa"
        self.assertTrue(admission_reasons(m, evidence_policy="conditional_nominal_geometry"))
        with self.assertRaises(ValueError): admission_reasons(m, evidence_policy="accept_anything")

    def test_future_observations_cannot_change_earlier_stage_response(self):
        p, m = fixture()
        d = require_admitted(m); mask = phase_mask(d, "first_compression")
        before = stage_residual(p, d, mask)
        future = {**d, "strain": d["strain"].copy()}
        future["strain"][~mask] = 1e100
        np.testing.assert_array_equal(stage_residual(p, future, mask), before)

    def test_nominal_inch_geometry_uses_original_dimensions_not_rounded_metric_table(self):
        self.assertAlmostEqual(NOMINAL_AREA*1e6, 219.25359375)
        self.assertAlmostEqual(NOMINAL_LENGTH*1000, 645.16)
        self.assertNotAlmostEqual(NOMINAL_LENGTH, .640)

    def test_first_compression_direction_does_not_override_reported_prior_tensile_yield(self):
        rows = {r["specimen_id"]: r for r in published_features()}
        for key in ("F", "G", "I"):
            self.assertEqual(rows[key]["first_cycle"], "compression")
            self.assertTrue(rows[key]["prior_tensile_yield_before_buckling"])
            with self.assertRaisesRegex(ValueError, "prior tensile"):
                fit_capacity(rows[key])
        self.assertFalse(rows["P"]["prior_tensile_yield_before_buckling"])

    def test_unknown_or_missing_publication_does_not_gain_physical_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            data = DashboardData(directory)
            self.assertIsNone(data.tian_ma_qu()["carden_conditional"])
            path = data.tmq_root/TMQ_CARDEN_ROOT/"summary.json"
            path.parent.mkdir(parents=True); path.write_text('{"schema":"unknown"}')
            with self.assertRaises(ValueError): data.tian_ma_qu()


@unittest.skipUnless((SOURCE/"carden_P_vector.json").exists(), "Downloaded source paths remain local")
class SavedCardenEvidenceTests(unittest.TestCase):
    def test_author_paths_match_first_direction_and_preserve_all_vertices(self):
        for key, count, sign in (("P",5397,-1),("Q",4192,1)):
            vector = json.loads((SOURCE/f"carden_{key}_vector.json").read_text())
            m = manifest_from_vector(vector)
            d = require_admitted(m, evidence_policy="conditional_nominal_geometry")
            self.assertEqual(len(d["sequence"]), count)
            xy = np.array([p[:2] for p in vector["vertices"]])
            np.testing.assert_allclose(d["displacement_m"], xy[:,0]*X_MM_PER_PT/1000, atol=1e-15)
            np.testing.assert_allclose(d["force_N"], xy[:,1]*Y_N_PER_PT)
            first_motion = next(x for x in d["displacement_m"] if x != 0)
            self.assertGreater(first_motion*sign, 0)
            self.assertTrue(admission_reasons(m))

    def test_source_peak_crosscheck_agrees_with_reported_kip_to_plot_precision(self):
        for key, peak_kip in (("P",12.),("Q",10.7)):
            m = manifest_from_vector(json.loads((SOURCE/f"carden_{key}_vector.json").read_text()))
            peak = -min(r["force"] for r in m["samples"])
            self.assertLess(abs(peak-peak_kip*4448.2216152605), m["force_resolution_N"])

    def test_published_failure_and_conditional_flags_remain_visible(self):
        summary = json.loads((OUTPUT/"summary.json").read_text())
        self.assertEqual(summary["status"], "nonidentifiable_stage")
        self.assertFalse(summary["physical_validation"])
        self.assertFalse(summary["strict_geometry_admitted"])
        self.assertFalse(summary["production_parameters_changed"])
        self.assertEqual(summary["stages"][-1]["sensitivity"]["local_rank"], 2)
        self.assertEqual(sum(r["complete_observed_points"] for r in summary["curve_metrics"]), 9589)
        self.assertGreater(summary["diagnostics"]["constant_later_peak_minimax_relative_error"], .16)
        self.assertEqual(summary["training"], "P"); self.assertEqual(summary["holdout"], "Q")
        self.assertAlmostEqual(summary["diagnostic_parameters"]["elastic_modulus"], 218e9)
        self.assertAlmostEqual(summary["diagnostic_parameters"]["yield_stress"], 338e6)
        plan = json.loads((OUTPUT/"rho_refinement/frozen_plan.json").read_text())
        self.assertEqual(plan["training"], "P")
        self.assertGreater(plan["force_threshold_N"], NOMINAL_AREA*338e6)
        self.assertEqual(summary["tension_refinement"]["observed_point_count"], 163)


if __name__ == "__main__": unittest.main()
