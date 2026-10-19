"""Equivalent member constitutive law for initially crooked angle members.

This module intentionally models a *member*, rather than replacing the steel
constitutive law.  Length, weak-axis inertia and initial crookedness are part of
the parameters, so a material instance may only be used by the physical member
for which it was generated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import pi, sqrt
from typing import Any, Iterable, Sequence


def ec3_reduction_factor(non_dimensional_slenderness: float, alpha: float = 0.34) -> float:
    """EN 1993 Perry-type column reduction factor (curve b by default)."""

    slenderness = float(non_dimensional_slenderness)
    if slenderness <= 0.0:
        raise ValueError("无量纲长细比必须为正数。")
    phi = 0.5 * (1.0 + alpha * (slenderness - 0.2) + slenderness**2)
    discriminant = max(phi**2 - slenderness**2, 0.0)
    return min(1.0, 1.0 / (phi + sqrt(discriminant)))


def gb50017_reduction_factor(
    non_dimensional_slenderness: float,
    curve: str = "a",
) -> float:
    """GB 50017-2017 Appendix D axial-compression stability factor.

    The implemented ``a`` and ``b`` parameter groups cover the comparison used
    by this experiment.  Q345 hot-rolled equal angles use curve ``a`` according
    to the section-class table cited in the accompanying report.
    """

    parameters = {
        "a": (0.41, 0.986, 0.152),
        "b": (0.65, 0.965, 0.300),
    }
    if curve not in parameters:
        raise ValueError("本实验当前仅实现 GB 50017 的 a、b 柱曲线。")
    slenderness = float(non_dimensional_slenderness)
    if slenderness <= 0.0:
        raise ValueError("无量纲长细比必须为正数。")
    alpha1, alpha2, alpha3 = parameters[curve]
    if slenderness <= 0.215:
        return 1.0 - alpha1 * slenderness**2
    b_value = alpha2 + alpha3 * slenderness + slenderness**2
    discriminant = max(b_value**2 - 4.0 * slenderness**2, 0.0)
    return (b_value - sqrt(discriminant)) / (2.0 * slenderness**2)


@dataclass(frozen=True)
class BackbonePoint:
    """One stress-strain point; compression is negative."""

    strain: float
    stress: float


@dataclass(frozen=True)
class PushoverPoint:
    """One monotonic compression result point using positive reporting signs."""

    shortening: float
    force: float
    midspan_lateral_displacement: float = 0.0


@dataclass(frozen=True)
class MemberProperties:
    """Properties of one physical compression member in SI units."""

    name: str
    length: float
    area: float
    inertia_weak: float
    extreme_fiber_distance: float
    elastic_modulus: float
    yield_strength: float
    effective_length_factor: float = 1.0
    leg_width: float | None = None
    thickness: float | None = None

    def __post_init__(self) -> None:
        positive = {
            "length": self.length,
            "area": self.area,
            "inertia_weak": self.inertia_weak,
            "extreme_fiber_distance": self.extreme_fiber_distance,
            "elastic_modulus": self.elastic_modulus,
            "yield_strength": self.yield_strength,
            "effective_length_factor": self.effective_length_factor,
        }
        invalid = [name for name, value in positive.items() if value <= 0.0]
        if invalid:
            raise ValueError(f"构件参数必须为正数：{', '.join(invalid)}")

    @classmethod
    def z30103a6_l125x8(cls, *, length: float = 3.0) -> "MemberProperties":
        """Return the L125x8Q345 properties found in ``Source/Z30103A6.s2k``."""

        leg_width = 0.125
        thickness = 0.008
        area = 0.001936
        centroid = (
            leg_width * thickness * leg_width / 2.0
            + thickness * (leg_width - thickness) * thickness / 2.0
        ) / area
        return cls(
            name="Z30103A6-L125x8Q345",
            length=length,
            area=area,
            inertia_weak=2.96163421763085e-6 - 1.76769111570248e-6,
            extreme_fiber_distance=sqrt(2.0) * centroid,
            elastic_modulus=2.06e11,
            yield_strength=345e6,
            leg_width=leg_width,
            thickness=thickness,
        )

    @property
    def radius_of_gyration(self) -> float:
        return sqrt(self.inertia_weak / self.area)

    @property
    def slenderness_ratio(self) -> float:
        return self.effective_length_factor * self.length / self.radius_of_gyration

    @property
    def euler_load(self) -> float:
        effective_length = self.effective_length_factor * self.length
        return pi**2 * self.elastic_modulus * self.inertia_weak / effective_length**2

    @property
    def squash_load(self) -> float:
        return self.area * self.yield_strength

    @property
    def non_dimensional_slenderness(self) -> float:
        return sqrt(self.squash_load / self.euler_load)

    def to_dict(self) -> dict[str, float | str | None]:
        data = asdict(self)
        data.update(
            radius_of_gyration=self.radius_of_gyration,
            slenderness_ratio=self.slenderness_ratio,
            euler_load=self.euler_load,
            squash_load=self.squash_load,
            non_dimensional_slenderness=self.non_dimensional_slenderness,
        )
        return data


class EquivalentImperfectionMaterial:
    """Generate and register an asymmetric OpenSees ``HystereticSM`` material.

    The tension side retains an ordinary steel envelope.  The compression side
    is either obtained from a Perry-type initially crooked pin-ended member or
    sampled from a four-segment reference analysis.
    """

    def __init__(
        self,
        member: MemberProperties,
        compression_envelope: Sequence[BackbonePoint],
        *,
        source: str,
        imperfection_ratio: float | None,
    ) -> None:
        if not 2 <= len(compression_envelope) <= 7:
            raise ValueError("HystereticSM 压缩骨架必须包含 2 到 7 个点。")
        strains = [point.strain for point in compression_envelope]
        if any(point.strain >= 0.0 or point.stress >= 0.0 for point in compression_envelope):
            raise ValueError("压缩骨架的应变和应力必须均为负值。")
        if any(next_value >= value for value, next_value in zip(strains, strains[1:])):
            raise ValueError("压缩骨架应变必须严格递减。")
        self.member = member
        self.compression_envelope = tuple(compression_envelope)
        self.source = source
        self.imperfection_ratio = imperfection_ratio

    @classmethod
    def from_perry(
        cls,
        member: MemberProperties,
        *,
        imperfection_ratio: float = 1.0 / 1000.0,
        residual_strength_ratio: float = 0.25,
        ultimate_strain: float = 0.03,
    ) -> "EquivalentImperfectionMaterial":
        """Build a first-principles trial envelope from a sinusoidal crookedness.

        The pre-peak relation uses ``e=e0/(1-N/Ne)`` and includes axial
        shortening plus the change of bowed centre-line length.  Peak load is
        reached when ``N/A + N*e*c/I = fy``.  The final residual-strength point
        is an explicit modelling assumption for later calibration.
        """

        if imperfection_ratio <= 0.0:
            raise ValueError("imperfection_ratio 必须大于 0。")
        if not 0.0 < residual_strength_ratio <= 1.0:
            raise ValueError("residual_strength_ratio 应在 (0, 1] 内。")

        peak_load = cls._perry_peak_load(member, imperfection_ratio)
        fractions = (0.10, 0.30, 0.50, 0.70, 0.85, 1.00)
        envelope: list[BackbonePoint] = []
        for fraction in fractions:
            load = fraction * peak_load
            strain = cls._equivalent_compressive_strain(member, imperfection_ratio, load)
            envelope.append(BackbonePoint(strain=-strain, stress=-load / member.area))

        peak_strain = abs(envelope[-1].strain)
        final_strain = max(ultimate_strain, peak_strain * 4.0)
        envelope.append(
            BackbonePoint(
                strain=-final_strain,
                stress=-residual_strength_ratio * peak_load / member.area,
            )
        )
        return cls(
            member,
            envelope,
            source="Perry sinusoidal-imperfection trial envelope",
            imperfection_ratio=imperfection_ratio,
        )

    @classmethod
    def from_reference_curve(
        cls,
        member: MemberProperties,
        curve: Sequence[PushoverPoint],
        *,
        imperfection_ratio: float,
    ) -> "EquivalentImperfectionMaterial":
        """Sample a monotonic four-segment curve into at most seven points."""

        valid = [point for point in curve if point.shortening > 0.0 and point.force > 0.0]
        if len(valid) < 3:
            raise ValueError("参考推覆曲线至少需要 3 个有效点。")
        peak_index = max(range(len(valid)), key=lambda index: valid[index].force)
        peak_shortening = valid[peak_index].shortening
        maximum_shortening = valid[-1].shortening
        targets = [
            0.30 * peak_shortening,
            0.65 * peak_shortening,
            peak_shortening,
            min(2.0 * peak_shortening, maximum_shortening),
            min(5.0 * peak_shortening, maximum_shortening),
            min(15.0 * peak_shortening, maximum_shortening),
            maximum_shortening,
        ]
        unique_targets: list[float] = []
        for target in targets:
            if not unique_targets or target - unique_targets[-1] > 1e-12:
                unique_targets.append(target)

        envelope = [
            BackbonePoint(
                strain=-target / member.length,
                stress=-cls._interpolate_force(valid, target) / member.area,
            )
            for target in unique_targets
        ]
        return cls(
            member,
            envelope,
            source="calibrated from four-segment geometric-imperfection model",
            imperfection_ratio=imperfection_ratio,
        )

    @staticmethod
    def _interpolate_force(curve: Sequence[PushoverPoint], shortening: float) -> float:
        if shortening <= curve[0].shortening:
            return curve[0].force * shortening / curve[0].shortening
        for left, right in zip(curve, curve[1:]):
            if shortening <= right.shortening:
                ratio = (shortening - left.shortening) / (right.shortening - left.shortening)
                return left.force + ratio * (right.force - left.force)
        return curve[-1].force

    @staticmethod
    def _perry_peak_load(member: MemberProperties, imperfection_ratio: float) -> float:
        e0 = member.length * imperfection_ratio
        upper = min(member.squash_load, member.euler_load * (1.0 - 1e-10))

        def yield_function(load: float) -> float:
            total_bow = e0 / (1.0 - load / member.euler_load)
            return (
                load / member.area
                + load * total_bow * member.extreme_fiber_distance / member.inertia_weak
                - member.yield_strength
            )

        lower = 0.0
        for _ in range(100):
            middle = 0.5 * (lower + upper)
            if yield_function(middle) > 0.0:
                upper = middle
            else:
                lower = middle
        return 0.5 * (lower + upper)

    @staticmethod
    def _equivalent_compressive_strain(
        member: MemberProperties,
        imperfection_ratio: float,
        load: float,
    ) -> float:
        e0 = member.length * imperfection_ratio
        total_bow = e0 / (1.0 - load / member.euler_load)
        axial_strain = load / (member.elastic_modulus * member.area)
        bow_shortening_strain = pi**2 * (total_bow**2 - e0**2) / (4.0 * member.length**2)
        return axial_strain + bow_shortening_strain

    @property
    def peak_compressive_stress(self) -> float:
        return max(abs(point.stress) for point in self.compression_envelope)

    @property
    def peak_compressive_load(self) -> float:
        return self.peak_compressive_stress * self.member.area

    def tension_envelope(self) -> tuple[BackbonePoint, ...]:
        yield_strain = self.member.yield_strength / self.member.elastic_modulus
        return (
            BackbonePoint(0.80 * yield_strain, 0.80 * self.member.yield_strength),
            BackbonePoint(yield_strain, self.member.yield_strength),
            BackbonePoint(max(0.02, 8.0 * yield_strain), 1.02 * self.member.yield_strength),
        )

    def register_opensees(self, ops: Any, material_tag: int) -> None:
        """Create the multilinear material in the active OpenSees domain."""

        arguments: list[Any] = ["HystereticSM", material_tag, "-posEnv"]
        for point in self.tension_envelope():
            arguments.extend((point.stress, point.strain))
        arguments.append("-negEnv")
        for point in self.compression_envelope:
            arguments.extend((point.stress, point.strain))
        arguments.extend(("-pinch", 1.0, 1.0, "-damage", 0.0, 0.0, "-beta", 0.0))
        ops.uniaxialMaterial(*arguments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "imperfection_ratio": self.imperfection_ratio,
            "peak_compressive_load": self.peak_compressive_load,
            "peak_compressive_stress": self.peak_compressive_stress,
            "compression_envelope": [asdict(point) for point in self.compression_envelope],
            "tension_envelope": [asdict(point) for point in self.tension_envelope()],
        }


def curve_area(curve: Iterable[PushoverPoint]) -> float:
    """Return the trapezoidal area under a force-shortening curve."""

    points = list(curve)
    return sum(
        0.5 * (left.force + right.force) * (right.shortening - left.shortening)
        for left, right in zip(points, points[1:])
    )
