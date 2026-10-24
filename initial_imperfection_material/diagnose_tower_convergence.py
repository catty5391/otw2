"""Isolated, instrumented reproductions; never overwrite the formal cyclic run.

Section axial strain is constant along the current dispBeamColumn interpolation.
All three integration points are checked at gravity; subsequent CSV rows use the
first. Failed-attempt section responses are labelled trial (not committed data).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import time
from pathlib import Path

import numpy as np
import openseespy.opensees as ops
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import eigsh

from initial_imperfection_material.full_tower_cyclic import (
    BASE_NODE_TAGS, DEFAULT_OUTPUT, DEFAULT_SOURCE, _apply_gravity, _base_shear,
    _build_model, _configure_static, default_protocol,
)
from util import PushoverWindLoadApplier
from util.analysis import AdaptiveStepper, Algorithm, RunManifest


DEFAULT_DIAGNOSIS = DEFAULT_OUTPUT.parent / "convergence_diagnosis"


class StiffnessProbe:
    """Read the assembled tangent without advancing/committing the domain.

    Standard eigenvalues are stiffness diagnostics, not vibration frequencies.
    Save K separately so constrained/condensed local stability can be examined.
    """

    def __init__(self, path):
        self.path = path

    def solve(self, **kw):
        from scipy.sparse import save_npz

        n = kw["num_eqn"]
        matrix = csr_matrix((np.frombuffer(kw["k_values"], dtype=np.float64).copy(),
                             np.frombuffer(kw["indices"], dtype=np.int32).copy(),
                             np.frombuffer(kw["index_ptr"], dtype=np.int32).copy()), shape=(n, n))
        save_npz(self.path, matrix)
        values, vectors = eigsh(matrix, k=kw["num_modes"], sigma=0.0, which="LM", tol=1e-10,
                                v0=np.ones(n))
        order = np.argsort(values)
        np.frombuffer(kw["eigenvalues"], dtype=np.float64)[:] = values[order]
        np.frombuffer(kw["eigenvectors"], dtype=np.float64)[:] = vectors[:, order].T.ravel()


def axial_state(model, tag):
    deformation = ops.eleResponse(tag, "section", 1, "deformation")
    force = ops.eleResponse(tag, "section", 1, "force")
    stiffness = ops.eleResponse(tag, "section", 1, "stiffness")
    if len(deformation) != 4 or len(force) != 4 or len(stiffness) != 16:
        raise RuntimeError(f"Unexpected section response for {tag}")
    material = model.equivalent_materials[tag]
    peak = max(material.compression_envelope, key=lambda p: abs(p.stress))
    return {
        "element": tag, "strain": deformation[0], "force_N": force[0],
        "axial_tangent_N": stiffness[0],
        "peak_strain_ratio": deformation[0] / peak.strain,
        "compression_force_peak_ratio": max(0.0, -force[0]) / material.peak_compressive_load,
    }


def run(args):
    output = args.output.resolve()
    if output == DEFAULT_OUTPUT.resolve() or DEFAULT_OUTPUT.resolve() in output.parents:
        raise ValueError("诊断不能写入正式 full_tower_cyclic 结果目录。")
    if (output / "run_manifest.json").exists():
        raise ValueError("诊断目录已有运行记录，请指定新目录保存本轮证据。")
    output.mkdir(parents=True, exist_ok=True)
    parameters = vars(args).copy()
    parameters["output"] = str(output)
    with RunManifest(output, parameters=parameters, input_files=(
        Path(__file__), DEFAULT_SOURCE, DEFAULT_OUTPUT / "calibration_library.json",
        Path(__file__).with_name("material.py"),
        DEFAULT_SOURCE.parents[1] / "model/tower_model_with_equivalent_imperfection.py",
    ), seed=30103) as manifest:
        try:
            _run(args, output, manifest)
        finally:
            ops.wipe()


def _run(args, output, manifest):
    started = time.perf_counter()
    shutil.copyfile(DEFAULT_OUTPUT / "calibration_library.json", output / "calibration_library.json")
    model = _build_model("equivalent", source=DEFAULT_SOURCE, output_dir=output,
                         calibration_cache=output / "calibration_library.json",
                         imperfection_ratio=.001, reference_divisions=4,
                         allow_legacy_calibration_cache=True)
    if args.elastic_members:
        # Diagnostic ablation only: rebuild selected elements with an elastic P
        # channel; bending, torsion, geometry, all other rods and loads unchanged.
        for tag in args.elastic_members:
            record = model.element_map[tag]
            old_section = model.section_tag_map[record["section_tag"]]
            mat_tag, sec_tag, int_tag = 100000 + tag, 100000 + tag, 100000 + tag
            ea = model.equivalent_materials[tag].member.elastic_modulus * record["area"]
            ops.uniaxialMaterial("Elastic", mat_tag, ea)
            ops.section("Aggregator", sec_tag, mat_tag, "P", old_section["mz_mat_tag"], "Mz",
                        old_section["my_mat_tag"], "My", old_section["torsion_mat_tag"], "T")
            ops.beamIntegration("Legendre", int_tag, sec_tag, 3)
            ops.remove("element", tag)
            ops.element("dispBeamColumn", tag, record["node_i"], record["node_j"], record["transf_tag"], int_tag)
    control = model.resolve_node_tag(350)
    bases = [model.resolve_node_tag(tag) for tag in BASE_NODE_TAGS]
    height = model.get_node_coord(350)[2]
    ops.logFile(str(output / "opensees.log"), "-noEcho")
    _apply_gravity(model)
    gravity = ops.nodeDisp(control, 2)
    wind = PushoverWindLoadApplier(tag_manager=model.tag_manager, load_dof=2).apply_from_model(model)
    for tag in model.element_map:
        strains = [ops.eleResponse(tag, "section", point, "deformation")[0] for point in (1, 2, 3)]
        if max(strains) - min(strains) > 1e-12:
            raise RuntimeError("Axial strain varies along integration points")
    _configure_static(args.increment, control, 2)
    tags = sorted(model.element_map)
    metadata = []
    for tag in tags:
        record = dict(model.element_map[tag])
        record["node_i_coord"] = ops.nodeCoord(record["node_i"])
        record["node_j_coord"] = ops.nodeCoord(record["node_j"])
        metadata.append(record)
    (output / "member_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    protocol = default_protocol() if args.protocol == "full" else (-.006, .01)
    step = stage = 0
    completed = 0
    failed_target = None
    last = []
    stiffness_probe = StiffnessProbe(output / "stiffness.npz")
    with (output / "history.csv").open("w", newline="") as hfile, \
         (output / "members.csv").open("w", newline="") as mfile, \
         (output / "attempts.jsonl").open("w") as afile:
        history = csv.DictWriter(hfile, fieldnames=("step", "stage", "u_m", "base_shear_N", "load_factor",
                                                    "negative_tangents", "max_compression_peak_ratio"))
        members = csv.DictWriter(mfile, fieldnames=("step", "stage", "element", "strain", "force_N",
                                                    "axial_tangent_N", "peak_strain_ratio", "compression_force_peak_ratio"))
        history.writeheader()
        members.writeheader()

        def capture():
            nonlocal last
            last = [axial_state(model, tag) for tag in tags]
            for row in last:
                members.writerow({"step": step, "stage": stage, **row})
            history.writerow({"step": step, "stage": stage, "u_m": ops.nodeDisp(control, 2) - gravity,
                              "base_shear_N": _base_shear(bases, 2), "load_factor": ops.getLoadFactor(wind.pattern_tag),
                              "negative_tangents": sum(row["axial_tangent_N"] < 0 for row in last),
                              "max_compression_peak_ratio": max(row["compression_force_peak_ratio"] for row in last)})
            hfile.flush()
            mfile.flush()
            if args.spectrum and step in (0, 249, 250, 251, 266, 267, 271, 272):
                stiffness_probe.path = output / f"stiffness_{step:04d}.npz"
                values = list(ops.eigen("standard", "PythonSparse", 6,
                                       {"solver": stiffness_probe,
                                        "scheme": "CSR"}))
                modes = []
                for mode in range(1, 7):
                    nodes = [{"node": n, "coord": ops.nodeCoord(n), "vector": ops.nodeEigenvector(n, mode)}
                             for n in ops.getNodeTags()]
                    modes.append(nodes)
                snapshot = {"step": step, "eigenvalues": values, "modes": modes,
                            "node_displacements": {n: ops.nodeDisp(n) for n in ops.getNodeTags()},
                            "node_dofs": {n: ops.nodeDOFs(n) for n in ops.getNodeTags()}}
                (output / f"spectrum_{step:04d}.json").write_text(json.dumps(snapshot), encoding="utf-8")

        def attempt(event):
            norms = list(ops.testNorms())
            iterations = int(ops.testIter())
            event.update(step_before=step, stage=stage, iterations=iterations,
                         norms=norms[:min(iterations, len(norms))])
            if event["return_code"] != 0:
                trial = [axial_state(model, tag) for tag in tags]
                event["trial_negative_tangents"] = [r for r in trial if r["axial_tangent_N"] < 0]
                event["trial_perry_members"] = [r for r in trial if r["element"] in (825, 828, 917, 920)]
            afile.write(json.dumps(event) + "\n")
            afile.flush()

        algorithms = (Algorithm("Newton"), Algorithm("KrylovNewton"), Algorithm("NewtonLineSearch", (.8,)))
        if args.algorithm == "initial":
            algorithms = (Algorithm("Newton", ("-initial",)),)
        elif args.algorithm != "fallback":
            algorithms = (Algorithm(args.algorithm),)
        stepper = AdaptiveStepper(ops, progress=lambda: float(ops.nodeDisp(control, 2)),
            configure_increment=lambda inc: ops.integrator("DisplacementControl", control, 2, inc),
            minimum_increment=args.minimum_increment, algorithms=algorithms,
            convergence_test=("NormDispIncr", args.tolerance, args.iterations, 0), on_attempt=attempt)
        capture()
        for stage, ratio in enumerate(protocol, 1):
            target = gravity + ratio * height
            while abs(target - ops.nodeDisp(control, 2)) > 1e-9:
                remaining = target - ops.nodeDisp(control, 2)
                result = stepper.step(math.copysign(min(abs(remaining), args.increment), remaining))
                if not result.converged:
                    failed_target = ratio
                    break
                step += 1
                capture()
                if step % 40 == 0:
                    print(json.dumps({"step": step, "stage": stage, "u_mm": (ops.nodeDisp(control, 2)-gravity)*1000,
                                      "negative_tangents": sum(r["axial_tangent_N"] < 0 for r in last)}), flush=True)
                    manifest.update(completed_steps=step, completed_targets=completed, solver=stepper.diagnostics())
            if failed_target is not None:
                break
            completed = stage
            print(f"Completed target {stage}: {ratio:+.4%}", flush=True)
        summary = {"converged": failed_target is None, "completed_targets": completed,
                   "requested_targets": len(protocol), "failed_target": failed_target, "steps": step,
                   "final_u_m": ops.nodeDisp(control, 2)-gravity, "runtime_seconds": time.perf_counter()-started,
                   "solver": stepper.diagnostics(), "opensees_version": ops.version(),
                   "last_committed_negative_tangents": [r for r in last if r["axial_tangent_N"] < 0],
                   "last_committed_perry_members": [r for r in last if r["element"] in (825,828,917,920)]}
        (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        manifest.update(completed_steps=step)
        manifest.finish(**summary)
        print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--increment", type=float, default=.005)
    parser.add_argument("--minimum-increment", type=float, default=.0003125)
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    parser.add_argument("--algorithm", default="fallback", choices=("fallback", "Newton", "KrylovNewton", "NewtonLineSearch", "ModifiedNewton", "initial"))
    parser.add_argument("--protocol", default="full", choices=("full", "negative_return"))
    parser.add_argument("--spectrum", action="store_true")
    parser.add_argument("--elastic-members", nargs="*", type=int, default=[])
    args = parser.parse_args()
    if (not all(math.isfinite(value) for value in (args.minimum_increment, args.increment, args.tolerance))
            or not 0 < args.minimum_increment <= args.increment or args.tolerance <= 0 or args.iterations < 1):
        parser.error("Invalid step or convergence settings")
    run(args)


if __name__ == "__main__":
    main()
