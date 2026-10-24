"""Quality contracts only: passing these tests does not validate tower physics."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from util.analysis.result_quality import MemberDomainRange, ResultQuality, normalize_result_quality
from util.analysis.run_manifest import RunManifest


class ResultQualityTests(unittest.TestCase):
    def make_quality(self, purpose="diagnostic", policy="stop"):
        quality = ResultQuality(purpose=purpose, domain_policy=policy)
        for evidence_id in ("calibration", "history", "audit", "validation", "criteria", "assessment"):
            quality.add_evidence(evidence_id, f"fixture/{evidence_id}.json", "synthetic unit-test evidence, not tower validation")
        return quality

    def register(self, quality, member=877, lower=-0.03, upper=0.02, **kwargs):
        quality.register_domain(MemberDomainRange(member, "equivalent_strain", lower, upper, ("calibration",), **kwargs))

    def observe(self, quality, value, step=0, member=877, **kwargs):
        return quality.observe_member_state(member, "equivalent_strain", value, accepted_step=step,
                                            evidence_ids=["history"], **kwargs)

    def formal_quality(self):
        quality = self.make_quality("formal_research")
        self.register(quality)
        self.observe(quality, -0.001)
        quality.finish_domain_audit(evidence_ids=["audit"])
        quality.set_validation("validated", scope=["held_out_C6_in_declared_domain"], evidence_ids=["validation"])
        quality.set_limit_state("not_reached", criteria_id="frozen_physical_rule_v1",
                                criteria_evidence_ids=["criteria"], evidence_ids=["assessment"])
        quality.set_coverage(9, 9)
        quality.set_execution("completed")
        return quality

    def test_completed_does_not_grant_validation_or_eligibility(self):
        quality = self.make_quality()
        quality.set_execution("completed")
        quality.set_coverage(9, 9)
        result = quality.to_dict()
        self.assertEqual(result["validation_status"], "unvalidated")
        self.assertEqual(result["domain_status"], "unknown")
        self.assertEqual(result["limit_state_status"], "not_evaluated")
        self.assertFalse(result["eligible_for_fragility"])

    def test_fine_sparse_semantics_are_completed_failed_and_out_of_range(self):
        quality = self.make_quality(policy="diagnostic_continue")
        self.register(quality)
        quality.set_execution("completed")
        quality.set_coverage(9, 9)
        quality.set_validation("failed", scope=["critical_member_response"], evidence_ids=["validation"],
                               flags=["local_response_mismatch"])
        self.assertEqual(self.observe(quality, -0.04103, step=500), "diagnostic_continue")
        result = quality.to_dict()
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["validation_status"], "failed")
        self.assertEqual(result["domain_status"], "out_of_range")
        self.assertIn("local_response_mismatch", result["quality_flags"])
        self.assertIn("out_of_calibration_range", result["quality_flags"])
        self.assertFalse(result["eligible_for_fragility"])

    def test_actual_member_ranges_and_first_events(self):
        quality = self.make_quality(policy="diagnostic_continue")
        self.register(quality, 877, lower=-0.025)
        self.register(quality, 878, lower=-0.05)
        self.assertEqual(self.observe(quality, -0.03, step=4), "diagnostic_continue")
        self.assertEqual(self.observe(quality, -0.03, step=4, member=878), "continue")
        self.observe(quality, -0.04, step=5)
        first = quality.to_dict()["first_out_of_domain_by_member"]
        self.assertEqual(first["877"]["accepted_step"], 4)
        self.assertEqual(first["877"]["allowed_range"], [-0.025, 0.02])
        self.assertEqual(first["877"]["evidence_ids"], ["history"])
        self.assertNotIn("878", first)

    def test_trial_states_never_pollute_domain_events(self):
        quality = self.make_quality()
        self.register(quality)
        self.assertEqual(self.observe(quality, math.nan, committed=False), "ignored_trial")
        self.assertEqual(quality.to_dict()["events"], [])
        self.assertEqual(quality.to_dict()["domain_status"], "unknown")

    def test_first_event_is_earliest_step_across_member_order(self):
        quality = self.make_quality()
        self.register(quality, 877)
        self.register(quality, 878)
        self.observe(quality, -0.04, step=50, member=877)
        self.observe(quality, -0.04, step=10, member=878)
        self.assertEqual(quality.to_dict()["first_out_of_domain_event"]["accepted_step"], 10)

    def test_direction_boundary_and_missing_context_are_checked(self):
        quality = self.make_quality()
        self.register(quality, allowed_directions=("compression",), allowed_boundaries=("pinned",))
        self.assertEqual(self.observe(quality, -0.001), "stop")
        self.assertEqual(quality.to_dict()["domain_status"], "unknown")
        self.assertIn("unknown_domain_context", quality.to_dict()["quality_flags"])
        self.observe(quality, -0.002, step=1, direction="compression", boundary="tower_3d")
        self.assertEqual(quality.to_dict()["domain_status"], "out_of_range")

    def test_policies_return_actions_without_fabricating_execution_failure(self):
        for policy in ("stop", "fail", "diagnostic_continue"):
            quality = self.make_quality(policy=policy)
            self.register(quality)
            quality.set_execution("running")
            self.assertEqual(self.observe(quality, -0.04), policy)
            self.assertEqual(quality.to_dict()["execution_status"], "running")
            self.assertEqual(quality.to_dict()["limit_state_status"], "not_evaluated")

    def test_no_events_is_not_a_completed_domain_audit(self):
        quality = self.make_quality()
        self.register(quality)
        self.register(quality, 878)
        self.observe(quality, -0.001)
        quality.finish_domain_audit(evidence_ids=["audit"])
        self.assertEqual(quality.to_dict()["domain_status"], "unknown")
        self.assertIn("incomplete_domain_audit", quality.to_dict()["quality_flags"])

    def test_every_positive_assessment_requires_evidence(self):
        quality = self.make_quality()
        with self.assertRaises(ValueError):
            quality.set_validation("validated", scope=["C6"])
        with self.assertRaises(ValueError):
            quality.set_validation("validated", evidence_ids=["validation"])
        with self.assertRaises(ValueError):
            quality.set_limit_state("reached", criteria_id="rule", evidence_ids=["assessment"])
        with self.assertRaises(ValueError):
            quality.register_domain(MemberDomainRange(877, "strain", -0.03, 0.02, ("missing",)))
        with self.assertRaises(ValueError):
            quality.add_evidence("calibration", "different_source")

    def test_true_eligibility_requires_all_independent_gates(self):
        quality = self.formal_quality()
        self.assertTrue(quality.to_dict()["eligible_for_fragility"])
        quality.set_execution("nonconverged")
        self.assertFalse(quality.to_dict()["eligible_for_fragility"])
        self.assertEqual(quality.to_dict()["limit_state_status"], "not_reached")
        quality.set_execution("completed")
        quality.set_coverage(10, 9)
        self.assertFalse(quality.to_dict()["eligible_for_fragility"])

    def test_training_diagnostic_and_unknown_coverage_are_not_formal_samples(self):
        for purpose in ("training_fit", "diagnostic", "independent_validation"):
            data = self.formal_quality().to_dict()
            data["purpose"] = purpose
            self.assertFalse(normalize_result_quality({"status": "completed", "quality": data})["eligible_for_fragility"])
        quality = self.formal_quality()
        quality.set_coverage(None, 100)
        self.assertFalse(quality.to_dict()["eligible_for_fragility"])

    def test_nonfinite_values_invalid_enums_and_chronology_rejected(self):
        quality = self.make_quality()
        self.register(quality)
        for value in (math.inf, math.nan, True):
            with self.assertRaises(ValueError):
                self.observe(quality, value)
        for bounds in ((-math.inf, 1), (0, 0), (2, 1)):
            with self.assertRaises(ValueError):
                MemberDomainRange(1, "strain", *bounds, ("calibration",))
        self.observe(quality, 0, step=5)
        with self.assertRaises(ValueError):
            self.observe(quality, 0, step=4)
        with self.assertRaises(ValueError):
            quality.set_execution("collapse")
        with self.assertRaises(ValueError):
            quality.set_coverage(True, 0)

    def test_domain_bounds_are_inclusive_and_audit_is_final(self):
        quality = self.make_quality()
        self.register(quality)
        self.assertEqual(self.observe(quality, -0.03), "continue")
        self.assertEqual(self.observe(quality, 0.02, step=1), "continue")
        quality.finish_domain_audit(evidence_ids=["audit"])
        self.assertEqual(quality.to_dict()["domain_status"], "in_range")
        with self.assertRaises(ValueError):
            self.observe(quality, 0, step=2)

    def test_normalizer_quarantines_missing_unknown_malformed_and_forged_metadata(self):
        for manifest in (None, {}, {"status": []}, {"status": "completed"}, {"quality": {}}, {"quality": {"schema": "future.v9"}}):
            result = normalize_result_quality(manifest)
            self.assertEqual(result["validation_status"], "legacy_unknown")
            self.assertFalse(result["eligible_for_fragility"])
        valid = self.formal_quality().to_dict()
        for key, value in (("evidence", {}), ("validation_status", "maybe"), ("domain_audit_evidence_ids", []),
                           ("member_domains", {}), ("events", [{"kind": "unresolved"}]), ("quality_flags", ""),
                           ("validation_scope", [None])):
            data = copy.deepcopy(valid)
            data[key] = value
            result = normalize_result_quality({"status": "completed", "quality": data})
            self.assertFalse(result["eligible_for_fragility"], key)
        data = ResultQuality().to_dict()
        data["eligible_for_fragility"] = True
        self.assertFalse(normalize_result_quality({"quality": data})["eligible_for_fragility"])

    def test_normalizer_recomputes_eligibility_and_rejects_conflicting_status(self):
        data = self.formal_quality().to_dict()
        data["eligible_for_fragility"] = False
        self.assertTrue(normalize_result_quality({"status": "completed", "quality": data})["eligible_for_fragility"])
        self.assertFalse(normalize_result_quality({"status": "failed", "quality": data})["eligible_for_fragility"])
        data["evidence"].clear()
        self.assertTrue(self.formal_quality().to_dict()["evidence"])

    def test_manifest_default_and_explicit_quality_remain_backward_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with RunManifest(root / "default", parameters={}, expected_steps=2) as run:
                run.update(completed_steps=2)
            default = json.loads((root / "default/run_manifest.json").read_text())
            self.assertEqual(default["status"], "completed")
            self.assertEqual(default["execution_status"], "completed")
            self.assertEqual(default["validation_status"], "unvalidated")
            self.assertFalse(default["eligible_for_fragility"])
            quality = self.formal_quality()
            with RunManifest(root / "explicit", parameters={}, quality=quality, expected_steps=1) as run:
                run.update(completed_steps=1)
                self.assertFalse(json.loads(run.path.read_text())["eligible_for_fragility"])
            result = json.loads((root / "explicit/run_manifest.json").read_text())
            self.assertEqual(result["quality"]["coverage"]["unit"], "targets")
            self.assertTrue(result["eligible_for_fragility"])
            self.assertTrue(normalize_result_quality(result)["eligible_for_fragility"])

    def test_manifest_failure_is_not_collapse_and_set_quality_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "solver stopped"):
                with RunManifest(root, parameters={}) as run:
                    run.set_quality(self.make_quality())
                    raise RuntimeError("solver stopped")
            data = json.loads((root / "run_manifest.json").read_text())
            self.assertEqual(data["status"], "failed")
            self.assertEqual(data["execution_status"], "failed")
            self.assertEqual(data["limit_state_status"], "not_evaluated")
            self.assertEqual(data["quality"]["failure_reason"], "solver stopped")
            self.assertFalse(data["eligible_for_fragility"])
            with self.assertRaises(RuntimeError):
                run.set_quality(self.make_quality())


if __name__ == "__main__":
    unittest.main()
