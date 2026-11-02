import csv
import json
from pathlib import Path
import unittest

import numpy as np

from initial_imperfection_material.tian_ma_qu.publish_insulators import interpolate_recorded, publish
from py_view.results_dashboard.server import DashboardData, TMQ_INSULATOR_ROOT

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"initial_imperfection_material/tian_ma_qu"/TMQ_INSULATOR_ROOT


def read_csv(path):
    with path.open() as stream:return list(csv.DictReader(stream))


class InsulatorComparisonContractTests(unittest.TestCase):
    def test_common_coverage_and_monotonicity_are_required(self):
        rows=[{"speed_m_s":0.,"x":0.},{"speed_m_s":20.,"x":2.}]
        self.assertEqual(interpolate_recorded(rows,10.,"x"),1.)
        for speed in (-1.,21.):
            with self.assertRaises(ValueError):interpolate_recorded(rows,speed,"x")
        with self.assertRaises(ValueError):interpolate_recorded(rows+rows,10.,"x")


@unittest.skipUnless((OUTPUT/"summary.json").exists(),"local insulator sensitivity evidence not installed")
class InsulatorSavedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary=json.loads((OUTPUT/"summary.json").read_text())

    def test_actual_completion_and_uncalibrated_scope_are_preserved(self):
        self.assertEqual(len(self.summary["cases"]),6)
        self.assertTrue(self.summary["all_cases_complete"])
        self.assertEqual(self.summary["physical_validation"],"unvalidated")
        self.assertFalse(self.summary["actual_geometry_and_string_type_confirmed"])
        for case in self.summary["cases"]:
            self.assertEqual(case["status"],"complete")
            self.assertEqual(case["returncode"],0)
            self.assertEqual(case["last"]["speed_m_s"],100.)
            self.assertEqual(case["accepted_steps"],130)

    def test_native_force_reconstruction_and_conductor_tension_every_step(self):
        for case in self.summary["cases"]:
            run=OUTPUT/"runs"/case["key"]
            rows=read_csv(run/"insulator_history.csv")
            self.assertEqual(len(rows),4*(case["accepted_steps"]+1))
            self.assertLess(max(abs(float(r["force_reconstruction_residual_N"])) for r in rows),1e-4)
            if case["variant"]=="tension_only":
                self.assertGreaterEqual(min(float(r["axial_force_N"]) for r in rows),-1e-8)
                self.assertTrue(any(r["state"]=="slack" for r in rows))
            self.assertTrue(all(float(r["axial_force_N"])>0 for r in read_csv(run/"line_history.csv")))
            equilibrium=[json.loads(line) for line in (run/"equilibrium.jsonl").read_text().splitlines()]
            self.assertEqual(len(equilibrium),case["accepted_steps"]+1)
            self.assertTrue(all(row["passed"] for row in equilibrium))

    def test_only_axial_assumption_changes_for_each_angle(self):
        for angle in (0,45):
            baseline=OUTPUT/"runs"/f"elastic_{angle}"
            reference=json.loads((baseline/"line_model/effective_configuration.json").read_text())
            for v in reference["insulators"].values():
                v["material"].pop("axial_behavior");v["material"].pop("compression_stiffness_ratio")
            loads=read_csv(baseline/"wind_nodal_loads.csv")
            base_legs=read_csv(baseline/"insulator_history.csv")[:4]
            for variant in ("tension_only","regularized"):
                run=OUTPUT/"runs"/f"{variant}_{angle}"
                actual=json.loads((run/"line_model/effective_configuration.json").read_text())
                for v in actual["insulators"].values():
                    v["material"].pop("axial_behavior");v["material"].pop("compression_stiffness_ratio")
                self.assertEqual(actual,reference)
                actual_loads=read_csv(run/"wind_nodal_loads.csv")
                self.assertEqual([r["node_tag"] for r in loads],[r["node_tag"] for r in actual_loads])
                for a,b in zip(loads,actual_loads):
                    np.testing.assert_allclose([float(a[k]) for k in a if k!="node_tag"],
                                               [float(b[k]) for k in b if k!="node_tag"],rtol=1e-12,atol=1e-8)
                np.testing.assert_allclose([float(r["axial_force_N"]) for r in base_legs],
                                          [float(r["axial_force_N"]) for r in read_csv(run/"insulator_history.csv")[:4]],atol=1e-6,rtol=1e-10)
        self.assertEqual(len({c["gravity_total_mass_kg"] for c in self.summary["cases"]}),1)

    def test_regularization_difference_is_reported_and_not_zeroed(self):
        rows=[c for c in self.summary["comparisons"] if c["candidate"]=="regularized" and c["relative_difference"] is not None]
        self.assertGreater(max(abs(c["relative_difference"]) for c in rows),1e-4)
        self.assertLess(max(abs(c["relative_difference"]) for c in rows),.01)
        for case in self.summary["cases"]:
            if case["variant"]=="regularized":self.assertLess(case["minimum_leg_force_N"],-1.)

    def test_source_snapshot_correction_is_explicit_and_does_not_change_effective_inputs(self):
        audit=json.loads((OUTPUT/"source_snapshot_correction.json").read_text())
        self.assertFalse(audit["numerical_results_modified"])
        self.assertFalse(audit["effective_configurations_modified"])
        source=json.loads((ROOT/"model/.config/tower_line_with_insulators.json").read_text())
        for row in audit["corrections"]:
            self.assertTrue((OUTPUT/row["original_snapshot_retained"]).exists())
            self.assertEqual(json.loads((OUTPUT/"runs"/row["case"]/"line_model/source_configuration.json").read_text()),source)

    def test_publication_is_protected_and_routes_expose_only_fixed_evidence(self):
        with self.assertRaises(FileExistsError):publish(OUTPUT)
        data=DashboardData(ROOT)
        result=data.tian_ma_qu()["insulator_sensitivity"]
        self.assertFalse(result["actual_geometry_and_string_type_confirmed"])
        for name in ("index.html","REPORT.md","summary.json","tower_comparison.svg","comparisons.csv"):
            self.assertTrue(data.tmq_file(f"{TMQ_INSULATOR_ROOT}/{name}").is_file())
        for name in ("insulator_experiment.py",f"{TMQ_INSULATOR_ROOT}/runs/unknown/history.csv",
                     f"{TMQ_INSULATOR_ROOT}/../../material.py"):
            self.assertIsNone(data.tmq_file(name))


if __name__=="__main__":unittest.main()
