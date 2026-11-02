"""Publish V-string sensitivity evidence; compare only recorded common load ranges."""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .insulator_experiment import VARIANTS, write_csv

LABELS = {"elastic":"Elastic (r=1)","tension_only":"Tension only (r=0)","regularized":"Regularized (r=1e-6)"}
COLORS = {"elastic":"#697683","tension_only":"#176b8d","regularized":"#d78327"}
QUANTITY_LABELS = {"top_along_m": "控制节点350沿风位移 (m)",
                   "tower_base_shear_N": "塔脚沿风剪力 (N)",
                   "hanger_max_abs_along_m": "挂点沿风位移最大幅值 (m)",
                   "hanger_max_abs_vertical_m": "挂点竖向位移最大幅值 (m)"}


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def interpolate_recorded(rows, speed, field):
    """No extrapolation beyond a completed recorded prefix."""
    x = np.array([r["speed_m_s"] for r in rows])
    y = np.array([r[field] for r in rows])
    if len(x) < 2 or np.any(np.diff(x) <= 0) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Finite strictly increasing recorded speeds required")
    if speed < x[0]-1e-9 or speed > x[-1]+1e-9:
        raise ValueError("Requested speed outside recorded range")
    return float(np.interp(speed,x,y))


def collect_case(root, execution):
    run = root/"runs"/execution["key"]
    summary = json.loads((run/"summary.json").read_text())
    history, legs = read_csv(run/"history.csv"), read_csv(run/"insulator_history.csv")
    by_step = {}
    for row in legs:
        by_step.setdefault(int(row["step"]),[]).append(row)
    gravity = {int(r["lower_node_tag"]):[float(r[k]) for k in ("lower_ux_m","lower_uy_m","lower_uz_m")] for r in by_step[0]}
    angle = math.radians(execution["wind_angle_deg"])
    direction = (math.cos(angle),math.sin(angle))
    rows = []
    first_event = None
    for row in history:
        step = int(row["step"]); strings = by_step[step]
        if len(strings)!=4 or len({int(r["element_tag"]) for r in strings})!=4:
            raise ValueError(f"Incomplete four-leg recording at {execution['key']} step {step}")
        displacements = {}
        for leg in strings:
            tag = int(leg["lower_node_tag"])
            displacements[tag] = [float(leg[k])-gravity[tag][i] for i,k in enumerate(("lower_ux_m","lower_uy_m","lower_uz_m"))]
        speed = float(row["equivalent_wind_speed_m_s"])
        item = {"case":execution["key"], "step":step, "speed_m_s":speed,
                "top_along_m":float(row["along_wind_displacement_m"]),
                "tower_base_shear_N":float(row["along_wind_base_shear_N"]),
                "hanger_max_abs_along_m":max(abs(d[0]*direction[0]+d[1]*direction[1]) for d in displacements.values()),
                "hanger_max_abs_vertical_m":max(abs(d[2]) for d in displacements.values()),
                "minimum_leg_force_N":min(float(r["axial_force_N"]) for r in strings),
                "buckled_members":int(row["buckled_members"])}
        rows.append(item)
        if first_event is None and any(r["state"] not in {"tension","zero"} for r in strings):
            first_event = {"step":step,"speed_bracket_m_s":[rows[-2]["speed_m_s"] if len(rows)>1 else 0.,speed],
                           "first_saved_speed_m_s":speed,"states":[r["state"] for r in strings]}
    equilibrium = [json.loads(line) for line in (run/"equilibrium.jsonl").read_text().splitlines()]
    if len(rows)!=len(equilibrium) or set(by_step)!={r["step"] for r in rows}:
        raise ValueError("State/force/equilibrium step coverage differs")
    errors = [abs(float(r["force_reconstruction_residual_N"])) for r in legs]
    force_min = min(float(r["axial_force_N"]) for r in legs)
    result = {**execution,"status":summary["status"],"stop_reason":summary.get("stop_reason"),
              "accepted_steps":summary["accepted_steps"],"last":rows[-1],"first_loss_of_taut_leg":first_event,
              "all_equilibrium_checks_passed":all(r["passed"] for r in equilibrium),
              "force_reconstruction_max_error_N":max(errors),"minimum_leg_force_N":force_min,
              "tension_only_no_compression_passed":force_min>=-1e-5 if execution["variant"]=="tension_only" else None,
              "gravity_total_mass_kg":summary["total_gravity_mass_kg"],
              "gravity_leg_forces_N":[float(r["axial_force_N"]) for r in by_step[0]],
              "insulator_assumptions":summary["line_model"]["insulator_assumptions"],
              "source_sha256":summary["directional_input_sha256"]}
    return result, rows


