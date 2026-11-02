"""Bounded 20/40/80-segment static study of the uncalibrated tension-only V string.

The 20-segment evidence is read-only. Four fresh runs change only cable mesh.
All comparisons use common committed load factors; no extrapolation is allowed.
"""
from __future__ import annotations

import argparse
import ast
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import html
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import numpy as np

MODULE = Path(__file__).resolve().parent
ROOT = MODULE.parents[1]
BASELINE = MODULE / "followup_results/insulator_sensitivity_20261024"
DEFAULT_OUTPUT = MODULE / "followup_results/B2_20261024/insulator_grid"
SPEED_TARGETS = [20, 40, 45, 46, 50, 60, 64, 65, 66, 70, 80, 90, 100]
ANGLES = (0, 45)
GRIDS = (20, 40, 80)
KEY_MEMBERS = (877, 878, 825, 828, 917, 920)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        raise ValueError("No rows to publish")
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def freeze_plan(output):
    """Must run before any new FE; existing output is never silently reused."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    for name in ("configs", "logs", "runs"):
        (output/name).mkdir()
    protected = {}
    for angle in ANGLES:
        run = BASELINE/"runs"/f"tension_only_{angle}"
        for name in ("summary.json", "history.csv", "insulator_history.csv", "line_history.csv",
                     "wind_config.json", "wind_nodal_loads.csv", "line_model/effective_configuration.json"):
            path = run/name
            protected[str(path.relative_to(ROOT))] = sha256(path)
    baseline = json.loads((BASELINE/"runs/tension_only_0/summary.json").read_text())
    sources = {p:sha256(ROOT/p) for p in baseline["code_sha256"] | baseline["directional_input_sha256"]}
    # The pre-existing source-snapshot deepcopy correction changes metadata only.
    changed = {p: {"baseline":old,"current":sources[p]} for p,old in
               (baseline["code_sha256"] | baseline["directional_input_sha256"]).items() if old != sources[p]}
    plan = {"schema":"otw2.insulator_grid.plan.v1", "frozen_at_utc":datetime.now(timezone.utc).isoformat(),
            "physical_validation":"unvalidated", "actual_string_type_and_geometry_confirmed":False,
            "baseline_segments":20, "new_grids":[40,80], "angles_deg":list(ANGLES),
            "new_full_tower_case_budget":4, "external_timeout_seconds":900,
            "solver_timeout_seconds":600, "execution":"serial independent processes",
            "speed_targets_m_s":SPEED_TARGETS, "maximum_load_increment":.25,
            "minimum_load_increment":.0001, "material":"strict tension_only, compression ratio=0",
            "response_tolerance": {"relative":.02,"absolute_displacement_m":1e-4,"absolute_force_N":10.,
                                   "formula":"abs(coarse-fine) <= max(absolute_tolerance, 0.02*abs(fine))",
                                   "assessment_pair":[40,80], "diagnostic_pair":[20,40]},
            "input_tolerance":{"relative_mass_and_resultant":1e-4,
                               "absolute_force_N":.01,"absolute_moment_Nm":.1},
            "interpolation":"linear in load factor on union of common committed states; no extrapolation",
            "key_member_ids":list(KEY_MEMBERS), "protected_baseline_sha256":protected,
            "physical_source_sha256":sources,"declared_source_changes_since_baseline":changed,
            "source_change_note":"directional_loading deepcopy protects original snapshot; effective FE parameters unchanged; other differences require review",
            "not_established":["actual insulator calibration","ultimate wind speed","dynamic/time-step convergence"]}
    write_json(output/"frozen_plan.json", plan)
    (output/"FROZEN_PLAN.md").write_text("# 本批预先冻结的试验方案\n\n"
        "仅受拉绝缘子、0°/45°、每跨40/80段，共4次独立全塔静力；复用20段原记录。每例总时限900 s，求解时限600 s。\n"
        "荷载目标与增量、塔材、导线参数、挂点和质量定义保持原设置，网格变化带来的弧长与节点分担变化单列。\n"
        "在共同保存荷载倍率上逐点比较；40→80段建议相对差2%，近零位移用0.1 mm、近零力用10 N绝对限值；两者取较大值。\n"
        "输入总质量及合力/矩相对限值1e-4，近零力/矩绝对限值0.01 N/0.1 Nm。上述为本项目数值筛查标准，不是规范或物理标定。\n"
        "控制点、两个挂点XYZ/沿横风、四跨张力包络、四肢串力及预选六杆轴力均单列。部分/失败工况只比较共同范围。\n"
        "实际绝缘子型式和挂点尺寸尚未确认；100 m/s不是极限风速。详见frozen_plan.json及冻结时戳。\n")
    return plan


def run_cases(output):
    output=Path(output)
    plan=freeze_plan(output)
    allowed_change="initial_imperfection_material/tian_ma_qu/directional_loading.py"
    if set(plan["declared_source_changes_since_baseline"])-{allowed_change}:
        raise RuntimeError("Unreviewed physical source change since baseline")
    executions=[]
    for segments in (40,80):
        for angle in ANGLES:
            key=f"segments_{segments}_angle_{angle}"
            config=json.loads((BASELINE/"runs"/f"tension_only_{angle}"/"wind_config.json").read_text())
            config["line_segments"]=segments
            config_path=output/"configs"/f"{key}.json";write_json(config_path,config)
            command=[sys.executable,"-m","initial_imperfection_material.tian_ma_qu.full_tower",
                     "--output",str(output/"runs"/key),"--wind-config",str(config_path),"--control-dof","1",
                     "--record-nodes","--timeout","600","--maximum-load-increment",".25",
                     "--minimum-load-increment",".0001","--wind-speed-targets",*map(str,SPEED_TARGETS)]
            start=time.monotonic()
            with (output/"logs"/f"{key}.log").open("w") as log:
                try:
                    result=subprocess.run(command,cwd=ROOT,
                        env={**os.environ,"CXX":"/usr/bin/g++-13","OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1"},
                        stdout=log,stderr=subprocess.STDOUT,timeout=900)
                    code,timed_out=result.returncode,False
                except subprocess.TimeoutExpired:
                    code,timed_out=None,True
            record={"key":key,"segments":segments,"angle_deg":angle,"command":command,
                    "returncode":code,"external_timeout":timed_out,"elapsed_seconds":time.monotonic()-start}
            executions.append(record);write_json(output/"execution.json",executions)
            print(json.dumps({k:v for k,v in record.items() if k!="command"}),flush=True)
    return executions


def compare_value(coarse, fine, *, relative=.02, absolute=1e-4):
    if not all(math.isfinite(x) for x in (coarse,fine,relative,absolute)) or min(relative,absolute)<0:
        raise ValueError("Finite values and nonnegative tolerances required")
    difference=abs(coarse-fine);limit=max(absolute,relative*abs(fine))
    return {"absolute_difference":difference,"relative_difference":difference/abs(fine) if abs(fine)>1e-12 else None,
            "tolerance":limit,"normalized_error":difference/limit if limit else (0. if difference==0 else None),
            "passed":difference<=limit}


def interpolate(rows, factor, field):
    x=np.asarray([r["load_factor"] for r in rows],float); y=np.asarray([r[field] for r in rows],float)
    if len(x)<2 or not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(np.diff(x)<=0):
        raise ValueError("Finite strictly increasing load factors required")
    if not math.isfinite(factor) or factor<x[0]-1e-10 or factor>x[-1]+1e-10:
        raise ValueError("Cannot extrapolate outside recorded range")
    return float(np.interp(factor,x,y))


def collect_case(run, segments, angle):
    """Extract matched physical outputs, never comparing mesh-dependent node ids."""
    run=Path(run)
    summary=json.loads((run/"summary.json").read_text()) if (run/"summary.json").exists() else {}
    required=("history.csv","insulator_history.csv","line_history.csv","equilibrium.jsonl")
    if any(not (run/name).exists() for name in required):
        return {"segments":segments,"angle_deg":angle,"status":summary.get("status","failed_no_history"),
                "stop_reason":summary.get("stop_reason","required saved history missing"),"accepted_steps":0}, []
    history=read_csv(run/"history.csv")
    strings,lines={},{}
    for row in read_csv(run/"insulator_history.csv"):
        strings.setdefault(int(row["step"]),[]).append(row)
    for row in read_csv(run/"line_history.csv"):
        lines.setdefault(int(row["step"]),{}).setdefault(row["line_id"],[]).append(row)
    if not history or 0 not in strings:
        return {"segments":segments,"angle_deg":angle,"status":"failed_no_gravity","accepted_steps":0}, []
    names=sorted({r["insulator_id"] for r in strings[0]})
    if len(names)!=2:raise ValueError("Exactly two V strings required")
    gravity={r["insulator_id"]:[float(r[k]) for k in ("lower_ux_m","lower_uy_m","lower_uz_m")] for r in strings[0]}
    line_names=sorted(lines[0])
    if len(line_names)!=4:raise ValueError("Exactly four spans required")
    theta=math.radians(angle);c,s=math.cos(theta),math.sin(theta)
    member_forces={}
    with sqlite3.connect(f"file:{run/'internal_forces.sqlite'}?mode=ro",uri=True) as db:
        for step,tag,force in db.execute("SELECT step,element_tag,p_i FROM force_history WHERE element_tag IN ("+
                                       ",".join("?"*len(KEY_MEMBERS))+")",KEY_MEMBERS):
            member_forces.setdefault(step,{})[tag]=force
    rows=[];first_slack=None
    for record in history:
        step=int(record["step"])
        legs=strings.get(step,[]);spans=lines.get(step,{})
        if len(legs)!=4 or len({r["element_tag"] for r in legs})!=4 or set(spans)!=set(line_names):
            raise ValueError(f"Incomplete committed force state {run}, step {step}")
        if any(len(v)!=segments for v in spans.values()) or set(member_forces.get(step,{}))!=set(KEY_MEMBERS):
            raise ValueError("Cable or key-member history coverage missing")
        row={"segments":segments,"angle_deg":angle,"step":step,
             "load_factor":float(record["wind_load_factor"]),"speed_m_s":float(record["equivalent_wind_speed_m_s"]),
             "control_ux_m":float(record["ux_m"]),"control_uy_m":float(record["uy_m"]),
             "control_along_m":float(record["along_wind_displacement_m"]),
             "control_cross_m":-s*float(record["ux_m"])+c*float(record["uy_m"]),
             "tower_base_shear_N":float(record["along_wind_base_shear_N"])}
        for i,name in enumerate(names,1):
            pair=sorted((r for r in legs if r["insulator_id"]==name),key=lambda r:int(r["element_tag"]))
            if len(pair)!=2:raise ValueError("Missing V leg")
            xyz=[float(pair[0][k])-gravity[name][j] for j,k in enumerate(("lower_ux_m","lower_uy_m","lower_uz_m"))]
            for j,axis in enumerate(("x","y","z")):row[f"hanger{i}_u{axis}_m"]=xyz[j]
            row[f"hanger{i}_along_m"]=c*xyz[0]+s*xyz[1]
            row[f"hanger{i}_cross_m"]=-s*xyz[0]+c*xyz[1]
            for j,leg in enumerate(pair,1):row[f"string{i}_leg{j}_N"]=float(leg["axial_force_N"])
        for i,name in enumerate(line_names,1):
            ordered=sorted(spans[name],key=lambda r:int(r["element_tag"]))
            forces=[float(r["axial_force_N"]) for r in ordered]
            for label,value in (("minimum",min(forces)),("maximum",max(forces)),("hanger",forces[0]),("remote",forces[-1])):
                row[f"span{i}_{label}_N"]=value
        for tag,force in sorted(member_forces[step].items()):row[f"member{tag}_axial_i_N"]=force
        row["buckled_members"]=int(record["buckled_members"])
        row["tensile_yield_members"]=int(record["tensile_yield_members"])
        rows.append(row)
        if first_slack is None and any(r["state"]=="slack" for r in legs):
            first_slack={"step":step,"speed_bracket_m_s":[rows[-2]["speed_m_s"] if len(rows)>1 else 0.,row["speed_m_s"]]}
    equilibrium=[json.loads(line) for line in (run/"equilibrium.jsonl").read_text().splitlines()]
    if len(equilibrium)!=len(rows) or set(strings)!={r["step"] for r in rows}:
        raise ValueError("Committed histories and equilibrium coverage differ")
    legrows=[r for state in strings.values() for r in state]
    config=json.loads((run/"wind_config.json").read_text())
    effective=json.loads((run/"line_model/effective_configuration.json").read_text())
    effective_no_mesh=json.loads(json.dumps(effective))
    for v in effective_no_mesh["transmission_lines"].values():v.pop("n_seg")
    line_model=read_csv(run/"line_model/transmission_lines.csv")
    # Post-processing scope warning; this catalogue value is not a calibrated failure law.
    rated={r["line_id"]:ast.literal_eval(r["conductor"]).get("rated_tensile_strength_n") for r in line_model}
    strength_events=[]
    for i,name in enumerate(line_names,1):
        nominal=rated[name]
        first=next((j for j,r in enumerate(rows) if nominal and r[f"span{i}_maximum_N"]>nominal),None)
        strength_events.append({"span":name,"catalogue_rated_tensile_strength_N":nominal,
            "maximum_recorded_force_N":max(r[f"span{i}_maximum_N"] for r in rows),
            "maximum_force_to_catalogue_ratio":max(r[f"span{i}_maximum_N"] for r in rows)/nominal if nominal else None,
            "last_point_maximum_force_N":rows[-1][f"span{i}_maximum_N"],
            "last_point_force_to_catalogue_ratio":rows[-1][f"span{i}_maximum_N"]/nominal if nominal else None,
            "first_exceedance_speed_bracket_m_s":[rows[max(0,first-1)]["speed_m_s"],rows[first]["speed_m_s"]] if first is not None else None,
            "first_exceeding_elements":[{"element_tag":int(r["element_tag"]),"axial_force_N":float(r["axial_force_N"])}
                for r in lines[rows[first]["step"]][name] if float(r["axial_force_N"])>nominal] if first is not None else [],
            "calibrated_failure_event":False})
    result={"segments":segments,"angle_deg":angle,"status":summary.get("status","partial_no_summary"),
            "stop_reason":summary.get("stop_reason"),"accepted_steps":len(rows)-1,"last":rows[-1],
            "recorded_states":len(rows),"all_equilibrium_checks_passed":all(r["passed"] for r in equilibrium),
            "native_force_reconstruction_error_N":max(abs(float(r["force_reconstruction_residual_N"])) for r in legrows),
            "minimum_insulator_force_N":min(float(r["axial_force_N"]) for r in legrows),
            "minimum_conductor_force_N":min(float(r["axial_force_N"]) for state in lines.values() for values in state.values() for r in values),
            "total_gravity_mass_kg":summary.get("total_gravity_mass_kg"),
            "total_conductor_mass_kg":sum(float(r["total_conductor_mass"]) for r in line_model),
            "total_discrete_cable_length_m":sum(float(r["conductor_length"]) for r in line_model),
            "reference_wind_resultant":summary.get("reference_wind_resultant"),
            "first_slack":first_slack,"first_buckling":summary.get("first_buckling"),
            "first_buckling_speed_bracket_m_s":summary.get("first_buckling_speed_bracket_m_s"),
            "max_buckled_members":max(r["buckled_members"] for r in rows),
            "max_tensile_yield_members":max(r["tensile_yield_members"] for r in rows),
            "catalogue_strength_screen":strength_events,
            "total_system_nodes":summary.get("total_system_nodes"),"total_system_elements":summary.get("total_system_elements"),
            "identity":{"configuration_without_mesh":{k:v for k,v in config.items() if k!="line_segments"},
                        "effective_configuration_without_mesh":effective_no_mesh,
                        "solver_settings":summary.get("solver_settings"),"source_sha256":summary.get("source_sha256"),
                        "engine_version":summary.get("engine_version"),"code_sha256":summary.get("code_sha256"),
                        "directional_input_sha256":summary.get("directional_input_sha256")},
            "physical_mapping":{"hangers":{str(i):name for i,name in enumerate(names,1)},
                                "spans":{str(i):name for i,name in enumerate(line_names,1)},
                                "member_force_sign":"element local end i, same physical member orientation across grids"}}
    return result,rows


def compare_histories(coarse, fine, plan):
    if not coarse or not fine:return [],{"assessment":"not_assessed","reason":"missing history"}
    lower=max(coarse[0]["load_factor"],fine[0]["load_factor"])
    upper=min(coarse[-1]["load_factor"],fine[-1]["load_factor"])
    points=sorted({r["load_factor"] for series in (coarse,fine) for r in series if lower<=r["load_factor"]<=upper})
    if len(points)<2:return [],{"assessment":"not_assessed","reason":"no shared interval"}
    fields=[k for k in fine[0] if k.endswith(("_m","_N")) and k!="speed_m_s"]
    settings=plan["response_tolerance"];comparisons=[]
    for field in fields:
        absolute=settings["absolute_displacement_m"] if field.endswith("_m") else settings["absolute_force_N"]
        for factor in points:
            a,b=interpolate(coarse,factor,field),interpolate(fine,factor,field)
            comparisons.append({"angle_deg":fine[0]["angle_deg"],"coarse_segments":coarse[0]["segments"],
                "fine_segments":fine[0]["segments"],"load_factor":factor,"speed_m_s":20*math.sqrt(factor),
                "quantity":field,"coarse_value":a,"fine_value":b,
                **compare_value(a,b,relative=settings["relative"],absolute=absolute)})
    worst=max(comparisons,key=lambda r:r["normalized_error"])
    result={"angle_deg":fine[0]["angle_deg"],"coarse_segments":coarse[0]["segments"],"fine_segments":fine[0]["segments"],
            "common_speed_range_m_s":[20*math.sqrt(lower),20*math.sqrt(upper)],"comparisons":len(comparisons),
            "all_declared_outputs_passed":all(r["passed"] for r in comparisons),
            "declared_quantity_count":len(fields),"failed_point_comparisons":sum(not r["passed"] for r in comparisons),
            "failed_quantity_count":len({r["quantity"] for r in comparisons if not r["passed"]}),
            "failed_quantities":sorted({r["quantity"] for r in comparisons if not r["passed"]}),
            "worst":worst,"per_quantity":{field:max((r for r in comparisons if r["quantity"]==field),key=lambda r:r["normalized_error"]) for field in fields}}
    return comparisons,result


def verify_inputs(cases,plan):
    checks=[]
    for angle in ANGLES:
        for coarse_n,fine_n in ((20,40),(40,80)):
            a,b=(cases[(n,angle)] for n in (coarse_n,fine_n))
            if "identity" not in a or "identity" not in b:
                checks.append({"angle_deg":angle,"coarse_segments":coarse_n,"fine_segments":fine_n,"passed":False,"reason":"missing inputs"});continue
            for key in ("configuration_without_mesh","effective_configuration_without_mesh","solver_settings","source_sha256","engine_version","code_sha256"):
                if a["identity"][key]!=b["identity"][key]:raise ValueError(f"Uncontrolled input differs: {angle}/{coarse_n}/{fine_n}/{key}")
            items={"total_gravity_mass_kg":(a["total_gravity_mass_kg"],b["total_gravity_mass_kg"],1e-6),
                   "total_conductor_mass_kg":(a["total_conductor_mass_kg"],b["total_conductor_mass_kg"],1e-6)}
            for key,absolute in (("force_N",plan["input_tolerance"]["absolute_force_N"]),("moment_Nm",plan["input_tolerance"]["absolute_moment_Nm"])):
                for j,axis in enumerate("xyz"):
                    items[f"reference_{key}_{axis}"]=(a["reference_wind_resultant"][key][j],b["reference_wind_resultant"][key][j],absolute)
            for key,(v0,v1,absolute) in items.items():
                checks.append({"angle_deg":angle,"coarse_segments":coarse_n,"fine_segments":fine_n,
                               "quantity":key,"coarse_value":v0,"fine_value":v1,
                               **compare_value(v0,v1,relative=plan["input_tolerance"]["relative_mass_and_resultant"],absolute=absolute)})
    return checks


def make_figures(output,curves,pairs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10,"axes.grid":True,"grid.alpha":.2,"axes.spines.top":False,"axes.spines.right":False})
    colors={20:"#7c8896",40:"#dd8d24",80:"#176b8d"}
    fig,axes=plt.subplots(3,2,figsize=(12,10))
    for col,angle in enumerate(ANGLES):
        for n in GRIDS:
            rows=curves[(n,angle)]
            if not rows:continue
            x=[r["speed_m_s"] for r in rows]
            for index,(field,scale,label) in enumerate((("control_along_m",1000,"Control node 350 along wind (mm)"),
                                                       ("hanger1_along_m",1,"Hanger 1 along wind (m)"),
                                                       ("hanger2_along_m",1,"Hanger 2 along wind (m)"))):
                axes[index,col].plot(x,[r[field]*scale for r in rows],label=f"{n} segments/span",color=colors[n],ls="--" if n==40 else "-")
                axes[index,col].set(xlabel="Equivalent static speed (m/s)",ylabel=label,title=f"{angle} degrees")
        axes[0,col].legend(fontsize=8)
    fig.suptitle("Tension-only V strings | cable-grid sensitivity | uncalibrated physical model")
    fig.tight_layout()
    for ext in ("png","svg","pdf"):fig.savefig(output/f"grid_response.{ext}",dpi=160,bbox_inches="tight")
    plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(12,7.4))
    for col,angle in enumerate(ANGLES):
        for n in GRIDS:
            rows=curves[(n,angle)]
            if not rows:continue
            x=[r["speed_m_s"] for r in rows]
            for index,(field,label) in enumerate((("span1_maximum_N","Span 1 maximum tension (kN)"),
                                                  ("string1_leg1_N","V string 1, leg 1 (kN)"))):
                axes[index,col].plot(x,[r[field]/1000 for r in rows],label=f"{n} segments/span",color=colors[n],ls="--" if n==40 else "-")
                axes[index,col].set(xlabel="Equivalent static speed (m/s)",ylabel=label,title=f"{angle} degrees")
        axes[0,col].legend(fontsize=8)
    fig.tight_layout()
    for ext in ("png","svg","pdf"):fig.savefig(output/f"grid_forces.{ext}",dpi=160,bbox_inches="tight")
    plt.close(fig)


def publish(output):
    output=Path(output)
    if (output/"summary.json").exists():raise FileExistsError("Existing grid publication is protected")
    plan=json.loads((output/"frozen_plan.json").read_text())
    executions=json.loads((output/"execution.json").read_text())
    if len(executions)!=4:raise ValueError("All four bounded attempts must be recorded")
    for p,digest in plan["protected_baseline_sha256"].items():
        if sha256(ROOT/p)!=digest:raise ValueError(f"Protected baseline changed: {p}")
    for p,digest in plan["physical_source_sha256"].items():
        if sha256(ROOT/p)!=digest:raise ValueError(f"Physical source changed during study: {p}")
    cases={};curves={}
    for n in GRIDS:
        for angle in ANGLES:
            run=BASELINE/"runs"/f"tension_only_{angle}" if n==20 else output/"runs"/f"segments_{n}_angle_{angle}"
            cases[(n,angle)],curves[(n,angle)]=collect_case(run,n,angle)
    comparisons=[];pairs=[]
    for angle in ANGLES:
        for a,b in ((20,40),(40,80)):
            rows,result=compare_histories(curves[(a,angle)],curves[(b,angle)],plan)
            comparisons.extend(rows);pairs.append(result)
    checks=verify_inputs(cases,plan)
    accepted=[p for p in pairs if p.get("coarse_segments")==40]
    complete=all(c["status"]=="complete" and c["last"]["speed_m_s"]==100 for c in cases.values()) and all(e["returncode"]==0 for e in executions)
    passed=complete and len(accepted)==2 and all(p["all_declared_outputs_passed"] for p in accepted) and all(c["passed"] for c in checks)
    summary={"schema":"otw2.insulator_grid_study.v1","execution_status":"complete","assessment":"pass" if passed else "limited",
             "physical_validation":"unvalidated","new_FE_runs":4,"all_cases_complete":complete,
             "static_declared_outputs_converged":passed,"dynamic_convergence_established":False,
             "actual_geometry_and_string_type_confirmed":False,"cases":list(cases.values()),
             "grid_comparisons":pairs,"input_checks_passed":all(c["passed"] for c in checks),
             "all_equilibrium_checks_passed":all(c.get("all_equilibrium_checks_passed",False) for c in cases.values()),
             "baseline_unchanged":True,"frozen_plan_sha256":sha256(output/"frozen_plan.json"),
             "artifacts":["REPORT.md","FROZEN_PLAN.md","index.html","summary.json","frozen_plan.json","execution.json",
                          "response_history.csv","grid_comparisons.csv","input_checks.csv","conductor_strength_screen.csv","conductor_source_verification.json","verification.json",
                          *[f"{name}.{ext}" for name in ("grid_response","grid_forces") for ext in ("svg","png","pdf")]]}
    write_csv(output/"response_history.csv",[r for rows in curves.values() for r in rows])
    write_csv(output/"grid_comparisons.csv",comparisons);write_csv(output/"input_checks.csv",checks)
    strength_rows=[{"segments":c["segments"],"angle_deg":c["angle_deg"],**r} for c in cases.values() for r in c.get("catalogue_strength_screen",[])]
    write_csv(output/"conductor_strength_screen.csv",strength_rows)
    zero_events=[r for r in strength_rows if r["angle_deg"]==0 and r["first_exceedance_speed_bracket_m_s"]]
    if zero_events:
        first_low=min(r["first_exceedance_speed_bracket_m_s"][0] for r in zero_events)
        first_high=max(r["first_exceedance_speed_bracket_m_s"][1] for r in zero_events)
        candidates=[r for r in strength_rows if r["angle_deg"]==0 and r["segments"]==80] or zero_events
        peak=max(candidates,key=lambda r:r["maximum_recorded_force_N"])
        strength_notice=(f"本批0°工况首次超过目录所引计算拉断力{peak['catalogue_rated_tensile_strength_N']/1000:.2f} kN的保存区间约为"
                         f"{first_low:.2f}～{first_high:.2f} m/s，{peak['segments']}段已保存范围最大张力约{peak['maximum_recorded_force_N']/1000:.2f} kN。")
    else:
        strength_notice="本批0°工况在保存范围内没有记录到超过目录计算拉断力；这不构成实测或工程承载力验证。"
    make_figures(output,curves,pairs)
    write_json(output/"summary.json",summary)
    table="\n".join(f"| {c['segments']} | {c['angle_deg']} | {c['status']} | {c['accepted_steps']} | {c.get('last',{}).get('speed_m_s',0):.3f} | "
                    f"{c.get('last',{}).get('control_along_m',0):.6f} | {c.get('last',{}).get('hanger1_along_m',0):.6f} | {c.get('last',{}).get('hanger2_along_m',0):.6f} |"
                    for c in cases.values())
    pairtable="\n".join(f"| {p['angle_deg']} | {p['coarse_segments']}→{p['fine_segments']} | {p['all_declared_outputs_passed']} | "
                        f"{p['worst']['quantity']} | {p['worst']['speed_m_s']:.3f} | {p['worst']['normalized_error']:.4g} |" for p in pairs if "worst" in p)
    events="\n".join(f"| {c['segments']} | {c['angle_deg']} | {c.get('first_slack')} | {c.get('first_buckling_speed_bracket_m_s')} | {c.get('max_buckled_members')} |" for c in cases.values())
    strength_table="\n".join(f"| {r['segments']} | {r['angle_deg']} | {r['span']} | {r['first_exceedance_speed_bracket_m_s']} | {r['last_point_maximum_force_N']/1000:.3f} | {r['last_point_force_to_catalogue_ratio']:.4f} |" for r in strength_rows)
    report=f"""# 仅受拉绝缘子：导线20/40/80段大变形静力对照

