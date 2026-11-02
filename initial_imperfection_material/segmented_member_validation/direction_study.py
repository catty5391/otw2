"""Direction/amplitude experiments using the shared spatial-member mechanics.

This studies isolated, pinned members with the current tower section orientation.
The seed reproduces the complete S2K traversal, not a new per-member draw.
No result here identifies actual installation angles or whole-tower capacity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from model.mechanical_profile import MechanicalCatalog, MechanicalProfile, local_axes

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMBER_IDS = (349, 920, 292)
DIRECTIONS = ("weak_plus", "weak_minus", "legacy_seed30103")
RATIOS = (0.0005, 0.001, 0.002)


def principal_directions(fibers: Sequence[dict[str, float]]) -> dict[str, Any]:
    """Return the weak *bending axis* and its perpendicular bow displacement.

    For physical moment/curvature components (My, Mz), the inertia matrix is
    [[integral(z²), -integral(yz)], [-integral(yz), integral(y²)]]. If transverse
    displacement is d=(dy,dz), its bending axis is x cross d=(-dz,dy).
    The canonical sign is set on d, since eigenvector signs are arbitrary.
    """
    if not fibers:
        raise ValueError("At least one fiber is required")
    rows = np.array([[f["y"], f["z"], f["area"]] for f in fibers], dtype=float)
    if not np.isfinite(rows).all() or np.any(rows[:, 2] <= 0):
        raise ValueError("Fibers must be finite and have positive areas")
    area = float(np.sum(rows[:, 2]))
    centroid = np.sum(rows[:, :2] * rows[:, 2, None], axis=0) / area
    yz = rows[:, :2] - centroid
    integral_y2 = float(np.sum(yz[:, 0] ** 2 * rows[:, 2]))
    integral_z2 = float(np.sum(yz[:, 1] ** 2 * rows[:, 2]))
    integral_yz = float(np.sum(yz[:, 0] * yz[:, 1] * rows[:, 2]))
    bending = np.array([[integral_z2, -integral_yz], [-integral_yz, integral_y2]])
    eigenvalues, axes = np.linalg.eigh(bending)
    if eigenvalues[0] <= 0 or math.isclose(eigenvalues[0], eigenvalues[1], rel_tol=1e-10, abs_tol=0):
        raise ValueError("A distinct positive weak principal inertia is required")
    weak_axis = axes[:, 0]
    displacement = np.array([weak_axis[1], -weak_axis[0]])
    first_nonzero = displacement[np.flatnonzero(np.abs(displacement) > 1e-12)[0]]
    if first_nonzero < 0:
        displacement *= -1
    weak_axis = np.array([-displacement[1], displacement[0]])
    return {"area_m2": area, "centroid_yz_m": centroid.tolist(),
            "physical_bending_inertia_yz_m4": bending.tolist(),
            "weak_inertia_m4": float(eigenvalues[0]), "strong_inertia_m4": float(eigenvalues[1]),
            "weak_bending_axis_yz": weak_axis.tolist(),
            "weak_displacement_yz": displacement.tolist(),
            "definition": "bending_axis = chord_x cross transverse_displacement; these directions are perpendicular"}


def section_orientation_roll(member: dict[str, Any], vector: Sequence[float], divisions: int) -> dict[str, Any]:
    """Audit reference-axis roll relative to minimal-rotation transport.

    Current tower rebuilds each segment reference from a global auxiliary axis.
    This quantity is geometric reference-frame roll, not a measured twist strain.
    """
    if isinstance(divisions, bool) or int(divisions) != divisions or divisions < 2:
        raise ValueError("divisions must be an integer >= 2")
    points = np.asarray(member["coordinates"], dtype=float)
    vector = np.asarray(vector, dtype=float)
    original = local_axes(points)
    if vector.shape != (3,) or not np.isfinite(vector).all():
        raise ValueError("Finite three-dimensional imperfection vector required")
    if abs(float(vector @ original[0])) > 1e-10 * max(1., np.linalg.norm(vector)):
        raise ValueError("Imperfection must be transverse")
    stations = np.linspace(0., 1., divisions + 1)
    coordinates = ((1 - stations[:, None]) * points[0] + stations[:, None] * points[1]
                   + np.sin(np.pi * stations[:, None]) * vector)
    rolls = []
    for left, right in zip(coordinates[:-1], coordinates[1:]):
        segment = local_axes([left, right])
        v = np.cross(original[0], segment[0])
        c = float(original[0] @ segment[0])
        if c <= -1 + 1e-10:
            raise ValueError("Cannot transport frame across an antiparallel segment")
        cross = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        rotation = np.eye(3) + cross + cross @ cross / (1 + c)
        transported_y = rotation @ original[1]
        transported_z = rotation @ original[2]
        rolls.append(math.degrees(math.atan2(float(segment[1] @ transported_z),
                                            float(segment[1] @ transported_y))))
    return {"segment_roll_degrees": rolls,
            "maximum_absolute_roll_degrees": max(abs(value) for value in rolls),
            "definition": "reference section roll relative to minimal-rotation transport of the original chord axes",
            "note": "current tower per-segment global auxiliary reference retained; not an installation-angle measurement or constitutive torsion strain"}


def build_case_matrix(catalog: MechanicalCatalog, member_ids: Sequence[int] = DEFAULT_MEMBER_IDS,
                      *, ratios: Sequence[float] = RATIOS, divisions: int = 16) -> list[dict[str, Any]]:
    if not ratios or any(not math.isfinite(ratio) or ratio <= 0 for ratio in ratios):
        raise ValueError("Positive finite imperfection ratios required")
    if catalog.profile.imperfection_seed != 30103 or catalog.profile.imperfection_ratio <= 0:
        raise ValueError("The legacy comparison requires seed 30103 and positive reference amplitude")
    vectors = catalog.imperfection_vectors()
    cases = []
    for member_id in member_ids:
        member = catalog.member(member_id)
        axes = local_axes(member["coordinates"])
        principal = principal_directions(member["fibers"])
        weak = np.asarray(principal["weak_displacement_yz"]) @ axes[1:]
        random_vector = np.asarray(vectors[member_id])
        random_unit = random_vector / np.linalg.norm(random_vector)
        for name, unit in zip(DIRECTIONS, (weak, -weak, random_unit)):
            local_unit = axes @ unit
            weak_angle = math.degrees(math.acos(np.clip(abs(float(unit @ weak)), 0, 1)))
            for ratio in ratios:
                vector = unit * member["length"] * ratio
                ratio_label = f"r{int(round(ratio * 1e6)):04d}"
                cases.append({"key": f"member_{member_id}_{name}_{ratio_label}",
                    "member_id": member_id, "section_name": member["section"]["section_name"],
                    "length_m": member["length"], "direction": name, "divisions": divisions,
                    "imperfection_ratio": ratio, "peak_bow_m": member["length"] * ratio,
                    "unit_direction_global": unit.tolist(), "unit_direction_local_xyz": local_unit.tolist(),
                    "imperfection_vector_global_m": vector.tolist(),
                    "angle_to_weak_displacement_line_degrees": weak_angle,
                    "principal_direction": principal,
                    "orientation_audit": section_orientation_roll(member, vector, divisions),
                    "seed": 30103 if name == "legacy_seed30103" else None,
                    "seed_scope": "complete original S2K member traversal before selecting representatives",
                    "profile": member["profile"], "steel_parameters": member["steel_tower"],
                    "source_coordinates_m": member["coordinates"]})
    return cases


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results" / "direction")
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    source = ROOT / "Source" / "Z30103A6.s2k"
    profile = MechanicalProfile(name="aligned_v1", long_edge_segments=32, short_edge_segments=4)
    catalog = MechanicalCatalog(source, output_dir=args.output / "parser", profile=profile)
    cases = build_case_matrix(catalog)
    plan = {"schema": "otw2.segmented_member_direction_plan.v1", "member_ids": list(DEFAULT_MEMBER_IDS),
            "case_count": len(cases), "cases": cases, "steps": args.steps,
            "source": str(source.relative_to(ROOT)), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "boundary": "isolated spatial pin-ended member; torsional rigid motion restrained at one end",
            "scope": "numerical direction/amplitude sensitivity, not whole-tower or experimental validation",
            "material_orientation": "current tower coordinate-derived orientation; actual S2K installation-angle equivalence not established"}
    write_json(args.output / "direction_plan.json", plan)
    if args.plan_only:
        print(json.dumps({"planned_cases": len(cases), "output": str(args.output)}, ensure_ascii=False), flush=True)
        return
    run_study(catalog, cases, args.output, steps=args.steps)
    finalize_study(args.output)


def run_study(catalog: MechanicalCatalog, cases: list[dict[str, Any]], output: Path, *, steps: int = 400) -> None:
    from .mechanics import run_case

    results = []
    for case in cases:
        print(json.dumps({"event": "direction_case_started", "key": case["key"]}), flush=True)
        result = run_case(catalog.member(case["member_id"]), output=output / "runs" / case["key"],
            divisions=case["divisions"], imperfection_ratio=case["imperfection_ratio"],
            unit_direction_global=case["unit_direction_global"], loading="monotonic", steps=steps)
        results.append({"case": case, "summary": result["summary"]})
        write_json(output / "direction_summary.json", {"schema": "otw2.segmented_member_direction.v1",
            "requested_cases": len(cases), "executed_cases": len(results), "cases": results,
            "physical_validation": False, "full_tower_validation": False})
        print(json.dumps({"event": "direction_case_finished", "key": case["key"], "summary": result["summary"]}), flush=True)


def read_comparison_history(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = []
        for row in csv.DictReader(stream):
            if row["requested_point"] not in ("True", "False"):
                raise ValueError("Unexpected requested_point boolean in ordered history")
            rows.append({"target_index": int(row["target_index"]),
                         "requested_point": row["requested_point"] == "True",
                         "strain": float(row["strain"]), "force_N": float(row["force_N"])})
        return rows


def finalize_study(output: Path) -> dict[str, Any]:
    """Add only common, ordered-point metrics and observed geometric evidence."""
    from .mechanics import compare_histories

    path = output / "direction_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    records = summary["cases"]
    for record in records:
        folder = output / "runs" / record["case"]["key"]
        history_path = folder / "history.csv"
        case_summary_path = folder / "summary.json"
        with history_path.open(encoding="utf-8", newline="") as stream:
            raw_rows = list(csv.DictReader(stream))
        peak = min(raw_rows, key=lambda row: float(row["force_N"]))
        peak_force, last_force = float(peak["force_N"]), float(raw_rows[-1]["force_N"])
        peak_sequence = int(peak["sequence"])
        monotonic = record["summary"]["loading"] == "monotonic"
        added = {"peak_sequence": peak_sequence, "peak_target_index": int(peak["target_index"]),
            "observed_monotonic_postpeak_drop_ratio": (last_force - peak_force) / abs(peak_force)
                if monotonic and peak_force < 0 else None,
            "observed_descending_branch": bool(monotonic and peak_force < 0
                and len(raw_rows) - 1 - peak_sequence >= 3 and last_force - peak_force > .01 * abs(peak_force)),
            "peak_semantics": "Maximum sampled compression on the completed prefix; not automatically a buckling capacity"}
        original_summary_hash = record["summary"].get("history_postprocessing", {}).get("original_solver_summary_sha256",
            hashlib.sha256(case_summary_path.read_bytes()).hexdigest())
        record["summary"].update(added)
        record["summary"]["history_postprocessing"] = {
            "fields": list(added), "source": "history.csv", "source_sha256": hashlib.sha256(history_path.read_bytes()).hexdigest(),
            "original_solver_summary_sha256": original_summary_hash,
            "note": "Derived from preserved committed history after execution; no finite-element rerun or altered force/displacement records"}
        write_json(case_summary_path, record["summary"])
    histories = {r["case"]["key"]: read_comparison_history(output / "runs" / r["case"]["key"] / "history.csv")
                 for r in records}
    index = {(r["case"]["member_id"], r["case"]["direction"], r["case"]["imperfection_ratio"]): r for r in records}
    comparisons = []
    same_amplitude = []
    geometry = []
    for record in records:
        case, result = record["case"], record["summary"]
        member_id = case["member_id"]
        ref = index.get((member_id, "weak_plus", .001))
        normalization = case["principal_direction"]["area_m2"] * case["steel_parameters"]["fy"]
        if ref is not None:
            comparisons.append({"candidate_key": case["key"], "reference_key": ref["case"]["key"],
                **compare_histories(histories[ref["case"]["key"]], histories[case["key"]],
                                    normalization=normalization, requested_steps=ref["summary"]["requested_steps"])})
        ref_same = index.get((member_id, "weak_plus", case["imperfection_ratio"]))
        if ref_same is not None:
            same_amplitude.append({"member_id": member_id, "direction": case["direction"],
                "imperfection_ratio": case["imperfection_ratio"], "candidate_key": case["key"],
                "reference_key": ref_same["case"]["key"],
                **compare_histories(histories[ref_same["case"]["key"]], histories[case["key"]],
                                    normalization=normalization, requested_steps=ref_same["summary"]["requested_steps"])})
        geometry.append({"key": case["key"], "member_id": member_id, "direction": case["direction"],
            "imperfection_ratio": case["imperfection_ratio"], "peak_bow_mm": case["peak_bow_m"] * 1000,
            "global_dx": case["unit_direction_global"][0], "global_dy": case["unit_direction_global"][1],
            "global_dz": case["unit_direction_global"][2],
            "local_dy": case["unit_direction_local_xyz"][1], "local_dz": case["unit_direction_local_xyz"][2],
            "angle_to_weak_line_degrees": case["angle_to_weak_displacement_line_degrees"],
            "max_reference_roll_degrees": case["orientation_audit"]["maximum_absolute_roll_degrees"],
            "observed_peak_compression_kN": result["peak_compression_kN"], "complete": result["complete"]})
    summary.update({"complete_cases": sum(r["summary"]["complete"] for r in records),
        "all_cases_complete": len(records) == summary["requested_cases"] and all(r["summary"]["complete"] for r in records),
        "failed_attempts": sum(r["summary"]["failed_attempts"] for r in records),
        "failed_case_keys": [r["case"]["key"] for r in records if not r["summary"]["complete"]],
        "comparisons_to_weak_plus_l1000": comparisons, "direction_comparisons_at_same_amplitude": same_amplitude,
        "history_path_pattern": "runs/{case.key}/history.csv",
        "comparison_note": "Ordered shared requested points only, no extrapolation; coverage and completion separate from physical validity",
        "orientation_note": "Direction and amplitude vary while the production per-segment reference-frame rule is retained; its roll variation is quantified but not separately removed",
        "execution_code_provenance_note": "The source S2K hash, full numerical settings and histories were preserved; a Python source snapshot was not frozen before this direction run. Publication-time code hashes identify publication source only. Subsequent peak metadata were derived from preserved histories; solver force/displacement records were not modified.",
        "execution_steps": ["Read original S2K geometry, material and angle fibers through MechanicalCatalog",
            "Fix full legacy_tower Steel02, 16 dispBeamColumn elements, Legendre6 and 32x4 fiber discretization",
            "Compute weak bending axis and perpendicular bow; reproduce the original S2K seed30103 traversal",
            "Apply each of three direction vectors at L/2000, L/1000 and L/500 using the same half-sine shape",
            "Apply the common isolated spatial pin-ended monotonic axial displacement protocol",
            "Preserve every committed step and failed attempt; compare only common ordered requested points"],
        "limits": ["All histories are synthetic loading protocols, not measured tests",
            "Actual member joint restraints and S2K installation-angle equivalence are not identified",
            "Three selected rods and one random realization do not establish a worst-case direction or probability distribution",
            "No whole-tower mesh, capacity, first buckling member or failure sequence validation"]})
    write_json(path, summary)
    with (output / "direction_geometry_audit.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(geometry[0]))
        writer.writeheader(); writer.writerows(geometry)
    old_geometry = ROOT / "initial_imperfection_material/tian_ma_qu/followup_results/single_tower_wind_comparison_20261028/runs/steel02_four_segments_0/model_data/split_nodes.csv"
    observed = {}
    with old_geometry.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if int(row["station_index"]) == 2:
                observed[int(row["original_element_tag"])] = np.array([float(row[a]) for a in ("x", "y", "z")])
    checks = []
    for record in records:
        case = record["case"]
        if case["direction"] != "legacy_seed30103" or case["imperfection_ratio"] != .001:
            continue
        recorded_vector = observed[case["member_id"]] - np.mean(case["source_coordinates_m"], axis=0)
        difference = float(np.max(np.abs(recorded_vector - case["imperfection_vector_global_m"])))
        if difference > 1e-12:
            raise ValueError("Frozen seed vector differs from previously saved tower geometry")
        checks.append({"member_id": case["member_id"], "maximum_coordinate_error_m": difference,
                       "matches_saved_geometry": True, "observed_midspan_vector_m": recorded_vector.tolist()})
    write_json(output / "direction_seed_geometry_verification.json", {
        "source": str(old_geometry.relative_to(ROOT)), "source_sha256": hashlib.sha256(old_geometry.read_bytes()).hexdigest(),
        "checks": checks, "scope": "three selected members of the saved zero-degree tower run"})
    return summary


if __name__ == "__main__":
    main()
