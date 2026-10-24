"""Luo-inspired quasi-static weakness screening, not dynamic collapse validation.

Read-only input analysis; raw FE runs and historical publications never change.
Records first *observed* buckling brackets, not interpolated critical loads.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SECTION_BASE_TAGS = (2510, 1490, 1300, 1200, 1150, 1130, 1110, 1000, 930, 910, 500, 380)
HEIGHT_BOUNDS = (0., 3.2, 6.8, 9., 13.2, 17.4, 21.6, 24., 27., 30., 33., 36.4, 39.6)


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        raise ValueError(f"No rows for {path}")
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite input")
    return result


def geometry(run_dir):
    path = Path(run_dir)/"model_data"
    nodes = {int(r["node_tag"]): [finite(r[k]) for k in ("x", "y", "z")] for r in read_csv(path/"nodes.csv")}
    params = {int(r["element_tag"]): r for r in read_csv(path/"tmq_member_parameters.csv")}
    members = {}
    for r in read_csv(path/"elements.csv"):
        tag = int(r["element_tag"])
        if tag in members:
            raise ValueError("Duplicate member")
        p = params[tag]
        a,b = nodes[int(r["node_i"])], nodes[int(r["node_j"])]
        area,E,fy,phi = (finite(p[k]) for k in ("area_m2", "elastic_modulus", "yield_stress", "phi"))
        if min(area,E,fy,phi) <= 0 or phi > 1:
            raise ValueError("Invalid member material inputs")
        members[tag] = dict(element_tag=tag, node_i=int(r["node_i"]), node_j=int(r["node_j"]),
            start=a, end=b, z_min=min(a[2],b[2]), z_max=max(a[2],b[2]), z_mid=(a[2]+b[2])/2,
            section=p["section_name"], steel=p["material_name"], length_m=finite(p["length_m"]), area_m2=area,
            elastic_modulus_Pa=E, yield_stress_Pa=fy, phi=phi, initial_buckling_force_N=phi*fy*area,
            initial_buckling_strain=phi*fy/E, slenderness_K1=finite(p["slenderness_K1"]))
    if set(members) != set(params):
        raise ValueError("Connectivity/parameters mismatch")
    return nodes, members


def load_history(run_dir):
    rows = read_csv(Path(run_dir)/"history.csv")
    result = {}
    for r in rows:
        step = int(r["step"])
        if step in result or step != len(result):
            raise ValueError("History must contain every accepted step, beginning with zero")
        result[step] = {k: finite(v) if k not in ("stage", "equilibrium_passed") else v for k,v in r.items()}
    return result


def update_member(record, row, point, previous_point):
    strain,stress,force = (finite(row[k]) for k in ("strain", "stress_Pa", "force_N"))
    if abs(force-stress*record["area_m2"]) > max(.001, abs(force)*1e-9):
        raise ValueError("Material stress/force scaling mismatch")
    count = int(row["buckling_count"])
    if count < record.get("buckling_count",0):
        raise ValueError("Committed buckling history cannot decrease")
    record["max_compression_strain_demand"] = max(record.get("max_compression_strain_demand",0.), -strain/record["initial_buckling_strain"],0.)
    record["max_compression_force_ratio"] = max(record.get("max_compression_force_ratio",0.), -force/record["initial_buckling_force_N"],0.)
    record["max_tension_yield_ratio"] = max(record.get("max_tension_yield_ratio",0.), stress/record["yield_stress_Pa"],0.)
    record["buckling_count"] = count
    record["ever_buckled"] = count > 0
    record["last_stage"] = row["stage"]
    record["last_force_N"] = force
    if count and record.get("first_observed") is None:
        record["first_observed"] = dict(step=int(point["step"]), stage=point["stage"],
            drift_ratio=point["drift_ratio"], base_shear_N=point["base_shear_N"],
            previous_step=int(previous_point["step"]) if previous_point else None,
            previous_drift_ratio=previous_point["drift_ratio"] if previous_point else None)


def member_screen(run_dir):
    run_dir = Path(run_dir)
    summary = json.loads((run_dir/"summary.json").read_text())
    if summary["status"] not in ("complete", "partial"):
        raise ValueError("Only finished complete/partial runs can be screened")
    nodes,members = geometry(run_dir)
    history = load_history(run_dir)
    if len(history) != summary["accepted_steps"]+1:
        raise ValueError("Summary/history coverage mismatch")
    expected = set(members)
    previous_step, seen, count = None, set(), 0
    selected_histories = {tag: [] for tag in (825,828,917,920,877,878) if tag in members}
    with gzip.open(run_dir/"member_states.csv.gz", "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            step,tag = int(row["step"]),int(row["element_tag"])
            if step != previous_step:
                if previous_step is not None and seen != expected:
                    raise ValueError(f"Missing members at step {previous_step}")
                if step != (0 if previous_step is None else previous_step+1):
                    raise ValueError("Member steps out of order or missing")
                previous_step,seen = step,set()
            if tag in seen or tag not in expected:
                raise ValueError("Duplicate or unknown member sample")
            seen.add(tag)
            update_member(members[tag],row,history[step],history.get(step-1))
            if tag in selected_histories:
                selected_histories[tag].append([step,finite(row["strain"]),finite(row["force_N"]),int(row["buckling_count"])])
            count+=1
    if seen != expected or previous_step != max(history):
        raise ValueError("Incomplete member history")
    for member in members.values():
        member.setdefault("first_observed",None)
    # Event class first, then rounded demand; symmetry is not broken by roundoff.
    ranking = sorted(members, key=lambda t:(not members[t]["ever_buckled"],
        -round(members[t]["max_compression_strain_demand"],6),t))
    events = sorted(({"element_tag":t, **r["first_observed"]} for t,r in members.items() if r["first_observed"]),
                    key=lambda e:(e["step"],e["element_tag"]))
    bins=[]
    for index,(lo,hi) in enumerate(zip(HEIGHT_BOUNDS,HEIGHT_BOUNDS[1:])):
        group=[r for r in members.values() if lo<=r["z_mid"]<hi or index==len(HEIGHT_BOUNDS)-2 and r["z_mid"]==hi]
        bins.append(dict(z_lower=lo,z_upper=hi,member_count=len(group),
            ever_buckled_count=sum(r["ever_buckled"] for r in group),
            max_compression_strain_demand=max((r["max_compression_strain_demand"] for r in group),default=0)))
    if sum(b["member_count"] for b in bins)!=len(members):
        raise ValueError("Height bins do not cover every member exactly once")
    return dict(run_directory=run_dir.name, run=summary, nodes=nodes, members=members, history=list(history.values()),
                ranking=ranking, events=events, height_bins=bins, selected_histories=selected_histories,
                coverage=dict(steps=len(history),members=len(members),material_rows=count))


def section_definitions(nodes):
    result=[]
    for base in SECTION_BASE_TAGS:
        tags=list(range(base,base+4))
        coords=np.asarray([nodes[t] for t in tags],dtype=float)
        if np.ptp(coords[:,2])>1e-6:
            raise ValueError("Section must be a horizontal complete node group")
        if np.linalg.matrix_rank(np.column_stack((np.ones(4),coords[:,:2])))!=3:
            raise ValueError("Section nodes must span a plane")
        result.append(dict(section_index=len(result),node_tags=tags,height_m=float(coords[0,2])))
    if any(a["height_m"]>=b["height_m"] for a,b in zip(result,result[1:])):
        raise ValueError("Section heights must be increasing")
    return result


def section_kinematics(coordinates, displacements):
    """Six DOFs in global axes; geometric fit is a sensitivity alternative.

    Small rigid rotation gives uz = a + Rx*y - Ry*x. Fits use mean-centered
    coordinates, and nodal rotations are global right-handed radians.
    """
    xyz,u = np.asarray(coordinates,dtype=float),np.asarray(displacements,dtype=float)
    if xyz.ndim!=2 or xyz.shape[1]!=3 or u.shape!=(len(xyz),6) or not np.all(np.isfinite(xyz)) or not np.all(np.isfinite(u)):
        raise ValueError("Need finite coordinates and six finite displacement DOFs per node")
    xy=xyz[:,:2]-xyz[:,:2].mean(axis=0)
    design=np.column_stack((np.ones(len(xyz)),xy))
    if np.linalg.matrix_rank(design)!=3:
        raise ValueError("Rotation fit needs noncollinear section nodes")
    fit=np.linalg.lstsq(design,u[:,2],rcond=None)[0]
    rms=float(np.sqrt(np.mean((design@fit-u[:,2])**2)))
    mean=u.mean(axis=0)
    return dict(ux=float(mean[0]),uy=float(mean[1]),rx=float(mean[3]),ry=float(mean[4]),
                fit_rx=float(fit[2]),fit_ry=float(-fit[1]),fit_rms_m=rms)


def panel_drift(lower,upper,height):
    if not math.isfinite(height) or height<=0:
        raise ValueError("Panel height must be positive")
    dx=(upper["ux"]-lower["ux"])/height
    dy=(upper["uy"]-lower["uy"])/height
    return dict(raw_x=dx,raw_y=dy,isdr_x=dx-lower["ry"],isdr_y=dy+lower["rx"],
                geometric_isdr_x=dx-lower["fit_ry"],geometric_isdr_y=dy+lower["fit_rx"],
                lower_fit_rms_m=lower["fit_rms_m"],upper_fit_rms_m=upper["fit_rms_m"])


def nodal_sections(run_dir,nodes,history):
    path=Path(run_dir)/"node_states.csv.gz"
    if not path.is_file():
        raise ValueError("No nodal histories: cannot reconstruct rotation-corrected ISDR from member forces")
    sections=section_definitions(nodes)
    needed={n for s in sections for n in s["node_tags"]}
    expected=set(nodes)
    baseline=None
    rows=[]

    def finish_step(step,values,seen):
        nonlocal baseline
        if seen!=expected:
            raise ValueError(f"Incomplete six-DOF nodal history at step {step}")
        if step==0:
            baseline={n:np.array(v) for n,v in values.items()}
        states=[section_kinematics([nodes[n] for n in s["node_tags"]],
                    [np.array(values[n])-baseline[n] for n in s["node_tags"]]) for s in sections]
        point=history[step]
        for index,(lo,hi) in enumerate(zip(sections,sections[1:])):
            rows.append(dict(step=step,stage=point["stage"],control_drift_ratio=point["drift_ratio"],
                base_shear_N=point["base_shear_N"],panel=index+1,z_lower=lo["height_m"],z_upper=hi["height_m"],
                **panel_drift(states[index],states[index+1],hi["height_m"]-lo["height_m"])))

    previous=None
    seen,values=set(),{}
    with gzip.open(path,"rt",encoding="utf-8",newline="") as stream:
        for row in csv.DictReader(stream):
            step,tag=int(row["step"]),int(row["node_tag"])
            if step!=previous:
                if previous is not None:
                    finish_step(previous,values,seen)
                if step!=(0 if previous is None else previous+1) or step>=len(history):
                    raise ValueError("Missing or extra nodal steps")
                previous,seen,values=step,set(),{}
            if tag in seen or tag not in expected:
                raise ValueError("Duplicate or unknown node")
            seen.add(tag)
            vector=[finite(row[k]) for k in ("ux","uy","uz","rx","ry","rz")]
            if tag in needed:
                values[tag]=vector
    if previous!=len(history)-1:
        raise ValueError("Incomplete node history")
    finish_step(previous,values,seen)
    return sections,rows


def envelope_panels(rows):
    envelopes=[]
    for panel in sorted({r["panel"] for r in rows}):
        group=[r for r in rows if r["panel"]==panel]
        out={k:group[0][k] for k in ("panel","z_lower","z_upper")}
        for key in ("raw_x","raw_y","isdr_x","isdr_y","geometric_isdr_x","geometric_isdr_y"):
            peak=max(group,key=lambda r:abs(r[key]))
            out[key+"_abs_max"]=abs(peak[key])
            out[key+"_max"]=max(r[key] for r in group)
            out[key+"_min"]=min(r[key] for r in group)
            out[key+"_peak_step"]=peak["step"]
        out["rotation_estimator_max_difference_y"]=max(abs(r["isdr_y"]-r["geometric_isdr_y"]) for r in group)
        out["fit_rms_max_m"]=max(max(r["lower_fit_rms_m"],r["upper_fit_rms_m"]) for r in group)
        envelopes.append(out)
    return envelopes


def compare_replay(new,old_run):
    old=load_history(old_run)
    new_rows=new["history"]
    if len(new_rows)!=len(old):
        return dict(passed=False,reason="Different accepted-step counts")
    max_u=max(abs(r["displacement_m"]-old[i]["displacement_m"]) for i,r in enumerate(new_rows))
    max_v=max(abs(r["base_shear_N"]-old[i]["base_shear_N"]) for i,r in enumerate(new_rows))
    branch_match=all(int(r["buckled_members"])==int(old[i]["buckled_members"]) for i,r in enumerate(new_rows))
    return dict(passed=max_u<1e-8 and max_v<.01 and branch_match,
                maximum_displacement_difference_m=max_u,maximum_shear_difference_N=max_v,
                all_step_buckled_counts_match=branch_match,old_directory=str(old_run))


def analyze(run_dir,extended_dir,baseline_dir,output):
    run_dir,extended_dir,baseline_dir,output=map(Path,(run_dir,extended_dir,baseline_dir,output))
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Refusing to overwrite a previous weakness analysis")
    main,extended=member_screen(run_dir),member_screen(extended_dir)
    replay=compare_replay(main,baseline_dir)
    if not replay["passed"]:
        raise ValueError(f"Adding nodal recorder changed response: {replay}")
    sections,panels=nodal_sections(run_dir,main["nodes"],main["history"])
    envelopes=envelope_panels(panels)
    stage_envelopes=[]
    # Each complete amplitude block contains +a, -a, 0; this is NOT a random sample.
    targets=main["run"]["targets_drift"]
    if len(targets)%3 or any(targets[i]!=-targets[i+1] or targets[i+2]!=0 for i in range(0,len(targets),3)):
        raise ValueError("This amplitude-block report requires (+a,-a,0) target groups")
    for start in range(0,len(targets),3):
        group=[r for r in panels if r["stage"].startswith("target_") and start<=int(r["stage"].split("_")[1])<start+3]
        for row in envelope_panels(group):
            stage_envelopes.append(dict(amplitude_drift=targets[start],**row))
    strongest=max(envelopes,key=lambda r:r["isdr_y_abs_max"])
    geometric=max(envelopes,key=lambda r:r["geometric_isdr_y_abs_max"])
    output.mkdir(parents=True,exist_ok=True)
    sources=[Path(__file__),run_dir/"summary.json",run_dir/"node_states.csv.gz",run_dir/"member_states.csv.gz",
             extended_dir/"summary.json",extended_dir/"member_states.csv.gz",ROOT/"article/风荷载作用下输电塔-线体系抗倒塌研究_罗贤超.pdf"]
    result=dict(schema_version=1,analysis="luo_inspired_quasi_static_weakness_screening",validated_for_collapse=False,
        run=main["run"],extended_run=extended["run"],replay_check=replay,sections=sections,panel_envelopes=envelopes,
        amplitude_envelopes=stage_envelopes,primary_max_isdr_y=strongest,geometric_max_isdr_y=geometric,
        events=main["events"],extended_events=extended["events"],member_ranking=main["ranking"],
        main_coverage=main["coverage"],extended_coverage=extended["coverage"],height_bins=main["height_bins"],
        source_sha256={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        literature=dict(title="风荷载作用下输电塔-线体系抗倒塌研究",author="罗贤超",formula="Eq 2.2, PDF26 / printed19",
            comparison="Table 2.3 PDF37/printed30; Figure 2.18 PDF38/printed31",
            protocol="20 independent 300s wind records; 0/30/45/90 degrees; multiple speeds",
            distinction="This report uses one quasi-static Y protocol and one partial extension, NOT wind-record probabilities"),
        definitions=dict(isdr_x="(mean Ux_upper-mean Ux_lower)/H-mean Ry_lower",
            isdr_y="(mean Uy_upper-mean Uy_lower)/H+mean Rx_lower",
            geometric_rotation="least squares uz=a+Rx*y-Ry*x on four corner nodes",
            reference="subtract the step0 gravity state from all six nodal DOFs",
            envelope="signed positive/negative and max absolute; absolute envelope adapts Luo Eq2.2 for cyclic loading",
            section_scope="11 central tower-body panels, 0–36.4m; projecting crossarms/head excluded from section groups",
            member_scope="all 1528 members including crossarms to z39.6m",
            height_counts="midpoint half-open bins, final bin closed; not damage probabilities",
            compression_demand="max(-equivalent_strain,0)/(phi*fy/E), normalized to INITIAL limit, NOT plastic strain or damage",
            event="historical committed buckling_count>0; first observed step is bracketed, not exact onset"),
        limitations=["No damage accumulation or failure deletion; do not label colors as damage D",
            "Tube-to-angle cyclic parameters uncalibrated; elastic uncoupled bending and torsion",
            "No conductor loads or dynamic wind records in this quasi-static single-tower experiment",
            "Luo 2% ISDR collapse threshold NOT transferred to this tower; no certified collapse threshold",
            "Nodal mean rotation is a declared implementation, not an algorithm specified by Luo",
            "No rigid diaphragms; compare geometric and nodal rotation estimates",
            "Never merge partial extended history with complete bounded history",
            "First softening location, maximum deformation location, and collapse-controlling location need not coincide"])
    (output/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    write_csv(output/"panel_history.csv",panels)
    write_csv(output/"panel_envelopes.csv",envelopes)
    write_csv(output/"amplitude_envelopes.csv",stage_envelopes)
    write_csv(output/"section_nodes.csv",[dict(section=s["section_index"],height_m=s["height_m"],node_tag=n) for s in sections for n in s["node_tags"]])
    for name,screen in (("bounded",main),("extended",extended)):
        rows=[]
        for tag in screen["ranking"]:
            member=screen["members"][tag]
            scalar={k:v for k,v in member.items() if k not in ("start","end","first_observed")}
            scalar.update({f"{prefix}_{axis}":v for prefix in ("start","end") for axis,v in zip("xyz",member[prefix])})
            event=member["first_observed"] or {}
            scalar.update(first_step=event.get("step"),first_drift_ratio=event.get("drift_ratio"),previous_drift_ratio=event.get("previous_drift_ratio"))
            rows.append(scalar)
        write_csv(output/f"{name}_members.csv",rows)
    from .weakness_view import publish
    publish(output,result,main,extended,panels)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--extended",type=Path,required=True)
    parser.add_argument("--baseline",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=analyze(args.run,args.extended,args.baseline,args.output)
    print(json.dumps({"max_isdr_y_panel":result["primary_max_isdr_y"],"replay":result["replay_check"]},ensure_ascii=False))
