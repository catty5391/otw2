"""OpenSees single-angle compression experiment and result export."""

from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

import openseespy.opensees as ops

from .material import (
    BackbonePoint,
    EquivalentImperfectionMaterial,
    MemberProperties,
    PushoverPoint,
    curve_area,
    ec3_reduction_factor,
    gb50017_reduction_factor,
)
from .visualization import create_all_figures


def _configure_static_analysis(node_tag: int, dof: int, increment: float) -> None:
    ops.system("BandGeneral")
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.test("NormDispIncr", 1e-8, 100)
    ops.algorithm("Newton")
    ops.integrator("DisplacementControl", node_tag, dof, increment)
    ops.analysis("Static")


def _analyze_one_step() -> int:
    result = ops.analyze(1)
    if result == 0:
        return result
    ops.test("NormDispIncr", 1e-7, 250)
    ops.algorithm("NewtonLineSearch", 0.8)
    result = ops.analyze(1)
    ops.algorithm("Newton")
    ops.test("NormDispIncr", 1e-8, 100)
    return result


def _equal_angle_weak_axis_fibers(
    member: MemberProperties,
    *,
    long_divisions: int = 30,
    thickness_divisions: int = 3,
) -> list[tuple[float, float]]:
    """Return ``(weak_axis_coordinate, area)`` cells for an equal angle."""

    if member.leg_width is None or member.thickness is None:
        raise ValueError("四分段基准模型需要 leg_width 和 thickness。")
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