本批执行状态complete，数值评估{summary['assessment']}，物理验证unvalidated。新全塔4例，复用旧20段2例；不宣称实际串型已标定或100 m/s为极限风速。

## 步骤与冻结条件

1. 在新FE前保存frozen_plan.json、旧20段记录SHA-256及当前物理源码指纹；唯一历史源码差异为已披露的源配置deepcopy快照隔离修复。
2. 原塔材、EA、导线单位质量/直径、初始弧垂/张力、V串几何、远端约束、风系数及13个目标保持一致，只有每跨分段改为40/80。严格仅受拉r=0。
3. 四例各用独立进程串行，保留每次命令、返回码、耗时、逐步平衡、塔杆/导线/绝缘子力与节点位移；solver600 s、外部900 s预算。
4. 从每例自己的重力平衡状态计算两挂点XYZ、沿/横风位移；导线以四跨物理名称配对，比较端部张力和全跨最小/最大张力，避免跨网格按节点号配对。
5. 在双方共同记录荷载倍率范围的合并采样点比较，必要时在线性荷载倍率坐标插值，禁止越过实际终点外推。塔杆预先固定877/878/825/828/917/920，使用SQLite原生端i轴力。
6. 40→80的建议静态数值标准为2%或绝对位移0.1 mm/力10 N（取较大者），20→40作为诊断。该标准比计划峰力5%更严格，仍不替代动态收敛或物理验证。

