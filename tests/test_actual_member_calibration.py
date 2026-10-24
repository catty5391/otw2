from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from initial_imperfection_material.calibrate_actual_members import (
    GATE_SCHEMA,REFERENCE_SCHEMA,TARGETS,calibrate_batch,reference_identity,
)
from initial_imperfection_material.calibration_cache import CalibrationCache,CacheWriteConflict
from initial_imperfection_material.config import AnalysisConfig,ReferenceSolverConfig,file_sha256,fingerprint


class ActualMemberCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.source=self.root/"synthetic_source.txt"
        self.source.write_text("Synthetic contract fixture, not an S2K model or physical G1 evidence.\n")
        self.source_hash=file_sha256(self.source)
        self.solver=ReferenceSolverConfig()
        self.profile={"name":"aligned_v1","long_edge_segments":32,"short_edge_segments":3,
            "integration_type":"Legendre","integration_points":6,"transformation":"Corotational",
            "element_type":"dispBeamColumn","imperfection_shape":"half_sine","imperfection_ratio":.001,
            "imperfection_seed":30103}
        steel={"E0":210e9,"fy":235e6,"b":.03,"R0":20.,"cR1":.925,"cR2":.15,
               "a1":.0005,"a2":.01,"a3":.0005,"a4":.01,"sig_init":0.}
        self.members={tag:{"member_id":tag,"length":length,"node_ids":[1,2],
            "coordinates":[[0.,0.,0.],[0.,0.,length]],"profile":self.profile,
            "section":{"section_name":section,"area":.000231,"i22":3.55e-8,"i33":3.55e-8,
                       "i23":2.13e-8,"tors_const":6e-10},"steel_tower":steel,"steel_member":steel}
                      for tag,(section,length) in TARGETS.items()}
        evidence=self.root/"synthetic_evidence.txt"
        evidence.write_text("Synthetic fixture only. No actual mesh, fiber or boundary validation was performed.\n")
        source_run=self.root/"source_run.json"
        source_run.write_text(json.dumps({"status":"completed","test_only":True,"source_sha256":self.source_hash}))
        self.evidence={"path":str(evidence),"sha256":file_sha256(evidence)}
        self.source_run={"path":str(source_run),"sha256":file_sha256(source_run)}
        self.gate={"schema":GATE_SCHEMA,"gate":"G1","status":"passed","source_sha256":self.source_hash,
            "mechanical_profile":self.profile,"test_only":True,
            "checks":{name:{"passed":True,"evidence":[self.evidence]} for name in
                      ("same_mesh_replay","mesh_convergence","step_convergence","fiber_convergence")},"groups":{}}
        self.references={}
        self.reference_data={}
        for tag in TARGETS:
            member=self.members[tag];length=member["length"]
            boundary={"type":"spatial_pinned","coordinate_frame":"original_member_local",
                      "description":"Synthetic explicit hinge boundary; test fixture, not tower evidence"}
            vector=[length*.001,0.,0.]
            curve=[]
            for step in range(31):
                strain=.03*step/30
                force=50000.*strain/.002 if strain<=.002 else 50000.*(1-.7*(strain-.002)/.028)
                curve.append({"shortening_m":strain*length,"compression_force_N":force,"committed":True})
            reference={"schema":REFERENCE_SCHEMA,"member_id":tag,"source_sha256":self.source_hash,
                "dimension":3,"boundary":boundary,"origin_convention":"zero_load_zero_end_shortening",
                "force_convention":"original_member_chord_compression_positive",
                "shortening_convention":"end_chord_shortening_positive",
                "steel":member["steel_tower"],"mechanical_profile":self.profile,"engine_version":"synthetic_test_only",
                "imperfection_vector":vector,"solver":self.solver.to_dict(),"requested_steps":30,"completed_steps":30,
                "execution_status":"completed","all_committed_states_included":True,
                "requested_end_shortening_m":.03*length,"actual_end_shortening_m":.03*length,"curve":curve,
                "configuration_fingerprint":reference_identity(member,source_sha256=self.source_hash,boundary=boundary,
                    imperfection_vector=vector,solver=self.solver,maximum_strain=.03)}
            path=self.root/f"reference_{tag}.json"
            self.references[tag]=path;self.reference_data[tag]=reference
            self.write_reference(tag)
        self.gate_path=self.root/"gate.json"
        self.write_gate()

    def tearDown(self):
        self.temporary.cleanup()

    def write_reference(self,tag):
        data=self.reference_data[tag]
        self.references[tag].write_text(json.dumps(data))
        self.gate["groups"][str(tag)]={"scope":{"member_id":tag,
            "steel_fingerprint":fingerprint(self.members[tag]["steel_tower"]),
            "boundary_fingerprint":fingerprint(data["boundary"]),
            "reference_configuration_fingerprint":data["configuration_fingerprint"],
            "reference_sha256":file_sha256(self.references[tag]),"source_run_sha256":self.source_run["sha256"],
            "loading":"zero_load_monotonic_compression","maximum_compression_strain":.03,
            "validation_kinds":["spatial_reference","mesh_step_fiber_verified","scalar_axial_identifiability"]},
            "source_run":self.source_run,"evidence":[self.evidence],
            "identifiability":{"status":"supported","independent_boundary_cases":2,
                               "maximum_conditional_force_spread_relative":.01}}

    def write_gate(self):
        self.gate_path.write_text(json.dumps(self.gate))

    def run_batch(self,name="result",**kwargs):
        self.write_gate()
        return calibrate_batch(self.source,self.gate_path,self.references,self.root/name,
                               member_records=self.members,make_plots=False,**kwargs)

    def test_full_synthetic_reference_publishes_legal_unvalidated_two_group_v2(self):
        with patch("initial_imperfection_material.material.EquivalentImperfectionMaterial.from_perry",
                   side_effect=AssertionError("Perry fallback must never run")):
            result=self.run_batch()
        self.assertEqual(result["status"],"calibrated_subset_unvalidated")
        config=AnalysisConfig(**json.loads((self.root/"result/config.json").read_text()))
        cache=CalibrationCache(self.root/"result/calibration_library.json").read(config)
        self.assertEqual(len(cache["groups"]),2)
        self.assertEqual(cache["validation_status"],"unvalidated")
        for record in result["groups"].values():
            self.assertEqual(record["independent_validation"]["status"],"not_performed")
            self.assertTrue(record["training_reconstruction"]["peak_sample_is_inserted"])
            self.assertLess(record["training_reconstruction"]["domain_weighted_nrmse_percent"],1e-10)

    def test_G1_pending_does_not_read_missing_reference_or_launch_catalog(self):
        self.gate["status"]="pending"
        self.references={tag:self.root/f"not_created_{tag}.json" for tag in TARGETS}
        result=self.run_batch()
        self.assertEqual(result["status"],"blocked")
        self.assertEqual(result["reason"],"G1_not_passed")
        self.assertFalse((self.root/"result/calibration_library.json").exists())
        self.assertFalse((self.root/"result/catalog").exists())

    def test_missing_fiber_evidence_blocks_even_if_gate_says_passed(self):
        del self.gate["checks"]["fiber_convergence"]
        result=self.run_batch()
        self.assertEqual(result["reason"],"G1_missing_fiber_convergence_evidence")
        self.assertNotIn("library",result)

    def test_boolean_alone_is_not_bound_identifiability_evidence(self):
        self.gate["groups"]["877"]={"scalar_axial_identifiable":True}
        result=self.run_batch()
        self.assertEqual(result["groups"]["877"]["reason"],"identifiability_scope_missing_or_mismatched")
        self.assertEqual(result["library"]["accepted_groups"],1)
        self.assertTrue(result["groups"]["877"]["recoverable_with_additional_evidence"])

    def test_source_run_hash_and_material_scope_are_required(self):
        self.gate["groups"]["877"]["scope"]["source_run_sha256"]="unrelated_run"
        self.gate["groups"]["825"]["scope"]["steel_fingerprint"]="different_material"
        result=self.run_batch()
        self.assertIn("source_run_hash",result["groups"]["877"]["reason"])
        self.assertIn("scope_missing",result["groups"]["825"]["reason"])
        self.assertFalse((self.root/"result/calibration_library.json").exists())

    def test_unidentifiable_boundary_stays_segmented_without_lifetime_ban(self):
        self.gate["groups"]["825"]["identifiability"]["status"]="not_evaluated"
        result=self.run_batch()
        row=result["groups"]["825"]
        self.assertEqual(row["status"],"unsupported")
        self.assertEqual(row["retained_representation"],"segmented")
        self.assertTrue(row["recoverable_with_additional_evidence"])

    def test_partial_reference_preserves_coverage_and_never_generates_full_backbone(self):
        data=self.reference_data[825]
        data.update(execution_status="not_converged",completed_steps=10,curve=data["curve"][:11],
                    actual_end_shortening_m=.01*self.members[825]["length"])
        self.write_reference(825)
        result=self.run_batch()
        row=result["groups"]["825"]
        self.assertEqual(row["status"],"partial_reference")
        self.assertAlmostEqual(row["coverage_percent"],100/3)
        cache=json.loads((self.root/"result/calibration_library.json").read_text())
        self.assertEqual(set(cache["groups"]),{"L40x3Q235|0.850000"})
        self.assertEqual(len((self.root/"result/reference_825.csv").read_text().splitlines()),12)

    def test_2D_or_prestressed_reference_is_unsupported_not_relabelled(self):
        self.reference_data[877]["dimension"]=2
        self.write_reference(877)
        self.reference_data[825]["origin_convention"]="gravity_preloaded"
        self.write_reference(825)
        result=self.run_batch()
        self.assertIn("spatial",result["groups"]["877"]["reason"])
        self.assertIn("prestressed",result["groups"]["825"]["reason"])
        self.assertNotIn("library",result)

    def test_missing_reference_is_recoverable_unsupported(self):
        self.references[825]=self.root/"not_exported_yet.json"
        result=self.run_batch()
        self.assertEqual(result["groups"]["825"]["reason"],"reference_input_not_available")

    def test_changed_evidence_hash_fails_and_never_falls_back(self):
        Path(self.evidence["path"]).write_text("changed after gate was frozen")
        with self.assertRaisesRegex(ValueError,"fingerprint mismatch"):
            self.run_batch()
        failure=json.loads((self.root/"result/failure.json").read_text())
        self.assertTrue(failure["no_silent_fallback"])
        self.assertFalse((self.root/"result/calibration_library.json").exists())

    def test_uniform_tolerance_and_no_automatic_5percent_extension(self):
        with self.assertRaisesRegex(ValueError,"same convergence tolerance"):
            self.run_batch(solver=ReferenceSolverConfig.legacy())
        with self.assertRaisesRegex(ValueError,"beyond 3%"):
            self.run_batch(maximum_strain=.05)
        with self.assertRaisesRegex(ValueError,"study justification"):
            self.run_batch(maximum_strain=.05,allow_range_extension=True)

    def test_incorrect_steel_or_missing_committed_rows_never_fit(self):
        self.reference_data[877]["steel"]={**self.reference_data[877]["steel"],"a1":0.}
        self.write_reference(877)
        self.reference_data[825]["curve"]=self.reference_data[825]["curve"][:-1]
        self.reference_data[825]["actual_end_shortening_m"]=self.reference_data[825]["curve"][-1]["shortening_m"]
        self.write_reference(825)
        result=self.run_batch()
        self.assertIn("material_profile",result["groups"]["877"]["reason"])
        self.assertIn("every_committed_state",result["groups"]["825"]["reason"])
        self.assertNotIn("library",result)

    def test_old_v1_cache_is_read_only_comparison_not_independent_validation(self):
        old=self.root/"old.json"
        first=self.run_batch("first")
        payload=json.loads((self.root/"first/calibration_library.json").read_text())
        payload["format"]="otw2.equivalent_imperfection_library.v1"
        for row in payload["groups"].values():
            row["source"]="old Perry trial, comparison only"
            for point in row["compression_envelope"]:
                point["stress"]*=.8
        old.write_text(json.dumps(payload))
        before=file_sha256(old)
        result=self.run_batch("new",old_cache=old)
        self.assertEqual(file_sha256(old),before)
        for row in result["groups"].values():
            self.assertEqual(row["old_comparison"]["status"],"compared")
            self.assertEqual(row["old_comparison"]["legacy_validation_status"],"legacy_unknown")
            self.assertEqual(row["independent_validation"]["status"],"not_performed")

    def test_output_cannot_overwrite_previous_evidence(self):
        self.run_batch()
        before=file_sha256(self.root/"result/summary.json")
        with self.assertRaises(CacheWriteConflict):
            self.run_batch()
        self.assertEqual(before,file_sha256(self.root/"result/summary.json"))

    def test_nonfinite_or_trial_reference_is_rejected(self):
        self.reference_data[877]["curve"][5]["committed"]=False
        self.write_reference(877)
        with self.assertRaisesRegex(ValueError,"committed states only"):
            self.run_batch()
        self.assertFalse((self.root/"result/calibration_library.json").exists())


if __name__=="__main__":
    unittest.main()
