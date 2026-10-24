"""T01 actual-section and real OpenSees elastic parity audit (no full tower)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import openseespy.opensees as ops

from model.mechanical_profile import (
    MechanicalCatalog, MechanicalProfile, beam_tangent, fiber_moments,
    fiber_section_tangent, local_axes, rigid_body_modes, scaled_tangent,
)
from model.tower_model import OpenSeesModel


def opensees_elastic_tangents(member: dict[str, Any], *, aggregator: bool = False,
                              principal_axes: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Extract the section 4x4 and *uncondensed* beam 12x12 tangent.

    Lagrange constraints fix all physical DOFs; their multiplier rows are
    excluded using nodeDOFs. This avoids singular free-free solves and penalty
    contamination. This deliberately owns/wipes the process's OpenSees domain.
    """
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    for tag, point in enumerate(member["coordinates"], 1):
        ops.node(tag, *point)
    section, E0 = member["section"], member["steel_tower"]["E0"]
    GJ = member["G"] * section["tors_const"]
    principal_rotation = None
    if principal_axes and not aggregator:
        raise ValueError("Principal-axis prototype requires the elastic aggregator")
    if aggregator:
        if principal_axes:
            moments = fiber_moments(member["fibers"])
            values, vectors = np.linalg.eigh([[moments["i33"], -moments["integral_yz"]],
                                             [-moments["integral_yz"], moments["i22"]]])
            if np.linalg.det(vectors) < 0:
                vectors[:, 0] *= -1
            principal_rotation = vectors.T
            channel_stiffnesses = (E0 * moments["area"], E0 * values[0], E0 * values[1], GJ)
        else:
            channel_stiffnesses = (E0 * section["area"], E0 * section["i33"], E0 * section["i22"], GJ)
        for tag, value in enumerate(channel_stiffnesses, 1):
            ops.uniaxialMaterial("Elastic", tag, value)
        ops.section("Aggregator", 1, 1, "P", 2, "Mz", 3, "My", 4, "T")
    else:
        ops.uniaxialMaterial("Elastic", 1, E0)
        ops.section("Fiber", 1, "-GJ", GJ)
        for patch in member["patches"]:
            ops.patch("rect", 1, patch["num_y"], patch["num_z"],
                      patch["y_i"], patch["z_i"], patch["y_j"], patch["z_j"])
    nodes = [dict(zip(("x", "y", "z"), point)) for point in member["coordinates"]]
    if principal_rotation is None:
        orientation = OpenSeesModel._geom_transf_vector(*nodes)
    else:
        axes = local_axes(member["coordinates"])
        cosine, sine = principal_rotation[0, 0], principal_rotation[1, 0]
        orientation = -sine * axes[1] + cosine * axes[2]
    ops.geomTransf("Linear", 1, *orientation)
    ops.beamIntegration("Legendre" if aggregator else member["profile"]["integration_type"],
                        1, 1, 3 if aggregator else member["profile"]["integration_points"])
    ops.element("dispBeamColumn", 1, 1, 2, 1, 1)
    for tag in (1, 2):
        ops.fix(tag, 1, 1, 1, 1, 1, 1)
    ops.constraints("Lagrange")
    ops.numberer("Plain")
    ops.system("FullGeneral")
    ops.test("NormDispIncr", 1e-12, 10)
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    if ops.analyze(1) != 0:
        raise RuntimeError("Elastic audit constraint solve failed")
    size = ops.systemSize()
    matrix = np.asarray(ops.printA("-ret"), dtype=float).reshape(size, size)
    dofs = list(ops.nodeDOFs(1)) + list(ops.nodeDOFs(2))
    beam = matrix[np.ix_(dofs, dofs)]
    section_values = np.asarray(ops.eleResponse(1, "section", 1, "stiffness"), dtype=float)
    if section_values.size != 16:
        raise RuntimeError("Engine does not expose the required section tangent")
    return section_values.reshape(4, 4), beam