## 最终保存状态（位移相对重力，单位m）

| 每跨段数 | 风角 | 状态 | 加载步 | 最后等效风速m/s | 节点350沿风 | 挂点1沿风 | 挂点2沿风 |
| --- | --- | --- | --- | --- | --- | --- | --- |
{table}

控制节点350高36.4 m，不泛指最高塔节点。挂点1/2及各跨的物理名称映射保存在summary.json。全部共同状态、三向/沿横风位移和力详见response_history.csv。

## 预先声明输出的共同区间对照

| 风角 | 分段对照 | 全输出通过 | 最不利输出 | 对应风速m/s | 差值/容许差 |
| --- | --- | --- | --- | --- | --- |
{pairtable}

差值/容许差≤1为本项通过；近零量采用绝对限值，不用接近零的分母放大相对误差。每项最不利点见summary.json的per_quantity；完整逐点表见grid_comparisons.csv。
全部工况完成：{complete}；所有保存平衡通过：{summary['all_equilibrium_checks_passed']}；输入质量/合力矩检查：{summary['input_checks_passed']}。

## 质量、荷载与事件

物理参数配置去掉分段数后逐项完全相同；求解设置、塔材料源码、S2K来源与引擎相同。离散抛物线弧长改变会造成小幅导线总质量变化，重力后几何改变也会使离散风荷载合力/矩略变；不是强行要求节点荷载向量相同。
input_checks.csv列明总质量、导线质量及基准风场三向力/矩，限值为相对1e-4（近零力0.01 N、矩0.1 Nm）。总量和各状态响应分别验收，不用输入总量相近替代响应收敛。