def save_fig(fig, root, name):
    fig.tight_layout()
    for ext in ("svg","png","pdf"):
        fig.savefig(root/f"{name}.{ext}",dpi=160,bbox_inches="tight")
    plt.close(fig)


def create_figures(root, cases):
    plt.rcParams.update({"font.size":10,"axes.grid":True,"grid.alpha":.22,"axes.spines.top":False,"axes.spines.right":False})
    fig,axes=plt.subplots(1,3,figsize=(15,4.4))
    for variant in VARIANTS:
        rows=read_csv(root/"standalone"/f"{variant}.csv")
        color=COLORS[variant]; style="--" if variant=="regularized" else "-"
        axes[0].plot([float(r["ux_m"])*1000 for r in rows],[float(r["horizontal_force_N"])/1000 for r in rows],style,color=color,label=LABELS[variant])
        axes[1].plot([float(r["horizontal_to_vertical_ratio"]) for r in rows],[min(float(r["left_force_N"]),float(r["right_force_N"]))/1000 for r in rows],style,color=color)
        peak=max(rows,key=lambda r:float(r["horizontal_to_vertical_ratio"]))
        x,z=float(peak["ux_m"]),-4+float(peak["uz_m"])
        axes[2].plot([-8.675,x,8.675],[0,z,0],style,color=color,label=LABELS[variant])
        axes[2].scatter([x],[z],color=color,s=25)
    axes[0].set(xlabel="Hanger displacement (mm)",ylabel="Horizontal force (kN)",title="Complete reversible loading paths")
    axes[0].legend(fontsize=8)
    axes[1].set(xlabel="Horizontal / vertical load",ylabel="Minimum leg force (kN)",title="Compression release")
    axes[1].axhline(0,color="black",lw=.5)
    axes[2].set(xlabel="X (m)",ylabel="Z (m)",title="H/W=3; chords only, not bent shapes",aspect="equal")
    fig.suptitle("Uncalibrated V-string assumptions | W=5 kN, EA=100 MN",y=1.04)
    save_fig(fig,root,"standalone_comparison")
    fig,axes=plt.subplots(3,2,figsize=(13,10))
    for c,angle in enumerate((0,45)):
        for variant in VARIANTS:
            rows=cases[f"{variant}_{angle}"]
            x=[r["speed_m_s"] for r in rows]
            for row,(field,scale,label) in enumerate((("top_along_m",1000,"Tower control displacement (mm)"),
                                                    ("hanger_max_abs_along_m",1,"Max |hanger along-wind motion| (m)"),
                                                    ("minimum_leg_force_N",.001,"Minimum V-string leg force (kN)"))):
                axes[row,c].plot(x,[r[field]*scale for r in rows],"--" if variant=="regularized" else "-",color=COLORS[variant],label=LABELS[variant])
                axes[row,c].set(xlabel="Equivalent static wind speed (m/s)",ylabel=label)
                axes[row,c].set_title(f"{angle} degrees")
        axes[0,c].legend(fontsize=8)
        axes[2,c].axhline(0,color="black",lw=.5)
    fig.suptitle("One tower / four spans: insulator-law sensitivity (not ultimate wind speed)",y=1.01)
    save_fig(fig,root,"tower_comparison")


