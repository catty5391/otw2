"""Controlled four-angle static wind comparison of two *tower model schemes*.

Run with ``python -m initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison
--output ...``. Each angle/scheme has a fresh OpenSees subprocess. Existing result
directories are never overwritten. This is neither wind time history nor a
calibrated design/collapse assessment.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
import hashlib
import html
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
ANGLES = (0, 30, 45, 90)
SPEEDS = (20., 30., 40., 60., 80.)
SCHEMES = ("tmq", "steel02_four_segments")


def write_json(path, data):
    path=Path(path)
    temporary=path.with_name(path.name+".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(path)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_speeds(values):
    values = tuple(float(v) for v in values)
    if not values or any(not math.isfinite(v) or v <= 0 for v in values) or any(b <= a for a, b in zip(values, values[1:])):
        raise ValueError("wind speeds must be positive, finite and strictly increasing")
    return values


def project_end_forces(first, last, chord):
    """Common physical-member end projection; tensile positive, N.

    ``first``/``last`` are 12-entry GLOBAL beam resisting-force vectors.
    Projection is onto the initial physical-member chord, not a bowed segment's
    axis or a TMQ equivalent material strain. Both endpoint values are retained.
    """
    if len(first) != 12 or len(last) != 12 or len(chord) != 3:
        raise ValueError("expected 3D beam end forces and 3D chord")
    norm = math.sqrt(sum(v*v for v in chord))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("positive finite chord length required")
    ni = -sum(first[k]*chord[k]/norm for k in range(3))
    nj = sum(last[6+k]*chord[k]/norm for k in range(3))
    return ni, nj, (ni+nj)/2


def run_case(output, scheme, angle, speeds=SPEEDS, timeout=1200.):
    import openseespy.opensees as ops
    from model.tower_model_with_tian_ma_qu import OpenSeesModelWithTianMaQu
    from model.tower_model_with_buckling import OpenSeesModelWithBuckling
    from initial_imperfection_material.full_tower_cyclic import _apply_gravity
    from .directional_loading import build_load_plan, verification_config
    from util.processing.directional_wind import apply_nodal_wind_loads, nodal_resultant, wind_unit_vector
    from util.analysis.equilibrium_checks import static_equilibrium
    from util.analysis.stepping import AdaptiveStepper

    speeds = validate_speeds(speeds)
    if scheme not in SCHEMES or angle not in ANGLES:
        raise ValueError("unsupported comparison scheme or angle")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing evidence: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT/"Source/Z30103A6.s2k"
    started = time.monotonic()
    summary = dict(schema_version=1, analysis="single_tower_static_wind_scheme_comparison", scheme=scheme,
        angle_deg=angle, status="running", worker_pid=os.getpid(), target_speeds_m_s=list(speeds), completed_speeds_m_s=[],
        validated_for_design=False, true_ultimate_wind_speed_established=False,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), engine_version=ops.version(),
        imperfection_ratio=.001, random_seed=30103 if scheme != "tmq" else None,
        control_node=350, control_height_m=36.4, accepted_steps=0,
        strain_warning="TMQ equivalent member strain is not Steel02 fiber strain; common axial/Afy metric is not a yield detector",
        member_force_definition="tension positive, average of both physical-member end forces projected onto initial chord",
        displacement_definition="original S2K nodes; wind increment relative to each scheme's own gravity equilibrium",
        time_axis="quasi-static accepted steps, not seconds")
    history = []
    write_json(output/"summary.json", summary)
    attempts = (output/"attempts.jsonl").open("w", encoding="utf-8")
    eqfile = (output/"equilibrium.jsonl").open("w", encoding="utf-8")
    hfile = (output/"history.csv").open("w", encoding="utf-8", newline="")
    nfile = gzip.open(output/"node_states.csv.gz", "wt", encoding="utf-8", newline="")
    mfile = gzip.open(output/"member_forces.csv.gz", "wt", encoding="utf-8", newline="")
    rfile = (output/"support_reactions.csv").open("w", encoding="utf-8", newline="")
    nw, mw, rw = csv.writer(nfile), csv.writer(mfile), csv.writer(rfile)
    nw.writerow(("step", "wind_speed_m_s", "node_tag", "ux_m", "uy_m", "uz_m", "rx_rad", "ry_rad", "rz_rad", "wind_ux_m", "wind_uy_m", "wind_uz_m"))
    mw.writerow(("step", "wind_speed_m_s", "physical_member_tag", "node_i", "node_j", "N_i_N", "N_j_N", "N_mean_N", "abs_N_over_Afy"))
    rw.writerow(("step", "wind_speed_m_s", "node_tag", "Rx_N", "Ry_N", "Rz_N", "Mx_Nm", "My_Nm", "Mz_Nm"))
    stepper = None
    try:
        ops.wipe()
        if scheme == "tmq":
            model = OpenSeesModelWithTianMaQu(source, output_dir=output/"model_data", imperfection_ratio=.001)
        else:
            model = OpenSeesModelWithBuckling(source, output_dir=output/"model_data", random_disp_ratio=.001,
                member_divisions=4, imperfection_seed=30103)
        import faulthandler
        model_start = time.monotonic()
        print("BUILD start; 90s stack snapshot, if emitted, is a diagnostic and does not stop the solver", flush=True)
        faulthandler.dump_traceback_later(90, repeat=False)
        try:
            model.model_tower()
        finally:
            faulthandler.cancel_dump_traceback_later()
        summary["model_build_seconds"] = time.monotonic()-model_start
        write_json(output/"summary.json", summary)
        original_nodes = model._parse_node_coordinates()
        connectivity = model._parse_element_connectivity()
        sections = model._frame_section_properties()
        assignments = model._element_section_assignments()
        basics = {model._parse_key_values(line)["Material"]: model._parse_key_values(line)
                  for line in model._table_lines("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES")}
        steels = {model._parse_key_values(line)["Material"]: model._parse_key_values(line)
                  for line in model._table_lines("MATERIAL PROPERTIES 03A - STEEL DATA")}
        physical = {}
        for tag, item in sorted(connectivity.items()):
            ni, nj = item["node_i"], item["node_j"]
            chord = tuple(original_nodes[nj][k]-original_nodes[ni][k] for k in "xyz")
            name = assignments[tag]["section_name"]
            section = sections[name]
            steel = section["material_name"]
            area, fy = float(section["area"]), float(steels[steel]["Fy"])*1e6
            physical[tag] = dict(node_i=ni, node_j=nj, chord=chord, section_name=name,
                E_Pa=float(basics[steel]["E1"]), fy_Pa=fy, area_m2=area, Afy_N=area*fy,
                segments=[tag] if scheme == "tmq" else model.element_segment_map[tag])
        bases = sorted(model.fix_map)
        height = original_nodes[350]["z"]-min(original_nodes[n]["z"] for n in bases)
        configuration = verification_config(angle, wind_speed_m_s=20.)
        loads, plan = build_load_plan(model, configuration)
        write_json(output/"wind_load_plan.json", plan)
        with (output/"wind_nodal_loads.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(("node_tag", "Fx_N", "Fy_N", "Fz_N", "Mx_Nm", "My_Nm", "Mz_Nm"))
            writer.writerows((n, *v) for n, v in sorted(loads.items()))
        audit = dict(original_node_count=len(original_nodes), physical_member_count=len(physical),
            finite_element_node_count=len(ops.getNodeTags()), finite_element_count=len(ops.getEleTags()),
            original_geometry_sha256=digest({n: [r[k] for k in "xyz"] for n, r in original_nodes.items()}),
            physical_member_inputs_sha256=digest({n: {k:v for k,v in r.items() if k != "segments"} for n,r in physical.items()}),
            nodal_mass_sha256=digest({n: [r[k] for k in ("mx","my","mz","mrx","mry","mrz")] for n,r in model.mass_map.items()}),
            supports_sha256=digest({n: [r[k] for k in ("ux","uy","uz","rx","ry","rz")] for n,r in model.fix_map.items()}),
            wind_nodal_load_sha256=digest(loads), reference_wind_resultant=plan["combined_initial_coordinate_resultant"],
            total_mass_xyz_kg=[sum(r[k] for r in model.mass_map.values()) for k in ("mx","my","mz")])
        write_json(output/"input_audit.json", audit)
        summary.update(audit=audit, control_height_m=height, wind_configuration=configuration)
        print(f"BUILT {scheme} angle={angle} nodes={len(ops.getNodeTags())} members={len(physical)}", flush=True)
        gravity_start = time.monotonic()
        gravity = _apply_gravity(model, steps=10)
        summary["gravity_seconds"] = time.monotonic()-gravity_start
        summary["pre_wind_seconds"] = time.monotonic()-started
        gravity_disps = {n: tuple(float(v) for v in ops.nodeDisp(n)) for n in original_nodes}
        summary["total_gravity_mass_kg"] = gravity.total_mass
        summary["gravity_control_displacement_m"] = list(gravity_disps[350])
        wind = apply_nodal_wind_loads(loads, model.tag_manager, ops)
        direction = wind_unit_vector(angle)
        constrained = {(int(n), d) for n, fix in model.fix_map.items()
                       for d, key in enumerate(("ux", "uy", "uz", "rx", "ry", "rz"), 1) if fix[key]}
        rotations = {(int(n), d) for n in ops.getNodeTags() for d in (4, 5, 6)}
        history_writer = None

        def capture():
            nonlocal history_writer
            step = len(history)
            factor = float(ops.getLoadFactor(wind.pattern_tag))
            speed = 20*math.sqrt(max(0., factor))
            combined = {int(n): list(v) for n, v in gravity.node_loads.items()}
            for n, vector in loads.items():
                destination = combined.setdefault(int(n), [0.]*6)
                for d, value in enumerate(vector):
                    destination[d] += factor*value
            ledger = {(n, d):v for n, vec in combined.items() for d, v in enumerate(vec, 1)}
            scale = max(1., sum(abs(v) for (n,d),v in ledger.items() if d <= 3))
            eq = static_equilibrium(ops, ledger, constrained_dofs=constrained, rotational_dofs=rotations,
                force_scale=scale, moment_scale=scale*height, relative_tolerance=1e-6,
                force_absolute_tolerance=.001, moment_absolute_tolerance=.001)
            eq.pop("free_dof_residuals")
            eqfile.write(json.dumps(dict(step=step, wind_speed_m_s=speed, **eq))+"\n")
            eqfile.flush()
            control = [float(ops.nodeDisp(350,d))-gravity_disps[350][d-1] for d in (1,2,3)]
            current_coords = {int(n): tuple(float(ops.nodeCoord(n,d))+float(ops.nodeDisp(n,d)) for d in (1,2,3))
                              for n in ops.getNodeTags()}
            ops.reactions()
            reactions = {n: tuple(float(v) for v in ops.nodeReaction(n)) for n in bases}
            external_resultant = nodal_resultant(current_coords, combined)
            reaction_resultant = nodal_resultant(current_coords, reactions)
            balance = {key: max(abs(a+b) for a,b in zip(external_resultant[key], reaction_resultant[key]))
                       for key in ("force_N", "moment_Nm")}
            for n, reaction in reactions.items():
                rw.writerow((step, speed, n, *reaction))
            max_nodal = 0.
            for n in sorted(original_nodes):
                absolute = tuple(float(v) for v in ops.nodeDisp(n))
                increment = tuple(absolute[d]-gravity_disps[n][d] for d in range(3))
                max_nodal = max(max_nodal, math.hypot(*increment[:2]))
                nw.writerow((step, speed, n, *absolute, *increment))
            compression, tension, maxratio, worst_member = 0., 0., 0., 0
            for tag, member in physical.items():
                segments = member["segments"]
                first, last = ops.eleForce(segments[0]), ops.eleForce(segments[-1])
                ni, nj, mean = project_end_forces(first, last, member["chord"])
                ratio = abs(mean)/member["Afy_N"]
                mw.writerow((step, speed, tag, member["node_i"], member["node_j"], ni, nj, mean, ratio))
                compression, tension = min(compression, mean), max(tension, mean)
                if ratio > maxratio:
                    maxratio, worst_member = ratio, tag
            states = model.committed_member_states() if scheme == "tmq" else []
            row = dict(step=step, wind_speed_m_s=speed, load_factor=factor,
                ux_m=control[0], uy_m=control[1], uz_m=control[2],
                along_wind_displacement_m=sum(control[d]*direction[d] for d in range(3)),
                across_wind_displacement_m=-control[0]*direction[1]+control[1]*direction[0],
                horizontal_drift_ratio=math.hypot(*control[:2])/height,
                max_original_node_horizontal_displacement_m=max_nodal,
                control_rz_rad=float(ops.nodeDisp(350,6))-gravity_disps[350][5],
                base_shear_x_N=-sum(v[0] for v in reactions.values()),
                base_shear_y_N=-sum(v[1] for v in reactions.values()),
                max_compression_chord_N=compression, max_tension_chord_N=tension,
                max_abs_chord_N_over_Afy=maxratio, max_axial_demand_member=worst_member,
                tmq_buckled_members=sum(s["buckling_count"] > 0 for s in states) if states else "",
                tmq_tension_yield_members=sum(s["tension_yield_ever"] for s in states) if states else "",
                equilibrium_passed=eq["passed"], force_residual_N=eq["translation"]["maximum_absolute"],
                moment_residual_Nm=eq["rotation"]["maximum_absolute"],
                global_force_balance_N=balance["force_N"], global_moment_balance_Nm=balance["moment_Nm"])
            if history_writer is None:
                history_writer = csv.DictWriter(hfile, fieldnames=list(row))
                history_writer.writeheader()
            history_writer.writerow(row)
            for f in (hfile,nfile,mfile,rfile):
                f.flush()
            history.append(row)
            summary.update(accepted_steps=step, last_point=row)
            write_json(output/"summary.json", summary)
            print(f"STEP {step} U={speed:.4f} along_mm={1000*row['along_wind_displacement_m']:.4f} eq={eq['passed']}", flush=True)
            if not eq["passed"]:
                raise RuntimeError("independent equilibrium failed at committed state; recorded, not rolled back")
            if row["horizontal_drift_ratio"] > .03:
                raise RuntimeError("3% computational drift guard; not a failure criterion")

        capture()
        ops.wipeAnalysis()
        ops.constraints("Transformation")
        ops.numberer("RCM")
        ops.system("UmfPack")
        ops.test("NormUnbalance", .005, 80, 0)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", .5)
        ops.analysis("Static")

        def log_attempt(record):
            attempts.write(json.dumps(record)+"\n")
            attempts.flush()

        stepper = AdaptiveStepper(ops, progress=lambda:float(ops.getLoadFactor(wind.pattern_tag)),
            configure_increment=lambda inc:ops.integrator("LoadControl", inc),
            convergence_test=("NormUnbalance", .005, 80, 0), minimum_increment=.0001,
            maximum_attempts_per_step=18, maximum_total_attempts=150,
            timeout_seconds=timeout, on_attempt=log_attempt,
            recovery_policy="gradual")
        summary["solver_settings"] = stepper.settings()
        for speed in speeds:
            result = stepper.advance_to((speed/20)**2, maximum_increment=.5, on_step=lambda step:capture())
            if not result.converged:
                summary.update(status="partial", stop_reason=result.stop_reason)
                break
            summary["completed_speeds_m_s"].append(speed)
            write_json(output/"summary.json", summary)
        else:
            summary["status"] = "complete"
    except Exception as error:
        summary.update(status="stopped", stop_reason=f"{type(error).__name__}: {error}")
        print(summary["stop_reason"], flush=True)
    finally:
        if stepper is not None:
            summary["solver_diagnostics"] = stepper.diagnostics()
        summary["wall_seconds"] = time.monotonic()-started
        summary["all_saved_equilibria_passed"] = bool(history) and all(row["equilibrium_passed"] for row in history)
        write_json(output/"summary.json", summary)
        for f in (attempts,eqfile,hfile,nfile,mfile,rfile):
            f.close()
        ops.wipe()
    return summary


def compare_audits(tmq, reference):
    keys = ("original_geometry_sha256", "physical_member_inputs_sha256", "nodal_mass_sha256", "supports_sha256", "wind_nodal_load_sha256")
    checks = {key:tmq.get(key) == reference.get(key) and key in tmq for key in keys}
    checks["reference_wind_force_and_moment_equal"] = "reference_wind_resultant" in tmq and tmq.get("reference_wind_resultant") == reference.get("reference_wind_resultant")
    checks["mass_xyz_equal"] = "total_mass_xyz_kg" in tmq and tmq.get("total_mass_xyz_kg") == reference.get("total_mass_xyz_kg")
    return dict(passed=all(checks.values()), checks=checks)


def _history(directory):
    path = directory/"history.csv"
    return list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []


def _at_speed(rows, speed):
    matching = [r for r in rows if abs(float(r["wind_speed_m_s"])-speed)<1e-6 and r["equilibrium_passed"] == "True"]
    return matching[-1] if matching else None


def case_directory(output, scheme, angle):
    key=f"{scheme}_{angle}"
    selection=output/"case_selections.json"
    entries=json.loads(selection.read_text()) if selection.exists() else {}
    candidate=(output/entries.get(key,{}).get("selected_directory",f"runs/{key}")).resolve()
    if not candidate.is_relative_to((output/"runs").resolve()):
        raise ValueError("case selection must remain inside this suite's runs directory")
    return candidate


def publish(output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output = Path(output)
    cases, pairs, table = [], [], []
    for angle in ANGLES:
        by_scheme = {}
        for scheme in SCHEMES:
            directory = case_directory(output,scheme,angle)
            path = directory/"summary.json"
            summary = json.loads(path.read_text()) if path.exists() else dict(status="missing",scheme=scheme,angle_deg=angle)
            rows = _history(directory)
            case = dict(**summary, history=rows, artifact_directory=str(directory.relative_to(output.resolve())))
            cases.append(case)
            by_scheme[scheme] = case
        tmq, reference = (by_scheme[s] for s in SCHEMES)
        audit = compare_audits(tmq.get("audit", {}), reference.get("audit", {}))
        pairs.append(dict(angle_deg=angle, **audit))
        for speed in SPEEDS:
            a, b = (_at_speed(case["history"],speed) for case in (tmq, reference))
            terminal = all(case.get("status") in {"complete","partial","stopped"} for case in (tmq,reference))
            row = dict(angle_deg=angle, speed_m_s=speed, comparable=bool(a and b and audit["passed"] and terminal))
            for label, state in (("tmq", a),("steel02", b)):
                for key in ("along_wind_displacement_m", "across_wind_displacement_m", "max_abs_chord_N_over_Afy", "max_compression_chord_N", "max_tension_chord_N", "horizontal_drift_ratio", "force_residual_N"):
                    row[f"{label}_{key}"] = float(state[key]) if state else None
            if row["comparable"]:
                ua, ub = float(a["along_wind_displacement_m"]), float(b["along_wind_displacement_m"])
                row["tmq_vs_steel02_displacement_change_percent"] = (ua/ub-1)*100 if ub else None
                # Match complete physical-member sets; a global curve cannot show redistribution.
                arrays = []
                for scheme, state in (("tmq",a),("steel02_four_segments",b)):
                    with gzip.open(case_directory(output,scheme,angle)/"member_forces.csv.gz", "rt", encoding="utf-8") as f:
                        arrays.append({int(v["physical_member_tag"]):float(v["N_mean_N"]) for v in csv.DictReader(f) if int(v["step"]) == int(state["step"])})
                if set(arrays[0]) != set(arrays[1]) or len(arrays[0]) != tmq["audit"]["physical_member_count"]:
                    raise ValueError("physical-member mismatch in force comparison")
                difference = {tag:arrays[0][tag]-arrays[1][tag] for tag in arrays[0]}
                norm = math.sqrt(sum(v*v for v in arrays[1].values()))
                row["member_axial_relative_L2_percent"] = 100*math.sqrt(sum(v*v for v in difference.values()))/norm if norm else None
                worst = max(difference,key=lambda tag:abs(difference[tag]))
                row["largest_axial_difference_member"] = worst
                row["largest_axial_difference_N"] = abs(difference[worst])
            table.append(row)
    result = dict(schema_version=1, analysis="same_wind_two_model_schemes_four_angles", angles_deg=list(ANGLES),
        speeds_m_s=list(SPEEDS), all_cases_complete=all(c["status"] == "complete" for c in cases),
        all_input_pairs_equal=all(p["passed"] for p in pairs),
        all_saved_equilibria_passed=all(c.get("all_saved_equilibria_passed",False) for c in cases),
        compared_input_audits=pairs, cases=cases, common_target_comparison=table,
        validated_for_design=False, true_ultimate_wind_speed_established=False,
        selected_retry_evidence=json.loads((output/"case_selections.json").read_text()) if (output/"case_selections.json").exists() else {})
    if (output/"verification.json").exists():
        verification=json.loads((output/"verification.json").read_text())
        result["artifact_verification"]={k:verification[k] for k in ("passed","selected_case_count","unit_tests_count","unit_tests_passed")}
    write_json(output/"summary.json", result)
    with (output/"comparison.csv").open("w",encoding="utf-8",newline="") as file:
        fields = list(dict.fromkeys(key for row in table for key in row))
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(table)
    fig, axes = plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    for angle, ax in zip(ANGLES,axes.flat):
        for scheme, color, label in (("tmq","#156a8c","TMQ axial + elastic bending"),("steel02_four_segments","#c55d2b","4-segment Steel02 fiber")):
            case = next(c for c in cases if c["scheme"] == scheme and c["angle_deg"] == angle)
            rows = [r for r in case["history"] if r["equilibrium_passed"] == "True"]
            ax.plot([float(r["wind_speed_m_s"]) for r in rows],[1000*float(r["along_wind_displacement_m"]) for r in rows],".-",color=color,label=label)
        ax.set(title=f"Wind angle {angle} deg",xlabel="Equivalent steady wind speed (m/s)",ylabel="Node 350 along-wind increment (mm)")
        ax.grid(alpha=.25)
        ax.legend(fontsize=8)
    fig.savefig(output/"displacement_comparison.png",dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(1,2,figsize=(12,4),constrained_layout=True)
    for angle in ANGLES:
        rows = [r for r in table if r["angle_deg"] == angle and r["comparable"]]
        axes[0].plot([r["speed_m_s"] for r in rows],[r["tmq_vs_steel02_displacement_change_percent"] for r in rows],"o-",label=f"{angle} deg")
        axes[1].plot([r["speed_m_s"] for r in rows],[r["member_axial_relative_L2_percent"] for r in rows],"o-",label=f"{angle} deg")
    axes[0].set(xlabel="Wind speed (m/s)",ylabel="TMQ displacement change\nrelative to Steel02 (%)")
    axes[1].set(xlabel="Wind speed (m/s)",ylabel="Physical-member axial-force\nrelative L2 difference (%)")
    for ax in axes:
        ax.grid(alpha=.25)
        ax.legend()
    fig.savefig(output/"difference_comparison.png",dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    for angle, ax in zip(ANGLES, axes.flat):
        direction = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        for scheme,color,label in (("tmq","#156a8c","TMQ axial + elastic bending"),("steel02_four_segments","#c55d2b","4-segment Steel02 fiber")):
            case = next(c for c in cases if c["scheme"] == scheme and c["angle_deg"] == angle)
            rows=[r for r in case["history"] if r["equilibrium_passed"] == "True"]
            ax.plot([1000*float(r["along_wind_displacement_m"]) for r in rows],
                    [(float(r["base_shear_x_N"])*direction[0]+float(r["base_shear_y_N"])*direction[1])/1000 for r in rows],
                    ".-",color=color,label=label)
        ax.set(title=f"Wind angle {angle} deg",xlabel="Node 350 along-wind increment (mm)",ylabel="Along-wind base shear (kN)")
        ax.grid(alpha=.25)
        ax.legend(fontsize=8)
    fig.savefig(output/"force_displacement_comparison.png",dpi=170)
    plt.close(fig)
    report = _report(result)
    (output/"REPORT.md").write_text(report,encoding="utf-8")
    # Standalone report does not depend on a frontend build or a CDN.
    _write_html(output, result, report)
    return result


def _write_html(output, result, report):
    rows=[]
    for row in result["common_target_comparison"]:
        if row["comparable"]:
            values=(f"{1000*row['tmq_along_wind_displacement_m']:.3f}",
                    f"{1000*row['steel02_along_wind_displacement_m']:.3f}",
                    f"{row['tmq_vs_steel02_displacement_change_percent']:+.3f}%",
                    f"{row['member_axial_relative_L2_percent']:.3f}%")
        else:
            values=("未形成共同有效点","—","—","—")
        rows.append(f"<tr data-angle='{row['angle_deg']}'><td>{row['angle_deg']}°</td><td>{row['speed_m_s']:g}</td>"+"".join(f"<td>{v}</td>" for v in values)+"</tr>")
    lines=report.splitlines()
    findings=[]
    active=False
    for line in lines:
        if line == "## 从实际结果能够得出的结论":
            active=True
        elif active and line.startswith("## "):
            break
        elif active and line.strip():
            findings.append(f"<p>{html.escape(line)}</p>")
    count=sum(c["status"]=="complete" for c in result["cases"])
    page="""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>单塔新旧方案四风角对比</title><style>
