"""Explicit mechanical profiles and read-only adapters to the existing tower.

These helpers do not alter either production tower's defaults. SI units are
used throughout. ``aligned_v1`` is a declared configuration, not a validated
replacement for the historical tower.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

import numpy as np

from .tower_model import OpenSeesModel
from .tower_model_with_buckling import OpenSeesModelWithBuckling


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


@dataclass(frozen=True)
class MechanicalProfile:
    name: str = "baseline_legacy"
    long_edge_segments: int = 8
    short_edge_segments: int = 1
    integration_type: str = "Legendre"
    integration_points: int = 6
    transformation: str = "Corotational"
    element_type: str = "dispBeamColumn"
    imperfection_shape: str = "half_sine"
    imperfection_ratio: float = 0.001
    imperfection_seed: int = 30103

    def __post_init__(self) -> None:
        if self.name not in {"baseline_legacy", "aligned_v1"}:
            raise ValueError("Unknown mechanical profile")
        for value in (self.long_edge_segments, self.short_edge_segments, self.integration_points):
            if isinstance(value, bool) or int(value) != value or value <= 0:
                raise ValueError("Mesh/integration counts must be positive integers")
        if not math.isfinite(self.imperfection_ratio) or self.imperfection_ratio < 0:
            raise ValueError("Imperfection ratio must be finite and nonnegative")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def steel(self, *, family: str, E0: float, fy: float, b: float = 0.03) -> Steel02Parameters:
        if family not in {"member", "tower"}:
            raise ValueError("family must be member or tower")
        factory = (Steel02Parameters.legacy_tower if family == "tower" or self.name == "aligned_v1"
                   else Steel02Parameters.legacy_member)
        return factory(E0=E0, fy=fy, b=b)


class MechanicalCatalog:
    """Reuse the actual S2K parser and fiber builder without constructing a domain.

    ``output_dir`` is explicit because the existing parser creates that directory.
    No model CSV files or OpenSees nodes/elements are generated here.
    """

    def __init__(self, source: str | Path, *, output_dir: str | Path,
                 profile: MechanicalProfile | None = None) -> None:
        self.profile = profile or MechanicalProfile()
        self.model = OpenSeesModel(source, output_dir=output_dir,
                                  long_edge_segments=self.profile.long_edge_segments,
                                  short_edge_segments=self.profile.short_edge_segments,
                                  num_intgr_pts=self.profile.integration_points,
                                  beam_integration_type=self.profile.integration_type)
        self.nodes = self.model._parse_node_coordinates()
        self.connectivity = self.model._parse_element_connectivity()
        self.assignments = self.model._element_section_assignments()
        self.sections = self.model._frame_section_properties()
        self.basics = {row["Material"]: row for row in self._table("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES")}
        self.steels = {row["Material"]: row for row in self._table("MATERIAL PROPERTIES 03A - STEEL DATA")}

    def _table(self, name: str) -> list[dict[str, Any]]:
        return [self.model._parse_key_values(line) for line in self.model._table_lines(name)]

    def member(self, member_id: int) -> dict[str, Any]:
        connectivity = self.connectivity[int(member_id)]
        assignment = self.assignments[int(member_id)]
        section = dict(self.sections[assignment["section_name"]])
        basic = self.basics[section["material_name"]]
        steel = self.steels[section["material_name"]]
        coordinates = [[float(self.nodes[connectivity[key]][axis]) for axis in ("x", "y", "z")]
                       for key in ("node_i", "node_j")]
        E0, fy = float(basic["E1"]), float(steel["Fy"]) * 1e6
        fibers, patches = self.model._l_section_rect_patches(section["section_name"], 1)
        return {"member_id": int(member_id), "node_ids": [connectivity["node_i"], connectivity["node_j"]],
                "coordinates": coordinates, "length": math.dist(*coordinates), "section": section,
                "fibers": fibers, "patches": patches["patches"],
                "steel_member": self.profile.steel(family="member", E0=E0, fy=fy).as_dict(),
                "steel_tower": self.profile.steel(family="tower", E0=E0, fy=fy).as_dict(),
                "G": float(basic["G12"]), "nu": float(basic["U12"]),
                "density": float(basic["UnitMass"]), "profile": self.profile.as_dict()}

    def representative_members(self) -> list[int]:
        """Critical Q235 rods plus median-length L125x8 Q345 and largest Q420."""
        rows = [self.member(tag) for tag in self.connectivity]
        q345 = sorted((row for row in rows if row["section"]["section_name"] == "L125x8Q345"),
                      key=lambda row: (row["length"], row["member_id"]))
        q420 = sorted((row for row in rows if row["section"]["material_name"] == "Q420"),
                      key=lambda row: (-row["section"]["area"], row["member_id"]))
        if not q345 or not q420:
            raise ValueError("Source must contain the designated actual Q345/Q420 representatives")
        return [877, 825, q345[len(q345) // 2]["member_id"], q420[0]["member_id"]]

    def imperfection_vectors(self) -> dict[int, tuple[float, float, float]]:
        """Reproduce legacy S2K traversal once; persist vectors before reordering.

        Reordering this returned mapping does not change a member's direction.
        Reconstructing a different S2K traversal from only the seed may do so.
        """
        adapter = object.__new__(OpenSeesModelWithBuckling)
        adapter.random_disp_ratio = self.profile.imperfection_ratio
        adapter._imperfection_random = random.Random(self.profile.imperfection_seed)
        result = {}
        for member_id, record in self.connectivity.items():
            points = [self.nodes[record[key]] for key in ("node_i", "node_j")]
            coordinates = [float(point[axis]) for point in points for axis in ("x", "y", "z")]
            result[member_id] = adapter._add_rand_disp(0.0, 0.0, 0.0, *coordinates)
        return result


def fiber_moments(fibers: Sequence[Mapping[str, float]]) -> dict[str, float]:
    area = sum(float(cell["area"]) for cell in fibers)
    if not fibers or not math.isfinite(area) or area <= 0:
        raise ValueError("Fiber area must be positive")
    cy = sum(float(cell["y"]) * float(cell["area"]) for cell in fibers) / area
    cz = sum(float(cell["z"]) * float(cell["area"]) for cell in fibers) / area
    i33 = sum((float(cell["y"]) - cy)**2 * float(cell["area"]) for cell in fibers)
    i22 = sum((float(cell["z"]) - cz)**2 * float(cell["area"]) for cell in fibers)
    iyz = sum((float(cell["y"]) - cy) * (float(cell["z"]) - cz) * float(cell["area"]) for cell in fibers)
    eig = np.linalg.eigvalsh([[i33, -iyz], [-iyz, i22]])
    return {"area": area, "centroid_y": cy, "centroid_z": cz, "i22": i22,
            "i33": i33, "integral_yz": iyz, "weak_principal": float(eig[0]),
            "strong_principal": float(eig[1])}


def fiber_section_tangent(fibers: Sequence[Mapping[str, float]], E0: float, GJ: float) -> np.ndarray:
    """Section order P/Mz/My/T, strain = eps - y*kz + z*ky."""
    moments = fiber_moments(fibers)
    result = np.zeros((4, 4))
    for cell in fibers:
        vector = np.array([1.0, -(cell["y"] - moments["centroid_y"]),
                           cell["z"] - moments["centroid_z"]])
        result[:3, :3] += E0 * cell["area"] * np.outer(vector, vector)
    result[3, 3] = GJ
    return result


def local_axes(coordinates: Sequence[Sequence[float]]) -> np.ndarray:
    points = np.asarray(coordinates, dtype=float)
    if points.shape != (2, 3) or not np.isfinite(points).all():
        raise ValueError("Expected two finite 3D coordinates")
    x = points[1] - points[0]
    length = np.linalg.norm(x)
    if length <= 0:
        raise ValueError("Member endpoints coincide")
    x /= length
    node_i, node_j = [dict(zip(("x", "y", "z"), point)) for point in points]
    reference = np.array(OpenSeesModel._geom_transf_vector(node_i, node_j))
    y = np.cross(reference, x)
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    return np.array([x, y, z])


def beam_tangent(section_tangent: np.ndarray, coordinates: Sequence[Sequence[float]]) -> np.ndarray:
    """Independent Euler-Bernoulli 12x12 elastic stiffness via Hermite strain B."""
    length = math.dist(*coordinates)
    axes = local_axes(coordinates)
    tangent = np.zeros((12, 12))
    locations, weights = np.polynomial.legendre.leggauss(3)
    for coordinate, weight in zip(locations, weights):
        xi = 0.5 * (coordinate + 1)
        B = np.zeros((4, 12))
        B[0, [0, 6]] = [-1 / length, 1 / length]
        B[3, [3, 9]] = [-1 / length, 1 / length]
        B[1, [1, 5, 7, 11]] = [(-6 + 12 * xi) / length**2, (-4 + 6 * xi) / length,
                                (6 - 12 * xi) / length**2, (-2 + 6 * xi) / length]
        B[2, [2, 4, 8, 10]] = [(6 - 12 * xi) / length**2, (-4 + 6 * xi) / length,
                                (-6 + 12 * xi) / length**2, (-2 + 6 * xi) / length]
        tangent += B.T @ section_tangent @ B * weight * length / 2
    transform = np.zeros((12, 12))
    for index in range(0, 12, 3):
        transform[index:index + 3, index:index + 3] = axes
    return transform.T @ tangent @ transform


def scaled_tangent(tangent: np.ndarray, length: float, EA: float) -> np.ndarray:
    scale = np.tile([length, length, length, 1.0, 1.0, 1.0], 2)
    return np.asarray(tangent) * np.outer(scale, scale) / (EA * length)


def rigid_body_modes(coordinates: Sequence[Sequence[float]]) -> np.ndarray:
    points = np.asarray(coordinates, dtype=float)
    modes = np.zeros((12, 6))
    for node, point in enumerate(points - points[0]):
        modes[node * 6:node * 6 + 3, :3] = np.eye(3)
        for axis in range(3):
            modes[node * 6:node * 6 + 3, axis + 3] = np.cross(np.eye(3)[axis], point)
        modes[node * 6 + 3:node * 6 + 6, 3:] = np.eye(3)
    return modes
