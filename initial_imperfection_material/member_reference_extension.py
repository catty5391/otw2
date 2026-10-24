"""Append one finer member mesh while reusing immutable prior matching evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from model.mechanical_profile import MechanicalCatalog, MechanicalProfile, local_axes
from .member_reference_3d import load_recorded_boundary, replay_boundary_history, subdivide_boundary_points
from .member_reference_convergence import (
    infer_half_sine_vector, lightweight_original_states, matched_history_metrics, validate_reference_manifest,
)
from .member_reference_fiber_sensitivity import load_original_points


def extend_mesh(source: Path, history: Path, verified_mesh: Path, output: Path, *,
                member_id: int, divisions: int = 32) -> dict[str, Any]:
    """Only append the requested new mesh; do not recalculate old 4/8/16 cases."""
    study = json.loads(verified_mesh.read_text(encoding="utf-8"))
    history_hash = hashlib.sha256(history.read_bytes()).hexdigest()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if study.get("source_sha256") != source_hash or study.get("history_sha256") != history_hash:
        raise ValueError("Mesh extension must use the same source and prescribed history")
    scope = validate_reference_manifest(json.loads((history.parent / "run_manifest.json").read_text(encoding="utf-8")), history)
    row = next((row for row in study["members"] if row["member_id"] == member_id), None)
    if not row or not row["cases"][0].get("matching_mesh_passed") or row.get("stop_reason"):
        raise ValueError("Cannot extend a failed matching implementation or incomplete prior mesh")
    previous = row["cases"][-1]
    if previous["execution_status"] != "completed" or divisions != 2 * previous["divisions"]:
        raise ValueError("Append exactly one doubling of a completed prior mesh")
    if row.get("mesh_thresholds_passed"):
        raise ValueError("Prior mesh passed; this tool only extends an unresolved mesh gate")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite mesh extension evidence: {output}")
    output.mkdir(parents=True, exist_ok=True)
    profile = MechanicalProfile(**study["profile"])
    member = MechanicalCatalog(source, output_dir=output / "parser", profile=profile).member(member_id)
    boundary = load_recorded_boundary(history, member_id)
    substeps = int(study["boundary_substeps"])
    baseline = load_original_points(verified_mesh.parent, previous, substeps)
    result = replay_boundary_history(member, subdivide_boundary_points(boundary["points"], substeps),
        divisions=divisions, imperfection_vector=infer_half_sine_vector(boundary["exact_coordinates"]),
        detail_stride=substeps, remove_rigid_translation=bool(study["removed_rigid_translation"]),
        algorithms=study.get("solver_algorithms", ("Newton",)))
    matched = lightweight_original_states(result["states"][::substeps])
    result.update({"source_history": str(history), "profile": profile.as_dict(),
        "boundary_substeps_per_recorded_interval": substeps,
        "reference_point_state_indices": list(range(0, len(result["states"]), substeps)),
        "verified_matching_legacy_mesh": str(verified_mesh)})
    state_path = output / f"member_{member_id}_divisions_{divisions}.json.gz"
    with gzip.open(state_path, "wt", encoding="utf-8") as stream:
        json.dump(result, stream, allow_nan=False, separators=(",", ":"))
    index_path = output / f"member_{member_id}_divisions_{divisions}.original_points.json"
    index_path.write_text(json.dumps({"schema": "otw2.original_member_points.v1",
        "source_state_file": state_path.name, "states": matched}, allow_nan=False), encoding="utf-8")
    metrics = matched_history_metrics(matched, baseline, original_axis=local_axes(member["coordinates"])[0])
    case = {"divisions": divisions, "execution_status": result["execution_status"],
        "completed_substeps": result["completed_steps"], "requested_substeps": result["requested_steps"],
        "state_file": state_path.name, "original_points_file": index_path.name,
        "maximum_fiber_stress_Pa": max(state["maximum_fiber_abs_stress"] for state in result["states"]),
        "maximum_fiber_strain": max(state["maximum_fiber_abs_strain"] for state in result["states"]),
        "failed_step": result["failed_step"]}
    summary = {"schema": "otw2.member_mesh_extension.v1", "source_scope": scope,
        "source_history": str(history), "source_sha256": source_hash, "history_sha256": history_hash,
        "profile": profile.as_dict(), "boundary_substeps": substeps,
        "removed_rigid_translation": study["removed_rigid_translation"],
        "previous_study": str(verified_mesh), "previous_study_sha256": hashlib.sha256(verified_mesh.read_bytes()).hexdigest(),
        "member_id": member_id, "previous_case": previous, "appended_case": case,
        "comparison": {"coarse_divisions": previous["divisions"], "fine_divisions": divisions, **metrics},
        "mesh_thresholds_passed": bool(metrics["passed"] and result["execution_status"] == "completed"),
        "G1_passed": False, "scope_note": "One mesh refinement only. Existing matching evidence is referenced, never recalculated or overwritten."}
    (output / "mesh_extension_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    figure, axis = plt.subplots(figsize=(10, 4), constrained_layout=True)
    local_axis = local_axes(member["coordinates"])[0]
    for states, label in ((baseline, f"Prior {previous['divisions']} segments"), (matched, f"New {divisions} segments")):
        forces = np.array([state["end_global_internal_force"][6:9] for state in states]) @ local_axis
        axis.plot(forces / 1000, label=label)
    axis.set(title=f"Member {member_id}: one-mesh extension", xlabel="Original committed sample (not seconds)", ylabel="Original-axis force (kN)")
    axis.grid(alpha=0.2)
    axis.legend()
    figure.savefig(output / "mesh_extension.png", dpi=160)
    plt.close(figure)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("Source/Z30103A6.s2k"))
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--verified-mesh", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--member", type=int, required=True)
    parser.add_argument("--divisions", type=int, default=32)
    args = parser.parse_args()
    summary = extend_mesh(args.source, args.history, args.verified_mesh, args.output,
        member_id=args.member, divisions=args.divisions)
    print(json.dumps({"output": str(args.output), "appended_case": summary["appended_case"], "comparison": summary["comparison"]}))


if __name__ == "__main__":
    main()
