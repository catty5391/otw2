"""Synthetic admission contracts, not material or damage-state validation."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from util.analysis.result_quality import MemberDomainRange, ResultQuality
from util.analysis.sample_admission import assess_sample, build_sample_flow, load_manifest_sample


class SampleAdmissionTests(unittest.TestCase):
    def manifest(self, state="not_reached", execution="completed"):
        quality = ResultQuality(purpose="formal_research")
        quality.add_evidence("synthetic", "fixture://test-only-not-physical-validation")
        quality.register_domain(MemberDomainRange(877, "strain", -0.03, 0.02, ("synthetic",)))
        quality.observe_member_state(877, "strain", 0.001, accepted_step=1, evidence_ids=["synthetic"])
        quality.finish_domain_audit(evidence_ids=["synthetic"])
        quality.set_validation("validated", scope=["synthetic_held_out_case"], evidence_ids=["synthetic"])
        quality.set_limit_state(state, criteria_id="synthetic-rule-v1", criteria_evidence_ids=["synthetic"], evidence_ids=["synthetic"])
        quality.set_coverage(10, 10)
        quality.set_execution(execution)
        return {"status": execution, "quality": quality.to_dict()}

    def sample(self, name="sample-1", speed=20, **kwargs):
        return {"sample_id": name, "wind_speed": speed, "manifest": self.manifest(**kwargs)}

    def test_formal_requires_normalized_quality_and_selected_criterion(self):
        row = assess_sample(self.sample(), criteria_id="synthetic-rule-v1")
        self.assertTrue(row["eligible_for_fragility"])
        self.assertEqual(row["physical_state_for_selected_criterion"], "not_reached")
        no_rule = assess_sample(self.sample())
        self.assertFalse(no_rule["eligible_for_fragility"])
        self.assertIn("criteria_not_selected", no_rule["reason_codes"])
        wrong_rule = assess_sample(self.sample(), criteria_id="other-rule")
        self.assertFalse(wrong_rule["eligible_for_fragility"])
        self.assertIn("criteria_mismatch_or_missing", wrong_rule["reason_codes"])

    def test_all_samples_and_overlapping_reasons_are_retained(self):
        samples = [self.sample("known-reached", state="reached"), self.sample("known-not-reached")]
        samples += [self.sample("nonconverged", execution="nonconverged"), self.sample("failed", execution="failed")]
        samples.append({"sample_id": "legacy", "wind_speed": 20, "manifest": {"status": "completed"}})
        out = self.sample("out-of-domain")
        out["manifest"]["quality"].update(domain_status="out_of_range", quality_flags=["out_of_calibration_range"])
        samples.append(out)
        result = build_sample_flow(samples, criteria_id="synthetic-rule-v1")
        counts = result["overall"]
        self.assertEqual(len(result["rows"]), 6)
        self.assertEqual(counts["input_records"], 6)
        self.assertEqual(counts["formal_admitted"], 2)
        self.assertEqual(counts["excluded"], 4)
        self.assertEqual(counts["reason_counts"]["legacy"], 1)
        self.assertEqual(counts["reason_counts"]["out_of_domain"], 1)
        self.assertEqual(counts["physical_state_unknown"], 4)
        self.assertEqual(counts["unclassified_failure_fraction_of_failures"], 1)
        self.assertEqual(counts["unclassified_failure_fraction_of_all_records"], 2 / 6)

    def test_count_bounds_do_not_assign_failed_outcomes_or_censoring(self):
        samples = [self.sample("event", state="reached"), self.sample("nonevent"), self.sample("failure", execution="failed")]
        result = build_sample_flow(samples, criteria_id="synthetic-rule-v1")
        bounds = result["overall"]["finite_cohort_event_fraction_bounds"]
        self.assertEqual(bounds["lower"], 1 / 3)
        self.assertEqual(bounds["upper"], 2 / 3)
        failed = result["rows"][2]
        self.assertEqual(failed["physical_state_for_selected_criterion"], "unknown")
        self.assertNotIn("censored", failed)
        self.assertNotIn("collapse", failed)

    def test_reported_event_on_incomplete_run_is_not_a_verified_formal_event(self):
        sample = self.sample(state="reached", execution="nonconverged")
        result = build_sample_flow([sample], criteria_id="synthetic-rule-v1")
        self.assertEqual(result["rows"][0]["reported_limit_state_status"], "reached")
        self.assertEqual(result["overall"]["known_reached"], 0)
        self.assertEqual(result["overall"]["physical_state_unknown"], 1)
        bounds = result["overall"]["finite_cohort_event_fraction_bounds"]
        self.assertEqual((bounds["lower"], bounds["upper"]), (0, 1))

    def test_legacy_exploration_is_explicit_and_cannot_become_formal(self):
        legacy = {"sample_id": "old", "wind_speed": 20, "manifest": None, "response": 0.001}
        formal = assess_sample(legacy, criteria_id="synthetic-rule-v1")
        exploratory = assess_sample(legacy, mode="exploratory_legacy", criteria_id="synthetic-rule-v1")
        self.assertFalse(formal["selected_for_analysis"])
        self.assertTrue(exploratory["selected_for_analysis"])
        self.assertFalse(exploratory["eligible_for_fragility"])
        self.assertEqual(exploratory["admission_status"], "exploratory_legacy_only")
        self.assertEqual(exploratory["physical_state_for_selected_criterion"], "unknown")

    def test_exploration_does_not_rescue_failed_or_invalid_responses(self):
        for status, response in (("failed", 1.0), ("completed", math.nan), ("completed", None), ("completed", True)):
            row = assess_sample({"sample_id": "legacy", "wind_speed": 20, "manifest": {"status": status}, "response": response}, mode="exploratory_legacy")
            self.assertFalse(row["selected_for_analysis"])
            self.assertFalse(row["eligible_for_fragility"])

    def test_speed_bins_keep_same_sample_names_at_different_speeds(self):
        samples = [self.sample("seed1", 10), self.sample("seed1", 20, state="reached"), self.sample("seed2", 20)]
        result = build_sample_flow(samples, criteria_id="synthetic-rule-v1")
        self.assertEqual([row["wind_speed_mps"] for row in result["by_wind_speed"]], [10.0, 20.0])
        self.assertEqual([row["input_records"] for row in result["by_wind_speed"]], [1, 2])
        self.assertEqual(result["overall"]["formal_admitted"], 3)
        self.assertEqual(result["by_wind_speed"][1]["finite_cohort_event_fraction_bounds"]["lower"], 0.5)

    def test_duplicate_identity_is_not_silently_deduplicated_or_counted_formally(self):
        samples = [self.sample(), self.sample()]
        result = build_sample_flow(samples, criteria_id="synthetic-rule-v1")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["overall"]["formal_admitted"], 0)
        self.assertEqual(result["overall"]["reason_counts"]["duplicate_sample_identity"], 2)
        self.assertFalse(result["overall"]["finite_cohort_event_fraction_bounds"]["available"])

    def test_invalid_metadata_is_retained_without_nonfinite_json(self):
        samples = [self.sample("", math.nan), self.sample("negative", -1)]
        result = build_sample_flow(samples, criteria_id="synthetic-rule-v1")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["overall"]["formal_admitted"], 0)
        self.assertFalse(result["overall"]["finite_cohort_event_fraction_bounds"]["available"])
        self.assertEqual(result["by_wind_speed"][0]["wind_speed_mps"], None)
        json.dumps(result, allow_nan=False)

    def test_direct_quality_input_is_normalized_and_forged_eligibility_rejected(self):
        quality = self.manifest()["quality"]
        row = assess_sample({"sample_id": "direct", "wind_speed": 20, "quality": quality}, criteria_id="synthetic-rule-v1")
        self.assertTrue(row["eligible_for_fragility"])
        quality["evidence"] = {}
        quality["eligible_for_fragility"] = True
        rejected = assess_sample({"sample_id": "forged", "wind_speed": 20, "quality": quality}, criteria_id="synthetic-rule-v1")
        self.assertFalse(rejected["eligible_for_fragility"])
        self.assertIn("legacy", rejected["reason_codes"])

    def test_budget_raises_instead_of_silently_truncating_and_input_not_mutated(self):
        samples = [self.sample("one"), self.sample("two")]
        before = copy.deepcopy(samples)
        with self.assertRaisesRegex(ValueError, "no truncated report"):
            build_sample_flow(samples, max_samples=1)
        self.assertEqual(samples, before)
        report = build_sample_flow(samples, criteria_id="synthetic-rule-v1", max_samples=2)
        self.assertEqual(report["overall"]["input_records"], 2)
        self.assertEqual(samples, before)

    def test_empty_cohort_and_missing_criteria_have_no_spurious_bounds(self):
        empty = build_sample_flow([])
        self.assertIsNone(empty["overall"]["unclassified_failure_fraction_of_all_records"])
        self.assertIsNone(empty["overall"]["finite_cohort_event_fraction_bounds"]["lower"])
        no_rule = build_sample_flow([self.sample()])
        self.assertEqual(no_rule["overall"]["finite_cohort_event_fraction_bounds"]["unavailable_reason"], "criteria_not_selected")
        for kwargs in ({"mode": "anything"}, {"criteria_id": ""}, {"max_samples": True}):
            with self.assertRaises(ValueError):
                build_sample_flow([], **kwargs)

    def test_missing_and_corrupt_manifest_files_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = load_manifest_sample("missing", 20, root / "missing.json", response=0.001)
            self.assertEqual(missing["input_errors"], ["manifest_missing"])
            self.assertEqual(assess_sample(missing, mode="exploratory_legacy")["admission_status"], "exploratory_legacy_only")
            path = root / "bad.json"
            path.write_text("not json", encoding="utf-8")
            bad = load_manifest_sample("corrupt", 20, path, response=0.001)
            self.assertEqual(bad["input_errors"], ["manifest_invalid_json"])
            self.assertFalse(assess_sample(bad, mode="exploratory_legacy")["selected_for_analysis"])
            path.write_text(json.dumps(self.manifest()), encoding="utf-8")
            valid = load_manifest_sample("valid", 20, path)
            self.assertTrue(assess_sample(valid, criteria_id="synthetic-rule-v1")["eligible_for_fragility"])
            oversized = load_manifest_sample("oversized", 20, path, maximum_bytes=10)
            self.assertEqual(oversized["input_errors"], ["manifest_exceeds_read_budget"])

    def test_ambiguous_manifest_and_quality_is_excluded(self):
        sample = self.sample()
        sample["quality"] = sample["manifest"]["quality"]
        row = assess_sample(sample, criteria_id="synthetic-rule-v1")
        self.assertFalse(row["eligible_for_fragility"])
        self.assertIn("ambiguous_manifest_and_quality", row["reason_codes"])

    def test_invalid_quality_is_not_downgraded_to_legacy_exploration(self):
        sample = self.sample()
        sample["response"] = 0.001
        sample["manifest"]["quality"]["schema"] = "future-unknown"
        row = assess_sample(sample, mode="exploratory_legacy")
        self.assertFalse(row["selected_for_analysis"])
        self.assertEqual(row["admission_status"], "excluded")


if __name__ == "__main__":
    unittest.main()