def audit_member(member: dict[str, Any]) -> dict[str, Any]:
    section, steel = member["section"], member["steel_tower"]
    moments = fiber_moments(member["fibers"])
    E0, length = steel["E0"], member["length"]
    analytical_section = fiber_section_tangent(member["fibers"], E0, member["G"] * section["tors_const"])
    actual_section, actual_beam = opensees_elastic_tangents(member)
    uncoupled_section, uncoupled_beam = opensees_elastic_tangents(member, aggregator=True)
    principal_section, principal_beam = opensees_elastic_tangents(member, aggregator=True, principal_axes=True)
    analytical_beam = beam_tangent(analytical_section, member["coordinates"])
    scaled = scaled_tangent(analytical_beam, length, E0 * section["area"])
    difference = scaled_tangent(actual_beam - analytical_beam, length, E0 * section["area"])
    # Section units differ; compare the actual/analytical entries after energy scaling.
    section_scale = np.diag([1.0, 1.0 / length, 1.0 / length, 1.0 / length])
    section_relative_error = np.linalg.norm(section_scale @ (actual_section - analytical_section) @ section_scale) / np.linalg.norm(section_scale @ analytical_section @ section_scale)
    rigid = rigid_body_modes(member["coordinates"])
    rigid_residual = np.linalg.norm(actual_beam @ rigid) / (np.linalg.norm(actual_beam) * np.linalg.norm(rigid))
    raw_inertia = np.array([[section["i33"], section["i23"]], [section["i23"], section["i22"]]])
    exact_eigen = np.linalg.eigvalsh(raw_inertia)
    bending_relative_difference = np.linalg.norm(uncoupled_section[1:3, 1:3] - actual_section[1:3, 1:3]) / np.linalg.norm(actual_section[1:3, 1:3])
    axes = local_axes(member["coordinates"])
    transform = np.zeros((12, 12))
    for index in range(0, 12, 3):
        transform[index:index + 3, index:index + 3] = axes
    unit_modes = {}
    for name, dof in (("axial_extension", 6), ("bending_y_translation", 7),
                      ("bending_z_translation", 8), ("torsion_rotation", 9)):
        local = np.zeros(12)
        local[dof] = length if dof < 9 else 1.0
        global_displacement = transform.T @ local
        force = actual_beam @ global_displacement
        expected = analytical_beam @ global_displacement
        unit_modes[name] = {"scaled_reaction_relative_error": float(np.linalg.norm(force - expected) / np.linalg.norm(expected)),
                            "local_reaction_per_unit_mode": (transform @ force).tolist()}
    return {
        "member_id": member["member_id"], "section_name": section["section_name"],
        "node_ids": member["node_ids"], "coordinates_m": member["coordinates"], "length_m": length,
        "local_axes_rows_xyz": axes.tolist(), "section_source": section,
        "fiber_count": len(member["fibers"]), "fiber_moments": moments,
        "fiber_area_relative_error": (moments["area"] - section["area"]) / section["area"],
        "fiber_i22_relative_error": (moments["i22"] - section["i22"]) / section["i22"],
        "fiber_i33_relative_error": (moments["i33"] - section["i33"]) / section["i33"],
        "fiber_cross_stiffness_relative_error": (-moments["integral_yz"] - section["i23"]) / np.sqrt(section["i22"] * section["i33"]),
        "fiber_weak_inertia_relative_error": (moments["weak_principal"] - exact_eigen[0]) / exact_eigen[0],
        "section_analytical_engine_relative_error": float(section_relative_error),
        "beam_analytical_engine_relative_error": float(np.linalg.norm(difference) / np.linalg.norm(scaled)),
        "rigid_body_relative_residual": float(rigid_residual),
        "uncoupled_bending_relative_difference": float(bending_relative_difference),
        "uncoupled_weak_stiffness_relative_difference": float(min(section["i22"], section["i33"]) / moments["weak_principal"] - 1),
        "section_tangent_fiber": actual_section.tolist(), "section_tangent_uncoupled": uncoupled_section.tolist(),
        "beam_tangent_fiber": actual_beam.tolist(), "beam_tangent_uncoupled": uncoupled_beam.tolist(),
        "beam_tangent_principal_axes_prototype": principal_beam.tolist(),
        "principal_axes_global_beam_relative_error": float(np.linalg.norm(scaled_tangent(principal_beam - actual_beam, length, E0 * section["area"])) / np.linalg.norm(scaled)),
        "principal_axes_prototype_scope": "Pure elastic fiber-moment-matched isolated prototype; rotates section axes and full element global mapping, not deployed.",
        "steel_member": member["steel_member"], "steel_tower": member["steel_tower"],
        "unit_modes": unit_modes,
        "elastic_implementation_passed": bool(section_relative_error <= 1e-6 and np.linalg.norm(difference) / np.linalg.norm(scaled) <= 1e-6 and rigid_residual <= 1e-6
                                                and all(mode["scaled_reaction_relative_error"] <= 1e-6 for mode in unit_modes.values())),
        "fiber_inertia_1pct_passed": bool(max(abs((moments[key] - section[key]) / section[key]) for key in ("i22", "i33")) <= 0.01),
    }


