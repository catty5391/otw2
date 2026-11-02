"""Bounded, reproducible TMQ / four-segment tower-line static comparison.

Run every case in a fresh process. Cable drag is frozen on the SAME initial
parabola, unlike directional_loading.build_load_plan's gravity-frozen drag.
This deliberately compares model formulations, not isolated material laws.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "initial_imperfection_material/tian_ma_qu/followup_results/tower_line_wind_comparison_20261028"
ANGLES = (0., 30., 45., 90.)
SPEEDS = (20., 30., 40., 60., 80.)
MODELS = ("tmq", "segmented_reference")


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def report_html(markdown_text):
    """Render this module's controlled report without optional Markdown packages."""
    def inline(value):
        value=html.escape(value)
        value=re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    lines=markdown_text.splitlines()
    parts=[]
    i=0
    while i<len(lines):
        line=lines[i]
        if not line.strip(): i+=1; continue
        if line.startswith("```"):
            code=[]; i+=1
            while i<len(lines) and not lines[i].startswith("```"):
                code.append(lines[i]); i+=1
            parts.append("<pre><code>"+html.escape("\n".join(code))+"</code></pre>")
        elif line.startswith("|"):
            table=[]
            while i<len(lines) and lines[i].startswith("|"):
                table.append(lines[i]); i+=1
            head="".join("<th>"+inline(c.strip())+"</th>" for c in table[0].strip("|").split("|"))
            body="".join("<tr>"+"".join("<td>"+inline(c.strip())+"</td>" for c in row.strip("|").split("|"))+"</tr>" for row in table[2:])
            parts.append("<div class=table-wrap><table><thead><tr>"+head+"</tr></thead><tbody>"+body+"</tbody></table></div>")
            continue
        elif line.startswith("#"):
            count=len(line)-len(line.lstrip("#"))
            parts.append(f"<h{count}>"+inline(line[count:].strip())+f"</h{count}>")
        elif (match:=re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)",line)):
            parts.append('<figure><img loading="lazy" src="'+html.escape(match[2],quote=True)+'" alt="'+html.escape(match[1],quote=True)+'"></figure>')
        elif line.startswith("- ") or re.match(r"\d+\. ",line):
            ordered=not line.startswith("- ")
            tag="ol" if ordered else "ul"
            items=[]
            while i<len(lines) and (bool(re.match(r"\d+\. ",lines[i])) if ordered else lines[i].startswith("- ")):
                text=re.sub(r"^(?:\d+\. |- )", "",lines[i])
                items.append("<li>"+inline(text)+"</li>"); i+=1
            parts.append(f"<{tag}>"+"".join(items)+f"</{tag}>")
            continue
        else:
            parts.append("<p>"+inline(line.strip())+"</p>")
        i+=1
    return "\n".join(parts)


