from __future__ import annotations

import math
import unittest

from initial_imperfection_material.compare_runs import compare_protocol_histories, normalize_legacy_diagnostic_history


def row(stage, direction, progress, value, **extra):
    return {"stage_id": stage, "direction": direction, "stage_progress": progress,
            "base_shear": value, **extra}


class ProtocolComparisonTests(unittest.TestCase):
    def test_reversal_and_different_adaptive_step_counts_remain_separate(self):
        ref = [row("out", 1, 0., 0.), row("out", 1, 1., 10.),
               row("back", -1, 0., 10.), row("back", -1, 1., 2.)]
        cand = [row("out", 1, x, x * 10) for x in (0., .1, .3, .7, 1.)]
        cand += [row("back", -1, x, 10 - 8 * x) for x in (0., .2, 1.)]
        result = compare_protocol_histories(ref, cand)
        self.assertEqual(result["status"], "compared")
        self.assertAlmostEqual(result["metrics"]["base_shear"]["rmse"], 0.)
        self.assertEqual(result["reference_protocol_coverage_percent"], 100.)

    def test_stage_and_direction_are_both_keys(self):
        result = compare_protocol_histories([row("a", 1, 0., 0.), row("a", 1, 1., 1.)],
                                            [row("a", -1, 0., 0.), row("a", -1, 1., 1.)])
        self.assertEqual(result["status"], "no_common_coverage")
        self.assertEqual(result["common_progress"], 0.)
        self.assertEqual(len(result["stages"]), 2)

    def test_partial_stage_has_no_extrapolation(self):
        result = compare_protocol_histories([row("a", 1, 0., 0.), row("a", 1, 1., 2.)],
                                            [row("a", 1, .2, .4), row("a", 1, .6, 1.2)])
        self.assertAlmostEqual(result["common_progress"], .4)
        self.assertAlmostEqual(result["reference_protocol_coverage_percent"], 40.)
        self.assertAlmostEqual(result["metrics"]["base_shear"]["rmse"], 0.)

    def test_exact_rmse_is_independent_of_sampling(self):
        ref = [row("a", 1, 0., 0.), row("a", 1, 1., 0.)]
        coarse = [row("a", 1, 0., 0.), row("a", 1, 1., 1.)]
        dense = [row("a", 1, x, x) for x in (0., .001, .4, .99, 1.)]
        a, b = compare_protocol_histories(ref, coarse), compare_protocol_histories(ref, dense)
        self.assertAlmostEqual(a["metrics"]["base_shear"]["rmse"], math.sqrt(1 / 3))
        self.assertAlmostEqual(a["metrics"]["base_shear"]["rmse"], b["metrics"]["base_shear"]["rmse"])
        self.assertIsNone(a["metrics"]["base_shear"]["nrmse_percent"])

    def test_jumps_are_recorded_and_no_interpolation_crosses_them(self):
        ref = [row("a", 1, 0., 0.), row("a", 1, .4, 4.), row("a", 1, .6, 20., jump_before=True),
               row("a", 1, 1., 24.)]
        result = compare_protocol_histories(ref, ref)
        self.assertAlmostEqual(result["common_progress"], .8)
        self.assertAlmostEqual(result["metrics"]["base_shear"]["rmse"], 0.)
        jump = result["stages"][0]["reference_jumps"][0]
        self.assertEqual(jump["increments"]["base_shear"], 16.)
        self.assertEqual([jump["progress_before"], jump["progress_after"]], [.4, .6])

    def test_repeated_progress_jump_has_separate_before_and_after(self):
        ref = [row("a", 1, 0., 0.), row("a", 1, .5, 1.), row("a", 1, .5, 10.), row("a", 1, 1., 11.)]
        result = compare_protocol_histories(ref, ref)
        self.assertEqual(len(result["stages"][0]["reference_jumps"]), 1)
        self.assertAlmostEqual(result["common_progress"], 1.)
        self.assertAlmostEqual(result["metrics"]["base_shear"]["rmse"], 0.)

    def test_stationary_and_no_common_histories_are_explicit(self):
        result = compare_protocol_histories([row("zero", 0, 0., 1.)], [row("zero", 0, 0., 2.)])
        self.assertEqual(result["stages"][0]["status"], "point_only")
        self.assertEqual(result["status"], "no_common_coverage")
        self.assertEqual(result["stages"][0]["metrics"]["base_shear"]["maximum_absolute_error"], 1.)
        self.assertEqual(compare_protocol_histories([], [])["reference_protocol_coverage_percent"], 0.)

    def test_failed_rows_and_invalid_progress(self):
        ref = [row("a", 1, 0., 0., accepted="1"), row("a", 1, .5, 999., state="trial"),
               row("a", 1, .6, 888., committed=False), row("a", 1, 1., 1.)]
        result = compare_protocol_histories(ref, [ref[0], ref[-1]])
        self.assertEqual(result["excluded_reference_trial_rows"], 2)
        self.assertAlmostEqual(result["metrics"]["base_shear"]["rmse"], 0.)
        with self.assertRaisesRegex(ValueError, "progress reverses"):
            compare_protocol_histories([row("a", 1, 1., 0.), row("a", 1, 0., 0.)], [])

    def test_declared_protocol_keeps_missing_later_stages_in_coverage(self):
        points = [row("1", 1, 0., 0.), row("1", 1, 1., 2.)]
        result = compare_protocol_histories(points, points, protocol_stages=[("1", 1), ("2", -1)])
        self.assertEqual(result["reference_protocol_coverage_percent"], 50.)
        self.assertEqual(result["stages"][1]["reason"], "stage_missing_in_both")

    def test_legacy_adapter_requires_targets_and_preserves_stage_start(self):
        source = [{"stage": 0, "u_m": 0., "base_shear_N": 0.},
                  {"stage": 1, "u_m": .5, "base_shear_N": 1.},
                  {"stage": 1, "u_m": 1., "base_shear_N": 2.},
                  {"stage": 2, "u_m": 0., "base_shear_N": 3.}]
        values = normalize_legacy_diagnostic_history(source, [1., -1.])
        self.assertEqual(len(values), 5)
        self.assertEqual(values[3]["base_shear"], 2.)
        self.assertEqual(values[3]["stage_progress"], 0.)
        self.assertEqual(values[-1]["stage_progress"], .5)
        self.assertEqual(values[-1]["direction"], -1)
        with self.assertRaisesRegex(ValueError, "stage 0"):
            normalize_legacy_diagnostic_history(source[1:], [1., -1.])


if __name__ == "__main__":
    unittest.main()
