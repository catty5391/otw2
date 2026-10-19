from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent / ".config" / "conductor_catalog.json"


@dataclass(frozen=True)
class ConductorMassProperties:
    """Resolved mass properties for one modeled conductor line.

    ``subconductor_mass_per_length`` is the bare mass of one physical
    subconductor. ``mass_per_length`` and ``weight_per_length`` include all
    subconductors represented by the OpenSees line.
    """

    model: str | None
    bundle_count: int
    subconductor_mass_per_length: float
    mass_per_length: float
    weight_per_length: float
    gravity: float
    source: str
    diameter_m: float | None = None
    rated_tensile_strength_n: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_conductor_catalog(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    catalog_path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    conductors = data.get("conductors", data)
    if not isinstance(conductors, dict):
        raise ValueError(f"导线参数表必须是 JSON object: {catalog_path}")
    return {str(name): record for name, record in conductors.items() if isinstance(record, dict)}


def _finite_nonnegative(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值，当前值为 {value!r}") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} 必须是非负有限数值，当前值为 {value!r}")
    return number


def _positive_bundle_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bundle_count 必须是正整数，当前值为 {value!r}") from exc
    if count < 1 or float(value) != count:
        raise ValueError(f"bundle_count 必须是正整数，当前值为 {value!r}")
    return count


def resolve_conductor_mass(
    line_config: dict[str, Any],
    *,
    gravity: float = 9.81,
    catalog_path: str | Path | None = None,
) -> ConductorMassProperties:
    """Resolve conductor mass while retaining compatibility with legacy ``q_g``.

    Preferred configuration::

        {
          "conductor": {"model": "JL/G1A-400/50", "bundle_count": 1},
          "gravity": 9.81
        }

    Mass values inside ``conductor`` describe one physical subconductor. A
    top-level ``mass_per_length`` is interpreted as the total mass of the
    modeled line. Legacy ``q_g``/``weight_per_length`` values are total weight
    per unit length in N/m.
    """

    gravity_value = _finite_nonnegative(gravity, "gravity")
    if gravity_value == 0.0:
        raise ValueError("gravity 必须大于 0，才能在质量与自重之间换算。")

    raw_conductor = line_config.get("conductor", {})
    if isinstance(raw_conductor, str):
        conductor: dict[str, Any] = {"model": raw_conductor}
    elif isinstance(raw_conductor, dict):
        conductor = raw_conductor
    else:
        raise ValueError("conductor 必须是型号字符串或 JSON object。")

    model_value = conductor.get("model", conductor.get("type", conductor.get("name")))
    model = str(model_value) if model_value not in (None, "") else None
    bundle_count = _positive_bundle_count(
        conductor.get("bundle_count", line_config.get("bundle_count", 1))
    )

    catalog_record: dict[str, Any] = {}
    if model is not None:
        catalog = load_conductor_catalog(catalog_path)
        catalog_record = catalog.get(model, {})

    source = "none"
    per_subconductor_mass: float | None = None
    total_mass: float | None = None

    if "mass_per_length" in conductor:
        per_subconductor_mass = _finite_nonnegative(
            conductor["mass_per_length"], "conductor.mass_per_length"
        )
        source = "conductor.mass_per_length"
    elif "unit_mass_kg_per_km" in conductor:
        per_subconductor_mass = _finite_nonnegative(
            conductor["unit_mass_kg_per_km"], "conductor.unit_mass_kg_per_km"
        ) / 1000.0
        source = "conductor.unit_mass_kg_per_km"
    elif "unit_mass_kg_per_km" in catalog_record:
        per_subconductor_mass = _finite_nonnegative(
            catalog_record["unit_mass_kg_per_km"], f"catalog[{model}].unit_mass_kg_per_km"
        ) / 1000.0
        source = f"catalog:{model}"
    elif "mass_per_length" in line_config:
        total_mass = _finite_nonnegative(line_config["mass_per_length"], "mass_per_length")
        per_subconductor_mass = total_mass / bundle_count
        source = "mass_per_length"
    elif "unit_mass_kg_per_km" in line_config:
        total_mass = _finite_nonnegative(
            line_config["unit_mass_kg_per_km"], "unit_mass_kg_per_km"
        ) / 1000.0
        per_subconductor_mass = total_mass / bundle_count
        source = "unit_mass_kg_per_km"
    else:
        legacy_weight = line_config.get(
            "q_g", line_config.get("weight_per_length", line_config.get("gravity_per_length"))
        )
        if legacy_weight is not None:
            weight = _finite_nonnegative(legacy_weight, "q_g/weight_per_length")
            total_mass = weight / gravity_value
            per_subconductor_mass = total_mass / bundle_count
            source = "legacy_weight_per_length"

    if per_subconductor_mass is None:
        if model is not None:
            raise KeyError(
                f"导线参数表中没有型号 {model!r}，"
                "且配置中未提供质量或自重。"
            )
        per_subconductor_mass = 0.0
    if total_mass is None:
        total_mass = per_subconductor_mass * bundle_count
    weight_per_length = total_mass * gravity_value

    # When both the preferred mass definition and legacy q_g are retained,
    # reject material inconsistencies while tolerating rounded engineering data.
    legacy_weight = line_config.get(
        "q_g", line_config.get("weight_per_length", line_config.get("gravity_per_length"))
    )
    if legacy_weight is not None and source != "legacy_weight_per_length":
        legacy_value = _finite_nonnegative(legacy_weight, "q_g/weight_per_length")
        tolerance = max(0.05, 0.02 * max(weight_per_length, legacy_value))
        if abs(legacy_value - weight_per_length) > tolerance:
            raise ValueError(
                "导线质量与 q_g 不一致："
                f"质量换算为 {weight_per_length:.6g} N/m，q_g={legacy_value:.6g} N/m。"
            )

    diameter_mm = conductor.get("diameter_mm", catalog_record.get("diameter_mm"))
    rated_strength = conductor.get(
        "rated_tensile_strength_n", catalog_record.get("rated_tensile_strength_n")
    )
    return ConductorMassProperties(
        model=model,
        bundle_count=bundle_count,
        subconductor_mass_per_length=per_subconductor_mass,
        mass_per_length=total_mass,
        weight_per_length=weight_per_length,
        gravity=gravity_value,
        source=source,
        diameter_m=(
            None
            if diameter_mm is None
            else _finite_nonnegative(diameter_mm, "diameter_mm") / 1000.0
        ),
        rated_tensile_strength_n=(
            None
            if rated_strength is None
            else _finite_nonnegative(rated_strength, "rated_tensile_strength_n")
        ),
    )


def tributary_lengths(coords: Sequence[Sequence[float]]) -> list[float]:
    """Return nodal tributary lengths from the actual conductor polyline."""

    if len(coords) < 2:
        raise ValueError("导线至少需要两个节点坐标。")
    segment_lengths: list[float] = []
    for index in range(len(coords) - 1):
        first = tuple(float(value) for value in coords[index])
        second = tuple(float(value) for value in coords[index + 1])
        if len(first) != len(second):
            raise ValueError("相邻导线节点坐标维数不一致。")
        length = math.dist(first, second)
        if length <= 0.0:
            raise ValueError(f"导线第 {index + 1} 段长度必须大于 0。")
        segment_lengths.append(length)

    result = [0.0] * len(coords)
    result[0] = 0.5 * segment_lengths[0]
    result[-1] = 0.5 * segment_lengths[-1]
    for index in range(1, len(coords) - 1):
        result[index] = 0.5 * (segment_lengths[index - 1] + segment_lengths[index])
    return result

