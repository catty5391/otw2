"""OpenSees validation experiments for the equivalent member constitutive law."""

from __future__ import annotations

import csv
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import openseespy.opensees as ops

from .material import (
    EquivalentImperfectionMaterial,
    MemberProperties,
    PushoverPoint,
    curve_area,
    ec3_reduction_factor,
    gb50017_reduction_factor,
)
from .visualization import create_all_figures
from util.postprocess.response_metrics import ResponseCurve, compare_curves
from .config import ReferenceSolverConfig
from .calibration_cache import ReferenceNonconvergence


@dataclass(frozen=True)
class AnalysisResult:
    """A curve plus an explicit convergence record."""

    curve: list[PushoverPoint]
    runtime_seconds: float
    requested_steps: int
    completed_steps: int
    converged: bool
    requested_end_shortening: float
    actual_end_shortening: float
    solver_settings: dict[str, Any] | None = None


@dataclass(frozen=True)
class CyclicPoint:
    """One signed compression-unloading history point; tension is positive."""

    stage: str
    axial_displacement: float
    axial_force: float
    strain: float
    stress: float
    midspan_lateral_displacement: float = 0.0
    maximum_abs_fiber_stress: float = 0.0


def _configure_static_analysis(node_tag: int, dof: int, increment: float,
                               solver_config: ReferenceSolverConfig | None = None) -> None:
    settings = solver_config or ReferenceSolverConfig.legacy()
    ops.system("BandGeneral")
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.test(settings.test_type, settings.tolerance, settings.max_iterations)
    ops.algorithm(*settings.algorithm)
    ops.integrator("DisplacementControl", node_tag, dof, increment)
    ops.analysis("Static")


def _analyze_one_step(solver_config: ReferenceSolverConfig | None = None) -> int:
    settings = solver_config or ReferenceSolverConfig.legacy()
    result = ops.analyze(1)
    if result == 0:
        return result
    try:
        ops.test(settings.test_type, settings.retry_tolerance, settings.retry_iterations)
        ops.algorithm(*settings.retry_algorithm)
        return ops.analyze(1)
    finally:
        ops.algorithm(*settings.algorithm)
        ops.test(settings.test_type, settings.tolerance, settings.max_iterations)


def _equal_angle_weak_axis_fibers(
    member: MemberProperties,
    *,
    long_divisions: int = 30,
    thickness_divisions: int = 3,
) -> list[tuple[float, float]]:
    """Return ``(weak_axis_coordinate, area)`` cells for an equal angle."""

    if member.leg_width is None or member.thickness is None:
        raise ValueError("分段基准模型需要 leg_width 和 thickness。")
    leg = member.leg_width
    thickness = member.thickness
    upper_divisions = max(1, round(long_divisions * (leg - thickness) / leg))
    rectangles = (
        (0.0, leg, 0.0, thickness, long_divisions, thickness_divisions),
        (0.0, thickness, thickness, leg, thickness_divisions, upper_divisions),
    )
    raw_cells: list[tuple[float, float, float]] = []
    for x0, x1, y0, y1, nx, ny in rectangles:
        cell_area = (x1 - x0) * (y1 - y0) / (nx * ny)
        for ix in range(nx):
            for iy in range(ny):
                x = x0 + (ix + 0.5) * (x1 - x0) / nx
                y = y0 + (iy + 0.5) * (y1 - y0) / ny
                raw_cells.append((x, y, cell_area))
    area = sum(cell[2] for cell in raw_cells)
    centroid_x = sum(x * cell_area for x, _, cell_area in raw_cells) / area
    centroid_y = sum(y * cell_area for _, y, cell_area in raw_cells) / area
    return [
        (((x - centroid_x) + (y - centroid_y)) / math.sqrt(2.0), cell_area)
        for x, y, cell_area in raw_cells
    ]


def section_discretization_check(
    member: MemberProperties,
    fibers: Sequence[tuple[float, float]] | None = None,
) -> dict[str, float | None]:
    """Report area and weak-axis inertia errors of the fiber discretization."""

    cells = list(fibers or _equal_angle_weak_axis_fibers(member))
    area = sum(cell_area for _, cell_area in cells)
    inertia = sum(coordinate**2 * cell_area for coordinate, cell_area in cells)
    return {
        "fiber_area": area,
        "area_error_percent": 100.0 * (area - member.area) / member.area,
        "fiber_inertia_weak": inertia,
        "inertia_error_percent": 100.0
        * (inertia - member.inertia_weak)
        / member.inertia_weak,
    }


