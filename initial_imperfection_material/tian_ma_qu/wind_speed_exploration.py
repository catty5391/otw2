"""Exploratory monotonic wind ramp with numerical-boundary sensitivity checks.

Not an engineering ultimate wind speed: the existing aerodynamic assumptions
and TMQ angle-steel transfer are uncalibrated. Nonconvergence is not collapse.
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

from .directional_loading import verification_config
from .wind_angle_verification import case_key, write_json
from util.processing.directional_wind import wind_unit_vector

ROOT=Path(__file__).resolve().parents[2]
ANGLES=(0,30,45,90)
MODES=("single_tower","tower_line_explicit")


def speed_from_factor(reference,factor):
    reference,factor=float(reference),float(factor)
    if not math.isfinite(reference) or reference<=0 or not math.isfinite(factor) or factor<0:
        raise ValueError("positive reference speed and finite nonnegative factor required")
    return reference*math.sqrt(factor)


def read_csv(path):
    with path.open(newline="",encoding="utf-8") as f: return list(csv.DictReader(f))


def audit_path(directory,rows,summary):
    """Read committed evidence only; never treat failed trial states as response."""
    audit={}
    if (directory/"support_reactions.csv").is_file() and (directory/"wind_load_plan.json").is_file():
        plan=json.loads((directory/"wind_load_plan.json").read_text())
        forces=plan["combined_initial_coordinate_resultant"]["force_N"]
        by_step={}
        for r in read_csv(directory/"support_reactions.csv"):
            sums=by_step.setdefault(int(r["step"]),[0.,0.,0.])
            for i,k in enumerate(("Rx_N","Ry_N","Rz_N")):sums[i]+=float(r[k])
        errors=[]
        for r in rows:
            if int(r["step"]) not in by_step:continue
            for i,reaction in enumerate(by_step[int(r["step"]) ]):
                external=float(r["wind_load_factor"])*forces[i]
                if i==2:external-=9.81*summary["total_gravity_mass_kg"]
                errors.append(abs(reaction+external))
        audit["global_XYZ_reaction_balance_max_N"]=max(errors,default=None)
        audit["support_states_complete"]=len(by_step)==len(rows)
    if (directory/"line_history.csv").is_file():
        values=[float(r["axial_force_N"]) for r in read_csv(directory/"line_history.csv")]
        audit["minimum_cable_axial_force_N"]=min(values,default=None)
        audit["all_recorded_cables_in_tension"]=bool(values) and min(values)>0
    def slope(points):
        xs=[float(r["along_wind_displacement_m"]) for r in points]
        ys=[float(r["wind_load_factor"]) for r in points]
        if not xs:return None
        xm,ym=sum(xs)/len(xs),sum(ys)/len(ys)
        denominator=sum((v-xm)**2 for v in xs)
        return sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/denominator if denominator>1e-20 else None
    if rows and "along_wind_displacement_m" in rows[0]:
        initial,end=slope(rows[:6]),slope(rows[-6:])
        audit["end_to_initial_load_displacement_slope_ratio"]=end/initial if initial and end is not None else None
        audit["slope_definition"]="OLS lambda versus along-wind displacement in first/last six committed points; diagnostic only, not a stability criterion"
    parameter_file=directory/"model_data/tmq_member_parameters.csv"
    if rows and parameter_file.is_file() and (directory/"member_states.csv.gz").is_file():
        params={int(r["element_tag"]):r for r in read_csv(parameter_file)}
        last_step=int(rows[-1]["step"]);closest=[];buckled=[];tension=[]
        with gzip.open(directory/"member_states.csv.gz","rt") as f:
            for r in csv.DictReader(f):
                if int(r["step"])!=last_step:continue
                tag=int(r["element_tag"]);p=params[tag];stress=float(r["stress_Pa"])
                if int(r["buckling_count"])>0:buckled.append(tag)
                elif stress<0:
                    closest.append({"element_tag":tag,"section":p["section_name"],
                        "compression_to_phi_fy":-stress/(float(p["phi"])*float(p["yield_stress"])),
                        "stress_Pa":stress,"stage":r["stage"]})
                if stress>0:tension.append(stress/float(p["yield_stress"]))
        audit["last_buckled_member_tags"]=buckled
        audit["last_unbuckled_compression_nearest_threshold"]=sorted(closest,key=lambda r:r["compression_to_phi_fy"],reverse=True)[:5]
        audit["maximum_last_tensile_stress_to_fy"]=max(tension,default=0.)
    return audit


def run_case(root,mode,angle,*,increment=.5,suffix="",ceiling=140,continuation_target=None):
    key=case_key(mode,angle)+suffix
    config=verification_config(angle,mode=mode)
    config_path=root/"configs"/f"{key}.json"
    write_json(config_path,config)
    direction=wind_unit_vector(angle)
    control=1 if abs(direction[0])>=abs(direction[1]) else 2
    command=[sys.executable,"-m","initial_imperfection_material.tian_ma_qu.full_tower",
        "--output",str(root/"runs"/key),"--wind-config",str(config_path),"--control-dof",str(control),
        "--timeout","600","--record-nodes"]
    if continuation_target is None:
        speeds=list(range(10,int(ceiling)+1,5))
        if speeds[-1]!=ceiling: speeds.append(ceiling)
        command += ["--wind-speed-targets",*map(str,speeds),"--maximum-load-increment",str(increment),
                    "--minimum-load-increment","0.0001","--drift-guard","0.03"]
    else:
        command += ["--targets",str(continuation_target),"--maximum-increment","0.0025",
                    "--minimum-increment","0.00001"]
    env=os.environ.copy();env.setdefault("CXX","/usr/bin/g++-13")
    timed_out=False
    with (root/"logs"/f"{key}.log").open("w",encoding="utf-8") as log:
        try:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=780)
            code=result.returncode
        except subprocess.TimeoutExpired:
            code=None;timed_out=True
    record={"key":key,"mode":mode,"wind_angle_deg":angle,"control_dof":control,
            "load_factor_increment":increment if continuation_target is None else None,
            "continuation_target_control_drift":continuation_target,"process_returncode":code,
            "process_timed_out":timed_out,"command":command}
    write_json(root/"logs"/f"{key}_execution.json",record)
    summary_path=root/"runs"/key/"summary.json"
    if summary_path.is_file():
        s=json.loads(summary_path.read_text())
        record["run_status"]=s.get("status");record["stop_reason"]=s.get("stop_reason")
        record["last_speed_m_s"]=speed_from_factor(20,s["last_point"]["wind_load_factor"]) if s.get("last_point",{}).get("wind_load_factor",-1)>=0 else None
    print(json.dumps(record,ensure_ascii=False),flush=True)
    return record


def collect_case(root,execution):
    directory=root/"runs"/execution["key"]
    sp=directory/"summary.json"
    s=json.loads(sp.read_text()) if sp.exists() else {"status":"missing"}
    rows=read_csv(directory/"history.csv") if (directory/"history.csv").exists() else []
    eq=[json.loads(v) for v in (directory/"equilibrium.jsonl").read_text().splitlines()] if (directory/"equilibrium.jsonl").exists() else []
    ref=s.get("directional_wind",{}).get("wind_speed_m_s",20.)
    for row in rows:
        factor=float(row["wind_load_factor"])
        row["equivalent_wind_speed_m_s"]=speed_from_factor(ref,factor) if factor>=0 else None
    valid=(bool(rows) and len(rows)==s.get("accepted_steps",-1)+1 and len(eq)==len(rows)
           and all(e["passed"] for e in eq) and s.get("status") in {"complete","partial"}
           and not execution["process_timed_out"] and execution["process_returncode"] in (0,2))
    first=s.get("first_buckling")
    point=max((r for r in rows if r["equivalent_wind_speed_m_s"] is not None),
              key=lambda r:r["equivalent_wind_speed_m_s"],default=None)
    # A sampled decline alone is evidence of a path peak, NOT proof of the
    # first loss of stability or the physical collapse capacity.
    peak_followed_by_decline=False
    if point is not None and execution["continuation_target_control_drift"] is not None:
        after=rows[rows.index(point)+1:]
        peak_factor=float(point["wind_load_factor"])
        peak_followed_by_decline=peak_factor>0 and any(float(r["wind_load_factor"])<.98*peak_factor for r in after)
    reason=s.get("stop_reason")
    if not valid: label="invalid_or_incomplete_evidence"
    elif peak_followed_by_decline: label="sampled_path_peak_with_decline_not_certified_collapse"
    elif s.get("status")=="complete": label="requested_range_completed_limit_not_established"
    elif reason=="minimum_increment": label="numerical_boundary_not_collapse"
    else: label="guard_or_budget_stop_not_capacity"
    result={**execution,"run":s,"history":rows,"evidence_valid":valid,"classification":label,
            "peak_point":point,"last_point":rows[-1] if rows else None,
            "first_buckling_speed_m_s":speed_from_factor(ref,first["wind_load_factor"]) if first and first["wind_load_factor"]>=0 else None,
            "first_buckling_members":first["element_tags"] if first else [],
            "sampled_path_peak_with_decline":peak_followed_by_decline,
            "true_ultimate_wind_speed_m_s":None,
            "artifacts_sha256":{name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                for name in ("summary.json","history.csv","attempts.jsonl","equilibrium.jsonl") if (directory/name).exists()}}
    result["path_audit"]=audit_path(directory,rows,s)
    return result


def publish(root,executions,*,workflow_status="complete"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cases=[collect_case(root,e) for e in executions]
    coarse=[c for c in cases if c["key"]==case_key(c["mode"],c["wind_angle_deg"])]
    summary={"schema_version":1,"analysis":"conditional_wind_speed_limit_exploration","workflow_status":workflow_status,
        "cases":cases,"coarse_case_count":len(coarse),"all_saved_evidence_valid":all(c["evidence_valid"] for c in cases),
        "actual_execution_counts":{"initial":len(coarse),
            "extended":sum(c["key"].endswith("_extended") for c in cases),
            "half_increment":sum(c["key"].endswith("_fine") for c in cases),
            "displacement_control":sum(c["key"].endswith("_disp") for c in cases)},
        "engineering_ultimate_wind_speed_established":False,
        "modeled_static_path_peak_with_decline_observed":any(c["sampled_path_peak_with_decline"] for c in cases),
        "speed_interpretation":"Equivalent UNIFORM static wind under fixed uncalibrated aerodynamic assumptions, NOT 10-m terrain-adjusted wind or a turbulent dynamic collapse wind",
        "mapping":"U=20*sqrt(lambda),lambda>=0; gravity constant; all tower and cable reference forces scaled together",
        "limitations":["Same prototype all-rod proxy, Cx=Cy=Cd=1, yaw gain=0.2; no shielding or validated angle-steel TMQ calibration",
            "One tower, with or without four fixed-end cable spans; not complete multi-tower/phase/bundle/ground-wire model",
            "No damage/fracture/deletion or verified collapse criterion; nonconvergence and guard limits are separate from capacity",
            "Aerodynamics frozen; no turbulent time histories, aerodynamic damping or geometry-updated wind forces",
            "3% horizontal-drift guard is a computational bound, NOT a paper-derived failure criterion"],
        "protocol":"Monotonic 10..140 m/s targets in 5 m/s intervals; cases reaching 140 are independently rerun up to 240 m/s or the 3% drift guard. Adaptive lambda steps .5 to .0001. Per-model earliest numerical endpoint replayed with .25 and displacement control when appropriate.",
        "source_code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_json(root/"summary.json",summary)
    with (root/"case_summary.csv").open("w",encoding="utf-8",newline="") as f:
        writer=csv.writer(f);writer.writerow(("case","mode","angle_deg","classification","first_buckling_U_m_s",
            "last_U_m_s","peak_sampled_U_m_s","last_control_drift","buckled_members","stop_reason","steps"))
        for c in cases:
            last=c["last_point"] or {};peak=c["peak_point"] or {}
            writer.writerow((c["key"],c["mode"],c["wind_angle_deg"],c["classification"],c["first_buckling_speed_m_s"],
                last.get("equivalent_wind_speed_m_s"),peak.get("equivalent_wind_speed_m_s"),last.get("drift_ratio"),
                c["run"].get("max_buckled_members"),c["run"].get("stop_reason"),c["run"].get("accepted_steps")))
    for kind in ("wind_response","pushover_response"):
        fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
        for mode,ax in zip(MODES,axes):
            for c in cases:
                if c["mode"]!=mode or not c["history"]:continue
                rows=[r for r in c["history"] if r["equivalent_wind_speed_m_s"] is not None]
                suffix=" fine" if c["key"].endswith("_fine") else " disp" if c["key"].endswith("_disp") else " extended" if c["key"].endswith("_extended") else ""
                if kind=="wind_response":
                    x=[float(r["along_wind_displacement_m"])*1000 for r in rows]
                    y=[r["equivalent_wind_speed_m_s"] for r in rows]
                else:
                    x=[float(r["along_wind_displacement_m"])*1000 for r in rows]
                    y=[float(r["along_wind_base_shear_N"])/1000 for r in rows]
                color={0:"#2467a7",30:"#d97706",45:"#1c8c73",90:"#a23a80"}[c["wind_angle_deg"]]
                style={" fine":"--"," disp":"-."," extended":":"}.get(suffix,"-")
                ax.plot(x,y,style,color=color,label=f'{c["wind_angle_deg"]} deg{suffix}',linewidth=1.5)
                if rows:ax.scatter(x[-1],y[-1],marker="x",s=35,color=color)
                first=c["run"].get("first_buckling")
                if first:
                    first_x=float(first["along_wind_displacement_m"])*1000
                    first_y=c["first_buckling_speed_m_s"] if kind=="wind_response" else float(first["along_wind_base_shear_N"])/1000
                    if first_y is not None:ax.scatter(first_x,first_y,marker="o",s=30,edgecolor=color,facecolor="white",zorder=4)
            ax.set(title="Bare tower" if mode==MODES[0] else "One tower + 4 fixed-end spans",
                   xlabel="Along-wind displacement (mm)",ylabel="Equivalent static wind (m/s)" if kind=="wind_response" else "Tower-base shear along wind (kN)")
            ax.grid(alpha=.25);ax.legend(fontsize=8)
        fig.suptitle("Conditional prototype: o = first member buckling; x = endpoint, NOT certified collapse",fontsize=11)
        for ext in ("svg","png","pdf"):fig.savefig(root/f"{kind}.{ext}",dpi=170)
        plt.close(fig)
    names={"numerical_boundary_not_collapse":"数值边界，未证明倒塌",
        "sampled_path_peak_with_decline_not_certified_collapse":"路径峰值后有下降，非认证倒塌",
        "requested_range_completed_limit_not_established":"完成指定范围，极限未确定",
        "guard_or_budget_stop_not_capacity":"保护或预算停止，非承载极限",
        "invalid_or_incomplete_evidence":"证据不完整/校核未通过"}
    def value(v):return "—" if v is None else f"{float(v):.2f}"
    table=[]
    for c in cases:
        last=c["last_point"] or {};peak=c["peak_point"] or {};key=html.escape(c["key"])
        table.append(f'<tr><td>{key}</td><td>{value(c["first_buckling_speed_m_s"])}</td>'
            f'<td>{value(peak.get("equivalent_wind_speed_m_s"))}</td><td>{value(last.get("equivalent_wind_speed_m_s"))}</td><td>{value(100*float(last.get("drift_ratio",0)))}</td>'
            f'<td>{c["run"].get("max_buckled_members",0)}</td><td>{names[c["classification"]]}<br>{html.escape(str(c["run"].get("stop_reason")))}</td>'
            f'<td><a href="runs/{key}/history.csv">曲线</a> · <a href="runs/{key}/summary.json">汇总</a> · <a href="runs/{key}/attempts.jsonl">求解尝试</a></td></tr>')
    diagnosis=[]
    for c in cases:
        audit=c["path_audit"];near=audit.get("last_unbuckled_compression_nearest_threshold",[])
        closest="、".join(f'{r["element_tag"]} ({r["compression_to_phi_fy"]:.6f})' for r in near[:2]) or "—"
        bracket=c["run"].get("first_buckling_speed_bracket_m_s")
        interval=f'({bracket[0]:.3f}, {bracket[1]:.3f}]' if bracket else "—"
        diagnosis.append(f'<tr><td>{html.escape(c["key"])}</td><td>{interval}</td><td>{value(audit.get("end_to_initial_load_displacement_slope_ratio"))}</td><td>{closest}</td></tr>')
    sensitivity=[]
    for mode in MODES:
        for angle in ANGLES:
            key=case_key(mode,angle)
            base=next((c for c in cases if c["key"]==key+"_extended"),next((c for c in cases if c["key"]==key),None))
            fine=next((c for c in cases if c["key"]==key+"_fine"),None)
            disp=next((c for c in cases if c["key"]==key+"_disp"),None)
            if not base or not fine:continue
            def endpoint(c):return c["last_point"]["equivalent_wind_speed_m_s"] if c and c["last_point"] else None
            b,f=endpoint(base),endpoint(fine)
            difference=100*(f/b-1) if b and f else None
            peak_speed=disp["peak_point"]["equivalent_wind_speed_m_s"] if disp and disp["peak_point"] else None
            sensitivity.append(f'<tr><td>{key}</td><td>{value(b)}</td><td>{value(f)}</td><td>{value(difference)}%</td><td>{value(peak_speed)}</td><td>{value(endpoint(disp))}</td><td>{"是" if disp and disp["sampled_path_peak_with_decline"] else "未记录到"}</td></tr>')
    text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>等效极限风速探索</title>
<style>body{font:16px/1.8 system-ui;color:#193247;background:#f3f6f9;margin:0}main{max-width:1150px;padding:24px;margin:auto}section{background:white;border-radius:12px;padding:24px;margin:20px 0}img{width:100%}a{color:#007e92}.warn{border-left:5px solid #c78b28;background:#fff6e5;padding:18px}.scroll{overflow:auto}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:14px}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}pre{overflow:auto;background:#eef3f5;padding:12px}</style>
<main><a href="/#tianmaqu">← 返回成果首页</a><h1>单塔与塔线：等效极限风速探索</h1>
<p class="warn">当前不能给出可信的实际工程极限风速。下表是真实求解得到的首次压屈与最后收敛等效风速；求解不收敛不等于结构倒塌。气动力面积/系数及角钢TMQ参数仍未标定，不得将这些数字用于实际线路安全决策。</p>
<section><h2>怎么加载与复核</h2><ol><li>每个工况重建模型、施加重力，并冻结重力。0°横线+X，90°顺线+Y。</li><li>以20m/s均匀静态风为参考，塔身和显式导线共同乘以λ；U=20√λ，而不是风速与荷载线性对应。</li><li>单调追踪10至140m/s，目标间隔5m/s，荷载系数步长最大0.5、最小0.0001，逐步检查自由节点力学平衡并保存全塔内力。</li><li>选各模型最早到达数值边界的方向，将荷载步长减半独立复算；再用位移控制尝试辨认峰后路径。各条曲线独立从重力状态开始，不继承别的风向材料历史。</li></ol><p>“首次压屈”指TMQ轴向等效分支，不是全塔失效。3%水平位移/高度仅是计算保护线，不作为倒塌判据。位移控制下若荷载因子回落，图中的等效风速也会回落，这不是单调增风历史。</p></section>
<section><h2>实际结果</h2><div class="scroll"><table><thead><tr><th>工况</th><th>首次记录压屈U / m/s</th><th>末点U / m/s</th><th>末点控制漂移 / %</th><th>曾压屈杆件</th><th>停止含义</th><th>原始证据</th></tr></thead><tbody>__TABLE__</tbody></table></div><p><a href="summary.json">完整结果JSON</a> · <a href="case_summary.csv">对比CSV</a> · <a href="verification.json">验证记录</a></p></section>
<section><h2>风速—位移全过程</h2><img src="wind_response.svg" alt="各风角等效静态风速随位移的变化及数值停止点"><p>末点×表示实际算到的位置，不能当作已确定的倒塌点。首次压屈事件的相邻采样区间见各工况summary.json。</p></section>
<section><h2>推覆形态</h2><img src="pushover_response.svg" alt="各风角塔基剪力随沿风位移变化"><p>塔线模型还有固定远端分担风荷载，因此塔基剪力不等于全体系风力。峰值、最后收敛点、首次压屈三个概念分别记录。</p></section>
<section><h2>适用范围</h2><p>沿用上一阶段相同模型：单塔或一塔两导线四档300m远端固定体系。塔身使用全杆件边宽投影代理、Cx=Cy=1、斜风修正0.2，导线Cd=1；均匀风场，无遮挡、脉动风和气动阻尼。导线气动力方向冻结于重力构形。没有损伤、断裂或删除，也未校核螺栓、节点板和完整线路极限状态。因此这里只能探索这套假设下的数值边界。</p><pre>CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.wind_speed_exploration --output /tmp/wind_speed_NEW --workers 2</pre></section></main></html>'''
    text=text.replace("单调追踪10至140m/s，目标间隔5m/s", "先追踪10至140m/s；完成范围的方向再独立重算，扩展至240m/s或3%计算保护线。目标间隔5m/s")
    if workflow_status!="complete":
        text=text.replace('<section><h2>实际结果</h2>', '<p class="warn">计算仍在继续：本页先展示已结束工况，半步长与位移控制复核尚未全部完成。最终结果会在本页更新。</p><section><h2>实际结果</h2>')
    counts=summary["actual_execution_counts"]
    actual=f'<p>本页实际收录：{counts["initial"]}个初始方向工况、{counts["extended"]}次范围扩展、{counts["half_increment"]}次半步长复核、{counts["displacement_control"]}次位移控制复核。每例完成情况见下表；计算保护线不代表算例已经达到该线。</p>'
    text=text.replace('<section><h2>实际结果</h2>','<section><h2>实际结果</h2>'+actual)
    text=text.replace('<th>末点U / m/s</th>','<th>路径最大U / m/s</th><th>末点U / m/s</th>')
    peaks=[c for c in cases if c["sampled_path_peak_with_decline"]]
    if peaks:
        finding='<section><h2>本轮测到了什么</h2><p>位移控制已记录到承载峰值及随后下降段，因此本轮结果不只是一组非收敛点。以下峰值属于当前模型及荷载模式，仍不是经标定的工程倒塌风速。</p><ul>'
        for c in peaks:
            p=c["peak_point"];last=c["last_point"]
            decline=100*(1-float(last["wind_load_factor"])/float(p["wind_load_factor"]))
            finding+=f'<li>{"单塔" if c["mode"]=="single_tower" else "一塔四档塔线"} {c["wind_angle_deg"]}°：采样峰值等效风速 <strong>{value(p["equivalent_wind_speed_m_s"])}m/s</strong>，沿风位移{value(1000*float(p["along_wind_displacement_m"]))}mm，塔基沿风剪力{value(float(p["along_wind_base_shear_N"])/1000)}kN；末点荷载系数比该峰值低{value(decline)}%，曾压屈{c["run"].get("max_buckled_members",0)}根、曾进入拉向强化{c["run"].get("max_tensile_yield_members",0)}根。实际停止原因：{html.escape(str(c["run"].get("stop_reason"))) if c["run"].get("stop_reason") else "达到指定控制位移"}。</li>'
        finding+='</ul><p>位移控制曲线的“路径最大U”与“末点U”不同，峰后荷载降低导致换算风速降低；它不是持续增风的动态倒塌过程。峰值取自离散采样，不能据此声称精确失稳风速。</p></section>'
        text=text.replace('<section><h2>怎么加载与复核</h2>',finding+'<section><h2>怎么加载与复核</h2>')
    text=text.replace("末点×表示实际算到的位置，不能当作已确定的倒塌点。", "空心圆表示首次记录杆件压屈；末点×表示实际算到的位置，不能当作已确定的倒塌点。风力随风速平方变化，因此弹性模型的风速—位移曲线也会弯曲；结构刚度变化应看下方荷载—位移图。")
    additions='<section><h2>停止位置复核</h2><div class="scroll"><table><thead><tr><th>方向</th><th>原步长末点U</th><th>半步长末点U</th><th>相对变化</th><th>位移控制路径最大U</th><th>位移控制末点U</th><th>峰后荷载下降超过2%</th></tr></thead><tbody>'+''.join(sensitivity)+'</tbody></table></div><p>单位m/s。半步长保持相同收敛容差和最小增量；位移控制独立从重力态重算。多个求解设置给出相近停止点，也不能单独证明该点是全塔极限。2%只用于识别已采样曲线中的明显下降，不是倒塌阈值。</p></section>'
    additions+='<section><h2>停止之前是什么状态</h2><div class="scroll"><table><thead><tr><th>工况</th><th>首次压屈采样区间 / m/s</th><th>末段/初段荷载—位移斜率</th><th>未压屈杆：最接近φfy的编号与压力比</th></tr></thead><tbody>'+''.join(diagnosis)+'</tbody></table></div><p>斜率以首末各6个已收敛点拟合λ—沿风位移获得，只用于观察曲线是否仍在上升。压力比接近1说明邻近TMQ分支阈值，并非已经证明不收敛的唯一原因。全塔所有接受步的12分量内力、材料状态及六自由度位移均有保存；相应下载见各工况的完整结果JSON及下面证据链接。</p><details><summary>下载各工况完整内力和状态</summary><ul>'+''.join(f'<li>{html.escape(c["key"])}：<a href="runs/{c["key"]}/internal_forces.sqlite">内力数据库</a> · <a href="runs/{c["key"]}/member_states.csv.gz">杆件材料状态</a> · <a href="runs/{c["key"]}/node_states.csv.gz">节点位移</a> · <a href="runs/{c["key"]}/support_reactions.csv">支座反力</a> · <a href="runs/{c["key"]}/wind_load_plan.json">实际风荷载</a></li>' for c in cases)+'</ul></details></section>'
    text=text.replace('<section><h2>适用范围</h2>',additions+'<section><h2>适用范围</h2>')
    (root/"index.html").write_text(text.replace("__TABLE__","".join(table)),encoding="utf-8")
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--workers",type=int,choices=(1,2),default=2);p.add_argument("--coarse-only",action="store_true")
    a=p.parse_args();root=a.output.resolve()
    if root.exists() and any(root.iterdir()):raise FileExistsError(f"Refusing to overwrite {root}")
    for name in ("runs","configs","logs"):(root/name).mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(run_case,root,mode,angle) for mode in MODES for angle in ANGLES]
        executions=[f.result() for f in futures]
    summary=publish(root,executions,workflow_status="complete" if a.coarse_only else "refinement_in_progress")
    if not a.coarse_only:
        completed=[c for c in summary["cases"] if c["evidence_valid"] and c["run"]["status"]=="complete"]
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures=[pool.submit(run_case,root,c["mode"],c["wind_angle_deg"],suffix="_extended",ceiling=240) for c in completed]
            executions.extend(f.result() for f in futures)
        summary=publish(root,executions,workflow_status="refinement_in_progress")
        selected=[]
        for mode in MODES:
            candidates=[c for c in summary["cases"] if c["mode"]==mode and c["evidence_valid"]
                        and c["run"].get("stop_reason")=="minimum_increment"]
            if candidates:selected.append(min(candidates,key=lambda c:c["last_point"]["equivalent_wind_speed_m_s"]))
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures=[pool.submit(run_case,root,c["mode"],c["wind_angle_deg"],increment=.25,suffix="_fine",
                                 ceiling=240 if c["key"].endswith("_extended") else 140) for c in selected]
            executions.extend(f.result() for f in futures)
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures=[pool.submit(run_case,root,c["mode"],c["wind_angle_deg"],suffix="_disp",
                        continuation_target=min(.03,max(.01,1.5*abs(float(c["last_point"]["drift_ratio"]))))) for c in selected]
            executions.extend(f.result() for f in futures)
        summary=publish(root,executions)
    write_json(root/"verification.json",{"all_saved_evidence_valid":summary["all_saved_evidence_valid"],
        "case_count":len(executions),"engineering_ultimate_wind_speed_established":False,
        "unit_tests":"record separately; not inferred from convergence"})
    raise SystemExit(0 if summary["all_saved_evidence_valid"] else 2)


if __name__=="__main__":main()
