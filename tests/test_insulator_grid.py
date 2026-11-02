import copy
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.tian_ma_qu.insulator_grid_study import (
    BASELINE, DEFAULT_OUTPUT, collect_case, compare_histories, compare_value,
    freeze_plan, interpolate, publish, verify_inputs,
)


PLAN={"response_tolerance":{"relative":.02,"absolute_displacement_m":1e-4,"absolute_force_N":10.},
      "input_tolerance":{"relative_mass_and_resultant":1e-4,"absolute_force_N":.01,"absolute_moment_Nm":.1}}


class InsulatorGridContractTests(unittest.TestCase):
    def test_near_zero_uses_frozen_absolute_scale(self):
        self.assertTrue(compare_value(5e-5,0,absolute=1e-4)["passed"])
        self.assertFalse(compare_value(2e-4,0,absolute=1e-4)["passed"])
        result=compare_value(103.,100.,absolute=.1)
        self.assertFalse(result["passed"])
        self.assertAlmostEqual(result["normalized_error"],1.5)
        for value in (float("nan"),float("inf")):
            with self.assertRaises(ValueError):compare_value(value,1.)

    def test_interpolation_uses_load_factor_and_refuses_extrapolation(self):
        rows=[{"load_factor":0.,"x":0.},{"load_factor":4.,"x":8.}]
        self.assertEqual(interpolate(rows,1.,"x"),2.)
        for value in (-.1,4.1,float("nan")):
            with self.assertRaises(ValueError):interpolate(rows,value,"x")
        with self.assertRaises(ValueError):interpolate(rows+rows,1.,"x")

    def test_partial_common_range_and_failed_field_are_preserved(self):
        def rows(n,end,value):
            return [{"segments":n,"angle_deg":0,"load_factor":0.,"control_along_m":0.,"span1_maximum_N":100.},
                    {"segments":n,"angle_deg":0,"load_factor":end,"control_along_m":value,"span1_maximum_N":200.}]
        a,b=rows(40,4.,.5),rows(80,1.,.1)
        comparisons,summary=compare_histories(a,b,PLAN)
        self.assertEqual(summary["common_speed_range_m_s"],[0.,20.])
        self.assertTrue(all(r["load_factor"]<=1. for r in comparisons))
        self.assertFalse(summary["all_declared_outputs_passed"])
        self.assertIn("control_along_m",summary["failed_quantities"])
        self.assertGreater(summary["worst"]["normalized_error"],1.)

    def test_input_identity_cannot_hide_material_or_solver_changes(self):
        identity={k:"frozen" for k in ("configuration_without_mesh","effective_configuration_without_mesh",
                  "solver_settings","source_sha256","engine_version","code_sha256")}
        base={"identity":identity,"total_gravity_mass_kg":10.,"total_conductor_mass_kg":5.,
              "reference_wind_resultant":{"force_N":[1.,0.,0.],"moment_Nm":[0.,2.,0.]}}
        cases={(n,a):copy.deepcopy(base) for n in (20,40,80) for a in (0,45)}
        self.assertTrue(all(r["passed"] for r in verify_inputs(cases,PLAN)))
        cases[(80,0)]["identity"]["solver_settings"]="looser"
        with self.assertRaises(ValueError):verify_inputs(cases,PLAN)

    def test_frozen_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileExistsError):freeze_plan(Path(directory))
            (Path(directory)/"summary.json").write_text("{}")
            with self.assertRaises(FileExistsError):publish(Path(directory))


@unittest.skipUnless((BASELINE/"summary.json").exists(),"local 20-segment evidence unavailable")
class SavedBaselineExtractionTests(unittest.TestCase):
    def test_two_hangers_four_spans_and_key_members_have_full_coverage(self):
        result,rows=collect_case(BASELINE/"runs/tension_only_0",20,0)
        self.assertEqual(len(rows),131)
        self.assertTrue(result["all_equilibrium_checks_passed"])
        self.assertEqual(result["minimum_insulator_force_N"],0.)
        self.assertGreater(result["minimum_conductor_force_N"],0.)
        for i in (1,2):
            for axis in ("x","y","z"):
                self.assertEqual(rows[0][f"hanger{i}_u{axis}_m"],0.)
            self.assertAlmostEqual(rows[-1][f"hanger{i}_along_m"],rows[-1][f"hanger{i}_ux_m"])
        self.assertIn("member917_axial_i_N",rows[-1])
        self.assertEqual(len(result["physical_mapping"]["spans"]),4)


@unittest.skipUnless((DEFAULT_OUTPUT/"summary.json").exists(),"local 40/80 grid evidence unavailable")
class SavedGridStudyTests(unittest.TestCase):
    def test_assessment_preserves_every_declared_quantity_and_physical_limit(self):
        summary=json.loads((DEFAULT_OUTPUT/"summary.json").read_text())
        self.assertEqual(summary["new_FE_runs"],4)
        self.assertEqual(summary["physical_validation"],"unvalidated")
        self.assertFalse(summary["dynamic_convergence_established"])
        self.assertEqual(len(summary["cases"]),6)
        for case in summary["cases"]:
            self.assertGreaterEqual(case["minimum_insulator_force_N"],-1e-8)
            self.assertGreater(case["minimum_conductor_force_N"],0.)
            self.assertLess(case["native_force_reconstruction_error_N"],1e-4)
        for pair in summary["grid_comparisons"]:
            self.assertEqual(set(pair["failed_quantities"]),{k for k,v in pair["per_quantity"].items() if not v["passed"]})


if __name__=="__main__":unittest.main()