def _build_segmented_reference_model(
    member: MemberProperties,
    *,
    imperfection_ratio: float,
    divisions: int,
    elastic_steel: bool = False,
    steel_parameters: Any = None,
) -> dict[str, Any]:
    if divisions < 2 or divisions % 2:
        raise ValueError("分段数必须是大于等于 2 的偶数，以保留跨中节点。")
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 3)
    e0 = imperfection_ratio * member.length
    for index in range(divisions + 1):
        station = index / divisions
        ops.node(index + 1, e0 * math.sin(math.pi * station), member.length * station)
    loaded_node = divisions + 1
    midspan_node = divisions // 2 + 1
    ops.fix(1, 1, 1, 0)
    ops.fix(loaded_node, 1, 0, 0)

    if elastic_steel:
        ops.uniaxialMaterial("Elastic", 1, member.elastic_modulus)
    elif steel_parameters is not None:
        if any(not math.isclose(a,b,rel_tol=1e-12) for a,b in (
            (steel_parameters.E0,member.elastic_modulus),
            (steel_parameters.fy,member.yield_strength),
            (steel_parameters.b,member.steel_hardening_ratio))):
            raise ValueError("Steel02 profile disagrees with MemberProperties")
        ops.uniaxialMaterial(*steel_parameters.opensees_arguments(1))
    else:
        ops.uniaxialMaterial(
            "Steel02",
            1,
            member.yield_strength,
            member.elastic_modulus,
            member.steel_hardening_ratio,
            20.0,
            0.925,
            0.15,
        )
    fibers = _equal_angle_weak_axis_fibers(member)
    ops.section("Fiber", 1)
    for coordinate, area in fibers:
        ops.fiber(coordinate, 0.0, area, 1)
    ops.geomTransf("Corotational", 1)
    element_tags: list[int] = []
    for index in range(divisions):
        element_tag = index + 1
        integration_tag = index + 1
        ops.beamIntegration("Legendre", integration_tag, 1, 6)
        ops.element(
            "dispBeamColumn",
            element_tag,
            index + 1,
            index + 2,
            1,
            integration_tag,
        )
        element_tags.append(element_tag)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(loaded_node, 0.0, -1.0, 0.0)
    return {
        "loaded_node": loaded_node,
        "midspan_node": midspan_node,
        "element_tags": element_tags,
        "fiber_coordinates": [coordinate for coordinate, _ in fibers],
        "integration_points": 6,
    }


