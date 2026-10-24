"""Full time-ordered scientific figures and a dependency-free result viewer."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .experiment import curve_points


def create_figures(directory, bundles, variants):
    directory = Path(directory)
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": .22,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, len(bundles), figsize=(16, 5.4), squeeze=False)
    for ax, bundle in zip(axes.flat, bundles):
        case, rows, events = bundle["case"], bundle["rows"], bundle["events"]
        points = curve_points(case, rows, events)
        ax.plot(points[:,0], points[:,1], color="#176b8d", lw=1.15, label="TMQ prototype: ALL steps")
        native = bundle.get("opensees_rows")
        if native:
            sampled = native[::max(1,len(native)//85)]
            ax.scatter([r["displacement_m"]*1e3 for r in sampled], [r["force_N"]/1e3 for r in sampled],
                       s=11, facecolors="none", edgecolors="#d47829", linewidths=.7, label="OpenSees truss check")
        peaks = [e for e in events if e["event"] == "buckling"]
        ax.scatter([peaks[0]["strain"]*case.length*1e3], [peaks[0]["stress"]*case.area/1e3],
                   color="#b73445", marker="v", s=42, label="First buckling (exact event)", zorder=4)
        ax.axhline(0, lw=.6, color="gray"); ax.axvline(0,lw=.6,color="gray")
        ax.set(title=case.label, xlabel="Axial displacement (mm); tension +", ylabel="Axial force (kN)")
        ax.legend(fontsize=7.4, loc="upper left")
    fig.suptitle("Tian-Ma-Qu formulation prototype | complete cyclic histories", fontsize=16)
    fig.text(.5,.018,"Published 2022 coefficients + assumed E, rho, gamma, zeta. Demo loading; NOT a fitted experimental reproduction.",
             ha="center", fontsize=9, color="#8b3a21")
    fig.tight_layout(rect=(0,.06,1,.93))
    for extension in ("png", "svg", "pdf"):
        fig.savefig(directory/f"full_hysteresis.{extension}",dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(len(bundles), 2, figsize=(13, 10))
    for index, bundle in enumerate(bundles):
        case, rows = bundle["case"], bundle["rows"]
        t = [r["step"] for r in rows]
        axes[index,0].plot(t,[r["displacement_m"]*1e3 for r in rows],color="#176b8d")
        axes[index,0].set(title=case.label, ylabel="Prescribed displacement (mm)", xlabel="Committed step (not physical time)")
        axes[index,1].plot(t,[r["force_N"]/1e3 for r in rows],color="#9f4349",lw=1)
        axes[index,1].set(ylabel="Axial force (kN)",xlabel="Committed step (not physical time)")
    fig.suptitle("Full loading and response histories - no truncated cycles",fontsize=15)
    fig.tight_layout(rect=(0,0,1,.96));fig.savefig(directory/"loading_history.png",dpi=160);plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    first = bundles[0];case = first["case"]
    rows = first["rows"]
    colors = plt.get_cmap("tab10")
    stages = sorted({row["stage"] for row in rows})
    for index,stage in enumerate(stages):
        selected = [row for row in rows if row["stage"] == stage]
        axes[0,0].scatter([r["strain"]*100 for r in selected],[r["stress_Pa"]*1e-6 for r in selected],
                          s=3,label=stage,color=colors(index))
    axes[0,0].set(xlabel="Equivalent member strain (%)",ylabel="Equivalent stress (MPa)",title="Active branches / P102 row A")
    axes[0,0].legend(fontsize=6,loc="upper left",ncol=2)
    targets = [r for r in rows if r["is_target"]]
    axes[0,1].plot([r["step"] for r in rows],[r["external_work_J"]/1000 for r in rows],color="#176b8d")
    axes[0,1].scatter([r["step"] for r in targets],[r["external_work_J"]/1000 for r in targets],s=8,color="#9f4349")
    axes[0,1].set(xlabel="Committed step",ylabel="Accumulated external work (kJ)",title="Integral N du; not automatically dissipation")
    for bundle in bundles:
        c = bundle["case"];peaks=[e for e in bundle["events"] if e["event"]=="buckling"]
        axes[1,0].plot(range(1,len(peaks)+1),[-e["stress"]*c.area/1e3 for e in peaks],"o-",ms=3,label=c.key)
        elastic=[r for r in bundle["rows"] if r["leg"]<=3]
        axes[1,1].plot([r["displacement_m"]*1000 for r in elastic],[r["force_N"]/1000 for r in elastic],label=c.key)
    axes[1,0].set(xlabel="Buckling branch number",ylabel="Compression peak magnitude (kN)",title="First peak vs later eta-scaled peaks")
    axes[1,1].set(xlabel="Displacement (mm)",ylabel="Force (kN)",title="Pre-yield cycles retrace the elastic line")
    axes[1,0].legend(fontsize=8);axes[1,1].legend(fontsize=8)
    fig.suptitle("Mechanism checks | parameter-dependent research prototype",fontsize=15)
    fig.tight_layout(rect=(0,0,1,.96));fig.savefig(directory/"mechanism_checks.png",dpi=170);plt.close(fig)

    if variants:
        fig,axes=plt.subplots(1,3,figsize=(15,4.8))
        baseline=curve_points(case,first["rows"],first["events"])
        for ax,parameter in zip(axes,("gamma","zeta","rho")):
            ax.plot(baseline[:,0],baseline[:,1],color="black",lw=.8,alpha=.7,label="Default assumption")
            for item in variants:
                if item["parameter"]==parameter:
                    points=curve_points(item["case"],item["rows"],item["events"])
                    ax.plot(points[:,0],points[:,1],lw=.7,alpha=.7,label=item["label"])
            ax.set(title=f"Uncalibrated {parameter}",xlabel="Displacement (mm)",ylabel="Force (kN)");ax.legend(fontsize=8)
        fig.suptitle("Missing-parameter sensitivity (P102 row A) - not an accuracy bound",fontsize=14)
        fig.tight_layout(rect=(0,0,1,.93));fig.savefig(directory/"assumption_sensitivity.png",dpi=160);plt.close(fig)


def create_viewer(directory, bundles):
    """Offline full-curve view, with an optional time-order replay slider."""
    payload=[]
    for bundle in bundles:
        payload.append({"key":bundle["case"].key,"label":bundle["case"].label,
                        "rows":[[r["displacement_m"]*1000,r["force_N"]/1000,r["stage"]] for r in bundle["rows"]]})
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TMQ 单杆完整滞回曲线</title>
<style>body{font-family:system-ui,sans-serif;max-width:1400px;margin:28px auto;padding:0 20px;color:#253641;background:#f5f7f9}section{background:white;padding:20px;margin:20px 0;border-radius:10px}h1{font-size:25px}img{width:100%;height:auto}canvas{width:100%;height:440px}select,button,input{font:inherit;margin:8px}input{width:45%}.note{border-left:4px solid #c77a36;padding:12px;background:#fff5e9}a{color:#176b8d}#status{font-family:monospace}</style>
<h1>Tian–Ma–Qu 杆件材料：完整往复模拟</h1>
<p class="note">这是基于 2022 年文献分段公式的实验原型，不是原作者 VUMAT 或原试验的完整定量复现。E、ρ、γ、ζ 采用已披露假设，加载历史为新设计。PP/PF 已包含在文献系数中；这里的单杆只验证等效轴向响应。尚未标定到当前角钢塔，未启用损伤删除。</p>
<section><h2>最终完整滞回曲线</h2><p>全部加载步均保留；蓝线为材料计算，橙色标记为 OpenSees 单杆核对（启用适配时）。正值为拉伸。最终回到零位移不等于回到零力。</p>
<img src="full_hysteresis.svg" alt="三组试件的完整滞回曲线"><p><a href="full_hysteresis.png">高清 PNG</a> · <a href="full_hysteresis.pdf">矢量 PDF</a> · <a href="summary.json">完整结果与检查</a> · <a href="../REPORT.md">改写报告</a></p></section>
<section><h2>按真实计算顺序回放</h2><select id="case"></select><button id="full">显示完整历程</button><input id="step" type="range" min="0"><div id="status"></div><canvas id="plot"></canvas><p id="download"></p></section>
<section><h2>加载历史</h2><img src="loading_history.png" alt="完整加载与响应历史"></section>
<section><h2>分支、初次与再次压屈、小循环</h2><img src="mechanism_checks.png" alt="力学分支检查"></section>
<section><h2>缺失参数的影响</h2><p>以下是单因素假设变化，不是置信区间或试验误差。</p><img src="assumption_sensitivity.png" alt="参数假设敏感性"></section>
<script>const data=__DATA__;
const select=document.getElementById('case'),slider=document.getElementById('step'),canvas=document.getElementById('plot');
data.forEach((item,index)=>{const o=document.createElement('option');o.value=index;o.textContent=item.label;select.appendChild(o)});
function draw(){const item=data[+select.value],rows=item.rows,n=+slider.value;const ratio=devicePixelRatio||1,w=canvas.clientWidth,h=440;canvas.width=w*ratio;canvas.height=h*ratio;const c=canvas.getContext('2d');c.scale(ratio,ratio);c.fillStyle='#fff';c.fillRect(0,0,w,h);const maxX=Math.max(...rows.map(r=>Math.abs(r[0])))*1.12,maxY=Math.max(...rows.map(r=>Math.abs(r[1])))*1.18;const x=v=>60+(v+maxX)/(2*maxX)*(w-90),y=v=>h-45-(v+maxY)/(2*maxY)*(h-75);c.strokeStyle='#d8e0e5';c.lineWidth=1;c.font='12px system-ui';c.fillStyle='#52616b';for(let k=-4;k<=4;k++){let a=maxX*k/5,b=maxY*k/5;c.beginPath();c.moveTo(x(a),y(-maxY));c.lineTo(x(a),y(maxY));c.stroke();c.fillText(a.toFixed(0),x(a)-8,h-25);c.beginPath();c.moveTo(x(-maxX),y(b));c.lineTo(x(maxX),y(b));c.stroke();c.fillText(b.toFixed(0),12,y(b)+4)}c.strokeStyle='#176b8d';c.lineWidth=1.4;c.beginPath();rows.slice(0,n+1).forEach((r,i)=>i?c.lineTo(x(r[0]),y(r[1])):c.moveTo(x(r[0]),y(r[1])));c.stroke();const r=rows[n];c.fillStyle='#bd493e';c.beginPath();c.arc(x(r[0]),y(r[1]),4,0,2*Math.PI);c.fill();c.fillStyle='#253641';c.fillText('Force (kN)',60,17);c.fillText('Displacement (mm)',w-180,h-7);document.getElementById('status').textContent=`步 ${n}/${rows.length-1} | 位移 ${r[0].toFixed(4)} mm | 轴力 ${r[1].toFixed(3)} kN | ${r[2]}`;document.getElementById('download').innerHTML=`<a href="${item.key}/history.csv">该工况完整 CSV</a> · <a href="${item.key}/events.json">精确折点事件</a>`;}
function reset(){slider.max=data[+select.value].rows.length-1;slider.value=slider.max;draw()};select.onchange=reset;slider.oninput=draw;document.getElementById('full').onclick=reset;window.addEventListener('resize',draw);reset();</script></html>'''
    (Path(directory)/"index.html").write_text(html.replace("__DATA__",json.dumps(payload,ensure_ascii=False)),encoding="utf-8")
