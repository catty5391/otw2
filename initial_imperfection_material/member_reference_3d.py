"""Isolated 3D physical-member builder and complete 6DOF boundary replay.

This is local-reference infrastructure, not a claim that T06/T08 have passed.
The real tower's initial + gravity + cyclic history is required for that claim.
Every call owns and wipes one process-local OpenSees domain; never run in threads.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import openseespy.opensees as ops

from model.mechanical_profile import MechanicalCatalog, Steel02Parameters, local_axes
from model.tower_model import OpenSeesModel


@dataclass(frozen=True)
class BoundaryPoint:
    stage_id: str
    stage_progress: float
    end_i: tuple[float, ...]
    end_j: tuple[float, ...]
    source_step: int = 0

    def __post_init__(self) -> None:
        if len(self.end_i) != 6 or len(self.end_j) != 6:
            raise ValueError("Boundary points require six DOFs at each endpoint")
        if not all(math.isfinite(float(value)) for value in (*self.end_i, *self.end_j, self.stage_progress)):
            raise ValueError("Boundary history must be finite")


def build_member_reference(member: dict[str, Any], *, divisions: int = 4,
                           imperfection_vector: Sequence[float] = (0.0, 0.0, 0.0),
                           elastic_steel: bool = False, transformation: str = "Corotational",
                           exact_coordinates: Sequence[Sequence[float]] | None = None,
                           orientation_vectors: Sequence[Sequence[float]] | None = None) -> dict[str, Any]:
    """Build actual tower patches/Steel02/Legendre6/dispBeamColumn, no supports.

    An ``exact_coordinates`` sequence preserves a recorded legacy geometry.
    Otherwise all meshes use the same global half-sine peak vector. No segment
    mass/self-weight is invented: legacy tower mass is at original joints only.
    """
    if isinstance(divisions, bool) or int(divisions) != divisions or divisions < 2:
        raise ValueError("divisions must be an integer >= 2")
    if transformation not in {"Linear", "Corotational"}:
        raise ValueError("Only explicit Linear or Corotational transformations are supported")
    points = np.asarray(member["coordinates"], dtype=float)
    vector = np.asarray(imperfection_vector, dtype=float)
    if vector.shape != (3,) or not np.isfinite(vector).all():
        raise ValueError("Imperfection vector must have three finite components")
    if abs(float(np.dot(vector, local_axes(points)[0]))) > 1e-10 * max(1.0, np.linalg.norm(vector)):
        raise ValueError("Imperfection vector must be transverse to the initial chord")
    if exact_coordinates is None:
        coordinates = [((1 - station / divisions) * points[0] + station / divisions * points[1]
                        + vector * math.sin(math.pi * station / divisions)).tolist()
                       for station in range(divisions + 1)]
    else:
        coordinates_array = np.asarray(exact_coordinates, dtype=float)
        if coordinates_array.shape != (divisions + 1, 3) or not np.isfinite(coordinates_array).all():
            raise ValueError("Recorded geometry must contain every segment node")
        if not np.allclose(coordinates_array[[0, -1]], points, atol=1e-12, rtol=0):
            raise ValueError("Recorded geometry endpoints disagree with the source member")
        coordinates = coordinates_array.tolist()
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    for tag, coordinate in enumerate(coordinates, 1):
        ops.node(tag, *coordinate)
    steel = Steel02Parameters(**member["steel_tower"])
    if elastic_steel:
        ops.uniaxialMaterial("Elastic", 1, steel.E0)
    else:
        ops.uniaxialMaterial(*steel.opensees_arguments(1))
    GJ = member["G"] * member["section"]["tors_const"]
    ops.section("Fiber", 1, "-GJ", GJ if GJ > 0 else 1.0)
    for patch in member["patches"]:
        ops.patch("rect", 1, patch["num_y"], patch["num_z"], patch["y_i"],
                  patch["z_i"], patch["y_j"], patch["z_j"])
    integration_points = int(member["profile"]["integration_points"])
    integration_type = member["profile"]["integration_type"]
    if orientation_vectors is not None and np.asarray(orientation_vectors).shape != (divisions, 3):
        raise ValueError("One orientation vector is required for every segment")
    for tag in range(1, divisions + 1):
        endpoints = [dict(zip(("x", "y", "z"), coordinate)) for coordinate in coordinates[tag - 1:tag + 1]]
        orientation = (OpenSeesModel._geom_transf_vector(*endpoints) if orientation_vectors is None
                       else orientation_vectors[tag - 1])
        ops.geomTransf(transformation, tag, *orientation)
        ops.beamIntegration(integration_type, tag, 1, integration_points)
        ops.element("dispBeamColumn", tag, tag, tag + 1, tag, tag)
    return {"member": member, "nodes": list(range(1, divisions + 2)),
            "elements": list(range(1, divisions + 1)), "coordinates": coordinates,
            "imperfection_vector": vector.tolist(), "elastic_steel": elastic_steel,
            "transformation": transformation, "integration_points": integration_points,
            "mass_convention": "no_intermediate_mass_or_load_in_legacy_tower"}


def capture_member_state(model: dict[str, Any], point: BoundaryPoint, accepted_step: int) -> dict[str, Any]:
    nodes, elements = model["nodes"], model["elements"]
    displacements = {str(tag): list(ops.nodeDisp(tag)) for tag in nodes}
    current_endpoints = [np.array(model["coordinates"][index]) + np.array(displacements[str(nodes[index])][:3])
                         for index in (0, -1)]
    member = model["member"]
    segment_rows = []
    for tag in elements:
        sections = []
        for section_id in range(1, model["integration_points"] + 1):
            fiber_responses = []
            for cell in member["fibers"]:
                response = ops.eleResponse(tag, "section", section_id, "fiber", cell["y"], cell["z"], "stressStrain")
                if response and len(response) == 2:
                    fiber_responses.append({"y": cell["y"], "z": cell["z"], "stress": response[0], "strain": response[1]})
            if len(fiber_responses) != len(member["fibers"]):
                raise RuntimeError("Required reference fiber responses are incomplete")
            sections.append({"section_id": section_id,
                             "deformation": list(ops.eleResponse(tag, "section", section_id, "deformation")),
                             "force": list(ops.eleResponse(tag, "section", section_id, "force")),
                             "max_abs_stress": max(fiber_responses, key=lambda row: abs(row["stress"])),
                             "max_abs_strain": max(fiber_responses, key=lambda row: abs(row["strain"]))})
        segment_rows.append({"segment_id": tag, "global_force": list(ops.eleResponse(tag, "globalForce")),
                             "local_force": list(ops.eleResponse(tag, "localForce")),
                             "basic_deformation": list(ops.eleResponse(tag, "basicDeformation")), "sections": sections})
    initial_length = member["length"]
    current_length = math.dist(*current_endpoints)
    return {"accepted_step": accepted_step, "source_step": point.source_step, "stage_id": point.stage_id,
            "stage_progress": point.stage_progress, "committed": True, "node_displacements": displacements,
            "end_global_internal_force": segment_rows[0]["global_force"][:6] + segment_rows[-1]["global_force"][6:],
            "chord_shortening_m": initial_length - current_length,
            "chord_strain": (current_length - initial_length) / initial_length,
            "sum_segment_basic_axial_extension_m": sum(row["basic_deformation"][0] for row in segment_rows),
            "segments": segment_rows,
            "maximum_fiber_abs_stress": max(abs(section["max_abs_stress"]["stress"]) for row in segment_rows for section in row["sections"]),
            "maximum_fiber_abs_strain": max(abs(section["max_abs_strain"]["strain"]) for row in segment_rows for section in row["sections"])}


def replay_boundary_history(member: dict[str, Any], points: Sequence[BoundaryPoint], *, divisions: int = 4,
                            imperfection_vector: Sequence[float] = (0.0, 0.0, 0.0),
                            elastic_steel: bool = False, transformation: str = "Corotational",
                            exact_coordinates: Sequence[Sequence[float]] | None = None,
                            tolerance: float = 1e-10, maximum_iterations: int = 80,
                            detail_stride: int = 1, remove_rigid_translation: bool = False,
                            algorithms: Sequence[str] = ("Newton",)) -> dict[str, Any]:
    """Prescribe all endpoint DOFs from the unloaded state, recording committed data.

    Synthetic tests may use explicit stages such as ``initial``/``test``.
    Imported tower histories additionally require gravity through the loader.
    Default is Newton only; an explicit fixed fallback sequence may be requested.
    No hidden tolerance relaxation, endpoint forces or duplicate endpoint gravity
    are added. Failure stops and retains only accepted states. Failed analyze
    reversion relies on OpenSees StaticAnalysis; time equality is an additional
    minimum guard, not a proof of every internal variable's rollback.
    ``remove_rigid_translation`` subtracts the same endpoint-i translation from
    every prescribed endpoint, then restores all output node translations. It
    is an explicit quasi-static coordinate normalization, not a dynamic moving
    frame (which would require transformed inertia terms).
    """
    if len(points) < 2 or points[0].stage_id != "initial":
        raise ValueError("Replay requires an explicit unloaded initial point")
    if any(abs(value) > 1e-14 for value in (*points[0].end_i, *points[0].end_j)):
        raise ValueError("Initial boundary displacement must be zero")
    if not math.isfinite(tolerance) or tolerance <= 0 or maximum_iterations < 1:
        raise ValueError("Invalid solver settings")
    if isinstance(detail_stride, bool) or int(detail_stride) != detail_stride or detail_stride < 1:
        raise ValueError("detail_stride must be a positive integer")
    algorithm_arguments = {"Newton": ("Newton",), "KrylovNewton": ("KrylovNewton",),
                           "NewtonLineSearch(0.8)": ("NewtonLineSearch", 0.8)}
    if not algorithms or any(name not in algorithm_arguments for name in algorithms):
        raise ValueError("Unsupported explicit replay algorithm sequence")
    model = build_member_reference(member, divisions=divisions, imperfection_vector=imperfection_vector,
                                   elastic_steel=elastic_steel, transformation=transformation,
                                   exact_coordinates=exact_coordinates)
    progress = list(range(len(points)))
    prescribed_points = points
    if remove_rigid_translation:
        prescribed_points = [BoundaryPoint(point.stage_id, point.stage_progress,
            (0.0, 0.0, 0.0) + tuple(point.end_i[3:]),
            tuple(np.asarray(point.end_j[:3]) - np.asarray(point.end_i[:3])) + tuple(point.end_j[3:]),
            point.source_step) for point in points]
    for end, tag in (("end_i", 1), ("end_j", divisions + 1)):
        for dof in range(6):
            series_tag = (0 if end == "end_i" else 6) + dof + 1
            values = [getattr(point, end)[dof] for point in prescribed_points]
            ops.timeSeries("Path", series_tag, "-time", *progress, "-values", *values, "-useLast")
            ops.pattern("Plain", series_tag, series_tag)
            ops.sp(tag, dof + 1, 1.0)
    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", tolerance, maximum_iterations)
    ops.algorithm("Newton")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    ops.initialize()
    accepted = [capture_member_state(model, points[0], 0)]
    previous_full_state = accepted[0]
    failed_step = None
    attempts = []
    events = []
    for step, point in enumerate(points[1:], 1):
        committed_time = ops.getTime()
        for name in algorithms:
            ops.test("NormDispIncr", tolerance, maximum_iterations)
            ops.algorithm(*algorithm_arguments[name])
            code = ops.analyze(1)
            observed_time = ops.getTime()
            failed_time_reverted = code == 0 or math.isclose(observed_time, committed_time, abs_tol=1e-12, rel_tol=0)
            attempts.append({"attempt_id": len(attempts) + 1, "requested_step": step, "return_code": code,
                "source_step": point.source_step, "stage_id": point.stage_id, "stage_progress": point.stage_progress,
                "iterations": ops.testIter(), "norms": list(ops.testNorms())[:ops.testIter()],
                "algorithm": name, "tolerance": tolerance, "committed_time_before": committed_time,
                "time_after_attempt": observed_time, "failed_time_reverted": failed_time_reverted})
            if code == 0 or not failed_time_reverted:
                break
        ops.algorithm("Newton")
        ops.test("NormDispIncr", tolerance, maximum_iterations)
        if code != 0:
            failed_step = step
            break
        state = capture_member_state(model, point, step)
        if remove_rigid_translation:
            translation = np.asarray(point.end_i[:3])
            for displacement in state["node_displacements"].values():
                displacement[:3] = (np.asarray(displacement[:3]) + translation).tolist()
            state["removed_rigid_translation_m"] = translation.tolist()
        previous = accepted[-1]
        event_types = []
        if previous["maximum_fiber_abs_stress"] < member["steel_tower"]["fy"] <= state["maximum_fiber_abs_stress"]:
            event_types.append("upward_fy_crossing_indicator_not_plastic_strain")
        if abs(state["chord_strain"] - previous["chord_strain"]) > 1e-4:
            event_types.append("chord_strain_increment_above_1e_minus_4")
        previous_force = np.asarray(previous["end_global_internal_force"][6:9])
        current_force = np.asarray(state["end_global_internal_force"][6:9])
        if np.linalg.norm(current_force - previous_force) > max(50.0, 0.1 * np.linalg.norm(previous_force)):
            event_types.append("end_force_increment_above_50N_and_10percent")
        if event_types:
            events.append({"accepted_step": step, "source_step": point.source_step, "types": event_types})
            if "segments" not in accepted[-1]:
                accepted[-1] = dict(previous_full_state, detail_level="retained_pre_event_full_section_extrema")
        full_state = dict(state)
        if detail_stride > 1 and step % detail_stride and not event_types and step != len(points) - 1:
            state["segment_summary"] = [{"segment_id": segment["segment_id"],
                "basic_deformation": segment["basic_deformation"],
                "local_end_force": segment["local_force"],
                "max_abs_stress": max((section["max_abs_stress"] for section in segment["sections"]), key=lambda row: abs(row["stress"])),
                "max_abs_strain": max((section["max_abs_strain"] for section in segment["sections"]), key=lambda row: abs(row["strain"]))}
                for segment in state.pop("segments")]
            state["detail_level"] = "all_nodes_and_forces_fiber_extrema_only"
        else:
            state["detail_level"] = "full_section_extrema"
        accepted.append(state)
        previous_full_state = full_state
    return {"schema": "otw2.member_reference_replay.v1", "member_id": member["member_id"],
            "execution_status": "completed" if failed_step is None else "not_converged",
            "validation_status": "unvalidated", "requested_steps": len(points) - 1,
            "completed_steps": len(accepted) - 1, "failed_step": failed_step,
            "geometry": model["coordinates"], "imperfection_vector": list(imperfection_vector),
            "elastic_steel": elastic_steel, "transformation": transformation,
            "steel": member["steel_tower"], "states": accepted, "attempts": attempts,
            "events": events, "detail_stride": detail_stride,
            "solver_algorithms": list(algorithms),
            "rollback_scope_note": "OpenSees failed-step reversion is relied on; logged time equality alone is not a complete internal-state proof.",
            "removed_rigid_translation": remove_rigid_translation,
            "boundary_points": [asdict(point) for point in points],
            "time_semantics": "monotonic_replay_index_not_seconds", "intermediate_loads": "none_legacy_tower",
            "force_semantics": "element_internal_end_forces_global_not_nodal_reactions"}


def load_recorded_boundary(path: str | Path, member_id: int) -> dict[str, Any]:
    """Load T04 recorder history; reject missing initial/gravity or internal loads.

    No endpoint-history reconstruction from old force-only SQLite is attempted.
    The returned coordinates exactly reproduce the recorded four-segment member.
    """
    from util.processing.member_state_recorder import iter_member_states
    path = Path(path)
    metadata_path = path.with_suffix(".metadata.json")
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Recorded geometry unavailable; a new instrumented run is required: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    entries = metadata["members"].get(str(member_id))
    if not entries:
        raise ValueError(f"No recorded member {member_id}")
    entries = sorted(entries, key=lambda row: row.get("segment_index", 0))
    if any(left["node_j"] != right["node_i"] for left, right in zip(entries, entries[1:])):
        raise ValueError("Recorded segments do not form a connected member")
    node_tags = [entries[0]["node_i"]] + [entry["node_j"] for entry in entries]
    coordinates = [metadata["node_coordinates"][str(tag)] for tag in node_tags]
    intermediate = set(node_tags[1:-1])
    for tag in intermediate:
        mass = metadata.get("node_masses", {}).get(str(tag))
        if mass and any(abs(float(mass.get(key, 0))) > 0 for key in ("mx", "my", "mz", "mrx", "mry", "mrz")):
            raise ValueError("Intermediate mass/loading requires an explicit extended replay, not this legacy adapter")
    points, reference_states = [], []
    for index, row in enumerate(iter_member_states(path)):
        if row.get("accepted_step") != index:
            raise ValueError("Recorded accepted-step sequence is incomplete or reordered")
        records = [entry for entry in row["members"] if int(entry["original_member_id"]) == member_id]
        if len(records) != 1:
            raise ValueError(f"Missing/duplicate member {member_id} in committed history")
        record = records[0]
        if any(str(tag) in row.get("loads", {}) for tag in intermediate):
            raise ValueError("Recorded intermediate load is unsupported; do not silently drop it")
        points.append(BoundaryPoint(stage_id=row["stage_id"], stage_progress=row["stage_progress"],
                                    end_i=tuple(row["node_displacements"][str(record["node_i"])]),
                                    end_j=tuple(row["node_displacements"][str(record["node_j"])]),
                                    source_step=row["accepted_step"]))
        reference_states.append(record)
    if not points or points[0].stage_id != "initial" or not any(point.stage_id == "gravity" for point in points):
        raise ValueError("A tower replay requires initial and complete gravity history, not a cyclic-only slice")
    gravity = [point.stage_progress for point in points if point.stage_id == "gravity"]
    if not math.isclose(gravity[-1], 1.0, abs_tol=1e-12) or any(left >= right for left, right in zip(gravity, gravity[1:])):
        raise ValueError("Gravity history must increase to the completed gravity state")
    return {"points": points, "exact_coordinates": coordinates, "divisions": len(entries),
            "reference_states": reference_states, "source_metadata": metadata,
            "boundary_file": str(path)}


def subdivide_boundary_points(points: Sequence[BoundaryPoint], substeps: int) -> list[BoundaryPoint]:
    """Explicit linear interpolation of prescribed endpoint motion.

    Every interpolated point is a real committed state, not a Newton trial.
    Preserve all states and compare only the original indices. This numerical
    choice must be checked for sensitivity in nonlinear reference histories.
    """
    if isinstance(substeps, bool) or int(substeps) != substeps or substeps < 1:
        raise ValueError("Boundary substeps must be a positive integer")
    if not points:
        raise ValueError("Boundary history is empty")
    dense = [points[0]]
    for left, right in zip(points, points[1:]):
        for index in range(1, substeps + 1):
            fraction = index / substeps
            dense.append(BoundaryPoint(
                right.stage_id, right.stage_progress if index == substeps else
                (left.stage_progress * (1 - fraction) + right.stage_progress * fraction
                 if left.stage_id == right.stage_id else right.stage_progress),
                tuple(np.asarray(left.end_i) * (1 - fraction) + np.asarray(right.end_i) * fraction),
                tuple(np.asarray(left.end_j) * (1 - fraction) + np.asarray(right.end_j) * fraction),
                right.source_step))
    return dense


def run_axial_boundary_case(member: dict[str, Any], axial_extensions: Sequence[float], *,
                            boundary: str = "pinned", divisions: int = 4,
                            imperfection_vector: Sequence[float] = (0.0, 0.0, 0.0),
                            rotational_stiffnesses: Sequence[float] | None = None,
                            elastic_steel: bool = False) -> dict[str, Any]:
    """Explicit 3D pinned/clamped/end-rotational-spring comparison.

    Motions/supports are in the original member's orthonormal axes, not guessed
    global DOFs. Every segment orientation is rotated together with geometry;
    the angle's material axes and bending coupling are preserved. Positive
    extension is tension. Springs are [i_ry,i_rz,j_ry,j_rz] in N*m/rad.
    Torsional rigid motion is removed by rx_i=0, without releasing other axes.
    """
    if boundary not in {"pinned", "clamped", "rotational_springs"}:
        raise ValueError("Unknown explicit 3D boundary")
    extensions = np.asarray(axial_extensions, dtype=float)
    if extensions.ndim != 1 or len(extensions) < 2 or not np.isfinite(extensions).all() or abs(extensions[0]) > 1e-14:
        raise ValueError("Axial history must be finite and start at zero")
    springs = None
    if boundary == "rotational_springs":
        springs = np.asarray(rotational_stiffnesses, dtype=float)
        if springs.shape != (4,) or not np.isfinite(springs).all() or np.any(springs < 0):
            raise ValueError("Four finite nonnegative rotational stiffnesses are required")
    elif rotational_stiffnesses is not None:
        raise ValueError("Rotational stiffnesses only apply to the spring boundary")
    axes = local_axes(member["coordinates"])
    global_model = build_member_reference(member, divisions=divisions, imperfection_vector=imperfection_vector,
                                          elastic_steel=elastic_steel)
    global_coordinates = np.asarray(global_model["coordinates"])
    local_coordinates = (global_coordinates - global_coordinates[0]) @ axes.T
    orientation_vectors = []
    for left, right in zip(global_coordinates, global_coordinates[1:]):
        arguments = [dict(zip(("x", "y", "z"), point)) for point in (left, right)]
        orientation_vectors.append((axes @ OpenSeesModel._geom_transf_vector(*arguments)).tolist())
    local_member = dict(member, coordinates=[local_coordinates[0].tolist(), local_coordinates[-1].tolist()])
    model = build_member_reference(local_member, divisions=divisions, exact_coordinates=local_coordinates,
                                   orientation_vectors=orientation_vectors, elastic_steel=elastic_steel)
    ni, nj = 1, divisions + 1
    if boundary == "clamped":
        ops.fix(ni, 1, 1, 1, 1, 1, 1)
        ops.fix(nj, 0, 1, 1, 1, 1, 1)
    else:
        ops.fix(ni, 1, 1, 1, 1, 0, 0)
        ops.fix(nj, 0, 1, 1, 0, 0, 0)
    if springs is not None:
        for index, endpoint in enumerate((ni, nj)):
            anchor = divisions + 2 + index
            ops.node(anchor, *local_coordinates[0 if index == 0 else -1])
            ops.fix(anchor, 1, 1, 1, 1, 1, 1)
            for axis in range(2):
                stiffness = float(springs[2 * index + axis])
                if stiffness > 0:
                    tag = 100 + 2 * index + axis
                    ops.uniaxialMaterial("Elastic", tag, stiffness)
                    ops.element("zeroLength", tag, anchor, endpoint, "-mat", tag, "-dir", axis + 5)
    ops.timeSeries("Path", 1, "-time", *range(len(extensions)), "-values", *extensions, "-useLast")
    ops.pattern("Plain", 1, 1)
    ops.sp(nj, 1, 1.0)
    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 1e-10, 80)
    ops.algorithm("Newton")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    ops.initialize()
    initial = BoundaryPoint("initial", 0, (0.0,) * 6, (0.0,) * 6)
    states = [capture_member_state(model, initial, 0)]
    failed = None
    for index, extension in enumerate(extensions[1:], 1):
        if ops.analyze(1) != 0:
            failed = index
            break
        point = BoundaryPoint("axial_protocol", index / (len(extensions) - 1), tuple(ops.nodeDisp(ni)), tuple(ops.nodeDisp(nj)), index)
        states.append(capture_member_state(model, point, index))
    return {"schema": "otw2.member_explicit_boundary.v1", "member_id": member["member_id"],
            "boundary": boundary, "rotation_spring_stiffnesses_Nm_per_rad": None if springs is None else springs.tolist(),
            "frame": "original_member_local_axes", "global_to_local_axes": axes.tolist(),
            "execution_status": "completed" if failed is None else "not_converged",
            "failed_step": failed, "states": states, "requested_steps": len(extensions) - 1,
            "completed_steps": len(states) - 1, "validation_status": "unvalidated"}


def run_pinned_2d_reference(member: dict[str, Any], *, imperfection_ratio: float,
                            maximum_shortening: float, steps: int, divisions: int = 16):
    """Thin wrapper over the retained 2D weak-axis reference, with explicit steel.

    This has genuinely different pinned 2D assumptions; it is not relabelled
    as a spatial replay. ``baseline_legacy`` retains the member Steel02 profile.
    """
    from .config import ReferenceSolverConfig
    from .experiment import run_segmented_reference
    from .material import MemberProperties
    section = member["section"]
    leg, thickness = OpenSeesModel._l_section_dimensions(section["section_name"])
    weak = float(np.linalg.eigvalsh([[section["i22"], section["i23"]], [section["i23"], section["i33"]]])[0])
    steel = Steel02Parameters(**member["steel_member"])
    properties = MemberProperties.from_equal_angle(name=f'{section["section_name"]}-member{member["member_id"]}',
        length=member["length"], leg_width=leg, thickness=thickness, area=section["area"], inertia_weak=weak,
        elastic_modulus=steel.E0, yield_strength=steel.fy, steel_hardening_ratio=steel.b)
    return run_segmented_reference(properties, imperfection_ratio=imperfection_ratio,
        maximum_shortening=maximum_shortening, steps=steps, divisions=divisions,
        steel_parameters=steel, solver_config=ReferenceSolverConfig(), strict=False)


def run_recorded_replays(source: Path, history: Path, output: Path,
                         member_ids: Sequence[int] = (877, 825), *, boundary_substeps: int = 1,
                         compact_substeps: bool = False, remove_rigid_translation: bool = False) -> dict[str, Any]:
    """Run matching-mesh replays only; comparisons never imply full-protocol validity."""
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite replay evidence: {output}")
    output.mkdir(parents=True, exist_ok=True)
    catalog = MechanicalCatalog(source, output_dir=output / "parser")
    summaries = []
    plot_data = []
    for member_id in member_ids:
        member = catalog.member(member_id)
        boundary = load_recorded_boundary(history, member_id)
        recorded = boundary["source_metadata"]["members"][str(member_id)][0]
        if recorded["section_name"] != member["section"]["section_name"]:
            raise ValueError("Source section differs from the recorded member")
        recorded_fibers = boundary["source_metadata"].get("fibers", {}).get(str(recorded["section_tag"]), [])
        actual_fibers = np.array([[row["y"], row["z"], row["area"]] for row in member["fibers"]])
        expected_fibers = np.array([[row["y"], row["z"], row["area"]] for row in recorded_fibers])
        if actual_fibers.shape != expected_fibers.shape or not np.allclose(actual_fibers, expected_fibers, rtol=1e-12, atol=1e-15):
            raise ValueError("Recorded fiber mesh differs; select an explicit matching mechanical profile")
        if int(recorded["num_intgr_pts"]) != member["profile"]["integration_points"] or recorded["integration_type"] != member["profile"]["integration_type"]:
            raise ValueError("Recorded beam integration differs from the selected profile")
        dense = subdivide_boundary_points(boundary["points"], boundary_substeps)
        result = replay_boundary_history(member, dense, divisions=boundary["divisions"],
                                         exact_coordinates=boundary["exact_coordinates"],
                                         detail_stride=boundary_substeps if compact_substeps else 1,
                                         remove_rigid_translation=remove_rigid_translation)
        observed = np.array([row["end_global_internal_force"] for row in result["states"][::boundary_substeps]])
        reference = np.array([row["segments"][0]["global_force"][:6] + row["segments"][-1]["global_force"][6:]
                              for row in boundary["reference_states"][:len(observed)]])
        scale = np.tile([1.0, 1.0, 1.0, 1 / member["length"], 1 / member["length"], 1 / member["length"]], 2)
        denominator = np.linalg.norm(reference * scale)
        difference = np.linalg.norm((observed - reference) * scale)
        relative_error = float(difference / denominator) if denominator > 1e-12 else None
        axis = local_axes(member["coordinates"])[0]
        observed_axial = observed[:, 6:9] @ axis
        reference_axial = reference[:, 6:9] @ axis
        result["comparison"] = {
            "scaled_end_force_history_relative_error": relative_error,
            "maximum_end_force_absolute_difference_N": float(np.max(np.abs((observed - reference)[:, [0, 1, 2, 6, 7, 8]]))),
            "maximum_end_moment_absolute_difference_Nm": float(np.max(np.abs((observed - reference)[:, [3, 4, 5, 9, 10, 11]]))),
            "maximum_original_axis_force_difference_N": float(np.max(np.abs(observed_axial - reference_axial))),
            "comparison_coverage": len(observed) / len(boundary["points"]),
            "force_scaling": "translational N, rotational moment / original_member_length N",
            "same_mesh_replay_tolerance_1e_minus_6_passed": bool(result["execution_status"] == "completed" and relative_error is not None and relative_error <= 1e-6),
            "scope": "Only this recorded protocol; no mesh convergence or nonlinear holdout certification."}
        result["input_hashes"] = {"source": hashlib.sha256(source.read_bytes()).hexdigest(),
                                   "history": hashlib.sha256(history.read_bytes()).hexdigest(),
                                   "metadata": hashlib.sha256(history.with_suffix('.metadata.json').read_bytes()).hexdigest()}
        result["source_history"] = str(history)
        result["boundary_substeps_per_recorded_interval"] = boundary_substeps
        result["reference_point_state_indices"] = list(range(0, len(result["states"]), boundary_substeps))
        result["reference_end_global_internal_forces"] = reference.tolist()
        result["inferred_peak_imperfection_vector"] = (np.array(boundary["exact_coordinates"][boundary["divisions"] // 2])
                                                        - np.mean(member["coordinates"], axis=0)).tolist()
        (output / f"member_{member_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        summaries.append({"member_id": member_id, "section_name": member["section"]["section_name"],
                          "execution_status": result["execution_status"], "completed_steps": result["completed_steps"],
                          "maximum_fiber_stress_Pa": max(row["maximum_fiber_abs_stress"] for row in result["states"]),
                          **result["comparison"]})
        plot_data.append((member_id, reference_axial, observed_axial))
    summary = {"schema": "otw2.member_reference_replay_batch.v1", "source_history": str(history),
               "engine_version": ops.version(), "members": summaries,
               "boundary_substeps_per_recorded_interval": boundary_substeps,
               "removed_rigid_translation": remove_rigid_translation,
               "full_protocol_validation": False,
               "note": "This checks isolation and boundary reproduction, not the equivalence of a scalar material."}
    (output / "replay_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    figure, axes = plt.subplots(len(plot_data), 1, figsize=(9, 3 * len(plot_data)), squeeze=False, constrained_layout=True)
    for axis, (member_id, reference_axial, observed_axial) in zip(axes[:, 0], plot_data):
        axis.plot(reference_axial / 1000, label="Recorded tower member")
        axis.plot(observed_axial / 1000, "--", label="Isolated 6DOF replay")
        axis.set_title(f"Member {member_id}: matching-mesh boundary reproduction")
        axis.set_ylabel("Original-chord axial force (kN)")
        axis.set_xlabel("Committed sample index (not seconds)")
        axis.legend()
        axis.grid(alpha=0.2)
    figure.savefig(output / "boundary_replay.png", dpi=160)
    plt.close(figure)
    ops.wipe()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("Source/Z30103A6.s2k"))
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--members", type=int, nargs="+", default=[877, 825])
    parser.add_argument("--boundary-substeps", type=int, default=1)
    parser.add_argument("--compact-substeps", action="store_true")
    parser.add_argument("--remove-rigid-translation", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_recorded_replays(args.source, args.history, args.output, args.members,
                                          boundary_substeps=args.boundary_substeps,
                                          compact_substeps=args.compact_substeps,
                                          remove_rigid_translation=args.remove_rigid_translation), ensure_ascii=False))


if __name__ == "__main__":
    main()
