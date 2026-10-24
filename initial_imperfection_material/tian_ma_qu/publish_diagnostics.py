"""Publish B1 evidence without running analyses or rewriting historical publications."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from html import escape
from pathlib import Path


SCHEMAS={"audit/model_contract.json":"otw2.tmq_model_contract.v1",
         "modal/summary.json":"otw2.modal_group_diagnostics.v1",
         "wind_projection/summary.json":"otw2.wind_projection.v1",
         "damping/summary.json":"otw2.damping_audit.v1"}


def read_components(root):
    values={}
    for name,schema in SCHEMAS.items():
        value=json.loads((root/name).read_text())
        if value.get("schema")!=schema or value.get("new_FE_runs")!=0:
            raise ValueError(f"invalid or out-of-batch diagnostic evidence: {name}")
        if value.get("physical_validation")!="unvalidated":
            raise ValueError(f"B1 must not silently claim physical validation: {name}")
        values[name.split('/')[0]]=value
    return values


def publish(root):
    root=Path(root)
    parts=read_components(root)
    a,m,w,d=(parts[k] for k in ("audit","modal","wind_projection","damping"))
    if not a["identity_and_initial_state_checks_passed"] or not a["baseline_check_passed"]:
        raise ValueError("identity or baseline audit unresolved; refuse completed B1 publication")
    observations=[]
    with (root/"wind_projection/static_observations.csv").open() as stream:
        for row in csv.DictReader(stream):
            keep=int(row["retained_modes"])==w["cases"][row["case"]]["saved_modes"]
            if not keep or row["truncation"]!=f'first_{row["retained_modes"]}':continue
            # Bare tower also stores a combined alias; publish one load family, not duplicate rows.
            if row["component"]!="combined":continue
            observations.append({**row,"passed":row["passed"]=="True",
                **{k:float(row[k]) if row[k] else None for k in ("direct_m","modal_m","absolute_error_m","relative_error")}})
    modal_rows=[]
    for key,c in m["cases"].items():
        if not c["segments_per_span"]:continue
        representative=next(r for r in c["representative_tower_modes"] if r["label"]=="X")
        family=next(r for r in c["shape_families"] if r["group"]=="X_shape_family_screen")
        modal_rows.append({"case":key,"segments":c["segments_per_span"],
                           "window_modes":c["window"]["mode_count"],
                           "X_mode":representative["mode"],"X_frequency_Hz":representative["frequency_Hz"],
                           "X_tower_share":representative["tower_kinetic_share"],
                           "X_family_trace":family["tower_kinetic_trace"]})
    modal_comparisons=[{"from":v["from"],"to":v["to"],
        "tower_min_cosine_squared":v["tower_subspace"]["minimum_principal_cosine_squared"],
        "tower_rank_from":v["tower_subspace"]["a"]["numerical_rank"],
        "tower_rank_to":v["tower_subspace"]["b"]["numerical_rank"],
        "cable_window_min_cosine_squared":v["cable_window_subspace"]["minimum_principal_cosine_squared"],
        "cable_rank_from":v["cable_window_subspace"]["a"]["numerical_rank"],
        "cable_rank_to":v["cable_window_subspace"]["b"]["numerical_rank"],
        "low_frequency_shape_and_frequency_pass":v["low_frequency_shape_and_frequency_pass"],
        "forced_response_convergence_certified":False} for v in m["mesh_comparisons"]]
    comparisons=a["wind_modal_initial_state_comparison"]
    summary={"schema":"otw2.tmq_b1_diagnostics.v1","execution_status":"complete","assessment":"limited",
        "physical_validation":"unvalidated","new_FE_runs":0,"new_eigen_solves":0,
        "scope":"N00-N05 offline diagnostics and publication only",
        "task_assessments":{"N00":"pass","N01":"pass","N02":"limited","N03":"limited","N04":"limited","N05":"publication_pending_verification"},
        "gates":{"G0":"pass","G1":"not_passed_N06_pending","G2":"not_passed_actual_damping_and_transient_pending","G4":"unvalidated"},
        "initial_state_matches":sum(v["gravity_state_matches"] for v in comparisons),
        "initial_state_comparisons":len(comparisons),"modal_groups":modal_rows,
        "modal_comparisons":modal_comparisons,"static_mesh_comparisons":w["mesh_comparison"],
        "static_observations":observations,"damping_candidates":d["candidates"],
        "primary_outputs":w.get("primary_outputs",[]),
        "load_audits_passed":w["all_distributed_load_audits_passed"],
        "historical_load_crosschecks_passed":w["same_grid_load_crosschecks_passed"],
        "unsupported_outputs":w["unsupported_outputs"],
        "recommendation":"Next N06: prioritize same 80-segment basis extension and candidate-C frequency response; 160 segments conditional on response evidence. No new FE in B1.",
        "source_sha256":{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in SCHEMAS},
        "limitations":["Static compliance uses the saved gravity tangent; 20 m/s is load normalization, not a new nonlinear equilibrium.",
            "Complete low-frequency shape agreement does not certify dynamic response, cable forces or modal truncation.",
            "Candidate damping is hypothetical; no free-decay or actual C validation yet.",
            "Angle-steel cyclic parameters and aerodynamic coefficients remain physically unvalidated."],
        "reports":{k:f"{k}/REPORT.md" for k in parts}}
    (root/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    table="".join(f'<tr><td>{r["segments"]}</td><td>{r["window_modes"]}</td><td>{r["X_mode"]}</td>'
        f'<td>{r["X_frequency_Hz"]:.6f}</td><td>{100*r["X_tower_share"]:.4f}%</td><td>{r["X_family_trace"]:.6f}</td></tr>' for r in modal_rows)
    compare="".join(f'<tr><td>{escape(r["from"])} → {escape(r["to"])}</td>'
        f'<td>{r["tower_rank_from"]} → {r["tower_rank_to"]}</td><td>{r["tower_min_cosine_squared"]:.8f}</td>'
        f'<td>{r["cable_rank_from"]} → {r["cable_rank_to"]}</td><td>{r["cable_window_min_cosine_squared"]:.8g}</td></tr>' for r in modal_comparisons)
    checks="".join(f'<li>{escape(r["coarse"])} → {escape(r["fine"])}：{r["passed_outputs"]}/{r["outputs"]} 个静态位移观察量通过；'
        f'最大非近零相对差 {100*r["maximum_non_near_zero_relative_error"]:.4f}%，最大绝对差 {1000*r["maximum_absolute_error_m"]:.5f} mm。</li>' for r in w["mesh_comparison"])
    damping="".join(f'<tr><td>{escape(c["label"])}</td><td>{100*c["lowest_cable_damping_ratio"]:.3f}%</td><td>'
        +" / ".join(f'{100*x:.3f}%' for x in c["tower_damping_ratios"])+"</td></tr>" for c in d["candidates"])
    last,previous=modal_rows[-1],modal_rows[-2]
    share_change=100*(last["X_tower_share"]-previous["X_tower_share"])
    trace_change=100*(last["X_family_trace"]/previous["X_family_trace"]-1)
    page=HTML.replace("__GROUPS__",table).replace("__COMPARE__",compare).replace("__STATIC_MESH__",checks).replace("__DAMPING__",damping)
    page=page.replace("12.75个百分点",f"{share_change:.2f}个百分点").replace("约0.0466%",f"约{trace_change:.4f}%")
    page=page.replace("__MATCHES__",str(summary["initial_state_matches"])).replace("__TOTAL__",str(summary["initial_state_comparisons"]))
    (root/"index.html").write_text(page,encoding="utf-8")
    return summary


HTML='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>塔线模态与风荷载诊断 · B1</title>
<style>:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#eef3f6;color:#233a4a;font:16px/1.75 system-ui}main{max-width:1240px;margin:auto;padding:28px}h1{font-size:clamp(27px,4vw,42px);line-height:1.25}h2{font-size:23px}h3{font-size:18px}a{color:#08768a}section{background:white;border:1px solid #d8e3e8;border-radius:12px;padding:24px;margin:20px 0}.eyebrow{color:#477386;letter-spacing:2px;font-size:12px;font-weight:700}.note{padding:15px;background:#eaf5f2;border-left:4px solid #17816d}.pending{background:#fff5dd;border-color:#bf8b28}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #e1e8ed;text-align:left}th{background:#f5f8fa}.figs{display:grid;grid-template-columns:1fr 1fr;gap:20px}img{width:100%;height:auto}select,button{font:inherit;padding:6px 10px;border:1px solid #b7cbd5;border-radius:6px;background:white}.tools{display:flex;gap:14px;flex-wrap:wrap;align-items:center}.pass{color:#14745a}.fail{color:#a14323}.links{display:flex;gap:15px;flex-wrap:wrap}.small{font-size:14px;color:#506b7c}code{background:#edf3f6;padding:2px 4px}nav{display:flex;gap:18px;flex-wrap:wrap}#responseStatus{min-height:2em}@media(max-width:720px){main{padding:14px}section{padding:16px}.figs{grid-template-columns:1fr}.tools label{width:100%}select{max-width:100%}}</style>
<main><a href="/#tianmaqu">← 成果首页</a><p class="eyebrow">B1 / N00—N05 / SAVED-RESULT DIAGNOSTICS</p><h1>塔线模态与风荷载：先核清哪些结果足够可靠</h1>
<p>已完成模型核对、成组模态、实际风荷载投影和阻尼审计。本批新增全塔计算 <strong>0</strong> 次；使用已有矩阵和振型完成后处理。</p>
<nav><a href="#identity">模型身份</a><a href="#groups">成组模态</a><a href="#projection">风荷载与截断</a><a href="#damping">阻尼</a><a href="#next">下一步与报告</a></nav>
<p class="note pending">首批诊断已完成，整体评估为<strong>受限可用</strong>。尚未通过完整动力截断、实际阻尼及角钢材料物理验证；此页不提供工程极限风速或倒塌结论。</p>
<section id="identity"><h2>模型与初态能否对应</h2><p><strong>__MATCHES__/__TOTAL__</strong> 个历史风速工况的重力初态，与相同网格模态的全部节点六自由度记录逐值一致。旧塔线风速用20段/档，模态主结果用80段/档；二者仍是不同网格。</p><p>塔身621节点、1528根原杆；一塔四跨固定远端、两组V串。质量核对分别计算塔、导线、绝缘子，以及自由/受约束质量，避免重复重力或将XYZ质量相加三遍。</p><div class="links"><a href="audit/REPORT.md">N00/N01步骤与结果</a><a href="audit/model_contract.json">模型声明 JSON</a><a href="audit/model_difference_table.csv">差异表 CSV</a><a href="audit/baseline_check.json">原证据保护检查</a></div></section>
<section id="groups"><h2>X向单阶份额变化，主要发生在哪里</h2><p>40→80段的代表X模态塔体份额变化12.75个百分点；把附近具有X形状的模态成组后，塔体迹量变化约0.0466%。这支持参与量在附近耦合模态间重新分配，不能只按一阶判断整个塔身形状变化。</p><div class="scroll"><table><thead><tr><th>每跨段数</th><th>1.8～2.7Hz阶数</th><th>代表X阶号</th><th>频率Hz</th><th>单阶塔体份额</th><th>X族塔体迹量</th></tr></thead><tbody>__GROUPS__</tbody></table></div><p class="small">组迹量是全质量归一化模态的塔体分量之和，可能大于1，不是百分比。窗口和归组规则在运行前冻结，完整候选仍保留。</p><div class="figs"><figure><img src="modal/selected_vs_group_tower_participation.svg" alt="单阶份额与X形状族迹量对照"><figcaption>单阶与成组结果分开比较。</figcaption></figure><figure><img src="modal/low_frequency_cable_subspace.svg" alt="公共弧长导线子空间比较"><figcaption>导线按公共弧长站点比较，允许近重根组内旋转。</figcaption></figure></div><div class="scroll"><table><thead><tr><th>网格</th><th>塔子空间秩</th><th>最小夹角余弦平方</th><th>导线窗口子空间秩</th><th>最小夹角余弦平方</th></tr></thead><tbody>__COMPARE__</tbody></table></div><p>秩不同时不能仅看较小一侧的夹角就判完整一致。40→80段形状证据较好；20→40段在该频带的导线子空间仍差异明显。形状通过不代表任意风响应通过。</p><div class="links"><a href="modal/REPORT.md">N02完整报告</a><a href="modal/candidate_modes.csv">全部模态候选CSV</a><a href="modal/subspace_checks.json">子空间证据</a><a id="manifestViewer" href="modal_view/index.html">查看配置驱动的振型动画 ↗</a></div></section>
<section id="projection"><h2>网格静柔度已经接近，160阶却仍漏掉部分响应</h2><p>0°/45°/90°下分别重建塔身、导线与组合风荷载，核对总力、总矩和固定端载荷。所有模型都在各自网格组装，直接解保存的重力切线K作为静柔度参照。</p><ul>__STATIC_MESH__</ul><p class="note">参考20m/s只是荷载幅值单位；下表是重力态的<strong>线性扰动响应</strong>，不是新求得的20m/s非线性平衡。允许误差为参考位移的2%或1μm绝对差中的较大者；与强度、损伤判据无关。</p><div class="tools"><label>模型 <select id="caseFilter"><option value="coupled_80_checked">塔线80段</option><option value="coupled_40_checked">塔线40段</option><option value="coupled_20_checked">塔线20段</option><option value="bare_checked">裸塔</option></select></label><label>风向 <select id="angleFilter"><option>0</option><option selected>45</option><option>90</option></select>°</label><label>位置 <select id="groupFilter"><option value="control">控制节点350</option><option value="attachment">挂点</option><option value="midspan">导线跨中</option></select></label><label><input id="failedOnly" type="checkbox">仅未通过</label></div><p id="responseStatus" role="status">加载数据…</p><div class="scroll"><table id="responseTable"><thead><tr><th>位置</th><th>方向</th><th>直接K解 mm</th><th>保存模态重构 mm</th><th>绝对差 mm</th><th>相对差</th><th>判定</th></tr></thead><tbody></tbody></table></div><p class="small">这里使用各模型全部已保存模态（裸塔20阶、塔线160阶）。相对误差为空表示参考接近零，仍按绝对差判定。反力、杆内力和线张力缺少独立线性恢复算子，尚未认证其截断精度。</p><div class="figs"><img src="wind_projection/static_truncation.svg" alt="静态模态截断误差"><img src="wind_projection/generalized_wind_force.svg" alt="实际风荷载广义力"></div><div class="links"><a href="wind_projection/REPORT.md">N03步骤与结果</a><a href="wind_projection/static_observations.csv">全部输出CSV</a><a href="wind_projection/generalized_wind_loads.csv">广义力CSV</a><a href="wind_projection/load_audits.json">载荷守恒检查</a></div></section>
<section id="damping"><h2>阻尼锚点需要覆盖导线和塔体两个频带</h2><p>用<strong>假设的1%目标</strong>比较三个数学方案；这个值没有被认定为实测阻尼。全局前两阶都接近0.195Hz，直接用它们拟合会明显提高塔体频带的阻尼；只用塔体锚点也会提高低频导线阻尼。</p><div class="scroll"><table><thead><tr><th>方案</th><th>最低导线模态</th><th>塔扭转 / X / Y</th></tr></thead><tbody>__DAMPING__</tbody></table></div><img src="damping/damping_spectrum.svg" alt="候选阻尼比与频率关系"><p>这些曲线假定C=αM+βK且全K参与。当前线与绝缘子构造未显式设置元素Rayleigh旗标；节点质量阻尼另需核对。后续必须用实际设置和自由衰减确认，不能用此图代替动力验证。</p><div class="links"><a href="damping/REPORT.md">N04报告与官方依据</a><a href="damping/damping_candidates.json">候选C构造与指纹</a><a href="damping/transient_adapter_spec.md">后续瞬态适配规格</a></div></section>
<section id="next"><h2>下一批：先验证截断，再决定进一步加密</h2><p>建议N06优先在同一80段模型上检查扩阶与候选C下的频响。当前证据不足以直接开批量随机风振；是否需要160段由指定输出的动态响应决定。本批没有提前启动这些计算。</p><p>之后通过空间加载、小扰动、自由衰减和时间步验证，才能进入小幅风振对比。真实角钢、轴弯传力和气动力的物理验证仍是独立任务。</p><div class="links"><a href="REPORT.md">本批完整步骤与最终结果</a><a href="summary.json">汇总JSON</a><a href="verification.json">本批测试与浏览器检查</a><a href="execution_status.json">任务执行状态</a><a href="/tmq/modal_results/index.html">原模态页面</a><a href="/tmq/wind_speed_results/index.html">原风速与峰后页面</a></div></section></main>
<script>'use strict';const $=s=>document.querySelector(s);let records=[];const names={X:'X',Y:'Y',Z:'Z',along:'沿风',cross:'横风',along_wind:'沿风',cross_wind:'横风'};function render(){const rows=records.filter(r=>r.case===$('#caseFilter').value&&+r.angle_deg===+$('#angleFilter').value&&r.group===$('#groupFilter').value&&(!$('#failedOnly').checked||!r.passed));const tbody=$('#responseTable tbody');tbody.replaceChildren();for(const r of rows){const tr=document.createElement('tr');for(const v of [r.point,names[r.direction]||r.direction,(1000*r.direct_m).toFixed(6),(1000*r.modal_m).toFixed(6),(1000*r.absolute_error_m).toFixed(6),r.relative_error===null?'接近零，仅看绝对差':(100*r.relative_error).toFixed(3)+'%',r.passed?'通过':'未通过']){const td=document.createElement('td');td.textContent=v;tr.append(td);}tr.lastChild.className=r.passed?'pass':'fail';tbody.append(tr);}$('#responseStatus').textContent=`${rows.length}项观察量；${rows.filter(r=>r.passed).length}项通过。仅静态位移截断检查。`;}
fetch('summary.json').then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json();}).then(s=>{records=s.static_observations;render();}).catch(e=>$('#responseStatus').textContent='读取诊断失败：'+e.message);for(const id of ['caseFilter','angleFilter','groupFilter','failedOnly'])$('#'+id).addEventListener('change',render);</script></html>'''


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,required=True)
    s=publish(p.parse_args().output)
    print(json.dumps({"status":s["execution_status"],"assessment":s["assessment"],"new_FE_runs":0}))
