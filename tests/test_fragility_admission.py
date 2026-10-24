"""Real extractor admission and audit integration; fixtures are not physics proof."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fluctuate_wind_simulate.fragility_curve.main import extract_input_from_opensees, main
from util.analysis.result_quality import MemberDomainRange, ResultQuality


class FragilityAdmissionTests(unittest.TestCase):
    criteria = "synthetic-frozen-rule"

    def manifest(self, state="not_reached", execution="completed"):
        quality = ResultQuality(purpose="formal_research")
        quality.add_evidence("fixture", "fixture://synthetic-not-physical-evidence")
        quality.register_domain(MemberDomainRange(877, "strain", -0.03, 0.02, ("fixture",)))
        quality.observe_member_state(877, "strain", 0.001, accepted_step=1, evidence_ids=["fixture"])
        quality.finish_domain_audit(evidence_ids=["fixture"])
        quality.set_validation("validated", scope=["synthetic_case"], evidence_ids=["fixture"])
        quality.set_limit_state(state, criteria_id=self.criteria, criteria_evidence_ids=["fixture"], evidence_ids=["fixture"])
        quality.set_coverage(10, 10)
        quality.set_execution(execution)
        return {"status": execution, "quality": quality.to_dict()}

    def sample(self, root, name, manifest=None, response="0 0\n1 .01\n", speed="20mps"):
        directory = root / speed / name
        directory.mkdir(parents=True, exist_ok=True)
        if manifest is not None:
            (directory / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if response is not None:
            (directory / "Node_displacement.out").write_text(response, encoding="utf-8")
        return directory

    def audit(self, root, filename="selected"):
        return json.loads((root / f"{filename}.admission.json").read_text())

    def test_formal_rejects_legacy_unvalidated_and_out_of_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "legacy", {"status": "completed"})
            quality = ResultQuality()
            quality.set_execution("completed")
            self.sample(root, "unvalidated", {"status": "completed", "quality": quality.to_dict()})
            out = self.manifest()
            out["quality"].update(domain_status="out_of_range", quality_flags=["out_of_calibration_range"])
            self.sample(root, "out", out)
            with self.assertRaisesRegex(RuntimeError, "全部3条样本流转"):
                extract_input_from_opensees(root, root / "selected.csv", criteria_id=self.criteria)
            audit = self.audit(root)
            self.assertEqual(audit["overall"]["input_records"], 3)
            self.assertEqual(audit["overall"]["formal_admitted"], 0)
            self.assertEqual(audit["overall"]["reason_counts"]["out_of_domain"], 1)
            self.assertEqual(audit["overall"]["reason_counts"]["legacy"], 1)
            self.assertFalse((root / "selected.csv").exists())

    def test_explicit_false_physical_event_is_retained_not_filtered_by_truthiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "a_non_event", self.manifest("not_reached"))
            self.sample(root, "b_event", self.manifest("reached"))
            result = extract_input_from_opensees(root, root / "selected.csv", criteria_id=self.criteria)
            self.assertEqual(result["limit_state_reached"].tolist(), [False, True])
            self.assertTrue(result["eligible_for_fragility"].all())
            self.assertEqual(self.audit(root)["overall"]["known_not_reached"], 1)
            self.assertEqual(self.audit(root)["overall"]["known_reached"], 1)

    def test_default_formal_requires_criterion_and_does_not_reuse_stale_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "valid", self.manifest())
            destination = root / "selected.csv"
            destination.write_text("previous output must not be used", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "缺少已冻结的criteria_id"):
                extract_input_from_opensees(root, destination)
            self.assertEqual(destination.read_text(), "previous output must not be used")
            self.assertEqual(self.audit(root)["overall"]["formal_admitted"], 0)

    def test_failure_missing_manifest_and_missing_response_stay_in_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "valid", self.manifest())
            self.sample(root, "nonconverged", self.manifest(execution="nonconverged"))
            self.sample(root, "unknown")
            self.sample(root, "missing_response", self.manifest(), response=None)
            result = extract_input_from_opensees(root, root / "selected.csv", criteria_id=self.criteria)
            audit = self.audit(root)
            self.assertEqual(len(result), 1)
            self.assertEqual(audit["overall"]["input_records"], 4)
            self.assertEqual(audit["overall"]["physical_state_unknown"], 3)
            self.assertEqual(audit["overall"]["unclassified_numerical_failures"], 1)
            self.assertEqual(audit["overall"]["reason_counts"]["response_missing"], 1)

    def test_expected_missing_run_is_retained_even_when_directory_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "valid", self.manifest())
            result = extract_input_from_opensees(root, root / "selected.csv", criteria_id=self.criteria,
                expected_samples=[{"sample_id": "valid", "wind_speed": 20}, {"sample_id": "never_started", "wind_speed": 20}])
            self.assertEqual(len(result), 1)
            audit = self.audit(root)
            self.assertEqual(audit["overall"]["input_records"], 2)
            missing = next(row for row in audit["rows"] if row["sample_id"] == "never_started")
            self.assertIn("manifest_missing", missing["reason_codes"])
            self.assertIn("response_missing", missing["reason_codes"])

    def test_nonfinite_response_rejected_and_drift_time_column_not_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "nan", self.manifest(), response="0 0\n1 nan\n")
            with self.assertRaises(RuntimeError):
                extract_input_from_opensees(root, root / "selected.csv", criteria_id=self.criteria)
            self.assertIn("response_invalid:ValueError", self.audit(root)["rows"][0]["reason_codes"])
            sample_dir = root / "20mps" / "nan"
            (sample_dir / "drift.csv").write_text("step,time,floor_1\n1,100,.001\n2,200,-.002\n", encoding="utf-8")
            result = extract_input_from_opensees(root, root / "drift.csv", "drift", criteria_id=self.criteria)
            self.assertEqual(result.iloc[0]["response"], .002)

    def test_exploration_distinguishes_legacy_and_intact_unvalidated_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "legacy", {"status": "completed"})
            quality = ResultQuality()
            quality.set_execution("completed")
            self.sample(root, "unvalidated", {"status": "completed", "quality": quality.to_dict()})
            result = extract_input_from_opensees(root, root / "selected.csv", eligibility_mode="exploratory_legacy")
            self.assertEqual(set(result["admission_status"]), {"exploratory_legacy_only", "exploratory_unvalidated_only"})
            self.assertFalse(result["eligible_for_fragility"].any())
            audit = self.audit(root)
            self.assertEqual(audit["overall"]["exploratory_legacy_only"], 1)
            self.assertEqual(audit["overall"]["exploratory_unvalidated_only"], 1)
            unvalidated = next(row for row in audit["rows"] if row["sample_id"] == "unvalidated")
            self.assertEqual(unvalidated["quality_metadata"]["validation_status"], "unvalidated")
            self.assertEqual(unvalidated["physical_state_for_selected_criterion"], "unknown")

    def test_exploration_cannot_promote_known_mismatch_out_of_range_or_bad_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = self.manifest()
            out["quality"].update(domain_status="out_of_range", quality_flags=["out_of_calibration_range"])
            self.sample(root, "out", out)
            failed = self.manifest()
            failed["quality"].update(validation_status="failed", quality_flags=["local_response_mismatch"])
            self.sample(root, "mismatch", failed)
            bad = self.manifest()
            bad["quality"]["schema"] = "future_unknown"
            self.sample(root, "bad", bad)
            with self.assertRaises(RuntimeError):
                extract_input_from_opensees(root, root / "selected.csv", eligibility_mode="exploratory_legacy")
            audit = self.audit(root)
            self.assertEqual(audit["overall"]["excluded"], 3)
            self.assertTrue(all(not row["selected_for_analysis"] for row in audit["rows"]))

    def test_missing_root_and_invalid_speed_are_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError):
                extract_input_from_opensees(root / "absent", root / "empty.csv", criteria_id=self.criteria)
            self.assertEqual(self.audit(root, "empty")["extraction"]["discovery_notes"][0]["reason"], "output_root_missing_or_not_directory")
            self.sample(root, "sample", self.manifest(), speed="bad-speed")
            with self.assertRaises(RuntimeError):
                extract_input_from_opensees(root, root / "selected.csv", criteria_id=self.criteria)
            self.assertIn("invalid_wind_speed", self.audit(root)["rows"][0]["reason_codes"])

    def test_formal_main_exports_without_running_unfrozen_threshold_fit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "valid", self.manifest())
            with patch("fluctuate_wind_simulate.fragility_curve.main.WindFragilityCurve.from_csv") as fitter:
                result = main(["--output-root", str(root), "--output-dir", str(root / "export"),
                               "--reference-type", "node_displacement", "--criteria-id", self.criteria])
            fitter.assert_not_called()
            self.assertEqual(len(result), 1)
            self.assertTrue((root / "export/input_wind_node_displacement_formal.admission.json").is_file())

    def test_formal_main_rejects_manual_thresholds_and_missing_criteria_writes_audit(self):
        with self.assertRaises(SystemExit):
            main(["--manual-thresholds", ".001"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample(root, "legacy", {"status": "completed"})
            with self.assertRaisesRegex(RuntimeError, "criteria_id"):
                main(["--output-root", str(root), "--output-dir", str(root / "export"), "--reference-type", "node_displacement"])
            self.assertTrue((root / "export/input_wind_node_displacement_formal.admission.json").is_file())


if __name__ == "__main__":
    unittest.main()
