"""Algorithm fallback and step reduction with explicit partial-progress reporting."""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Algorithm:
    name: str
    arguments: tuple[Any, ...] = ()


@dataclass(frozen=True)
class StepResult:
    converged: bool
    requested_increment: float
    accepted_increment: float
    attempts: int
    algorithm: str | None
    return_code: int
    stop_reason: str | None = None
    iterations: int | None = None


@dataclass(frozen=True)
class AdvanceResult:
    converged: bool
    start: float
    target: float
    achieved: float
    accepted_steps: int
    stop_reason: str | None = None


class AdaptiveStepper:
    """Advance an already-configured static or transient analysis.

    ``progress`` must return node displacement for displacement control, or
    domain time for transient analysis. ``configure_increment`` updates the
    static integrator. A failed OpenSees step must leave the committed state
    unchanged. The same convergence test is used for every fallback algorithm.
    """

    def __init__(
        self,
        ops: Any,
        *,
        progress: Callable[[], float],
        configure_increment: Callable[[float], None] | None = None,
        transient: bool = False,
        minimum_increment: float = 1e-5,
        algorithms: tuple[Algorithm, ...] = (
            Algorithm("Newton"), Algorithm("KrylovNewton"), Algorithm("NewtonLineSearch", (0.8,)),
        ),
        convergence_test: tuple[Any, ...] = ("NormDispIncr", 1e-6, 60, 0),
        progress_tolerance: float = 1e-9,
        on_attempt: Callable[[dict[str, Any]], None] | None = None,
        maximum_attempts_per_step: int | None = None,
        maximum_total_attempts: int | None = None,
        maximum_accepted_steps: int | None = None,
        timeout_seconds: float | None = None,
        recovery_policy: str = "legacy",
        recovery_growth_factor: float = 1.5,
        recovery_successes_before_growth: int = 2,
        recover_analysis_exception: Callable[[Exception], bool] | None = None,
    ) -> None:
        if not math.isfinite(minimum_increment) or minimum_increment <= 0:
            raise ValueError("minimum_increment 必须为有限正数。")
        if not math.isfinite(progress_tolerance) or progress_tolerance <= 0:
            raise ValueError("progress_tolerance 必须为有限正数。")
        if not algorithms:
            raise ValueError("至少需要一种求解算法。")
        if not transient and configure_increment is None:
            raise ValueError("静力求解必须提供 configure_increment。")
        for name, value in (("maximum_attempts_per_step", maximum_attempts_per_step),
                            ("maximum_total_attempts", maximum_total_attempts),
                            ("maximum_accepted_steps", maximum_accepted_steps),
                            ("recovery_successes_before_growth", recovery_successes_before_growth)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ValueError(f"{name} must be a positive integer")
        if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be finite and positive")
        if recovery_policy not in {"legacy", "last_success", "gradual"}:
            raise ValueError("recovery_policy must be legacy, last_success or gradual")
        if not math.isfinite(recovery_growth_factor) or recovery_growth_factor < 1:
            raise ValueError("recovery_growth_factor must be finite and >= 1")
        self.ops = ops
        self.progress = progress
        self.configure_increment = configure_increment
        self.transient = transient
        self.minimum_increment = float(minimum_increment)
        self.algorithms = algorithms
        self.convergence_test = convergence_test
        self.progress_tolerance = progress_tolerance
        self.on_attempt = on_attempt
        self.maximum_attempts_per_step = maximum_attempts_per_step
        self.maximum_total_attempts = maximum_total_attempts
        self.maximum_accepted_steps = maximum_accepted_steps
        self.timeout_seconds = timeout_seconds
        self.recovery_policy = recovery_policy
        self.recovery_growth_factor = recovery_growth_factor
        self.recovery_successes_before_growth = recovery_successes_before_growth
        # Only an explicitly verified application recovery may permit retry
        # after an exception. Checking one progress DOF alone is not rollback.
        self.recover_analysis_exception = recover_analysis_exception
        self._started_at = time.monotonic()
        self.restore_errors: list[str] = []
        self.attempt_count = 0
        self.failed_attempts = 0
        self.accepted_steps = 0
        self.reduced_steps = 0

    def diagnostics(self) -> dict[str, int]:
        return {
            "attempts": self.attempt_count, "failed_attempts": self.failed_attempts,
            "accepted_steps": self.accepted_steps, "reduced_steps": self.reduced_steps,
        }

    def _tolerance(self, start: float, target: float) -> float:
        return max(self.progress_tolerance, 16 * math.ulp(max(abs(start), abs(target), 1.0)))

    def settings(self) -> dict[str, Any]:
        """Effective settings suitable for inclusion in a run manifest."""
        return {"minimum_increment": self.minimum_increment,
                "algorithms": [{"name": a.name, "arguments": list(a.arguments)} for a in self.algorithms],
                "convergence_test": list(self.convergence_test), "progress_tolerance": self.progress_tolerance,
                "maximum_attempts_per_step": self.maximum_attempts_per_step,
                "maximum_total_attempts": self.maximum_total_attempts,
                "maximum_accepted_steps": self.maximum_accepted_steps, "timeout_seconds": self.timeout_seconds,
                "recovery_policy": self.recovery_policy, "recovery_growth_factor": self.recovery_growth_factor,
                "recovery_successes_before_growth": self.recovery_successes_before_growth,
                "exception_recovery_configured": self.recover_analysis_exception is not None}

    def _budget_reason(self, attempts: int) -> str | None:
        if self.maximum_attempts_per_step is not None and attempts >= self.maximum_attempts_per_step:
            return "maximum_attempts_per_step"
        if self.maximum_total_attempts is not None and self.attempt_count >= self.maximum_total_attempts:
            return "maximum_total_attempts"
        if self.maximum_accepted_steps is not None and self.accepted_steps >= self.maximum_accepted_steps:
            return "maximum_accepted_steps"
        if self.timeout_seconds is not None and time.monotonic() - self._started_at >= self.timeout_seconds:
            return "timeout"
        return None

    def _iteration_diagnostics(self) -> tuple[int | None, list[Any] | None, list[str]]:
        iterations, norms, errors = None, None, []
        if hasattr(self.ops, "testIter"):
            try:
                iterations = int(self.ops.testIter())
            except Exception as error:
                errors.append(f"testIter: {type(error).__name__}: {error}")
        if hasattr(self.ops, "testNorms"):
            try:
                values = list(self.ops.testNorms())
                values = values[:max(0, iterations)] if iterations is not None else values
                # Nonfinite convergence norms remain explicit, JSON-safe strings.
                norms = [float(value) if math.isfinite(float(value)) else str(value) for value in values]
            except Exception as error:
                errors.append(f"testNorms: {type(error).__name__}: {error}")
        return iterations, norms, errors

    def step(self, increment: float) -> StepResult:
        requested = float(increment)
        if not math.isfinite(requested) or requested == 0 or (self.transient and requested < 0):
            raise ValueError("步长必须有限且非零；瞬态时间步长必须为正。")
        before = float(self.progress())
        if not math.isfinite(before):
            raise ValueError("当前分析进度不是有限数值。")
        trial = requested
        attempts = 0
        code = -1
        try:
            while True:
                if self.configure_increment is not None:
                    self.configure_increment(trial)
                for algorithm in self.algorithms:
                    reason = self._budget_reason(attempts)
                    if reason is not None:
                        return StepResult(False, requested, 0.0, attempts, None, code, reason)
                    self.ops.test(*self.convergence_test)
                    self.ops.algorithm(algorithm.name, *algorithm.arguments)
                    exception = None
                    attempt_started = time.monotonic()
                    try:
                        code = int(self.ops.analyze(1, trial) if self.transient else self.ops.analyze(1))
                    except Exception as error:
                        exception, code = error, -999
                    after = float(self.progress())
                    attempts += 1
                    self.attempt_count += 1
                    if code != 0:
                        self.failed_attempts += 1
                    iterations, norms, diagnostic_errors = self._iteration_diagnostics()
                    event = {"attempt_id": self.attempt_count, "before": before, "after": after,
                             "requested_increment": requested, "increment": trial,
                             "algorithm": algorithm.name, "algorithm_arguments": list(algorithm.arguments),
                             "convergence_test": list(self.convergence_test),
                             "return_code": code if exception is None else None,
                             "iterations": iterations, "norms": norms,
                             "diagnostic_errors": diagnostic_errors,
                             "elapsed_seconds": time.monotonic() - attempt_started,
                             "state": "committed" if code == 0 else "failed_attempt",
                             "exception": f"{type(exception).__name__}: {exception}" if exception else None}
                    expected = before + trial if code == 0 else before
                    state_consistent = math.isfinite(after) and abs(after - expected) <= self._tolerance(before, expected)
                    event["committed_progress_consistent"] = state_consistent
                    if code == 0 and state_consistent and after != before:
                        # The analysis has already committed even if the recorder
                        # raises below. Account for it before invoking callbacks.
                        self.accepted_steps += 1
                        self.reduced_steps += int(abs(trial) < abs(requested))
                    if self.on_attempt:
                        self.on_attempt(event)
                    if not state_consistent:
                        raise RuntimeError(
                            f"求解状态与返回码不一致: code={code}, before={before}, "
                            f"after={after}, expected={expected}；已停止重试。"
                        )
                    if exception is not None:
                        if self.recover_analysis_exception is None or not self.recover_analysis_exception(exception):
                            raise exception
                        recovered = float(self.progress())
                        if not math.isfinite(recovered) or abs(recovered - before) > self._tolerance(before, before):
                            raise RuntimeError("Explicit exception recovery did not restore committed progress") from exception
                    if code == 0:
                        if after == before:
                            raise RuntimeError("求解返回成功，但分析状态没有前进。")
                        return StepResult(True, requested, trial, attempts, algorithm.name, 0, iterations=iterations)
                if abs(trial) <= self.minimum_increment:
                    return StepResult(False, requested, 0.0, attempts, None, code, "minimum_increment")
                trial = math.copysign(max(abs(trial) * 0.5, self.minimum_increment), trial)
        finally:
            baseline = self.algorithms[0]
            active_exception = sys.exc_info()[0] is not None
            try:
                self.ops.algorithm(baseline.name, *baseline.arguments)
                self.ops.test(*self.convergence_test)
            except Exception as error:
                self.restore_errors.append(f"{type(error).__name__}: {error}")
                if not active_exception:
                    raise

    def advance_to(
        self,
        target: float,
        *,
        maximum_increment: float,
        on_step: Callable[[StepResult], None] | None = None,
    ) -> AdvanceResult:
        target, limit = float(target), float(maximum_increment)
        start = float(self.progress())
        if not all(math.isfinite(v) for v in (start, target, limit)) or limit <= 0:
            raise ValueError("目标必须有限，maximum_increment 必须为有限正数。")
        if self.transient and target < start:
            raise ValueError("瞬态目标时间不能早于当前时间。")
        accepted = 0
        next_limit = limit
        small_successes = 0
        while True:
            current = float(self.progress())
            remaining = target - current
            if abs(remaining) <= self._tolerance(start, target):
                return AdvanceResult(True, start, target, current, accepted)
            result = self.step(math.copysign(min(abs(remaining), next_limit), remaining))
            if not result.converged:
                return AdvanceResult(False, start, target, float(self.progress()), accepted, result.stop_reason)
            accepted += 1
            if self.recovery_policy != "legacy":
                if abs(result.accepted_increment) < abs(result.requested_increment):
                    next_limit = min(limit, abs(result.accepted_increment))
                    small_successes = 0
                elif self.recovery_policy == "gradual":
                    small_successes += 1
                    if small_successes >= self.recovery_successes_before_growth:
                        next_limit = min(limit, next_limit * self.recovery_growth_factor)
                        small_successes = 0
            if on_step:
                on_step(result)
