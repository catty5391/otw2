"""Postprocess saved convergence evidence; does not rerun or alter the tower."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openseespy.opensees as ops
from scipy.sparse import load_npz
from scipy.sparse.linalg import splu

from initial_imperfection_material.diagnose_tower_convergence import DEFAULT_DIAGNOSIS
from initial_imperfection_material.full_tower_cyclic import DEFAULT_OUTPUT
from initial_imperfection_material.material import BackbonePoint, EquivalentImperfectionMaterial, MemberProperties


def read_csv(path):
    with Path(path).open(newline="") as file:
        return list(csv.DictReader(file))


def symmetric_factor(matrix):
    """No row pivoting: signs of U's diagonal give symmetric LDL inertia."""
    lu = splu(matrix.tocsc(), permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0,
              options={"SymmetricMode": True})
    if not np.array_equal(lu.perm_r, lu.perm_c):
        raise RuntimeError("Pivot permutations differ; cannot infer symmetric inertia")
    return lu


def stiffness_evidence(root):
    run = root / "fine_sparse"
    snapshot = json.loads((run / "spectrum_0272.json").read_text())
    matrix = load_npz(run / "stiffness_0272.npz")
    residuals = []
    for index, mode in enumerate(snapshot["modes"]):
        vector = np.zeros(matrix.shape[0])
        for node in mode:
            for dof, value in zip(snapshot["node_dofs"][str(node["node"])], node["vector"]):
                if dof >= 0:
                    vector[dof] = value
        residuals.append(float(np.linalg.norm(matrix @ vector - snapshot["eigenvalues"][index] * vector)))
    if max(residuals) > 1e-3:
        raise RuntimeError("Matrix and saved mode/DOF mapping do not match")
    asymmetry = float(abs(matrix - matrix.T).max())
    matrix = (matrix + matrix.T) * .5
    nodes = {n["node"]: n for n in snapshot["modes"][0]}
    gradient = np.zeros((matrix.shape[0], 2))
    for column, (ni, nj) in enumerate(((801, 821), (800, 820))):
        xi = np.array(nodes[ni]["coord"]) + np.array(snapshot["node_displacements"][str(ni)][:3])
        xj = np.array(nodes[nj]["coord"]) + np.array(snapshot["node_displacements"][str(nj)][:3])
        axis = (xj - xi) / np.linalg.norm(xj - xi)
        for node, sign in ((ni, -1), (nj, 1)):
            for dof, value in zip(snapshot["node_dofs"][str(node)][:3], sign * axis):
                if dof >= 0:
                    gradient[dof, column] = value
    # Stability at prescribed tower-top displacement: remove that DOF before
    # condensation. The existing base support DOFs have already been eliminated.
    control_dof = snapshot["node_dofs"]["350"][1]
    keep = np.arange(matrix.shape[0]) != control_dof
    constrained = matrix[keep][:, keep]
    gradient = gradient[keep]
    lu = symmetric_factor(constrained)
    compliance = gradient.T @ lu.solve(gradient)
    condensed = np.linalg.inv(compliance)
    library = json.loads((root / "baseline/calibration_library.json").read_text())
    group = library["groups"]["L40x3Q235|0.850000"]
    points = group["compression_envelope"]
    area, length = group["member"]["area"], group["member"]["length"]
    def slope(left, right):
        return area / length * (right["stress"]-left["stress"]) / (right["strain"]-left["strain"])
    before, after = slope(points[4], points[5]), slope(points[3], points[4])
    environment = condensed - np.eye(2) * before
    after_corner = condensed + np.eye(2) * (after-before)
    return {
        "state": "last accepted baseline step 272, frozen geometry and all other tangents",
        "matrix_eigenpair_residual_norms": residuals,
        "matrix_max_absolute_asymmetry": asymmetry,
        "negative_pivots_before": int(np.sum(lu.U.diagonal() < 0)),
        "compression_corner_strain": points[4]["strain"],
        "member_axial_stiffness_before_N_per_m": before,
        "member_axial_stiffness_after_N_per_m": after,
        "condensed_with_members_before_N_per_m": condensed.tolist(),
        "surrounding_structure_N_per_m": environment.tolist(),
        "condensed_with_members_after_N_per_m": after_corner.tolist(),
        "condensed_eigenvalues_before_N_per_m": np.linalg.eigvalsh(condensed).tolist(),
        "condensed_eigenvalues_after_N_per_m": np.linalg.eigvalsh(after_corner).tolist(),
        "interpretation": "local tangent loses positive definiteness on the steeper unloading segment; not a new equilibrated state",
    }


