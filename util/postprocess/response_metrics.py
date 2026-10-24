"""Comparison on shared curve support and signed work along response paths."""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ResponseCurve:
    x: tuple[float, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.x) < 2 or len(self.x) != len(self.y):
            raise ValueError("曲线至少需要两个配对点。")
        if not all(math.isfinite(v) for v in (*self.x, *self.y)):
            raise ValueError("曲线包含非有限数值。")
        if any(right <= left for left, right in zip(self.x, self.x[1:])):
            raise ValueError("比较曲线的横坐标必须严格递增；往复历程应使用 path_work。")

    @classmethod
    def from_pairs(cls, values: Iterable[tuple[float, float]]) -> "ResponseCurve":
        pairs = tuple((float(x), float(y)) for x, y in values)
        return cls(tuple(x for x, _ in pairs), tuple(y for _, y in pairs))

    def evaluate(self, x: float) -> float:
        x = float(x)
        if not math.isfinite(x) or x < self.x[0] or x > self.x[-1]:
            raise ValueError("请求点超出曲线范围，禁止外推。")
        index = bisect_left(self.x, x)
        if self.x[index] == x:
            return self.y[index]
        fraction = (x - self.x[index - 1]) / (self.x[index] - self.x[index - 1])
        return self.y[index - 1] + fraction * (self.y[index] - self.y[index - 1])

    def clip(self, start: float, end: float) -> "ResponseCurve":
        if not math.isfinite(start) or not math.isfinite(end) or start >= end:
            raise ValueError("共同评价区间必须具有正长度。")
        xs = (start,) + tuple(x for x in self.x if start < x < end) + (end,)
        return ResponseCurve(xs, tuple(self.evaluate(x) for x in xs))


def path_work(points: Iterable[tuple[float, float]], *, require_closed: bool = False) -> float:
    """Return signed integral y dx in input order, preserving every reversal.

    Open paths are external work. Only an appropriately closed force-displacement
    loop can be interpreted as hysteretic energy; no sorting by displacement is done.
    """
    pairs = tuple((float(x), float(y)) for x, y in points)
    if len(pairs) < 2 or not all(math.isfinite(v) for pair in pairs for v in pair):
        raise ValueError("路径至少需要两个有限配对点。")
    if require_closed and not all(
        math.isclose(pairs[0][i], pairs[-1][i], rel_tol=1e-8, abs_tol=1e-10) for i in (0, 1)
    ):
        raise ValueError("路径未闭合，不能当作闭合滞回回线。")
    return math.fsum(
        (y0 + y1) * 0.5 * (x1 - x0)
        for (x0, y0), (x1, y1) in zip(pairs, pairs[1:])
    )


def compare_curves(reference: ResponseCurve, candidate: ResponseCurve) -> dict[str, float | None]:
    """Compare piecewise-linear curves over their actual intersection.

    RMSE is integrated with respect to x (exact for piecewise-linear errors),
    making it independent of sampling density. Percentages with a zero
    denominator are returned as None, never fabricated as zero or infinity.
    """
    start, end = max(reference.x[0], candidate.x[0]), min(reference.x[-1], candidate.x[-1])
    if start >= end:
        raise ValueError("两条曲线没有正长度的共同评价区间。")
    ref, cand = reference.clip(start, end), candidate.clip(start, end)
    xs = sorted(set(ref.x) | set(cand.x))
    errors = [cand.evaluate(x) - ref.evaluate(x) for x in xs]
    integral_squared = math.fsum(
        (right - left) * (a * a + a * b + b * b) / 3
        for left, right, a, b in zip(xs, xs[1:], errors, errors[1:])
    )
    rmse = math.sqrt(integral_squared / (end - start))
    reference_scale = max(abs(y) for y in ref.y)
    reference_work = path_work(zip(ref.x, ref.y))
    candidate_work = path_work(zip(cand.x, cand.y))
    return {
        "common_start": start, "common_end": end,
        "reference_coverage_percent": 100 * (end - start) / (reference.x[-1] - reference.x[0]),
        "candidate_coverage_percent": 100 * (end - start) / (candidate.x[-1] - candidate.x[0]),
        "rmse": rmse,
        "domain_weighted_nrmse_percent": 100 * rmse / reference_scale if reference_scale else None,
        "reference_work": reference_work, "candidate_work": candidate_work,
        "work_error_percent": 100 * (candidate_work - reference_work) / abs(reference_work) if reference_work else None,
    }
