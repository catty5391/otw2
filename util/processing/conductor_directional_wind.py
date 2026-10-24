"""Direction-aware, SI-unit conductor wind loads without OpenSees side effects.

The angle is the direction **towards which** air moves: 0 degrees is global
+X, 90 degrees is global +Y.  A straight line parallel to Y therefore receives
its largest normal drag at 0 degrees.  These are wind forces only; this module
does not change mass, gravity, form finding, or initial tension.

Two mutually exclusive representations of a physical span are provided:

* ``explicit_conductor_loads`` distributes normal drag on a fixed polyline;
* ``equivalent_attachment_loads`` places the straight-line wind-span force at
  one attachment.  Its ``wind_span_m`` is a tributary length, not necessarily a
  complete span (use ``wind_span_from_adjacent`` for two half spans).

The straight-line sin-squared law is described, for example, by Cai et al.,
formula (31) and the paragraph following it in the publicly available paper:
https://vibcon.tongji.edu.cn/Upload/file/20220216/202202162058006832578.pdf
The implementation uses its vector normal-drag form, f = rho Cd d |v_perp|
v_perp / 2, per unit *actual conductor length*.  This assumes independent
subconductors (no bundle shielding), neglects tangential skin friction and
lift, and is not a galloping/aeroelastic model.  For sagged lines even a wind
parallel to the horizontal chord can have nonzero local normal drag.

The geometry supplied by the caller is fixed for this load evaluation.  There
is no structural-relative-velocity aerodynamic damping, follower-force update,
gust factor, or height profile hidden in this module.  Segment-specific wind
speeds may be supplied explicitly.  Existing structural damping is untouched.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Vector3 = tuple[float, float, float]
NodalLoad = tuple[float, float, float, float, float, float]
ZERO: Vector3 = (0.0, 0.0, 0.0)
ZERO_LOAD: NodalLoad = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
ANGLE_CONVENTION = "degrees; wind towards; 0=global +X, 90=global +Y"


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number, not bool")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number <= 0.0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonnegative(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number < 0.0:
        raise ValueError(f"{name} must be nonnegative")
    return number


def _vector(value: Sequence[float], name: str) -> Vector3:
    if len(value) != 3:
        raise ValueError(f"{name} must have three components")
    return tuple(_finite(item, f"{name}[{index}]") for index, item in enumerate(value))  # type: ignore[return-value]


def _tag(value: Any) -> int:
    number = _positive(value, "node_tag")
    if not number.is_integer():
        raise ValueError("node_tag must be a positive integer")
    return int(number)


def _span_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("span_id must be a nonempty string identifying a physical span")
    return value


def _add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a: Vector3, factor: float) -> Vector3:
    return (a[0] * factor, a[1] * factor, a[2] * factor)


def _dot(a: Vector3, b: Vector3) -> float:
    return math.fsum(x * y for x, y in zip(a, b))


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sum_vectors(vectors: Sequence[Vector3]) -> Vector3:
    return tuple(math.fsum(v[index] for v in vectors) for index in range(3))  # type: ignore[return-value]


def _load(force: Vector3) -> NodalLoad:
    return (*force, 0.0, 0.0, 0.0)


def _add_loads(a: NodalLoad, b: NodalLoad) -> NodalLoad:
    return tuple(x + y for x, y in zip(a, b))  # type: ignore[return-value]


def horizontal_wind_direction(wind_angle_deg: float) -> Vector3:
    """Unit wind-flow vector, using degrees rather than the old radian API."""
    angle = math.radians(_finite(wind_angle_deg, "wind_angle_deg") % 360.0)
    # Exact cardinal directions avoid a tiny fictitious parallel-line force.
    components = (math.cos(angle), math.sin(angle), 0.0)
    return tuple(0.0 if abs(item) < 1.0e-14 else item for item in components)  # type: ignore[return-value]


@dataclass(frozen=True)
class ConductorAerodynamics:
    """One physical subconductor's diameter, with an explicit bundle multiplier.

    ``diameter_m`` is NOT sqrt(4 * metallic_area / pi): the catalog's outside
    diameter is required.  Coefficient and density have no implicit defaults.
    Diameters above one metre are rejected as a probable mm/m input mistake in
    this transmission-line application.  Bundle shielding is not represented.
    """

    diameter_m: float
    drag_coefficient: float
    air_density: float
    bundle_count: int = 1

    def __post_init__(self) -> None:
        diameter = _positive(self.diameter_m, "diameter_m")
        if diameter > 1.0:
            raise ValueError("diameter_m exceeds 1 m; supply outside diameter in metres, not millimetres")
        drag = _positive(self.drag_coefficient, "drag_coefficient")
        density = _positive(self.air_density, "air_density")
        count = _positive(self.bundle_count, "bundle_count")
        if not count.is_integer():
            raise ValueError("bundle_count must be a positive integer")
        object.__setattr__(self, "diameter_m", diameter)
        object.__setattr__(self, "drag_coefficient", drag)
        object.__setattr__(self, "air_density", density)
        object.__setattr__(self, "bundle_count", int(count))

    @property
    def force_factor(self) -> float:
        """Factor multiplying |v_perp| v_perp to obtain force per length."""
        return 0.5 * self.air_density * self.drag_coefficient * self.diameter_m * self.bundle_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "diameter_m": self.diameter_m,
            "drag_coefficient": self.drag_coefficient,
            "air_density_kg_per_m3": self.air_density,
            "bundle_count": self.bundle_count,
            "bundle_shielding_included": False,
        }


@dataclass(frozen=True)
class SegmentWindLoad:
    span_id: str
    segment_index: int
    node_i: int
    node_j: int
    length_m: float
    tangent: Vector3
    wind_velocity_m_s: Vector3
    normal_velocity_m_s: Vector3
    application_point_m: Vector3
    force_n: Vector3

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ConductorWindLoads:
    """A load plan, not an applied OpenSees pattern.

    ``nodal_forces`` holds OpenSees-compatible six-tuples (Fx, Fy, Fz, Mx, My,
    Mz), with N and N m units; all nodal couples are zero for conductor drag.
    Use ``combine_conductor_loads`` before applying several plans.  It rejects
    any repeated physical span ID, including explicit/equivalent duplication.
    No global registry is used, so independent wind-angle cases stay isolated.
    """

    mode: str
    span_ids: tuple[str, ...]
    wind_angle_deg: float
    nodal_forces: dict[int, NodalLoad]
    node_coordinates: dict[int, Vector3]
    reference_origin: Vector3
    target_force: Vector3
    target_moment: Vector3
    segments: tuple[SegmentWindLoad, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_force(self) -> Vector3:
        return _sum_vectors([load[:3] for load in self.nodal_forces.values()])

    @property
    def total_moment(self) -> Vector3:
        return _sum_vectors([
            _add(_cross(_sub(self.node_coordinates[tag], self.reference_origin), load[:3]), load[3:])
            for tag, load in self.nodal_forces.items()
        ])

    def audit(self) -> dict[str, Any]:
        return {
            "target_force_n": self.target_force,
            "nodal_force_n": self.total_force,
            "force_residual_n": _sub(self.total_force, self.target_force),
            "target_moment_nm": self.target_moment,
            "nodal_moment_nm": self.total_moment,
            "moment_residual_nm": _sub(self.total_moment, self.target_moment),
            "reference_origin_m": self.reference_origin,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "span_ids": self.span_ids,
            "wind_angle_deg": self.wind_angle_deg,
            "angle_convention": ANGLE_CONVENTION,
            "nodal_loads_n_nm": self.nodal_forces,
            "nodal_load_components": ["Fx_N", "Fy_N", "Fz_N", "Mx_Nm", "My_Nm", "Mz_Nm"],
            "node_coordinates_m": self.node_coordinates,
            "segments": [segment.to_dict() for segment in self.segments],
            "audit": self.audit(),
            "metadata": self.metadata,
        }


def _normal_velocity(wind: Vector3, tangent: Vector3) -> Vector3:
    normal = _sub(wind, _scale(tangent, _dot(wind, tangent)))
    # Cancellation for exactly parallel oblique vectors is numerical, not drag.
    if math.sqrt(_dot(normal, normal)) <= 1.0e-14 * math.sqrt(_dot(wind, wind)):
        return ZERO
    return normal


def _speeds(value: float | Sequence[float], count: int) -> list[float]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != count:
            raise ValueError("wind_speed_m_s sequence must contain one speed per segment")
        return [_nonnegative(item, "wind_speed_m_s") for item in value]
    return [_nonnegative(value, "wind_speed_m_s")] * count


def explicit_conductor_loads(
    line_id: str,
    node_tags: Sequence[int],
    coordinates: Sequence[Sequence[float]],
    *,
    wind_speed_m_s: float | Sequence[float],
    wind_angle_deg: float,
    aerodynamics: ConductorAerodynamics,
    reference_origin: Sequence[float] = ZERO,
) -> ConductorWindLoads:
    """Distribute each segment's uniform drag equally to its two end nodes.

    Actual 3D segment lengths and tangents are used.  This preserves each
    segment's force and moment exactly (up to floating-point arithmetic).
    Supplying one speed per segment permits an explicit height profile without
    silently reapplying a gust factor or aerodynamic damping model.
    """
    span_id = _span_id(line_id)
    if len(node_tags) < 2 or len(node_tags) != len(coordinates):
        raise ValueError("node_tags and coordinates must have equal length, at least two")
    tags = [_tag(tag) for tag in node_tags]
    if len(set(tags)) != len(tags):
        raise ValueError("a conductor polyline must not repeat node tags")
    coords = [_vector(coord, "coordinate") for coord in coordinates]
    origin = _vector(reference_origin, "reference_origin")
    angle = _finite(wind_angle_deg, "wind_angle_deg") % 360.0
    direction = horizontal_wind_direction(angle)
    speeds = _speeds(wind_speed_m_s, len(tags) - 1)
    if not isinstance(aerodynamics, ConductorAerodynamics):
        raise TypeError("aerodynamics must be ConductorAerodynamics")
    nodal = {tag: ZERO_LOAD for tag in tags}
    segments: list[SegmentWindLoad] = []
    moments: list[Vector3] = []
    for index, (first, second) in enumerate(zip(coords, coords[1:])):
        delta = _sub(second, first)
        length = math.sqrt(_dot(delta, delta))
        if length <= 0.0:
            raise ValueError(f"segment {index} has zero length")
        tangent = _scale(delta, 1.0 / length)
        wind = _scale(direction, speeds[index])
        normal = _normal_velocity(wind, tangent)
        normal_speed = math.sqrt(_dot(normal, normal))
        force = _scale(normal, aerodynamics.force_factor * normal_speed * length)
        midpoint = _scale(_add(first, second), 0.5)
        nodal[tags[index]] = _add_loads(nodal[tags[index]], _load(_scale(force, 0.5)))
        nodal[tags[index + 1]] = _add_loads(nodal[tags[index + 1]], _load(_scale(force, 0.5)))
        moments.append(_cross(_sub(midpoint, origin), force))
        segments.append(SegmentWindLoad(
            span_id, index, tags[index], tags[index + 1], length, tangent,
            wind, normal, midpoint, force,
        ))
    return ConductorWindLoads(
        mode="explicit",
        span_ids=(span_id,),
        wind_angle_deg=angle,
        nodal_forces=nodal,
        node_coordinates=dict(zip(tags, coords)),
        reference_origin=origin,
        target_force=_sum_vectors([segment.force_n for segment in segments]),
        target_moment=_sum_vectors(moments),
        segments=tuple(segments),
        metadata={
            "aerodynamics": aerodynamics.to_dict(),
            "actual_conductor_length_m": math.fsum(segment.length_m for segment in segments),
            "geometry": "fixed supplied 3D polyline",
            "normal_drag_only": True,
            "structural_relative_velocity_included": False,
            "follower_force_update_included": False,
            "mass_gravity_initial_tension_changed": False,
        },
    )


def wind_span_from_adjacent(left_span_m: float, right_span_m: float) -> float:
    """Return (left + right) / 2; either side may be zero at a dead end."""
    left = _nonnegative(left_span_m, "left_span_m")
    right = _nonnegative(right_span_m, "right_span_m")
    if left + right <= 0.0:
        raise ValueError("at least one adjacent span must be positive")
    return 0.5 * (left + right)


def equivalent_attachment_loads(
    span_id: str,
    node_tag: int,
    coordinate: Sequence[float],
    *,
    wind_span_m: float,
    wind_speed_m_s: float,
    wind_angle_deg: float,
    aerodynamics: ConductorAerodynamics,
    line_azimuth_deg: float = 90.0,
    source_span_ids: Sequence[str] | None = None,
    reference_origin: Sequence[float] = ZERO,
) -> ConductorWindLoads:
    """Straight-horizontal-line normal drag lumped at one tower attachment.

    At line_azimuth_deg=90 the force is q Cd d Lwind cos(alpha)|cos(alpha)|
    in X (not q Cd d Lwind cos^2(alpha) subsequently rotated along the wind).
    A general horizontal line azimuth is supported using normal projection.

    The wind span is explicitly supplied: for adjacent horizontal spans use
    (Lleft + Lright)/2.  ``source_span_ids`` identifies *both* physical spans
    represented by such an attachment, so merging with explicit loads on either
    span is rejected.  No sag, insulator motion, vertical gravity reaction, or
    dynamic tension transfer is reproduced by this reduced representation.
    """
    label = _span_id(span_id)
    sources = (label,) if source_span_ids is None else tuple(_span_id(item) for item in source_span_ids)
    if not sources or len(set(sources)) != len(sources):
        raise ValueError("source_span_ids must be nonempty and unique")
    tag = _tag(node_tag)
    coord = _vector(coordinate, "coordinate")
    origin = _vector(reference_origin, "reference_origin")
    length = _positive(wind_span_m, "wind_span_m")
    speed = _nonnegative(wind_speed_m_s, "wind_speed_m_s")
    angle = _finite(wind_angle_deg, "wind_angle_deg") % 360.0
    line_angle = _finite(line_azimuth_deg, "line_azimuth_deg") % 360.0
    tangent = horizontal_wind_direction(line_angle)
    normal = _normal_velocity(_scale(horizontal_wind_direction(angle), speed), tangent)
    if not isinstance(aerodynamics, ConductorAerodynamics):
        raise TypeError("aerodynamics must be ConductorAerodynamics")
    force = _scale(normal, aerodynamics.force_factor * math.sqrt(_dot(normal, normal)) * length)
    return ConductorWindLoads(
        mode="equivalent_attachment",
        span_ids=sources,
        wind_angle_deg=angle,
        nodal_forces={tag: _load(force)},
        node_coordinates={tag: coord},
        reference_origin=origin,
        target_force=force,
        target_moment=_cross(_sub(coord, origin), force),
        metadata={
            "attachment_id": label,
            "wind_span_m": length,
            "line_azimuth_deg": line_angle,
            "aerodynamics": aerodynamics.to_dict(),
            "geometry": "straight horizontal tributary wind span, reduced to attachment",
            "normal_drag_only": True,
            "structural_relative_velocity_included": False,
            "follower_force_update_included": False,
            "mass_gravity_initial_tension_changed": False,
            "not_equivalent_to_dynamic_coupled_conductor": True,
        },
    )


def conductor_loads_from_model(
    model: Any,
    line_id: str,
    *,
    wind_speed_m_s: float | Sequence[float],
    wind_angle_deg: float,
    drag_coefficient: float,
    air_density: float,
    diameter_m: float | None = None,
    bundle_count: int | None = None,
    reference_origin: Sequence[float] = ZERO,
) -> ConductorWindLoads:
    """Read a built TowerLineSystemModel's maps, without invoking OpenSees.

    ``transmission_line_map[line_id]['conductor']['diameter_m']`` is the already
    resolved outside diameter in metres.  Missing diameter is an error; neither
    equivalent axial area nor mass is converted into an aerodynamic diameter.
    Coordinates come from ``node_map`` (fixed reference geometry), not current
    deformed positions.  Overrides are explicit and recorded for reproducibility.
    """
    line_id = _span_id(line_id)
    try:
        line = model.transmission_line_map[line_id]
    except (AttributeError, KeyError) as exc:
        raise KeyError(f"model has no built transmission line {line_id!r}") from exc
    conductor = line.get("conductor", {})
    if not isinstance(conductor, Mapping):
        raise ValueError("resolved conductor properties must be a mapping")
    resolved_diameter = conductor.get("diameter_m") if diameter_m is None else diameter_m
    if resolved_diameter is None:
        raise ValueError("outside diameter_m is missing; supply an explicit SI diameter")
    resolved_bundle = conductor.get("bundle_count", 1) if bundle_count is None else bundle_count
    aerodynamics = ConductorAerodynamics(resolved_diameter, drag_coefficient, air_density, resolved_bundle)
    tags = line.get("node_tags", [])
    coordinates = []
    for raw_tag in tags:
        tag = _tag(raw_tag)
        try:
            node = model.node_map[tag]
            coordinates.append((node["x"], node["y"], node["z"]))
        except (AttributeError, KeyError) as exc:
            raise KeyError(f"missing node coordinate for conductor node {tag}") from exc
    result = explicit_conductor_loads(
        line_id, tags, coordinates, wind_speed_m_s=wind_speed_m_s,
        wind_angle_deg=wind_angle_deg, aerodynamics=aerodynamics,
        reference_origin=reference_origin,
    )
    result.metadata["model_adapter"] = {
        "line_id": line_id,
        "diameter_source": "resolved conductor metadata" if diameter_m is None else "explicit override",
        "bundle_count_source": "resolved conductor metadata" if bundle_count is None else "explicit override",
        "model_maps_modified": False,
    }
    return result


def combine_conductor_loads(
    *plans: ConductorWindLoads,
    reference_origin: Sequence[float] = ZERO,
) -> ConductorWindLoads:
    """Merge load plans, refusing duplicate physical spans in any representation.

    Distinct spans may meet at a shared node: their nodal forces are accumulated.
    A repeated span is rejected even if both plans use the same mode.  This strict
    guard is intended for one-tower loading; representing two attachments of a
    complete span by two reduced plans is deliberately not supported here.
    """
    if not plans:
        raise ValueError("at least one conductor load plan is required")
    if any(not isinstance(plan, ConductorWindLoads) for plan in plans):
        raise TypeError("plans must be ConductorWindLoads")
    origin = _vector(reference_origin, "reference_origin")
    angle = plans[0].wind_angle_deg
    used: set[str] = set()
    coords: dict[int, Vector3] = {}
    nodal: dict[int, NodalLoad] = {}
    forces: list[Vector3] = []
    moments: list[Vector3] = []
    for plan in plans:
        if not isinstance(plan, ConductorWindLoads):
            raise TypeError("plans must be ConductorWindLoads")
        difference = (plan.wind_angle_deg - angle + 180.0) % 360.0 - 180.0
        if abs(difference) > 1.0e-10:
            raise ValueError("all plans in one load case must use the same wind_angle_deg")
        overlap = used.intersection(plan.span_ids)
        if overlap:
            raise ValueError(
                "duplicate physical span loading (explicit and equivalent modes are mutually exclusive): "
                + ", ".join(sorted(overlap))
            )
        used.update(plan.span_ids)
        for tag, force in plan.nodal_forces.items():
            coord = plan.node_coordinates[tag]
            if tag in coords and coords[tag] != coord:
                raise ValueError(f"shared node {tag} has inconsistent coordinates")
            coords[tag] = coord
            nodal[tag] = _add_loads(nodal.get(tag, ZERO_LOAD), force)
        forces.append(plan.target_force)
        moments.append(_add(
            plan.target_moment,
            _cross(_sub(plan.reference_origin, origin), plan.target_force),
        ))
    return ConductorWindLoads(
        mode="combined",
        span_ids=tuple(sorted(used)),
        wind_angle_deg=angle,
        nodal_forces=nodal,
        node_coordinates=coords,
        reference_origin=origin,
        target_force=_sum_vectors(forces),
        target_moment=_sum_vectors(moments),
        segments=tuple(segment for plan in plans for segment in plan.segments),
        metadata={
            "representation_guard": "all physical span IDs must be disjoint",
            "component_modes": [plan.mode for plan in plans],
            "component_metadata": [plan.metadata for plan in plans],
            "mass_gravity_initial_tension_changed": False,
        },
    )
