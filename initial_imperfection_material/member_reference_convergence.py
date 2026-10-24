"""T08 staged local mesh study, gated by a matching-mesh recorded-boundary replay.

All committed states are retained losslessly in gzip JSON. Original recorded
points and event points keep section detail; other substeps keep all node DOFs,
endpoint/segment forces, basic deformations and fiber extrema. No full tower is
built. A failed four-segment replay stops that member's mesh study.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from model.mechanical_profile import MechanicalCatalog, MechanicalProfile, local_axes
from .member_reference_3d import load_recorded_boundary, replay_boundary_history, subdivide_boundary_points


def lightweight_original_states(states: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep an inexpensive index for comparisons; full states stay in gzip."""
    keys = ("source_step", "stage_id", "stage_progress", "end_global_internal_force",
            "chord_shortening_m", "maximum_fiber_abs_stress", "maximum_fiber_abs_strain")
    return [{key: state[key] for key in keys} for state in states]


def validate_reference_manifest(manifest: dict[str, Any], history: Path) -> dict[str, Any]:
    """Accept a complete run or an explicitly scoped initial-to-target prefix.

    A derived prefix is not a completed parent analysis: validate all committed
    stages and the exact copied prefix hash, and propagate its limited scope.
    """
    if manifest.get("status") != "completed":
        raise ValueError("Cannot validate against an unfinished/failed recorded tower run")
    if manifest.get("artifact_type") != "derived_committed_prefix":
        return {"artifact_type": "completed_run", "scope": "source_completed_protocol"}
    scope, derivation = manifest.get("scope", {}), manifest.get("derivation", {})
    requested = scope.get("requested_target_count", 0)
    completed = scope.get("completed_target_count", 0)
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 6 or completed != requested:
        raise ValueError("Derived boundary prefix must contain at least six complete requested targets")
    if scope.get("starts_from_unloaded") is not True or scope.get("includes_complete_gravity") is not True:
        raise ValueError("Derived history must begin unloaded and include complete gravity")
    if derivation.get("method") != "committed_prefix_from_initial_not_restart" or not derivation.get("source_run_id"):
        raise ValueError("Derived prefix requires explicit source provenance and no-restart method")
    if scope.get("source_requested_target_count", 0) < requested:
        raise ValueError("Invalid parent protocol coverage")
    if hashlib.sha256(history.read_bytes()).hexdigest() != derivation.get("source_history_prefix_sha256"):
        raise ValueError("Derived prefix hash does not match the copied committed history")
    metadata = history.with_suffix(".metadata.json")
    if not metadata.is_file() or hashlib.sha256(metadata.read_bytes()).hexdigest() != derivation.get("source_metadata_sha256"):
        raise ValueError("Derived geometry metadata hash mismatch")
    target_stages: dict[str, list[float]] = {}
    closed_stages = set()
    previous_stage = None
    first, last = None, None
    gravity = []
    with history.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            row = json.loads(line)
            if row.get("committed") is not True or row.get("accepted_step") != index:
                raise ValueError("Derived history omits/reorders accepted states")
            if first is None:
                first = row
            stage = row["stage_id"]
            if stage != previous_stage:
                if stage in closed_stages:
                    raise ValueError("Derived stages are not contiguous")
                if previous_stage is not None:
                    closed_stages.add(previous_stage)
                previous_stage = stage
            if stage.startswith("target_"):
                target_stages.setdefault(stage, []).append(float(row["stage_progress"]))
            elif stage == "gravity":
                gravity.append(float(row["stage_progress"]))
            last = row
    if first is None or first["stage_id"] != "initial" or not gravity or not math.isclose(gravity[-1], 1.0, abs_tol=1e-12):
        raise ValueError("Derived prefix lacks initial or completed gravity state")
    if len(target_stages) != requested or list(target_stages) != scope.get("target_stage_ids"):
        raise ValueError("Derived target list/coverage disagrees with actual committed history")
    for values in target_stages.values():
        if not math.isclose(values[0], 0.0, abs_tol=1e-12) or not math.isclose(values[-1], 1.0, abs_tol=1e-12) or any(b < a - 1e-12 for a, b in zip(values, values[1:])):
            raise ValueError("Derived target stage is incomplete or nonmonotonic in progress")
    if last["stage_id"] != list(target_stages)[-1] or not math.isclose(last["stage_progress"], 1.0, abs_tol=1e-12):
        raise ValueError("Derived prefix must end at its last requested target")
    if last["accepted_step"] != derivation.get("last_included_accepted_step"):
        raise ValueError("Derived last-step provenance mismatch")
    return {"artifact_type": "derived_committed_prefix", "scope": scope, "derivation": derivation,
            "parent_protocol_completed": derivation.get("source_run_status_at_snapshot") == "completed",
            "validation_scope_note": "Only the copied complete prefix; do not claim completion/validity of later source targets."}


