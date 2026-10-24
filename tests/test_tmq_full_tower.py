"""Full-tower integration contracts; native ABI checks are explicitly opt-in."""
from copy import deepcopy
import csv
import gzip
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
import sqlite3

from initial_imperfection_material.tian_ma_qu.cases import literature_cases
from initial_imperfection_material.tian_ma_qu.material import TianMaQuPrototype
from initial_imperfection_material.tian_ma_qu.section_adapter import AxialSectionMaterial, CopyRegistry


class TMQSectionTests(unittest.TestCase):
    def setUp(self):
        self.p = literature_cases()[0].parameters

    def test_section_units_and_independent_copies(self):
        material = AxialSectionMaterial(self.p, .002)
        copy = material.get_copy()
        self.assertAlmostEqual(copy.get_initial_tangent(), .002*self.p.elastic_modulus)
        copy.set_trial_strain(.0001)
        copy.commit_state()
        self.assertAlmostEqual(copy.get_stress(), .002*self.p.elastic_modulus*.0001)
        self.assertEqual(material.get_stress(), 0)
        self.assertEqual(len(material.registry.committed()), 1)
        copy.set_trial_strain(-.01)
        copy.revert_to_last_commit()
        self.assertAlmostEqual(copy.get_strain(), .0001)

    def test_invalid_area_rejected(self):
        for area in (0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                AxialSectionMaterial(self.p, area)

    def test_fast_copy_matches_deepcopy_and_does_not_share_mutable_state(self):
        material = TianMaQuPrototype(self.p)
        for strain in (0, -.004, -.001, .004, .001, -.008, -.003):
            material.set_trial_strain(strain)
            material.commit_state()
        fast, slow = material.get_copy(), deepcopy(material)
        for strain in (.005, -.009, .001, -.004, -.002, .006, 0):
            for m in (fast, slow):
                m.set_trial_strain(strain)
                m.commit_state()
            self.assertEqual(fast.get_state(), slow.get_state())
        self.assertAlmostEqual(material.get_strain(), -.003)
        fast._committed.buckled_curves.add(999)
        self.assertNotIn(999, material._committed.buckled_curves)

    def test_existing_results_never_overwritten(self):
        from initial_imperfection_material.tian_ma_qu.full_tower import run
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/"keep.txt"
            p.write_text("unchanged")
            with self.assertRaises(FileExistsError):
                run(directory)
            self.assertEqual(p.read_text(), "unchanged")

    @unittest.skipUnless(os.environ.get("TMQ_TEST_NATIVE") == "1", "requires native ABI")
    def test_native_aggregator_force_and_three_copies_match_direct_material(self):
        import openseespy.opensees as ops
        from initial_imperfection_material.tian_ma_qu.opensees_adapter import register_model
        ops.wipe()
        try:
            ops.model("basic", "-ndm", 3, "-ndf", 6)
            ops.node(1, 0, 0, 0)
            ops.node(2, 3, 0, 0)
            ops.fix(1, 1, 1, 1, 1, 1, 1)
            ops.fix(2, 0, 1, 1, 1, 1, 1)
            registry = CopyRegistry()
            register_model(1, AxialSectionMaterial(self.p, .002, registry))
            ops.uniaxialMaterial("Elastic", 2, 1e5)
            ops.section("Aggregator", 1, 1, "P", 2, "My", 2, "Mz", 2, "T")
            ops.geomTransf("Corotational", 1, 0, 0, 1)
            ops.beamIntegration("Legendre", 1, 1, 3)
            ops.element("dispBeamColumn", 1, 1, 2, 1, 1)
            ops.timeSeries("Linear", 1)
            ops.pattern("Plain", 1, 1)
            ops.load(2, 1, 0, 0, 0, 0, 0)
            ops.constraints("Plain")
            ops.numberer("Plain")
            ops.system("BandGeneral")
            ops.test("NormUnbalance", 1e-5, 30)
            ops.algorithm("Newton")
            ops.integrator("DisplacementControl", 2, 1, .0001)
            ops.analysis("Static")
            direct = TianMaQuPrototype(self.p)
            for strain in (.0001, -.0001, 0, -.003, -.008, -.002, .004, -.006, .002, 0):
                delta = strain*3 - ops.nodeDisp(2, 1)
                ops.integrator("DisplacementControl", 2, 1, delta)
                self.assertEqual(ops.analyze(1), 0)
                direct.set_trial_strain(strain)
                direct.commit_state()
                self.assertAlmostEqual(ops.getLoadFactor(1), .002*direct.get_stress(), delta=.001)
                copies = registry.committed()
                self.assertEqual(len(copies), 3)
                for copy in copies:
                    self.assertAlmostEqual(copy.get_strain(), strain, delta=1e-12)
                    self.assertAlmostEqual(copy.get_stress(), .002*direct.get_stress(), delta=.001)
        finally:
            ops.wipe()


EVIDENCE = Path(__file__).resolve().parents[1]/"initial_imperfection_material/tian_ma_qu/tower_results"


@unittest.skipUnless((EVIDENCE/"publication.json").is_file(), "saved full-tower evidence not installed")
class TMQTowerEvidenceTests(unittest.TestCase):
    def test_actual_protocol_coverage_and_failed_extension_are_distinct(self):
        pub=json.loads((EVIDENCE/"publication.json").read_text())
        s=pub["run"]
        self.assertEqual(s["status"],"complete")
        self.assertEqual(s["completed_targets"],len(s["targets_drift"]))
        self.assertEqual(s["elements"],1528)
        self.assertEqual(s["accepted_steps"],409)
        self.assertEqual(s["max_buckled_members"],4)
        self.assertEqual(s["max_tensile_yield_members"],0)
        self.assertFalse(pub["validated_for_tower"])
        self.assertEqual(pub["extended_run"]["status"],"partial")
        self.assertEqual(pub["extended_run"]["stop_reason"],"minimum_increment")
        self.assertEqual(pub["extended_run"]["accepted_steps"],264)
        self.assertLess(pub["extended_run"]["completed_targets"],len(pub["extended_run"]["targets_drift"]))

    def test_elastic_control_and_every_saved_state_balance(self):
        pub=json.loads((EVIDENCE/"publication.json").read_text())
        self.assertTrue(pub["checks"]["elastic_control_complete"])
        self.assertLess(pub["checks"]["initial_stiffness_relative_error"],1e-6)
        self.assertLess(pub["checks"]["initial_frequency_max_relative_error"],1e-6)
        for name in ("tmq_bounded_03","tmq_cyclic_02","elastic_control_02"):
            s=json.loads((EVIDENCE/name/"summary.json").read_text())
            checks=[json.loads(r) for r in (EVIDENCE/name/"equilibrium.jsonl").read_text().splitlines()]
            self.assertEqual(len(checks),s["accepted_steps"]+1)
            self.assertTrue(all(c["passed"] for c in checks))

    def test_all_members_and_steps_have_material_and_twelve_force_records(self):
        run=EVIDENCE/"tmq_bounded_03"
        with sqlite3.connect(f"file:{run/'internal_forces.sqlite'}?mode=ro",uri=True) as db:
            self.assertEqual(db.execute("select count(*) from force_history").fetchone()[0],410*1528)
            self.assertEqual(db.execute("select count(distinct element_tag) from force_history").fetchone()[0],1528)
            self.assertEqual(db.execute("select min(time),max(time) from force_history").fetchone(),(0.,409.))
            self.assertEqual(db.execute("select count(*) from force_history where p_i is null or mz_j is null").fetchone()[0],0)
        count=0
        with gzip.open(run/"member_states.csv.gz","rt") as f:
            for row in csv.DictReader(f):
                count+=1
                self.assertEqual(row["active_copies"],"3")
        self.assertEqual(count,410*1528)

    def test_parameter_mapping_uses_real_tower_materials_and_positive_reductions(self):
        with (EVIDENCE/"tmq_bounded_03/model_data/tmq_member_parameters.csv").open() as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),1528)
        self.assertEqual({round(float(r["yield_stress"])/1e6) for r in rows},{235,345,420})
        self.assertTrue(all(0<float(r["phi"])<=1 for r in rows))
        self.assertTrue(all(float(r["elastic_modulus"])==210e9 for r in rows))
        for r in rows:
            self.assertAlmostEqual(float(r["perry_first_yield_N"]),float(r["phi"])*float(r["yield_stress"])*float(r["area_m2"]),delta=1e-5)


if __name__ == "__main__":
    unittest.main()