def run_four_segment_reference(
    member: MemberProperties,
    *,
    imperfection_ratio: float,
    maximum_shortening: float,
    steps: int,
) -> tuple[list[PushoverPoint], float]:
    """Run the existing modelling idea on a deterministic four-segment member."""

    started = time.perf_counter()
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 3)
    divisions = 4
    e0 = imperfection_ratio * member.length
    for index in range(divisions + 1):
        station = index / divisions
        x = e0 * math.sin(math.pi * station)
        ops.node(index + 1, x, member.length * station)
    ops.fix(1, 1, 1, 0)
    ops.fix(divisions + 1, 1, 0, 0)

    material_tag = 1
    section_tag = 1
    transformation_tag = 1
    integration_tag = 1
    ops.uniaxialMaterial(
        "Steel02",
        material_tag,
        member.yield_strength,
        member.elastic_modulus,
        0.005,
        20.0,
        0.925,
        0.15,
    )
    ops.section("Fiber", section_tag)
    for coordinate, area in _equal_angle_weak_axis_fibers(member):
        ops.fiber(coordinate, 0.0, area, material_tag)
    ops.geomTransf("Corotational", transformation_tag)
    ops.beamIntegration("Lobatto", integration_tag, section_tag, 5)
    for index in range(divisions):
        ops.element(
            "forceBeamColumn",
            index + 1,
            index + 1,
            index + 2,
            transformation_tag,
            integration_tag,
        )

    loaded_node = divisions + 1
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(loaded_node, 0.0, -1.0, 0.0)
    _configure_static_analysis(loaded_node, 2, -maximum_shortening / steps)

    curve: list[PushoverPoint] = []
    for _ in range(steps):
        if _analyze_one_step() != 0:
            break
        curve.append(
            PushoverPoint(
                shortening=-float(ops.nodeDisp(loaded_node, 2)),
                force=max(0.0, float(ops.getLoadFactor(1))),
                midspan_lateral_displacement=float(ops.nodeDisp(3, 1)),
            )
        )
    ops.wipe()
    if len(curve) < max(10, steps // 4):
        raise RuntimeError(f"四分段基准模型仅收敛 {len(curve)}/{steps} 步。")
    return curve, time.perf_counter() - started


def run_truss_pushover(
    member: MemberProperties,
    *,
    maximum_shortening: float,
    steps: int,
    material: EquivalentImperfectionMaterial | None,
) -> tuple[list[PushoverPoint], float]:
    """Run one two-node truss with either Steel02 or the new member material."""

    started = time.perf_counter()
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
            0.005,
            20.0,
            0.925,
            0.15,
        )
    else:
        material.register_opensees(ops, 1)
    ops.element("truss", 1, 1, 2, member.area, 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(2, -1.0)
    _configure_static_analysis(2, 1, -maximum_shortening / steps)

    curve: list[PushoverPoint] = []
    for _ in range(steps):
        if _analyze_one_step() != 0:
            break
        curve.append(
            PushoverPoint(
                shortening=-float(ops.nodeDisp(2, 1)),
                force=max(0.0, float(ops.getLoadFactor(1))),
            )
        )
    ops.wipe()
    if len(curve) < steps:
        raise RuntimeError(f"单单元模型仅收敛 {len(curve)}/{steps} 步。")
    return curve, time.perf_counter() - started


def _interpolated_force(curve: Sequence[PushoverPoint], shortening: float) -> float:
    return EquivalentImperfectionMaterial._interpolate_force(curve, shortening)


def _comparison_metrics(
    reference: Sequence[PushoverPoint],
    candidate: Sequence[PushoverPoint],
) -> dict[str, float]:
    peak_reference = max(reference, key=lambda point: point.force)
    peak_candidate = max(candidate, key=lambda point: point.force)
    squared_errors = [
        (_interpolated_force(candidate, point.shortening) - point.force) ** 2
        for point in reference
    ]
    rmse = math.sqrt(sum(squared_errors) / len(squared_errors))
    reference_stiffness = reference[0].force / reference[0].shortening
    candidate_stiffness = candidate[0].force / candidate[0].shortening
    metrics = {
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
        "curve_area_error_percent": 100.0
        * (curve_area(candidate) - curve_area(reference))
        / curve_area(reference),
    }
    for multiple in (2.0, 4.0, 6.0):
        target = multiple * peak_reference.shortening
        reference_force = _interpolated_force(reference, target)
        candidate_force = _interpolated_force(candidate, target)
        metrics[f"force_error_at_{multiple:.0f}x_peak_shortening_percent"] = (
            100.0 * (candidate_force - reference_force) / reference_force
        )
    return metrics


def _write_curves(path: Path, curves: dict[str, Sequence[PushoverPoint]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("model", "step", "shortening_m", "force_n", "midspan_displacement_m"),
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


def _write_backbones(
    path: Path,
    materials: dict[str, EquivalentImperfectionMaterial],
) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=("material", "branch", "point", "strain", "stress_pa"))
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


def run_experiment(
    output_dir: str | Path | None = None,
    *,
    imperfection_ratio: float = 1.0 / 1000.0,
    length: float = 3.0,
    maximum_strain: float = 0.03,
    steps: int = 400,
) -> dict[str, Any]:
    """Run all comparisons, export data and create the figures."""

    if steps < 50:
        raise ValueError("为识别峰值，steps 不应小于 50。")
    member = MemberProperties.z30103a6_l125x8(length=length)
    destination = Path(output_dir) if output_dir else Path(__file__).with_name("results")
    destination.mkdir(parents=True, exist_ok=True)
    maximum_shortening = maximum_strain * member.length

    reference, reference_time = run_four_segment_reference(
        member,
        imperfection_ratio=imperfection_ratio,
        maximum_shortening=maximum_shortening,
        steps=steps,
    )
    calibrated_material = EquivalentImperfectionMaterial.from_reference_curve(
        member,
        reference,
        imperfection_ratio=imperfection_ratio,
    )
    perry_material = EquivalentImperfectionMaterial.from_perry(
        member,
        imperfection_ratio=imperfection_ratio,
    )
    calibrated, calibrated_time = run_truss_pushover(
        member,
        maximum_shortening=maximum_shortening,
        steps=steps,
        material=calibrated_material,
    )
    perry, perry_time = run_truss_pushover(
        member,
        maximum_shortening=maximum_shortening,
        steps=steps,
        material=perry_material,
    )
    perfect, perfect_time = run_truss_pushover(
        member,
        maximum_shortening=maximum_shortening,
        steps=steps,
        material=None,
    )
    curves = {
        "four_segment_reference": reference,
        "equivalent_calibrated": calibrated,
        "equivalent_perry": perry,
        "perfect_steel_truss": perfect,
    }
    materials = {
        "equivalent_calibrated": calibrated_material,
        "equivalent_perry": perry_material,
    }

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

    slenderness = member.non_dimensional_slenderness
    summary: dict[str, Any] = {
        "member": member.to_dict(),
        "experiment": {
            "imperfection_ratio": imperfection_ratio,
            "imperfection_amplitude": imperfection_ratio * member.length,
            "maximum_shortening": maximum_shortening,
            "steps": steps,
        },
        "theory": {
            "gb50017_curve_a_factor": gb50017_reduction_factor(slenderness, "a"),
            "gb50017_curve_a_load": gb50017_reduction_factor(slenderness, "a")
            * member.squash_load,
            "ec3_curve_b_factor": ec3_reduction_factor(slenderness, 0.34),
            "ec3_curve_b_load": ec3_reduction_factor(slenderness, 0.34) * member.squash_load,
            "perry_first_yield_load": perry_material.peak_compressive_load,
        },
        "metrics": {
            "equivalent_calibrated": _comparison_metrics(reference, calibrated),
            "equivalent_perry": _comparison_metrics(reference, perry),
            "perfect_steel_truss": _comparison_metrics(reference, perfect),
        },
        "runtime_seconds": {
            "four_segment_reference": reference_time,
            "equivalent_calibrated": calibrated_time,
            "equivalent_perry": perry_time,
            "perfect_steel_truss": perfect_time,
        },
        "materials": {name: material.to_dict() for name, material in materials.items()},
        "sensitivity": sensitivity,
    }

    _write_curves(destination / "pushover_curves.csv", curves)
    _write_backbones(destination / "material_backbones.csv", materials)
    with (destination / "imperfection_sensitivity.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(sensitivity[0]))
        writer.writeheader()
        writer.writerows(sensitivity)
    with (destination / "summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)

    create_all_figures(destination, member, curves, materials, summary)
    return summary
