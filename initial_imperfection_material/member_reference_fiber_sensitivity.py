"""Refine only Fiber after a separately verified matching-legacy mesh study.

This tool never compares a deliberately refined section against a same-Fiber
implementation tolerance. The legacy implementation check and the subsequent
physical discretization change have distinct gates and reported meanings.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from model.mechanical_profile import MechanicalCatalog, MechanicalProfile, fiber_moments, local_axes
from .member_reference_3d import load_recorded_boundary, replay_boundary_history, subdivide_boundary_points
from .member_reference_convergence import (
    infer_half_sine_vector, lightweight_original_states, matched_history_metrics,
    validate_reference_manifest,
)
from .state_archive import iter_archive_states


def require_verified_legacy_case(study: dict[str, Any], *, member_id: int, divisions: int,
                                 history_sha256: str, source_sha256: str) -> dict[str, Any]:
    """Fail closed before building an intentionally changed section."""
    if study.get("history_sha256") != history_sha256 or study.get("source_sha256") != source_sha256:
        raise ValueError("Fiber refinement requires the identical verified source and boundary history")
    if study.get("profile", {}).get("long_edge_segments") != 8 or study.get("profile", {}).get("short_edge_segments") != 1:
        raise ValueError("This refinement study requires an explicit legacy 8x1 baseline")
    row = next((row for row in study.get("members", []) if row["member_id"] == member_id), None)
    if row is None or not row.get("mesh_thresholds_passed") or row.get("stop_reason"):
        raise ValueError("The legacy spatial mesh has not passed for this member")
    cases = row.get("cases", [])
    if not cases or cases[0].get("divisions") != 4 or not cases[0].get("matching_mesh_passed"):
        raise ValueError("Matching four-segment legacy implementation must pass before Fiber refinement")
    case = next((case for case in cases if case["divisions"] == divisions), None)
    if case is None or case.get("execution_status") != "completed":
        raise ValueError("Requested fixed mesh must have completed the whole supplied history")
    return case


def load_original_points(directory: Path, case: dict[str, Any], stride: int) -> list[dict[str, Any]]:
    """Use small indices for new results; preserve compatibility with old gzip."""
    if case.get("original_points_file"):
        index = json.loads((directory / case["original_points_file"]).read_text(encoding="utf-8"))
        if index.get("source_state_file") != case["state_file"]:
            raise ValueError("Original-point index references a different state file")
        return index["states"]
    return [lightweight_original_states([state])[0]
            for index, state in enumerate(iter_archive_states(directory / case["state_file"])) if index % stride == 0]


def run_fiber_study(source: Path, history: Path, verified_mesh: Path, output: Path, *,
                    member_ids: Sequence[int] = (877, 825), divisions: int = 16,
                    long_edge_segments: int = 32, short_edge_segments: int = 3) -> dict[str, Any]:
    manifest_path = history.parent / "run_manifest.json"
    source_scope = validate_reference_manifest(json.loads(manifest_path.read_text(encoding="utf-8")), history)
    study = json.loads(verified_mesh.read_text(encoding="utf-8"))
    history_hash = hashlib.sha256(history.read_bytes()).hexdigest()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    cases = {member_id: require_verified_legacy_case(study, member_id=member_id, divisions=divisions,
                history_sha256=history_hash, source_sha256=source_hash) for member_id in member_ids}
    if long_edge_segments <= 8 or short_edge_segments <= 1:
        raise ValueError("Refine both Fiber directions explicitly beyond legacy 8x1")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite Fiber refinement evidence: {output}")
    output.mkdir(parents=True, exist_ok=True)
    substeps = int(study["boundary_substeps"])
    remove_translation = bool(study["removed_rigid_translation"])
    refined_profile = MechanicalProfile(long_edge_segments=long_edge_segments, short_edge_segments=short_edge_segments)
    fine_catalog = MechanicalCatalog(source, output_dir=output / "refined_parser", profile=refined_profile)
    legacy_catalog = MechanicalCatalog(source, output_dir=output / "legacy_parser")
    rows, plots = [], []
    for member_id in member_ids:
        print(json.dumps({"event": "fiber_started", "member_id": member_id, "divisions": divisions}), flush=True)
        baseline_case = cases[member_id]
        baseline = load_original_points(verified_mesh.parent, baseline_case, substeps)
        member, legacy = fine_catalog.member(member_id), legacy_catalog.member(member_id)
        boundary = load_recorded_boundary(history, member_id)
        result = replay_boundary_history(member, subdivide_boundary_points(boundary["points"], substeps),
            divisions=divisions, imperfection_vector=infer_half_sine_vector(boundary["exact_coordinates"]),
            detail_stride=substeps, remove_rigid_translation=remove_translation,
            algorithms=study.get("solver_algorithms", ("Newton",)))
        matched = lightweight_original_states(result["states"][::substeps])
        result.update({"source_history": str(history), "profile": refined_profile.as_dict(),
            "boundary_substeps_per_recorded_interval": substeps,
            "reference_point_state_indices": list(range(0, len(result["states"]), substeps)),
            "verified_matching_legacy_mesh": str(verified_mesh)})
        state_path = output / f"member_{member_id}_fibers_{long_edge_segments}x{short_edge_segments}.json.gz"
        with gzip.open(state_path, "wt", encoding="utf-8") as stream:
            json.dump(result, stream, allow_nan=False, separators=(",", ":"))
        index_path = state_path.with_suffix("").with_suffix(".original_points.json")
        index_path.write_text(json.dumps({"schema": "otw2.original_member_points.v1",
            "source_state_file": state_path.name, "states": matched}, allow_nan=False), encoding="utf-8")
        metrics = matched_history_metrics(matched, baseline, original_axis=local_axes(member["coordinates"])[0])
        fine_stress = max(state["maximum_fiber_abs_stress"] for state in result["states"])
        fine_strain = max(state["maximum_fiber_abs_strain"] for state in result["states"])
        stress_change = abs(baseline_case["maximum_fiber_stress_Pa"] - fine_stress) / fine_stress if fine_stress > 1 else None
        strain_change = abs(baseline_case["maximum_fiber_strain"] - fine_strain) / fine_strain if fine_strain > 1e-10 else None
        row = {"member_id": member_id, "divisions": divisions, "execution_status": result["execution_status"],
            "completed_substeps": result["completed_steps"], "requested_substeps": result["requested_steps"],
            "state_file": state_path.name, "original_points_file": index_path.name,
            "legacy_fiber_moments": fiber_moments(legacy["fibers"]), "refined_fiber_moments": fiber_moments(member["fibers"]),
            "legacy_maximum_fiber_stress_Pa": baseline_case["maximum_fiber_stress_Pa"],
            "refined_maximum_fiber_stress_Pa": fine_stress,
            "legacy_maximum_fiber_strain": baseline_case["maximum_fiber_strain"],
            "refined_maximum_fiber_strain": fine_strain,
            "maximum_fiber_stress_relative_change": stress_change,
            "maximum_fiber_strain_relative_change": strain_change,
            "history_metrics": metrics, "force_history_thresholds_passed": bool(metrics["passed"] and result["execution_status"] == "completed"),
            "fiber_extrema_within_two_percent": bool(result["execution_status"] == "completed" and stress_change is not None
                and strain_change is not None and max(stress_change, strain_change) <= 0.02),
            "extrema_note": "Different Fiber centroids sample different physical points; report this alongside force convergence, not as identical-fiber implementation error."}
        rows.append(row)
        plots.append((member_id, baseline, matched, local_axes(member["coordinates"])[0]))
        print(json.dumps({"event": "fiber_finished", "member_id": member_id, "execution_status": result["execution_status"],
            "force_history_thresholds_passed": row["force_history_thresholds_passed"]}), flush=True)
        del result
    summary = {"schema": "otw2.member_fiber_study.v1", "source_scope": source_scope, "source_sha256": source_hash,
        "history_sha256": history_hash, "verified_legacy_mesh_study": str(verified_mesh),
        "verified_legacy_mesh_study_sha256": hashlib.sha256(verified_mesh.read_bytes()).hexdigest(),
        "fixed_divisions": divisions, "fixed_boundary_substeps": substeps, "removed_rigid_translation": remove_translation,
        "legacy_fiber_mesh": [8, 1], "refined_fiber_mesh": [long_edge_segments, short_edge_segments], "members": rows,
        "G1_passed": False, "scope_note": "Fiber sensitivity only; no automatic full G1 or material equivalence validation."}
    (output / "fiber_study_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    figure, axes = plt.subplots(len(plots), 1, figsize=(10, 3.5 * len(plots)), squeeze=False, constrained_layout=True)
    for axis_plot, (member_id, baseline, matched, axis) in zip(axes[:, 0], plots):
        for states, label, style in ((baseline, "Legacy Fiber 8x1", "-"), (matched, f"Refined Fiber {long_edge_segments}x{short_edge_segments}", "--")):
            forces = np.array([state["end_global_internal_force"][6:9] for state in states]) @ axis
            axis_plot.plot(forces / 1000, style, label=label)
        axis_plot.set(title=f"Member {member_id}; fixed {divisions} segments", xlabel="Original committed sample (not seconds)", ylabel="Original-axis force (kN)")
        axis_plot.legend()
        axis_plot.grid(alpha=0.2)
    if source_scope["artifact_type"] == "derived_committed_prefix":
        figure.suptitle(f"Complete first {source_scope['scope']['requested_target_count']} targets only")
    figure.savefig(output / "fiber_study.png", dpi=160)
    plt.close(figure)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("Source/Z30103A6.s2k"))
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--verified-mesh", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--members", type=int, nargs="+", default=[877, 825])
    parser.add_argument("--divisions", type=int, default=16)
    parser.add_argument("--long-edge-segments", type=int, default=32)
    parser.add_argument("--short-edge-segments", type=int, default=3)
    args = parser.parse_args()
    result = run_fiber_study(args.source, args.history, args.verified_mesh, args.output, member_ids=args.members,
        divisions=args.divisions, long_edge_segments=args.long_edge_segments, short_edge_segments=args.short_edge_segments)
    print(json.dumps({"output": str(args.output), "members": result["members"]}))


if __name__ == "__main__":
    main()
