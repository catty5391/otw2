"""Complete Steel02 parameters shared by tower construction and member studies.

The legacy member and tower factories retain their distinct historical values.
New tower-aligned studies use ``legacy_tower`` for both models.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


@dataclass(frozen=True)
class Steel02Parameters:
    E0: float
    fy: float
    b: float = 0.03
    R0: float = 20.0
    cR1: float = 0.925
    cR2: float = 0.15
    a1: float = 0.0
    a2: float = 1.0
    a3: float = 0.0
    a4: float = 1.0
    sig_init: float = 0.0

    def __post_init__(self) -> None:
        values = asdict(self)
        if not all(math.isfinite(float(value)) for value in values.values()):
            raise ValueError("Steel02 parameters must be finite")
        if min(self.E0, self.fy, self.R0, self.cR2, self.a2, self.a4) <= 0:
            raise ValueError("Steel02 modulus, strength and denominators must be positive")
        if not 0 <= self.b < 1 or min(self.a1, self.a3, self.cR1) < 0:
            raise ValueError("Invalid Steel02 hardening parameters")

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    def to_dict(self) -> dict[str, float]:
        return self.as_dict()

    def opensees_arguments(self, tag: int) -> tuple[Any, ...]:
        return ("Steel02", int(tag), self.fy, self.E0, self.b, self.R0,
                self.cR1, self.cR2, self.a1, self.a2, self.a3, self.a4, self.sig_init)

    @classmethod
    def legacy_member(cls, *, E0: float, fy: float, b: float = 0.03) -> "Steel02Parameters":
        return cls(E0=E0, fy=fy, b=b)

    @classmethod
    def legacy_tower(cls, *, E0: float, fy: float, b: float = 0.03) -> "Steel02Parameters":
        return cls(E0=E0, fy=fy, b=b, a1=0.0005, a2=0.01, a3=0.0005, a4=0.01)