def publish_html(output):
    """Republish only the report page; leave FE evidence and figures untouched."""
    output=Path(output)
    body=report_html((output/"REPORT.md").read_text(encoding="utf-8"))
    style="""
html{box-sizing:border-box}*,*::before,*::after{box-sizing:inherit}
body{width:100%;max-width:1180px;min-width:0;margin:36px auto;padding:0 20px;
font:16px/1.7 system-ui;color:#213547;overflow-wrap:anywhere}
.table-wrap{width:100%;max-width:100%;min-width:0;overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;min-width:600px;font-size:14px}
td,th{border:1px solid #ccd5df;padding:7px;text-align:left}
img{display:block;width:100%;max-width:100%;height:auto}
pre{max-width:100%;white-space:pre-wrap;overflow-wrap:anywhere;overflow-x:auto;background:#f1f4f8;padding:16px}
code{overflow-wrap:anywhere;word-break:break-word}pre code{white-space:pre-wrap}
h1,h2,h3{color:#163956}a{color:#176baa}figure{margin:24px 0}
"""
    (output/"index.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>新旧塔线模型四风角对比</title><style>'+style+'</style><body>'+body+'</body></html>',encoding="utf-8")


def canonical_ledger(loads, nodes, identities):
    """Tag-independent audit: semantic node, initial position and six DOF load.

    Duplicate semantic names and unmapped loaded nodes fail closed. The stored
    numeric records (not only the hash) permit an independent tolerance audit.
    """
    if len(set(identities.values())) != len(identities):
        raise ValueError("semantic node identities must be unique")
    rows = []
    for tag, values in loads.items():
        if tag not in identities:
            raise ValueError(f"loaded node {tag} has no semantic identity")
        if len(values) != 6 or not all(math.isfinite(float(v)) for v in values):
            raise ValueError("six finite load components required")
        record = nodes[tag]
        xyz = [float(record[k]) for k in "xyz"]
        rows.append({"node": identities[tag], "xyz_m": [round(x, 12) for x in xyz],
                     "load": [round(float(v), 9) for v in values]})
    return sorted(rows, key=lambda row: row["node"])


def semantic_nodes(model, system, original_nodes):
    identities = {tag: f"tower:{model.node_global_to_local_tag.get(tag, tag)}" for tag in original_nodes}
    for name, record in system.insulator_map.items():
        identities[int(record["lower_node_tag"])] = f"insulator:{name}:lower"
    for name, record in system.transmission_line_map.items():
        for index, tag in enumerate(record["node_tags"][1:], 1):
            identities[int(tag)] = f"line:{name}:{index}"
    return identities


def common_initial_load_plan(model, system, config):
    from util.processing.tower_directional_wind import geometry_from_model, TowerWindCoefficients, build_tower_wind_load
    from util.processing.conductor_directional_wind import conductor_loads_from_model, combine_conductor_loads
    from util.processing.directional_wind import merge_nodal_loads, nodal_resultant
    geometry = geometry_from_model(model, area_basis=config["area_basis"], area_provenance=config["area_provenance"])
    tower = build_tower_wind_load(geometry, wind_angle_deg=config["wind_angle_deg"],
        reference_pressure_pa=.5*config["air_density"]*config["wind_speed_m_s"]**2,
        height_edges_m=config["height_edges_m"], height_factors=config["height_factors"],
        height_factor_provenance=config["height_factor_provenance"],
        coefficients=TowerWindCoefficients(config["tower_coefficient_x"], config["tower_coefficient_y"],
                                         config["yaw_gain"], config["coefficient_provenance"]))
    lines = [conductor_loads_from_model(system, name,
        wind_speed_m_s=config["wind_speed_m_s"], wind_angle_deg=config["wind_angle_deg"],
        drag_coefficient=config["conductor_drag_coefficient"], air_density=config["air_density"])
        for name in system.transmission_line_map]
    cable = combine_conductor_loads(*lines).nodal_forces
    loads = merge_nodal_loads(tower.applied_loads, cable)
    return loads, {"configuration": config,
        "geometry_for_drag": "common INITIAL parabola; NOT separately gravity-deformed geometry",
        "tower": asdict(tower), "conductors": [line.to_dict() for line in lines],
        "tower_resultant": nodal_resultant(model.node_map, tower.applied_loads),
        "conductor_resultant": nodal_resultant(model.node_map, cable),
        "combined_resultant": nodal_resultant(model.node_map, loads)}


def run_case(output, *, model_kind, angle_deg, speeds=SPEEDS, segments=40, timeout=1200.):
    import openseespy.opensees as ops
    from model.tower_model_with_tian_ma_qu import OpenSeesModelWithTianMaQu
    from model.tower_model_with_buckling import OpenSeesModelWithBuckling
    from model.insulator_mechanics import insulator_states
    from initial_imperfection_material.full_tower_cyclic import _apply_gravity
    from .directional_loading import verification_config, validate_config, attach_explicit_lines
    from util.processing.directional_wind import apply_nodal_wind_loads, nodal_resultant, wind_unit_vector
    from util.analysis.stepping import AdaptiveStepper
    from util.analysis.equilibrium_checks import static_equilibrium

    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite evidence: {output}")
    if model_kind not in MODELS or not all(math.isfinite(float(u)) and u > 0 for u in speeds):
        raise ValueError("known model and positive finite speeds required")
    if any(b <= a for a, b in zip(speeds, speeds[1:])):
        raise ValueError("strictly increasing speed targets required")
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source = ROOT / "Source/Z30103A6.s2k"
    summary = {"schema": "otw2.tower_line_wind_comparison.v1", "model_kind": model_kind,
        "angle_deg": float(angle_deg), "targets_m_s": list(speeds), "status": "building",
        "completed_targets_m_s": [], "control_node": 350, "segments_per_span": segments,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "engine_version": ops.version(), "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "steel_b": .03, "imperfection_ratio": .001, "reference_divisions": 4,
        "reference_seed": 30103, "coefficient_case": "p102_row_a",
        "reference_integration_points": 6, "tmq_integration_points": 3,
        "validated_for_design": False, "true_ultimate_wind_speed_established": False,
        "comparison_scope": "model formulations: axial TMQ+elastic uncoupled bending vs bowed Steel02 fiber beam",
        "time_axis": "quasi-static accepted step; not seconds",
        "incremental_response_reference": "each model's separately equilibrated gravity state",
        "load_geometry": "shared initial geometry; not gravity-deformed cable geometry",
        "code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            ROOT/"model/tower_model_with_tian_ma_qu.py", ROOT/"model/tower_model_with_buckling.py",
            ROOT/"model/tower_line_system_model.py", Path(__file__).with_name("directional_loading.py"))}}
    history, targets, snapshots, stepper = [], [], [], None
    write_json(output/"summary.json", summary)
    attempt_file = (output/"attempts.jsonl").open("w", encoding="utf-8")
    equilibrium_file = (output/"equilibrium.jsonl").open("w", encoding="utf-8")
    snapshot_file = (output/"states.jsonl").open("w", encoding="utf-8")
    history_file = (output/"history.csv").open("w", encoding="utf-8", newline="")
    writer = None
    try:
        ops.wipe()
        if model_kind == "tmq":
            model = OpenSeesModelWithTianMaQu(source, output_dir=output/"model_data", imperfection_ratio=.001)
        else:
            model = OpenSeesModelWithBuckling(source, output_dir=output/"model_data",
                random_disp_ratio=.001, member_divisions=4, imperfection_seed=30103)
        model.model_tower()
        original_nodes = set(model._parse_node_coordinates())
        base = [int(n) for n, row in model.fix_map.items() if row["ux"] and row["uy"] and row["uz"]]
        tower_mass = {int(n): [float(row[k]) for k in ("mx", "my", "mz")] for n, row in model.mass_map.items()}
        if set(tower_mass)-original_nodes:
            raise ValueError("unexpected non-original tower mass nodes")
        summary.update(tower_physical_nodes=len(original_nodes), tower_fe_nodes=len(model.node_map),
            tower_physical_members=len(model._parse_element_connectivity()), tower_fe_elements=len(model.element_map),
            tower_mass_kg=sum(row[2] for row in tower_mass.values()),
            original_tower_mass_sha256=digest(tower_mass), tower_base_nodes=base)
        c = verification_config(angle_deg, mode="tower_line_explicit", line_segments=segments)
        c.update(insulator_axial_behavior="elastic", insulator_compression_stiffness_ratio=1.)
        config = validate_config(c)
        system, metadata = attach_explicit_lines(model, output/"line_model", config)
        summary["line_model"] = metadata
        summary["line_parameters"] = {name: {key: rec[key] for key in (
            "span", "n_seg", "initial_sag", "mass_per_length", "total_conductor_mass", "material", "conductor")}
            for name, rec in system.transmission_line_map.items()}
        identities = semantic_nodes(model, system, original_nodes)
        nodal_loads, plan = common_initial_load_plan(model, system, config)
        ledger = canonical_ledger(nodal_loads, model.node_map, identities)
        write_json(output/"semantic_wind_loads.json", ledger)
        write_json(output/"wind_load_plan.json", plan)
        summary["semantic_wind_load_sha256"] = digest(ledger)
        summary["reference_wind_resultant"] = plan["combined_resultant"]
        summary["reference_tower_resultant"] = plan["tower_resultant"]
        summary["reference_conductor_resultant"] = plan["conductor_resultant"]
        summary["status"] = "gravity"
        write_json(output/"summary.json", summary)
        gravity = _apply_gravity(model, steps=50)
        summary["total_gravity_mass_kg"] = gravity.total_mass
        gravity_ledger = canonical_ledger(gravity.node_loads, model.node_map, identities)
        write_json(output/"semantic_gravity_loads.json", gravity_ledger)
        summary["semantic_gravity_load_sha256"] = digest(gravity_ledger)
        wind = apply_nodal_wind_loads(nodal_loads, model.tag_manager, ops)
        direction = wind_unit_vector(angle_deg)
        anchors = metadata["fixed_anchor_nodes"]
        constrained = {(int(n), d) for n, row in model.fix_map.items()
            for d, key in enumerate(("ux", "uy", "uz", "rx", "ry", "rz"), 1) if row[key]}
        rotations = {(int(n), d) for n in model.node_map for d in (4, 5, 6)}
        gravity_u = list(ops.nodeDisp(350))
        gravity_hang = {name: list(ops.nodeDisp(row["lower_node_tag"])) for name, row in system.insulator_map.items()}
        ops.reactions()
        gravity_base = [-sum(ops.nodeReaction(n, d) for n in base) for d in (1, 2, 3)]
        gravity_anchor = [-sum(ops.nodeReaction(n, d) for n in anchors) for d in (1, 2, 3)]
        summary["gravity_control_displacement_m"] = gravity_u[:3]
        summary["gravity_hanger_displacements_m"] = {name: u[:3] for name, u in gravity_hang.items()}

        def capture(step):
            nonlocal writer
            factor = float(ops.getLoadFactor(wind.pattern_tag))
            ledger_dof = {(int(n), d): float(v) for n, values in gravity.node_loads.items() for d, v in enumerate(values, 1)}
            for n, values in wind.applied_loads.items():
                for d, v in enumerate(values, 1):
                    ledger_dof[int(n), d] = ledger_dof.get((int(n), d), 0.) + factor*float(v)
            scale = max(1., sum(abs(v) for (n, d), v in ledger_dof.items() if d <= 3))
            eq = static_equilibrium(ops, ledger_dof, constrained_dofs=constrained, rotational_dofs=rotations,
                force_scale=scale, moment_scale=scale*36.4, relative_tolerance=1e-6,
                force_absolute_tolerance=.001, moment_absolute_tolerance=.001)
            eq.pop("free_dof_residuals")
            equilibrium_file.write(json.dumps({"step": step, **eq}, allow_nan=False)+"\n")
            equilibrium_file.flush()
            ops.reactions()
            u = list(ops.nodeDisp(350))
            du = [a-b for a, b in zip(u, gravity_u)]
            shear = [-sum(ops.nodeReaction(n, d) for n in base)-gravity_base[d-1] for d in (1, 2, 3)]
            anchor = [-sum(ops.nodeReaction(n, d) for n in anchors)-gravity_anchor[d-1] for d in (1, 2, 3)]
            strings = insulator_states(system)
            hangs = {name: [float(x)-g for x, g in zip(ops.nodeDisp(row["lower_node_tag"]), gravity_hang[name])][:3]
                     for name, row in system.insulator_map.items()}
            line_rows = []
            for name, line in system.transmission_line_map.items():
                forces = [float(ops.eleResponse(t, "axialForce")[0]) for t in line["element_tags"]]
                rated = line["conductor"].get("rated_tensile_strength_n")
                line_rows.append({"line_id": name, "min_N": min(forces), "max_N": max(forces),
                    "hanger_end_N": forces[0], "anchor_end_N": forces[-1],
                    "rated_tensile_strength_N": rated,
                    "max_rated_ratio": max(forces)/rated if rated else None,
                    "ordered_segment_forces_N": forces})
            coords = {n: [x+d for x, d in zip(ops.nodeCoord(n), ops.nodeDisp(n)[:3])] for n in model.node_map}
            all_loads = {n: [ledger_dof.get((n, d), 0.) for d in range(1, 7)] for n in model.node_map}
            applied_resultant = nodal_resultant(coords, all_loads)
            reaction_resultant = nodal_resultant(coords, {n: list(ops.nodeReaction(n)) for n in model.fix_map})
            force_balance = [a+b for a, b in zip(applied_resultant["force_N"], reaction_resultant["force_N"])]
            moment_balance = [a+b for a, b in zip(applied_resultant["moment_Nm"], reaction_resultant["moment_Nm"])]
            # Independent global balances also include geometric moment arms at this state.
            global_ok = max(map(abs, force_balance)) <= .01+scale*1e-6 and max(map(abs, moment_balance)) <= .01+scale*36.4*1e-6
            tmq_states = model.committed_member_states() if model_kind == "tmq" else []
            row = {"step": step, "wind_speed_m_s": 20.*math.sqrt(max(0., factor)), "load_factor": factor,
                "ux_m": du[0], "uy_m": du[1], "uz_m": du[2],
                "along_wind_displacement_m": sum(du[i]*direction[i] for i in range(3)),
                "horizontal_drift": math.hypot(*du[:2])/36.4,
                "tower_base_x_N": shear[0], "tower_base_y_N": shear[1],
                "tower_base_along_N": sum(shear[i]*direction[i] for i in range(3)),
                "anchor_x_N": anchor[0], "anchor_y_N": anchor[1],
                "hanger_max_horizontal_displacement_m": max(math.hypot(*v[:2]) for v in hangs.values()),
                "line_min_force_N": min(v["min_N"] for v in line_rows),
                "line_max_force_N": max(v["max_N"] for v in line_rows),
                "line_max_rated_ratio": max((v["max_rated_ratio"] for v in line_rows if v["max_rated_ratio"] is not None), default=0.),
                "insulator_min_force_N": min(v["axial_force_N"] for v in strings),
                "insulator_compression_legs": sum(v["axial_force_N"] < -1. for v in strings),
                "insulator_force_reconstruction_max_error_N": max(abs(v["force_reconstruction_residual_N"]) for v in strings),
                "tmq_buckled_members": sum(s["buckling_count"] > 0 for s in tmq_states) if tmq_states else None,
                "tmq_tensile_yield_members": sum(s["tension_yield_ever"] for s in tmq_states) if tmq_states else None,
                "equilibrium_passed": eq["passed"], "global_balance_passed": global_ok,
                "force_residual_N": eq["translation"]["maximum_absolute"],
                "moment_residual_Nm": eq["rotation"]["maximum_absolute"],
                "global_force_balance_max_N": max(map(abs, force_balance)),
                "global_moment_balance_max_Nm": max(map(abs, moment_balance))}
            # This flag only checks the declared axial assumptions, not design adequacy.
            row["axial_assumption_guard_passed"] = row["insulator_compression_legs"] == 0 and row["line_min_force_N"] > 0 and row["line_max_rated_ratio"] <= 1
            snapshot = {**row, "hangers_incremental_displacement_m": hangs, "strings": strings, "lines": line_rows,
                "global_force_balance_N": force_balance, "global_moment_balance_Nm": moment_balance,
                "support_reactions": {"tower_base": {str(n): list(ops.nodeReaction(n)) for n in base},
                                      "remote_anchor": {str(n): list(ops.nodeReaction(n)) for n in anchors}}}
            if writer is None:
                writer = csv.DictWriter(history_file, fieldnames=list(row))
                writer.writeheader()
            writer.writerow(row)
            history_file.flush()
            snapshot_file.write(json.dumps(snapshot, allow_nan=False)+"\n")
            snapshot_file.flush()
            history.append(row)
            snapshots.append(snapshot)
            summary.update(accepted_steps=step, last_point=row)
            if not row["axial_assumption_guard_passed"] and "first_axial_assumption_guard_failure" not in summary:
                summary["first_axial_assumption_guard_failure"] = row
            if not eq["passed"] or not global_ok:
                raise RuntimeError(f"Committed step {step} failed independent equilibrium; not retried")

        capture(0)
        summary["gravity_equilibrium_passed"] = True
        summary["status"] = "wind"
        ops.wipeAnalysis()
        ops.constraints("Transformation")
        ops.numberer("RCM")
        ops.system("UmfPack")
        ops.test("NormUnbalance", .005, 80, 0)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", .5)
        ops.analysis("Static")

        def log_attempt(event):
            attempt_file.write(json.dumps(event, allow_nan=False)+"\n")
            attempt_file.flush()

        stepper = AdaptiveStepper(ops, progress=lambda: float(ops.getLoadFactor(wind.pattern_tag)),
            configure_increment=lambda inc: ops.integrator("LoadControl", inc), minimum_increment=.0001,
            convergence_test=("NormUnbalance", .005, 80, 0), on_attempt=log_attempt,
            timeout_seconds=timeout, maximum_total_attempts=400, maximum_accepted_steps=160,
            maximum_attempts_per_step=30, recovery_policy="gradual")
        summary["solver_settings"] = stepper.settings()
        increment, stop = .5, False
        for speed in speeds:
            target = (speed/20.)**2
            while target-float(ops.getLoadFactor(wind.pattern_tag)) > 1e-9:
                result = stepper.step(min(increment, target-float(ops.getLoadFactor(wind.pattern_tag))))
                if not result.converged:
                    summary.update(status="partial", stop_reason=result.stop_reason or "nonconvergence",
                                   failed_target_m_s=speed)
                    stop = True
                    break
                capture(len(history))
                increment = min(.5, abs(result.accepted_increment)*1.5)
                if history[-1]["horizontal_drift"] > .03:
                    summary.update(status="partial", stop_reason="3_percent_computational_drift_guard",
                                   failed_target_m_s=speed)
                    stop = True
                    break
            if stop:
                break
            targets.append(snapshots[-1])
            summary["completed_targets_m_s"].append(speed)
            write_json(output/"targets.json", targets)
            write_json(output/"summary.json", summary)
            print(f"{model_kind} {angle_deg:g}deg: target {speed:g}m/s; ux={history[-1]['ux_m']:.6g}, uy={history[-1]['uy_m']:.6g}, Vmin={history[-1]['insulator_min_force_N']:.3f}N", flush=True)
        if not stop:
            summary.update(status="complete", stop_reason=None)
    except Exception as error:
        summary.update(status="error", stop_reason=f"{type(error).__name__}: {error}")
        import traceback
        traceback.print_exc()
    finally:
        for handle in (attempt_file, equilibrium_file, snapshot_file, history_file):
            handle.close()
        if stepper is not None:
            summary["solver_diagnostics"] = stepper.diagnostics()
        summary["runtime_seconds"] = time.monotonic()-started
        if history:
            summary.update(max_local_force_residual_N=max(row["force_residual_N"] for row in history),
                max_global_force_balance_N=max(row["global_force_balance_max_N"] for row in history),
                max_global_moment_balance_Nm=max(row["global_moment_balance_max_Nm"] for row in history),
                all_saved_states_equilibrated=all(row["equilibrium_passed"] and row["global_balance_passed"] for row in history),
                all_saved_states_axial_guard_passed=all(row["axial_assumption_guard_passed"] for row in history))
        write_json(output/"targets.json", targets)
        write_json(output/"summary.json", summary)
        ops.wipe()
    print(json.dumps({k: summary.get(k) for k in ("model_kind", "angle_deg", "status", "completed_targets_m_s", "runtime_seconds", "stop_reason")}), flush=True)
    return summary


