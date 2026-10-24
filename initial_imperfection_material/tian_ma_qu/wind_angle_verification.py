"""Run independent single-tower / one-tower cable verification cases and publish.

All aerodynamic inputs are explicit verification assumptions, not calibrated
design loads. Each FE case has its own PROCESS, gravity and material history.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import html
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from .directional_loading import verification_config
from util.processing.directional_wind import wind_unit_vector

ROOT = Path(__file__).resolve().parents[2]
ANGLES = (0,30,45,90)
MODES = ("single_tower","tower_line_explicit")


def write_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def case_key(mode,angle):
    return f"{'single' if mode=='single_tower' else 'tower_line'}_{int(angle)}"


def _execute(task):
    root,mode,angle = task
    key = case_key(mode,angle)
    config = verification_config(angle,mode=mode)
    config_file=root/"configs"/f"{key}.json"
    write_json(config_file,config)
    direction=wind_unit_vector(angle)
    control=1 if abs(direction[0]) >= abs(direction[1]) else 2
    command=[sys.executable,"-m","initial_imperfection_material.tian_ma_qu.full_tower",
             "--output",str(root/"runs"/key),"--wind-config",str(config_file),"--control-dof",str(control),
             "--record-nodes","--targets","0.0001","-0.0001","0","--timeout","180"]
    env=os.environ.copy()
    env.setdefault("CXX","/usr/bin/g++-13")
    timed_out=False
    with (root/"logs"/f"{key}.log").open("w",encoding="utf-8") as log:
        try:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
            exit_code=result.returncode
        except subprocess.TimeoutExpired:
            timed_out=True
            exit_code=None
    info={"key":key,"mode":mode,"wind_angle_deg":angle,"control_dof":control,
          "process_returncode":exit_code,"process_timed_out":timed_out,"command":command}
    print(json.dumps(info,ensure_ascii=False),flush=True)
    return info


def publish(root,executions):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cases=[]
    for execution in executions:
        key=execution["key"]
        directory=root/"runs"/key
        summary_path=directory/"summary.json"
        run=json.loads(summary_path.read_text()) if summary_path.exists() else {"status":"missing"}
        plan_path=directory/"wind_load_plan.json"
        plan=json.loads(plan_path.read_text()) if plan_path.exists() else None
        history_path=directory/"history.csv"
        history=list(csv.DictReader(history_path.open())) if history_path.exists() else []
        equilibrium_path=directory/"equilibrium.jsonl"
        eqs=[json.loads(r) for r in equilibrium_path.read_text().splitlines()] if equilibrium_path.exists() else []
        completed=(execution["process_returncode"]==0 and not execution["process_timed_out"]
                   and run.get("status")=="complete" and run.get("completed_targets")==3
                   and len(history)==run.get("accepted_steps",-1)+1
                   and len(eqs)==len(history) and all(e["passed"] for e in eqs))
        row={**execution,"passed":completed,"run":run,"history":history,
             "force_residual_max_N":max((e["translation"]["maximum_absolute"] for e in eqs),default=None),
             "moment_residual_max_Nm":max((e["rotation"]["maximum_absolute"] for e in eqs),default=None)}
        if plan:
            row["tower_load"]=plan["tower"]["summary"]
            row["conductor_force_N"]=[sum(c["audit"]["nodal_force_n"][i] for c in plan["conductors"]) for i in range(3)]
            row["load_resultant"]=plan["combined_initial_coordinate_resultant"]
            errors=[abs(v) for c in plan["conductors"] for k in ("force_residual_n","moment_residual_nm") for v in c["audit"][k]]
            row["conductor_lumping_max_residual"]=max(errors,default=0.)
            # Reactions at the tower base alone need not balance cable loads:
            # fixed remote supports carry their own part of the system load.
            balances=[]
            for state in history:
                factor=float(state["wind_load_factor"])
                for axis,index in (("x",0),("y",1)):
                    actual=float(state[f"base_shear_{axis}_N"])+float(state[f"remote_support_shear_{axis}_N"])
                    expected=factor*row["load_resultant"]["force_N"][index]
                    balances.append(abs(actual-expected))
            row["global_horizontal_balance_max_N"]=max(balances,default=None)
            if row["global_horizontal_balance_max_N"] is None or row["global_horizontal_balance_max_N"] > .01:
                row["passed"]=False
        else:
            row["passed"]=False
        row["artifact_sha256"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (summary_path,history_path,plan_path,equilibrium_path) if p.exists()}
        cases.append(row)
    output={"schema_version":1,"analysis":"directional_wind_single_tower_and_explicit_cables_verification",
        "passed":all(c["passed"] for c in cases),"case_count":len(cases),"cases":cases,
        "scope":"One Z30103A6 tower; bare tower and tower with two V strings/four fixed-end cable spans; no neighbouring towers",
        "angle_convention":"0=+X transverse;90=+Y longitudinal; degrees; flow towards",
        "validated_for_design":False,"capacity_or_collapse_evaluated":False,
        "protocol":"Each fresh model: gravity, +0.01%/-0.01%/0 selected-global-DOF drift; not wind time seconds",
        "limitations":["Aerodynamic coefficients and all-rod leg-width proxy areas UNCALIBRATED; no shielding",
            "Uniform reference wind field, no atmospheric boundary-layer profile/turbulence or gust multiplication",
            "No conductor lift/aerodynamic damping, drag orientation frozen after gravity, insulator drag omitted",
            "Fixed remote anchors replace neighbouring towers; two one-subconductor lines only; not complete phase/ground-wire system",
            "Inherited tube TMQ coefficients not angle-steel calibrated; no material damage/fracture/deletion",
            "Small-amplitude interface validation, NOT ultimate strength, complete nonlinear hysteresis or worst wind-angle identification",
            "Equivalent attachment loading verified analytically/unit-tested, NOT added on top of explicit cable loads"],
        "sources":[{"title":"Cai et al. 2021, equations 27-31; tower yaw form and conductor normal force",
                    "url":"https://vibcon.tongji.edu.cn/Upload/file/20220216/202202162058006832578.pdf"},
                   {"title":"Tang et al. 2022; angle-steel tower geometry-dependent skew wind limitations",
                    "url":"https://scholarsmine.mst.edu/civarc_enveng_facwork/2277/"},
                   {"title":"OpenSees nodal reference loads and time-series multiplier",
                    "url":"https://openseespydoc.readthedocs.io/en/latest/src/load.html"}],
        "code_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),Path(__file__).with_name("full_tower.py"),Path(__file__).with_name("directional_loading.py")]
            +list((ROOT/"util/processing").glob("*directional_wind.py"))}}
    write_json(root/"summary.json",output)
    with (root/"case_summary.csv").open("w",newline="",encoding="utf-8") as f:
        names=("key","angle_deg","passed","accepted_steps","tower_Fx_N","tower_Fy_N","tower_Mz_Nm",
               "conductor_Fx_N","conductor_Fy_N","max_equilibrium_residual_N","global_balance_residual_N")
        writer=csv.writer(f);writer.writerow(names)
        for c in cases:
            t=c.get("tower_load",{});cf=c.get("conductor_force_N",[None]*3)
            writer.writerow((c["key"],c["wind_angle_deg"],c["passed"],c["run"].get("accepted_steps"),
                *t.get("force_N",[None]*3)[:2],t.get("moment_Nm",[None]*3)[2],*cf[:2],
                c["force_residual_max_N"],c.get("global_horizontal_balance_max_N")))
    fig,axs=plt.subplots(1,2,figsize=(12,4.5),layout="constrained")
    for mode,ax in zip(MODES,axs):
        for c in cases:
            if c["mode"] != mode or not c["history"]: continue
            points=c["history"]
            ax.plot([float(p["along_wind_displacement_m"])*1000 for p in points],
                    [float(p["along_wind_base_shear_N"])/1000 for p in points],"o-",markersize=3,label=f'{c["wind_angle_deg"]} deg')
        ax.set(title="Bare tower" if mode==MODES[0] else "One tower + 4 cable spans",
               xlabel="Along-wind control-node displacement (mm)",ylabel="TOWER-base shear along wind (kN)")
        ax.grid(alpha=.25);ax.legend()
    fig.suptitle("Small-amplitude cyclic integration check — NOT capacity curves",fontsize=12)
    for ext in ("svg","png","pdf"): fig.savefig(root/f"small_cycles.{ext}",dpi=170)
    plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(12,4.5),layout="constrained")
    bare=[c for c in cases if c["mode"]==MODES[0] and "tower_load" in c]
    coupled=[c for c in cases if c["mode"]==MODES[1] and "conductor_force_N" in c]
    for i,name in enumerate(("Fx","Fy")):
        axs[0].plot([c["wind_angle_deg"] for c in bare],[c["tower_load"]["force_N"][i]/1000 for c in bare],"o-",label=name)
        axs[1].plot([c["wind_angle_deg"] for c in coupled],[c["conductor_force_N"][i]/1000 for c in coupled],"o-",label=name)
    for ax,title in zip(axs,("Tower: all-rod proxy, no shielding","Four sagged spans: normal drag")):
        ax.set(title=title,xlabel="Angle (deg): 0 transverse X, 90 longitudinal Y",ylabel="Reference force at multiplier=1 (kN)")
        ax.grid(alpha=.25);ax.legend()
    fig.suptitle("Explicit verification assumptions: 20 m/s uniform field; NOT calibrated design loads",fontsize=11)
    for ext in ("svg","png","pdf"): fig.savefig(root/f"reference_loads.{ext}",dpi=170)
    plt.close(fig)
    rows=[]
    for c in cases:
        r=c["run"]; key=html.escape(c["key"])
        residual=c["force_residual_max_N"]
        residual_text=f"{residual:.3g}" if residual is not None else "—"
        rows.append(f'<tr><td>{key}</td><td>{c["wind_angle_deg"]}°</td><td>{"通过" if c["passed"] else "未通过"}</td>'
                    f'<td>{r.get("completed_targets",0)}/3</td><td>{r.get("accepted_steps",0)}</td><td>{residual_text}</td>'
                    f'<td><a href="runs/{key}/summary.json">汇总</a> · <a href="runs/{key}/history.csv">曲线数据</a> · '
                    f'<a href="runs/{key}/wind_load_plan.json">逐杆荷载</a></td></tr>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>单塔与塔线 · 多风角加载验证</title><style>body{font:16px/1.8 system-ui,sans-serif;color:#172b40;background:#f4f7fa;margin:0}main{max-width:1100px;margin:auto;padding:28px}h1{font-size:30px}h2{margin-top:32px}section{background:white;padding:24px;border-radius:12px;margin:20px 0}a{color:#006d82}img{width:100%}.warning{border-left:5px solid #c9801a;background:#fff6e5;padding:18px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}code,pre{background:#edf2f5}pre{overflow:auto;padding:16px}li{margin:7px 0}</style>
<main><a href="/#tianmaqu">← 返回 9999 成果首页</a><h1>单塔与塔线：多风角加载验证</h1>
<p>0° = +X 横线路；90° = +Y 顺线路；角度为风流去向。每个角度独立进程、独立重力和材料历史。</p>
<p class="warning">这次完成的是加载和小幅往复接入验证，不是极限推覆、完整非线性滞回或倒塌分析。塔身面积采用全杆件角钢边宽代理，Cx=Cy=1、角度系数0.2、均匀参考风速20 m/s均为显式未标定验证输入，不能据此给出真实承载风速。</p>
<section><h2>实施步骤与验收</h2><ol><li>统一角度、SI单位和六分量节点荷载；X/Y由同一时间系数驱动。</li><li>塔身按原始物理杆件和局部高度分带，跨带裁切后按位置分配两端，保留横担局部荷载，检查合力/合矩。</li><li>导线按三维线段法向速度计算阻力，显式加载与挂点等效模式互斥；质量、自重、初张力分开管理。</li><li>先通过解析与异常输入测试，再独立运行0°/30°/45°/90°的单塔与一塔四档模型。</li><li>每例施加重力，再做控制自由度+0.01%、−0.01%、0的小幅循环，逐步核查全部自由节点平衡和整体水平反力。</li></ol>
<p>控制轴：0°/30°/45°为X，90°为Y。其他平移自由度不人为锁住。图中另行计算沿风位移和沿风塔基剪力，不能把全局控制漂移当沿风漂移。</p>
<div class="scroll"><table><thead><tr><th>模型</th><th>风角</th><th>验收</th><th>目标</th><th>接受步</th><th>最大自由节点力残差/N</th><th>证据</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<p><a href="summary.json">完整汇总与来源</a> · <a href="case_summary.csv">对比表CSV</a> · <a href="verification.json">测试记录</a></p></section>
<section><h2>不同风角的参考荷载</h2><img src="reference_loads.svg" alt="单塔及四档弧垂导线随风角的参考力分量"><p>这是荷载系数=1的参考场，不是循环各点实际风速。沿线风下，弧垂导线各斜段仍可有法向分量；水平直线导线的90°零风力只用于对应简化的解析验收。不可将该分量再按风向重复旋转。</p></section>
<section><h2>实际小幅循环结果</h2><img src="small_cycles.svg" alt="两种模型四个角度的小幅往复曲线"><p>曲线接近直线是小幅接入验证的预期结果，不代表强风下不会屈曲。负荷载系数只是固定模式的机械反向，不代表重建了另一风向的随机风场。</p></section>
<section><h2>塔线模型与边界</h2><p>一座Z30103A6塔，沿用已有两个V形绝缘子挂点。每个下挂点向±Y各连接300 m导线，共四档，远端固定，无相邻塔。每档20段、初始抛物线弧垂8 m、初力20 kN；采用既有JL/G1A-400/50单根子导线参数，每米质量1.5103 kg、外径27.6 mm。重力平衡后弧垂可改变，未反求精确目标弧垂。</p><p>导线建模器产生的临时重力模式被明确移除，再按全体系质量仅施加一次重力。导线荷载部分由远端承担，所以应检查“塔基反力＋远端反力”，不能要求塔基单独平衡全部导线风力。<code>line_history.csv</code>记录各段轴力，塔杆12分量内力另存SQLite；未混为一种应力。</p></section>
<section><h2>限制与后续</h2><ul><li>本次不是多塔模型；未包含完整三相束导线、地线、绝缘子风阻。</li><li>塔身代理面积不等于IEC单面面积，不含遮挡。导线不含升力、气动阻尼、束遮挡，阻力方向冻结于重力平衡几何。</li><li>保持TMQ原型的未标定角钢迁移、轴弯不耦合及无损伤删除限制。不得从小幅曲线判定最危险风角或倒塌位置。</li><li>后续先补充气动力面积/系数依据和真实线路参数，再增加幅值、步长/导线网格检查及脉动风空间相关性验证。</li></ul></section>
<section><h2>复现</h2><pre>CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.wind_angle_verification --output /tmp/wind_angle_NEW --workers 2
.venv/bin/python -m unittest tests.test_directional_wind tests.test_tower_directional_wind tests.test_conductor_directional_wind tests.test_directional_integration -v</pre><p>输出目录禁止覆盖。全过程参数、逐杆荷载、接受步、失败尝试和独立平衡记录保留，HTTP页面只读成果不启动分析。</p></section></main></html>'''
    (root/"index.html").write_text(page.replace("__ROWS__","".join(rows)),encoding="utf-8")
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--workers",type=int,choices=(1,2),default=2)
    args=parser.parse_args()
    root=args.output.resolve()
    if root.exists() and any(root.iterdir()): raise FileExistsError(f"Refusing to overwrite {root}")
    for name in ("configs","logs","runs"): (root/name).mkdir(parents=True,exist_ok=True)
    tasks=[(root,mode,angle) for mode in MODES for angle in ANGLES]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        executions=list(pool.map(_execute,tasks))
    result=publish(root,executions)
    write_json(root/"verification.json",{"FE_matrix_passed":result["passed"],"cases":len(executions),
        "unit_tests":"Run separately; no test count inferred from FE completion"})
    raise SystemExit(0 if result["passed"] else 2)


if __name__=="__main__": main()
