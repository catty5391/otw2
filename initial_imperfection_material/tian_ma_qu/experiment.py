"""Reproducible displacement histories and independent OpenSees truss checks."""
from __future__ import annotations

import csv
import json
from dataclasses import replace
from math import isfinite
from pathlib import Path

import numpy as np

from .material import TianMaQuPrototype


def demonstration_targets():
    """Metres. Two large cycles at each amplitude; not an experimental record."""
    targets = [0.0, .001, -.001, 0.0]
    for amplitude in (.010, .015, .020, .025, .030, .035):
        targets.extend((amplitude, -amplitude, amplitude, -amplitude, amplitude))
    targets.append(0.0)
    return targets


def displacement_history(targets, steps_per_leg):
    if steps_per_leg < 1:
        raise ValueError("steps_per_leg must be positive")
    if len(targets) < 2 or targets[0] != 0 or not all(isfinite(v) for v in targets):
        raise ValueError("Need finite targets starting at zero")
    rows = [(0, 0, 0.0, True)]
    for leg, (start, end) in enumerate(zip(targets, targets[1:]), 1):
        if start == end:
            raise ValueError("Consecutive targets must differ")
        for index in range(1, steps_per_leg + 1):
            rows.append((len(rows), leg, start + (end-start)*index/steps_per_leg,
                         index == steps_per_leg))
    return rows


def simulate(case, targets=None, steps_per_leg=100):
    material = TianMaQuPrototype(case.parameters)
    rows, events = [], []
    history = displacement_history(demonstration_targets() if targets is None else targets, steps_per_leg)
    for step, leg, displacement, is_target in history:
        material.set_trial_strain(displacement / case.length)
        state = material.get_state()
        row = {"step": step, "leg": leg, "is_target": is_target,
               "displacement_m": displacement, "strain": state["strain"],
               "force_N": state["stress"] * case.area, "stress_Pa": state["stress"],
               "tangent_Pa": state["tangent"], "stage": state["stage"],
               "buckling_count": state["buckling_count"],
               "external_work_J": state["external_work_density"] * case.area * case.length}
        rows.append(row)
        events.extend({"step": step, "leg": leg, **event} for event in state["events"])
        material.commit_state()
    return rows, events


def curve_points(case, rows, events):
    """Include exact corners in time order; NEVER sort a hysteresis curve by strain."""
    by_step = {}
    for event in events:
        if event["event"] in ("corner", "buckling"):
            by_step.setdefault(event["step"], []).append(event)
    points = []
    for row in rows:
        for event in by_step.get(row["step"], []):
            points.append((event["strain"] * case.length * 1e3, event["stress"] * case.area / 1e3))
        points.append((row["displacement_m"] * 1e3, row["force_N"] / 1e3))
    return np.asarray(points)


def run_opensees(case, expected):
    """Actual single-truss equilibrium solves; independent from plotting driver.

    DisplacementControl follows negative tangents. A completed one-DOF member
    path does NOT imply stable/convergent full-tower displacement control.
    """
    import openseespy.opensees as ops
    from .opensees_adapter import register_material
    rows = [{"step": 0, "displacement_m": 0.0, "force_N": 0.0, "stress_Pa": 0.0,
             "strain": 0.0, "load_factor_N": 0.0, "reaction_N": 0.0}]
    failure = None
    ops.wipe()
    try:
        ops.model("basic", "-ndm", 1, "-ndf", 1)
        ops.node(1, 0.0)
        ops.node(2, case.length)
        ops.fix(1, 1)
        metadata = register_material(1, case.parameters)
        ops.element("truss", 1, 1, 2, case.area, 1)
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 1.0)
        ops.constraints("Plain")
        ops.numberer("Plain")
        ops.system("FullGeneral")
        ops.test("NormUnbalance", 1e-6, 30, 0)
        ops.algorithm("Newton")
        ops.integrator("DisplacementControl", 2, 1, 1e-6)
        ops.analysis("Static")
        for item in expected[1:]:
            increment = item["displacement_m"] - ops.nodeDisp(2, 1)
            ops.integrator("DisplacementControl", 2, 1, increment)
            code = ops.analyze(1)
            if code != 0:
                failure = {"step": item["step"], "return_code": code,
                           "target_displacement_m": item["displacement_m"]}
                break
            stress, strain = ops.eleResponse(1, "material", "stressStrain")
            ops.reactions()
            rows.append({"step": item["step"], "displacement_m": ops.nodeDisp(2, 1),
                         "force_N": stress * case.area, "stress_Pa": stress, "strain": strain,
                         "load_factor_N": ops.getLoadFactor(1), "reaction_N": ops.nodeReaction(1, 1)})
        common = len(rows)
        differences = [abs(row["stress_Pa"] - expected[i]["stress_Pa"]) for i, row in enumerate(rows)]
        equilibrium = [abs(row["force_N"] + row["reaction_N"]) for row in rows]
        load_balance = [abs(row["force_N"] - row["load_factor_N"]) for row in rows]
        result = {"engine_version": ops.version(), "adapter": metadata,
                  "requested_steps": len(expected)-1, "completed_steps": common-1,
                  "complete": failure is None and common == len(expected), "failure": failure,
                  "max_stress_difference_Pa": max(differences),
                  "max_reaction_balance_error_N": max(equilibrium),
                  "max_load_balance_error_N": max(load_balance),
                  "scope": "adapter/kinematics/equilibrium cross-check, NOT independent material validation"}
        result["passed"] = result["complete"] and max(differences) < .1 and max(load_balance) < 1e-4
        return rows, result
    finally:
        ops.wipe()