def common_target_rows(reference, candidate):
    """Compare only achieved, independently balanced target states; never extrapolate."""
    def states(rows):
        return {round(float(row["wind_speed_m_s"]), 7): row for row in rows
                if row.get("equilibrium_passed") is True and row.get("global_balance_passed") is True}
    a, b = states(reference), states(candidate)
    return [(speed, a[speed], b[speed]) for speed in sorted(a.keys() & b.keys())]


def finalize_interrupted_case(directory):
    """Recover the last flushed accepted state after a supervisor budget stop.

    The previous manifest is retained; raw states, attempts and history never
    change. This recovers evidence already written, not an FE restart/rollback.
    """
    directory=Path(directory)
    path=directory/"summary.json"
    s=json.loads(path.read_text())
    if s.get("status")!="hard_timeout" or s.get("accepted_state_recovery"):
        return s
    states=[]
    for line in (directory/"states.jsonl").read_text().splitlines():
        try: states.append(json.loads(line))
        except json.JSONDecodeError: break  # A killed writer may leave one incomplete trailing record.
    if not states: return s
    backup=directory/"summary_at_supervisor_stop.json"
    if not backup.exists(): write_json(backup,s)
    with (directory/"history.csv").open() as f:
        keys=next(csv.reader(f))
    last={key:states[-1][key] for key in keys}
    budget=s.get("outer_wall_budget_seconds",2400 if "2400" in s.get("stop_reason","") else None)
    s.update(last_point=last, accepted_steps=last["step"],
        accepted_state_recovery="reconstructed from complete flushed states.jsonl records; no FE rerun",
        all_saved_states_equilibrated=all(row["equilibrium_passed"] and row["global_balance_passed"] for row in states),
        all_saved_states_axial_guard_passed=all(row["axial_assumption_guard_passed"] for row in states),
        max_local_force_residual_N=max(row["force_residual_N"] for row in states),
        max_global_force_balance_N=max(row["global_force_balance_max_N"] for row in states),
        max_global_moment_balance_Nm=max(row["global_moment_balance_max_Nm"] for row in states),
        runtime_seconds=None, outer_wall_budget_seconds=budget,
        stop_reason=f"outer_wall_budget_stop ({budget if budget is not None else 'unrecorded'} s); NOT a solver nonconvergence finding")
    failed=next((row for row in states if not row["axial_assumption_guard_passed"]),None)
    if failed: s["first_axial_assumption_guard_failure"]={key:failed[key] for key in keys}
    write_json(path,s)
    return s


