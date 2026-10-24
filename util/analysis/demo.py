"""Small analytic OpenSees checks that leave the full-tower result folders alone."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from . import AdaptiveStepper, RunManifest, cyclic_targets
from ..postprocess.response_metrics import path_work


def run_demo(output: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import openseespy.opensees as ops

    def spring(*, dynamic: bool):
        ops.wipe()
        ops.model("basic", "-ndm", 1, "-ndf", 1)
        ops.node(1, 0.)
        ops.node(2, 0.)
        ops.fix(1, 1)
        ops.mass(2, 2.)
        ops.uniaxialMaterial("Elastic", 1, 200.)
        ops.element("zeroLength", 1, 1, 2, "-mat", 1, "-dir", 1)
        ops.timeSeries("Constant" if dynamic else "Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 1.)
        ops.system("BandGeneral")
        ops.numberer("RCM")
        ops.constraints("Plain")
        ops.test("NormDispIncr", 1e-12, 30)
        ops.algorithm("Newton")

    with RunManifest(output, parameters={"example": "elastic_spring", "k_n_per_m": 200,
                                          "mass_kg": 2, "dt_s": .001}, input_files=[Path(__file__)]) as run:
        try:
            spring(dynamic=False)
            ops.integrator("DisplacementControl", 2, 1, .001)
            ops.analysis("Static")
            static_points = [{"displacement_m": 0., "force_n": 0., "analytical_n": 0.}]
            static_solver = AdaptiveStepper(
                ops, progress=lambda: ops.nodeDisp(2, 1),
                configure_increment=lambda du: ops.integrator("DisplacementControl", 2, 1, du),
                convergence_test=("NormDispIncr", 1e-12, 30), minimum_increment=.0001,
            )

            def capture_static(_):
                x = float(ops.nodeDisp(2, 1))
                static_points.append({"displacement_m": x, "force_n": float(ops.getLoadFactor(1)),
                                      "analytical_n": 200 * x})

            for target in cyclic_targets([.01, .02]):
                if not static_solver.advance_to(target, maximum_increment=.003,
                                                 on_step=capture_static).converged:
                    raise RuntimeError("静力弹簧校验未完成。")
            static_error = max(abs(p["force_n"] - p["analytical_n"]) for p in static_points)

            spring(dynamic=True)
            ops.integrator("Newmark", .5, .25)
            ops.analysis("Transient")
            ops.setNodeAccel(2, 1, .5, "-commit")
            dynamic_points = [{"time_s": 0., "displacement_m": 0., "analytical_m": 0.}]
            dynamic_solver = AdaptiveStepper(ops, progress=ops.getTime, transient=True,
                                            convergence_test=("NormDispIncr", 1e-12, 30), minimum_increment=1e-5)

            def capture_dynamic(_):
                t = float(ops.getTime())
                dynamic_points.append({"time_s": t, "displacement_m": float(ops.nodeDisp(2, 1)),
                                       "analytical_m": (1 - math.cos(10 * t)) / 200})

            if not dynamic_solver.advance_to(.2, maximum_increment=.001, on_step=capture_dynamic).converged:
                raise RuntimeError("动力弹簧校验未完成。")
            dynamic_error = max(abs(p["displacement_m"] - p["analytical_m"]) for p in dynamic_points)
            summary = {
                "static_maximum_force_error_n": static_error,
                "static_return_path_work_j": path_work((p["displacement_m"], p["force_n"]) for p in static_points),
                "transient_maximum_displacement_error_m": dynamic_error,
                "transient_end_time_s": float(ops.getTime()),
                "static_solver": static_solver.diagnostics(), "transient_solver": dynamic_solver.diagnostics(),
                "passed": static_error < 1e-8 and dynamic_error < 1e-6,
            }
            for name, points in (("static", static_points), ("transient", dynamic_points)):
                path = output / f"{name}.csv"
                with path.open("w", encoding="utf-8", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=list(points[0]))
                    writer.writeheader()
                    writer.writerows(points)
                run.add_artifact(name, path)
            figure, axes = plt.subplots(1, 2, figsize=(10, 4))
            axes[0].plot([p["displacement_m"] for p in static_points],
                         [p["force_n"] for p in static_points], label="OpenSees cyclic response")
            axes[0].set(xlabel="Displacement (m)", ylabel="Force (N)", title="Static spring: F = 200u")
            axes[1].plot([p["time_s"] for p in dynamic_points],
                         [p["displacement_m"] for p in dynamic_points], label="Newmark")
            axes[1].plot([p["time_s"] for p in dynamic_points],
                         [p["analytical_m"] for p in dynamic_points], "--", label="Analytical")
            axes[1].set(xlabel="Time (s)", ylabel="Displacement (m)", title="Constant-load oscillator")
            for axis in axes:
                axis.legend(fontsize=8)
                axis.grid(alpha=.25)
            figure.tight_layout()
            figure.savefig(output / "verification.png", dpi=160)
            plt.close(figure)
            (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            run.add_artifact("summary", output / "summary.json")
            run.add_artifact("figure", output / "verification.png")
            run.update(completed_steps=len(static_points) + len(dynamic_points) - 2)
            if not summary["passed"]:
                raise RuntimeError("弹簧算例与解析解的误差超过验收界限。")
            return summary
        finally:
            ops.wipe()


def main() -> None:
    parser = argparse.ArgumentParser(description="通用分析模块的 OpenSees 解析小算例")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / ".output" / "demo")
    arguments = parser.parse_args()
    print(json.dumps(run_demo(arguments.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
