"""V-string analytical checks and isolated 0/45-degree tower-line sensitivity runs.

Actual string geometry/type is unconfirmed. No result here is a design capacity.
Raw outputs are local and never overwrite earlier runs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from model.insulator_mechanics import register_axial_material

MODULE = Path(__file__).resolve().parent
ROOT = MODULE.parents[1]
VARIANTS = {"elastic": ("elastic", 1.), "tension_only": ("tension_only", 0.),
            "regularized": ("regularized_tension_only", 1e-6)}


def analytical_slack_state(half_width, drop, ea, weight, horizontal_force):
    """Exact finite-EA solution with one straight taut leg and one slack leg."""
    if min(half_width, drop, ea, weight) <= 0 or not math.isfinite(horizontal_force):
        raise ValueError("Positive geometry/EA/weight and finite horizontal force required")
    side = 1 if horizontal_force >= 0 else -1
    length = math.hypot(half_width, drop)
    force = math.hypot(horizontal_force, weight)
    current_length = length*(1+force/ea)
    x = -side*half_width+current_length*horizontal_force/force
    z = -current_length*weight/force
    slack_length = math.hypot(x-side*half_width, z)
    if slack_length > length+1e-9:
        raise ValueError("Both legs remain taut; single-taut-leg solution is not applicable")
    return {"x_m": x, "z_m": z, "taut_force_N": force, "slack_length_m": slack_length}


def run_standalone(variant="tension_only", *, increment=.025,
                   targets=(0., 1., 2., 2.2, 3., 0., -3., 0.)):
    import openseespy.opensees as ops
    from util.analysis.stepping import AdaptiveStepper
    behavior, ratio = VARIANTS[variant]
    a, h, ea, weight = 8.675, 4., 1e8, 5000.
    rows, attempts = [], []
    ops.wipe()
    try:
        ops.model("basic", "-ndm", 2, "-ndf", 2)
        ops.node(1, -a, 0.); ops.node(2, a, 0.); ops.node(3, 0., -h)
        ops.fix(1, 1, 1); ops.fix(2, 1, 1)
        register_axial_material(ops, 1, ea, 1., {"axial_behavior": behavior, "compression_stiffness_ratio": ratio})
        ops.element("corotTruss", 1, 1, 3, 1., 1)
        ops.element("corotTruss", 2, 2, 3, 1., 1)
        ops.timeSeries("Linear", 1); ops.pattern("Plain", 1, 1); ops.load(3, 0., -weight)
        ops.constraints("Plain"); ops.numberer("Plain"); ops.system("BandGeneral")
        ops.test("NormUnbalance", 1e-7, 40); ops.algorithm("Newton")
        ops.integrator("LoadControl", .1); ops.analysis("Static")
        if ops.analyze(10) != 0:
            raise RuntimeError("Standalone gravity did not converge")
        ops.loadConst("-time", 0.)
        ops.timeSeries("Linear", 2); ops.pattern("Plain", 2, 2); ops.load(3, weight, 0.)

        def capture():
            factor = ops.getLoadFactor(2)
            ux, uz = ops.nodeDisp(3)
            forces = [float(ops.eleResponse(tag, "axialForce")[0]) for tag in (1, 2)]
            ops.reactions()
            residual = math.hypot(ops.nodeReaction(1, 1)+ops.nodeReaction(2, 1)+factor*weight,
                                  ops.nodeReaction(1, 2)+ops.nodeReaction(2, 2)-weight)
            rows.append({"step": len(rows), "horizontal_to_vertical_ratio": factor,
                         "horizontal_force_N": factor*weight, "ux_m": ux, "uz_m": uz,
                         "left_force_N": forces[0], "right_force_N": forces[1],
                         "support_equilibrium_residual_N": residual})

        capture()
        stepper = AdaptiveStepper(ops, progress=lambda: ops.getLoadFactor(2),
            configure_increment=lambda value: ops.integrator("LoadControl", value),
            minimum_increment=1e-6, convergence_test=("NormUnbalance", 1e-7, 50, 0),
            timeout_seconds=60, maximum_total_attempts=3000, maximum_accepted_steps=2000,
            on_attempt=attempts.append, recovery_policy="gradual")
        for target in targets:
            while abs(target-ops.getLoadFactor(2)) > 1e-10:
                value = target-ops.getLoadFactor(2)
                result = stepper.step(math.copysign(min(abs(value), increment), value))
                if not result.converged:
                    raise RuntimeError(f"Standalone V-string stopped: {result.stop_reason}")
                capture()
        peak = max(rows, key=lambda row: row["horizontal_to_vertical_ratio"])
        prediction = analytical_slack_state(a, h, ea, weight, peak["horizontal_force_N"])
        last = rows[-1]
        summary = {"variant": variant, "axial_behavior": behavior, "compression_stiffness_ratio": ratio,
                   "half_upper_separation_m": a, "drop_m": h, "EA_N": ea, "vertical_load_N": weight,
                   "initial_length_m": math.hypot(a,h), "rigid_geometry_slack_threshold_H_over_W": a/h,
                   "steps": len(rows)-1, "targets": list(targets), "peak": peak,
                   "single_taut_leg_analytical_solution": prediction,
                   "analytical_position_error_m": math.hypot(peak["ux_m"]-prediction["x_m"], -h+peak["uz_m"]-prediction["z_m"]),
                   "return_to_gravity_position_error_m": math.hypot(last["ux_m"]-rows[0]["ux_m"],last["uz_m"]-rows[0]["uz_m"]),
                   "maximum_equilibrium_residual_N": max(row["support_equilibrium_residual_N"] for row in rows),
                   "minimum_force_N": min(min(row["left_force_N"],row["right_force_N"]) for row in rows),
                   "solver_attempts": len(attempts), "physical_validation": "uncalibrated_sensitivity_assumption"}
        return summary, rows
    finally:
        ops.wipe()


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def run_tower_case(output, variant, angle, segments=20):
    from .directional_loading import verification_config, validate_config
    behavior, ratio = VARIANTS[variant]
    key = f"{variant}_{angle}"
    config = verification_config(angle, mode="tower_line_explicit", line_segments=segments)
    config.update(insulator_axial_behavior=behavior, insulator_compression_stiffness_ratio=ratio)
    config = validate_config(config)
    path = output / "configs" / f"{key}.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2)+"\n")
    command = [sys.executable, "-m", "initial_imperfection_material.tian_ma_qu.full_tower",
               "--output", str(output/"runs"/key), "--wind-config", str(path), "--control-dof", "1",
               "--record-nodes", "--timeout", "600", "--maximum-load-increment", ".25",
               "--minimum-load-increment", ".0001", "--wind-speed-targets",
               "20", "40", "45", "46", "50", "60", "64", "65", "66", "70", "80", "90", "100"]
    env = {**os.environ, "CXX": "/usr/bin/g++-13", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
    start = time.monotonic()
    with (output/"logs"/f"{key}.log").open("w") as stream:
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=720)
            code, timed_out = result.returncode, False
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
    execution = {"key": key, "variant": variant, "wind_angle_deg": angle, "segments_per_span": segments,
                 "command": command, "returncode": code, "external_timeout": timed_out,
                 "elapsed_seconds": time.monotonic()-start}
    (output/"logs"/f"{key}_execution.json").write_text(json.dumps(execution, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({k:v for k,v in execution.items() if k!="command"}), flush=True)
    return execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tower", action="store_true")
    parser.add_argument("--segments", type=int, default=20)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    for folder in ("standalone", "configs", "runs", "logs"):
        (output/folder).mkdir(parents=True, exist_ok=True)
    summaries = []
    for variant in VARIANTS:
        summary, rows = run_standalone(variant)
        summaries.append(summary)
        write_csv(output/"standalone"/f"{variant}.csv", rows)
    (output/"standalone"/"summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(summaries, ensure_ascii=False), flush=True)
    if args.tower:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run_tower_case, output, variant, angle, args.segments)
                       for variant in VARIANTS for angle in (0,45)]
            executions = [future.result() for future in futures]
        (output/"execution.json").write_text(json.dumps(executions, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
