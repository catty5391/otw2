import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from initial_imperfection_material.calibration_cache import (
    CalibrationCache, CacheCorruptionError, CacheIdentityMismatch,
    CacheWriteConflict, LegacyCacheRequiresOptIn, ReferenceNonconvergence,
    publish_json_once,
)
from initial_imperfection_material.config import (
    AnalysisConfig, ReferenceSolverConfig, file_sha256, fingerprint, grouped_length,
)
from initial_imperfection_material.experiment import AnalysisResult
from initial_imperfection_material.material import EquivalentImperfectionMaterial
from model.mechanical_profile import Steel02Parameters
from model.tower_model_with_equivalent_imperfection import OpenSeesModelWithEquivalentImperfection


ROOT = Path(__file__).resolve().parents[1]


def example_config():
    return AnalysisConfig(
        model={"source_sha256": "source-a", "section": {"A": 0.001, "I23": 1e-7},
               "divisions": 16, "algorithm_version": "v1", "engine": "3.8.0"},
        steel={"Q235": Steel02Parameters.legacy_member(E0=210e9, fy=235e6).as_dict()},
        boundary={"type": "pinned"}, protocol={"steps": 120, "maximum_strain": 0.03},
        solver=ReferenceSolverConfig().to_dict(),
        calibration={"method": "reference", "fallback_policy": "error"},
    )


