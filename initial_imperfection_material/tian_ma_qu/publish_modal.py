"""Publish verified gravity-state modes, component shares and tower-shape matches."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import shutil
import re
import math
from html import escape
import numpy as np

from .modal_analysis import weighted_mac
from .wind_angle_verification import write_json

CASES=("bare_checked","coupled_20_checked","coupled_40_checked","coupled_80_checked")
LABELS=("单塔","塔线·20段/档","塔线·40段/档","塔线·80段/档")
MODE_NAMES=("塔身扭转","塔身横线向X侧摆","塔身顺线向Y侧摆")


def publication_config(root, manifest=None):
    """Validate a versioned publication manifest without modifying any input."""
    root=Path(root).resolve()
    if manifest is None:
        raw={"schema_version":1,"reference_case":CASES[0],"primary_case":CASES[-1],
             "cases":[{"key":k,"label":l,"source":str(root/"runs"/k)} for k,l in zip(CASES,LABELS)],
             "matching":{"method":"mass_weighted_mac","mac_min":.9,"tower_share_min":.005}}
        base=root
    else:
        path=Path(manifest).resolve();base=path.parent
        raw=json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version")!=1 or not isinstance(raw.get("cases"),list) or len(raw["cases"])<2:
        raise ValueError("manifest requires schema_version=1 and at least reference/coupled cases")
    rows=[];seen=set()
    for row in raw["cases"]:
        key=row.get("key","")
        if not isinstance(key,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",key) or key in seen:
            raise ValueError("invalid or duplicate case key")
        seen.add(key)
        if not isinstance(row.get("source"),str) or not isinstance(row.get("label"),str):
            raise ValueError("case source and label required")
        source=(base/row["source"]).resolve()
        if not source.is_relative_to(Path(__file__).resolve().parents[2]) or not source.is_dir():
            raise ValueError("case source must be an existing directory inside project")
        summary=json.loads((source/"summary.json").read_text())
        if summary.get("status")!="complete" or summary.get("checks_passed") is not True:
            raise ValueError("Refuse publication: modal case checks did not pass")
        modes=summary.get("modes",[])
        if len(modes)<6 or any(not math.isfinite(m["frequency_Hz"]) or m["frequency_Hz"]<=0 for m in modes):
            raise ValueError("modal case requires at least six finite positive frequencies")
        rows.append({"key":key,"label":row["label"],"source":source,"summary":summary})
    reference=raw.get("reference_case");primary=raw.get("primary_case")
    if reference not in seen or primary not in seen or reference==primary:
        raise ValueError("reference_case and primary_case must identify distinct manifest cases")
    order=[next(r for r in rows if r["key"]==reference)]+[r for r in rows if r["key"]!=reference]
    if order[0]["summary"].get("segments_per_span")!=0 or any(r["summary"].get("segments_per_span",0)<=0 for r in order[1:]):
        raise ValueError("reference must be bare tower and comparisons must be cable cases")
    matching=raw.get("matching",{})
    if matching.get("method","mass_weighted_mac")!="mass_weighted_mac":
        raise ValueError("unsupported matching method")
    matching={"method":"mass_weighted_mac","mac_min":matching.get("mac_min",.9),
              "tower_share_min":matching.get("tower_share_min",.005)}
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<1
           for v in (matching["mac_min"],matching["tower_share_min"])):
        raise ValueError("matching thresholds must be finite in [0,1)")
    return {"cases":order,"primary_case":primary,"reference_case":reference,"matching":matching,
            "manifest_source":str(Path(manifest).resolve()) if manifest else None}


def publish(root, manifest=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.ticker import MaxNLocator
    from mpl_toolkits.mplot3d.art3d import Line3DCollection
    config=publication_config(root,manifest)
    root=Path(root);runs=root/"runs"
    CASES=tuple(r["key"] for r in config["cases"])
    LABELS=tuple(r["label"] for r in config["cases"])
    primary_key=config["primary_case"]
    if manifest is not None:
        if root.exists():raise FileExistsError("manifest publication requires a new output directory")
        # Copy immutable input evidence into a new publication; never write viewer files into old runs.
        files=("summary.json","eigenvectors.npz","modes.csv","geometry.json","stiffness.npz",
               "mass.npz","equation_modes.npz","opensees_modal_properties.txt")
        for row in config["cases"]:
            for name in files:
                if not (row["source"]/name).is_file():raise ValueError(f"missing publication input: {row['key']}/{name}")
        for row in config["cases"]:
            target=runs/row["key"];target.mkdir(parents=True)
            for name in files:shutil.copy2(row["source"]/name,target/name)
    summaries={k:json.loads((runs/k/"summary.json").read_text()) for k in CASES}
    if any(s["status"]!="complete" or not s["checks_passed"] for s in summaries.values()):
        raise ValueError("Refuse publication: some requested modal cases did not pass")
    data={k:np.load(runs/k/"eigenvectors.npz") for k in CASES};b=data[CASES[0]]
    matches={};candidates={}
    for key in CASES[1:]:
        c=data[key];lookup={int(n):i for i,n in enumerate(c["node_tags"])}
        indices=[lookup[int(n)] for n in b["node_tags"]]
        matches[key]=[];candidates[key]=[]
        for m in range(3):
            records=[]
            for i,v in enumerate(c["vectors"]):
                mac=weighted_mac(b["vectors"][m,:,:3],v[indices,:3],b["mass"][:,:3])
                row=summaries[key]["modes"][i]
                if mac>config["matching"]["mac_min"] and row["tower_kinetic_share"]>config["matching"]["tower_share_min"]:
                    records.append({**row,"tower_MAC":mac,"reference_mode":m+1})
            if not records:raise ValueError(f"No credible tower shape match {key}, {m+1}")
            best=max(records,key=lambda r:r["tower_MAC"]*r["tower_kinetic_share"])
            best={**best,"change_from_bare_percent":100*(best["frequency_Hz"]/summaries[CASES[0]]["modes"][m]["frequency_Hz"]-1)}
            matches[key].append(best);candidates[key].append(records)
    native_crosscheck={}
    for key,old in (("bare_checked","bare"),("coupled_20_checked","coupled_20")):
        oldfile=runs/old/"summary.json"
        if key in summaries and oldfile.exists():
            original=json.loads(oldfile.read_text())
            if original.get("status")=="complete":
                new=np.array([v["frequency_Hz"] for v in summaries[key]["modes"]])
                previous=np.array([v["frequency_Hz"] for v in original["modes"]])
                native_crosscheck[key]=float(np.max(abs(new/previous-1)))
    mesh=[]
    for a,bkey in zip(CASES[1:-1],CASES[2:]):
        af=np.array([v["frequency_Hz"] for v in summaries[a]["modes"][:6]])
        bf=np.array([v["frequency_Hz"] for v in summaries[bkey]["modes"][:6]])
        mesh.append({"from":a,"to":bkey,"first_six_max_frequency_change_percent":float(np.max(abs(bf/af-1))*100),
            "matched_tower_frequency_change_percent":[100*(y["frequency_Hz"]/x["frequency_Hz"]-1) for x,y in zip(matches[a],matches[bkey])],
            "matched_tower_kinetic_share_change":[y["tower_kinetic_share"]-x["tower_kinetic_share"] for x,y in zip(matches[a],matches[bkey])]})
    summary={"schema_version":1,"analysis":"single_tower_cable_gravity_modal_analysis","status":"complete",
        "case_keys":list(CASES),"reference_case":CASES[0],"primary_case":primary_key,"cases":summaries,"tower_matches":matches,
        "case_labels":dict(zip(CASES,LABELS)),"publication_config":{"schema_version":1,"matching":config["matching"],"source":config["manifest_source"]},
        "tower_like_candidate_modes":candidates,"mesh_checks":mesh,"native_solver_frequency_crosscheck":native_crosscheck,
        "validated_for_design":False,"wind_load_applied":False,
        "modal_equilibrium":"Undamped tangent modes after gravity and conductor prestress equilibration; not damaged wind-peak modes",
        "matching_method":f"Common original tower translational DOFs; mass-weighted MAC > {config['matching']['mac_min']}, tower kinetic share > {config['matching']['tower_share_min']}; representative maximizes MAC times tower share. This representative is not subspace convergence certification.",
        "participation_definition":"Effective modal mass for uniform translational support excitation divided by total FREE directional mass; not generalized wind forcing",
        "classification_thresholds":{"tower_dominated_min_tower_kinetic_share":.6,"cable_attachment_dominated_max_tower_kinetic_share":.1},
        "limitations":["One tower, two conductors/four 300m fixed-remote-end spans, elastic V strings; no adjacent towers/ground wires/full phase bundle",
            "Initial 8m sag and 20kN force inherited; actual gravity equilibrium used; target sag not fitted",
            "TMQ angle-steel transfer uncalibrated; no yielding in these gravity states, so this is initial tangent behaviour",
            "No damping, wind time history, aerodynamic coupling, fatigue or capacity inference",
            "Close/repeated cable eigenvalues have nonunique modal bases; compare frequency groups and summed contributions",
            "Low-frequency and first three tower-shape screening only; high-order cable modes and dynamic modal truncation not certified"],
        "excluded_attempt":{"case":"coupled_40","reason":"Default ARPACK iteration limit, invalid final eigenpair/zero generalized mass; rejected, not used in figures or matches"},
        "artifact_sha256":{key:{n:hashlib.sha256((runs/key/n).read_bytes()).hexdigest() for n in ("summary.json","eigenvectors.npz","modes.csv","stiffness.npz","mass.npz","equation_modes.npz")} for key in CASES},
        "publisher_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "template_sha256":hashlib.sha256(Path(__file__).with_name("modal_viewer.html").read_bytes()).hexdigest()}
    write_json(root/"summary.json",summary)
    with (root/"tower_mode_comparison.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f);w.writerow(("case","shape","bare_mode","coupled_mode","frequency_Hz","period_s","change_from_bare_percent","tower_MAC","tower_kinetic_share"))
        for key in CASES[1:]:
            for name,row in zip(MODE_NAMES,matches[key]):
                w.writerow((key,name,row["reference_mode"],row["mode"],row["frequency_Hz"],row["period_s"],row["change_from_bare_percent"],row["tower_MAC"],row["tower_kinetic_share"]))
    for key in CASES:
        d=data[key];geometry=json.loads((runs/key/"geometry.json").read_text());shapes=d["vectors"][:,:,:3]
        scales=np.linalg.norm(shapes,axis=2).max(axis=1)
        normalized=shapes/scales[:,None,None]
        # Display rounding only; exact mass-normalized six-DOF shapes stay in NPZ.
        normalized=np.array([float(f"{x:.6g}") for x in normalized.ravel()]).reshape(normalized.shape)
        viewer={"geometry":geometry,"modes":summaries[key]["modes"],
            "display_shapes":normalized.tolist(),"normalization":"each mode's largest nodal translational norm = 1; display only",
            "tower_modes":[r["mode"] for r in matches[key]] if key in matches else [1,2,3]}
        (runs/key/"viewer_data.json").write_text(json.dumps(viewer,separators=(",",":"),ensure_ascii=False,allow_nan=False),encoding="utf-8")
    colors=[plt.get_cmap("tab10")(i%10) for i in range(len(CASES))]
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout="constrained")
    for key,color in zip(CASES[1:],colors[1:]):
        rows=summaries[key]["modes"][:24]
        axes[0].plot([v["mode"] for v in rows],[v["frequency_Hz"] for v in rows],".-",color=color,label=str(summaries[key]["segments_per_span"])+" segments/span")
    axes[0].set(xlabel="Global mode number",ylabel="Frequency (Hz)",title="Low cable-frequency groups");axes[0].legend()
    for i,(key,color) in enumerate(zip(CASES,colors)):
        fs=[v["frequency_Hz"] for v in summaries[key]["modes"][:3]] if i==0 else [v["frequency_Hz"] for v in matches[key]]
        width=.8/len(CASES)
        axes[1].bar(np.arange(3)+width*(i-(len(CASES)-1)/2),fs,width,color=color,label="Bare" if i==0 else str(summaries[key]["segments_per_span"])+" seg/span")
    axes[1].set(xticks=range(3),xticklabels=["Tower torsion","Tower X sway","Tower Y sway"],ylabel="Frequency (Hz)",title="Matched tower shapes, not global mode ranks");axes[1].legend(fontsize=8)
    for ax in axes:ax.grid(alpha=.2,axis="y")
    for ext in ("png","svg","pdf"):fig.savefig(root/f"frequency_comparison.{ext}",dpi=170)
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout="constrained")
    primary=summaries[primary_key]
    for axis,color in zip("XYZ",("#326bb1","#14816d","#bd6e0b")):
        axes[0].plot([v["mode"] for v in primary["modes"]],[100*v[f"cumulative_mass_ratio_{axis}"] for v in primary["modes"]],color=color,label=axis)
    axes[0].set(xlabel=f"Global mode number ({primary['segments_per_span']} segments/span)",ylabel="Cumulative effective / free mass (%)",ylim=(0,100),title="Uniform support excitation; not wind participation");axes[0].legend()
    for key,color in zip(CASES[1:],colors[1:]):
        rows=summaries[key]["modes"]
        axes[1].scatter([v["frequency_Hz"] for v in rows],[100*v["tower_kinetic_share"] for v in rows],s=14,label=str(summaries[key]["segments_per_span"])+" seg/span",color=color,alpha=.8)
    axes[1].set(xlabel="Frequency (Hz)",ylabel="Tower share of modal kinetic energy (%)",xlim=(0,3),title="Most low modes belong to cables");axes[1].legend()
    for ax in axes:ax.grid(alpha=.25)
    for ext in ("png","svg","pdf"):fig.savefig(root/f"modal_participation.{ext}",dpi=170)
    plt.close(fig)
    key=primary_key;d=data[key];geom=json.loads((runs/key/"geometry.json").read_text());coords=d["gravity_coordinates"]
    chosen=[1,2,5]+[r["mode"] for r in matches[key]]
    fig=plt.figure(figsize=(13,8),layout="constrained")
    for plot,mode in enumerate(chosen,1):
        shape=d["vectors"][mode-1,:,:3]
        tower_only=plot>3;edges=[e for e in geom["edges"] if not tower_only or e[2]=="tower"]
        ns=sorted({n for e in edges for n in e[:2]});amplitude=3 if tower_only else 20
        scale=amplitude/np.linalg.norm(shape[ns],axis=1).max();deformed=coords+scale*shape
        if tower_only:
            ax=fig.add_subplot(2,3,plot,projection="3d")
            ax.add_collection3d(Line3DCollection([[coords[a],coords[b]] for a,b,g in edges],colors="#b6c1c9",linewidths=.5))
            ax.add_collection3d(Line3DCollection([[deformed[a],deformed[b]] for a,b,g in edges],colors="#14816d",linewidths=.8))
            positions=np.vstack((coords[ns],deformed[ns]));low=positions.min(axis=0);high=positions.max(axis=0)
            for setlim,a,b in zip((ax.set_xlim,ax.set_ylim,ax.set_zlim),low,high):setlim(a-1,b+1)
            ax.set_box_aspect(np.maximum(high-low,5));ax.view_init(elev=20,azim=-58)
            for axis in (ax.xaxis,ax.yaxis,ax.zaxis):axis.set_major_locator(MaxNLocator(3))
            ax.set(xlabel="X (m)",ylabel="Y (m)",zlabel="Z (m)")
        else:
            ax=fig.add_subplot(2,3,plot);component=0 if plot<3 else 2
            cable_edges=[e for e in edges if e[2]=="cable"]
            for points,color in ((coords,"#b6c1c9"),(deformed,"#14816d")):
                ax.add_collection(LineCollection([[points[a,[1,component]],points[b,[1,component]]] for a,b,g in cable_edges],colors=color,linewidths=1.3))
            ax.autoscale();ax.axvline(0,color="#6b7e8a",linestyle=":",linewidth=.8)
            ax.set(xlabel="Along-line Y (m)",ylabel="Transverse X (m)" if component==0 else "Vertical Z (m)")
            ax.grid(alpha=.25)
        row=primary["modes"][mode-1]
        ax.set_title(f'Mode {mode}: {row["frequency_Hz"]:.4f} Hz\nTower kinetic share {100*row["tower_kinetic_share"]:.3g}%',fontsize=9)
    fig.suptitle(f"{primary['segments_per_span']}-segment model: grey = gravity geometry; green = mode shape. Top cable projections / bottom tower 3D; scales differ.",fontsize=10)
    for ext in ("png","svg","pdf"):fig.savefig(root/f"mode_shapes.{ext}",dpi=170)
    plt.close(fig)
    render_html(root,summary)
    return summary


def render_html(root,s):
    CASES=tuple(s["case_keys"]);LABELS=tuple(s.get("case_labels",dict(zip(CASES,CASES)))[k] for k in CASES)
    primary=s["cases"][s["primary_case"]];rows=[]
    for i,name in enumerate(MODE_NAMES):
        base=s["cases"][CASES[0]]["modes"][i];v=s["tower_matches"][s["primary_case"]][i]
        rows.append(f'<tr><td>{name}</td><td>{base["frequency_Hz"]:.6f}</td><td>{v["mode"]}</td><td>{v["frequency_Hz"]:.6f}</td><td>{v["change_from_bare_percent"]:+.4f}%</td><td>{v["tower_MAC"]:.8f}</td><td>{100*v["tower_kinetic_share"]:.2f}%</td></tr>')
    lowrows=[]
    for v in primary["modes"][:12]:
        lowrows.append(f'<tr><td>{v["mode"]}</td><td>{v["frequency_Hz"]:.6f}</td><td>{v["period_s"]:.4f}</td><td>{v["dominant_translation"]}</td><td>{100*v["tower_kinetic_share"]:.6f}%</td><td>{100*v["effective_mass_ratio_X"]:.4f}%</td><td>{100*v["effective_mass_ratio_Y"]:.4f}%</td></tr>')
    meshrows=[]
    for v in s["mesh_checks"]:
        meshrows.append(f'<tr><td>{s["cases"][v["from"]]["segments_per_span"]}→{s["cases"][v["to"]]["segments_per_span"]}</td><td>{v["first_six_max_frequency_change_percent"]:.4f}%</td><td>'+" / ".join(f'{x:+.4f}%' for x in v["matched_tower_frequency_change_percent"])+"</td><td>"+" / ".join(f'{100*x:+.2f}个百分点' for x in v["matched_tower_kinetic_share_change"])+"</td></tr>")
    candidate_rows=[]
    for key in CASES[1:]:
        for v in s["tower_like_candidate_modes"][key][1]:
            candidate_rows.append(f'<tr><td>{s["cases"][key]["segments_per_span"]}</td><td>{v["mode"]}</td><td>{v["frequency_Hz"]:.6f}</td><td>{100*v["tower_kinetic_share"]:.2f}%</td><td>{100*v["effective_mass_ratio_X"]:.2f}%</td></tr>')
    free=primary['free_mass_XYZ_kg'][0];total=primary['gravity_total_mass_kg'];f1=primary['modes'][0]['frequency_Hz']
    template=Path(__file__).with_name("modal_viewer.html").read_text()
    values={"FIRST":f'{f1:.6f}',"PERIOD":f'{1/f1:.4f}',"MASS":f'{total:.3f}',"FREE":f'{free:.3f}',
        "TABLE":"".join(rows),"LOWTABLE":"".join(lowrows),"MESHTABLE":"".join(meshrows),"CANDIDATES":"".join(candidate_rows),
        "CUM":" / ".join(f'{100*v:.2f}%' for v in primary['cumulative_mass_ratio_XYZ']),
        "CHECKS":"；".join(f'{escape(LABELS[i])}：正交误差{v["orthogonality_max_error"]:.2e}，特征方程残差{v["eigen_equation_relative_residual_max"]:.2e}' for i,v in enumerate(s['cases'].values())),
        "DOWNLOADS":"".join(f'<li>{escape(label)}：<a href="runs/{key}/modes.csv">频率和参与质量CSV</a> · <a href="runs/{key}/eigenvectors.npz">全部六自由度振型NPZ</a> · <a href="runs/{key}/summary.json">参数与检查</a> · <a href="runs/{key}/opensees_modal_properties.txt">OpenSees原始模态报告</a></li>' for key,label in zip(CASES,LABELS))}
    matching=s.get("publication_config",{}).get("matching",{"mac_min":.9,"tower_share_min":.005})
    values.update(PRIMARY_SEGMENTS=str(primary["segments_per_span"]),PRIMARY_MODES=str(len(primary["modes"])),
        CASE_OPTIONS="".join(f'<option value="{k}"'+(' selected' if k==s['primary_case'] else '')+f'>{escape(l)}</option>' for k,l in reversed(tuple(zip(CASES,LABELS)))),
        CASE_LIST=" / ".join(escape(l) for l in LABELS),MATCH_MAC=str(matching["mac_min"]),
        MATCH_SHARE=f'{100*matching["tower_share_min"]:g}')
    if not s.get("publication_config",{}).get("source"):
        template=template.replace('href="../verification.json"','href="verification.json"')
    for name,value in values.items():template=template.replace('__'+name+'__',value)
    (root/"index.html").write_text(template,encoding="utf-8")


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True)
    p.add_argument("--manifest",type=Path,help="Versioned source cases and matching config; requires new output")
    args=p.parse_args();publish(args.output,args.manifest)