def material_replay(root, members):
    group = json.loads((root / "baseline/calibration_library.json").read_text())["groups"]["L40x3Q235|0.850000"]
    member = MemberProperties(**group["member"])
    material = EquivalentImperfectionMaterial(member, [BackbonePoint(**p) for p in group["compression_envelope"]],
                                               source=group["source"], imperfection_ratio=group["imperfection_ratio"])
    ops.wipe()
    try:
        material.register_opensees(ops, 1, stress_scale=member.area)
        ops.testUniaxialMaterial(1)
        rows = []
        for record in members:
            ops.setStrain(float(record["strain"]))
            rows.append({"step": int(record["step"]), "strain": float(record["strain"]),
                         "tower_force_N": float(record["force_N"]), "material_force_N": ops.getStress(),
                         "material_tangent_N": ops.getTangent()})
        probes = []
        # A force-continuous corner with different one-sided tangents.
        for strain in (-.003751, -.003750001, -.00375, -.003749999, -.003749, 0.0):
            ops.setStrain(strain)
            probes.append({"strain": strain, "force_N": ops.getStress(), "tangent_N": ops.getTangent()})
    finally:
        ops.wipe()
    with (root / "material_replay_877.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    return {"max_force_error_N": max(abs(r["tower_force_N"]-r["material_force_N"]) for r in rows),
            "samples": len(rows), "corner_probes": probes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_DIAGNOSIS)
    args = parser.parse_args()
    root = args.root
    history = read_csv(root / "baseline/history.csv")
    by_step = {int(r["step"]): r for r in history}
    # Keep only the members needed in the report, not the whole-tower CSV in RAM.
    with (root / "baseline/members.csv").open() as file:
        member_rows = [r for r in csv.DictReader(file) if int(r["element"]) in (825, 828, 877, 878, 917, 920)]
    member877 = [r for r in member_rows if r["element"] == "877"]
    runs = {name: json.loads((root / name / "summary.json").read_text())
            for name in ("baseline", "fine_sparse", "elastic_877_878") if (root / name / "summary.json").exists()}
    stability = stiffness_evidence(root)
    replay = material_replay(root, member877)
    fine_history = read_csv(root / "fine_sparse/history.csv")
    fine_by_step = {int(r["step"]): r for r in fine_history}
    fine_stages = {int(r["stage"]): r for r in fine_history}
    fine_attempts = [json.loads(line) for line in (root / "fine_sparse/attempts.jsonl").open()]
    accepted = [r for r in fine_attempts if r["return_code"] == 0]
    fine_member877, outside = [], {}
    with (root / "fine_sparse/members.csv").open() as file:
        for row in csv.DictReader(file):
            if row["element"] == "877":
                fine_member877.append(row)
            if float(row["strain"]) < -.03:
                outside[row["element"]] = min(float(row["strain"]), outside.get(row["element"], 0.))
    checkpoints = []
    with sqlite3.connect(f"file:{DEFAULT_OUTPUT}/segmented_reference/tower_internal_forces.sqlite?mode=ro", uri=True) as conn:
        for tag in (825, 828, 877, 878):
            ref = conn.execute("SELECT f.p_j FROM force_history f JOIN elements e ON e.element_tag=f.element_tag "
                               "WHERE f.step=251 AND e.original_element_tag=? AND e.segment_index=1", (tag,)).fetchone()[0]
            equivalent = float(next(r for r in member_rows if r["step"] == "251" and int(r["element"]) == tag)["force_N"])
            checkpoints.append({"element": tag, "drift": -.006, "equivalent_force_N": equivalent,
                                "reference_first_segment_force_N": ref,
                                "compression_magnitude_difference_percent": 100*(abs(equivalent)/abs(ref)-1)})
    evidence = {"runs": runs, "material_replay": replay, "local_stability": stability,
                "fine_step_diagnostics": {
                    "minimum_accepted_increment_m": min(abs(r["increment"]) for r in accepted),
                    "stage_endpoints": fine_stages,
                    "members_beyond_three_percent_compression": outside,
                    "first_return_jump": [r for r in fine_member877 if int(r["step"]) in (274, 275)],
                    "first_return_jump_solver": next(r for r in accepted if r["step_before"] == 274),
                },
                "member_comparison_at_negative_0_6_percent": checkpoints,
                "baseline_steps_249_250_251_272": [{**r, "tower_u_m": by_step[int(r["step"])]["u_m"]}
                    for r in member877 if int(r["step"]) in (249,250,251,272)]}
    (root / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    with (root / "critical_members.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=member_rows[0]); writer.writeheader(); writer.writerows(member_rows)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5), constrained_layout=True)
    for name, label, color in (("elastic_877_878", "Diagnostic only: rods 877/878 elastic", "#7c8c8d"),
                               ("fine_sparse", "Unchanged material, smaller allowed steps", "#167b82"),
                               ("baseline", "Original step limit: stops", "#c03d3e")):
        rows = read_csv(root / name / "history.csv")
        axes[0,0].plot([float(r["u_m"])*1000 for r in rows], [float(r["base_shear_N"])/1000 for r in rows],
                       label=label, color=color, lw=1.5)
    axes[0,0].scatter([float(history[-1]["u_m"])*1000],[float(history[-1]["base_shear_N"])/1000], c="black",marker="x",zorder=5)
    axes[0,0].set(xlabel="Tower control displacement (mm)", ylabel="Base shear (kN)",title="A. Global curve hides the local event")
    axes[0,0].legend(fontsize=8)
    for stage, label, color in ((6, "Loading to -0.6%", "#167b82"), (7, "Return toward +1.0%", "#c03d3e")):
        rows=[r for r in member877 if int(r["stage"])==stage]
        axes[0,1].plot([float(by_step[int(r["step"])]["u_m"])*1000 for r in rows],
                       [-100*float(r["strain"]) for r in rows],color=color,label=label)
    rows=[r for r in fine_member877 if int(r["stage"])==7]
    axes[0,1].plot([float(fine_by_step[int(r["step"])]["u_m"])*1000 for r in rows],
                   [-100*float(r["strain"]) for r in rows], color="#6b56a1", ls="--", label="Fine-step return: jump back to pre-peak")
    axes[0,1].set(xlim=(-225,-80), xlabel="Tower control displacement (mm)",ylabel="Rod 877 compression strain (%)",title="B. Local jump and return jump")
    axes[0,1].legend(fontsize=8)
    group=json.loads((root/'baseline/calibration_library.json').read_text())["groups"]["L40x3Q235|0.850000"]
    pts=[{"strain":0,"stress":0},*group["compression_envelope"]]
    axes[1,0].plot([-100*p["strain"] for p in pts],[-p["stress"]*group["member"]["area"]/1000 for p in pts],color="#334155",marker=".")
    stop=member877[-1]
    axes[1,0].scatter([-100*float(stop["strain"])],[-float(stop["force_N"])/1000],c="#c03d3e",marker="x",s=60,label="Last accepted state")
    axes[1,0].axvline(.375,ls="--",color="#d39b35",label="Unloading corner: 0.375%")
    axes[1,0].set(xlim=(0,.65),xlabel="Compression strain (%)",ylabel="Compression force (kN)",title="C. Return encounters a steeper negative tangent")
    axes[1,0].legend(fontsize=8)
    attempts=[json.loads(line) for line in (root/'baseline/attempts.jsonl').open()]
    fail=next(r for r in attempts if r["step_before"]==272 and r["algorithm"]=="Newton" and r["increment"]==.0003125)
    axes[1,1].semilogy(np.arange(1,len(fail["norms"])+1),fail["norms"],color="#c03d3e",label="Newton displacement-increment norm")
    axes[1,1].axhline(1e-6,ls="--",color="#167b82",label="Convergence tolerance")
    axes[1,1].set(xlabel="Iteration",ylabel="Norm",title="D. Iteration stagnates instead of converging")
    axes[1,1].legend(fontsize=8)
    for ax in axes.flat: ax.grid(alpha=.2)
    fig.savefig(root / "convergence_diagnosis.png", dpi=180);plt.close(fig)
    print(json.dumps({"local_stability":stability,"material_replay":replay,"checkpoints":checkpoints},indent=2))


if __name__ == "__main__":
    main()
