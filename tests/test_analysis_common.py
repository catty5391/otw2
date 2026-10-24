from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from util.analysis import AdaptiveStepper, Algorithm, RunManifest, TimeGrid, bounded_increments, cyclic_targets
from util.analysis.time_series import validate_wind_sample
from util.postprocess.response_metrics import ResponseCurve, compare_curves, path_work


class ProtocolTests(unittest.TestCase):
    def test_repetitions_sign_and_final_zero(self):
        self.assertEqual(cyclic_targets([.001], repeats=2, start_positive=False),
                         (-.001, .001, -.001, .001, 0.))
        self.assertEqual(cyclic_targets([.002], return_to_zero=False), (.002, -.002))

    def test_reversals_and_remainder_do_not_overshoot(self):
        steps = list(bounded_increments(.1, -.12, .05))
        self.assertAlmostEqual(sum(steps), -.22)
        self.assertTrue(all(-.05 <= value < 0 for value in steps))
        self.assertAlmostEqual(steps[-1], -.02)
        self.assertEqual(list(bounded_increments(0, 0, .01)), [])

    def test_invalid_protocol_is_rejected(self):
        for amplitudes in ([], [0], [-1], [math.nan], [math.inf]):
            with self.subTest(amplitudes=amplitudes), self.assertRaises(ValueError):
                cyclic_targets(amplitudes)
        with self.assertRaises(ValueError):
            cyclic_targets([.1], repeats=True)
        with self.assertRaises(ValueError):
            list(bounded_increments(0, 1, 0))


