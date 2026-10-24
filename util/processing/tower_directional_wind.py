"""Auditable single-tower directional loads, independent of the FE domain.

Angles are degrees, measured from global +X towards +Y, and denote where the
air flows *towards*.  The application uses X across the transmission line and
Y along it.  This module does not turn meteorological ``from`` directions into
structural angles, infer aerodynamic coefficients, or generate turbulence.

Two orthogonal *member-assigned* solid areas are required.  Verified external
areas may be supplied, or the caller may explicitly select the uncalibrated
``angle_leg_uniform_breadth_proxy``.  The latter sums projections of ALL physical
members, treating the angle leg as a uniform rod breadth.  It is NOT the area
of a single tower face, the true silhouette of an angle section, or a shielding
model.  Single-face code coefficients cannot be silently reused with it.

The yaw interpolation is F=q G [1+k sin²(2a)] [Cx Ax cos²(a)+Cy Ay sin²(a)].
All coefficients, k, height factors and their provenance must be supplied.
The force is assumed along the wind, without independent aerodynamic lift or
torque.  Its spatial eccentricity is retained: there is no recentering of loads.
Clipped member pieces are loaded at their midpoints, then distributed by linear
shape functions to the ORIGINAL endpoints.  This preserves force and moment,
including crossarm-local loading, but is not a beam consistent-load vector.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import cos, fsum, isfinite, radians, sin, sqrt
from typing import Any


Vector3 = tuple[float, float, float]
Load6 = tuple[float, float, float, float, float, float]
PROXY_AREA_BASIS = "angle_leg_uniform_breadth_proxy"
PROVIDED_AREA_BASIS = "provided_member_projected_areas"


def _finite(value: float, name: str, *, nonnegative: bool = False) -> float:
    number = float(value)
    if not isfinite(number) or (nonnegative and number < 0):
        raise ValueError(f"{name} must be finite" + (" and nonnegative" if nonnegative else ""))
    return number


def _xyz(value: Sequence[float] | Mapping[str, Any], name: str) -> Vector3:
    if isinstance(value, Mapping):
        value = (value["x"], value["y"], value["z"])
    if len(value) != 3:
        raise ValueError(f"{name} must have three coordinates")
    return tuple(_finite(x, name) for x in value)  # type: ignore[return-value]


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


@dataclass(frozen=True)
class TowerWindMember:
    """Whole-physical-member areas, distributed uniformly along that member."""

    tag: int
    node_i: int
    node_j: int
    area_x_m2: float
    area_y_m2: float
    region: str = "all_members"
    section_name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "area_x_m2", _finite(self.area_x_m2, "area_x_m2", nonnegative=True))
        object.__setattr__(self, "area_y_m2", _finite(self.area_y_m2, "area_y_m2", nonnegative=True))
        if not isinstance(self.region, str) or not self.region.strip():
            raise ValueError("region must be a nonempty string")


@dataclass(frozen=True)
class TowerWindGeometry:
    nodes: Mapping[int, Vector3 | Mapping[str, Any]]
    members: tuple[TowerWindMember, ...]
    origin: Vector3
    area_basis: str
    area_provenance: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TowerWindCoefficients:
    coefficient_x: float
    coefficient_y: float
    yaw_gain: float
    provenance: str

    def __post_init__(self) -> None:
        for name in ("coefficient_x", "coefficient_y", "yaw_gain"):
            object.__setattr__(self, name, _finite(getattr(self, name), name, nonnegative=True))
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("coefficient provenance must be supplied explicitly")


@dataclass(frozen=True)
class TowerWindLoadResult:
    applied_loads: dict[int, Load6]
    panels: tuple[dict[str, Any], ...]
    segments: tuple[dict[str, Any], ...]
    summary: dict[str, Any]

    @property
    def nodal_forces(self) -> dict[int, Load6]:
        """Alias shared with other directional-load adapters."""
        return self.applied_loads


def geometry_from_model(
    model: Any,
    *,
    area_basis: str,
    area_provenance: str,
    member_projected_areas: Mapping[int, Sequence[float]] | None = None,
    member_regions: Mapping[int, str] | None = None,
) -> TowerWindGeometry:
    """Read original S2K members without building or querying an FE domain.

    ``member_projected_areas`` maps ORIGINAL/global physical member tags to
    (Ax, Ay), not subdivision element tags.  The supplied areas must use the
    same basis as the aerodynamic coefficients used later.  Proxy width is
    the equal angle leg b, with Ax=b*sqrt(dy²+dz²), Ay=b*sqrt(dx²+dz²).
    Nothing in the adapter proves that supplied areas or coefficients have
    been physically validated.
    """
    if area_basis not in (PROXY_AREA_BASIS, PROVIDED_AREA_BASIS):
        raise ValueError("select an explicit supported area_basis")
    if not isinstance(area_provenance, str) or not area_provenance.strip():
        raise ValueError("area_provenance must be supplied explicitly")
    if area_basis == PROXY_AREA_BASIS and member_projected_areas is not None:
        raise ValueError("proxy areas and supplied areas must not be mixed")
    if area_basis == PROVIDED_AREA_BASIS and member_projected_areas is None:
        raise ValueError("provided_member_projected_areas requires member_projected_areas")
    raw_nodes = model._parse_node_coordinates()
    nodes = {int(tag): _xyz(record, f"node {tag}") for tag, record in raw_nodes.items()}
    connectivity = model._parse_element_connectivity()
    assignments = model._element_section_assignments()
    members: list[TowerWindMember] = []
    if member_projected_areas is not None and set(member_projected_areas) != set(connectivity):
        raise ValueError("member_projected_areas must cover exactly the original physical members")
    if member_regions is not None and set(member_regions) - set(connectivity):
        raise ValueError("member_regions contains unknown physical member tags")
    for tag, record in sorted(connectivity.items()):
        node_i, node_j = int(record["node_i"]), int(record["node_j"])
        section_name = str(assignments[tag]["section_name"])
        if area_basis == PROXY_AREA_BASIS:
            leg, _ = model._l_section_dimensions(section_name)
            leg = _finite(leg, "angle leg breadth", nonnegative=True)
            if leg == 0:
                raise ValueError("angle leg breadth must be positive")
            dx, dy, dz = (nodes[node_j][k] - nodes[node_i][k] for k in range(3))
            ax, ay = leg * sqrt(dy * dy + dz * dz), leg * sqrt(dx * dx + dz * dz)
        else:
            assert member_projected_areas is not None
            values = member_projected_areas[tag]
            if len(values) != 2:
                raise ValueError("each supplied member area must be (Ax, Ay)")
            ax, ay = float(values[0]), float(values[1])
        members.append(TowerWindMember(int(tag), node_i, node_j, ax, ay,
                                      (member_regions or {}).get(tag, "all_members"), section_name))
    warnings = (
        "uncalibrated_memberwise_sum: all physical member projections are summed; "
        "overlap and aerodynamic shielding are not deducted",
        "uniform_angle_leg_breadth_is_not_verified_angle_section_silhouette",
        "single_face_coefficients_must_not_be_reused_without_area_basis_conversion",
    ) if area_basis == PROXY_AREA_BASIS else (
        "externally_supplied_areas_and_coefficients_require_independent_validation",
    )
    return TowerWindGeometry(nodes, tuple(members), _xyz(model.origin, "origin"),
                             area_basis, area_provenance, warnings)


def build_tower_wind_load(
    geometry: TowerWindGeometry,
    *,
    wind_angle_deg: float,
    reference_pressure_pa: float,
    height_edges_m: Sequence[float],
    height_factors: Sequence[float],
    coefficients: TowerWindCoefficients | Mapping[str, TowerWindCoefficients],
    height_factor_provenance: str,
) -> TowerWindLoadResult:
    """Build physical nodal loads in N, without normalizing or applying them.

    Edges are heights ABOVE ``geometry.origin``.  Each factor is constant over
    one height band; split members preserve the load centroid of each piece.
    A horizontal member on an interior edge belongs to the upper band, and
    a horizontal member on the last edge belongs to the last band.  Every
    member must lie inside the covered height range: no silent omissions.

    There is no implicit gust factor or density: callers must establish what
    their pressure and height factors include, especially for time histories.
    """
    angle = _finite(wind_angle_deg, "wind_angle_deg") % 360.0
    pressure = _finite(reference_pressure_pa, "reference_pressure_pa", nonnegative=True)
    edges = tuple(_finite(z, "height edge") for z in height_edges_m)
    if len(edges) < 2 or any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError("height_edges_m must be strictly increasing with at least two entries")
    factors = tuple(_finite(g, "height factor", nonnegative=True) for g in height_factors)
    if len(factors) != len(edges) - 1:
        raise ValueError("one explicit height factor is required per band")
    if not isinstance(height_factor_provenance, str) or not height_factor_provenance.strip():
        raise ValueError("height_factor_provenance must be supplied explicitly")
    if not isinstance(geometry.area_basis, str) or not geometry.area_basis.strip() or not isinstance(
        geometry.area_provenance, str
    ) or not geometry.area_provenance.strip():
        raise ValueError("geometry area basis and provenance are required")
    if not geometry.members:
        raise ValueError("at least one physical member is required")
    origin = _xyz(geometry.origin, "origin")
    nodes = {int(tag): _xyz(record, f"node {tag}") for tag, record in geometry.nodes.items()}
    regions = {member.region for member in geometry.members}
    coefficient_map = {region: coefficients for region in regions} if isinstance(
        coefficients, TowerWindCoefficients
    ) else dict(coefficients)
    if regions - set(coefficient_map):
        raise ValueError("explicit coefficients are required for every member region")
    if any(not isinstance(coefficient_map[region], TowerWindCoefficients) for region in regions):
        raise TypeError("coefficients must be TowerWindCoefficients objects")
    c, s = cos(radians(angle)), sin(radians(angle))
    # Make cardinal directions exact rather than leaving floating-point leakage.
    c = 0.0 if abs(c) < 1e-15 else c
    s = 0.0 if abs(s) < 1e-15 else s
    direction = (c, s, 0.0)
    node_loads: dict[int, list[float]] = {}
    segments: list[dict[str, Any]] = []
    panels: dict[tuple[int, str], dict[str, Any]] = {}
    seen: set[int] = set()
    tolerance = 1e-8
    for member in geometry.members:
        if member.tag in seen:
            raise ValueError("physical member tags must be unique")
        seen.add(member.tag)
        if member.node_i not in nodes or member.node_j not in nodes:
            raise ValueError(f"member {member.tag} references a missing node")
        pi, pj = nodes[member.node_i], nodes[member.node_j]
        delta = tuple(pj[k] - pi[k] for k in range(3))
        length = sqrt(fsum(d * d for d in delta))
        if not isfinite(length) or length <= 0:
            raise ValueError(f"member {member.tag} must have finite positive length")
        zi, zj = pi[2] - origin[2], pj[2] - origin[2]
        if min(zi, zj) < edges[0] - tolerance or max(zi, zj) > edges[-1] + tolerance:
            raise ValueError(f"height bands do not fully cover member {member.tag}")
        cuts = [0.0, 1.0]
        if abs(zj - zi) > 1e-14:
            cuts.extend((z - zi) / (zj - zi) for z in edges[1:-1] if 0 < (z - zi) / (zj - zi) < 1)
        cuts.sort()
        coeff = coefficient_map[member.region]
        yaw_factor = 1 + coeff.yaw_gain * sin(2 * radians(angle)) ** 2
        for left, right in zip(cuts, cuts[1:]):
            fraction, parameter = right - left, (left + right) / 2
            point = tuple(pi[k] + parameter * delta[k] for k in range(3))
            local_point = tuple(point[k] - origin[k] for k in range(3))
            band = min(max(bisect_right(edges, local_point[2]) - 1, 0), len(factors) - 1)
            ax, ay = member.area_x_m2 * fraction, member.area_y_m2 * fraction
            magnitude = pressure * factors[band] * yaw_factor * (
                coeff.coefficient_x * ax * c * c + coeff.coefficient_y * ay * s * s
            )
            if not isfinite(magnitude):
                raise ValueError(f"non-finite force magnitude for member {member.tag}; check input scales")
            force = tuple(magnitude * v for v in direction)
            moment = _cross(local_point, force)
            for tag, weight in ((member.node_i, 1 - parameter), (member.node_j, parameter)):
                destination = node_loads.setdefault(tag, [0.0] * 6)
                for component in range(3):
                    destination[component] += weight * force[component]
            segments.append({
                "member_tag": member.tag, "node_i": member.node_i, "node_j": member.node_j,
                "region": member.region, "section_name": member.section_name,
                "band_index": band, "t_start": left, "t_end": right,
                "midpoint_parameter": parameter, "length_m": length * fraction,
                "area_x_m2": ax, "area_y_m2": ay, "height_factor": factors[band],
                "yaw_factor": yaw_factor, "coefficient_x": coeff.coefficient_x,
                "coefficient_y": coeff.coefficient_y, "coefficient_provenance": coeff.provenance,
                "load_point_global_m": point, "load_point_local_m": local_point,
                "force_magnitude_N": magnitude, "force_N": force, "moment_Nm": moment,
            })
            panel = panels.setdefault((band, member.region), {
                "band_index": band, "region": member.region,
                "z_min_local_m": edges[band], "z_max_local_m": edges[band + 1],
                "area_x_m2": 0.0, "area_y_m2": 0.0, "force_magnitude_N": 0.0,
                "force_N": [0.0] * 3, "moment_Nm": [0.0] * 3,
                "member_piece_count": 0,
            })
            for key, value in (("area_x_m2", ax), ("area_y_m2", ay), ("force_magnitude_N", magnitude)):
                panel[key] += value
            panel["member_piece_count"] += 1
            for k in range(3):
                panel["force_N"][k] += force[k]
                panel["moment_Nm"][k] += moment[k]
    nodal_force = tuple(fsum(load[k] for load in node_loads.values()) for k in range(3))
    nodal_moments = [_cross(tuple(nodes[tag][k] - origin[k] for k in range(3)), tuple(load[:3]))
                     for tag, load in node_loads.items()]
    nodal_moment = tuple(fsum(moment[k] for moment in nodal_moments) for k in range(3))
    target_force = tuple(fsum(row["force_N"][k] for row in segments) for k in range(3))
    target_moment = tuple(fsum(row["moment_Nm"][k] for row in segments) for k in range(3))
    force_error = tuple(nodal_force[k] - target_force[k] for k in range(3))
    moment_error = tuple(nodal_moment[k] - target_moment[k] for k in range(3))
    magnitude = fsum(row["force_magnitude_N"] for row in segments)
    centroid = tuple(fsum(row["load_point_global_m"][k] * row["force_magnitude_N"] for row in segments)
                     / magnitude for k in range(3)) if magnitude > 0 else None
    summary = {
        "model": "single_tower_directional_alongwind_member_assigned_areas",
        "wind_angle_deg": angle, "angle_convention": "flow_towards_0_global_positive_X_90_positive_Y_degrees",
        "wind_unit_vector": direction, "reference_pressure_pa": pressure,
        "height_edges_local_m": edges, "height_factors": factors,
        "height_factor_provenance": height_factor_provenance,
        "area_basis": geometry.area_basis, "area_provenance": geometry.area_provenance,
        "engineering_validation": "not_established_by_this_module",
        "proxy_uncalibrated": geometry.area_basis == PROXY_AREA_BASIS,
        "physical_member_count": len(geometry.members), "loaded_node_count": len(node_loads),
        "member_piece_count": len(segments), "origin_m": origin,
        "total_area_x_m2": fsum(member.area_x_m2 for member in geometry.members),
        "total_area_y_m2": fsum(member.area_y_m2 for member in geometry.members),
        "force_magnitude_N": magnitude, "force_N": nodal_force, "moment_Nm": nodal_moment,
        "target_force_N": target_force, "target_moment_Nm": target_moment,
        "force_residual_N": force_error, "moment_residual_Nm": moment_error,
        "force_centroid_global_m": centroid,
        "coefficients_by_region": {region: {
            "coefficient_x": coefficient_map[region].coefficient_x,
            "coefficient_y": coefficient_map[region].coefficient_y,
            "yaw_gain": coefficient_map[region].yaw_gain,
            "provenance": coefficient_map[region].provenance,
        } for region in sorted(regions)},
        "load_distribution": "clipped_member_midpoint_force_to_original_endpoints_linear_weights",
        "warnings": list(geometry.warnings) + [
            "no_independent_crosswind_lift_or_aerodynamic_torque; geometric_load_eccentricity_is_retained",
            "nodal_lumping_preserves_force_and_moment_but_is_not_a_beam_consistent_load_vector",
            "no_implicit_gust_factor_or_turbulence; pressure_and_height_factor_definitions_are_caller_responsibility",
        ],
    }
    return TowerWindLoadResult(
        {tag: tuple(load) for tag, load in sorted(node_loads.items())},  # type: ignore[arg-type]
        tuple(panels[key] for key in sorted(panels)), tuple(segments), summary,
    )
