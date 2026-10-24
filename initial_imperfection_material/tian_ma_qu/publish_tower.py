"""Create read-only full-tower figures/report from actual saved analysis records."""
import argparse
import csv
import gzip
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .full_tower import write_json


def publish(run_dir, control_dir, output, extended_dir=None):
    run_dir, control_dir, output = map(Path, (run_dir, control_dir, output))
    public_files = ("publication.json", "index.html", "full_tower_hysteresis.svg", "full_tower_hysteresis.png", "critical_members.svg")
    if any((output/name).exists() for name in public_files):
        raise FileExistsError("Publication artifacts already exist; use a new output directory")
    summary = json.loads((run_dir/"summary.json").read_text())
    control = json.loads((control_dir/"summary.json").read_text())
    with (run_dir/"history.csv").open() as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("Cannot plot an empty analysis")
    tagged = set(summary.get("first_buckling", {}).get("element_tags", []))
    members, ranking = {}, {}
    with gzip.open(run_dir/"member_states.csv.gz", "rt") as f:
        for r in csv.DictReader(f):
            tag = int(r["element_tag"])
            ranking[tag] = max(ranking.get(tag, 0), int(r["buckling_count"]))
    tagged.update(sorted(ranking, key=lambda t: (-ranking[t], t))[:4])
    tags = sorted(tagged)[:6]
    with gzip.open(run_dir/"member_states.csv.gz", "rt") as f:
        for r in csv.DictReader(f):
            tag = int(r["element_tag"])
            if tag in tags:
                members.setdefault(tag, []).append(r)
    params = {}
    with (run_dir/"model_data/tmq_member_parameters.csv").open() as f:
        params = {int(r["element_tag"]): r for r in csv.DictReader(f)}
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"axes.grid": True, "grid.alpha": .2, "font.size": 10})
    fig, axs = plt.subplots(2, 2, figsize=(13, 9))
    x = [float(r["drift_ratio"])*100 for r in rows]
    y = [float(r["base_shear_N"])/1000 for r in rows]
    steps = [int(r["step"]) for r in rows]
    axs[0,0].plot(x, y, lw=1, label="All accepted steps in loading order")
    axs[0,0].scatter([x[-1]], [y[-1]], color="red", marker="x", label="Actual final accepted state")
    if "first_buckling" in summary:
        first = summary["first_buckling"]
        axs[0,0].scatter([first["drift_ratio"]*100], [first["base_shear_N"]/1000], label="First observed member buckling")
    axs[0,0].set(xlabel="Control drift (%)", ylabel="Base shear (kN)", title="Whole-tower cyclic response")
    axs[0,0].legend(fontsize=8)
    axs[0,1].plot(steps, x)
    axs[0,1].set(xlabel="Accepted quasi-static step (NOT seconds)", ylabel="Drift (%)", title="Actual loading history")
    for key,label in (("buckled_members","Ever buckled"), ("tensile_yield_members","Ever entered tensile hardening"),
                      ("compression_tail_members","Currently on assumed compression tail")):
        axs[1,0].plot(steps, [int(r[key]) for r in rows], label=label)
    axs[1,0].legend(fontsize=8)
    axs[1,0].set(xlabel="Accepted step", ylabel="Members", title="Material branch counts (not fiber damage)")
    for tag in tags[:4]:
        rr = members[tag]
        axs[1,1].plot([float(r["strain"])*float(params[tag]["length_m"])*1000 for r in rr],
                       [float(r["force_N"])/1000 for r in rr], label=f"Member {tag}", lw=1)
    axs[1,1].legend(fontsize=8)
    axs[1,1].set(xlabel="Equivalent axial deformation (mm)", ylabel="Axial force (kN), tension +", title="Local hysteresis (full recorded paths)")
    fig.suptitle(f"Tian-Ma-Qu exploratory full tower | {summary['completed_targets']}/{len(summary['targets_drift'])} targets | {summary['status']}")
    fig.tight_layout(rect=(0,.04,1,.96))
    fig.text(.5,.015,"Uncalibrated tube-to-angle transfer; uncoupled elastic bending/torsion; no damage/deletion. Not a collapse-capacity result.",ha="center",fontsize=8)
    for suffix in ("svg", "png", "pdf"):
        fig.savefig(output/f"full_tower_hysteresis.{suffix}",dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    for ax,tag in zip(axes.flat,tags):
        rr=members[tag]
        ax.plot([float(r["strain"])*1000 for r in rr],[float(r["force_N"])/1000 for r in rr],lw=1)
        ax.set(title=f"#{tag} | {params[tag]['section_name']}",xlabel="Equivalent axial strain (per mille)",ylabel="Axial force (kN)")
    for ax in list(axes.flat)[len(tags):]:
        ax.set_visible(False)
    fig.suptitle("Critical member histories: all accepted states; tension +")
    fig.tight_layout()
    fig.savefig(output/"critical_members.svg")
    plt.close(fig)
    with (control_dir/"history.csv").open() as f:
        control_rows=list(csv.DictReader(f))
    def stiffness(rr):
        r=next(r for r in rr if abs(float(r["relative_displacement_m"]))>1e-6)
        return (float(r["base_shear_N"])-float(rr[0]["base_shear_N"]))/float(r["relative_displacement_m"])
    stiffness_error=abs(stiffness(rows)/stiffness(control_rows)-1)
    freq_error=max(abs(a/b-1) for a,b in zip(summary["initial_frequencies_Hz"],control["initial_frequencies_Hz"]))
    publication={"schema_version":1,"run":summary,"control":control,"run_directory":run_dir.name,
                 "control_directory":control_dir.name,"critical_members":tags,
                 "checks":{"elastic_control_complete":control["status"]=="complete",
                           "initial_stiffness_relative_error":stiffness_error,
                           "initial_frequency_max_relative_error":freq_error,
                           "all_saved_equilibrium_passed":all(r["equilibrium_passed"]=="True" for r in rows)},
                 "validated_for_tower":False,"viewer_url":"/tmq/tower_results/index.html"}
    extended_html = ""
    if extended_dir is not None:
        extended_dir = Path(extended_dir)
        extended = json.loads((extended_dir/"summary.json").read_text())
        if extended["status"] == "running":
            raise ValueError("Wait for the extended run to stop before publishing")
        publication["extended_run"] = extended
        publication["extended_directory"] = extended_dir.name
        with (extended_dir/"history.csv").open() as f:
            erows = list(csv.DictReader(f))
        ex=[float(r["drift_ratio"])*100 for r in erows]
        ey=[float(r["base_shear_N"])/1000 for r in erows]
        fig, ax=plt.subplots(figsize=(10,5))
        ax.plot(ex,ey,lw=1,label="Actual accepted path (different loading protocol)")
        ax.scatter(ex[-1],ey[-1],c="red",marker="x",s=65,label="Last accepted state; no extrapolation")
        ax.set(title=f"Extended trial: {extended['completed_targets']}/{len(extended['targets_drift'])} targets | {extended['status']}",xlabel="Drift (%)",ylabel="Base shear (kN)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(output/"extended_hysteresis.svg")
        plt.close(fig)
        edir=html.escape(extended_dir.name)
        extended_html=f'''<h2>更大幅值试算：单独保留未完成路径</h2><p>目标包含 ±0.6%、±1.0%；实际完成 {extended['completed_targets']}/{len(extended['targets_drift'])} 个目标，{extended['accepted_steps']} 步，最终漂移 {ex[-1]:.6f}%，剪力 {ey[-1]:.3f} kN。状态 {html.escape(extended['status'])}；停止原因 {html.escape(str(extended.get('stop_reason')))}。这是不同的完整加载协议，不能与上面的曲线拼接。</p><img src="extended_hysteresis.svg" alt="更大幅值试算在真实停止点截断"><p><a href="{edir}/summary.json">扩展试算汇总</a> · <a href="{edir}/history.csv">实际路径 CSV</a> · <a href="{edir}/attempts.jsonl">回退 / 减步日志</a> · <a href="{edir}/internal_forces.sqlite">内力数据库</a></p><p>停止仅说明当前静力路径和求解设置未完成，不能直接认定全塔倒塌。此先导试算的拉向监测使用初始应变阈值，正式有界试验已改为材料分支判定；本页不以先导拉向监测值进行验证。两个试算使用的本构方程一致，各自保留源代码哈希。早期 *_01 目录仅为控制节点配置校验失败的调试记录，不计入物理结果。</p>'''
    write_json(output/"publication.json",publication)
    payload=json.dumps({"history":[[int(r["step"]),float(r["drift_ratio"])*100,float(r["base_shear_N"])/1000,
                                  int(r["buckled_members"]),int(r["tensile_yield_members"])] for r in rows]},allow_nan=False)
    run_url=html.escape(run_dir.name)
    assumptions="".join(f"<li>{html.escape(a)}</li>" for a in summary["assumptions"])
    table="".join(f"<tr><td>{k}</td><td>{html.escape(str(v))}</td></tr>" for k,v in (
        ("节点 / 杆件",f"{summary['nodes']} / {summary['elements']}"),
        ("控制点",f"节点 {summary['control_node']}，DOF {summary['control_dof']}，高度 {summary['control_height_m']} m"),
        ("实际完成",f"{summary['completed_targets']}/{len(summary['targets_drift'])} 个目标，{summary['accepted_steps']} 个接受步"),
        ("状态 / 停止原因",f"{summary['status']} / {summary.get('stop_reason')}"),
        ("曾压屈 / 曾拉向强化杆件",f"{summary.get('max_buckled_members',0)} / {summary.get('max_tensile_yield_members',0)}"),
        ("实际最大基底剪力幅值",f"{abs(summary['maximum_absolute_shear_point']['base_shear_N'])/1000:.3f} kN（不自动等于承载力）"),
        ("初始刚度 / 频率相对误差",f"{stiffness_error:.3e} / {freq_error:.3e}（同拓扑弹性对照，不是四段参考）"),
        ("耗时",f"{summary['runtime_seconds']:.1f} s")))
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TMQ 全塔探索性往复结果</title>
<style>body{font:16px system-ui;max-width:1200px;margin:auto;padding:24px;background:#f6f8fa;color:#172b3a}h1{font-size:30px}.warning{background:#fff0d7;border-left:5px solid #cf7820;padding:16px}img,canvas{width:100%;background:white}table{border-collapse:collapse;width:100%;background:white}td{padding:10px;border-bottom:1px solid #ddd}a{color:#126b83}input{width:100%}pre{overflow:auto;background:white;padding:16px}li{margin:8px 0}</style>
<a href="/#tianmaqu">← 返回成果总览</a><h1>Tian–Ma–Qu：Z30103A6 全塔往复</h1>
<p class="warning">已实际接入全塔并求解；这是未经本塔角钢试验标定的探索性模型。完成协议不等于验证通过，未完成的协议不绘制或补齐后续曲线。少量杆件压屈时，全塔曲线仍可能接近直线。</p>
<h2>实施步骤</h2><ol><li>逐杆读取 S2K 的 E、fy、A、L 和弱轴惯性矩，以 K=1、L/1000 的 Perry 首次屈服估计确定 φ。</li><li>每根物理杆件采用一个三维共回转梁，P 通道为 A×TMQ 应力，弯曲和扭转通道保持弹性；不再叠加杆内初弯曲。</li><li>用同拓扑弹性模型核查初始模态、刚度和重力；先小幅往复，再依次提高漂移目标。</li><li>采用位移控制、算法回退和减步；每个接受步独立检查节点平衡，记录所有杆件状态和 12 分量梁端内力。</li><li>按真实加载顺序展示全部接受步。保留失败尝试和实际停止点，不延长或拼接未计算路径。</li></ol>
<h2>实际结果</h2><table>TABLE</table><h2>完整全塔与局部曲线</h2><img src="full_tower_hysteresis.svg" alt="全塔完整已计算往复曲线与局部滞回"><h2>逐步查看全塔路径</h2><input id="frame" type="range" min="0"><p id="state"></p><canvas id="curve" width="1100" height="440"></canvas><h2>关键杆件完整滞回</h2><img src="critical_members.svg" alt="关键杆件完整轴力应变路径">EXTENDED
<h2>适用范围与假设</h2><ul>ASSUMPTIONS</ul><p>全塔漂移取相对重力平衡位置的侧移 / 控制点高度。数据库 time 为拟静力接受步号，不是物理时间；可按任意已保存步区间提取全塔内力。模型的压屈计数不是损伤，等效应变不是钢材纤维应变。现有网页下方旧版内力浏览器仍对应旧模型，本页提供新模型独立数据库。</p>
<p>建模接口依据：<a href="https://openseespydoc.readthedocs.io/en/latest/src/sectionaggregator.html">OpenSees Aggregator</a>；<a href="https://opensees.github.io/OpenSeesDocumentation/user/manual/model/geomTransf/Corotational.html">Corotational 坐标转换</a>。材料系数来源和转录边界见<a href="../REPORT.md">单杆报告</a>。</p>
<h2>原始证据与重跑</h2><p><a href="RUN/history.csv">全塔历史 CSV</a> · <a href="RUN/summary.json">运行参数 / 结果 JSON</a> · <a href="RUN/member_states.csv.gz">全塔逐步材料状态</a> · <a href="RUN/internal_forces.sqlite">全塔内力 SQLite</a> · <a href="RUN/attempts.jsonl">求解尝试日志</a> · <a href="RUN/equilibrium.jsonl">独立平衡检查</a> · <a href="RUN/model_data/tmq_member_parameters.csv">逐杆参数表</a> · <a href="full_tower_hysteresis.pdf">曲线 PDF</a></p>
<pre>CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.full_tower --output /path/to/NEW_EMPTY_DIRECTORY
TMQ_TEST_NATIVE=1 .venv/bin/python -m unittest tests.test_tmq_full_tower -v</pre>
<script>const data=PAYLOAD;const rows=data.history,s=document.getElementById('frame'),c=document.getElementById('curve'),ctx=c.getContext('2d');s.max=rows.length-1;s.value=s.max;function draw(){const i=+s.value,r=rows[i];document.getElementById('state').textContent=`接受步 ${r[0]} / ${rows.at(-1)[0]} · 漂移 ${r[1].toFixed(4)}% · 基底剪力 ${r[2].toFixed(3)} kN · 曾压屈 ${r[3]} 根 · 曾拉向强化 ${r[4]} 根`;ctx.clearRect(0,0,c.width,c.height);let xmax=Math.max(...rows.map(r=>Math.abs(r[1])),1e-8)*1.1,ymax=Math.max(...rows.map(r=>Math.abs(r[2])),1)*1.1;const X=x=>c.width/2+x/xmax*(c.width/2-65),Y=y=>c.height/2-y/ymax*(c.height/2-35);ctx.strokeStyle='#bbb';ctx.beginPath();ctx.moveTo(50,Y(0));ctx.lineTo(c.width-30,Y(0));ctx.moveTo(X(0),20);ctx.lineTo(X(0),c.height-20);ctx.stroke();ctx.strokeStyle='#16758d';ctx.lineWidth=2;ctx.beginPath();rows.slice(0,i+1).forEach((r,j)=>j?ctx.lineTo(X(r[1]),Y(r[2])):ctx.moveTo(X(r[1]),Y(r[2])));ctx.stroke();ctx.fillStyle='#c44';ctx.beginPath();ctx.arc(X(r[1]),Y(r[2]),5,0,Math.PI*2);ctx.fill();ctx.fillStyle='#172b3a';ctx.font='16px sans-serif';ctx.fillText('Base shear (kN)',15,20);ctx.fillText('Drift (%)',c.width-95,c.height-10)}s.oninput=draw;draw();</script></html>'''
    page=page.replace("TABLE",table).replace("EXTENDED",extended_html).replace("ASSUMPTIONS",assumptions).replace("RUN/",run_url+"/").replace("PAYLOAD",payload)
    (output/"index.html").write_text(page,encoding="utf-8")
    return publication


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--control",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--extended",type=Path)
    args=parser.parse_args()
    publish(args.run,args.control,args.output,args.extended)