class TimeSeriesTests(unittest.TestCase):
    def test_floating_point_time_grid(self):
        grid = TimeGrid.from_values(i / 12 for i in range(721))
        self.assertEqual(grid.nsteps, 720)
        self.assertAlmostEqual(grid.dt, 1 / 12)
        self.assertEqual(grid.duration, 60)

    def test_invalid_time_grids(self):
        for values in ([0], [1, 2], [0, 0], [0, 2, 1], [0, .1, .25], [0, math.nan]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                TimeGrid.from_values(values)

    def _files(self, root: Path, forces: str = "1\n2\n3\n"):
        (root / "t.csv").write_text("\ufeff0\n0.1\n0.2\n", encoding="utf-8")
        (root / "floor0_wind_press.csv").write_text(forces, encoding="utf-8")

    def test_wind_channels_and_optional_model_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._files(root)
            result = validate_wind_sample(root, {"floor0": [1, 2]}, available_nodes=[1, 2, 3])
            self.assertEqual(result["nsteps"], 2)
            self.assertEqual(result["channels"]["floor0"]["maximum"], 3)
            with self.assertRaises(ValueError):
                validate_wind_sample(root, {"floor0": [1, 4]}, available_nodes=[1, 2])

    def test_bad_force_files_cannot_silently_truncate_analysis(self):
        for forces in ("1\n2\n", "1\nNaN\n3\n", "1,2\n3\n4\n", ""):
            with self.subTest(forces=forces), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._files(root, forces)
                with self.assertRaises(ValueError):
                    validate_wind_sample(root, {"floor0": [1]})

    def test_duplicate_floor_nodes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._files(root)
            with self.assertRaises(ValueError):
                validate_wind_sample(root, {"floor0": [1, 1]})


class ResponseMetricsTests(unittest.TestCase):
    def test_only_common_support_is_compared(self):
        ref = ResponseCurve.from_pairs([(0, 0), (1, 2), (2, 4)])
        cand = ResponseCurve.from_pairs([(.5, 1), (1.5, 3)])
        result = compare_curves(ref, cand)
        self.assertEqual(result["common_start"], .5)
        self.assertEqual(result["common_end"], 1.5)
        self.assertEqual(result["reference_coverage_percent"], 50)
        self.assertAlmostEqual(result["rmse"], 0)

    def test_exact_rmse_is_sampling_density_independent(self):
        ref = ResponseCurve.from_pairs([(0, 0), (1, 0)])
        coarse = ResponseCurve.from_pairs([(0, 0), (1, 1)])
        dense = ResponseCurve.from_pairs([(0, 0), (.01, .01), (.02, .02), (.9, .9), (1, 1)])
        a, b = compare_curves(ref, coarse), compare_curves(ref, dense)
        self.assertAlmostEqual(a["rmse"], math.sqrt(1 / 3))
        self.assertAlmostEqual(a["rmse"], b["rmse"])
        self.assertIsNone(a["domain_weighted_nrmse_percent"])

    def test_no_extrapolation_and_no_reversal_sorting(self):
        ref = ResponseCurve.from_pairs([(0, 0), (1, 1)])
        with self.assertRaises(ValueError):
            ref.evaluate(-.1)
        with self.assertRaises(ValueError):
            compare_curves(ref, ResponseCurve.from_pairs([(2, 0), (3, 1)]))
        with self.assertRaises(ValueError):
            ResponseCurve.from_pairs([(0, 0), (1, 1), (0, 0)])

    def test_signed_work_distinguishes_elastic_return_and_closed_loop(self):
        self.assertEqual(path_work([(0, 0), (1, 2), (0, 0)], require_closed=True), 0)
        self.assertEqual(abs(path_work([(0, 0), (1, 0), (1, 2), (0, 2), (0, 0)], require_closed=True)), 2)
        with self.assertRaises(ValueError):
            path_work([(0, 0), (1, 2)], require_closed=True)


class FakeSolver:
    def __init__(self, limit: float = math.inf):
        self.position = 0.
        self.increment = 0.
        self.limit = limit
        self.algorithm_name = "Newton"
        self.tests = []
        self.fail_newton = False
        self.corrupt_failure = False

    def algorithm(self, name, *args):
        self.algorithm_name = name

    def test(self, *args):
        self.tests.append(args)

    def analyze(self, nsteps, dt=None):
        increment = self.increment if dt is None else dt
        if abs(increment) > self.limit or (self.fail_newton and self.algorithm_name == "Newton"):
            if self.corrupt_failure:
                self.position += .01
            return -3
        self.position += increment
        return 0


class AdaptiveStepperTests(unittest.TestCase):
    def make_stepper(self, solver, **kwargs):
        return AdaptiveStepper(solver, progress=lambda: solver.position,
                               configure_increment=lambda value: setattr(solver, "increment", value),
                               minimum_increment=.01, **kwargs)

    def test_algorithm_fallback_restores_baseline_and_tolerance(self):
        solver = FakeSolver()
        solver.fail_newton = True
        stepper = self.make_stepper(solver)
        result = stepper.step(.1)
        self.assertTrue(result.converged)
        self.assertEqual(result.algorithm, "KrylovNewton")
        self.assertAlmostEqual(solver.position, .1)
        self.assertEqual(solver.algorithm_name, "Newton")
        self.assertEqual(len(set(solver.tests)), 1)

    def test_subdivision_advances_to_exact_target(self):
        solver = FakeSolver(limit=.03)
        stepper = self.make_stepper(solver)
        captured = []
        result = stepper.advance_to(.1, maximum_increment=.1, on_step=lambda step: captured.append(solver.position))
        self.assertTrue(result.converged)
        self.assertAlmostEqual(result.achieved, .1)
        self.assertGreater(result.accepted_steps, 1)
        self.assertEqual(len(captured), result.accepted_steps)
        self.assertGreater(stepper.diagnostics()["reduced_steps"], 0)

    def test_reverse_and_remainder_smaller_than_minimum(self):
        solver = FakeSolver()
        solver.position = .02
        stepper = self.make_stepper(solver)
        result = stepper.advance_to(-.003, maximum_increment=.01)
        self.assertTrue(result.converged)
        self.assertAlmostEqual(result.achieved, -.003)

    def test_failure_preserves_actual_partial_endpoint(self):
        class PartialSolver(FakeSolver):
            def analyze(self, nsteps, dt=None):
                if self.position >= .025 - 1e-12:
                    return -3
                return super().analyze(nsteps, dt)
        solver = PartialSolver(limit=.025)
        result = self.make_stepper(solver).advance_to(.1, maximum_increment=.1)
        self.assertFalse(result.converged)
        self.assertAlmostEqual(result.achieved, .025)
        self.assertEqual(result.accepted_steps, 1)

    def test_inconsistent_failed_state_is_not_retried(self):
        solver = FakeSolver(limit=0)
        solver.corrupt_failure = True
        stepper = self.make_stepper(solver)
        with self.assertRaisesRegex(RuntimeError, "返回码不一致"):
            stepper.step(.1)
        self.assertEqual(stepper.attempt_count, 1)

    def test_transient_time_steps_cover_full_interval(self):
        solver = FakeSolver(limit=.03)
        stepper = AdaptiveStepper(solver, progress=lambda: solver.position, transient=True,
                                  minimum_increment=.01)
        self.assertTrue(stepper.advance_to(.1, maximum_increment=.1).converged)
        self.assertAlmostEqual(solver.position, .1)
        with self.assertRaises(ValueError):
            stepper.advance_to(0, maximum_increment=.1)


class RunManifestTests(unittest.TestCase):
    def read(self, root):
        return json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))

    def test_completion_fingerprints_and_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("initial input", encoding="utf-8")
            with RunManifest(root, parameters={"model": "test"}, input_files=[source], seed=7) as run:
                run.update(completed_steps=2)
                self.assertEqual(self.read(root)["status"], "running")
                with self.assertRaisesRegex(RuntimeError, "运行锁"):
                    with RunManifest(root, parameters={}):
                        pass
                run.add_artifact("source", source)
            result = self.read(root)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["completed_steps"], 2)
            self.assertEqual(len(result["inputs"][0]["sha256"]), 64)
            self.assertEqual(result["seed"], 7)
            self.assertFalse((root / ".run.lock").exists())

    def test_exceptions_record_failure_and_propagate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                with RunManifest(root, parameters={}) as run:
                    run.update(completed_steps=3)
                    raise RuntimeError("stopped")
            result = self.read(root)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["completed_steps"], 3)
            self.assertFalse((root / ".run.lock").exists())

    def test_missing_input_does_not_leave_stale_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with RunManifest(root, parameters={}):
                pass
            with self.assertRaises(FileNotFoundError):
                with RunManifest(root, parameters={}, input_files=[root / "missing.txt"]):
                    pass
            self.assertEqual(self.read(root)["status"], "failed")
            self.assertFalse((root / ".run.lock").exists())

    def test_nonconvergence_and_interrupt_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with RunManifest(root, parameters={}) as run:
                run.finish(converged=False)
            self.assertEqual(self.read(root)["status"], "nonconverged")
            with self.assertRaises(KeyboardInterrupt):
                with RunManifest(root, parameters={}):
                    raise KeyboardInterrupt()
            self.assertEqual(self.read(root)["status"], "interrupted")

    def test_nonfinite_metrics_and_rewinding_progress_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with RunManifest(root, parameters={}) as run:
                run.update(completed_steps=3)
                with self.assertRaises(ValueError):
                    run.update(completed_steps=2)
                with self.assertRaises(ValueError):
                    run.update(error=math.nan)
                self.assertEqual(self.read(root)["completed_steps"], 3)

    def test_partial_run_is_not_automatically_marked_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with RunManifest(root, parameters={}, expected_steps=10) as run:
                run.update(completed_steps=4)
            self.assertEqual(self.read(root)["status"], "nonconverged")


if __name__ == "__main__":
    unittest.main()