def publish(root):
    root=Path(root)
    if (root/"summary.json").exists():
        raise FileExistsError("Publication already exists; preserve it and use a new output")
    executions=json.loads((root/"execution.json").read_text())
    expected={f"{v}_{a}" for v in VARIANTS for a in (0,45)}
    if len(executions)!=6 or {e["key"] for e in executions}!=expected:
        raise ValueError("Six explicit sensitivity cases required")
    summaries=[];cases={}
    for execution in executions:
        result,rows=collect_case(root,execution);summaries.append(result);cases[execution["key"]]=rows
    comparisons=[]
    for angle in (0,45):
        for variant,reference in (("tension_only","elastic"),("regularized","tension_only")):
            candidate,baseline=cases[f"{variant}_{angle}"],cases[f"{reference}_{angle}"]
            upper=min(candidate[-1]["speed_m_s"],baseline[-1]["speed_m_s"])
            for speed in (20.,40.,50.,60.,70.,80.,90.,100.):
                if speed>upper+1e-9:continue
                for field in ("top_along_m","tower_base_shear_N","hanger_max_abs_along_m","hanger_max_abs_vertical_m"):
                    value=interpolate_recorded(candidate,speed,field);ref=interpolate_recorded(baseline,speed,field)
                    comparisons.append({"angle_deg":angle,"candidate":variant,"reference":reference,
                                        "speed_m_s":speed,"quantity":field,"reference_value":ref,"candidate_value":value,
                                        "difference":value-ref,"relative_difference":(value-ref)/abs(ref) if abs(ref)>1e-8 else None})
    standalone=json.loads((root/"standalone/summary.json").read_text())
    result={"schema":"otw2.insulator_sensitivity.v1","physical_validation":"unvalidated",
            "actual_geometry_and_string_type_confirmed":False,"standalone":standalone,"cases":summaries,
            "all_cases_complete":all(s["status"]=="complete" and s["returncode"]==0 for s in summaries),
            "all_equilibrium_checks_passed":all(s["all_equilibrium_checks_passed"] for s in summaries),
            "comparison_scope":"common recorded speeds only; no extrapolation or certified collapse wind speed",
            "comparisons":comparisons}
    write_csv(root/"response_history.csv",[r for rows in cases.values() for r in rows])
    write_csv(root/"comparisons.csv",comparisons)
    (root/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    create_figures(root,cases)
    table=[]
    for s in summaries:
        event=s["first_loss_of_taut_leg"]
        table.append(f"| {s['key']} | {s['status']} | {s['accepted_steps']} | {s['last']['speed_m_s']:.2f} | {event['first_saved_speed_m_s']:.2f}"+f" | {s['minimum_leg_force_N']/1000:.4f} |" if event else
                     f"| {s['key']} | {s['status']} | {s['accepted_steps']} | {s['last']['speed_m_s']:.2f} | 未发生 | {s['minimum_leg_force_N']/1000:.4f} |")
    at100=[c for c in comparisons if c["speed_m_s"]==100 and c["candidate"]=="tension_only"]
    deltas="\n".join(f"| {c['angle_deg']} | {QUANTITY_LABELS[c['quantity']]} | {c['reference_value']:.6g} | {c['candidate_value']:.6g} | {100*c['relative_difference']:.3f}% |" for c in at100 if c['relative_difference'] is not None)
    report=f"""# V形绝缘子受压/松弛敏感性试验（2026-10-24）

本批是现有单塔四跨模型的受力假设对照，实际绝缘子型号、抗压/屈曲能力、挂点与串长尚未确认。
原始数据仅保留本地；方法、结论和代码可同步Git。0～100 m/s是静态等效加载比较范围，终点不是极限风速。

## 实施步骤与方法

1. 复核原几何：上挂点相距17.35 m、垂向落差4 m，每肢9.552781 m、夹角130.4916°。没有将落差误改成串长。
2. 增加三种显式轴向假设：原弹性杆r=1；仅受拉r=0；微小压缩刚度r=1e-6。保持EA=100 MN、质量、几何、导线、塔材和风系数一致。
3. 用OpenSees `Elastic(E,0,Eneg)` 的独立压缩模量实现N=EA·ε（ε≥0），N=r·EA·ε（ε<0）。
   仅受拉支可逆，无塑性记忆；松弛支的ε为端点弦长变化，不能解释为实际瓷件/芯棒材料压应变。
4. 独立二维V串先施加5 kN竖向力，再完整加载H/W=0→1→2→2.2→3→0→−3→0；记录每个收敛步。
5. 仅一肢受拉时，以上挂点中点为原点、左上挂点为(-a,0)（正水平加载），T=√(H²+W²)、L=L₀(1+T/EA)，下挂点坐标为(x,z)=(-a+LH/T,-LW/T)。
   检查另一肢端距≤L₀后才使用该解析解；两肢仍受拉时不套用它。仅受拉峰值位置误差为{standalone[1]['analytical_position_error_m']:.3g} m，完整往复后回到重力位置的误差为{standalone[1]['return_to_gravity_position_error_m']:.3g} m。
6. 六个全塔算例在隔离进程中运行；每跨20段，与既有风速探索保持一致。记录控制节点350的位移，并投影至0°、45°风向；采用荷载控制。
   单步荷载倍率上限0.25、下限0.0001；以自适应LoadControl逐级加载至100 m/s。此处未重新证明大变形网格收敛。
7. 每步新增四肢原生轴力、端距、应变、受拉/受压/松弛状态和挂点三向位移；用独立端距公式复核原生轴力。
   塔脚与远端反力共同参与平衡检查；比较只在双方已保存的共同风速区间内进行。

## 全塔结果

| 工况 | 状态 | 接受步数 | 最后风速 m/s | 首次记录非受拉肢 m/s | 最小肢杆力 kN |
| --- | --- | ---: | ---: | ---: | ---: |
{chr(10).join(table)}

全部工况完成：{result['all_cases_complete']}；全部保存状态平衡检查通过：{result['all_equilibrium_checks_passed']}。
首次记录事件是离散采样，准确区间见summary.json中的speed_bracket_m_s，不称断裂或倒塌。

## 100 m/s共同点：仅受拉相对原弹性杆

位移单位m，剪力单位N；相对差是两种假设的差异，不是真实工程误差。
CSV中的top_along_m为控制节点350沿风位移，不泛指整塔最高点；全部位移相对重力平衡状态。

| 风角 | 量 | 原弹性杆 | 仅受拉 | 相对变化 |
| --- | --- | ---: | ---: | ---: |
{deltas}

## 结论与下一步

本批检验了受压假设对传力与位移的影响，没有证明仅受拉一定是本塔真实绝缘子的正确模型。
微小压缩刚度只用于数值敏感性，不能当成实测抗压刚度或压屈承载力；应以严格r=0结果为该理想假设的基准。
已保存数据中的塔材压屈仍沿用未按本塔角钢定量标定的TMQ原型，风系数亦未按实际线路校准。
下一步先取得绝缘子型号/挂线图：盘形串可进一步核对松弛假设，棒形复合串需依据芯棒与金具构造补充受压弯曲/压屈规律；
随后校核真实导线分裂数、地线和远端柔度，并针对选定模型做40/80段大变形对照，再开展模态扩阶与时程。

## 文献与复现

- [OpenSees Elastic材料文档](https://openseespydoc.readthedocs.io/en/latest/src/ElasticUni.html)：独立Eneg参数。
- [周超等，2021，风载荷作用下V形绝缘子串的力学特性分析](https://qikan.cmes.org/gcsjxb/CN/10.3785/j.issn.1006-754X.2021.00.001)：研究复合绝缘子受压屈曲及结构形式影响；本文未借其数值直接标定当前塔。
- [赵芳瀷等，2016，特高压输电线路V型绝缘子串动力学特性数值仿真研究](https://pubs.cstam.org.cn/article/doi/10.11776/cjam.33.04.C009)：索单元串线耦合以及串轴力、挂点位移的评价思路。

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.insulator_experiment --output /tmp/insulator_new --tower
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.publish_insulators --output /tmp/insulator_new
```

执行命令和返回码在execution.json；逐工况日志在logs/；全部原始CSV、SQLite、节点记录在runs/。
[完整对比表](comparisons.csv) · [抽取响应历程](response_history.csv) · [机器可读汇总](summary.json)
"""
    (root/"REPORT.md").write_text(report)
    body="".join(f"<tr><td>{html.escape(s['key'])}</td><td>{s['status']}</td><td>{s['accepted_steps']}</td><td>{s['last']['speed_m_s']:.2f}</td><td>{s['minimum_leg_force_N']/1000:.3f}</td></tr>" for s in summaries)
    page=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V形绝缘子受压与松弛对照</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1200px;margin:30px auto;padding:0 18px;color:#203340;background:#f4f7f9}}section{{background:white;padding:22px;margin:18px 0;border-radius:12px}}img{{width:100%;height:auto}}.note{{border-left:4px solid #c77b26;padding:12px;background:#fff3df}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;border-bottom:1px solid #d9e2e8;padding:9px}}a{{color:#176b8d}}.scroll{{overflow:auto}}</style>
<a href="/#tianmaqu">← 返回成果首页</a><h1>V形绝缘子受压与松弛对照</h1>
<p class="note">保留原几何，比较三种轴向假设。实际绝缘子类型与受压能力尚未确认；100 m/s为本轮比较上限，不是极限风速。</p>
<section><h2>独立V串：完整往复与解析检查</h2><p>仅受拉模型的位置与解析解误差：{standalone[1]['analytical_position_error_m']:.2g} m。图中的线表示端点连线，不代表松弛后的真实弯曲形状。</p><img src="standalone_comparison.svg" alt="独立V串三种假设的完整往复、轴力和几何对比"><a href="standalone_comparison.png">PNG</a> · <a href="standalone_comparison.pdf">PDF</a></section>
<section><h2>单塔四跨：0°与45°</h2><img src="tower_comparison.svg" alt="六个全塔算例的控制点位移、挂点位移与绝缘子轴力"><a href="tower_comparison.png">PNG</a> · <a href="tower_comparison.pdf">PDF</a><div class="scroll"><table><thead><tr><th>工况</th><th>状态</th><th>步数</th><th>最后风速 m/s</th><th>最小肢杆力 kN</th></tr></thead><tbody>{body}</tbody></table></div></section>
<section><h2>步骤、结论与数据</h2><a href="REPORT.md">完整报告</a> · <a href="comparisons.csv">共同风速对比CSV</a> · <a href="response_history.csv">响应历程CSV</a> · <a href="summary.json">汇总JSON</a><p>只比较已计算共同区间；数值模型差异不能直接解释为真实工程误差。原始数据仅保留本地。</p></section></html>"""
    (root/"index.html").write_text(page)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();result=publish(args.output)
    print(json.dumps({"all_cases_complete":result["all_cases_complete"],"equilibrium_passed":result["all_equilibrium_checks_passed"]}))