class CalibrationConfigTests(unittest.TestCase):
    def test_config_round_trip_and_key_order(self):
        config = example_config()
        self.assertEqual(AnalysisConfig(**config.to_dict()).fingerprint, config.fingerprint)
        self.assertEqual(fingerprint({"a": 1, "b": 2}), fingerprint({"b": 2, "a": 1}))

    def test_every_physical_and_method_change_invalidates(self):
        config = example_config()
        cases = [("steel", "Q235", key, value) for key, value in
                 (("E0", 206e9), ("fy", 345e6), ("b", 0.005), ("a1", 0.0005))]
        cases += [("model", key, value) for key, value in
                  (("source_sha256", "source-b"), ("divisions", 8),
                   ("algorithm_version", "v2"), ("engine", "3.9"))]
        cases += [("boundary", "type", "fixed"), ("calibration", "method", "perry"),
                  ("solver", "tolerance", 1e-9), ("model", "section", {"A": 0.001, "I23": 2e-7})]
        for case in cases:
            with self.subTest(case=case):
                changed = config.to_dict()
                target = changed
                for key in case[:-2]:
                    target = target[key]
                target[case[-2]] = case[-1]
                self.assertNotEqual(AnalysisConfig(**changed).fingerprint, config.fingerprint)

    def test_solver_strict_and_legacy_are_distinct(self):
        strict = ReferenceSolverConfig()
        legacy = ReferenceSolverConfig.legacy()
        self.assertFalse(strict.relaxes_tolerance)
        self.assertTrue(legacy.relaxes_tolerance)
        self.assertNotEqual(fingerprint(strict.to_dict()), fingerprint(legacy.to_dict()))

    def test_invalid_finite_values_and_missing_steel(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    grouped_length(value, 0.01)
                with self.assertRaises(ValueError):
                    ReferenceSolverConfig(tolerance=value)
        config = example_config().to_dict()
        del config["steel"]["Q235"]["a1"]
        with self.assertRaises(ValueError):
            AnalysisConfig(**config)

    def test_length_bin_boundaries_are_explicit(self):
        self.assertAlmostEqual(grouped_length(1.0049, 0.01), 1.0)
        self.assertAlmostEqual(grouped_length(1.0051, 0.01), 1.01)
        self.assertEqual(grouped_length(1.005, 0.01), round(1.005 / 0.01) * 0.01)
        with self.assertRaises(ValueError):
            grouped_length(0.001, 0.01)

    def test_config_is_snapshot_of_input(self):
        original = example_config().to_dict()
        config = AnalysisConfig(**original)
        before = config.fingerprint
        original["model"]["divisions"] = 999
        returned = config.to_dict()
        returned["model"]["divisions"] = 100
        self.assertEqual(config.fingerprint, before)

    def test_invalid_iteration_counts(self):
        for value in (0, -1, 1.5, True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ReferenceSolverConfig(max_iterations=value)


class CalibrationCacheTests(unittest.TestCase):
    def test_write_read_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = CalibrationCache(Path(temporary) / "cache.json")
            config = example_config()
            self.assertIsNone(cache.read(config))
            cache.write(config, {"group": {"value": 1}})
            before = file_sha256(cache.path)
            self.assertEqual(cache.read(config)["groups"]["group"]["value"], 1)
            with self.assertRaises(CacheWriteConflict):
                cache.write(config, {"group": {"value": 2}})
            self.assertEqual(file_sha256(cache.path), before)
            self.assertEqual(list(Path(temporary).glob("*.tmp")), [])

    def test_method_mismatch_rejects_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = CalibrationCache(Path(temporary) / "cache.json")
            config = example_config()
            cache.write(config, {})
            perry = replace(config, calibration={"method": "perry", "fallback_policy": "error"})
            with self.assertRaises(CacheIdentityMismatch):
                cache.read(perry)

    def test_corrupt_half_written_json_and_nonfinite_are_rejected(self):
        for text in ('{"format":', '{"x": NaN}', "[]", '{"format":"unknown"}'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "cache.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(CacheCorruptionError):
                    CalibrationCache(path).read(example_config())

    def test_complete_json_with_corrupt_group_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cache.json"
            cache = CalibrationCache(path)
            cache.write(example_config(), {"group": {"force": 123}})
            payload = json.loads(path.read_text())
            payload["groups"]["group"]["force"] = 456
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(CacheCorruptionError):
                cache.read(example_config())

    def test_incomplete_status_is_not_reusable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cache.json"
            cache = CalibrationCache(path)
            cache.write(example_config(), {})
            payload = json.loads(path.read_text())
            payload["status"] = "failed"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(CacheCorruptionError):
                cache.read(example_config())

    def test_lock_excludes_competing_writer_and_cleans_up_after_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = CalibrationCache(Path(temporary) / "cache.json")
            with self.assertRaisesRegex(RuntimeError, "test exception"):
                with cache.locked():
                    with self.assertRaises(CacheWriteConflict):
                        with CalibrationCache(cache.path).locked():
                            self.fail("competing writer acquired lock")
                    raise RuntimeError("test exception")
            with cache.locked():
                pass
            self.assertFalse(cache.path.with_name("cache.json.lock").exists())

    def test_atomic_publish_failure_does_not_leave_partial_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cache.json"
            with patch("initial_imperfection_material.calibration_cache.os.link", side_effect=OSError("disk fault")):
                with self.assertRaises(OSError):
                    publish_json_once(path, {"complete": True})
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_legacy_requires_opt_in_and_never_changes_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.json"
            publish_json_once(path, {"format": "otw2.equivalent_imperfection_library.v1", "groups": {"old": {}}})
            before = file_sha256(path)
            with self.assertRaises(LegacyCacheRequiresOptIn):
                CalibrationCache(path).read(example_config())
            result = CalibrationCache(path, allow_legacy=True).read(example_config())
            self.assertTrue(result["legacy"])
            self.assertEqual(result["validation_status"], "legacy_unknown")
            self.assertEqual(before, file_sha256(path))


class CalibrationModelIntegrationTests(unittest.TestCase):
    def model(self, temporary, **kwargs):
        model = OpenSeesModelWithEquivalentImperfection(
            ROOT / "Source/Z30103A6.s2k", output_dir=Path(temporary) / "model",
            calibration_cache=Path(temporary) / "cache.json", **kwargs)
        # Exactly one virtual source member; never run the 194-group tower batch.
        model._parse_node_coordinates = lambda: {
            1: {"x": 0.0, "y": 0.0, "z": 0.0},
            2: {"x": 0.0, "y": 0.0, "z": 0.853}}
        model._parse_element_connectivity = lambda: {877: {"node_i": 1, "node_j": 2}}
        model._element_section_assignments = lambda: {877: {"section_name": "L40x3Q235"}}
        return model

    @staticmethod
    def partial_result():
        return AnalysisResult(curve=[], runtime_seconds=1.2, requested_steps=120,
                              completed_steps=37, converged=False,
                              requested_end_shortening=0.0255, actual_end_shortening=0.0078)

    def test_cold_then_hot_cache_does_not_recalibrate(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = self.model(temporary, calibration_method="perry")
            first.prepare_calibration_library()
            self.assertFalse(first.calibration_cache_info["cache_hit"])
            before = file_sha256(first.calibration_cache)
            second = self.model(temporary, calibration_method="perry")
            with patch.object(EquivalentImperfectionMaterial, "from_perry", side_effect=AssertionError("recalibrated")):
                second.prepare_calibration_library()
            self.assertTrue(second.calibration_cache_info["cache_hit"])
            self.assertEqual(second.calibration_cache_info["cache_mode"], "warm_v2")
            self.assertEqual(second.calibration_cache_info["calibration_seconds"], 0)
            self.assertEqual(file_sha256(second.calibration_cache), before)
            payload = json.loads(second.calibration_cache.read_text())
            member = next(iter(payload["groups"].values()))["actual_members"][0]
            self.assertAlmostEqual(member["actual_length"], 0.853)
            self.assertAlmostEqual(member["representative_length"], 0.85)
            self.assertAlmostEqual(member["length_error"], -0.003)

    def test_model_method_change_fails_without_reference_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.model(temporary, calibration_method="perry").prepare_calibration_library()
            model = self.model(temporary, calibration_method="reference")
            with patch("model.tower_model_with_equivalent_imperfection.run_segmented_reference") as reference:
                with self.assertRaises(CacheIdentityMismatch):
                    model.prepare_calibration_library()
                reference.assert_not_called()

    def test_program_error_never_falls_back_to_perry(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = self.model(temporary, calibration_fallback_policy="perry_exploratory")
            with patch("model.tower_model_with_equivalent_imperfection.run_segmented_reference", side_effect=KeyError("bug")):
                with self.assertRaises(KeyError):
                    model.prepare_calibration_library()
            self.assertFalse(model.calibration_cache.exists())

    def test_nonconvergence_is_strict_by_default_and_preserves_partial_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = self.model(temporary)
            with patch("model.tower_model_with_equivalent_imperfection.run_segmented_reference", return_value=self.partial_result()):
                with self.assertRaises(ReferenceNonconvergence) as caught:
                    model.prepare_calibration_library()
            self.assertEqual(caught.exception.result.completed_steps, 37)
            self.assertFalse(model.calibration_cache.exists())
            failure_files = list(Path(temporary).glob("cache.json.failed.*.json"))
            self.assertEqual(len(failure_files), 1)
            failure = json.loads(failure_files[0].read_text())["failure"]
            self.assertEqual(failure["completed_steps"], 37)
            self.assertAlmostEqual(failure["actual_end_shortening"], 0.0078)

    def test_opt_in_fallback_keeps_partial_record_and_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = self.model(temporary, calibration_fallback_policy="perry_exploratory")
            with patch("model.tower_model_with_equivalent_imperfection.run_segmented_reference", return_value=self.partial_result()):
                model.prepare_calibration_library()
            record = next(iter(model.calibration_records.values()))
            self.assertEqual(record["method"], "perry_fallback")
            self.assertEqual(record["completed_steps"], 37)
            self.assertEqual(record["runtime_seconds"], 1.2)
            self.assertIn("exploratory_perry_fallback", record["quality_flags"])

    def test_invalid_model_inputs_fail_fast(self):
        cases = [{"imperfection_ratio": float("nan")}, {"calibration_length_bin": 0},
                 {"calibration_steps": 1.5}, {"calibration_divisions": 3}]
        with tempfile.TemporaryDirectory() as temporary:
            for case in cases:
                with self.subTest(case=case), self.assertRaises(ValueError):
                    self.model(temporary, **case)


if __name__ == "__main__":
    unittest.main()