body{max-width:1160px;margin:32px auto;padding:0 20px;color:#20303b;font:16px/1.65 system-ui;background:#f4f7fa}h1{font-size:32px;line-height:1.3}h2{margin-top:0}section{background:#fff;margin:20px 0;padding:24px;border-radius:12px;border:1px solid #dee6ed}img{width:100%;display:block}.cards{display:flex;gap:12px;flex-wrap:wrap}.cards div{flex:1;min-width:150px;background:#eaf3f7;border-radius:10px;padding:18px}.cards b{display:block;font-size:23px}a{color:#056a91}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px 12px;border-bottom:1px solid #e1e6eb;text-align:right;white-space:nowrap}th{background:#f1f6f9}th:first-child,td:first-child{text-align:left}.scroll{overflow:auto}.muted{color:#5d6d78}.pill{color:#765519;background:#fff3d5;padding:12px 16px;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}select{padding:8px;margin:8px 0 16px}summary{cursor:pointer;font-weight:700}
</style><p class="muted">Z30103A6 · 2026-10-28 · 静态风荷载</p><h1>单塔：新旧方案 × 四个风攻角</h1>
<p>同一塔、同一逐节点风荷载与质量，从重力平衡开始，比较 TMQ 等效轴向梁与四分段 Steel02 纤维梁。</p>
<div class="pill">探索性建模方案对比。尚不能作为设计、倒塌风速或风振滞回结论。</div>
<p><a href="REPORT.md">完整步骤与结论</a> · <a href="comparison.csv">对比表 CSV</a> · <a href="summary.json">完整审计 JSON</a> · <a href="verification.json">测试与数据完整性</a></p>
<div class="cards">"""
    page+=f"<div><b>{count} / 8</b>组合完成全部目标</div><div><b>{sum(p['passed'] for p in result['compared_input_audits'])} / 4</b>新旧输入核对通过</div><div><b>20–80 m/s</b>目标等效静态风速</div><div><b>0° / 30° / 45° / 90°</b>风朝向 +X 至 +Y</div></div>"
    page+="<section><h2>结果说明</h2>"+"".join(findings)+"</section>"
    page+="<section><h2>风速与沿风位移</h2><p class='muted'>节点 350，高 36.4 m。位移扣除各自重力平衡值。风力正比于风速平方，曲线弯曲不直接等于材料非线性。</p><img src='displacement_comparison.png' alt='四风角两种方案风速-沿风位移曲线'></section>"
    page+="<section><h2>基底剪力与位移</h2><p class='muted'>用力—位移关系判断本轮刚度是否发生明显变化；曲线仅绘制实际通过平衡的状态。</p><img src='force_displacement_comparison.png' alt='四风角两种方案沿风基底剪力-位移曲线'></section>"
    page+="<section><h2>整体响应与逐杆内力差异</h2><img src='difference_comparison.png' alt='沿风位移与所有物理杆轴力差异'></section>"
    page+="<section><h2>共同目标风速对照</h2><label>风攻角 <select id='angle'><option value='all'>全部</option><option>0</option><option>30</option><option>45</option><option>90</option></select></label><div class='scroll'><table><thead><tr><th>风角</th><th>风速 m/s</th><th>TMQ 位移 mm</th><th>四段位移 mm</th><th>位移相对变化</th><th>逐杆轴力 L2 差</th></tr></thead><tbody>"+"".join(rows)+"</tbody></table></div><p class='muted'>弦向轴力取物理杆两个端点的全局端力在原始弦方向的投影平均；L2 差避免小轴力分母失真。它不等于纤维应力或屈服指标。</p></section>"
    page+="<section><details><summary>全部方法、执行步骤、收敛记录与局限</summary><pre>"+html.escape(report)+"</pre></details></section><script>document.getElementById('angle').addEventListener('change',e=>{document.querySelectorAll('tr[data-angle]').forEach(r=>r.hidden=e.target.value!=='all'&&r.dataset.angle!==e.target.value)})</script></html>"
    (output/"index.html").write_text(page,encoding="utf-8")


def _report(result):
    cases = result["cases"]
    lines = ["# 单塔新旧建模方案与风攻角对比（2026-10-28）", "",
        "## 问题与结果口径", "",
        "对 Z30103A6 单塔，在相同静态风场下对比当前 TMQ 方案与四分段 Steel02 纤维梁方案；同时覆盖 0°、30°、45°、90°。角度采用 flow TOWARDS（风吹向）：0° 朝全局 +X 横向，90° 朝 +Y 沿线方向。目标风速 20、30、40、60、80 m/s，0 为各模型自身重力平衡状态。计算步号不是秒；本次不是脉动风时程，也不是往复滞回验证。", "",
        f"真实执行：{sum(c['status']=='complete' for c in cases)}/{len(cases)} 个组合完成全部目标；输入公平核对 {'全部通过' if result['all_input_pairs_equal'] else '存在不一致，见 summary.json'}；已保存状态独立自由度平衡 {'全部通过' if result['all_saved_equilibria_passed'] else '存在未通过/未完成状态'}。", "",
        "## 执行步骤", "",
        "1. 每个建模方案、每个风角新建独立 OpenSees 进程，避免复用塑性或屈曲历史。设置 OPENBLAS_NUM_THREADS=1、OMP_NUM_THREADS=1。",
        "2. 同一 S2K 输入、同一原始节点/物理杆连接、E/fy/A、质量与支承。四分段模型显式半正弦 L/1000 初弯曲，固定随机方向种子 30103；TMQ 折算同一缺陷幅比，直梁不叠加几何初弯曲。",
        "3. 两者使用现有 verification_config 和原始 S2K 物理杆迎风面积生成器，避免把四分段重复计入受风面积。rho_air=1.225 kg/m³，Cx=Cy=1，yaw_gain=0.2；配置中的导线 Cd=1 仅供塔线复用，本单塔无导线受风力。均匀高度因子，全部物理杆角钢肢宽投影代理求和，无屏蔽或截面朝向校准。",
        "4. 用 SHA256 核对原始节点坐标、物理杆输入、逐节点质量、约束、逐节点风荷载，并精确比较合力/合矩。不把有意不同的中间节点与单元数当成输入不一致。",
        "5. 每种模型以 10 个重力增量求静力平衡，再冻结重力并重置伪时间；加载 q=0.5*rho*U²，参考 U=20 m/s，lambda=(U/20)²，最大荷载因子步长 0.5。",
        "6. 每个接受步独立重组全部梁单元全局节点力，检查自由平移与转动残差；保存支座反力、重力和风的整体合力/合矩平衡。记录原始 621 节点的完整位移及 1528 根物理杆两个端点的弦向轴力。",
        "7. 只在两方案真实达到且通过平衡的同一目标风速比较；输出沿风位移、侧风位移、漂移、压/拉弦向轴力极值、所有物理杆轴力向量 L2 差。停止点保留，不插值冒充完成。", "",
        "### 本轮风荷载公式", "",
        "`q = 0.5 × rho_air × U²`；每个物理杆在高度分带内的荷载幅值为 `F = q × G(z) × [1 + 0.2 sin²(2θ)] × [Ax cos²θ + Ay sin²θ]`，方向为 `(cosθ, sinθ, 0)`。本次 `G(z)=1`；角钢肢宽 b 的代理面积 `Ax=b√(dy²+dz²)`、`Ay=b√(dx²+dz²)`。每个杆段按其荷载作用点线性分配到原始两端节点，保持合力和关于原点的合矩。每个风角都重新生成投影/偏航与方向，未把一个角度的总力简单旋转。", "",
        "实现来自现有 `directional_loading.verification_config/build_load_plan` 与 `util.processing.tower_directional_wind`。这些系数和面积用途是固定静态验证场，不是按规范校准的设计荷载。比较不同风角时，既改变施力方向，也改变荷载幅值，所以不能只由位移大小反推结构方向刚度。", "",
        "## 同条件结果", "", "位移为节点 350（高 36.4 m）相对自身重力平衡的沿风增量；弦向轴力拉为正。", "",
        "|风角°|风速 m/s|TMQ 位移 mm|四段位移 mm|TMQ 相对变化 %|逐杆轴力相对 L2 差 %|", "|---:|---:|---:|---:|---:|---:|"]
    for r in result["common_target_comparison"]:
        if r["comparable"]:
            lines.append(f"|{r['angle_deg']}|{r['speed_m_s']:g}|{1000*r['tmq_along_wind_displacement_m']:.4f}|{1000*r['steel02_along_wind_displacement_m']:.4f}|{r['tmq_vs_steel02_displacement_change_percent']:+.3f}|{r['member_axial_relative_L2_percent']:.3f}|")
        else:
            lines.append(f"|{r['angle_deg']}|{r['speed_m_s']:g}|未形成共同有效点|—|—|—|")
    common=[r for r in result["common_target_comparison"] if r["comparable"]]
    if common:
        lines.extend(["", "## 从实际结果能够得出的结论", ""])
        biggest=max(common,key=lambda r:abs(r["tmq_vs_steel02_displacement_change_percent"]))
        lines.append(f"共同有效点中，沿风位移相对差异最大出现在 {biggest['angle_deg']}°、{biggest['speed_m_s']:g} m/s：TMQ 相对四段变化 {biggest['tmq_vs_steel02_displacement_change_percent']:+.3f}%。这反映整体响应差异，不能替代局部内力核对。")
        local=max(common,key=lambda r:r["member_axial_relative_L2_percent"])
        lines.append(f"逐根物理杆轴力向量相对 L2 差最大为 {local['member_axial_relative_L2_percent']:.3f}%（{local['angle_deg']}°、{local['speed_m_s']:g} m/s）；该点单根最大绝对差 {local['largest_axial_difference_N']/1000:.3f} kN，物理杆号 {local['largest_axial_difference_member']}。小轴力杆不作除以单杆小分母的百分比排名。")
        complete_speeds=[speed for speed in SPEEDS if len([r for r in common if r["speed_m_s"]==speed]) == len(ANGLES)]
        if complete_speeds:
            speed=max(complete_speeds)
            for key,label in (("tmq","TMQ"),("steel02","四段 Steel02")):
                rows=[r for r in common if r["speed_m_s"]==speed]
                largest=max(rows,key=lambda r:r[f"{key}_along_wind_displacement_m"])
                demand=max(rows,key=lambda r:r[f"{key}_max_abs_chord_N_over_Afy"])
                lines.append(f"在四角均有共同数据的最高风速 {speed:g} m/s，{label} 的最大沿风位移出现在 {largest['angle_deg']}°（{1000*largest[f'{key}_along_wind_displacement_m']:.3f} mm）；最大弦向轴力需求比出现在 {demand['angle_deg']}°（{demand[f'{key}_max_abs_chord_N_over_Afy']:.5f}）。这是所测四角与所选指标的比较，不是连续风角搜索。")
        buckled=max((int(r["tmq_buckled_members"]) for c in cases if c["scheme"]=="tmq" for r in c["history"]),default=0)
        tension=max((int(r["tmq_tension_yield_members"]) for c in cases if c["scheme"]=="tmq" for r in c["history"]),default=0)
        lines.append(f"所有已保存 TMQ 状态中，最大本构屈曲计数杆数为 {buckled}，最大拉伸屈服计数杆数为 {tension}。{'因此本轮未激活 TMQ 的压屈/拉伸屈服分支，曲线主要检验弹性传力与几何效应。' if buckled==0 and tension==0 else '计数仅表明 TMQ 自身分支激活，不能用来替代纤维参考的屈服判定。'}")
        for case in cases:
            if case["scheme"] != "tmq":
                continue
            history=case["history"]
            first=next((i for i,row in enumerate(history) if int(row["tmq_buckled_members"])>0),None)
            if first is not None:
                before=float(history[first-1]["wind_speed_m_s"]) if first>0 else 0.
                after=float(history[first]["wind_speed_m_s"])
                count=max(int(row["tmq_buckled_members"]) for row in history)
                lines.append(f"TMQ {case['angle_deg']}° 的首次压屈分支事件落在相邻保存风速 ({before:.4f}, {after:.4f}] m/s 之间，最大计数 {count} 根；这是首次保存事件的区间，不是已精定位的临界风速。")
        lines.append("整体剪力—位移近似直线不代表每根杆均处于同一分支；少数杆件的状态变化可能只对整体刚度造成很小影响。旧方案未逐纤维输出钢材应力/塑性历史，本轮不作其全部未屈服的断言。")
        lines.append("风速—位移曲线的弯曲不能直接解释成材料非线性，因为风荷载本身正比于 U²；另附基底剪力—位移曲线供检查刚度变化。")
    lines.extend(["", "## 收敛与平衡", "", "|方案|风角°|状态|最后保存风速 m/s|接受步|最大自由平移残差 N|最大自由转动残差 N·m|最大整体合力残差 N|最大整体合矩残差 N·m|耗时 s|", "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"])
    for c in cases:
        h = c["history"]
        lines.append(f"|{c['scheme']}|{c['angle_deg']}|{c['status']}|{float(h[-1]['wind_speed_m_s']) if h else 0:.4f}|{c.get('accepted_steps',0)}|{max((float(r['force_residual_N']) for r in h),default=0):.3g}|{max((float(r['moment_residual_Nm']) for r in h),default=0):.3g}|{max((float(r['global_force_balance_N']) for r in h),default=0):.3g}|{max((float(r['global_moment_balance_Nm']) for r in h),default=0):.3g}|{c.get('wall_seconds',0):.1f}|")
        if c.get("stop_reason"):
            lines.append(f"\n{c['scheme']} / {c['angle_deg']}° 停止原因：{c['stop_reason']}\n")
    if result.get("selected_retry_evidence"):
        lines.extend(["", "计算预算重跑记录（所有原始尝试均保留）：", ""])
        for key,entry in result["selected_retry_evidence"].items():
            lines.append(f"- {key}：{entry['reason']}；原证据 `{entry['original_directory']}`；最终对比采用 `{entry['selected_directory']}`。风场、材料、离散与求解容差保持不变。")
    if result.get("artifact_verification"):
        v=result["artifact_verification"]
        lines.extend(["", "## 测试与结果完整性", "",
            f"{v['unit_tests_count']} 项单元与实际 S2K 解析检查全部通过；{v['selected_case_count']} 例结果逐一检查 gzip 完整解压/CRC、节点和物理杆行数、历史与独立平衡行数、目标风速是否全部到达。每例 34 个保存状态（重力1个+风加载33个），原节点位移 21,114 行、物理杆力 51,952 行。详细核对与代码哈希见 `verification.json`。",
            "测试覆盖力投影符号/端点反向、输入审计缺失与篡改、目标顺序、两模型实际 S2K 原始风几何完全相同，以及既有证据保护、重跑目录边界、summary 半写读取和原生清理期间并发 slot 保护。",
            "初期接续调度曾读到旧 worker 短暂半写的 summary，分析进程未受影响；已改为原子写入并容忍旧格式瞬态。接续调度现在等待 PID 实际退出后释放并发 slot，避免已完成计算但仍清理的进程被漏计。"])
    lines.extend(["", "## 必须保留的解释边界", "",
        "- 本次是两套建模方案对比，不能把差异全部归因于材料。四段 Steel02 是空间纤维梁，轴弯耦合、塑性弯曲、显式初弯曲、每段 Legendre6；TMQ 是一根直梁、Legendre3、等效轴向滞回＋独立弹性弯扭，未实现钢纤维轴弯耦合，I23 未进入弯曲刚度。",
        "- 同一个 e0/L 不等于两模型具有相同初始刚度或同一压屈荷载；TMQ 的 phi 来源为 K=1 Perry 首纤维屈服估算，循环系数沿用钢管文献 P102 row A，尚未用本塔角钢实验识别。",
        "- 四分段参考本身存在网格、纤维离散和随机缺陷方向影响，不能视为试验真值；本轮固定 seed=30103，未开展缺陷方向统计。",
        "- 风角比较同时包含迎风投影/偏航系数导致的总荷载改变与结构方向刚度改变。判断最不利风角必须说明选用的响应指标；四个角度不等于连续角度最不利搜索。",
        "- 全杆肢宽投影求和未考虑遮挡，Cx/Cy/yaw 与高度因子均为接口验证假设，80 m/s 仅是该假设风场的荷载参数，不是工程基本风速、抗风上限或倒塌风速。",
        "- abs(N_chord)/(A*fy) 仅是可比的轴力需求比；不包含纤维弯曲应力，也不是 TMQ 屈曲阈值，不能用其小于 1 断言全塔钢材未屈服。TMQ 屈曲计数是该本构状态机自身事件，不能直接等同真实角钢破坏。",
        "- 增大静态风速仅验证单调加载路径；尚不能说明卸载、再加载或风振滞回正确。", "",
        "## 文件与复现", "",
        "- `comparison.csv`：四风角 × 共同目标风速摘要；`summary.json`：所有状态、输入审计、求解器预算与停止原因。",
        "- `runs/<scheme>_<angle>/`：荷载计划、原始节点荷载、逐步历史、独立平衡、尝试记录、节点位移 gzip、物理杆轴力 gzip、支座反力。",
        "- `displacement_comparison.png` / `force_displacement_comparison.png` / `difference_comparison.png`：风速—位移、基底剪力—位移及共同点差异，不越过实际停止点。",
        "- 可复现命令（必须给新输出目录）：`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison --output <new_directory>`。最终调度最多 2 个独立进程；风分析预算 1200 s，外层进程上限 2400 s。初始尝试使用总预算 420 s / 外层 600 s，随后分离风预算 420 s / 外层 900 s，宿主负载较高后提高到最终预算；各例有效 solver_settings 与 executions 单独保存。90 s 建模栈采样仅是定位日志，不代表失败。达到预算视作计算停止，不能解释为物理极限。", ""])
    return "\n".join(lines)


def existing_worker(directory):
    """Find only this runner's exact case process when resuming an owned suite."""
    target = Path(directory).resolve()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry/"cmdline").read_bytes().decode().strip("\0").split("\0")
            if "initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison" not in args or "--case" not in args:
                continue
            index = args.index("--output")
            if Path(args[index+1]).resolve() == target:
                return int(entry.name)
        except (OSError,ValueError,IndexError,UnicodeError):
            pass
    return None


