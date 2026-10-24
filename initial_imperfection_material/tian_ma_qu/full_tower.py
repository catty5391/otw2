"""Independent exploratory whole-tower TMQ runner. Never overwrites evidence.

Example: python -m initial_imperfection_material.tian_ma_qu.full_tower --output ...
All history times are quasi-static step indices, not seconds. No fiber damage.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import openseespy.opensees as ops

from model.tower_model_with_tian_ma_qu import OpenSeesModelWithTianMaQu
from initial_imperfection_material.full_tower_cyclic import _apply_gravity, _configure_static, _base_shear
from util.analysis.stepping import AdaptiveStepper
from util.analysis.equilibrium_checks import static_equilibrium
from util.processing.internal_force_recorder import TowerInternalForceRecorder
from util.processing.pushover_wind_load import PushoverWindLoadApplier

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS = (.0001, -.0001, 0, .001, -.001, 0, .003, -.003, 0, .006, -.006, 0, .01, -.01, 0)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(output, *, axial_mode="tmq", targets=DEFAULT_TARGETS, maximum_increment=.005,
        minimum_increment=.00002, timeout=900, control_node=350, control_dof=2,
        source=ROOT / "Source/Z30103A6.s2k", coefficient_case="p102_row_a", record_nodes=False,
        directional_config=None, wind_speed_targets=None, maximum_load_increment=.5,
        minimum_load_increment=.0001, drift_guard=.03):
    output, source = Path(output), Path(source)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing evidence: {output}")
    if not targets or any(not math.isfinite(t) for t in targets):
        raise ValueError("finite nonempty drift targets required")
    if not 0 < minimum_increment <= maximum_increment < math.inf:
        raise ValueError("invalid increments")
    if not math.isfinite(timeout) or timeout <= 0 or control_dof not in (1, 2):
        raise ValueError("positive timeout and lateral control DOF required")
    if wind_speed_targets is not None:
        if directional_config is None:
            raise ValueError("wind-speed loading requires dimensional directional_config")
        wind_speed_targets=tuple(float(v) for v in wind_speed_targets)
        if (not wind_speed_targets or any(not math.isfinite(v) or v<=0 for v in wind_speed_targets)
                or any(b<=a for a,b in zip(wind_speed_targets,wind_speed_targets[1:]))):
            raise ValueError("wind speed targets must be positive, finite and strictly increasing")
        if not 0 < minimum_load_increment <= maximum_load_increment < math.inf:
            raise ValueError("invalid load-factor increments")
        if not math.isfinite(drift_guard) or drift_guard <= 0:
            raise ValueError("positive finite displacement guard required")
    if directional_config is not None:
        from .directional_loading import validate_config
        from util.processing.directional_wind import wind_unit_vector
        directional_config = validate_config(directional_config)
        if abs(wind_unit_vector(directional_config["wind_angle_deg"])[control_dof-1]) < 1e-8:
            raise ValueError("control_dof is perpendicular to reference wind; select its dominant X/Y component")
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    summary = {"schema_version": 1, "analysis": "tmq_full_tower_exploratory", "axial_mode": axial_mode,
        "status": "running", "validated_for_tower": False, "control_node": control_node, "control_dof": control_dof,
        "targets_drift": list(targets), "completed_targets": 0, "accepted_steps": 0,
        "maximum_increment_m": maximum_increment, "minimum_increment_m": minimum_increment,
        "time_axis": "quasi_static_accepted_step_not_seconds", "coefficient_case": coefficient_case,
        "node_recording": bool(record_nodes), "node_displacement_reference": "absolute; step0 is gravity equilibrium",
        "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "engine_version": ops.version(), "assumptions": [
            "S2K E/fy/A/L; rho=0.03 (tower input); gamma=0.5 and zeta=0.1 assumed",
            "Perry first-fiber-yield phi, K=1 and e0/L=1/1000; not a calibrated ultimate buckling load",
            "Tube cyclic coefficients transferred to angle members WITHOUT experimental calibration",
            "One straight Corotational dispBeamColumn per member; no added initial bow",
            "TMQ axial force plus elastic uncoupled My/Mz/T; I23 omitted in beam stiffness",
            "No damage/fracture/deletion; equivalent member strain is NOT steel-fiber strain",
            "Not a comparison against the segmented fiber reference or a collapse certification"],
        "code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__), ROOT/"model/tower_model_with_tian_ma_qu.py", Path(__file__).with_name("material.py"),
             Path(__file__).with_name("section_adapter.py"), Path(__file__).with_name("opensees_adapter.py"))}}
    write_json(output / "summary.json", summary)
    if wind_speed_targets is not None:
        summary.update(loading_control="monotonic_wind_load_factor",targets_drift=None,
            targets_wind_speed_m_s=list(wind_speed_targets),
            equivalent_speed_definition="U=U_reference*sqrt(lambda), lambda>=0; same frozen shape, density and coefficients; NOT validated site/basic wind speed",
            reference_wind_speed_m_s=directional_config["wind_speed_m_s"],
            maximum_load_factor_increment=maximum_load_increment,minimum_load_factor_increment=minimum_load_increment,
            displacement_guard_ratio=drift_guard,
            displacement_guard_interpretation="computational safety guard, NOT calibrated collapse criterion",
            true_ultimate_wind_speed_established=False)
    if directional_config is not None:
        provenance_files=[ROOT/p for p in (
            "util/processing/directional_wind.py","util/processing/tower_directional_wind.py",
            "util/processing/conductor_directional_wind.py",
            "initial_imperfection_material/tian_ma_qu/directional_loading.py",
            "model/tower_line_system_model.py","model/conductor_properties.py",
            "model/.config/conductor_catalog.json","model/.config/tower_line_with_insulators.json")]
        summary["directional_input_sha256"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in provenance_files}
    history, recorder, stepper = [], None, None
    states_file = gzip.open(output / "member_states.csv.gz", "wt", encoding="utf-8", newline="")
    attempt_file = (output / "attempts.jsonl").open("w", encoding="utf-8")
    equilibrium_file = (output / "equilibrium.jsonl").open("w", encoding="utf-8")
    history_file = (output / "history.csv").open("w", encoding="utf-8", newline="")
    nodes_file = gzip.open(output / "node_states.csv.gz", "wt", encoding="utf-8", newline="") if record_nodes else None
    nodes_writer = csv.writer(nodes_file) if nodes_file is not None else None
    if nodes_writer is not None:
        nodes_writer.writerow(("step", "node_tag", "ux", "uy", "uz", "rx", "ry", "rz"))
    state_writer, history_writer = None, None
    line_history_file = None
    reaction_file = None
    try:
        ops.wipe()
        model = OpenSeesModelWithTianMaQu(source, output_dir=output / "model_data", axial_mode=axial_mode,
                                        coefficient_case=coefficient_case)
        model.model_tower()
        if control_node not in model.node_map:
            raise ValueError(f"Control node {control_node} missing")
        base = tuple(int(n) for n in model.fix_map)
        height = model.node_map[control_node]["z"] - min(model.node_map[n]["z"] for n in base)
        if height <= 0:
            raise ValueError("control height must be positive")
        summary.update(nodes=len(model.node_map), elements=len(model.element_map), control_height_m=height,
                       native_metadata=model.native_metadata)
        # Identical topology elastic control checks these initial frequencies.
        summary["initial_frequencies_Hz"] = [math.sqrt(v)/(2*math.pi) for v in ops.eigen(3)]
        print(f"BUILT {axial_mode}: {len(model.element_map)} members, H={height:g}m", flush=True)
        line_system = None
        if directional_config is not None:
            from .directional_loading import attach_explicit_lines, build_load_plan
            from util.processing.directional_wind import apply_nodal_wind_loads, wind_unit_vector
            summary["directional_wind"] = directional_config
            summary["frequency_scope"] = "bare tower before cables and gravity; NOT coupled modes"
            summary["controlled_drift_definition"] = "selected global DOF / height, NOT along-wind drift; along-wind response recorded separately"
            summary["negative_factor_interpretation"] = "mechanical reversal of the fixed load pattern, NOT a newly generated opposite wind field"
            if directional_config["mode"] == "tower_line_explicit":
                line_system, line_meta = attach_explicit_lines(model, output / "line_model", directional_config)
                summary["line_model"] = line_meta
                summary["total_system_nodes"] = len(model.node_map)
                summary["total_system_elements"] = len(ops.getEleTags())
                line_history_file = (output / "line_history.csv").open("w",encoding="utf-8",newline="")
                line_writer = csv.writer(line_history_file)
                line_writer.writerow(("step","line_id","element_tag","axial_force_N"))
            write_json(output / "wind_config.json", directional_config)
        gravity = _apply_gravity(model, steps=50 if line_system is not None else 10)
        gravity_u = float(ops.nodeDisp(control_node, control_dof))
        summary["gravity_control_displacement_m"] = gravity_u
        if directional_config is None:
            wind = PushoverWindLoadApplier(tag_manager=model.tag_manager, load_dof=control_dof).apply_from_model(model)
        else:
            gravity_xy = tuple(float(ops.nodeDisp(control_node,d)) for d in (1,2))
            gravity_rz = float(ops.nodeDisp(control_node,6))
            reaction_file=(output/"support_reactions.csv").open("w",encoding="utf-8",newline="")
            reaction_writer=csv.writer(reaction_file)
            reaction_writer.writerow(("step","node_tag","support_group","Rx_N","Ry_N","Rz_N","Mx_Nm","My_Nm","Mz_Nm"))
            wind_direction = wind_unit_vector(directional_config["wind_angle_deg"])
            nodal_loads, load_plan = build_load_plan(model, directional_config, line_system)
            write_json(output / "wind_load_plan.json", load_plan)
            wind = apply_nodal_wind_loads(nodal_loads,model.tag_manager,ops)
            summary["reference_wind_resultant"] = load_plan["combined_initial_coordinate_resultant"]
            summary["total_gravity_mass_kg"] = gravity.total_mass
            with (output / "wind_nodal_loads.csv").open("w",encoding="utf-8",newline="") as f:
                w=csv.writer(f)
                w.writerow(("node_tag","Fx_N","Fy_N","Fz_N","Mx_Nm","My_Nm","Mz_Nm"))
                w.writerows((n,*v) for n,v in sorted(nodal_loads.items()))
        constrained = {(int(n), d) for n, fix in model.fix_map.items()
                       for d, key in enumerate(("ux", "uy", "uz", "rx", "ry", "rz"), 1) if fix[key]}
        rotations = {(int(n), d) for n in model.node_map for d in (4, 5, 6)}
        recorder = TowerInternalForceRecorder(model, output / "internal_forces.sqlite", commit_every=10)

        def capture(step, stage):
            nonlocal state_writer, history_writer
            factor = float(ops.getLoadFactor(wind.pattern_tag))
            loads = {(int(n), d): float(v) for n, values in gravity.node_loads.items()
                     for d, v in enumerate(values, 1)}
            for n, values in wind.applied_loads.items():
                for d, v in enumerate(values, 1):
                    loads[int(n), d] = loads.get((int(n), d), 0.) + factor*float(v)
            scale = max(1., sum(abs(v) for (n,d),v in loads.items() if d <= 3))
            eq = static_equilibrium(ops, loads, constrained_dofs=constrained, rotational_dofs=rotations,
                force_scale=scale, moment_scale=scale*height, relative_tolerance=1e-6,
                force_absolute_tolerance=.001, moment_absolute_tolerance=.001)
            eq.pop("free_dof_residuals")
            equilibrium_file.write(json.dumps({"step": step, **eq}) + "\n")
            equilibrium_file.flush()
            states = model.committed_member_states()
            buckled = [s["element_tag"] for s in states if s["buckling_count"] > 0]
            yielded = [s["element_tag"] for s in states if s["tension_yield_ever"]]
            row = dict(step=step, stage=stage, displacement_m=float(ops.nodeDisp(control_node, control_dof)),
                       relative_displacement_m=float(ops.nodeDisp(control_node, control_dof))-gravity_u,
                       drift_ratio=(float(ops.nodeDisp(control_node, control_dof))-gravity_u)/height,
                       base_shear_N=_base_shear(base, control_dof), wind_load_factor=factor,
                       buckled_members=len(buckled), tensile_yield_members=len(yielded),
                       compression_tail_members=sum(s["stage"] == "compression_tail_extension" for s in states),
                       equilibrium_passed=eq["passed"], force_residual_N=eq["translation"]["maximum_absolute"],
                       moment_residual_Nm=eq["rotation"]["maximum_absolute"])
            if directional_config is not None:
                ux,uy=(float(ops.nodeDisp(control_node,d))-gravity_xy[d-1] for d in (1,2))
                vx,vy=(_base_shear(base,d) for d in (1,2))
                anchors=summary.get("line_model",{}).get("fixed_anchor_nodes",[])
                row.update(ux_m=ux,uy_m=uy,control_rz_rad=float(ops.nodeDisp(control_node,6))-gravity_rz,
                           base_shear_x_N=vx,base_shear_y_N=vy,
                           along_wind_displacement_m=ux*wind_direction[0]+uy*wind_direction[1],
                           along_wind_base_shear_N=vx*wind_direction[0]+vy*wind_direction[1],
                           remote_support_shear_x_N=_base_shear(anchors,1) if anchors else 0.,
                           remote_support_shear_y_N=_base_shear(anchors,2) if anchors else 0.)
                if wind_speed_targets is not None:
                    row["equivalent_wind_speed_m_s"]=directional_config["wind_speed_m_s"]*math.sqrt(factor) if factor>=0 else None
                    row["horizontal_drift_ratio"]=math.hypot(ux,uy)/height
                if line_system is not None:
                    for line_id,line in line_system.transmission_line_map.items():
                        for tag in line["element_tags"]:
                            force=ops.eleResponse(tag,"axialForce")
                            line_writer.writerow((step,line_id,tag,float(force[0])))
                    line_history_file.flush()
                for group,tags in (("tower_base",base),("remote_anchor",anchors)):
                    for tag in tags:
                        reaction_writer.writerow((step,tag,group,*ops.nodeReaction(tag)))
                reaction_file.flush()
            recorder.capture(step=step, time=float(step))
            if nodes_writer is not None:
                for node in sorted(model.node_map):
                    values = tuple(float(v) for v in ops.nodeDisp(node))
                    if len(values) != 6 or not all(math.isfinite(v) for v in values):
                        raise ValueError(f"Node {node}: expected six finite DOFs")
                    nodes_writer.writerow((step, node, *values))
            if history_writer is None:
                history_writer = csv.DictWriter(history_file, fieldnames=list(row))
                history_writer.writeheader()
            history_writer.writerow(row)
            history_file.flush()
            history.append(row)
            for s in states:
                state_row = {"step": step, **s}
                if state_writer is None:
                    state_writer = csv.DictWriter(states_file, fieldnames=list(state_row))
                    state_writer.writeheader()
                state_writer.writerow(state_row)
            if buckled and "first_buckling" not in summary:
                summary["first_buckling"] = {**row, "element_tags": buckled}
                if wind_speed_targets is not None:
                    summary["first_buckling_speed_bracket_m_s"]=[history[-2]["equivalent_wind_speed_m_s"] if len(history)>1 else 0.,row["equivalent_wind_speed_m_s"]]
            if yielded and "first_tension_yield" not in summary:
                summary["first_tension_yield"] = {**row, "element_tags": yielded}
            summary.update(accepted_steps=step, last_point=row,
                max_buckled_members=max(summary.get("max_buckled_members", 0), len(buckled)),
                max_tensile_yield_members=max(summary.get("max_tensile_yield_members", 0), len(yielded)))
            if step % 10 == 0:
                write_json(output / "summary.json", summary)
                print(f"STEP {step}: drift={row['drift_ratio']:.6g}, shear={row['base_shear_N']/1000:.3f}kN, buckled={len(buckled)}", flush=True)
            if not eq["passed"]:
                raise RuntimeError(f"Committed state {step} failed independent equilibrium; recorded, not rolled back")

        capture(0, "gravity_end")
        summary["gravity_equilibrium_passed"] = True
        _configure_static(maximum_increment, control_node, control_dof)

        def log_attempt(event):
            attempt_file.write(json.dumps(event, allow_nan=False) + "\n")
            attempt_file.flush()

        if wind_speed_targets is None:
            progress=lambda: float(ops.nodeDisp(control_node,control_dof))
            configure=lambda inc: ops.integrator("DisplacementControl",control_node,control_dof,inc)
            target_values=[gravity_u+ratio*height for ratio in targets]
            limit,minimum=maximum_increment,minimum_increment
        else:
            progress=lambda: float(ops.getLoadFactor(wind.pattern_tag))
            configure=lambda inc: ops.integrator("LoadControl",inc)
            target_values=[(speed/directional_config["wind_speed_m_s"])**2 for speed in wind_speed_targets]
            limit,minimum=maximum_load_increment,minimum_load_increment
        stepper = AdaptiveStepper(ops, progress=progress,
            configure_increment=configure,
            minimum_increment=minimum, convergence_test=("NormUnbalance", .01, 40, 0),
            on_attempt=log_attempt, timeout_seconds=timeout, maximum_total_attempts=3000,
            maximum_accepted_steps=1500, maximum_attempts_per_step=54 if wind_speed_targets is not None else 36, recovery_policy="gradual")
        summary["solver_settings"] = stepper.settings()
        step, increment, stopped = 0, limit, False
        for index, target in enumerate(target_values):
            label=targets[index] if wind_speed_targets is None else wind_speed_targets[index]
            while abs(target-progress()) > 1e-9:
                remaining = target-progress()
                result = stepper.step(math.copysign(min(abs(remaining), increment), remaining))
                if not result.converged:
                    summary.update(status="partial", stop_reason=result.stop_reason or "nonconvergence",
                                   failed_target_index=index)
                    if wind_speed_targets is None:
                        summary["failed_target_drift"]=label
                    else:
                        summary["failed_target_wind_speed_m_s"]=label
                    stopped = True
                    break
                step += 1
                capture(step, f"target_{index}_{label:+g}" if wind_speed_targets is None else f"wind_target_{label:g}_m_s")
                increment = min(limit, abs(result.accepted_increment)*1.5)
                if wind_speed_targets is not None and history[-1]["horizontal_drift_ratio"] >= drift_guard:
                    summary.update(status="partial",stop_reason="displacement_guard",failed_target_index=index,
                                   failed_target_wind_speed_m_s=label)
                    stopped=True
                    break
            if stopped:
                break
            summary["completed_targets"] += 1
            write_json(output / "summary.json", summary)
        if not stopped:
            summary.update(status="complete", stop_reason=None)
    except Exception as error:
        summary.update(status="error", stop_reason=f"{type(error).__name__}: {error}")
        print(summary["stop_reason"], flush=True)
    finally:
        if recorder is not None:
            recorder.close()
        for file in (states_file, history_file, attempt_file, equilibrium_file):
            file.close()
        if nodes_file is not None:
            nodes_file.close()
        if line_history_file is not None:
            line_history_file.close()
        if reaction_file is not None:
            reaction_file.close()
        if stepper is not None:
            summary["solver_diagnostics"] = stepper.diagnostics()
        summary["runtime_seconds"] = time.monotonic()-started
        if history:
            peak = max(history, key=lambda p: abs(p["base_shear_N"]))
            summary["maximum_absolute_shear_point"] = peak
            if wind_speed_targets is not None:
                summary["maximum_converged_equivalent_speed_point"]=max(history,key=lambda p:p["wind_load_factor"])
                summary["ceiling_reached_without_establishing_limit"]=summary["status"]=="complete"
        write_json(output / "summary.json", summary)
        ops.wipe()
    print(json.dumps({k: summary.get(k) for k in ("status", "completed_targets", "accepted_steps", "stop_reason", "runtime_seconds")}), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--axial-mode", choices=("tmq", "elastic"), default="tmq")
    parser.add_argument("--targets", type=float, nargs="+", default=DEFAULT_TARGETS)
    parser.add_argument("--maximum-increment", type=float, default=.005)
    parser.add_argument("--minimum-increment", type=float, default=.00002)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--record-nodes", action="store_true", help="Save all six nodal DOFs at every accepted step")
    parser.add_argument("--wind-config", type=Path, help="Explicit directional wind JSON; omitted preserves legacy single-DOF loading")
    parser.add_argument("--control-dof", type=int, choices=(1,2), default=2)
    parser.add_argument("--wind-speed-targets",type=float,nargs="+",help="Monotonic dimensional wind-speed targets; requires --wind-config")
    parser.add_argument("--maximum-load-increment",type=float,default=.5)
    parser.add_argument("--minimum-load-increment",type=float,default=.0001)
    parser.add_argument("--drift-guard",type=float,default=.03,help="Horizontal displacement/height computational guard, NOT collapse")
    args = parser.parse_args()
    result = run(args.output, axial_mode=args.axial_mode, targets=args.targets,
        maximum_increment=args.maximum_increment, minimum_increment=args.minimum_increment, timeout=args.timeout,
        record_nodes=args.record_nodes,control_dof=args.control_dof,
        directional_config=json.loads(args.wind_config.read_text()) if args.wind_config else None,
        wind_speed_targets=args.wind_speed_targets,maximum_load_increment=args.maximum_load_increment,
        minimum_load_increment=args.minimum_load_increment,drift_guard=args.drift_guard)
    raise SystemExit(0 if result["status"] == "complete" else 2)


if __name__ == "__main__":
    main()
