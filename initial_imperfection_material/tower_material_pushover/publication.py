"""Publish saved, independently checked prefixes without extending capacity curves."""
from __future__ import annotations
import argparse
import csv
import html
import json
from pathlib import Path
import math

from .experiment import OUTPUT, SCHEMES, ANGLES, write_json
from .evidence import curve_evidence

LABELS={'steel01_four_segments':'Steel01 · 4段','steel02_four_segments':'Steel02 · 4段','tmq':'Tian–Ma–Qu · 整杆等效'}
PLOT_LABELS={'steel01_four_segments':'Steel01 / 4 segments','steel02_four_segments':'Steel02 / 4 segments','tmq':'Tian-Ma-Qu / equivalent member'}
COLORS={'steel01_four_segments':'#2166ac','steel02_four_segments':'#df741b','tmq':'#168777'}
FIGURES=('capacity','alongwind_capacity','member_events','story_drift','stiffness')
STOPS={'first_newton_nonconvergence':'首个 Newton 增量不收敛','case_time_budget':'运行时限','worker_hard_timeout':'进程硬时限',None:'完成预定目标'}


def load_history(path):
    if not path.exists():return []
    with path.open(encoding='utf-8') as f: rows=list(csv.DictReader(f))
    for r in rows:
        for k,v in list(r.items()):
            if v=='':r[k]=None
            elif v in ('True','False'):r[k]=v=='True'
            else:r[k]=float(v)
    return rows


def save_csv(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)


def event_mm(event):
    if not event or not event.get('observed'):return '未观测到' if event and event.get('available') else '不适用'
    current=event['current']['relative_control_displacement_m']*1000
    previous=event.get('previous')
    return (f'≤{current:.1f}（首点已出现）' if previous is None else f"({previous['relative_control_displacement_m']*1000:.1f}, {current:.1f}]")+' mm'


def number(v,dec=2):return '—' if v is None else f'{v:.{dec}f}'


def stop_label(row):
    if row.get('status') in ('building','gravity','pushing'):return '计算中：'+row['status']
    return STOPS.get(row.get('stop_reason'),str(row.get('stop_reason')))


