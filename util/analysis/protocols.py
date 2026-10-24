"""Dimensionless drift protocols and signed, endpoint-exact increments."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator


def cyclic_targets(
    amplitudes: Iterable[float],
    *,
    repeats: int = 1,
    start_positive: bool = True,
    return_to_zero: bool = True,
) -> tuple[float, ...]:
    """Return (+a, -a) pairs; 0.001 means 0.1% drift, not 0.001%."""
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats 必须为正整数。")
    values = tuple(float(value) for value in amplitudes)
    if not values or any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("循环幅值必须是非空的有限正数序列。")
    sign = 1.0 if start_positive else -1.0
    targets = tuple(
        sign * amplitude * direction
        for amplitude in values
        for _ in range(repeats)
        for direction in (1, -1)
    )
    return targets + ((0.0,) if return_to_zero else ())


def bounded_increments(start: float, target: float, maximum_increment: float) -> Iterator[float]:
    """Yield signed increments with an exact last remainder and no overshoot."""
    current, target, limit = float(start), float(target), float(maximum_increment)
    if not all(math.isfinite(v) for v in (current, target, limit)) or limit <= 0:
        raise ValueError("起终点必须有限，maximum_increment 必须为有限正数。")
    while current != target:
        remaining = target - current
        increment = math.copysign(min(abs(remaining), limit), remaining)
        updated = current + increment
        if updated == current:
            raise ValueError("步长小于当前数值精度，无法前进。")
        yield increment
        current = target if abs(remaining) <= limit else updated
