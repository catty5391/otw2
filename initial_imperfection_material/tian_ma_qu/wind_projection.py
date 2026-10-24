"""Offline wind-load projection and static modal truncation of saved modal cases.

No OpenSees domain, eigen solve, or new finite-element state is created here.
The reference is a linear solve of the saved gravity-tangent K. Forces retain
the historical 20 m/s *uncalibrated* reference pattern; these are tangent
sensitivities, not a newly equilibrated 20 m/s nonlinear wind state.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.sparse import load_npz
from scipy.sparse.linalg import splu

from util.processing.conductor_directional_wind import (
    ConductorAerodynamics, explicit_conductor_loads, combine_conductor_loads,
)
from util.processing.directional_wind import merge_nodal_loads, nodal_resultant
from util.processing.tower_directional_wind import (
    PROXY_AREA_BASIS, TowerWindGeometry, TowerWindMember, TowerWindCoefficients,
    build_tower_wind_load,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path(__file__).resolve().parent
CASE_KEYS = ("bare_checked", "coupled_20_checked", "coupled_40_checked", "coupled_80_checked")
ANGLES = (0, 45, 90)
CUTOFFS_HZ = (.5, 1., 2., 2.7, 3.)
RELATIVE_TOLERANCE = .02
ABSOLUTE_DISPLACEMENT_TOLERANCE_M = 1e-6
SOURCE_SPEED = 20.
HEIGHT_EDGES = (0., 3.2, 6.8, 9., 13.2, 17.4, 21.6, 24., 27., 30., 33., 36.4, 39.6)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        raise ValueError("cannot silently publish an empty table")
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def fingerprint(path):
    path = Path(path)
    return {"path":str(path.relative_to(ROOT)), "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes":path.stat().st_size}


def validate_mapping(node_tags, node_dofs, number_equations):
    """This saved-data adapter supports unique unconstrained equation mapping.

    A general MP-constraint model needs its transformation matrix; silently
    adding duplicate equation IDs would incorrectly handle its applied forces.
    """
    tags, dofs = np.asarray(node_tags), np.asarray(node_dofs)
    if tags.ndim != 1 or len(set(tags.tolist())) != len(tags):
        raise ValueError("node tags must be unique one-dimensional values")
    if dofs.shape != (len(tags), 6) or not np.issubdtype(dofs.dtype, np.integer):
        raise ValueError("node_dofs must be integer nodes x 6")
    free = dofs[dofs >= 0]
    if np.any(dofs < -1) or len(free) != number_equations or not np.array_equal(np.sort(free), np.arange(number_equations)):
        raise ValueError("equation map must cover unique free DOFs exactly; MP maps require a transformation")
    return {int(tag):i for i,tag in enumerate(tags)}


def map_loads(loads, node_tags, node_dofs, number_equations):
    index = validate_mapping(node_tags, node_dofs, number_equations)
    nodal = np.zeros((len(node_tags), 6))
    for tag, vector in loads.items():
        if int(tag) not in index:
            raise ValueError(f"unknown loaded node {tag}")
        vector = np.asarray(vector, float)
        if vector.shape != (6,) or not np.isfinite(vector).all():
            raise ValueError("loads require six finite components")
        nodal[index[int(tag)]] = vector
    free = np.zeros(number_equations)
    mask = node_dofs >= 0
    free[node_dofs[mask]] = nodal[mask]
    return free, nodal, np.where(mask, 0., nodal)


def mass_normalize(vectors, mass_matrix):
    vectors = np.asarray(vectors, float)
    if vectors.ndim != 2 or vectors.shape[0] != mass_matrix.shape[0] or not np.isfinite(vectors).all():
        raise ValueError("finite free-equation mode columns required")
    generalized_mass = np.sum(vectors * (mass_matrix @ vectors), axis=0)
    if np.any(generalized_mass <= 0) or not np.isfinite(generalized_mass).all():
        raise ValueError("positive generalized mass required for every mode")
    normalized = vectors / np.sqrt(generalized_mass)
    error = float(np.max(np.abs(normalized.T @ (mass_matrix @ normalized)-np.eye(vectors.shape[1]))))
    if error > 1e-6:
        raise ValueError(f"saved modes fail mass orthogonality: {error}")
    return normalized, error


def project_static(vectors, eigenvalues, force, selection):
    values = np.asarray(eigenvalues, float)
    if values.shape != (vectors.shape[1],) or np.any(values <= 0) or not np.isfinite(values).all():
        raise ValueError("positive finite eigenvalues matching modal columns required")
    q = vectors.T @ force
    indices = np.asarray(selection, dtype=int)
    if indices.size and (np.min(indices) < 0 or np.max(indices) >= len(values)):
        raise ValueError("mode selection outside saved modes")
    if len(np.unique(indices)) != len(indices):
        raise ValueError("duplicate mode selections are not allowed")
    return q, vectors[:,indices] @ (q[indices] / values[indices])


def output_error(reference, approximation, *, relative_tolerance=RELATIVE_TOLERANCE,
                 absolute_tolerance=ABSOLUTE_DISPLACEMENT_TOLERANCE_M):
    if not all(math.isfinite(v) for v in (reference, approximation)):
        raise ValueError("finite output values required")
    absolute = abs(approximation-reference)
    # Near-zero threshold follows the frozen crossover of the two error limits.
    near_zero = abs(reference) <= absolute_tolerance / relative_tolerance
    tolerance = max(absolute_tolerance, relative_tolerance * abs(reference))
    return {"absolute_error_m":absolute,
            "relative_error":None if near_zero else absolute/abs(reference),
            "near_zero_reference":near_zero,"error_tolerance_m":tolerance,"passed":absolute<=tolerance}


def tower_geometry(run, data):
    coords = {int(tag):tuple(x) for tag,x in zip(data["node_tags"],data["initial_coordinates"])}
    members = []
    for row in read_csv(run/"model_data/elements.csv"):
        match = re.fullmatch(r"L([0-9.]+)[x×]([0-9.]+)Q[0-9]+", row["section_name"])
        if not match:
            raise ValueError(f"unsupported proxy section {row['section_name']}")
        leg = float(match.group(1)) / 1000
        a,b = int(row["node_i"]),int(row["node_j"])
        dx,dy,dz = np.asarray(coords[b])-coords[a]
        members.append(TowerWindMember(int(row["element_tag"]),a,b,leg*math.hypot(dy,dz),
            leg*math.hypot(dx,dz),section_name=row["section_name"]))
    return TowerWindGeometry(coords,tuple(members),(0.,0.,0.),PROXY_AREA_BASIS,
        "same historical all-member equal-angle leg-breadth proxy; no shielding/calibration")


def line_records(run):
    path = run/"line_model/transmission_lines.csv"
    if not path.exists():return []
    records=[]
    for row in read_csv(path):
        records.append({"line_id":row["line_id"],"node_tags":ast.literal_eval(row["node_tags"]),
                        "conductor":ast.literal_eval(row["conductor"])})
    return records


def build_saved_loads(run, data, angle):
    """Rebuild each grid on its own saved coordinates without any FE calls."""
    tower=build_tower_wind_load(tower_geometry(run,data),wind_angle_deg=angle,
        reference_pressure_pa=.5*1.225*SOURCE_SPEED**2,height_edges_m=HEIGHT_EDGES,
        height_factors=[1.]*(len(HEIGHT_EDGES)-1),height_factor_provenance="historical uniform verification field",
        coefficients=TowerWindCoefficients(1.,1.,.2,"historical uncalibrated verification coefficients"))
    coords={int(n):tuple(x) for n,x in zip(data["node_tags"],data["gravity_coordinates"])}
    lines=[]
    for row in line_records(run):
        c=row["conductor"]
        lines.append(explicit_conductor_loads(row["line_id"],row["node_tags"],
            [coords[tag] for tag in row["node_tags"]],wind_speed_m_s=SOURCE_SPEED,wind_angle_deg=angle,
            aerodynamics=ConductorAerodynamics(c["diameter_m"],1.,1.225,c["bundle_count"])))
    line_loads=combine_conductor_loads(*lines).nodal_forces if lines else {}
    components={"tower":tower.applied_loads,"combined":merge_nodal_loads(tower.applied_loads,line_loads)}
    if lines:components["conductors"]=line_loads
    return components,{"tower":tower.summary,"conductors":[line.audit() for line in lines]}


def observation_rows(run, data, angle):
    tags=data["node_tags"];index={int(n):i for i,n in enumerate(tags)}
    points={"control_350":350}
    for row in line_records(run):
        ns=row["node_tags"]
        points[f"attachment_{ns[0]}"]=ns[0]
        points[f"midspan_{row['line_id']}"]=ns[len(ns)//2]
    c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
    directions={"X":(1.,0.,0.),"Y":(0.,1.,0.),"Z":(0.,0.,1.),"along":(c,s,0.),"cross":(-s,c,0.)}
    result=[]
    for name,tag in points.items():
        if tag not in index:raise ValueError(f"missing observation node {tag}")
        for direction,weights in directions.items():
            result.append({"name":name,"node_tag":tag,"node_index":index[tag],"direction":direction,
                           "weights":weights,"group":"control" if name=="control_350" else
                           "attachment" if name.startswith("attachment") else "midspan"})
    return result


def extract_output(vector, observer, dofs):
    value=0.
    for d,weight in enumerate(observer["weights"]):
        equation=dofs[observer["node_index"],d]
        if equation>=0:value+=weight*vector[equation]
    return float(value)


def force_balance_check(audit):
    tower=audit["tower"]
    checks=[]
    for force,moment,target_f,target_m in [(tower["force_residual_N"],tower["moment_residual_Nm"],
            tower["target_force_N"],tower["target_moment_Nm"])]+[
            (a["force_residual_n"],a["moment_residual_nm"],a["target_force_n"],a["target_moment_nm"])
            for a in audit["conductors"]]:
        fe=float(max(abs(x) for x in force));me=float(max(abs(x) for x in moment))
        ft=max(1e-6,1e-10*max(abs(x) for x in target_f));mt=max(1e-6,1e-10*max(abs(x) for x in target_m))
        checks.append({"force_residual_max_N":fe,"moment_residual_max_Nm":me,"passed":fe<=ft and me<=mt})
    return checks


def run(output, *, source=MODULE/"modal_results/runs"):
    started=time.monotonic();output=Path(output);source=Path(source)
    if output.exists() and any(output.iterdir()):raise FileExistsError(output)
    output.mkdir(parents=True,exist_ok=True)
    frozen={"schema":"otw2.wind_projection_config.v1","case_keys":CASE_KEYS,"angles_deg":ANGLES,
        "mode_count_requests":[40,80,120,160],"common_cutoffs_Hz":CUTOFFS_HZ,
        "static_displacement_relative_tolerance":RELATIVE_TOLERANCE,
        "static_displacement_absolute_tolerance_m":ABSOLUTE_DISPLACEMENT_TOLERANCE_M,
        "near_zero_crossover_m":ABSOLUTE_DISPLACEMENT_TOLERANCE_M/RELATIVE_TOLERANCE,
        "error_rule":"abs(approx-reference)<=max(1e-6 m,0.02 abs(reference)); near-zero relative errors are null",
        "candidate_band_Hz":[0.,3.],"wind_reference_speed_m_s":SOURCE_SPEED,
        "meaning":"linear sensitivity of saved gravity equilibrium to historical uniform uncalibrated reference wind pattern",
        "new_FE_runs":0,"eigen_solves":0,"frozen_at_utc":datetime.now(timezone.utc).isoformat()}
    write_json(output/"config.json",frozen)
    all_sources=[Path(__file__),ROOT/"util/processing/tower_directional_wind.py",ROOT/"util/processing/conductor_directional_wind.py",
        ROOT/"util/processing/directional_wind.py"]
    qrows=[];observations=[];static_rows=[];load_rows=[];ledgers=[];cases={};direct_rows=[];map_audits=[]
    for key in CASE_KEYS:
        print(f"Offline projection: {key}",flush=True)
        run_path=source/key
        paths=[run_path/n for n in ["eigenvectors.npz","equation_modes.npz","stiffness.npz","mass.npz","summary.json","model_data/elements.csv"]]
        if (run_path/"line_model/transmission_lines.csv").exists():paths.append(run_path/"line_model/transmission_lines.csv")
        all_sources.extend(paths)
        data=dict(np.load(run_path/"eigenvectors.npz"));equations=dict(np.load(run_path/"equation_modes.npz"))
        K=load_npz(run_path/"stiffness.npz").tocsc();M=load_npz(run_path/"mass.npz").tocsr()
        dofs=equations["node_dofs"];tags=equations["node_tags"]
        if not np.array_equal(tags,data["node_tags"]):raise ValueError("node order differs between saved equation and nodal arrays")
        validate_mapping(tags,dofs,K.shape[0])
        if not np.array_equal(dofs<0,data["fixed"]):raise ValueError("fixed DOFs disagree with saved constraints")
        phi,orthogonality=mass_normalize(equations["vectors"],M)
        lambdas=equations["values"];freq=np.sqrt(lambdas)/(2*math.pi)
        if not np.isfinite(K.data).all() or not np.isfinite(M.data).all():raise ValueError("nonfinite matrix")
        if freq[-1]<max(CUTOFFS_HZ):raise ValueError("case does not cover frozen common frequency band")
        lu=splu(K)
        zero_mass=np.flatnonzero(M.diagonal()==0.)
        zlu=splu(K[zero_mass,:][:,zero_mass].tocsc()) if len(zero_mass) else None
        truncations=[(f"first_{n}",np.arange(n)) for n in sorted(set([min(n,len(lambdas)) for n in (40,80,120,160)]))]
        truncations += [(f"cutoff_{f:g}_Hz",np.flatnonzero(freq<=f)) for f in CUTOFFS_HZ]
        info=read_json(run_path/"summary.json")
        cases[key]={"segments_per_span":info["segments_per_span"],"saved_modes":len(lambdas),"highest_frequency_Hz":float(freq[-1]),
            "free_equations":K.shape[0],"zero_mass_equations":len(zero_mass),"M_orthogonality_error":orthogonality,
            "free_mass_XYZ_kg":info["free_mass_XYZ_kg"],"all_saved_modes_static_output_summary":[],
            "load_audits_passed":True,"direct_linear_solve_relative_residual_max":0.,"zero_mass_load_response_max":0.}
        for angle in ANGLES:
            components,audit=build_saved_loads(run_path,data,angle)
            checks=force_balance_check(audit)
            if not all(v["passed"] for v in checks):raise ValueError("distributed/nodal force or moment mismatch")
            map_audits.append({"case":key,"angle_deg":angle,"distributed_to_nodal_checks":checks})
            # Same-grid historical crosscheck of a separately stored load plan.
            if key in {"bare_checked","coupled_20_checked"}:
                oldkey=f"{'single' if key=='bare_checked' else 'tower_line'}_{angle}"
                oldpath=MODULE/"wind_speed_results/runs"/oldkey/"wind_load_plan.json"
                old=read_json(oldpath);all_sources.append(oldpath)
                oldloads={int(k):v for k,v in old["tower"]["applied_loads"].items()}
                for line in old["conductors"]:
                    oldloads=merge_nodal_loads(oldloads,{int(k):v for k,v in line["nodal_loads_n_nm"].items()})
                errors=[max(abs(a-b) for a,b in zip(components["combined"].get(n,(0.,)*6),oldloads.get(n,(0.,)*6)))
                        for n in set(components["combined"])|set(oldloads)]
                comparison={"case":key,"angle_deg":angle,"saved_plan":str(oldpath.relative_to(ROOT)),
                    "maximum_nodal_component_difference":float(max(errors)),"passed":max(errors)<=1e-6}
                map_audits[-1]["same_grid_historical_load_reconstruction"]=comparison
                if not comparison["passed"]:raise ValueError(f"saved load mismatch: {comparison}")
            observers=observation_rows(run_path,data,angle)
            coords={int(n):tuple(x) for n,x in zip(tags,data["gravity_coordinates"])}
            for component,loads in components.items():
                F,nodal,constrained=map_loads(loads,tags,dofs,K.shape[0])
                direct=lu.solve(F)
                residual=float(np.linalg.norm(K@direct-F)/(np.linalg.norm(K@direct)+np.linalg.norm(F)))
                if residual>1e-8:raise ValueError(f"saved K direct solve residual {residual}")
                cases[key]["direct_linear_solve_relative_residual_max"]=max(cases[key]["direct_linear_solve_relative_residual_max"],residual)
                massless_only=np.zeros_like(F)
                if zlu:massless_only[zero_mass]=zlu.solve(F[zero_mass])
                cases[key]["zero_mass_load_response_max"]=max(cases[key]["zero_mass_load_response_max"],float(np.max(np.abs(massless_only))))
                free_nodal=np.where(dofs>=0,nodal,0.)
                ledger={"case":key,"angle_deg":angle,"component":component,
                    "total_gravity_coordinate_resultant":nodal_resultant(coords,loads),
                    "free_load_resultant":nodal_resultant(coords,{int(n):tuple(v) for n,v in zip(tags,free_nodal)}),
                    "fixed_load_resultant":nodal_resultant(coords,{int(n):tuple(v) for n,v in zip(tags,constrained)}),
                    "fixed_load_role":"external load ledger only; excluded from free modal forcing",
                    "direct_solve_relative_residual":residual,"massless_DOF_load_norm":float(np.linalg.norm(F[zero_mass])),
                    "massless_direct_static_part_max":float(np.max(np.abs(massless_only)))}
                ledgers.append(ledger)
                for tag,values,con in zip(tags,nodal,constrained):
                    if np.any(values):load_rows.append({"case":key,"angle_deg":angle,"component":component,"node_tag":int(tag),
                        **dict(zip(("Fx_N","Fy_N","Fz_N","Mx_Nm","My_Nm","Mz_Nm"),map(float,values))),
                        "fixed_Fx_N":float(con[0]),"fixed_Fy_N":float(con[1]),"fixed_Fz_N":float(con[2])})
                q=phi.T@F
                for j in range(len(lambdas)):
                    qrows.append({"case":key,"angle_deg":angle,"component":component,"mode":j+1,"frequency_Hz":float(freq[j]),
                        "generalized_force_mass_normalized":float(q[j]),"modal_static_amplitude":float(q[j]/lambdas[j])})
                reference_values={ (o["name"],o["direction"]):extract_output(direct,o,dofs) for o in observers}
                for o in observers:
                    direct_rows.append({"case":key,"segments_per_span":info["segments_per_span"],"angle_deg":angle,"component":component,
                        "point":o["name"],"node_tag":o["node_tag"],"direction":o["direction"],"group":o["group"],
                        "linear_tangent_displacement_m":reference_values[o["name"],o["direction"]]})
                for label,selection in truncations:
                    _,approx=project_static(phi,lambdas,F,selection)
                    compliance=float(F@direct);approx_compliance=float(F@approx)
                    group_results={g:[] for g in ("control","attachment","midspan")}
                    for o in observers:
                        reference=reference_values[o["name"],o["direction"]];predicted=extract_output(approx,o,dofs)
                        e=output_error(reference,predicted);group_results[o["group"]].append(e)
                        observations.append({"case":key,"angle_deg":angle,"component":component,"truncation":label,
                            "retained_modes":len(selection),"point":o["name"],"node_tag":o["node_tag"],"direction":o["direction"],"group":o["group"],
                            "direct_m":reference,"modal_m":predicted,"residual_static_m":reference-predicted,
                            "static_residual_corrected_m":reference,**e})
                    row={"case":key,"angle_deg":angle,"component":component,"truncation":label,"retained_modes":len(selection),
                        "highest_retained_frequency_Hz":float(freq[selection[-1]]) if len(selection) else 0.,
                        "direct_compliance_J":compliance,"modal_compliance_J":approx_compliance,
                        "compliance_relative_missing":float((compliance-approx_compliance)/compliance) if abs(compliance)>1e-14 else None,
                        "all_observed_outputs_passed":all(e["passed"] for es in group_results.values() for e in es)}
                    for group,errors in group_results.items():
                        row[f"{group}_outputs_count"]=len(errors)
                        row[f"{group}_passed"]=all(e["passed"] for e in errors) if errors else None
                        row[f"{group}_maximum_relative_error"]=max([e["relative_error"] for e in errors if e["relative_error"] is not None],default=None)
                        row[f"{group}_maximum_absolute_error_m"]=max([e["absolute_error_m"] for e in errors],default=None)
                    static_rows.append(row)
                    if label==f"first_{len(lambdas)}":cases[key]["all_saved_modes_static_output_summary"].append(row)
        del K,M,phi,lu,zlu,data,equations
    mesh_rows=compare_meshes(direct_rows)
    sources={str(p.resolve()):p for p in all_sources}
    write_json(output/"source_fingerprints.json",[fingerprint(p) for p in sources.values()])
    write_json(output/"load_ledger.json",ledgers);write_json(output/"load_audits.json",map_audits)
    write_csv(output/"nodal_loads.csv",load_rows);write_csv(output/"generalized_wind_loads.csv",qrows)
    write_csv(output/"static_observations.csv",observations);write_csv(output/"direct_static_observations.csv",direct_rows)
    write_csv(output/"truncation_summary.csv",static_rows);write_csv(output/"mesh_comparison.csv",mesh_rows)
    write_json(output/"static_truncation.json",{"schema":"otw2.static_truncation.v1","criteria":frozen,"rows":static_rows,
        "response_table":"static_observations.csv","comparison_scope":"gravity tangent static displacement only"})
    summary={"schema":"otw2.wind_projection.v1","execution_status":"complete","assessment":"limited",
        "physical_validation":"unvalidated","new_FE_runs":0,"eigen_solves":0,"direct_K_factorizations":len(CASE_KEYS),
        "case_count":len(CASE_KEYS),"reference_wind_speed_m_s":SOURCE_SPEED,"cases":cases,
        "all_distributed_load_audits_passed":all(all(a["passed"] for a in r["distributed_to_nodal_checks"]) for r in map_audits),
        "historical_same_grid_load_crosschecks":sum("same_grid_historical_load_reconstruction" in r for r in map_audits),
        "same_grid_load_crosschecks_passed":all(r.get("same_grid_historical_load_reconstruction",{}).get("passed",True) for r in map_audits),
        "criteria":frozen,"mesh_comparison":summarize_mesh(mesh_rows),
        "primary_outputs":primary_outputs(observations),
        "largest_linear_tangent_displacement_m":max(abs(r["linear_tangent_displacement_m"]) for r in direct_rows),
        "unsupported_outputs":{"base_and_remote_support_reactions":"saved K contains only free equations; constrained coupling/recovery operator absent",
            "member_end_forces":"no independently verified element force recovery matrix in saved state",
            "cable_tension":"no independently verified cable axial force recovery matrix; displacement convergence is not tension convergence"},
        "interpretation":["This is linear tangent compliance of the saved zero-wind gravity state, not a new nonlinear equilibrium.",
            "Residual static correction exactly reproduces the same direct static solution by construction; it is not independent validation or dynamic accuracy.",
            "Effective uniform-support-acceleration mass is not used as a wind participation percentage.",
            "All applied nodal moments are zero in these physical reference patterns; massless rotational DOFs remain in K and the eigenvectors.",
            "No frequency-response/time-history/damping validation performed; N06/N08 remain necessary."],
        "recommendations":recommendations(cases,mesh_rows),"runtime_seconds":time.monotonic()-started,
        "artifacts":{"truncation":"static_truncation.json","observations":"static_observations.csv","load_ledger":"load_ledger.json",
            "modal_loads":"generalized_wind_loads.csv","mesh":"mesh_comparison.csv","report":"REPORT.md"}}
    write_json(output/"summary.json",summary)
    plot_results(output,static_rows,qrows,mesh_rows)
    report(output,summary)
    write_json(output/"execution.json",{"command":sys.argv,"completed_at_utc":datetime.now(timezone.utc).isoformat(),
        "runtime_seconds":time.monotonic()-started,"new_FE_runs":0,"eigen_solves":0,
        "steps":["freeze cutoffs and tolerances before reading responses","read full saved matrices/modes/geometry",
            "rebuild own-grid tower and cable loads at 0/45/90 degrees","audit distributed and fixed/free load ledgers",
            "crosscheck six historical same-grid load plans","factor each saved K once and solve reference loads",
            "project modes and compare fixed counts/common frequency cutoffs","publish numerical tables and figures"]})
    return summary


def compare_meshes(rows):
    # Attachment tags differ only if topology changes. Stable physical labels
    # are mapped by the sorted attachment location ordinal, not raw tag equality.
    lookup={}
    for r in rows:
        point=r["point"]
        if point.startswith("attachment_"):
            # In this fixed two-attachment topology tags are shared, but use an
            # explicit ordinal to keep the comparison definition documented.
            tags=sorted({x["node_tag"] for x in rows if x["case"]==r["case"] and x["group"]=="attachment"})
            point=f"attachment_{tags.index(r['node_tag'])+1}"
        lookup[(r["case"],r["angle_deg"],r["component"],point,r["direction"])]=r
    comparisons=[]
    for coarse,fine in (("coupled_20_checked","coupled_40_checked"),("coupled_40_checked","coupled_80_checked")):
        for key,r in lookup.items():
            if key[0]!=coarse:continue
            target=lookup[(fine,*key[1:])]
            ref=target["linear_tangent_displacement_m"];value=r["linear_tangent_displacement_m"]
            comparisons.append({"coarse":coarse,"fine":fine,"angle_deg":key[1],"component":key[2],"point":key[3],"direction":key[4],"group":r["group"],
                "coarse_direct_m":value,"fine_direct_m":ref,**output_error(ref,value)})
    return comparisons


def summarize_mesh(rows):
    result=[]
    for coarse,fine in (("coupled_20_checked","coupled_40_checked"),("coupled_40_checked","coupled_80_checked")):
        selected=[r for r in rows if r["coarse"]==coarse and r["fine"]==fine]
        result.append({"coarse":coarse,"fine":fine,"outputs":len(selected),"passed_outputs":sum(r["passed"] for r in selected),
            "all_passed":all(r["passed"] for r in selected),"maximum_non_near_zero_relative_error":max(r["relative_error"] for r in selected if r["relative_error"] is not None),
            "maximum_absolute_error_m":max(r["absolute_error_m"] for r in selected)})
    return result


def recommendations(cases,mesh):
    return ["Use the direct saved-K compliance and output-specific truncation errors; a single mass-ratio target is insufficient.",
        "Expand the saved modal basis only for output/load combinations failing the frozen 2% or 1 micrometre static criterion; dynamic cutoffs require N06 frequency-response checks.",
        "Assess same-physical-load 40-to-80 displacement mesh errors before requesting 160 segments; static displacement adequacy does not certify cable tension or dynamic response.",
        "A finite-mode static residual correction is permissible as a labeled zero-frequency correction, not as proof that missing dynamic modes are unimportant."]


def primary_outputs(observations):
    """Keep main-direction and small transverse outputs separately auditable."""
    results=[]
    for row in observations:
        modes=20 if row["case"]=="bare_checked" else 160
        if row["truncation"]!=f"first_{modes}":continue
        if row["component"]!="combined" or row["group"] not in {"control","attachment"}:continue
        if row["direction"] not in {"X","Y","along","cross"}:continue
        results.append(row)
    return results


def plot_results(output,static_rows,qrows,mesh_rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False})
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout="constrained")
    for case,color in zip(CASE_KEYS,("C0","C1","C2","C3")):
        selected=[r for r in static_rows if r["case"]==case and r["angle_deg"]==45 and r["component"]=="combined" and r["truncation"].startswith("first_")]
        for ax,group in zip(axes,("control","midspan")):
            vals=[r for r in selected if r[f"{group}_maximum_relative_error"] is not None]
            if vals:ax.plot([r["retained_modes"] for r in vals],[100*r[f"{group}_maximum_relative_error"] for r in vals],"o-",color=color,label=case.replace("_checked",""))
            ax.axhline(2,color="black",ls="--",lw=.7);ax.set(xlabel="Retained modes",ylabel="Maximum non-near-zero output error (%)",title=f"45 deg combined load: {group}")
            ax.set_yscale("symlog",linthresh=.05);ax.grid(alpha=.2)
    axes[0].legend(fontsize=8)
    fig.suptitle("Static tangent reconstruction only; zero-reference outputs use 1 micrometre criterion")
    savefig(fig,output/"static_truncation");plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout="constrained")
    # Direct primary response and absolute residual shown together; avoid
    # conflating cancellation-dominated crosswind error with alongwind error.
    raw=read_csv(output/"static_observations.csv")
    for direction,color in (("along","C0"),("cross","C1")):
        selected=[r for r in raw if r["case"]=="coupled_80_checked" and r["component"]=="combined" and r["point"]=="control_350" and r["truncation"]=="first_160" and r["direction"]==direction]
        x=[float(r["angle_deg"]) for r in selected]
        axes[0].plot(x,[1000*float(r["direct_m"]) for r in selected],"o-",color=color,label=f"{direction}: direct saved K")
        axes[0].plot(x,[1000*float(r["modal_m"]) for r in selected],"s--",color=color,label=f"{direction}: 160 modes")
        axes[1].plot(x,[1000*float(r["absolute_error_m"]) for r in selected],"o-",color=color,label=direction)
    axes[0].set(ylabel="Linear tangent displacement (mm)",title="Control node 350: signed response")
    axes[1].set(ylabel="Absolute truncation error (mm)",title="Same physical 20 m/s reference-pattern amplitude")
    for ax in axes:ax.set_xlabel("Wind angle (degrees)");ax.set_xticks(ANGLES);ax.legend(fontsize=8);ax.grid(alpha=.2)
    fig.suptitle("80 segments: main alongwind response and small crosswind response kept separate")
    savefig(fig,output/"primary_static_response");plt.close(fig)
    fig,axes=plt.subplots(3,1,figsize=(11,8),layout="constrained",sharex=True)
    for ax,component in zip(axes,("tower","conductors","combined")):
        selected=[r for r in qrows if r["case"]=="coupled_80_checked" and r["angle_deg"]==45 and r["component"]==component]
        ax.stem([r["frequency_Hz"] for r in selected],[abs(r["generalized_force_mass_normalized"]) for r in selected],markerfmt=".",basefmt=" ")
        ax.set(title=component,ylabel="|Generalized force|\n(mass-normalized)");ax.grid(alpha=.2)
    axes[-1].set_xlabel("Frequency (Hz)");fig.suptitle("80 segments / 45 deg: actual spatial wind projection; not a wind participation ratio")
    savefig(fig,output/"generalized_wind_force");plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4.5),layout="constrained")
    positions=np.arange(3);width=.35
    for j,(coarse,label) in enumerate((("coupled_20_checked","20 to 40"),("coupled_40_checked","40 to 80"))):
        vals=[]
        for group in ("control","attachment","midspan"):
            selected=[r["relative_error"] for r in mesh_rows if r["coarse"]==coarse and r["component"]=="combined" and r["group"]==group and r["relative_error"] is not None]
            vals.append(100*max(selected))
        ax.bar(positions+j*width,vals,width,label=label)
    ax.axhline(2,color="black",ls="--",lw=.7);ax.set_xticks(positions+width/2,["Control node","Attachment","Cable midspan"])
    ax.set(ylabel="Maximum relative difference (%)",title="Direct saved-K static mesh comparison: combined loads, 0/45/90 deg")
    ax.legend();ax.grid(axis="y",alpha=.2);savefig(fig,output/"static_mesh_comparison");plt.close(fig)


def savefig(fig,path):
    for suffix in ("svg","png","pdf"):
        fig.savefig(path.with_suffix("."+suffix),dpi=180)


def report(output,s):
    lines=["# N03 实际风荷载投影与静态模态截断", "", "本次只对已保存的重力态矩阵和完整振型做后处理：新FE=0、特征值求解=0。",
        "参考解为保存K的线性扰动解；20 m/s只是沿用历史荷载形状的幅值单位，不是新求得的20 m/s非线性平衡。", "",
        "## 实施步骤", "", "1. 在计算前冻结0/45/90°、40/80/120/160阶及0.5/1/2/2.7/3 Hz公共截止频率。",
        "2. 各网格从自身原始塔杆/截面与重力后导线坐标重新组装荷载；没有复用20段节点号去加载80段。",
        "3. 核对分布荷载到节点的总力/总矩；固定端荷载单列，不进入自由方程广义力。",
        "4. 重建裸塔和20段的六份历史0/45/90°荷载计划，独立存量交叉核对。",
        "5. 每个保存K仅做一次稀疏LU，求三种方向及塔/线/组合加载静柔度；不修改质量、刚度。",
        "6. 质量归一化后计算Q=Phi.T F，与直接K解比较控制点、挂点和跨中的XYZ/沿横风位移。", "",
        "## 已有全部模态的结果", "", "误差判据：|差值|≤max(1 μm,参考位移绝对值的2%)。参考接近零时相对误差为null，仍检验绝对误差。", "",
        "| 工况 | 风向 | 荷载 | 控制点最大相对误差 | 跨中最大相对误差 | 全部观察位移通过 |",
        "|---|---:|---|---:|---:|---|"]
    def percent(v):return "不适用" if v is None else f"{100*v:.5g}%"
    for key,c in s["cases"].items():
        for r in c["all_saved_modes_static_output_summary"]:
            if r["component"]!="combined":continue
            lines.append(f"| {key} | {r['angle_deg']}° | 组合 | {percent(r['control_maximum_relative_error'])} | {percent(r['midspan_maximum_relative_error'])} | {r['all_observed_outputs_passed']} |")
    lines += ["", "## 80段模型主向位移与小横向位移分别看", "",
        "下表全部为combined参考荷载、160阶；绝对量用mm。45°横风位移是X/Y组合后的较小差值，大相对误差不能概括为沿风主响应同样误差。", "",
        "| 风向 | 观察点 | 方向 | 直接K解/mm | 160阶/mm | 绝对差/mm | 相对差 | 通过 |",
        "|---:|---|---|---:|---:|---:|---:|---|"]
    for r in s["primary_outputs"]:
        if r["case"]!="coupled_80_checked" or r["direction"] not in {"along","cross"}:continue
        lines.append(f"| {r['angle_deg']}° | {r['point']} | {r['direction']} | {1000*r['direct_m']:.8g} | {1000*r['modal_m']:.8g} | {1000*r['absolute_error_m']:.8g} | {percent(r['relative_error'])} | {r['passed']} |")
    lines += ["", "## 直接静柔度的空间网格比较", ""]
    for m in s["mesh_comparison"]:
        lines.append(f"- {m['coarse']}→{m['fine']}：{m['passed_outputs']}/{m['outputs']}项满足冻结门槛；非近零输出最大相对差{100*m['maximum_non_near_zero_relative_error']:.5g}%，最大绝对差{m['maximum_absolute_error_m']:.6g} m。")
    lines += ["", "## 能说明与不能说明的范围", "",
        "- 当前采用全部原始自由方程，包含无质量转动DOF；质量矩阵没有求逆、补小质量或做未声明凝聚。当前风荷载无节点力矩，无质量DOF的独立直接受载静态项为零；保留的静态残差仍包含未保存高阶模态的作用。",
        "- 静态残差修正 u_direct−u_modal 加回后精确恢复同一个直接解，这是构造恒等式，不是新的独立验证；不能据此认定动态截断足够。",
        "- 塔基/远端反力、杆端内力和线张力没有独立恢复算子，本轮为unsupported。保存K只含自由方程，不能补出未保存的约束耦合行。",
        "- 这些荷载的空间分布是历史均匀流原型，非空间相关随机风；本轮没有频响、阻尼或时程验证。",
        f"- 本批线性切线外推的最大观察位移为{s['largest_linear_tangent_displacement_m']:.6g}m；较大导线位移不代表这一风速的真实非线性平衡。所有误差是在同一重力态切线系统下的数值比较，可将荷载统一缩小后作为小扰动灵敏度使用。",
        "- 当前全部模态的静态位移是否合格必须逐工况/输出读取表，不能由累计有效质量或一个代表振型推断。", "",
        "## 下一步", "", "先按失败输出进行有界扩阶或静态残余修正评估，再在冻结候选C下做N06频响；网格加密依据直接静柔度和后续动态响应，反力/张力需独立恢复验证。所有判断仅为数值范围，物理适用性仍未验证。", "",
        "完整表：`static_observations.csv`、`truncation_summary.csv`、`mesh_comparison.csv`；源文件指纹：`source_fingerprints.json`。测试命令及结果由`validation/tests.log`与`verification.json`记录。"]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source",type=Path,default=MODULE/"modal_results/runs")
    args=parser.parse_args()
    result=run(args.output,source=args.source)
    print(json.dumps({"execution_status":result["execution_status"],"assessment":result["assessment"],
        "new_FE_runs":0,"runtime_seconds":result["runtime_seconds"]},ensure_ascii=False))


if __name__=="__main__":main()