def collect(root):
    cases={};allrows=[];rows=[];issues=[];candidates=[]
    for angle in ANGLES:
        for scheme in SCHEMES:
            key=f'{scheme}_deg_{angle}';folder=root/'runs'/key
            if not (folder/'summary.json').exists():continue
            s=json.loads((folder/'summary.json').read_text());history=load_history(folder/'history.csv')
            e=curve_evidence(history,s.get('control_height_m',36.4));s['curve_evidence']=e
            valid=history[:e['valid_prefix_points']]
            cases[key]={'summary':s,'history':valid}
            allrows.extend(dict(case=key,scheme=scheme,angle_deg=angle,**r) for r in history)
            last=e.get('last_point') or {};peak=e.get('sampled_peak') or {};events=e['events']
            failed=[]
            if (folder/'attempts.jsonl').exists():
                failed=[r for r in map(json.loads,(folder/'attempts.jsonl').read_text().splitlines()) if r.get('return_code')!=0]
            row=dict(case=key,scheme=scheme,angle_deg=angle,status=s.get('status'),stop_reason=s.get('stop_reason'),
                accepted_steps=s.get('accepted_steps',0),valid_points=len(valid),
                last_displacement_mm=last.get('relative_control_displacement_m',0)*1000 if last else None,
                last_control_drift_pct=last.get('control_drift_ratio',0)*100 if last else None,
                last_shear_kN=last.get('base_shear_along_N',0)/1000 if last else None,
                sampled_peak_kN=peak.get('base_shear_along_N',0)/1000 if peak else None,
                peak_is_last=e.get('peak_is_last'),descending_branch=e.get('observed_descending_branch'),
                first_fiber_yield=event_mm(events['first_fiber_nominal_yield_observed']),
                first_tmq_buckling=event_mm(events['first_tmq_buckling_observed']),
                last_fiber_yielded_members=valid[-1].get('fiber_ever_yielded_members') if valid else None,
                last_tmq_buckled_members=valid[-1].get('tmq_buckled_members') if valid else None,
                failed_attempts=len(failed),failed_target_displacement_mm=s.get('failed_target_displacement_m',0)*1000 if 'failed_target_displacement_m' in s else None,
                elapsed_seconds=s.get('wall_seconds'))
            rows.append(row)
            candidates.append(dict(case=key,assigned_damage_grades=False,ultimate_capacity_established=False,
                events=events,sampled_peak=e.get('sampled_peak'),peak_is_last=e.get('peak_is_last'),
                observed_descending_branch=e.get('observed_descending_branch'),postpeak_80pct_candidate=e.get('postpeak_80pct_candidate'),
                scope='Evidence candidates only. No extrapolation, no failure grade from solver termination.'))
            if s.get('status') in ('partial','stopped'):issues.append(dict(case=key,status=s.get('status'),stop_reason=s.get('stop_reason'),
                failed_target_displacement_m=s.get('failed_target_displacement_m',s.get('pending_target_displacement_m')),
                last_accepted=last,last_failed_attempt=failed[-1] if failed else None,
                conclusion='Cause unresolved; first failure retained without retries. Numerical stop is not a collapse criterion.'))
    checks={}
    for angle in ANGLES:
        group=[v['summary'] for v in cases.values() if v['summary']['angle_deg']==angle]
        fields=('original_geometry_sha256','physical_member_inputs_sha256','nodal_mass_sha256','supports_sha256','wind_nodal_load_sha256')
        checks[str(angle)]={'cases_present':len(group),'all_three_present':len(group)==3,
            'equal_inputs':{k:len(group)==3 and all(k in g.get('input_audit',{}) for g in group) and len({g['input_audit'][k] for g in group})==1 for k in fields}}
    common=[]
    for angle in ANGLES:
        group=[cases.get(f'{scheme}_deg_{angle}',{}).get('history',[]) for scheme in SCHEMES]
        if any(len(h)<2 for h in group):continue
        end=min(h[-1]['relative_control_displacement_m'] for h in group)
        row={'angle_deg':angle,'common_end_mm':end*1000}
        for scheme,h in zip(SCHEMES,group):
            for a,b in zip(h,h[1:]):
                if a['relative_control_displacement_m']-1e-10<=end<=b['relative_control_displacement_m']+1e-10:
                    fraction=(end-a['relative_control_displacement_m'])/(b['relative_control_displacement_m']-a['relative_control_displacement_m'])
                    row[scheme+'_kN']=(a['base_shear_along_N']+fraction*(b['base_shear_along_N']-a['base_shear_along_N']))/1000
                    break
        common.append(row)
    save_csv(root/'common_range.csv',common)
    summary=dict(schema='otw2.tower_material_pushover_publication.v1',expected_cases=12,cases_present=len(cases),
        pending_cases=12-sum(r['status'] in ('complete','partial','stopped') for r in rows),
        complete_cases=sum(r['status']=='complete' for r in rows),cases_with_valid_curve=sum(r['valid_points']>=2 for r in rows),
        converged_wind_steps=sum(r['accepted_steps'] for r in rows),target_control_drift=.03,
        physical_validation=False,damage_state_thresholds_established=False,common_input_checks=checks,cases=rows,common_range_comparison=common,
        event_observation='First full-member scan at gravity end; first event is an observation interval, not exact onset.',
        capacity_scope='Only contiguous accepted points passing independent free-DOF force/moment equilibrium.')
    save_csv(root/'case_summary.csv',rows);save_csv(root/'histories.csv',allrows)
    write_json(root/'summary.json',summary);write_json(root/'damage_candidates.json',candidates);write_json(root/'issues.json',issues)
    return cases,summary,issues