def make_report(output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output = Path(output)
    summaries, target_maps, cases = {}, {}, []
    for path in sorted(output.glob("*_deg_*/summary.json")):
        s = finalize_interrupted_case(path.parent)
        key = (s["angle_deg"], s["model_kind"])
        summaries[key] = s
        targets = path.parent/"targets.json"
        target_maps[key] = json.loads(targets.read_text()) if targets.exists() else []
        cases.append({"directory": path.parent.name, **s})
    audits, comparisons = [], []
    measures = ("along_wind_displacement_m", "ux_m", "uy_m", "tower_base_along_N", "tower_base_x_N", "tower_base_y_N",
                "anchor_x_N", "anchor_y_N", "hanger_max_horizontal_displacement_m", "line_max_force_N", "insulator_min_force_N")
    for angle in ANGLES:
        if (angle, "tmq") not in summaries or (angle, "segmented_reference") not in summaries:
            continue
        t, r = summaries[angle, "tmq"], summaries[angle, "segmented_reference"]
        checks = {name: t.get(name) is not None and t.get(name) == r.get(name) for name in (
            "source_sha256", "original_tower_mass_sha256", "semantic_wind_load_sha256", "semantic_gravity_load_sha256")}
        audits.append({"angle_deg": angle, "checks": checks, "passed": all(checks.values()),
            "tower_mass_difference_kg": t.get("tower_mass_kg", 0)-r.get("tower_mass_kg", 0),
            "total_gravity_mass_difference_kg": t.get("total_gravity_mass_kg", 0)-r.get("total_gravity_mass_kg", 0)})
        for speed, ref, new in common_target_rows(target_maps[angle, "segmented_reference"], target_maps[angle, "tmq"]):
            for key in measures:
                old, value = ref[key], new[key]
                comparisons.append({"angle_deg": angle, "wind_speed_m_s": speed, "metric": key,
                    "reference": old, "tmq": value, "difference": value-old,
                    "relative_difference_percent": 100*(value-old)/abs(old) if abs(old)>1e-8 else None,
                    "both_axial_assumption_guards_passed": ref["axial_assumption_guard_passed"] and new["axial_assumption_guard_passed"],
                    "identical_input_audit_passed": all(checks.values())})
    state_events=[]
    for angle in ANGLES:
        path=output/f"tmq_deg_{angle:g}/history.csv"
        if not path.exists(): continue
        with path.open() as f: rows=list(csv.DictReader(f))
        first=next((i for i,row in enumerate(rows) if int(row["tmq_buckled_members"])>0),None)
        entry={"angle_deg":angle,
            "max_tmq_buckled_members":max((int(row["tmq_buckled_members"]) for row in rows),default=0),
            "max_tmq_tensile_yield_members":max((int(row["tmq_tensile_yield_members"]) for row in rows),default=0),
            "first_buckling_saved_speed_m_s":None,
            "interpretation":"local constitutive branch activation; not experimentally verified physical member buckling"}
        if first is not None:
            row=rows[first]
            entry.update(first_buckling_saved_speed_m_s=float(row["wind_speed_m_s"]),
                previous_saved_speed_m_s=float(rows[first-1]["wind_speed_m_s"]) if first else 0.,
                v_min_force_at_first_saved_buckling_N=float(row["insulator_min_force_N"]),
                axial_assumption_guard_passed_at_first_saved_buckling=row["axial_assumption_guard_passed"]=="True")
        state_events.append(entry)
    write_json(output/"tmq_state_events.json",state_events)
    write_json(output/"input_audit.json", audits)
    write_json(output/"comparison.json", comparisons)
    write_json(output/"summary.json", {"schema": "otw2.tower_line_wind_comparison_summary.v1", "cases": cases,
        "angles_deg": list(ANGLES), "targets_m_s": list(SPEEDS), "input_audits": audits,
        "all_identical_input_audits_passed": len(audits)==len(ANGLES) and all(a["passed"] for a in audits),
        "comparison_rows": len(comparisons), "tmq_state_events":state_events,"validated_for_design": False})
    if comparisons:
        with (output/"comparison.csv").open("w", newline="", encoding="utf-8") as f:
            w=csv.DictWriter(f, fieldnames=list(comparisons[0])); w.writeheader(); w.writerows(comparisons)
    # Connected lines display accepted equilibrium states, not artificial target extrapolation.
    plots = [("control_displacement.png", "along_wind_displacement_m", 1000., "Control 350 displacement along wind [mm]"),
             ("tower_base_shear.png", "tower_base_along_N", .001, "Tower base shear increment along wind [kN]"),
             ("hanger_displacement.png", "hanger_max_horizontal_displacement_m", 1000., "Maximum V lower-node horizontal displacement [mm]"),
             ("cable_tension.png", "line_max_force_N", .001, "Maximum cable axial force [kN]"),
             ("v_string_force.png", "insulator_min_force_N", .001, "Minimum V-leg axial force [kN]; tension positive")]
    for filename, metric, scale, ylabel in plots:
        fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
        for axis, angle in zip(axes.flat, ANGLES):
            for kind, color in (("tmq", "#b84634"), ("segmented_reference", "#1b6996")):
                directory=output/f"{kind}_deg_{angle:g}"
                path=directory/"history.csv"
                if not path.exists(): continue
                with path.open() as f: rows=list(csv.DictReader(f))
                rows=[r for r in rows if r["equilibrium_passed"]=="True" and r["global_balance_passed"]=="True"]
                axis.plot([float(r["wind_speed_m_s"]) for r in rows], [float(r[metric])*scale for r in rows],
                          color=color, label="TMQ" if kind=="tmq" else "Steel02 / 4 segments", marker=".", markersize=3)
                invalid=[r for r in rows if r["axial_assumption_guard_passed"]!="True"]
                if invalid:
                    axis.scatter([float(r["wind_speed_m_s"]) for r in invalid], [float(r[metric])*scale for r in invalid],
                                 facecolors="none", edgecolors=color, s=35)
            axis.set_title(f"Wind angle {angle:g} deg")
            axis.grid(alpha=.25); axis.set_xlabel("Static equivalent wind speed [m/s]")
            axis.set_ylabel(ylabel, fontsize=9); axis.legend(fontsize=8)
            if metric=="insulator_min_force_N": axis.axhline(0, color="black", lw=.7)
        fig.suptitle("Tower + four 300 m spans | common frozen initial wind geometry\nOpen circles: V/cable assumption guard exceeded", fontsize=11)
        fig.tight_layout(); fig.savefig(output/filename, dpi=170); plt.close(fig)
    fig, axes=plt.subplots(2,2,figsize=(11,7))
    for axis,angle in zip(axes.flat,ANGLES):
        for kind,color in (("tmq","#b84634"),("segmented_reference","#1b6996")):
            path=output/f"{kind}_deg_{angle:g}/history.csv"
            if not path.exists(): continue
            with path.open() as f: rows=list(csv.DictReader(f))
            rows=[r for r in rows if r["equilibrium_passed"]=="True" and r["global_balance_passed"]=="True"]
            axis.plot([1000*float(r["along_wind_displacement_m"]) for r in rows],
                      [.001*float(r["tower_base_along_N"]) for r in rows], color=color,
                      label="TMQ" if kind=="tmq" else "Steel02 / 4 segments")
            invalid=[r for r in rows if r["axial_assumption_guard_passed"]!="True"]
            axis.scatter([1000*float(r["along_wind_displacement_m"]) for r in invalid],
                         [.001*float(r["tower_base_along_N"]) for r in invalid],facecolors="none",edgecolors=color,s=28)
        axis.set_title(f"Wind angle {angle:g} deg")
        axis.set_xlabel("Control 350 displacement along wind [mm]")
        axis.set_ylabel("Tower base shear increment along wind [kN]")
        axis.grid(alpha=.25); axis.legend(fontsize=8)
    fig.suptitle("Static force-displacement comparison | open circles: V/cable assumption guard exceeded")
    fig.tight_layout(); fig.savefig(output/"pushover_curve.png",dpi=170); plt.close(fig)
    lines=["# 新旧模型塔线静态风对比（2026-10-28）", "",
        "对比当前 TMQ 轴向等效塔与四分段 Steel02 纤维梁塔，并连接相同四跨导线及两组 V 串。四个风攻角为 0°、30°、45°、90°，共同目标为 20、30、40、60、80 m/s。结果仅为未标定均匀静态风下的模型形式对比，不是极限风速、脉动风时程或工程设计验证。", "",
        "## 实施步骤", "",
        "1. 每组合使用独立进程重建 Z30103A6；S2K 原始节点质量、E、fy、截面和 b=0.03 一致。四分段塔采用 L/1000 半正弦缺陷、随机方向种子 30103；TMQ 使用现行 p102_row_a 与 Perry 首屈服估计，不另施加杆内弯曲。",
        "2. 两组 V 串均使用历史弹性轴向假设，四跨各 300 m、每跨 40 段，初始垂度 8 m、初拉力 20 kN；保持同一导线质量/EA/名义抗拉强度，删除组件独立重力后施加一次总质量重力。",
        "3. 用原 S2K 物理杆投影面积产生塔风。导线法向阻力冻结在两模型完全相同的初始抛物线上；**不同于历史 directional_loading 在各模型重力后形状上冻结风力**。该选择用于严格相同外荷载比较，不是追随力或气动弹性分析。",
        "4. 每模型分 50 步建立自己的重力平衡初态，输出语义节点重力/风荷载清单及 SHA256；两种模型的节点标签可不同，按原塔节点与线跨/序号对齐。质量只统计原节点与实际线/串质量，不重复统计分段节点。",
        "5. 风荷载因子 λ=(U/20)²，最大增量 0.5，最小 0.0001，采用统一 NormUnbalance 0.005 N、80 次迭代收敛检查和渐进自适应。每个接受状态另组装全局单元端力检查自由 DOF 平衡，并核查所有支座与当前坐标下外力合力/合矩。失败时停止并保留最后实际接受状态，绝不插值外推到目标。",
        "6. 相对各自重力初态报告塔控点 350、挂点位移与塔脚/远端剪力；索力和 V 肢力为总力。同步核查 V 肢压力、索力符号和名义抗拉强度。空心点标记假设超界结果，只作数值敏感性，不能视为物理有效承载能力。", "",
        "风向定义为气流**流向**（flow TOWARDS）：0° 沿 +X 横向，90° 沿 +Y 导线走向。参考静态动压 `q=ρU²/2`；塔的分段力使用 `q G [1+0.2 sin²(2θ)] [Cx Ax cos²θ+Cy Ay sin²θ]` 并沿水平风向分解。导线逐初始弦段使用法向速度 `v_perp=v−(v·t)t`，单位长度阻力为 `0.5 ρ Cd D |v_perp| v_perp`，所以改变风攻角并非简单旋转一套固定大小的塔线荷载。初始垂度使 90° 工况的局部导线法向阻力未必严格为零。", "",
        "## 运行结果", "", "|模型|攻角|完成目标 m/s|状态|用时 s|最后平衡速度 m/s|", "|---|---:|---|---|---:|---:|"]
    for case in cases:
        last=case.get("last_point", {})
        elapsed=f"{case['runtime_seconds']:.1f}" if case.get('runtime_seconds') is not None else (f"外层预算 {case['outer_wall_budget_seconds']:g}" if case.get('outer_wall_budget_seconds') else "运行中")
        lines.append(f"|{case['model_kind']}|{case['angle_deg']:g}|{', '.join(f'{u:g}' for u in case['completed_targets_m_s']) or '无'}|{case['status']}|{elapsed}|{last.get('wind_speed_m_s',0):.3f}|")
    lines.extend(["", "### 相同输入检查", "", "|攻角|原始质量/源/逐节点风与重力相同|总质量差 kg|", "|---|---|---:|"])
    for a in audits: lines.append(f"|{a['angle_deg']:g}°|{'全部通过' if a['passed'] else '未全部通过，见 input_audit.json'}|{a['total_gravity_mass_difference_kg']:.6g}|")
    lines.extend(["", "### 参考 20 m/s 的风合力与合矩", "", "下表是共同初始坐标、塔底原点下的施加荷载合量；其他风速按 `(U/20)²` 缩放。单位 kN / kN·m。塔与线的分项和逐节点荷载在每工况 wind_load_plan.json 内。", "",
        "|攻角|总 Fx|总 Fy|总 Fz|总 Mx|总 My|总 Mz|", "|---|---:|---:|---:|---:|---:|---:|"])
    for angle in ANGLES:
        source_summary=summaries.get((angle,"tmq"),{})
        res=source_summary.get("reference_wind_resultant")
        if res:
            lines.append(f"|{angle:g}°|"+"|".join(f"{v/1000:.4f}" for v in res['force_N']+res['moment_Nm'])+"|")
    lines.extend(["", "### 40 m/s 的塔控点沿风位移", "", "这是共同完成且 V 未受压的数值基准；实际串型、几何和材料仍未验证，不能称物理已验证区间。差值百分数以四分段模型为分母。接近零的响应同时提供绝对值，不能仅看百分比。", "", "|攻角|四分段 mm|TMQ mm|相对差 %|V/索假设检查|", "|---|---:|---:|---:|---|"])
    for row in comparisons:
        if row["metric"]=="along_wind_displacement_m" and abs(row["wind_speed_m_s"]-40)<1e-6:
            rel=row['relative_difference_percent']
            lines.append(f"|{row['angle_deg']:g}°|{row['reference']*1000:.3f}|{row['tmq']*1000:.3f}|{rel:.2f}|{'通过' if row['both_axial_assumption_guards_passed'] else '超界'}|")
    lines.extend(["", "### 整体近似直线，局部本构已激活", "",
        "共同 40 m/s 目标点，四角 TMQ 均为 0 根进入压屈分支、0 根拉伸屈服；新旧模型沿风位移差约 0.4%。扩展加载中，45° 和 90° 已出现少数 TMQ 杆件进入压屈分支，所以不能根据整体剪力–位移曲线近似直线，就认为所有杆件始终弹性。这里记录的是当前等效本构的内部状态，不等于已验证真实角钢发生屈曲。四段参考的全纤维屈服状态本次未逐一筛查，不能据此断言其全弹性。", "",
        "|风攻角|最终最大压屈杆数|首次保存点 m/s|前一个保存点 m/s|首次点V最小肢力 kN|", "|---|---:|---:|---:|---:|"])
    for event in state_events:
        first=event['first_buckling_saved_speed_m_s']
        if first is None:
            lines.append(f"|{event['angle_deg']:g}°|{event['max_tmq_buckled_members']}|未触发|—|—|")
        else:
            lines.append(f"|{event['angle_deg']:g}°|{event['max_tmq_buckled_members']}|{first:.3f}|{event['previous_saved_speed_m_s']:.3f}|{event['v_min_force_at_first_saved_buckling_N']/1000:.3f}|")
    lines.extend(["", "45° 的首次记录点已伴随 V 肢受压，需在该假设超界条件下解释；90° 首次记录点 V 肢仍受拉，但材料系数/串构造仍未实测校准。表中速度只给出保存步的检测区间，不是精确分岔或极限速度。", ""])
    lines.extend(["", "### 假设超界与未完成工况", ""])
    for case in cases:
        label=f"{case['model_kind']} / {case['angle_deg']:g}°"
        fail=case.get("first_axial_assumption_guard_failure")
        if fail: lines.append(f"- {label}：首次保存的假设超界点 U={fail['wind_speed_m_s']:.3f} m/s，最小 V 肢力 {fail['insulator_min_force_N']/1000:.3f} kN、索力/名义强度 {fail['line_max_rated_ratio']:.3f}。这是采样发现点，不是精确临界速度。")
        else: lines.append(f"- {label}：所保存状态内未触发 V/索轴向假设检查。")
        if case.get("stop_reason"): lines.append(f"  停止原因：{case['stop_reason']}。")
    lines.extend(["", "## 图与可复核文件", ""])
    for filename, _, _, ylabel in plots: lines.extend([f"![{ylabel}]({filename})", ""])
    lines.extend(["![塔脚剪力与塔控点位移直接对比](pushover_curve.png)", ""])
    lines.extend(["- `comparison.csv/json`：仅共同已到达、平衡通过的目标点，含塔控点、塔脚、远端、挂点、索力与 V 肢力。",
        "- 每工况 `states.jsonl`：四跨每个索段轴力、四根 V 肢力、各挂点三向位移、各支座六分量反力。",
        "- 每工况 `history.csv` / `equilibrium.jsonl` / `attempts.jsonl`：全部接受状态、独立残差及每次成功/失败求解尝试。",
        "- `semantic_wind_loads.json` / `semantic_gravity_loads.json`：标签无关的逐物理节点清单；`wind_load_plan.json`：塔/线/总合力合矩。", "",
        "## 结论边界", "",
        "此对比不能把所有差别归因于 TMQ 公式。参考塔是四段 Corotational dispBeamColumn + Steel02 纤维截面，包含杆内初弯曲和弯轴耦合；TMQ 塔每根一段、轴向滞回与弹性弯扭解耦，I23 耦合未保留。若小幅风下曲线近线性，只能说明所走路径的整体响应接近线性，不能证明屈曲后参数正确。TMQ 的钢管文献参数尚未经本塔角钢实测标定。",
        "40 段导线采用既有 B2 40→80 段静态敏感性结果作为成本选择依据；本次未声称四段塔或全部高风状态网格收敛。原四段 Steel02 本身也不是收敛真值。弹性 V 串一旦受压，即超出柔性悬垂串的受力解释；继续到 60/80 m/s 的输出只显示当前数学模型，不承诺构造适用。导线 8 m 初垂度和 20 kN 初力不是由实测悬链线反求，相同初始输入可以产生不同的重力后形状，已分别记录。",
        "塔风使用全杆角钢肢宽投影代理，Cx=Cy=Cd=1、均匀高度系数、yaw_gain=0.2，缺少真实风场/体型/遮挡校准；两个导线挂点和四个固定远端并非完整多塔多分裂导线系统。不存在根据本次结果认定工程极限风速的依据。", "",
        "导线目录名义拉断力 123.04 kN 只用于数值状态筛查，`索力/目录拉断力` 不是含分项系数、组合与构造条件的设计承载比。风速20–80 m/s仅为本固定验证静态风场的荷载标度，不能称规范基本风速或工程极限风速。每例用时受到宿主高负载与进程争用影响，不用于报告一般性加速比。若存在 runtime_budget_adjustment.json，其记录仅调整计算预算，不改变物理/收敛参数；运行中已持有旧预算的算例保留原设置。", "",
        "## 复现", "", "```bash", "OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.tower_line_wind_comparison batch --output <新的空目录>", "```", ""])
    (output/"REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    publish_html(output)


def run_batch(output, *, timeout=1200.):
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite evidence: {output}")
    output.mkdir(parents=True)
    write_json(output/"plan.json", {"angles_deg": list(ANGLES), "speeds_m_s": list(SPEEDS),
        "models": list(MODELS), "segments_per_span": 40, "timeout_per_wind_stage_seconds": timeout,
        "maximum_parallel_independent_processes": 2, "load_geometry": "common initial parabola"})
    env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    def one_case(pair):
        angle, kind=pair
        name=f"{kind}_deg_{angle:g}"
        print(f"START {name}", flush=True)
        with (output/f"{name}.log").open("w") as log:
            cmd=[sys.executable, "-m", "initial_imperfection_material.tian_ma_qu.tower_line_wind_comparison", "case",
                 "--output", str(output/name), "--model", kind, "--angle", str(angle), "--timeout", str(timeout)]
            try:
                result=subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout+1200)
                print(f"END {name}: exit {result.returncode}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"END {name}: hard timeout", flush=True)
                summary_path=output/name/"summary.json"
                if summary_path.exists():
                    summary=json.loads(summary_path.read_text())
                    summary.update(status="hard_timeout", stop_reason="subprocess_hard_timeout",
                                   outer_wall_budget_seconds=timeout+1200)
                    write_json(summary_path, summary)
    # Threads only supervise fresh child processes; no shared OpenSees domain.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one_case, [(angle, kind) for angle in ANGLES for kind in MODELS]))
    make_report(output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("case", "batch", "report"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", choices=MODELS, default="tmq")
    parser.add_argument("--angle", type=float, default=0.)
    parser.add_argument("--timeout", type=float, default=1200.)
    args=parser.parse_args()
    if args.command=="case":
        result=run_case(args.output, model_kind=args.model, angle_deg=args.angle, timeout=args.timeout)
        raise SystemExit(0 if result["status"]=="complete" else 2)
    elif args.command=="report": make_report(args.output)
    else: run_batch(args.output, timeout=args.timeout)


if __name__=="__main__":
    main()