def numerical_checks(case, targets, steps_per_leg, baseline):
    # Pre-yield geometry-equivalent material must not acquire artificial plastic memory.
    small = case.length * case.parameters.yield_strain * min(.2, case.parameters.phi/3)
    elastic, _ = simulate(case, [0, -small, small, -small/2, 0], 10)
    fine, _ = simulate(case, targets, steps_per_leg*2)
    a = [r for r in baseline if r["is_target"]]
    b = [r for r in fine if r["is_target"]]
    stress_error = max(abs(x["stress_Pa"]-y["stress_Pa"]) for x, y in zip(a,b))
    work_error = max(abs(x["external_work_J"]-y["external_work_J"]) for x, y in zip(a,b))
    result = {"elastic_return_force_N": elastic[-1]["force_N"],
              "elastic_cycle_external_work_J": elastic[-1]["external_work_J"],
              "elastic_peak_stress_ratio": max(abs(r["stress_Pa"]) for r in elastic)/case.parameters.yield_stress,
              "refinement_steps_per_leg": [steps_per_leg, steps_per_leg*2],
              "max_turning_point_stress_difference_Pa": stress_error,
              "max_turning_point_work_difference_J": work_error}
    result["passed"] = (abs(result["elastic_return_force_N"]) < 1e-6
                         and abs(result["elastic_cycle_external_work_J"]) < 1e-6
                         and stress_error < .1 and work_error < 1e-5)
    return result


def summarize_case(case, rows, events):
    peaks = [event for event in events if event["event"] == "buckling"]
    # Include exact events: sampled steps can miss the sharp compression maximum.
    forces = [r["force_N"] for r in rows] + [e["stress"]*case.area for e in peaks]
    return {"case": case.to_dict(), "requested_steps": len(rows)-1,
            "completed_steps": len(rows)-1, "complete": True,
            "peak_tension_kN": max(forces)/1e3, "peak_compression_kN": min(forces)/1e3,
            "first_buckling_kN": peaks[0]["stress"]*case.area/1e3 if peaks else None,
            "subsequent_buckling_kN": peaks[1]["stress"]*case.area/1e3 if len(peaks)>1 else None,
            "buckling_count": rows[-1]["buckling_count"], "stages_visited": sorted({r["stage"] for r in rows}),
            "tail_extension_steps": sum(r["stage"] == "compression_tail_extension" for r in rows),
            "final_displacement_m": rows[-1]["displacement_m"], "final_force_kN": rows[-1]["force_N"]/1e3,
            "external_work_J": rows[-1]["external_work_J"],
            "external_work_note": "Integral N du, NOT automatically dissipated energy; final state is not initial state"}


def write_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sensitivity_curves(case, targets):
    variants = []
    for parameter, values in (("gamma", (.35,.65)), ("zeta", (.05,.2)), ("rho", (.005,.02))):
        for value in values:
            changed = replace(case, parameters=replace(case.parameters, **{parameter:value}))
            rows, events = simulate(changed, targets, 30)
            variants.append({"label": f"{parameter} = {value}", "parameter": parameter,
                             "value": value, "case": changed, "rows": rows, "events": events})
    return variants
