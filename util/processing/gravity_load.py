from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from util.preprocess.tag_manager import TagManager


@dataclass
class GravityLoadResult:
    time_series_tag: int
    pattern_tag: int
    direction: str
    dof: int
    factor: float
    total_mass: float
    total_load: float
    node_loads: dict[int, tuple[float, ...]]


class GravityLoadApplier:
    """Apply nodal gravity loads computed from model mass records."""

    TIME_SERIES_NAMESPACE = "timeSeries"
    PATTERN_NAMESPACE = "pattern"
    DIRECTION_TO_DOF = {"X": 1, "Y": 2, "Z": 3}
    DOF_TO_MASS_KEY = {1: "mx", 2: "my", 3: "mz"}

    def __init__(
        self,
        tag_manager: TagManager | None = None,
        existing_tags: dict[str, Any] | None = None,
        direction: str = "Z",
        factor: float = -9.81,
        ndf: int = 6,
    ) -> None:
        self.ndf = int(ndf)
        if self.ndf < 1:
            raise ValueError("ndf must be positive.")
        self.direction = self.normalize_direction(direction)
        self.dof = self.direction_to_dof(self.direction, self.ndf)
        self.factor = float(factor)
        self.tag_manager = tag_manager or TagManager(
            start_tag={
                self.TIME_SERIES_NAMESPACE: 1,
                self.PATTERN_NAMESPACE: 1,
            }
        )
        if existing_tags:
            self.tag_manager.initialize(existing_tags)
        self.last_result: GravityLoadResult | None = None

    @classmethod
    def normalize_direction(cls, direction: str) -> str:
        normalized = str(direction).upper()
        if normalized not in cls.DIRECTION_TO_DOF:
            raise ValueError("direction must be one of X, Y, Z.")
        return normalized

    @classmethod
    def direction_to_dof(cls, direction: str, ndf: int) -> int:
        dof = cls.DIRECTION_TO_DOF[cls.normalize_direction(direction)]
        if dof > int(ndf):
            raise ValueError(f"direction {direction} requires dof {dof}, but ndf={ndf}.")
        return dof

    @classmethod
    def mass_key_for_dof(cls, dof: int) -> str:
        if int(dof) not in cls.DOF_TO_MASS_KEY:
            raise ValueError("gravity load currently supports translational dof 1, 2, 3.")
        return cls.DOF_TO_MASS_KEY[int(dof)]

    @staticmethod
    def _node_tag_from_record(default_node_tag: Any, record: Any) -> int:
        if isinstance(record, Mapping) and "node_tag" in record:
            return int(record["node_tag"])
        return int(default_node_tag)

    def mass_value(self, record: Any, dof: int | None = None) -> float:
        if isinstance(record, Mapping):
            mass_key = self.mass_key_for_dof(self.dof if dof is None else int(dof))
            if mass_key in record:
                return float(record[mass_key])
            if "mass" in record:
                return float(record["mass"])
        return float(record)

    def node_load_vector(self, mass: float, factor: float | None = None) -> tuple[float, ...]:
        gravity_factor = self.factor if factor is None else float(factor)
        values = [0.0] * self.ndf
        values[self.dof - 1] = float(mass) * gravity_factor
        return tuple(values)

    def node_loads(
        self,
        mass_records: Mapping[Any, Any],
        factor: float | None = None,
    ) -> dict[int, tuple[float, ...]]:
        loads: dict[int, tuple[float, ...]] = {}
        for default_node_tag, record in mass_records.items():
            node_tag = self._node_tag_from_record(default_node_tag, record)
            mass = self.mass_value(record)
            loads[node_tag] = self.node_load_vector(mass, factor=factor)
        return loads

    def total_mass(self, mass_records: Mapping[Any, Any]) -> float:
        return sum(self.mass_value(record) for record in mass_records.values())

    def apply(
        self,
        mass_records: Mapping[Any, Any],
        ops_module: Any | None = None,
        time_series_type: str = "Linear",
        factor: float | None = None,
    ) -> GravityLoadResult:
        if not mass_records:
            raise ValueError("mass_records must not be empty.")

        ops = self._ops_module(ops_module)
        node_loads = self.node_loads(mass_records, factor=factor)
        time_series_tag = self.tag_manager.get_next_tag(namespace=self.TIME_SERIES_NAMESPACE)
        pattern_tag = self.tag_manager.get_next_tag(namespace=self.PATTERN_NAMESPACE)

        ops.timeSeries(time_series_type, time_series_tag)
        ops.pattern("Plain", pattern_tag, time_series_tag)
        for node_tag, load_values in sorted(node_loads.items()):
            ops.load(node_tag, *load_values)

        gravity_factor = self.factor if factor is None else float(factor)
        total_mass = self.total_mass(mass_records)
        result = GravityLoadResult(
            time_series_tag=time_series_tag,
            pattern_tag=pattern_tag,
            direction=self.direction,
            dof=self.dof,
            factor=gravity_factor,
            total_mass=total_mass,
            total_load=total_mass * gravity_factor,
            node_loads=node_loads,
        )
        self.last_result = result
        return result

    def apply_from_model(
        self,
        model: Any,
        ops_module: Any | None = None,
        time_series_type: str = "Linear",
        factor: float | None = None,
        call_mass_if_empty: bool = True,
    ) -> GravityLoadResult:
        mass_records = getattr(model, "mass_map", {}) or {}
        if not mass_records and call_mass_if_empty:
            mass_records = model.mass()
        return self.apply(
            mass_records,
            ops_module=ops_module,
            time_series_type=time_series_type,
            factor=factor,
        )

    @staticmethod
    def remove(result: GravityLoadResult, ops_module: Any | None = None) -> None:
        ops = GravityLoadApplier._ops_module(ops_module)
        ops.remove("loadPattern", int(result.pattern_tag))
        ops.remove("timeSeries", int(result.time_series_tag))

    @staticmethod
    def read_mass_csv(path: str | Path) -> dict[int, dict[str, float | int]]:
        import csv

        mass_records: dict[int, dict[str, float | int]] = {}
        with Path(path).open("r", newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                node_tag = int(row["node_tag"])
                mass_records[node_tag] = {
                    "node_tag": node_tag,
                    "mx": float(row["mx"]),
                    "my": float(row["my"]),
                    "mz": float(row["mz"]),
                    "mrx": float(row.get("mrx", 0.0)),
                    "mry": float(row.get("mry", 0.0)),
                    "mrz": float(row.get("mrz", 0.0)),
                }
        return mass_records

    @staticmethod
    def _ops_module(ops_module: Any | None = None) -> Any:
        if ops_module is not None:
            return ops_module
        import openseespy.opensees as ops

        return ops
