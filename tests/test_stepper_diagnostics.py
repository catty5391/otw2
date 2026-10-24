from __future__ import annotations

import unittest

import openseespy.opensees as ops

from util.analysis.stepping import AdaptiveStepper, Algorithm


class Solver:
    def __init__(self, limit=float("inf")):
        self.position = 0.
        self.increment = 0.
        self.limit = limit
        self.name = "Newton"
        self.arguments = ()
        self.raise_once = False
        self.calls = 0

    def algorithm(self, name, *args):
        self.name, self.arguments = name, args

    def test(self, *args):
        self.test_args = args

    def analyze(self, count):
        self.calls += 1
        if self.raise_once:
            self.raise_once = False
            raise RuntimeError("engine raised")
        if abs(self.increment) > self.limit:
            return -3
        self.position += self.increment
        return 0

    def testIter(self):
        return 2

    def testNorms(self):
        return [1e-3, 1e-12, 0., 0.]


def stepper(solver, **kwargs):
    return AdaptiveStepper(solver, progress=lambda: solver.position,
                            configure_increment=lambda value: setattr(solver, "increment", value),
                            minimum_increment=.001, **kwargs)


class StepperDiagnosticsTests(unittest.TestCase):
    def test_real_opensees_attempt_reports_actual_convergence_iterations(self):
        ops.wipe()
        try:
            ops.model("basic", "-ndm", 1, "-ndf", 1)
            ops.node(1, 0.)
            ops.node(2, 1.)
            ops.fix(1, 1)
            ops.uniaxialMaterial("Elastic", 1, 1000.)
            ops.element("truss", 1, 1, 2, 1., 1)
            ops.timeSeries("Linear", 1)
            ops.pattern("Plain", 1, 1)
            ops.load(2, 1.)
            ops.constraints("Plain")
            ops.numberer("Plain")
            ops.system("BandGeneral")
            ops.integrator("DisplacementControl", 2, 1, .001)
            ops.algorithm("Newton")
            ops.analysis("Static")
            events, direct_snapshots = [], []
            def capture(event):
                events.append(event)
                direct_snapshots.append((ops.testIter(), list(ops.testNorms())[:ops.testIter()]))
            model = AdaptiveStepper(ops, progress=lambda: ops.nodeDisp(2, 1), minimum_increment=1e-5,
                                    configure_increment=lambda du: ops.integrator("DisplacementControl", 2, 1, du),
                                    convergence_test=("NormDispIncr", 1e-12, 20), on_attempt=capture)
            self.assertTrue(model.step(.001).converged)
            # Resetting the baseline test on exit may reset engine counters;
            # compare while the actual attempt diagnostics still exist.
            self.assertEqual(events[0]["iterations"], direct_snapshots[0][0])
            self.assertEqual(events[0]["norms"], direct_snapshots[0][1])
            self.assertGreaterEqual(events[0]["iterations"], 1)
        finally:
            ops.wipe()

    def test_attempt_has_real_iterations_norms_algorithm_arguments_and_test(self):
        solver, events = Solver(), []
        model = stepper(solver, algorithms=(Algorithm("NewtonLineSearch", (.8,)),), on_attempt=events.append)
        result = model.step(.1)
        self.assertEqual(result.iterations, 2)
        self.assertEqual(events[0]["iterations"], 2)
        self.assertEqual(events[0]["norms"], [1e-3, 1e-12])
        self.assertEqual(events[0]["algorithm_arguments"], [.8])
        self.assertEqual(events[0]["convergence_test"], list(model.convergence_test))
        self.assertEqual(events[0]["state"], "committed")

    def test_attempt_and_global_step_limits_stop_with_reason(self):
        solver = Solver(limit=0.)
        result = stepper(solver, maximum_attempts_per_step=2).step(.1)
        self.assertFalse(result.converged)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.stop_reason, "maximum_attempts_per_step")
        solver = Solver()
        result = stepper(solver, maximum_accepted_steps=2).advance_to(1., maximum_increment=.1)
        self.assertFalse(result.converged)
        self.assertEqual(result.stop_reason, "maximum_accepted_steps")
        self.assertAlmostEqual(result.achieved, .2)

    def test_total_attempt_budget_is_shared_across_steps(self):
        solver = Solver()
        model = stepper(solver, maximum_total_attempts=1)
        self.assertTrue(model.step(.1).converged)
        self.assertEqual(model.step(.1).stop_reason, "maximum_total_attempts")
        self.assertEqual(solver.calls, 1)

    def test_analysis_exception_is_recorded_and_terminates_by_default(self):
        solver, events = Solver(), []
        solver.raise_once = True
        model = stepper(solver, on_attempt=events.append)
        with self.assertRaisesRegex(RuntimeError, "engine raised"):
            model.step(.1)
        self.assertEqual(solver.calls, 1)
        self.assertIsNone(events[0]["return_code"])
        self.assertIn("engine raised", events[0]["exception"])
        self.assertEqual(solver.name, "Newton")

    def test_explicit_exception_recovery_is_opt_in_and_checked(self):
        solver = Solver()
        solver.raise_once = True
        recovery_calls = []
        model = stepper(solver, recover_analysis_exception=lambda error: recovery_calls.append(str(error)) or True)
        self.assertTrue(model.step(.1).converged)
        self.assertEqual(len(recovery_calls), 1)
        solver = Solver()
        solver.raise_once = True
        def bad_recovery(error):
            solver.position = 5.
            return True
        with self.assertRaisesRegex(RuntimeError, "did not restore"):
            stepper(solver, recover_analysis_exception=bad_recovery).step(.1)

    def test_recorder_error_after_commit_stops_and_keeps_commit_accounting(self):
        solver = Solver()
        def bad_recorder(event):
            raise OSError("recording failed")
        model = stepper(solver, on_attempt=bad_recorder)
        with self.assertRaisesRegex(OSError, "recording failed"):
            model.step(.1)
        self.assertAlmostEqual(solver.position, .1)
        self.assertEqual(model.accepted_steps, 1)
        self.assertEqual(solver.calls, 1)
        self.assertEqual(solver.name, "Newton")

    def test_recovery_policy_avoids_restarting_large_step_after_each_cutback(self):
        results = {}
        for policy in ("legacy", "last_success", "gradual"):
            solver = Solver(limit=.025)
            model = stepper(solver, recovery_policy=policy)
            outcome = model.advance_to(.2, maximum_increment=.1)
            self.assertTrue(outcome.converged)
            self.assertAlmostEqual(solver.position, .2)
            results[policy] = model.failed_attempts
        self.assertLess(results["last_success"], results["legacy"])
        self.assertLess(results["gradual"], results["legacy"])

    def test_timeout_and_invalid_configuration(self):
        solver = Solver()
        model = stepper(solver, timeout_seconds=1.)
        model._started_at -= 2.
        result = model.step(.1)
        self.assertEqual(result.stop_reason, "timeout")
        self.assertEqual(solver.calls, 0)
        for kwargs in ({"maximum_attempts_per_step": 0}, {"maximum_accepted_steps": True},
                       {"recovery_policy": "unknown"}, {"recovery_growth_factor": .5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                stepper(Solver(), **kwargs)


if __name__ == "__main__":
    unittest.main()
