from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import openseespy.opensees as ops

from fluctuate_wind_simulate.opensees_simulate import wind_refactor_common as wind
from util import TowerInternalForceHistory
from util.preprocess.force_control import ForceControl
from util.analysis import AdaptiveStepper


class WindModelIsolationTests(unittest.TestCase):
    def setUp(self):
        ops.wipe()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.build_count = 0

    def tearDown(self):
        ops.wipe()
        self.temporary.cleanup()

    def spring_factory(self, plastic=True):
        # No wipe here: isolation belongs to the adapter, not this fixture.
        self.build_count += 1
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.node(1, 0., 0., 0.)
        ops.node(42, 1., 0., 0.)
        ops.fix(1, 1, 1, 1, 1, 1, 1)
        ops.fix(42, 1, 0, 1, 1, 1, 1)
        ops.mass(42, 0., 1., 0., 0., 0., 0.)
        if plastic:
            ops.uniaxialMaterial("Steel01", 1, .5, 1000., .02)
        else:
            ops.uniaxialMaterial("Elastic", 1, 1000.)
        ops.element("twoNodeLink", 1, 1, 42, "-mat", 1, "-dir", 2)
        return SimpleNamespace(ops=ops, element_map={1: {"element_tag":1,"node_i":1,"node_j":42,"component":"tower"}})

    def aggregator_factory(self):
        self.build_count += 1
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.node(1, 0., 0., 0.)
        ops.node(42, 0., 0., 1.)
        ops.fix(1, 1, 1, 1, 1, 1, 1)
        ops.fix(42, 1, 0, 1, 1, 1, 1)
        ops.mass(42, 0., 1., 0., 0., 0., 0.)
        ops.geomTransf("Linear", 1, 1., 0., 0.)
        for tag, stiffness in ((1, 1e6), (2, 100.), (3, 100.), (4, 100.)):
            ops.uniaxialMaterial("Elastic", tag, stiffness)
        ops.section("Aggregator", 1, 1, "P", 2, "Mz", 3, "My", 4, "T")
        ops.beamIntegration("Legendre", 1, 1, 2)
        ops.element("dispBeamColumn", 1, 1, 42, 1, 1)
        return SimpleNamespace(ops=ops, equivalent_materials={1: "test_only"},
                               element_map={1:{"element_tag":1,"node_i":1,"node_j":42,"component":"tower"}})

    def sample(self, name, amplitude=1., count=20):
        root = self.root / "input" / name
        root.mkdir(parents=True)
        (root / "t.csv").write_text("\n".join(str(i * .01) for i in range(count + 1)) + "\n")
        (root / "floor0_wind_press.csv").write_text("\n".join(str(0. if i == 0 else amplitude) for i in range(count + 1)) + "\n")
        return root

    def options(self, output):
        return dict(output_root=self.root/output, control_node=42, control_dof=2,
                    drift_enabled=False, model_declaration={"model_family":"test_nonlinear_spring"})

    def history(self, output, name):
        return [[float(value) for value in line.split()] for line in
                (self.root/output/"test"/name/"Node_displacement.out").read_text().splitlines()]

    def assert_same_history(self, left, right):
        self.assertEqual(len(left), len(right))
        self.assertGreater(len(left), 1)
        for a, b in zip(left, right):
            self.assertEqual(len(a), len(b))
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=12)

    def test_default_batch_rebuilds_a_then_b_and_b_then_a_independently(self):
        sample_a, sample_b = self.sample("A", 20.), self.sample("B", 2.)
        a, b = (1,"test","A",sample_a), (2,"test","B",sample_b)
        with patch.object(wind, "build_base_model", side_effect=self.spring_factory):
            wind.run_sample_batch([a,b], node_config={"floor0":[42]}, **self.options("AB"))
            wind.run_sample_batch([b], node_config={"floor0":[42]}, **self.options("B_only"))
            wind.run_sample_batch([b,a], node_config={"floor0":[42]}, **self.options("BA"))
            wind.run_sample_batch([a], node_config={"floor0":[42]}, **self.options("A_only"))
        self.assertEqual(self.build_count, 6)
        self.assert_same_history(self.history("AB","B"), self.history("B_only","B"))
        self.assert_same_history(self.history("BA","A"), self.history("A_only","A"))
        self.assertGreater(max(abs(row[1]) for row in self.history("AB","A")), .0005)

    def preload(self, model):
        ops.timeSeries("Linear", 7)
        ops.pattern("Plain", 7, 7)
        ops.load(42, 0., .4, 0., 0., 0., 0.)
        ops.constraints("Plain")
        ops.numberer("Plain")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1e-12, 20)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.)
        ops.analysis("Static")
        self.assertEqual(ops.analyze(1), 0)
        ops.loadConst()  # Retain domain time=1, and the committed preload.
        return {"gravity":"completed_test_preload_0.4N", "damping":{"type":"none","coefficient":0.},
                "mass":{"type":"nodal_diagonal","node42_y_kg":1.}, "initialization":"test_static_preload"}

    def test_factory_initialization_preserves_preload_and_nonzero_domain_time(self):
        sample = self.sample("preload", 0., count=3)
        with patch.object(ops, "reset", side_effect=AssertionError("reset would erase preload")):
            result = wind.run_one_sample(1,"test","preload",sample,{"floor0":[42]},
                model_factory=lambda:self.spring_factory(False),initialize_model=self.preload,**self.options("preload"))
        metadata = result["model_adapter"]
        self.assertEqual(metadata["transient_start_time"], 1.)
        self.assertAlmostEqual(metadata["initial_control_displacement"], .0004)
        self.assertEqual(metadata["gravity"], "completed_test_preload_0.4N")
        for row in self.history("preload","preload"):
            self.assertAlmostEqual(row[1], .0004, places=10)
        times = TowerInternalForceHistory(result["internal_force_database"]).recorded_times()
        self.assertEqual(len(times), 4)
        self.assertAlmostEqual(times[0], 1.)
        self.assertAlmostEqual(times[-1], 1.03)
        self.assertIn(7, ops.getPatterns())

    def test_external_legacy_model_keeps_committed_state_and_declares_unknown_isolation(self):
        model = self.spring_factory(False)
        self.preload(model)
        sample = self.sample("external", 0., count=3)
        result = wind.run_one_sample(1,"test","external",sample,{"floor0":[42]},model=model,
                                     **self.options("external"))
        self.assertAlmostEqual(result["model_adapter"]["initial_control_displacement"], .0004)
        self.assertEqual(result["model_adapter"]["domain_source"], "external_legacy_model")
        self.assertEqual(result["model_adapter"]["sample_isolation"], "caller_managed_unknown")
        self.assertEqual(result["model_adapter"]["gravity"], "unknown")

    def test_nonzero_start_time_shifts_wind_series_without_changing_response(self):
        sample = self.sample("offset", 1., count=3)
        wind.run_one_sample(1,"test","offset",sample,{"floor0":[42]},
                            model_factory=lambda:self.spring_factory(False),**self.options("offset_zero"))
        def start_later(model):
            ops.setTime(2.)
            return {"initialization":"zero-state clock-offset test","gravity":"none","damping":"none"}
        wind.run_one_sample(1,"test","offset",sample,{"floor0":[42]},
                            model_factory=lambda:self.spring_factory(False),initialize_model=start_later,
                            **self.options("offset_two"))
        zero, later = self.history("offset_zero","offset"), self.history("offset_two","offset")
        self.assertEqual(len(zero),len(later))
        for first,second in zip(zero,later):
            self.assertAlmostEqual(second[0]-first[0],2.)
            self.assertAlmostEqual(first[1],second[1],places=12)

    def test_aggregator_uses_generalized_section_responses_without_any_fiber_query(self):
        sample = self.sample("aggregator", .2, count=3)
        with patch.object(ops,"eleResponse",wraps=ops.eleResponse) as query:
            result = wind.run_one_sample(1,"test","aggregator",sample,{"floor0":[42]},
                model_factory=self.aggregator_factory,**self.options("aggregator"))
        self.assertFalse(any("fiber" in call.args for call in query.call_args_list))
        metadata = result["model_adapter"]
        self.assertIn("not_steel_fiber_strain", metadata["section_deformation_meaning"])
        self.assertEqual(metadata["section_response_capabilities"]["available_elements"], 1)
        rows = [json.loads(line) for line in (self.root/"aggregator"/"test"/"aggregator"/"section_responses.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows),4)
        self.assertTrue(rows[-1]["sections"][0]["generalized_force"])
        self.assertFalse((self.root/"aggregator"/"test"/"aggregator"/"Element_all_section_1.out").exists())

    def test_all_adaptive_successful_substeps_keep_actual_time(self):
        class HalfStepSolver(AdaptiveStepper):
            def advance_to(self,target,*,maximum_increment,on_step=None):
                return super().advance_to(target,maximum_increment=maximum_increment/2,on_step=on_step)
        sample = self.sample("adaptive", .2, count=3)
        with patch.object(wind,"AdaptiveStepper",HalfStepSolver):
            result=wind.run_one_sample(1,"test","adaptive",sample,{"floor0":[42]},
                model_factory=self.aggregator_factory,**self.options("adaptive"))
        times=TowerInternalForceHistory(result["internal_force_database"]).recorded_times()
        self.assertEqual(len(times),7)
        for actual,expected in zip(times,[0.,.005,.01,.015,.02,.025,.03]):
            self.assertAlmostEqual(actual,expected)
        rows=[json.loads(line) for line in (self.root/"adaptive"/"test"/"adaptive"/"section_responses.jsonl").read_text().splitlines()]
        self.assertEqual([row["time"] for row in rows],times)

    def test_invalid_control_threaded_reuse_and_aggregator_fiber_are_rejected(self):
        sample=self.sample("bad",.2,count=3)
        with self.assertRaisesRegex(ValueError,"does not exist"):
            wind.run_one_sample(1,"test","bad",sample,{"floor0":[42]},model_factory=self.spring_factory,
                                output_root=self.root/"bad",control_node=999,drift_enabled=False)
        with wind._own_domain():
            with self.assertRaisesRegex(RuntimeError,"cannot share"):
                wind.run_one_sample(1,"test","thread",sample,{"floor0":[42]},model_factory=self.spring_factory,
                                    **self.options("thread"))
        with self.assertRaisesRegex(ValueError,"Aggregator"):
            wind.run_one_sample(1,"test","fiber",sample,{"floor0":[42]},model_factory=self.aggregator_factory,
                                legacy_fiber_recording=True,**self.options("fiber"))
        self.assertFalse((self.root/"fiber"/"test"/"fiber"/".run.lock").exists())

    def test_partial_wind_creation_failure_removes_only_its_resources(self):
        self.spring_factory(False)
        sample = self.sample("load_failure", .2, count=3)
        ops.timeSeries("Constant",7)
        ops.pattern("Plain",7,7)
        with patch.object(ops,"load",side_effect=RuntimeError("injected load creation failure")):
            with self.assertRaisesRegex(RuntimeError,"injected"):
                wind.apply_wind_load_for_sample({"floor0":[42]},sample,ForceControl(10000,10000),"failure",.01)
        self.assertEqual(ops.getPatterns(),[7])
        # Reusing this tag succeeds only if the partially created Path was removed.
        ops.timeSeries("Constant",10000)


if __name__ == "__main__":
    unittest.main()
