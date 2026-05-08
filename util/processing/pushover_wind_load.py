from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from util.preprocess.tag_manager import TagManager


@dataclass
class PushoverWindLoadResult:
    time_series_tag: int
    pattern_tag: int
    floor_ratios: dict[str, float]
    node_ratios: dict[int, float]
    applied_loads: dict[int, tuple[float, ...]]


class PushoverWindLoadApplier:
    """Create normalized pushover wind loads from floor wind load magnitudes."""

    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    DEFAULT_NODE_CONFIG_PATH = PROJECT_ROOT / "pushover" / ".config" / "node_to_add_wind_press.json"
    TIME_SERIES_NAMESPACE = "timeSeries"
    PATTERN_NAMESPACE = "pattern"

    def __init__(
        self,
        node_config_path: str | Path | None = None,
        tag_manager: TagManager | None = None,
        existing_tags: dict[str, Any] | None = None,
        load_dof: int = 2,
        ndf: int = 6,
        load_factor: float = 1.0,
    ) -> None:
        self.node_config_path = Path(node_config_path) if node_config_path else self.DEFAULT_NODE_CONFIG_PATH
        self.floor_to_nodes = self.load_floor_nodes(self.node_config_path)
        self.floor_order = self.sorted_floor_keys(self.floor_to_nodes)
        self.load_dof = self.normalize_dof(load_dof, ndf)
        self.ndf = int(ndf)
        self.load_factor = float(load_factor)
        self.tag_manager = tag_manager or TagManager(
            start_tag={
                self.TIME_SERIES_NAMESPACE: 1,
                self.PATTERN_NAMESPACE: 1,
            }
        )
        if existing_tags:
            self.tag_manager.initialize(existing_tags)
        self.last_result: PushoverWindLoadResult | None = None

    @staticmethod
    def load_floor_nodes(json_path: str | Path) -> dict[str, list[int]]:
        path = Path(json_path)
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict) or not data:
            raise ValueError("node config must be a non-empty object.")

        floor_to_nodes: dict[str, list[int]] = {}
        for floor_name, nodes in data.items():
            if not isinstance(nodes, list) or len(nodes) == 0:
                raise ValueError(f"{floor_name} must contain at least one node tag.")
            floor_to_nodes[str(floor_name)] = [int(node_tag) for node_tag in nodes]
        return floor_to_nodes

    @staticmethod
    def floor_index(floor_name: str) -> int:
        match = re.fullmatch(r"floor(\d+)", str(floor_name))
        if not match:
            raise ValueError(f"invalid floor name: {floor_name!r}")
        return int(match.group(1))

    @classmethod
    def sorted_floor_keys(cls, floor_to_nodes: Mapping[str, Sequence[int]]) -> list[str]:
        return sorted(floor_to_nodes, key=cls.floor_index)

    @staticmethod
    def normalize_dof(load_dof: int, ndf: int) -> int:
        dof = int(load_dof)
        ndf = int(ndf)
        if ndf < 1:
            raise ValueError("ndf must be positive.")
        if dof < 1 or dof > ndf:
            raise ValueError(f"load_dof must be in [1, {ndf}].")
        return dof

    @classmethod
    def _floor_value(cls, floor_values: Mapping[Any, float] | Sequence[float], floor_name: str) -> float:
        floor_index = cls.floor_index(floor_name)
        if isinstance(floor_values, Mapping):
            for key in (floor_name, floor_index, str(floor_index)):
                if key in floor_values:
                    return float(floor_values[key])
            raise KeyError(f"missing wind load value for {floor_name}.")
        return float(floor_values[floor_index])

    def floor_load_values(self, floor_values: Mapping[Any, float] | Sequence[float]) -> dict[str, float]:
        values: dict[str, float] = {}
        for floor_name in self.floor_order:
            value = self._floor_value(floor_values, floor_name)
            if value < 0.0:
                raise ValueError(f"{floor_name} wind load value must be non-negative.")
            values[floor_name] = value
        return values

    def floor_load_ratios(self, floor_values: Mapping[Any, float] | Sequence[float]) -> dict[str, float]:
        values = self.floor_load_values(floor_values)
        total = sum(values.values())
        if total <= 0.0:
            raise ValueError("sum of floor wind load values must be positive.")
        return {floor_name: value / total for floor_name, value in values.items()}

    def node_load_ratios(self, floor_values: Mapping[Any, float] | Sequence[float]) -> dict[int, float]:
        floor_ratios = self.floor_load_ratios(floor_values)
        node_ratios: dict[int, float] = {}
        for floor_name in self.floor_order:
            nodes = self.floor_to_nodes[floor_name]
            node_ratio = floor_ratios[floor_name] / len(nodes)
            for node_tag in nodes:
                node_ratios[int(node_tag)] = node_ratios.get(int(node_tag), 0.0) + node_ratio
        return node_ratios

    def load_vector(self, ratio: float, load_factor: float | None = None) -> tuple[float, ...]:
        factor = self.load_factor if load_factor is None else float(load_factor)
        values = [0.0] * self.ndf
        values[self.load_dof - 1] = float(ratio) * factor
        return tuple(values)

    def apply(
        self,
        floor_values: Mapping[Any, float] | Sequence[float],
        ops_module: Any | None = None,
        time_series_type: str = "Linear",
        load_factor: float | None = None,
    ) -> PushoverWindLoadResult:
        ops = self._ops_module(ops_module)
        floor_ratios = self.floor_load_ratios(floor_values)
        node_ratios: dict[int, float] = {}
        for floor_name in self.floor_order:
            nodes = self.floor_to_nodes[floor_name]
            node_ratio = floor_ratios[floor_name] / len(nodes)
            for node_tag in nodes:
                node_ratios[int(node_tag)] = node_ratios.get(int(node_tag), 0.0) + node_ratio

        time_series_tag = self.tag_manager.get_next_tag(namespace=self.TIME_SERIES_NAMESPACE)
        pattern_tag = self.tag_manager.get_next_tag(namespace=self.PATTERN_NAMESPACE)
        applied_loads = {
            node_tag: self.load_vector(ratio, load_factor=load_factor)
            for node_tag, ratio in sorted(node_ratios.items())
        }

        ops.timeSeries(time_series_type, time_series_tag)
        ops.pattern("Plain", pattern_tag, time_series_tag)
        for node_tag, load_values in applied_loads.items():
            ops.load(node_tag, *load_values)

        result = PushoverWindLoadResult(
            time_series_tag=time_series_tag,
            pattern_tag=pattern_tag,
            floor_ratios=floor_ratios,
            node_ratios=node_ratios,
            applied_loads=applied_loads,
        )
        self.last_result = result
        return result

    def apply_from_model(
        self,
        model: Any,
        theta: float = 0.0,
        ops_module: Any | None = None,
        time_series_type: str = "Linear",
        load_factor: float | None = None,
    ) -> PushoverWindLoadResult:
        return self.apply(
            model.get_area(theta=theta),
            ops_module=ops_module,
            time_series_type=time_series_type,
            load_factor=load_factor,
        )

    @staticmethod
    def remove(result: PushoverWindLoadResult, ops_module: Any | None = None) -> None:
        ops = PushoverWindLoadApplier._ops_module(ops_module)
        ops.remove("loadPattern", int(result.pattern_tag))
        ops.remove("timeSeries", int(result.time_series_tag))

    @staticmethod
    def _ops_module(ops_module: Any | None = None) -> Any:
        if ops_module is not None:
            return ops_module
        import openseespy.opensees as ops

        return ops
