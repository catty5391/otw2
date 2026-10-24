"""Validate wind histories before constructing Path loads or running a tower."""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def read_numeric_series(path: str | Path) -> tuple[float, ...]:
    path = Path(path)
    values = []
    with path.open(encoding="utf-8-sig", newline="") as file:
        for line, row in enumerate(csv.reader(file), start=1):
            if not row or (len(row) == 1 and not row[0].strip()):
                continue
            try:
                if len(row) != 1:
                    raise ValueError("需要单列数据")
                value = float(row[0])
                if not math.isfinite(value):
                    raise ValueError("数据不能包含 NaN/Inf")
            except ValueError as error:
                raise ValueError(f"{path}:{line}: 无效数值记录 ({error})") from error
            values.append(value)
    if not values:
        raise ValueError(f"数据文件为空: {path}")
    return tuple(values)


@dataclass(frozen=True)
class TimeGrid:
    times: tuple[float, ...]
    dt: float

    @property
    def nsteps(self) -> int:
        return len(self.times) - 1

    @property
    def duration(self) -> float:
        return self.times[-1] - self.times[0]

    @classmethod
    def from_values(cls, values: Iterable[float], *, require_zero: bool = True) -> "TimeGrid":
        times = tuple(float(t) for t in values)
        if len(times) < 2 or not all(math.isfinite(t) for t in times):
            raise ValueError("时间序列至少需要两个有限时间点。")
        if require_zero and abs(times[0]) > 1e-10:
            raise ValueError("当前 Path 荷载要求时间序列从 0 开始。")
        dt = times[1] - times[0]
        if dt <= 0:
            raise ValueError("时间必须严格递增。")
        for index, (left, right) in enumerate(zip(times, times[1:]), start=1):
            delta = right - left
            if delta <= 0:
                raise ValueError(f"时间必须严格递增，第 {index + 1} 点重复或倒序。")
            if not math.isclose(delta, dt, rel_tol=1e-8, abs_tol=1e-10):
                raise ValueError(f"时间不等间隔，第 {index + 1} 点间隔 {delta}，预期 {dt}。")
        return cls(times, dt)

    @classmethod
    def from_csv(cls, path: str | Path, *, require_zero: bool = True) -> "TimeGrid":
        return cls.from_values(read_numeric_series(path), require_zero=require_zero)


def validate_wind_sample(
    sample_dir: str | Path,
    node_config: Mapping[str, Iterable[int]],
    *,
    available_nodes: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Check time alignment, every floor history, and optional model node tags.

    A node may belong to two adjacent floors; duplicates *inside* a floor are
    rejected because they would alter its load distribution.
    """
    directory = Path(sample_dir)
    grid = TimeGrid.from_csv(directory / "t.csv")
    if not node_config:
        raise ValueError("风荷载节点配置不能为空。")
    known = None if available_nodes is None else set(available_nodes)
    channels = {}
    for floor, raw_nodes in node_config.items():
        if not re.fullmatch(r"floor\d+", floor):
            raise ValueError(f"非法楼层名称: {floor}")
        nodes = tuple(raw_nodes)
        if not nodes or any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in nodes):
            raise ValueError(f"{floor} 节点必须为非空正整数序列。")
        if len(nodes) != len(set(nodes)):
            raise ValueError(f"{floor} 内存在重复节点。")
        if known is not None and set(nodes) - known:
            raise ValueError(f"{floor} 的节点不在模型中: {sorted(set(nodes) - known)}")
        values = read_numeric_series(directory / f"{floor}_wind_press.csv")
        if len(values) != len(grid.times):
            raise ValueError(f"{floor} 荷载数 {len(values)} 与时间点数 {len(grid.times)} 不一致。")
        channels[floor] = {
            "count": len(values), "minimum": min(values), "maximum": max(values),
            "rms": math.sqrt(sum(v * v for v in values) / len(values)), "nodes": list(nodes),
        }
    return {"dt": grid.dt, "nsteps": grid.nsteps, "duration": grid.duration,
            "time_points": len(grid.times), "channels": channels}