def figures(root,cases):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':180})
    for kind in FIGURES:
        fig,axes=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
        for angle,ax in zip(ANGLES,axes.flat):
            for scheme in SCHEMES:
                c=cases.get(f'{scheme}_deg_{angle}');h=c['history'] if c else []
                if not h:continue
                x=[r['relative_control_displacement_m']*1000 for r in h]
                if kind=='capacity':y=[r['base_shear_along_N']/1000 for r in h];ylabel='Along-wind base shear (kN)'
                elif kind=='alongwind_capacity':
                    x=[r['along_wind_displacement_m']*1000 for r in h];y=[r['base_shear_along_N']/1000 for r in h];ylabel='Along-wind base shear (kN)'
                elif kind=='member_events':
                    y=[r['tmq_buckled_members'] if scheme=='tmq' else r['fiber_ever_yielded_members'] for r in h];ylabel='Members with observed event (count)'
                elif kind=='story_drift':y=[r['max_abs_corrected_along_drift']*100 for r in h];ylabel='Max rotation-corrected panel drift (%)'
                else:
                    points=c['summary']['curve_evidence']['secant_stiffness_history'];x=x[1:];y=[r['along_to_initial_ratio'] for r in points[1:]];ylabel='Secant stiffness / initial prefix stiffness'
                ax.plot(x,y,color=COLORS[scheme],label=PLOT_LABELS[scheme],lw=1.8)
                if x:ax.plot(x[-1],y[-1],marker='o' if c['summary']['status']=='complete' else 'x',color=COLORS[scheme],ms=7)
            ax.set_title(f'Wind {angle}° | control '+('X' if angle!=90 else 'Y'))
            ax.set_xlabel('Node 350 along-wind displacement (mm)' if kind=='alongwind_capacity' else 'Node 350 control displacement (mm)')
            ax.set_ylabel(ylabel if 'ylabel' in locals() else 'No saved curve');ax.grid(alpha=.2);ax.set_xlim(left=0)
            if ax.lines:ax.legend(fontsize=8,loc='best')
        caption={'capacity':'Displacement-controlled whole tower | accepted equilibrium prefix only',
            'alongwind_capacity':'Projected response | no extrapolation beyond last accepted state',
            'member_events':'Steel: nominal fiber yield observed | TMQ: constitutive buckling event (different criteria)',
            'story_drift':'Gravity subtracted; lower-section mean rigid rotation removed',
            'stiffness':'Initial stiffness: OLS of first six accepted samples (including gravity origin)'}[kind]
        fig.suptitle(caption,fontsize=12)
        for ext in ('png','svg','pdf'):fig.savefig(root/f'{kind}.{ext}')
        plt.close(fig)