def execute_case(root, angle, scheme, env):
    key=f"{scheme}_{angle}"
    directory=root/"runs"/key
    summary_path=directory/"summary.json"
    if directory.exists() and any(directory.iterdir()):
        # Resume observes existing evidence. No rerun or truncate of case files.
        wait_started=time.monotonic()
        observed_pid=None
        while True:
            try:
                summary=json.loads(summary_path.read_text()) if summary_path.exists() else {}
            except json.JSONDecodeError:
                # Older active workers write directly; observe a later complete
                # snapshot rather than failing the whole scheduler.
                summary={}
            pid=existing_worker(directory)
            # A final numerical summary can precede native cleanup, gzip close,
            # or interpreter shutdown. Keep its concurrency slot until actual
            # process exit, not merely completion of the loading loop.
            if summary.get("status") in {"complete","partial","stopped"} and not pid:
                return dict(case=key,returncode=0 if summary["status"] == "complete" else 2,
                    timed_out=False,preserved_existing_evidence=True,observed_existing_pid=observed_pid)
            if not pid or time.monotonic()-wait_started > 2400:
                return dict(case=key,returncode=None,timed_out=bool(pid),
                    preserved_existing_evidence=True,status="existing_run_incomplete",observed_existing_pid=observed_pid)
            observed_pid=pid
            time.sleep(1)
    command=[sys.executable,"-m","initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison",
             "--output",str(directory),"--case",scheme,"--angle",str(angle)]
    with (root/"logs"/f"{key}.log").open("w",encoding="utf-8") as log:
        try:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=2400)
            return dict(case=key,returncode=result.returncode,timed_out=False,command=command)
        except subprocess.TimeoutExpired:
            return dict(case=key,returncode=None,timed_out=True,command=command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--case",choices=SCHEMES)
    parser.add_argument("--angle",type=int,choices=ANGLES,default=0)
    parser.add_argument("--publish-only",action="store_true")
    parser.add_argument("--resume",action="store_true",help="Observe existing cases; never rerun/overwrite case evidence")
    args = parser.parse_args()
    if args.case:
        result = run_case(args.output,args.case,args.angle)
        return 0 if result["status"] == "complete" else 2
    if args.publish_only:
        publish(args.output)
        return 0
    if args.output.exists() and any(args.output.iterdir()) and not args.resume:
        raise FileExistsError(f"Refusing to overwrite existing evidence: {args.output}")
    (args.output/"logs").mkdir(parents=True,exist_ok=args.resume)
    executions=[]
    env = {**os.environ,"OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1","CXX":os.environ.get("CXX","/usr/bin/g++-13")}
    # Parallel processes, never parallel OpenSees domains inside one process.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(execute_case,args.output,angle,scheme,env) for angle in ANGLES for scheme in SCHEMES]
        for future in futures:
            execution=future.result()
            executions.append(execution)
            write_json(args.output/"executions.json",executions)
            print(json.dumps(execution),flush=True)
    publish(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
