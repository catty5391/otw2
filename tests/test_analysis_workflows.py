from __future__ import annotations

import csv
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import openseespy.opensees as ops

from util.analysis import AdaptiveStepper, AdvanceResult, RunManifest, cyclic_targets


class OpenSeesIntegrationTests(unittest.TestCase):
    def setUp(self):
        ops.wipe()

    def tearDown(self):
        ops.wipe()

    def spring(self, stiffness=200., mass=2., time_series="Constant"):
        ops.model("basic", "-ndm", 1, "-ndf", 1)
        ops.node(1, 0.)
        ops.node(2, 0.)
        ops.fix(1, 1)
        ops.mass(2, mass)
        ops.uniaxialMaterial("Elastic", 1, stiffness)
        ops.element("zeroLength", 1, 1, 2, "-mat", 1, "-dir", 1)
        ops.timeSeries(time_series, 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 1.)
        ops.system("BandGeneral")
        ops.constraints("Plain")
        ops.numberer("RCM")

    def test_static_reversal_spring_matches_force_displacement_law(self):
        self.spring(time_series="Linear")
        ops.integrator("DisplacementControl", 2, 1, .001)
        ops.test("NormDispIncr", 1e-10, 20)
        ops.algorithm("Newton")
        ops.analysis("Static")
        stepper = AdaptiveStepper(
            ops, progress=lambda: ops.nodeDisp(2, 1),
            configure_increment=lambda du: ops.integrator("DisplacementControl", 2, 1, du),
            convergence_test=("NormDispIncr", 1e-10, 20), minimum_increment=.0001,
        )
        for target in cyclic_targets([.01, .02]):
            self.assertTrue(stepper.advance_to(target, maximum_increment=.003).converged)
            self.assertAlmostEqual(ops.nodeDisp(2, 1), target, places=10)
            self.assertAlmostEqual(ops.getLoadFactor(1), 200 * target, places=8)

    def test_transient_spring_matches_constant_load_analytic_response(self):
        self.spring(stiffness=200., mass=2.)
        ops.integrator("Newmark", .5, .25)
        ops.test("NormDispIncr", 1e-12, 20)
        ops.algorithm("Newton")
        ops.analysis("Transient")
        # Consistent acceleration at t=0 for a suddenly applied unit force.
        ops.setNodeAccel(2, 1, .5, "-commit")
        stepper = AdaptiveStepper(ops, progress=ops.getTime, transient=True,
                                  convergence_test=("NormDispIncr", 1e-12, 20), minimum_increment=1e-5)
        self.assertTrue(stepper.advance_to(.1, maximum_increment=.001).converged)
        expected = (1 - math.cos(10 * .1)) / 200
        self.assertAlmostEqual(ops.nodeDisp(2, 1), expected, delta=5e-8)
        self.assertAlmostEqual(ops.getTime(), .1)

    def tiny_wind_model(self):
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.node(1, 0., 0., 0.)
        ops.node(370, 0., 0., 1.)
        ops.fix(1, 1, 1, 1, 1, 1, 1)
        ops.fix(370, 1, 0, 1, 1, 1, 1)
        ops.mass(370, 1., 1., 1., 0., 0., 0.)
        ops.geomTransf("Linear", 1, 0., 1., 0.)
        ops.element("elasticBeamColumn", 1, 1, 370, .01, 2e11, 8e10, 1e-4, 1e-4, 1e-4, 1)
        return SimpleNamespace(ops=ops, element_map={
            1: {"element_tag": 1, "node_i": 1, "node_j": 370, "component": "tower"}
        })

    def wind_files(self, root):
        sample = root / "input"
        sample.mkdir()
        (sample / "t.csv").write_text("0\n.01\n.02\n.03\n", encoding="utf-8")
        (sample / "floor0_wind_press.csv").write_text("0\n1\n2\n1\n", encoding="utf-8")
        config = root / "floors.json"
        config.write_text(json.dumps({"floor0": [1], "floor1": [370]}), encoding="utf-8")
        return sample, config

    def test_wind_entry_writes_manifest_and_every_successful_substep(self):
        from fluctuate_wind_simulate.opensees_simulate import wind_refactor_common as wind
        from util import TowerInternalForceHistory

        class SmallStepSolver(AdaptiveStepper):
            def advance_to(self, target, *, maximum_increment, on_step=None):
                return super().advance_to(target, maximum_increment=maximum_increment / 2, on_step=on_step)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample, config = self.wind_files(root)
            model = self.tiny_wind_model()
            with patch.object(wind, "RECORD_ROOT", root / "output"), \
                 patch.object(wind, "DRIFT_NODE_CONFIG", config), \
                 patch.object(wind, "AdaptiveStepper", SmallStepSolver):
                result = wind.run_one_sample(1, "10mps", "sample_01", sample, {"floor0": [370]}, model=model)
            output = root / "output" / "10mps" / "sample_01"
            manifest = json.loads((output / "run_manifest.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["completed_steps"], 3)
            history = TowerInternalForceHistory(result["internal_force_database"])
            times = history.recorded_times()
            self.assertEqual(len(times), 7)  # initial + 2 substeps per nominal interval
            self.assertAlmostEqual(times[-1], .03)
            with (output / "drift.csv").open() as file:
                self.assertEqual(len(list(csv.DictReader(file))), 6)

    def test_wind_failure_is_recorded_and_force_database_is_closed(self):
        from fluctuate_wind_simulate.opensees_simulate import wind_refactor_common as wind
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample, config = self.wind_files(root)
            model = self.tiny_wind_model()
            with patch.object(wind, "RECORD_ROOT", root / "output"), \
                 patch.object(wind, "DRIFT_NODE_CONFIG", config), \
                 patch.object(AdaptiveStepper, "advance_to", return_value=AdvanceResult(False, 0, .01, 0, 0)):
                with self.assertRaisesRegex(RuntimeError, "transient analyze failed"):
                    wind.run_one_sample(1, "10mps", "sample_01", sample, {"floor0": [370]}, model=model)
            output = root / "output" / "10mps" / "sample_01"
            manifest = json.loads((output / "run_manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertFalse((output / ".run.lock").exists())
            with sqlite3.connect(output / "tower_internal_forces.sqlite", timeout=.1) as connection:
                connection.execute("BEGIN EXCLUSIVE")
                connection.rollback()


class DownstreamStatusTests(unittest.TestCase):
    def test_fragility_extraction_excludes_failed_sample(self):
        from fluctuate_wind_simulate.fragility_curve.main import extract_input_from_opensees
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, valid, peak in (("sample_01", True, .01), ("sample_02", False, 999.)):
                output = root / "20mps" / name
                output.mkdir(parents=True)
                (output / "Node_displacement.out").write_text(f"0 0\n1 {peak}\n", encoding="utf-8")
                with RunManifest(output, parameters={}) as run:
                    run.finish(converged=valid)
            data = extract_input_from_opensees(root, root / "selected.csv", eligibility_mode="exploratory_legacy")
            self.assertEqual(len(data), 1)
            self.assertEqual(data.iloc[0]["sample"], "sample_01")
            self.assertEqual(data.iloc[0]["response"], .01)


if __name__ == "__main__":
    unittest.main()