def infer_half_sine_vector(coordinates: Sequence[Sequence[float]], *, tolerance: float = 1e-10) -> np.ndarray:
    """Recover and check one global peak vector, never re-randomize an old member."""
    points = np.asarray(coordinates, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError("Complete finite segment coordinates are required")
    fractions = np.linspace(0, 1, len(points))
    shape = np.sin(np.pi * fractions)
    straight = points[0] + fractions[:, None] * (points[-1] - points[0])
    vector = np.sum((points - straight) * shape[:, None], axis=0) / np.dot(shape, shape)
    if np.max(np.abs(points - straight - shape[:, None] * vector)) > tolerance:
        raise ValueError("Recorded imperfection is not the common half-sine family; do not remesh silently")
    return vector


def matched_history_metrics(reference: Sequence[dict[str, Any]], candidate: Sequence[dict[str, Any]],
                             *, original_axis: Sequence[float]) -> dict[str, Any]:
    """Compare ordered, same-source protocol points without sorting cyclic strain."""
    count = min(len(reference), len(candidate))
    if count < 2:
        return {"coverage": 0.0, "passed": False, "reason": "insufficient_common_committed_points"}
    left, right = list(reference[:count]), list(candidate[:count])
    for ref, cand in zip(left, right):
        if ref["source_step"] != cand["source_step"] or ref["stage_id"] != cand["stage_id"] or not math.isclose(ref["stage_progress"], cand["stage_progress"], abs_tol=1e-12):
            raise ValueError("Histories must align by source step, stage, and stage progress")
    axis = np.asarray(original_axis, dtype=float)
    ref_force = np.asarray([row["end_global_internal_force"][6:9] for row in left]) @ axis
    cand_force = np.asarray([row["end_global_internal_force"][6:9] for row in right]) @ axis
    error = cand_force - ref_force
    weights = np.array([abs(b["stage_progress"] - a["stage_progress"]) if a["stage_id"] == b["stage_id"] else 0.0
                        for a, b in zip(left, left[1:])])
    integral = np.sum(weights * (error[:-1]**2 + error[:-1] * error[1:] + error[1:]**2) / 3)
    weighted_rmse = math.sqrt(integral / weights.sum()) if weights.sum() > 0 else None
    ref_peak = max(0.0, -float(np.min(ref_force)))
    cand_peak = max(0.0, -float(np.min(cand_force)))
    peak_error = abs(cand_peak - ref_peak) / ref_peak if ref_peak > 1.0 else None
    scale = max(float(np.max(np.abs(ref_force))), 1.0)
    nrmse = weighted_rmse / scale if weighted_rmse is not None else None
    ref_peak_index, cand_peak_index = int(np.argmin(ref_force)), int(np.argmin(cand_force))
    ref_shortening = float(left[ref_peak_index]["chord_shortening_m"])
    cand_shortening = float(right[cand_peak_index]["chord_shortening_m"])
    displacement_error = abs(cand_shortening - ref_shortening) / abs(ref_shortening) if abs(ref_shortening) > 1e-9 else None
    coverage = count / max(len(reference), len(candidate))
    passed = (coverage == 1.0 and peak_error is not None and peak_error <= 0.01
              and nrmse is not None and nrmse <= 0.02
              and displacement_error is not None and displacement_error <= 0.02)
    return {"coverage": coverage, "reference_peak_compression_N": ref_peak,
            "candidate_peak_compression_N": cand_peak, "peak_relative_difference": peak_error,
            "equal_stage_progress_weighted_nrmse": nrmse,
            "peak_shortening_relative_difference": displacement_error,
            "reference_peak_source_step": left[ref_peak_index]["source_step"],
            "candidate_peak_source_step": right[cand_peak_index]["source_step"],
            "maximum_force_difference_N": float(np.max(np.abs(error))),
            "not_evaluable_reason": "no_compression_peak_in_protocol" if peak_error is None else (
                "near_zero_peak_shortening_requires_absolute_tolerance" if displacement_error is None else None),
            "normalization": "own member peak force; ordered stage-progress integration; no cyclic displacement sorting",
            "passed": bool(passed)}


def _recorded_force_states(boundary: dict[str, Any], length: float) -> list[dict[str, Any]]:
    return [{"source_step": point.source_step, "stage_id": point.stage_id, "stage_progress": point.stage_progress,
             "end_global_internal_force": row["segments"][0]["global_force"][:6] + row["segments"][-1]["global_force"][6:],
             "chord_shortening_m": -row["chord_strain"] * length}
            for point, row in zip(boundary["points"], boundary["reference_states"])]


def run_mesh_study(source: Path, history: Path, output: Path, *, member_ids: Sequence[int] = (877, 825),
                   divisions: Sequence[int] = (4, 8, 16), boundary_substeps: int = 10,
                   long_edge_segments: int = 8, short_edge_segments: int = 1,
                   remove_rigid_translation: bool = False,
                   algorithms: Sequence[str] = ("Newton",)) -> dict[str, Any]:
    if not divisions or divisions[0] != 4 or any(isinstance(value, bool) or int(value) != value or value < 2 for value in divisions):
        raise ValueError("This staged legacy study must start with matching four segments")
    if any(right <= left for left, right in zip(divisions, divisions[1:])):
        raise ValueError("Segment refinements must be strictly increasing")
    manifest_path = history.parent / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("A completed instrumented run manifest is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_scope = validate_reference_manifest(manifest, history)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite study output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    profile = MechanicalProfile(long_edge_segments=long_edge_segments, short_edge_segments=short_edge_segments)
    catalog = MechanicalCatalog(source, output_dir=output / "parser", profile=profile)
    member_results = []
    plot_curves = []
    for member_id in member_ids:
        member = catalog.member(member_id)
        boundary = load_recorded_boundary(history, member_id)
        if boundary["divisions"] != divisions[0]:
            raise ValueError("Matching first mesh differs from recorded geometry")
        peak_vector = infer_half_sine_vector(boundary["exact_coordinates"])
        dense = subdivide_boundary_points(boundary["points"], boundary_substeps)
        records = _recorded_force_states(boundary, member["length"])
        axis = local_axes(member["coordinates"])[0]
        cases, curves = [], {}
        stop_reason = None
        for count in divisions:
            print(json.dumps({"member_id": member_id, "divisions": count, "event": "started"}), flush=True)
            result = replay_boundary_history(member, dense, divisions=count, imperfection_vector=peak_vector,
                exact_coordinates=boundary["exact_coordinates"] if count == divisions[0] else None,
                detail_stride=boundary_substeps, remove_rigid_translation=remove_rigid_translation,
                algorithms=algorithms)
            matched = lightweight_original_states(result["states"][::boundary_substeps])
            curves[count] = matched
            result["source_history"] = str(history)
            result["reference_point_state_indices"] = list(range(0, len(result["states"]), boundary_substeps))
            result["boundary_substeps_per_recorded_interval"] = boundary_substeps
            result["reference_end_global_internal_forces"] = [row["end_global_internal_force"] for row in records]
            result["profile"] = profile.as_dict()
            state_path = output / f"member_{member_id}_divisions_{count}.json.gz"
            with gzip.open(state_path, "wt", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            index_path = output / f"member_{member_id}_divisions_{count}.original_points.json"
            index_path.write_text(json.dumps({"schema": "otw2.original_member_points.v1",
                "source_state_file": state_path.name, "states": matched}, allow_nan=False), encoding="utf-8")
            case = {"divisions": count, "execution_status": result["execution_status"],
                    "completed_substeps": result["completed_steps"], "requested_substeps": result["requested_steps"],
                    "state_file": state_path.name, "original_points_file": index_path.name,
                    "maximum_fiber_stress_Pa": max(row["maximum_fiber_abs_stress"] for row in result["states"]),
                    "maximum_fiber_strain": max(row["maximum_fiber_abs_strain"] for row in result["states"]),
                    "events": result["events"], "physical_yield_note": "fy crossing indicator, not an independent plastic strain definition"}
            if count == divisions[0]:
                observed = np.array([row["end_global_internal_force"] for row in matched])
                reference = np.array([row["end_global_internal_force"] for row in records[:len(matched)]])
                scale = np.tile([1, 1, 1, 1 / member["length"], 1 / member["length"], 1 / member["length"]], 2)
                denominator = np.linalg.norm(reference * scale)
                relative = float(np.linalg.norm((observed - reference) * scale) / denominator) if denominator > 1e-12 else None
                case["matching_mesh_scaled_end_force_relative_error"] = relative
                case["matching_mesh_passed"] = bool(result["execution_status"] == "completed" and relative is not None and relative <= 1e-6)
                if not case["matching_mesh_passed"]:
                    stop_reason = "matching_mesh_replay_failed_no_refinement_authorized_by_this_tool"
            elif result["execution_status"] != "completed":
                stop_reason = "refined_mesh_nonconvergence_not_physical_collapse"
            cases.append(case)
            print(json.dumps({"member_id": member_id, "divisions": count, "event": "completed_case", "execution_status": result["execution_status"], "stop_reason": stop_reason}), flush=True)
            del result
            if stop_reason:
                break
        comparisons = []
        for coarse, fine in zip(cases, cases[1:]):
            metrics = matched_history_metrics(curves[fine["divisions"]], curves[coarse["divisions"]], original_axis=axis)
            comparisons.append({"coarse_divisions": coarse["divisions"], "fine_divisions": fine["divisions"], **metrics})
        member_results.append({"member_id": member_id, "section_name": member["section"]["section_name"],
            "cases": cases, "comparisons": comparisons, "stop_reason": stop_reason,
            "mesh_thresholds_passed": bool(not stop_reason and comparisons and comparisons[-1]["passed"]),
            "imperfection_vector_global_m": peak_vector.tolist()})
        plot_curves.append((member_id, records, curves, axis))
    summary = {"schema": "otw2.member_mesh_study.v1", "members": member_results,
        "source_history": str(history), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "history_sha256": hashlib.sha256(history.read_bytes()).hexdigest(),
        "source_scope": source_scope,
        "boundary_substeps": boundary_substeps, "profile": profile.as_dict(),
        "removed_rigid_translation": remove_rigid_translation,
        "solver_algorithms": list(algorithms),
        "thresholds": {"matching_mesh_end_force_relative": 1e-6, "mesh_peak_relative": 0.01, "mesh_nrmse": 0.02, "mesh_peak_shortening_relative": 0.02},
        "G1_passed": False, "scope_note": "Only local mesh evidence; full G1 also needs boundary-step/fiber/mirror sensitivity and residual acceptance."}
    (output / "mesh_study_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    figure, axes = plt.subplots(len(plot_curves), 1, figsize=(10, 3.5 * len(plot_curves)), squeeze=False, constrained_layout=True)
    for plot_axis, (member_id, recorded, curves, axis) in zip(axes[:, 0], plot_curves):
        forces = np.array([row["end_global_internal_force"][6:9] for row in recorded]) @ axis
        plot_axis.plot(forces / 1000, color="black", linewidth=2, label="Recorded tower")
        for count, states in curves.items():
            forces = np.array([row["end_global_internal_force"][6:9] for row in states]) @ axis
            plot_axis.plot(forces / 1000, "--", label=f"Local {count} segments")
        plot_axis.set_title(f"Member {member_id}: ordered supplied boundary history")
        plot_axis.set_ylabel("Original-axis force (kN)")
        plot_axis.set_xlabel("Original committed sample (not seconds)")
        plot_axis.legend()
        plot_axis.grid(alpha=0.2)
    if source_scope["artifact_type"] == "derived_committed_prefix":
        figure.suptitle(f"Complete first {source_scope['scope']['requested_target_count']} targets only; parent protocol is separate")
    figure.savefig(output / "mesh_study.png", dpi=160)
    plt.close(figure)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("Source/Z30103A6.s2k"))
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--members", type=int, nargs="+", default=[877, 825])
    parser.add_argument("--divisions", type=int, nargs="+", default=[4, 8, 16])
    parser.add_argument("--boundary-substeps", type=int, default=10)
    parser.add_argument("--long-edge-segments", type=int, default=8)
    parser.add_argument("--short-edge-segments", type=int, default=1)
    parser.add_argument("--remove-rigid-translation", action="store_true")
    parser.add_argument("--algorithm-fallback", action="store_true", help="Explicit Newton/KrylovNewton/NewtonLineSearch(0.8); unchanged tolerance")
    args = parser.parse_args()
    summary = run_mesh_study(args.source, args.history, args.output, member_ids=args.members,
        divisions=args.divisions, boundary_substeps=args.boundary_substeps,
        long_edge_segments=args.long_edge_segments, short_edge_segments=args.short_edge_segments,
        remove_rigid_translation=args.remove_rigid_translation,
        algorithms=("Newton", "KrylovNewton", "NewtonLineSearch(0.8)") if args.algorithm_fallback else ("Newton",))
    print(json.dumps({"output": str(args.output), "source_scope": summary["source_scope"],
        "members": [{"member_id": row["member_id"], "stop_reason": row["stop_reason"],
                     "mesh_thresholds_passed": row["mesh_thresholds_passed"],
                     "cases": [{key: case[key] for key in ("divisions", "execution_status", "completed_substeps", "requested_substeps")}
                               for case in row["cases"]], "comparisons": row["comparisons"]}
                    for row in summary["members"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