def run_audit(source: Path, output: Path) -> dict[str, Any]:
    if (output / "mechanical_audit.json").exists():
        raise FileExistsError(f"Refusing to replace audit: {output}")
    output.mkdir(parents=True, exist_ok=True)
    catalog = MechanicalCatalog(source, output_dir=output / "parser")
    members = catalog.representative_members()
    rows = [audit_member(catalog.member(member_id)) for member_id in members]
    fine = MechanicalCatalog(source, output_dir=output / "parser_fine",
                             profile=MechanicalProfile(long_edge_segments=32, short_edge_segments=3))
    fine_rows = [audit_member(fine.member(member_id)) for member_id in members]
    vectors = catalog.imperfection_vectors()
    (output / "imperfection_vectors.json").write_text(json.dumps({
        "schema": "otw2.member_imperfection_vectors.v1", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "profile": catalog.profile.as_dict(), "frame": "global_XYZ_m",
        "vectors": {str(key): value for key, value in vectors.items()},
        "note": "Persisted original-traversal vectors, reuse by member ID for every mesh."}, indent=2), encoding="utf-8")
    summary = {"schema": "otw2.mechanical_audit.v1", "engine_version": ops.version(),
               "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "profile": catalog.profile.as_dict(), "members": rows, "fiber_refinement_32x3": fine_rows,
               "actual_tower_built": False,
               "conclusion": "Elastic implementation verified; existing equivalent bending is not section-equivalent. No production mechanics changed.",
               "scope": "Initial straight pure-Elastic tangent only; neither nonlinear boundary replay nor whole-tower validation.",
               "steel02_parameter_difference": ["a1", "a2", "a3", "a4"],
               "aligned_v1": "Declares tower Steel02 parameters for both families; not deployed or physically validated.",
               "section_convention": "Fiber eps=eps0-y*kappa_z+z*kappa_y; K_MzMy=-E*integral(y*z*dA). S2K positive I23 is reported separately.",
               "findings": [
                   {"field": "Steel02 a1-a4", "classification": "requires_alignment_before_cyclic_validation"},
                   {"field": "I23 bending coupling", "classification": "requires_coupling_or_explicit_limitation"},
                   {"field": "Fiber 8x1 discretization", "classification": "measured_error_not_assumed_exact"},
                   {"field": "6 vs 3 Legendre points", "classification": "elastic_initial_parity_only_not_nonlinear_parity"},
                   {"field": "boundary", "classification": "pinned_2d_vs_shared_6dof_requires_replay"},
                   {"field": "mass_and_gravity", "classification": "original_joint_lumped_only_no_added_segment_mass"}],
               "primary_sources": ["https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Steel02.html",
                                   "https://github.com/OpenSees/OpenSees/blob/master/SRC/material/section/FiberSection3d.cpp"]}
    (output / "mechanical_audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = ["member_id", "section_name", "length_m", "fiber_count", "fiber_i22_relative_error", "fiber_weak_inertia_relative_error",
               "uncoupled_bending_relative_difference", "uncoupled_weak_stiffness_relative_difference", "beam_analytical_engine_relative_error", "elastic_implementation_passed"]
    with (output / "mechanical_audit.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row[column] for column in columns} for row in rows)
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    figure, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    labels = [f'{row["member_id"]}\n{row["section_name"]}' for row in rows]
    positions = np.arange(len(rows))
    axes[0].bar(positions - 0.18, [100 * row["fiber_weak_inertia_relative_error"] for row in rows], width=0.36, label="Fiber 8x1")
    axes[0].bar(positions + 0.18, [100 * row["fiber_weak_inertia_relative_error"] for row in fine_rows], width=0.36, label="Fiber 32x3")
    axes[0].set_ylabel("Weak-axis inertia error (%)")
    axes[0].legend()
    axes[1].bar(positions, [100 * row["uncoupled_bending_relative_difference"] for row in rows])
    axes[1].set_ylabel("Uncoupled / fiber bending matrix difference (%)")
    for axis in axes:
        axis.set_xticks(positions, labels)
        axis.grid(axis="y", alpha=0.2)
    figure.savefig(output / "mechanical_audit.png", dpi=160)
    plt.close(figure)
    ops.wipe()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("Source/Z30103A6.s2k"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run_audit(args.source, args.output)
    print(json.dumps({"members": [row["member_id"] for row in summary["members"]],
                      "elastic_implementation_passed": all(row["elastic_implementation_passed"] for row in summary["members"]),
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
