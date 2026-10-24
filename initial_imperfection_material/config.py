"""Serializable, fingerprinted calibration settings (SI units).

This module describes what a solver actually uses; a configuration is not a
claim that a mechanical model or its calibration has passed validation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


CONFIG_SCHEMA = "otw2.calibration_config.v2"


def canonical_json(value: Any) -> str:
    """Reject NaN/Infinity and produce a stable, UTF-8 JSON representation."""

    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def positive_finite(value: float, name: str, *, allow_zero: bool = False) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{name} must be finite and {'nonnegative' if allow_zero else 'positive'}")
    return number


def positive_integer(value: int, name: str) -> int:
    if isinstance(value, bool) or not math.isfinite(float(value)) or int(value) != value or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def grouped_length(length: float, bin_width: float) -> float:
    """Preserve the historical Python round rule, including binary-float ties."""

    length = positive_finite(length, "length")
    bin_width = positive_finite(bin_width, "length_bin")
    grouped = round(length / bin_width) * bin_width
    return positive_finite(grouped, "grouped_length (choose a smaller bin)")


@dataclass(frozen=True)
class ReferenceSolverConfig:
    test_type: str = "NormDispIncr"
    tolerance: float = 1e-8
    max_iterations: int = 100
    algorithm: tuple[Any, ...] = ("Newton",)
    retry_tolerance: float = 1e-8
    retry_iterations: int = 250
    retry_algorithm: tuple[Any, ...] = ("NewtonLineSearch", 0.8)

    def __post_init__(self) -> None:
        positive_finite(self.tolerance, "tolerance")
        positive_finite(self.retry_tolerance, "retry_tolerance")
        positive_integer(self.max_iterations, "max_iterations")
        positive_integer(self.retry_iterations, "retry_iterations")
        if not self.test_type or not self.algorithm or not self.retry_algorithm:
            raise ValueError("test_type and algorithms cannot be empty")
        canonical_json(asdict(self))

    @classmethod
    def legacy(cls) -> "ReferenceSolverConfig":
        """Explicitly reproduce the old 1e-7 retry tolerance."""

        return cls(retry_tolerance=1e-7)

    @property
    def relaxes_tolerance(self) -> bool:
        return self.retry_tolerance > self.tolerance

    def to_dict(self) -> dict[str, Any]:
        return json.loads(canonical_json({**asdict(self),
                                         "relaxes_tolerance": self.relaxes_tolerance}))


@dataclass(frozen=True)
class AnalysisConfig:
    """Six explicit configuration blocks; all fields participate in identity.

    Blocks are JSON snapshots, not arbitrary executable callbacks. Steel is a
    mapping from source material name to complete Steel02Parameters dictionaries.
    """

    model: Mapping[str, Any]
    steel: Mapping[str, Mapping[str, Any]]
    boundary: Mapping[str, Any]
    protocol: Mapping[str, Any]
    solver: Mapping[str, Any]
    calibration: Mapping[str, Any]
    schema: str = CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CONFIG_SCHEMA:
            raise ValueError(f"unsupported configuration schema: {self.schema}")
        for block in ("model", "steel", "boundary", "protocol", "solver", "calibration"):
            data = getattr(self, block)
            if not isinstance(data, Mapping) or not data:
                raise ValueError(f"{block} must be a nonempty mapping")
            object.__setattr__(self, block, json.loads(canonical_json(dict(data))))
        for name, material in self.steel.items():
            required = ("E0", "fy", "b", "R0", "cR1", "cR2", "a1", "a2", "a3", "a4", "sig_init")
            missing = set(required).difference(material)
            if missing:
                raise ValueError(f"steel {name} missing parameters: {sorted(missing)}")
            for key in ("E0", "fy", "R0", "a2", "a4"):
                positive_finite(material[key], f"{name}.{key}")
            for key in ("b", "cR1", "cR2", "a1", "a3"):
                positive_finite(material[key], f"{name}.{key}", allow_zero=True)
        if self.calibration.get("method") not in {"reference", "perry"}:
            raise ValueError("calibration.method must be reference or perry")
        if self.calibration.get("fallback_policy") not in {"error", "perry_exploratory"}:
            raise ValueError("fallback_policy must be error or perry_exploratory")

    def to_dict(self) -> dict[str, Any]:
        return json.loads(canonical_json(asdict(self)))

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())