| 段数 | 风角 | 首次松弛区间m/s | 首次塔杆压屈区间m/s | 最大压屈杆数 |
| --- | --- | --- | --- | --- |
{events}

首次事件是离散保存状态区间；塔材压屈仍为未按本塔角钢标定的TMQ原型状态，不代表实测破坏。缺失事件表示本次保存范围未记录到。

## 导线目录计算拉断力的补充筛查

本项是看到高风端张力后的适用范围检查，未修改此前冻结的网格验收标准，也未追加FE。
重新下载并核对[贵州大龙电厂机组送电湖南配套工程环境影响报告](https://sthj.guizhou.gov.cn/xwzx/tzgg/202009/W020221227481943376498.pdf)PDF第11页（正文第7页）表1-6：
JL/G1A-400/50的“计算拉断力(N)”为123040 N。项目目录用rated_tensile_strength_n保存此值，当前bundle_count=1。
它不是本塔导线实测强度，也不是设计允许张力；本模型没有导线断裂机制，因此超越该值后求解仍能继续。
下表筛查各已保存加载步的全部导线单元轴力；首次超越区间内未定位精确交点。具体线路、元素号、首超越轴力及末点比值见conductor_strength_screen.csv与summary.json。

| 段数 | 风角 | 物理线路 | 首次超越区间m/s | 末点最大张力kN | 末点/123.04kN |
| --- | --- | --- | --- | --- | --- |
{strength_table}

不得把网格数值通过和100 m/s仍收敛解释成导线在该风速实际完好。原PDF仅本地保留，来源、页码与SHA-256见conductor_source_verification.json。

## 使用范围与后续

只允许在本批明确输出、两风角、相同物理假设和共同静态加载范围内解释网格差；不将40/80相近推广到完整风向或动态响应。
若某项超限，应保留该项失败及发生区间，不能平均后消除。真实绝缘子类型、每肢9.55 m几何、完整相线/地线/分裂束与远端柔度仍需核对。
本批与N06旧弹性V串的无风重力线性模态任务分开；任何全塔瞬态仍需实际阻尼、时间步、空间荷载与动力平衡验收。

## 复现

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.insulator_grid_study --run --output /tmp/insulator_grid_NEW
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.insulator_grid_study --publish --output /tmp/insulator_grid_NEW
.venv/bin/python -m unittest tests.test_insulator_grid -v
```

原始数据保留本地，代码/方法/结论可同步。旧20段数据和本批物理源码在发布前核对指纹未改变。
"""
    (output/"REPORT.md").write_text(report)
    body="".join(f"<tr><td>{c['segments']}</td><td>{c['angle_deg']}°</td><td>{html.escape(c['status'])}</td><td>{c['accepted_steps']}</td><td>{c.get('last',{}).get('speed_m_s',0):.2f}</td></tr>" for c in cases.values())
    page=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>仅受拉V串导线网格对照</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1200px;margin:30px auto;padding:0 18px;color:#203340;background:#f4f7f9}}section{{background:white;padding:22px;margin:18px 0;border-radius:12px}}img{{width:100%;height:auto}}.note{{border-left:4px solid #c77b26;padding:12px;background:#fff3df}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;border-bottom:1px solid #d9e2e8;padding:9px}}a{{color:#176b8d}}.scroll{{overflow:auto}}</style>
<a href="../index.html">← 本批总览</a><h1>仅受拉V串：20／40／80段导线对照</h1><p class="note">4个新全塔工况；评估 {summary['assessment']}，物理验证未完成。100 m/s为本轮比较上限。</p>
<p class="note"><b>导线承载范围提示：</b>{strength_notice}当前导线模型没有断裂机制；网格检查通过不表示该荷载下导线实际完好。目录值也不是实测或设计允许张力。<a href="conductor_strength_screen.csv">逐跨筛查CSV</a></p>
<section><h2>控制点与两个挂点运动</h2><img src="grid_response.svg" alt="两风角各三种网格的控制点与两挂点沿风位移"><a href="grid_response.png">PNG</a> · <a href="grid_response.pdf">PDF</a></section>
<section><h2>导线与绝缘子力</h2><img src="grid_forces.svg" alt="跨1张力和V串1肢杆力的三网格对照"><a href="grid_forces.png">PNG</a> · <a href="grid_forces.pdf">PDF</a><div class="scroll"><table><thead><tr><th>每跨段数</th><th>风角</th><th>状态</th><th>步数</th><th>最后风速m/s</th></tr></thead><tbody>{body}</tbody></table></div></section>
<section><h2>步骤、判据与结果</h2><p>40→80的全指定输出静态检查：{passed}。逐点差异采用预声明2%及近零绝对限值，不平均掩盖超限。</p><a href="REPORT.md">完整报告</a> · <a href="FROZEN_PLAN.md">冻结方案</a> · <a href="grid_comparisons.csv">逐点误差CSV</a> · <a href="response_history.csv">全部提取响应</a> · <a href="input_checks.csv">质量/荷载检查</a> · <a href="summary.json">汇总JSON</a></section></html>"""
    (output/"index.html").write_text(page)
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--publish",action="store_true")
    args=parser.parse_args()
    if args.run: run_cases(args.output.resolve())
    if args.publish:
        result=publish(args.output.resolve())
        print(json.dumps({k:result[k] for k in ("assessment","all_cases_complete","static_declared_outputs_converged")}))