def report(root,cases,s,issues):
    lines=['# 全塔位移控制推覆：Steel01、Steel02 四分段与 Tian–Ma–Qu', '',
        f"本轮建立 {s['cases_present']}/12 个工况，{s['cases_with_valid_curve']} 个形成至少两个有效平衡点；{s['complete_cases']} 个到达预定 3% 控制点位移比；{s['pending_cases']} 个尚待结束。已停止的工况保留首次停止位置。3% 是计算范围，不能据此定义损伤等级。",'',
        '## 1. 实际执行步骤','',
        '1. 冻结当前代码与 S2K 源文件哈希；各模型在独立进程、独立目录建立，保留原有历史结果。',
        '2. Steel01 和 Steel02 采用同一四分段半正弦初弯曲、L/1000、随机种子30103、每截面17纤维和6点Legendre积分、Corotational dispBeamColumn。',
        '3. TMQ 采用每根物理杆一个直线 Corotational dispBeamColumn；等效轴向材料加弹性弯扭截面、3点Legendre。初弯曲已在构件级强度映射中考虑，不再加同一几何缺陷。',
        '4. 两种钢材均使用S2K实参 E=210 GPa，Q235/Q345/Q420按截面赋值，b=0.03。Steel01使用默认无等向硬化；Steel02保留塔模型完整R0/cR/a参数，逐工况summary列出。这是现有方案比较，并非重新统一标定的纯材料对照。',
        '5. 先按原节点质量施加10步重力，Newton、NormDispIncr(1e-7,120)，冻结重力；保存无载→重力→推覆的真实端部六自由度历史。',
        '6. 固定原始几何的节点风荷载分布，0°沿+X，90°沿+Y，30°/45°保持对应双向分量。20 m/s只作参考荷载归一化；密度1.225、Cx=Cy=1、yaw_gain=0.2、高度系数1、角钢肢宽投影代理，未做规范风场/遮挡校准，不能据荷载系数报告设计极限风速。',
        '7. 350号节点位于(0,1.95,36.4)m，是偏心控制点，不是塔顶中心。0°/30°/45°控制X，90°控制Y；另存沿风投影与39.6m真正塔顶40–43号节点平均位移。',
        '8. 控制增量0–50mm为2mm、50–200mm为5mm、以后10mm，末步截齐。目标为1.092m（36.4m×3%），不能当作失效应变。',
        '9. 推覆用Newton、NormUnbalance(0.005,40)、UmfPack；每增量只尝试一次，不切算法、不降步长重算、不放宽容差。独立平衡核查为自由平动/转动残差，绝对容差0.001、相对容差1e-6，尺度为外载合力绝对和及其×控制高度。',
        '10. 每个接受点保存全1528根物理杆端部全局力/矩、弦向轴力；钢材扫描4段×6积分点×17纤维全部应力应变包络；TMQ保存屈曲/拉伸屈服等内部状态。失败尝试仅进入attempts，不进入容量曲线。','',
        '## 2. 实际曲线与停止点','',
        '|风角|方案|有效步数|末点位移mm|末点控制位移比%|采样最大基底剪力kN|峰后降幅>1%|停止原因|',
        '|---|---|---:|---:|---:|---:|---|---|']
    for r in s['cases']:
        lines.append(f"|{r['angle_deg']}°|{LABELS[r['scheme']]}|{max(0,r['valid_points']-1)}|{number(r['last_displacement_mm'])}|{number(r['last_control_drift_pct'],4)}|{number(r['sampled_peak_kN'])}|{'是' if r['descending_branch'] else '未观测'}|{stop_label(r)}|")
    lines+=['','![控制位移推覆](capacity.png)','','![沿风投影推覆](alongwind_capacity.png)','','图中×表示当前有效前缀末点（完成状态/停止原因见表），圆点表示完成计算范围。只绘有效平衡前缀。采样最大值若在末点，只说明当前前缀最大值；即使有下降，也需辨别数值路径与真实失稳，不能直接认定倒塌。','',
        '表中下降标记要求峰后已接受点降幅超过1%；小于1%的下降或波动仍完整保留在曲线中，并非认定完全没有下降。', '',
        '共同位移范围内的比较（不外推；m→mm、N→kN）。不能拿提前截断的末点与另一方案已有的峰值直接比较承载力。','',
        '|风角|共同末点mm|Steel01剪力kN|Steel02剪力kN|TMQ剪力kN|','|---|---:|---:|---:|---:|']
    for r in s['common_range_comparison']:
        lines.append('|'+str(r['angle_deg'])+'°|'+number(r['common_end_mm'])+'|'+ '|'.join(number(r.get(scheme+'_kN')) for scheme in SCHEMES)+'|')
    lines+=['',
        '## 3. 杆件屈服、屈曲与变形证据','',
        '|风角|方案|首次纤维名义屈服区间|首次TMQ压屈区间|末点曾达fy杆数|末点TMQ压屈杆数|',
        '|---|---|---|---|---:|---:|']
    for r in s['cases']:lines.append(f"|{r['angle_deg']}°|{LABELS[r['scheme']]}|{r['first_fiber_yield']}|{r['first_tmq_buckling']}|{number(r['last_fiber_yielded_members'],0)}|{number(r['last_tmq_buckled_members'],0)}|")
    lines+=['','![杆件事件](member_events.png)','','Steel01/Steel02以任意纤维|σ|≥fy作名义屈服观察；Steel02平滑过渡中，达到fy不等于塑性起点。TMQ压屈是构件本构内部事件，与纤维屈服不是同一损伤量。不能按这两类杆数直接判新旧方案更安全。全塔扫描从重力末点开始；首点已阳性时只能记“首点已出现”，不能恢复重力过程的全塔首次顺序。','',
        '![旋转修正层间指标](story_drift.png)','','以既有四节点塔层观测组及真正顶层取平均，扣除重力平衡位移。原始沿风层间位移除层高；修正项为下层平均转角×上下层重心连线的沿风投影除层高。可去除刚体转动，但不等于刚性楼板假设或已验证损伤指标。全部组定义保存于section_groups.json。','',
        '![割线刚度](stiffness.png)','','初始刚度按前6个已接受点做直线最小二乘，割线刚度相对重力后零点计算。若最初几步已进入材料非线性，它是该采样前缀刚度，不应称理论未损刚度。','',
        '## 4. 不收敛问题记录','']
    for issue in issues:
        a=issue['last_failed_attempt'] or {}
        lines += [f"### {issue['case']}",'',
            f"停止原因：{STOPS.get(issue['stop_reason'],issue['stop_reason'])}；首失败/待求目标位移 {number(issue['failed_target_displacement_m']*1000 if issue['failed_target_displacement_m'] is not None else None)} mm。",'',
            f"求解返回码：{a.get('return_code','未进入或未完成analyze')}；testIter返回值：{a.get('iterations','—')}；最后保存范数：{(a.get('norms') or ['—'])[-1]}。迭代上限仍为40；OpenSees失败时testIter可能返回41，testNorm保存40项，不代表增加了迭代预算。具体目标、算法与范数序列保存在该工况 attempts.jsonl；不对失败步绘制曲线。",'',
            '本轮未重试。材料切线、杆件失稳、控制点路径、步长与约束等原因尚未分离；保留完整已提交关键杆端部历史，供后续逐杆重放和收敛诊断。','']
    lines+=['## 5. 后续易损性分级如何使用','',
        '- damage_candidates.json保存首纤维名义屈服、首次TMQ压屈的前后观测区间，采样峰值、是否观测下降，以及存在时的峰后80%线性插值候选。所有工况明确assigned_damage_grades=false。',
        '- 首次杆件事件只作局部损伤起点线索；需结合薄弱位置、层间变形、整体刚度退化和独立判据决定各级界限。',
        '- 未达到峰值/下降支的曲线属于截断证据；不把末点、不收敛点或人为3%目标指定为严重损伤或倒塌。',
        '- 80%仅为数据整理标记；仅在已接受下降段真实跨过时插值，并保留两侧观测点。当前未选择规范/试验支持的最终分级方法。',
        '- TMQ的管材循环系数、Perry K=1首次屈服映射、弯扭弹性与忽略I23仍未由本塔角钢试验验证；四分段也保留先前约0.6–5.1%的单杆峰值离散差异。需要完成参数识别/网格/构件边界核对后，才能把比较曲线作为可靠工程容量。','',
        '## 6. 同输入核对与复现','',
        '各角度比较原始节点几何、物理杆E/fy/A/连接、节点质量、支承及固定风荷载哈希。四分段内部几何和TMQ直杆几何本来不同，此审计不声明它们等刚度。','',
        '```json',json.dumps(s['common_input_checks'],ensure_ascii=False,indent=2),'```','',
        '```bash',
        'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tower_material_pushover.experiment --output /tmp/new_tower_pushover --angles 0 30 45 90 --target-drift .03 --case-budget 3600 --jobs 2',
        '.venv/bin/python -m initial_imperfection_material.tower_material_pushover.publication --output /tmp/new_tower_pushover',
        '```','',
        '已有目录不会覆盖；重跑必须另给新输出目录。同目录矩阵追加只复用已有摘要，不宣称重新计算。运行时限和非收敛分开记录。','',
        '本地原始目录 runs/<case>/：history.csv、member_envelopes.csv、node_states.csv、panel_history.csv、support_reactions.csv、critical_member_history.jsonl及metadata、attempts.jsonl、equilibrium.jsonl、summary.json、model_data与code_snapshot。静力step是加载序号，不是物理时间。网页仅开放汇总和必要诊断，原始大数据保留本地。','']
    lines+=['## 7. 数值验算与运行记录','',
        '外载为 Pg + λPw；控制增量相对重力平衡点，基底剪力为 −Σ(R−Rg) 在风向上的投影。全塔静力状态另通过CSV独立重算合力与合矩：使用原坐标加总平移后的节点坐标，计入固定支座反力与反力矩。此项不再调用有限元求解器。', '',
        '运行超时与Newton非收敛分开。早期300秒预检查预算被建模阶段耗尽，未用作容量结果；正式例预算3600秒。部分30°进程在资源争用期间短暂暂停后原状态续算，未改变荷载、增量或材料；wall_seconds包含调度等待，不能据此评价新旧模型的纯求解速度。详情见execution_notes.json。','']
    if (root/'verification.json').exists():
        v=json.loads((root/'verification.json').read_text())
        maxf=max((r['maximum_force_residual_N'] or 0 for r in v['cases'].values()),default=0)
        maxm=max((r['maximum_moment_residual_Nm'] or 0 for r in v['cases'].values()),default=0)
        lines += [f"独立全局平衡复核：{v['checked_points']} 个状态，全部通过={v['all_global_equilibria_passed']}；最大合力残差 {maxf:.6g} N，最大合矩残差 {maxm:.6g} N·m。逐点结果见verification.json。",'']
        if v.get('automated_tests'):
            lines += [f"相关自动化测试：{v['automated_tests']['passed']} 项通过。浏览器核对记录与测试日志在py_view/.output/tower_pushover_20261029/。",'']
    (root/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')


def page(root,s):
    rows=''.join('<tr data-angle="'+str(r['angle_deg'])+'"><td>'+str(r['angle_deg'])+'°</td><td><a href="runs/'+r['case']+'/summary.json">'+LABELS[r['scheme']]+'</a></td>'+''.join('<td>'+html.escape(v)+'</td>' for v in
        [str(max(0,r['valid_points']-1)),number(r['last_displacement_mm']),number(r['last_control_drift_pct'],4),number(r['sampled_peak_kN']),
         r['first_fiber_yield'] if r['scheme']!='tmq' else r['first_tmq_buckling'],'是' if r['descending_branch'] else '未观测',stop_label(r)])+ '</tr>' for r in s['cases'])
    links=''.join(f'<a href="{name}">{title}</a>' for name,title in [('REPORT.md','完整步骤与结果报告'),('case_summary.csv','结果表 CSV'),('histories.csv','全部已保存曲线 CSV'),('common_range.csv','同位移对比'),('damage_candidates.json','损伤证据候选'),('issues.json','停止问题清单'),('summary.json','输入审计与摘要')])
    figtitles={'capacity':('控制点位移—基底剪力','各工况在首个失败步停止，×标记最后接受点。350号节点高36.4m，真正塔顶39.6m位移另行记录。'),
        'alongwind_capacity':('沿风位移—基底剪力','30°和45°仍用单一全局自由度控制；此图把实际位移与基底剪力投影到风向，便于阅读。'),
        'member_events':('材料进入非线性的证据','Steel01/Steel02显示曾有纤维达到名义fy的杆数；TMQ显示材料压屈事件杆数。两者定义不同。'),
        'story_drift':('旋转修正层间变形','扣除重力及下层平均刚体旋转，保留原始层间指标供复核。'),
        'stiffness':('割线刚度变化','相对前6个接受点拟合刚度归一化，仅是当前观测前缀指标。')}
    panels=''.join(f'<section id="{name}"><h2>{title}</h2><p>{desc}</p><img src="{name}.png" alt="{title}" loading="lazy"><div class="downloads"><a href="{name}.svg">SVG</a><a href="{name}.pdf">PDF</a><a href="{name}.png">PNG</a></div></section>' for name,(title,desc) in figtitles.items())
    progress_note=f'<p class="notice">仍有 {s["pending_cases"]} 个工况在运行或排队。此页为已保存结果，最终汇总将在全部停止后更新。</p>' if s['pending_cases'] else '<p>12 个工况均已结束本轮尝试，以下为最终保存结果。</p>'
    text=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>全塔位移控制推覆 · 三方案四风角</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f6;color:#203641;font:16px/1.7 system-ui,sans-serif}}main{{max-width:1200px;margin:auto;padding:30px 24px 70px}}header{{padding:30px;background:#102d3b;color:white;border-radius:14px}}h1{{font-size:32px;line-height:1.3}}h2{{font-size:24px}}.eyebrow{{letter-spacing:2px;color:#80d6c2;font-size:12px}}.stats{{display:flex;gap:24px;flex-wrap:wrap}}.stats b{{font-size:28px;display:block;color:#80d6c2}}section{{margin-top:26px;padding:26px;background:white;border:1px solid #d9e4e4;border-radius:12px}}a{{color:#116e8a;text-decoration:underline;text-underline-offset:3px}}img{{display:block;width:100%;height:auto}}.downloads{{display:flex;gap:18px;flex-wrap:wrap}}.notice{{border-left:4px solid #d89a41;background:#fff7e9;padding:14px 18px}}.table-wrap{{overflow:auto;max-width:100%}}table{{border-collapse:collapse;min-width:1050px;width:100%;font-size:13px}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #dfe8e8}}th{{background:#e9f3f3}}select{{padding:8px;margin:10px;border:1px solid #7a9caa;border-radius:5px}}details{{margin:14px 0}}summary{{cursor:pointer;font-weight:650}}.muted{{color:#56707a}}@media(max-width:600px){{main{{padding:16px 12px 40px}}header,section{{padding:18px}}h1{{font-size:25px}}h2{{font-size:21px}}.stats{{gap:16px}}}}</style><body><main>
<header><div class="eyebrow">Z30103A6 / DISPLACEMENT CONTROL / 2026-10-29</div><h1>全塔推覆：三种方案，四个风攻角</h1><p>Steel01 四分段 · Steel02 四分段 · Tian–Ma–Qu 整杆等效</p><div class="stats"><div><b>{s['cases_present']}/12</b>实际尝试工况</div><div><b>{s['cases_with_valid_curve']}</b>有有效曲线</div><div><b>{s['complete_cases']}</b>到达预定目标</div><div><b>{s['converged_wind_steps']}</b>接受的风荷载增量</div></div></header>
<section><h2>这轮回答什么</h2>{progress_note}<p>直接检查全塔能推到哪里、材料是否进入非线性，以及不收敛前的实际路径。每组遇到第一次 Newton 不收敛即停止，保存完整前缀与失败问题，不在本轮调参追算。</p><p class="notice">采样最大剪力、最后收敛点、首次材料事件分别报告。当前未建立最终极限承载力，也未指定易损性损伤等级；3%只是计算范围。</p><div class="downloads">{links}</div></section>
<section><h2>本轮结果表</h2><label>显示风攻角<select id="angle-filter"><option value="all">全部</option>{''.join(f'<option value="{a}">{a}°</option>' for a in ANGLES)}</select></label><div class="table-wrap"><table><thead><tr>{''.join('<th>'+v+'</th>' for v in ['风角','方案','有效步数','末点位移mm','末点位移比%','采样最大剪力kN','首次材料事件区间','降幅>1%','停止原因'])}</tr></thead><tbody>{rows}</tbody></table></div><p class="muted">材料事件：钢材为任意纤维名义屈服，TMQ为等效杆件压屈；区间为相邻已接受点，不是精确起点。下降标记使用峰后降幅>1%，小幅下降仍保留在图中。</p></section>
{panels}
<section><h2>统一了什么，还存在什么差别</h2><details open><summary>相同几何、质量、重力和节点风荷载</summary><p>对照源节点、截面、材料等级、E/fy、质量、支承和荷载哈希。钢材方案用相同四分段L/1000半正弦缺陷，种子30103，17纤维、6点积分。所有工况先施加10步重力，扣除重力平衡位移和基底剪力。</p></details><details><summary>TMQ 是整杆等效方案</summary><p>每根物理杆使用一根直线梁，TMQ只负责等效轴向行为，弯扭弹性且未耦合I23，不再重复加入初弯曲。管材循环系数与角钢/塔杆的适用性仍待试验验证；因此不是只替换钢材本构的严格对照。</p></details><details><summary>如何为后续易损性分级留证</summary><p>保存首纤维屈服、TMQ压屈、整体曲线、刚度与分层变形，真实跨过峰后80%时才生成插值候选。未观测到的阶段明确留空。后续需结合文献、构件行为和整体破坏判据确定等级；不把数值不收敛当成倒塌。</p></details><details><summary>每一步保存了哪些数据</summary><p>全塔1528根杆端力与弯矩、钢材所有积分点纤维包络或TMQ状态、所有原始节点六自由度、支座反力、分层变形、独立平衡残差；8根重点杆保存无载→重力→推覆的端部完整历史，供后续边界重放。</p></details><p>计算步骤、材料参数、荷载归一化假设、各个停止原因、复现命令和本地文件位置均见<a href="REPORT.md">完整报告</a>。</p></section></main><script>document.getElementById('angle-filter').addEventListener('change',e=>document.querySelectorAll('tr[data-angle]').forEach(r=>r.hidden=e.target.value!=='all'&&r.dataset.angle!==e.target.value));</script></body></html>'''
    (root/'index.html').write_text(text,encoding='utf-8')


def publish(root=OUTPUT):
    root=Path(root);cases,s,issues=collect(root)
    figures(root,cases);report(root,cases,s,issues);page(root,s)
    print(json.dumps({k:s[k] for k in ('cases_present','complete_cases','cases_with_valid_curve','converged_wind_steps')},ensure_ascii=False))
    return s

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=OUTPUT);a=p.parse_args();publish(a.output)