def _build_truss_model(
    member: MemberProperties,
    material: EquivalentImperfectionMaterial | None,
    *,
    response_mode: str = "reversible",
) -> dict[str, Any]:
    ops.wipe()
    ops.model("basic", "-ndm", 1, "-ndf", 1)
    ops.node(1, 0.0)
    ops.node(2, member.length)
    ops.fix(1, 1)
    if material is None:
        ops.uniaxialMaterial(
            "Steel02",
            1,
            member.yield_strength,
            member.elastic_modulus,
            member.steel_hardening_ratio,
            20.0,
            0.925,
            0.15,
        )
    else:
        material.register_opensees(ops, 1, response_mode=response_mode)
    ops.element("corotTruss", 1, 1, 2, member.area, 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(2, -1.0)
    return {"loaded_node": 2}


def _maximum_abs_fiber_stress(model_data: dict[str, Any]) -> float:
    coordinates = model_data["fiber_coordinates"]
    probes = (min(coordinates), max(coordinates))
    maximum = 0.0
    for element_tag in model_data["element_tags"]:
        for section_number in range(1, model_data["integration_points"] + 1):
            for coordinate in probes:
                response = ops.eleResponse(
                    element_tag,
                    "section",
                    section_number,
                    "fiber",
                    coordinate,
                    0.0,
                    "stressStrain",
                )
                if response:
                    maximum = max(maximum, abs(float(response[0])))
    return maximum


def run_segmented_reference(
    member: MemberProperties,
    *,
    imperfection_ratio: float,
    maximum_shortening: float,
    steps: int,
    divisions: int = 16,
    strict: bool = True,
    solver_config: ReferenceSolverConfig | None = None,
    steel_parameters: Any = None,
) -> AnalysisResult:
    """Run a segmented reference consistent with the current tower element setup."""

    started = time.perf_counter()
    if isinstance(steps,bool) or int(steps)!=steps or steps<=0:
        raise ValueError("steps must be a positive integer")
    if not math.isfinite(maximum_shortening) or maximum_shortening<=0:
        raise ValueError("maximum_shortening must be positive and finite")
    model = _build_segmented_reference_model(
        member,
        imperfection_ratio=imperfection_ratio,
        divisions=divisions,
        steel_parameters=steel_parameters,
    )
    loaded_node = model["loaded_node"]
    settings = solver_config or ReferenceSolverConfig.legacy()
    _configure_static_analysis(loaded_node, 2, -maximum_shortening / steps, settings)
    curve: list[PushoverPoint] = []
    for _ in range(steps):
        if _analyze_one_step(settings) != 0:
            break
        curve.append(
            PushoverPoint(
                shortening=-float(ops.nodeDisp(loaded_node, 2)),
                force=float(ops.getLoadFactor(1)),
                midspan_lateral_displacement=float(ops.nodeDisp(model["midspan_node"], 1)),
            )
        )
    runtime = time.perf_counter() - started
    result = AnalysisResult(
        curve=curve,
        runtime_seconds=runtime,
        requested_steps=steps,
        completed_steps=len(curve),
        converged=len(curve) == steps,
        requested_end_shortening=maximum_shortening,
        actual_end_shortening=curve[-1].shortening if curve else 0.0,
        solver_settings=settings.to_dict(),
    )
    ops.wipe()
    if strict and not result.converged:
        raise ReferenceNonconvergence(result,
            f"{divisions} 段参考模型仅收敛 {result.completed_steps}/{steps} 步，"
            "禁止继续进行完整曲线误差评价。"
        )
    return result


def run_four_segment_reference(
    member: MemberProperties,
    *,
    imperfection_ratio: float,
    maximum_shortening: float,
    steps: int,
    strict: bool = True,
) -> AnalysisResult:
    """Backward-compatible explicit four-segment convergence run."""

    return run_segmented_reference(
        member,
        imperfection_ratio=imperfection_ratio,
        maximum_shortening=maximum_shortening,
        steps=steps,
        divisions=4,
        strict=strict,
    )


def run_truss_pushover(
    member: MemberProperties,
    *,
    maximum_shortening: float,
    steps: int,
    material: EquivalentImperfectionMaterial | None,
    response_mode: str = "reversible",
    strict: bool = True,
) -> AnalysisResult:
    """Run one corotTruss with Steel02 or an equivalent member law."""

    started = time.perf_counter()
    model = _build_truss_model(member, material, response_mode=response_mode)
    loaded_node = model["loaded_node"]
    _configure_static_analysis(loaded_node, 1, -maximum_shortening / steps)
    curve: list[PushoverPoint] = []
    for _ in range(steps):
        if _analyze_one_step() != 0:
            break
        curve.append(
            PushoverPoint(
                shortening=-float(ops.nodeDisp(loaded_node, 1)),
                force=float(ops.getLoadFactor(1)),
            )
        )
    runtime = time.perf_counter() - started
    result = AnalysisResult(
        curve=curve,
        runtime_seconds=runtime,
        requested_steps=steps,
        completed_steps=len(curve),
        converged=len(curve) == steps,
        requested_end_shortening=maximum_shortening,
        actual_end_shortening=curve[-1].shortening if curve else 0.0,
    )
    ops.wipe()
    if strict and not result.converged:
        raise RuntimeError(f"单单元模型仅收敛 {result.completed_steps}/{steps} 步。")
    return result


def _run_displacement_history(
    member: MemberProperties,
    model_data: dict[str, Any],
    *,
    dof: int,
    target_strains: Sequence[float],
    steps_per_segment: int,
    reference_model: bool,
) -> list[CyclicPoint]:
    loaded_node = model_data["loaded_node"]
    _configure_static_analysis(loaded_node, dof, -1e-12)
    history = [CyclicPoint("origin", 0.0, 0.0, 0.0, 0.0)]
    for segment_index, target_strain in enumerate(target_strains, start=1):
        target_displacement = target_strain * member.length
        current_displacement = float(ops.nodeDisp(loaded_node, dof))
        increment = (target_displacement - current_displacement) / steps_per_segment
        ops.integrator("DisplacementControl", loaded_node, dof, increment)
        stage = "compression" if increment < 0.0 else "unloading"
        for _ in range(steps_per_segment):
            if _analyze_one_step() != 0:
                raise RuntimeError(
                    f"循环路径第 {segment_index} 段未收敛，目标应变 {target_strain}。"
                )
            displacement = float(ops.nodeDisp(loaded_node, dof))
            axial_force = -float(ops.getLoadFactor(1))
            maximum_fiber_stress = (
                _maximum_abs_fiber_stress(model_data) if reference_model else 0.0
            )
            history.append(
                CyclicPoint(
                    stage=stage,
                    axial_displacement=displacement,
                    axial_force=axial_force,
                    strain=displacement / member.length,
                    stress=axial_force / member.area,
                    midspan_lateral_displacement=(
                        float(ops.nodeDisp(model_data["midspan_node"], 1))
                        if reference_model
                        else 0.0
                    ),
                    maximum_abs_fiber_stress=maximum_fiber_stress,
                )
            )
    return history


def run_pre_yield_unloading_check(
    member: MemberProperties,
    material: EquivalentImperfectionMaterial,
    *,
    imperfection_ratio: float,
    peak_compressive_strain: float = 0.0005,
    divisions: int = 16,
    steps_per_segment: int = 50,
) -> tuple[dict[str, list[CyclicPoint]], dict[str, Any]]:
    """Check that reversible geometric flexibility returns to zero force."""

    targets = (-abs(peak_compressive_strain), 0.0)
    reference_model = _build_segmented_reference_model(
        member,
        imperfection_ratio=imperfection_ratio,
        divisions=divisions,
    )
    reference = _run_displacement_history(
        member,
        reference_model,
        dof=2,
        target_strains=targets,
        steps_per_segment=steps_per_segment,
        reference_model=True,
    )
    ops.wipe()
    equivalent_model = _build_truss_model(member, material, response_mode="reversible")
    equivalent = _run_displacement_history(
        member,
        equivalent_model,
        dof=1,
        target_strains=targets,
        steps_per_segment=steps_per_segment,
        reference_model=False,
    )
    ops.wipe()
    legacy_model = _build_truss_model(member, material, response_mode="hysteretic")
    legacy = _run_displacement_history(
        member,
        legacy_model,
        dof=1,
        target_strains=targets,
        steps_per_segment=steps_per_segment,
        reference_model=False,
    )
    ops.wipe()

    peak_index = steps_per_segment
    maximum_fiber_stress = max(point.maximum_abs_fiber_stress for point in reference)
    summary = {
        "peak_compressive_strain": peak_compressive_strain,
        "reference_peak_force_abs": abs(reference[peak_index].axial_force),
        "equivalent_peak_force_abs": abs(equivalent[peak_index].axial_force),
        "legacy_hysteretic_peak_force_abs": abs(legacy[peak_index].axial_force),
        "reference_final_force": reference[-1].axial_force,
        "equivalent_final_force": equivalent[-1].axial_force,
        "legacy_hysteretic_final_force": legacy[-1].axial_force,
        "reference_maximum_abs_fiber_stress": maximum_fiber_stress,
        "reference_remained_elastic": maximum_fiber_stress < member.yield_strength,
        "acceptance_force_tolerance": 0.001 * member.squash_load,
    }
    summary["passed"] = (
        summary["reference_remained_elastic"]
        and abs(summary["reference_final_force"]) <= summary["acceptance_force_tolerance"]
        and abs(summary["equivalent_final_force"]) <= summary["acceptance_force_tolerance"]
    )
    return {
        "segmented_reference": reference,
        "equivalent_reversible": equivalent,
        "legacy_hysteretic": legacy,
    }, summary


def _comparison_metrics(
    reference: Sequence[PushoverPoint],
    candidate: Sequence[PushoverPoint],
) -> dict[str, float]:
    reference_curve = ResponseCurve.from_pairs((p.shortening, p.force) for p in reference)
    candidate_curve = ResponseCurve.from_pairs((p.shortening, p.force) for p in candidate)
    shared = compare_curves(reference_curve, candidate_curve)
    common_end = min(reference[-1].shortening, candidate[-1].shortening)
    common_start = max(reference[0].shortening, candidate[0].shortening)
    # Clip both starts as well, so unequal time/displacement meshes never extrapolate.
    reference_clipped = reference_curve.clip(common_start, common_end)
    candidate_clipped = candidate_curve.clip(common_start, common_end)
    reference_common = [PushoverPoint(shortening=x, force=y) for x, y in zip(
        reference_clipped.x, reference_clipped.y,
    )]
    candidate_common = [PushoverPoint(shortening=x, force=y) for x, y in zip(
        candidate_clipped.x, candidate_clipped.y,
    )]
    peak_reference = max(reference_common, key=lambda point: point.force)
    peak_candidate = max(candidate_common, key=lambda point: point.force)
    squared_errors = [
        (candidate_clipped.evaluate(point.shortening) - point.force) ** 2
        for point in reference_common
    ]
    rmse = math.sqrt(sum(squared_errors) / len(squared_errors))
    reference_stiffness = reference_common[0].force / reference_common[0].shortening
    candidate_stiffness = candidate_common[0].force / candidate_common[0].shortening
    metrics = {
        "common_start_shortening": common_start,
        "common_end_shortening": common_end,
        "domain_weighted_nrmse_percent": shared["domain_weighted_nrmse_percent"],
        "reference_coverage_percent": shared["reference_coverage_percent"],
        "candidate_coverage_percent": shared["candidate_coverage_percent"],
        "peak_force": peak_candidate.force,
        "peak_shortening": peak_candidate.shortening,
        "initial_stiffness": candidate_stiffness,
        "initial_stiffness_error_percent": 100.0
        * (candidate_stiffness - reference_stiffness)
        / reference_stiffness,
        "peak_force_error_percent": 100.0
        * (peak_candidate.force - peak_reference.force)
        / peak_reference.force,
        "peak_shortening_error_percent": 100.0
        * (peak_candidate.shortening - peak_reference.shortening)
        / peak_reference.shortening,
        "normalized_rmse_percent": 100.0 * rmse / peak_reference.force,
        "monotonic_work_error_percent": 100.0
        * (curve_area(candidate_common) - curve_area(reference_common))
        / curve_area(reference_common),
    }
    for multiple in (2.0, 4.0, 6.0):
        target = multiple * peak_reference.shortening
        if target <= common_end:
            reference_force = reference_clipped.evaluate(target)
            candidate_force = candidate_clipped.evaluate(target)
            metrics[f"force_error_at_{multiple:.0f}x_peak_shortening_percent"] = (
                100.0 * (candidate_force - reference_force) / reference_force
            )
    return metrics


def _result_status(result: AnalysisResult) -> dict[str, Any]:
    return {
        "requested_steps": result.requested_steps,
        "completed_steps": result.completed_steps,
        "converged": result.converged,
        "requested_end_shortening": result.requested_end_shortening,
        "actual_end_shortening": result.actual_end_shortening,
        "runtime_seconds": result.runtime_seconds,
    }


def _write_curves(path: Path, curves: dict[str, Sequence[PushoverPoint]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("model", "step", "shortening_m", "force_n", "midspan_displacement_m"),
            lineterminator="\n",
        )
        writer.writeheader()
        for name, curve in curves.items():
            for step, point in enumerate(curve, start=1):
                writer.writerow(
                    {
                        "model": name,
                        "step": step,
                        "shortening_m": point.shortening,
                        "force_n": point.force,
                        "midspan_displacement_m": point.midspan_lateral_displacement,
                    }
                )


def _write_cyclic_history(path: Path, histories: dict[str, Sequence[CyclicPoint]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        fields = ("model", "step", *asdict(next(iter(histories.values()))[0]).keys())
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for name, history in histories.items():
            for step, point in enumerate(history):
                writer.writerow({"model": name, "step": step, **asdict(point)})


def _write_backbones(
    path: Path,
    materials: dict[str, EquivalentImperfectionMaterial],
) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("material", "branch", "point", "strain", "stress_pa"),
            lineterminator="\n",
        )
        writer.writeheader()
        for name, material in materials.items():
            for branch, points in (
                ("tension", material.tension_envelope()),
                ("compression", material.compression_envelope),
            ):
                for index, point in enumerate(points, start=1):
                    writer.writerow(
                        {
                            "material": name,
                            "branch": branch,
                            "point": index,
                            "strain": point.strain,
                            "stress_pa": point.stress,
                        }
                    )


def _study_row(kind: str, divisions: int, steps: int, result: AnalysisResult) -> dict[str, Any]:
    peak = max(result.curve, key=lambda point: point.force)
    return {
        "study": kind,
        "divisions": divisions,
        "steps": steps,
        "completed_steps": result.completed_steps,
        "converged": result.converged,
        "peak_force_n": peak.force,
        "peak_shortening_m": peak.shortening,
        "runtime_seconds": result.runtime_seconds,
        "peak_force_error_vs_16_percent": "",
    }


def run_convergence_study(
    member: MemberProperties,
    *,
    imperfection_ratio: float,
    maximum_shortening: float,
    main_steps: int,
    reference_divisions: int,
) -> list[dict[str, Any]]:
    """Run explicit mesh and displacement-step convergence checks."""

    mesh_steps = max(400, main_steps // 2)
    rows: list[dict[str, Any]] = []
    cache: dict[tuple[int, int], AnalysisResult] = {}
    for divisions in (4, 8, 16):
        result = run_segmented_reference(
            member,
            imperfection_ratio=imperfection_ratio,
            maximum_shortening=maximum_shortening,
            steps=mesh_steps,
            divisions=divisions,
        )
        cache[(divisions, mesh_steps)] = result
        rows.append(_study_row("mesh", divisions, mesh_steps, result))
    for step_count in sorted({mesh_steps, main_steps}):
        result = cache.get((reference_divisions, step_count))
        if result is None:
            result = run_segmented_reference(
                member,
                imperfection_ratio=imperfection_ratio,
                maximum_shortening=maximum_shortening,
                steps=step_count,
                divisions=reference_divisions,
            )
        rows.append(_study_row("step", reference_divisions, step_count, result))
    mesh_rows = [row for row in rows if row["study"] == "mesh"]
    finest_peak = float(mesh_rows[-1]["peak_force_n"])
    for row in mesh_rows:
        row["peak_force_error_vs_16_percent"] = 100.0 * (
            float(row["peak_force_n"]) - finest_peak
        ) / finest_peak
    return rows


def extract_actual_section_lengths(
    s2k_path: str | Path,
    section_name: str,
) -> list[dict[str, float | int]]:
    """Extract actual member lengths for one assigned section from an S2K file."""

    text = Path(s2k_path).read_text(encoding="utf-8", errors="ignore")
    connectivity_block = text.split('TABLE:  "CONNECTIVITY - FRAME"', 1)[1].split(
        "TABLE:", 1
    )[0]
    assignment_block = text.split('TABLE:  "FRAME SECTION ASSIGNMENTS"', 1)[1].split(
        "TABLE:", 1
    )[0]
    lengths: dict[int, float] = {}
    for line in connectivity_block.splitlines():
        frame = re.search(r"Frame=(\d+)", line)
        length = re.search(r"Length=([0-9.Ee+-]+)", line)
        if frame and length:
            lengths[int(frame.group(1))] = float(length.group(1))
    frames: list[int] = []
    for line in assignment_block.splitlines():
        if f"AnalSect={section_name}" not in line:
            continue
        frame = re.search(r"Frame=(\d+)", line)
        if frame:
            frames.append(int(frame.group(1)))
    return [{"frame": frame, "length": lengths[frame]} for frame in frames if frame in lengths]


def _actual_member_screening(
    s2k_path: Path,
    *,
    imperfection_ratio: float,
) -> list[dict[str, Any]]:
    rows = extract_actual_section_lengths(s2k_path, "L125x8Q345")
    for row in rows:
        member = MemberProperties.z30103a6_l125x8(length=float(row["length"]))
        perry = EquivalentImperfectionMaterial.from_perry(
            member,
            imperfection_ratio=imperfection_ratio,
        )
        row.update(
            slenderness_ratio=member.slenderness_ratio,
            non_dimensional_slenderness=member.non_dimensional_slenderness,
            euler_load_n=member.euler_load,
            perry_first_yield_load_n=perry.peak_compressive_load,
        )
    return rows


def run_actual_member_validation(
    actual_members: Sequence[dict[str, Any]],
    *,
    imperfection_ratio: float,
    maximum_strain: float,
    divisions: int = 16,
    steps: int = 400,
) -> list[dict[str, Any]]:
    """Validate minimum/median/maximum actual L125x8 member lengths."""

    lengths = sorted(float(row["length"]) for row in actual_members)
    representatives = (
        ("minimum", lengths[0]),
        ("median", lengths[len(lengths) // 2]),
        ("maximum", lengths[-1]),
    )
    rows: list[dict[str, Any]] = []
    for label, length in representatives:
        member = MemberProperties.z30103a6_l125x8(length=length)
        maximum_shortening = maximum_strain * length
        reference = run_segmented_reference(
            member,
            imperfection_ratio=imperfection_ratio,
            maximum_shortening=maximum_shortening,
            steps=steps,
            divisions=divisions,
        )
        material = EquivalentImperfectionMaterial.from_reference_curve(
            member,
            reference.curve,
            imperfection_ratio=imperfection_ratio,
        )
        equivalent = run_truss_pushover(
            member,
            maximum_shortening=maximum_shortening,
            steps=steps,
            material=material,
        )
        metrics = _comparison_metrics(reference.curve, equivalent.curve)
        rows.append(
            {
                "representative": label,
                "length_m": length,
                "slenderness_ratio": member.slenderness_ratio,
                "reference_peak_force_n": max(point.force for point in reference.curve),
                "peak_force_error_percent": metrics["peak_force_error_percent"],
                "normalized_rmse_percent": metrics["normalized_rmse_percent"],
                "monotonic_work_error_percent": metrics["monotonic_work_error_percent"],
                "reference_converged": reference.converged,
                "equivalent_converged": equivalent.converged,
            }
        )
    return rows


def _write_dict_rows(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_experiment(
    output_dir: str | Path | None = None,
    *,
    imperfection_ratio: float = 1.0 / 1000.0,
    length: float = 3.0,
    maximum_strain: float = 0.03,
    steps: int = 800,
    reference_divisions: int = 16,
    run_convergence: bool = True,
    run_actual_validation: bool = True,
) -> dict[str, Any]:
    """Run monotonic, unloading, convergence and actual-member checks."""

    if steps < 50:
        raise ValueError("为识别峰值，steps 不应小于 50。")
    member = MemberProperties.z30103a6_l125x8(length=length)
    destination = Path(output_dir) if output_dir else Path(__file__).with_name("results")
    destination.mkdir(parents=True, exist_ok=True)
    maximum_shortening = maximum_strain * member.length

    reference_result = run_segmented_reference(
        member,
        imperfection_ratio=imperfection_ratio,
        maximum_shortening=maximum_shortening,
        steps=steps,
        divisions=reference_divisions,
    )
    calibrated_material = EquivalentImperfectionMaterial.from_reference_curve(
        member,
        reference_result.curve,
        imperfection_ratio=imperfection_ratio,
    )
    perry_material = EquivalentImperfectionMaterial.from_perry(
        member,
        imperfection_ratio=imperfection_ratio,
    )
    calibrated_result = run_truss_pushover(
        member,
        maximum_shortening=maximum_shortening,
        steps=steps,
        material=calibrated_material,
    )
    perry_result = run_truss_pushover(
        member,
        maximum_shortening=maximum_shortening,
        steps=steps,
        material=perry_material,
    )
    perfect_result = run_truss_pushover(
        member,
        maximum_shortening=maximum_shortening,
        steps=steps,
        material=None,
    )
    curves = {
        "segmented_reference": reference_result.curve,
        "equivalent_calibrated": calibrated_result.curve,
        "equivalent_perry": perry_result.curve,
        "perfect_steel_corot_truss": perfect_result.curve,
    }
    materials = {
        "equivalent_calibrated": calibrated_material,
        "equivalent_perry": perry_material,
    }

    cyclic_histories, unloading_summary = run_pre_yield_unloading_check(
        member,
        calibrated_material,
        imperfection_ratio=imperfection_ratio,
        divisions=reference_divisions,
    )
    convergence = (
        run_convergence_study(
            member,
            imperfection_ratio=imperfection_ratio,
            maximum_shortening=maximum_shortening,
            main_steps=steps,
            reference_divisions=reference_divisions,
        )
        if run_convergence
        else []
    )

    sensitivity_ratios = (1 / 2000, 1 / 1000, 1 / 500, 1 / 350, 1 / 250, 1 / 100)
    sensitivity = []
    for ratio in sensitivity_ratios:
        trial = EquivalentImperfectionMaterial.from_perry(member, imperfection_ratio=ratio)
        sensitivity.append(
            {
                "imperfection_ratio": ratio,
                "imperfection_denominator": 1.0 / ratio,
                "peak_load": trial.peak_compressive_load,
                "peak_ratio_to_squash": trial.peak_compressive_load / member.squash_load,
            }
        )

    root = Path(__file__).resolve().parents[1]
    actual_members = _actual_member_screening(
        root / "Source" / "Z30103A6.s2k",
        imperfection_ratio=imperfection_ratio,
    )
    lengths = sorted(float(row["length"]) for row in actual_members)
    actual_member_summary = {
        "section": "L125x8Q345",
        "count": len(lengths),
        "minimum_length": min(lengths),
        "median_length": lengths[len(lengths) // 2],
        "maximum_length": max(lengths),
        "minimum_slenderness": min(float(row["slenderness_ratio"]) for row in actual_members),
        "maximum_slenderness": max(float(row["slenderness_ratio"]) for row in actual_members),
    }
    actual_validation = (
        run_actual_member_validation(
            actual_members,
            imperfection_ratio=imperfection_ratio,
            maximum_strain=maximum_strain,
            divisions=reference_divisions,
            steps=max(400, steps // 2),
        )
        if run_actual_validation
        else []
    )

    slenderness = member.non_dimensional_slenderness
    results = {
        "segmented_reference": reference_result,
        "equivalent_calibrated": calibrated_result,
        "equivalent_perry": perry_result,
        "perfect_steel_corot_truss": perfect_result,
    }
    summary: dict[str, Any] = {
        "member": member.to_dict(),
        "section_discretization": section_discretization_check(member),
        "experiment": {
            "imperfection_ratio": imperfection_ratio,
            "imperfection_amplitude": imperfection_ratio * member.length,
            "maximum_shortening": maximum_shortening,
            "steps": steps,
            "reference_divisions": reference_divisions,
            "reference_element": "dispBeamColumn",
            "beam_integration": "Legendre-6",
            "equivalent_element": "corotTruss",
            "equivalent_response_mode": "reversible ElasticMultiLinear",
        },
        "theory": {
            "gb50017_curve_a_factor": gb50017_reduction_factor(slenderness, "a"),
            "gb50017_curve_a_load": gb50017_reduction_factor(slenderness, "a")
            * member.squash_load,
            "ec3_curve_b_factor": ec3_reduction_factor(slenderness, 0.34),
            "ec3_curve_b_load": ec3_reduction_factor(slenderness, 0.34) * member.squash_load,
            "perry_first_yield_load": perry_material.peak_compressive_load,
        },
        "analysis_status": {name: _result_status(result) for name, result in results.items()},
        "metrics": {
            name: _comparison_metrics(reference_result.curve, result.curve)
            for name, result in results.items()
            if name != "segmented_reference"
        },
        "pre_yield_unloading": unloading_summary,
        "convergence": convergence,
        "actual_member_screening": actual_member_summary,
        "actual_member_validation": actual_validation,
        "materials": {name: material.to_dict() for name, material in materials.items()},
        "sensitivity": sensitivity,
    }

    _write_curves(destination / "pushover_curves.csv", curves)
    _write_cyclic_history(destination / "pre_yield_unloading.csv", cyclic_histories)
    _write_backbones(destination / "material_backbones.csv", materials)
    _write_dict_rows(destination / "imperfection_sensitivity.csv", sensitivity)
    _write_dict_rows(destination / "convergence_study.csv", convergence)
    _write_dict_rows(destination / "actual_l125x8_members.csv", actual_members)
    _write_dict_rows(destination / "actual_member_validation.csv", actual_validation)
    with (destination / "summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)

    create_all_figures(
        destination,
        member,
        curves,
        materials,
        summary,
        cyclic_histories=cyclic_histories,
    )
    return summary
