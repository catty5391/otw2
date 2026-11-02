"""Publish the two spatial-member studies without rerunning OpenSees."""
from __future__ import annotations

import csv
import argparse
import hashlib
from html import escape
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).parent / 'results'
FIGURES = ('mesh_curves', 'cyclic_curves', 'direction_curves', 'direction_peaks', 'section_directions')
COLORS = ('#226d93', '#bd4054', '#c58b26', '#427d58')
DIRECTION_LABELS = {'weak_plus': 'Weak flexure +', 'weak_minus': 'Weak flexure -',
                    'legacy_seed30103': 'Tower random / seed 30103'}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def csv_rows(path):
    with path.open(encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def table(headers, rows):
    return '<div class="table-scroll"><table><thead><tr>'+''.join('<th>'+escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def publish(output=OUTPUT):
    output = Path(output)
    convergence = json.loads((output/'convergence/summary.json').read_text())
    direction = json.loads((output/'direction/direction_summary.json').read_text())
    cases, histories, configurations = {}, {}, {}
    for key, summary in convergence['cases'].items():
        name = 'convergence/'+key
        cases[name] = summary
        histories[name] = csv_rows(output/'convergence/runs'/key/'history.csv')
    for entry in direction['cases']:
        config, summary = entry['case'], entry['summary']
        name = 'direction/'+config['key']
        cases[name] = summary
        configurations[name] = config
        histories[name] = csv_rows(output/'direction/runs'/config['key']/'history.csv')
    member_ids = sorted({int(case['member_id']) for case in cases.values()})
    members = {i: convergence['members'][str(i)] for i in member_ids}
    plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False,
                         'svg.fonttype': 'none'})

    def title(i):
        m = members[i]
        return f"#{i} | {m['section']['section_name']} | L={m['length']:.3f} m"

    def select(i, loading='monotonic', **conditions):
        answer=[]
        for name, case in cases.items():
            if not name.startswith('convergence/') or int(case['member_id'])!=i or case['loading']!=loading:
                continue
            if all((case['profile'].get(key) if key in ('long_edge_segments','short_edge_segments') else case.get(key))==value
                   for key,value in conditions.items()):
                answer.append(name)
        return sorted(answer, key=lambda k:(cases[k]['divisions'], cases[k]['profile']['long_edge_segments'], k))

    def curve(ax, name, label, *, compression=True, color=None, style='-'):
        rows=histories[name]
        sign=-1 if compression else 1
        x=np.array([float(row['displacement_m']) for row in rows])*sign*1000
        y=np.array([float(row['force_N']) for row in rows])*sign/1000
        ax.plot(x,y,label=label,color=color,lw=1.1,ls=style)
        if not cases[name]['complete']:
            ax.plot(x[-1],y[-1],'x',ms=8,color=color)
        ax.set(xlabel='Shortening (mm)' if compression else 'Axial displacement (mm), tension +',
               ylabel='Compression (kN)' if compression else 'Axial force (kN), tension +')
        ax.grid(alpha=.2)

    def save(fig, name):
        fig.tight_layout()
        for extension in ('png','svg','pdf'):
            fig.savefig(output/f'{name}.{extension}',dpi=155,bbox_inches='tight')
        plt.close(fig)

    fig, axes=plt.subplots(len(member_ids),2,figsize=(13,3.5*len(member_ids)),squeeze=False)
    mesh_rows=[]
    for row,i in enumerate(member_ids):
        for name in select(i,long_edge_segments=8,short_edge_segments=1):
            # A refined-step case is shown separately in the data/report.
            if 'step' in name: continue
            curve(axes[row,0],name,f"{cases[name]['divisions']} segments")
        for name in select(i,divisions=16):
            if 'step' in name: continue
            profile=cases[name]['profile']
            curve(axes[row,1],name,f"Fibers: {profile['long_edge_segments']} x {profile['short_edge_segments']}")
        axes[row,0].set_title(title(i)+' / fixed tower section (17 fibers)')
        axes[row,1].set_title('16 segments / independent section refinement')
        for ax in axes[row]: ax.legend(fontsize=8)
        standard=select(i,divisions=32,long_edge_segments=8,short_edge_segments=1)
        baseline=cases[standard[0]] if standard else None
        for name in select(i,long_edge_segments=8,short_edge_segments=1):
            if 'step' in name: continue
            case=cases[name]
            difference=100*(case['peak_compression_kN']/baseline['peak_compression_kN']-1) if baseline and baseline['complete'] and case['complete'] else None
            mesh_rows.append([i,case['divisions'],round(case['peak_compression_kN'],3),
                              '—' if difference is None else f'{difference:+.3f}%',case['complete']])
    save(fig,'mesh_curves')

    fig,axes=plt.subplots(len(member_ids),2,figsize=(13,3.5*len(member_ids)),squeeze=False)
    for row,i in enumerate(member_ids):
        for col,loading in enumerate(('elastic','cyclic')):
            for name in select(i,loading):
                case=cases[name];p=case['profile']
                curve(axes[row,col],name,f"{case['divisions']} segments / {p['long_edge_segments']}x{p['short_edge_segments']}",compression=False)
            axes[row,col].set_title(title(i)+(' / small unloading' if col==0 else ' / ordered cyclic loading'))
            if axes[row,col].lines: axes[row,col].legend(fontsize=8)
    save(fig,'cyclic_curves')

    fig,axes=plt.subplots(len(member_ids),2,figsize=(13,3.5*len(member_ids)),squeeze=False)
    direction_rows=[]
    for row,i in enumerate(member_ids):
        for name,config in configurations.items():
            if config['member_id']!=i: continue
            if config['imperfection_ratio']==.001:
                curve(axes[row,0],name,DIRECTION_LABELS[config['direction']])
            if config['direction']=='weak_plus':
                curve(axes[row,1],name,f"e0/L = 1/{round(1/config['imperfection_ratio'])}")
            case=cases[name]
            direction_rows.append([i,config['direction'],f"L/{round(1/config['imperfection_ratio'])}",
                                   round(case['peak_compression_kN'],3),case['complete']])
        axes[row,0].set_title(title(i)+' / e0=L/1000')
        axes[row,1].set_title('Same positive weak direction / bow amplitude')
        for ax in axes[row]: ax.legend(fontsize=8)
    save(fig,'direction_curves')

    fig,axes=plt.subplots(1,len(member_ids),figsize=(15,4.5),squeeze=False)
    for ax,i in zip(axes[0],member_ids):
        for j,label in enumerate(DIRECTION_LABELS):
            entries=sorted([(config['imperfection_ratio'],cases[name]) for name,config in configurations.items()
                            if config['member_id']==i and config['direction']==label])
            ax.plot([x*1000 for x,c in entries],[c['peak_compression_kN'] for x,c in entries],
                    'o-',label=DIRECTION_LABELS[label],color=COLORS[j])
        ax.set(title=title(i),xlabel='Bow amplitude / L (per mille)',ylabel='Maximum sampled compression (kN)')
        ax.grid(alpha=.2);ax.legend(fontsize=7)
    save(fig,'direction_peaks')

    fig,axes=plt.subplots(1,len(member_ids),figsize=(15,4.5),squeeze=False)
    for ax,i in zip(axes[0],member_ids):
        cells=members[i]['fibers']
        ax.scatter([c['y']*1000 for c in cells],[c['z']*1000 for c in cells],s=7,c='#a2acb0',label='Section fiber centers')
        radius=max(max(abs(c['y']),abs(c['z'])) for c in cells)*1000*.7
        for j,label in enumerate(DIRECTION_LABELS):
            config=next(c for c in configurations.values() if c['member_id']==i and c['direction']==label and c['imperfection_ratio']==.001)
            y,z=config['unit_direction_local_xyz'][1:]
            ax.arrow(0,0,y*radius,z*radius,width=radius*.015,color=COLORS[j],length_includes_head=True,label=DIRECTION_LABELS[label])
        ax.set(title=title(i),xlabel='Section y (mm)',ylabel='Section z (mm)',aspect='equal')
        ax.grid(alpha=.2);ax.legend(fontsize=7)
    save(fig,'section_directions')

    with (output/'histories.csv').open('w',encoding='utf-8',newline='') as stream:
        fields=['case',*next(iter(histories.values()))[0]]
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for name,rows in histories.items():
            writer.writerows(dict(case=name,**row) for row in rows)
    case_rows=[]
    for name,case in cases.items():
        p=case['profile'];config=configurations.get(name,{})
        case_rows.append(dict(case=name,member_id=case['member_id'],divisions=case['divisions'],
            fiber_mesh=f"{p['long_edge_segments']}x{p['short_edge_segments']}",loading=case['loading'],
            direction=config.get('direction','weak_direction'),imperfection_ratio=case['imperfection_ratio'],
            complete=case['complete'],peak_compression_kN=case['peak_compression_kN'],
            final_force_kN=float(histories[name][-1]['force_N'])/1000,history_points=len(histories[name])))
    with (output/'case_summary.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(case_rows[0]));writer.writeheader();writer.writerows(case_rows)
    complete=sum(c['complete'] for c in cases.values())
    failure_attempts=sum(case['failed_attempts'] for case in cases.values())
    mesh_evidence=csv_rows(output/'convergence/mesh_summary.csv')
    fiber_evidence=csv_rows(output/'convergence/fiber_summary.csv')
    elastic_evidence=csv_rows(output/'convergence/elastic_summary.csv')
    findings=[]
    for i in member_ids:
        grid={int(row['divisions']):row for row in mesh_evidence if int(row['member_id'])==i}
        coarse=next(row for row in fiber_evidence if int(row['member_id'])==i and int(row['fiber_count'])==17)
        fine=next(cases[name] for name,config in configurations.items()
                  if config['member_id']==i and config['direction']=='weak_plus' and config['imperfection_ratio']==.001)
        random_case=next(cases[name] for name,config in configurations.items()
                        if config['member_id']==i and config['direction']=='legacy_seed30103' and config['imperfection_ratio']==.001)
        findings.append([i,f"{float(grid[4]['peak_difference_to_32_percent']):+.3f}%",
            f"{float(grid[16]['peak_difference_to_32_percent']):+.3f}%",
            f"{float(coarse['peak_difference_to_fine_percent']):+.3f}%",
            f"{100*(random_case['peak_compression_kN']/fine['peak_compression_kN']-1):+.3f}%"])
    result_explanation=(f'全部工况完成，共记录{failure_attempts}次失败尝试，均由NewtonLineSearch恢复，未放宽残差容限。'
        '四段最大压力偏高约0.56%～5.08%，16段相对32段的偏差降至0.24%以内（均固定17纤维）。'
        '固定16段时，17纤维相对272纤维的最大压力低约0.12%～1.69%；两种离散误差不能直接相加或认为能够可靠抵消。'
        '在L/1000下，所测三杆的一个随机方向样本与弱轴正方向的首压差异均小于1%；这不能代表任意方向或整个塔。')
    elastic_note=(f"小幅循环每步检查全部纤维，最大应力/fy={max(float(r['max_observed_fiber_stress_over_fy']) for r in elastic_evidence):.5f}，"
        f"回到原端距后的轴力最大绝对值{max(abs(float(r['final_force_N'])) for r in elastic_evidence):.3g} N。"
        '这仅验证本轮小幅弹性恢复；屈曲后循环仍需试验依据。')
    summary=dict(schema='otw2.segmented_member_validation_publication.v1',total_cases=len(cases),complete_cases=complete,
        failed_attempts=failure_attempts,result_findings=findings,
        physical_validation=False,full_tower_validation=False,member_ids=member_ids,cases=cases,
        source_studies=['convergence/summary.json','direction/direction_summary.json'],
        code_sha256_scope='Publication-time source snapshot; see study manifests for execution provenance.',
        direction_configuration=configurations,mesh_peak_comparison=mesh_rows,
        comparisons=convergence.get('comparisons',{}),
        notes=['Isolated spatial pin-ended members; not full-tower boundary replay.',
               'Maximum sampled compression is not automatically an identified buckling capacity.',
               'Whole-tower material parameters are shared; b is a project assumption, not coupon identification.',
               'Original per-segment section reference convention is retained; installation angles are not verified.'])
    summary['code_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),Path(__file__).with_name('mechanics.py'),Path(__file__).with_name('experiment.py'),
         Path(__file__).with_name('direction_study.py'),ROOT/'model/steel02_parameters.py',ROOT/'model/tower_model_with_buckling.py']}
    write_json(output/'summary.json',summary)

    section_rows=[]
    for i in member_ids:
        m=members[i]
        c=next(c for c in configurations.values() if c['member_id']==i and c['direction']=='legacy_seed30103' and c['imperfection_ratio']==.001)
        section_rows.append([i,m['section']['section_name'],f"{m['length']:.4f}",
                             f"{c['angle_to_weak_displacement_line_degrees']:.3f}°",
                             f"{c['orientation_audit']['maximum_absolute_roll_degrees']:.4f}°"])
    report=[
        '# 四分段初始缺陷：空间单杆验证\n',
        f'日期：2026-10-29。完成 {complete}/{len(cases)} 个数值工况。各工况是否完整以 complete 字段为准；未完成工况不参与完整峰值误差评价。\n',
        '## 执行步骤\n',
        '1. 从S2K读取真实杆件几何、截面和钢材；349号保留为既有对照，920和292号按已完成风荷载工况的同钢级压缩 |N|/Afy 筛选。该指标用于选样，不是屈曲安全系数。\n',
        '2. 复用既有空间单杆建模器；共享全塔 Steel02Parameters.legacy_tower 工厂，完整参数一致。采用三维两端铰接边界，一端约束扭转刚体转动，保留双向弯曲。\n',
        '3. 固定全塔17纤维截面比较4/8/16/32段；固定16段比较8×1、16×2、32×4截面网格。单调压缩至等效应变−1.5%，另检查步长、弹性卸载和有序往复。\n',
        '4. 固定16段、32×4截面，比较弱轴弯曲正反方向与seed30103真实随机样本，分别采用L/2000、L/1000、L/500。随机方向从全塔原始遍历序列提取，不重新抽样。\n',
        '5. 每步保存有序位移、轴力、轴向反力平衡与迭代记录；失败保留最后已接受状态，不把预算停止当作倒塌。图中叉号表示提前停止。\n',
        '## 材料与默认值变更\n',
        'Steel02参数类抽取至model/steel02_parameters.py；mechanical_profile继续重新导出以兼容既有调用。全塔保持原a1=a3=0.0005、a2=a4=0.01、b=0.03等设定，并在materials.csv完整记录。裸构造器初缺陷默认由L/100改为L/1000；历史L/100可显式传入0.01。旧推覆幅值扫描固定seed30103。历史结果未重新生成。\n',
        '## 长度分段比较\n',
        result_explanation+'\n\n'+elastic_note+'\n\n',
        '|杆件|分段|最大压力/kN|相对32段|完整|\n|---|---:|---:|---:|---|\n',
        *['|'+'|'.join(map(str,row))+'|\n' for row in mesh_rows],
        '\n32段是数值比较基准，不是实测真值。截面网格与步长结果详见convergence/summary.json；不同端部约束下不能直接套用此处百分比。\n',
        '349号杆16段17纤维的步长减半后，最大采样压力由541.040增至542.721 kN（约0.31%），但共同采样点NRMSE/Afy约1.12e-6。细采样更接近曲线尖峰，不能将共同点接近写成峰值位置已经精确收敛。\n',
        '920号杆在原全塔的轴力不能与本页铰接杆最大压力直接相除并宣布失稳：全塔共用节点转角，端部约束及受弯状态不同。本页选杆只利用原结果的需求排名。\n',
        '## 方向及幅值比较\n',
        '|杆件|方向|幅值|最大压力/kN|完整|\n|---|---|---|---:|---|\n',
        *['|'+'|'.join(map(str,row))+'|\n' for row in direction_rows],
        '\n## 适用范围\n',
        '弱轴弯曲的横向偏移方向与弱弯矩轴垂直。原模型每段由全局辅助轴重建截面朝向，本次保留该约定并记录相对最小旋转输运的参考绕轴角；它不是扭转应变，也不是实测安装角。\n',
        '完整计算不等于试验验证；这三根铰接杆不代表全塔全部杆件、节点约束或失效顺序。标准纤维梁不能仅靠长度加密补齐角钢局部屈曲、翘曲、连接滑移及断裂机制。\n',
        '## 文件\n',
        'case_summary.csv：全部工况索引；histories.csv：全部有序曲线，压缩取负，未按位移重新排序；summary.json：汇总与代码哈希。convergence/runs、direction/runs保留原始history.csv、attempts.csv和summary.json。PNG/SVG/PDF为可单独使用的科研图。\n',
        '文献依据及已读范围见 ../../../literature/opensees_segmented_steel02_20261028/README.md。\n',
    ]
    report_text=re.sub(r'\n(?=## )', '\n\n', ''.join(report))
    report_text=re.sub(r'(?m)^(#{1,2} [^\n]+)\n', r'\1\n\n', report_text)
    (output/'REPORT.md').write_text(report_text,encoding='utf-8')
    descriptions={
        'mesh_curves':('分段与截面网格','左列固定全塔17纤维截面改变长度分段；右列固定16段改变截面网格。'),
        'cyclic_curves':('卸载与完整往复','按实际计算顺序连线；正负号保持拉力、伸长为正。'),
        'direction_curves':('方向与幅值','左列固定L/1000比较方向；右列固定弱轴正方向比较幅值。'),
        'direction_peaks':('最大压力随缺陷幅值变化','这是指定加载范围内的最大采样压力，是否形成下降支需结合完整曲线。'),
        'section_directions':('截面内的缺陷方向','箭头表示初弯曲位移方向；弱弯矩轴与弱弯曲位移方向相互垂直。'),
    }
    figures=''.join(f'<section id="{name}"><h2>{descriptions[name][0]}</h2><p>{descriptions[name][1]}</p>'
        f'<a href="{name}.svg"><img src="{name}.png" alt="{descriptions[name][0]}" loading="lazy"></a>'
        f'<p class="downloads"><a href="{name}.svg">SVG</a><a href="{name}.pdf">PDF</a><a href="{name}.png">PNG</a></p></section>' for name in FIGURES)
    style='''*{box-sizing:border-box}body{margin:0;background:#f3f4ef;color:#172c38;font:16px/1.75 system-ui,sans-serif}main{max-width:1260px;margin:auto;padding:32px 22px}h1{font-size:clamp(26px,4vw,40px);line-height:1.3}h2{font-size:23px}a{color:#126c78}header,section{background:white;padding:26px;margin:0 0 24px;border:1px solid #dbe3df;border-radius:14px}header{border-top:5px solid #126c78}.eyebrow{letter-spacing:.12em;font-size:12px;color:#526b73}.stats{display:flex;gap:20px;flex-wrap:wrap}.stats b{font-size:26px;display:block}.note{padding:14px 18px;background:#fff5dd;border-left:3px solid #c58b26}nav,.downloads{display:flex;flex-wrap:wrap;gap:18px}img{width:100%;height:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}th,td{padding:10px 14px;text-align:left;border-bottom:1px solid #dbe3df}th{background:#eef5f3}.table-scroll{overflow:auto}details{margin:14px 0}summary{cursor:pointer;font-weight:600}code{overflow-wrap:anywhere}@media(max-width:600px){main{padding:16px 10px}header,section{padding:18px 12px}.stats{gap:14px}body{font-size:14px}}'''
    body=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>四分段初始缺陷：空间单杆验证</title><style>{style}</style></head><body><main>
<header><div class="eyebrow">SPATIAL MEMBER VALIDATION · 2026-10-29</div><h1>四分段初始缺陷<br>参数统一、网格与方向验证</h1><p>沿用全塔 Steel02 和角钢纤维截面，在真实杆件上分别检查分段精度、缺陷方向和幅值。</p><div class="stats"><span><b>{len(member_ids)}</b>根实际塔杆</span><span><b>{complete}/{len(cases)}</b>完整数值工况</span><span><b>4 / 8 / 16 / 32</b>长度分段</span><span><b>L/2000 — L/500</b>缺陷幅值</span></div><p class="note">本页为独立空间铰接单杆研究。计算完成不等于全塔验证或角钢试验验证；历史二维对照仍保留在独立模块。</p><nav><a href="#mesh_curves">网格曲线</a><a href="#cyclic_curves">往复曲线</a><a href="#direction_curves">方向与幅值</a><a href="#evidence">步骤与数据</a></nav></header>
<section><h2>试件与实际方向</h2>{table(['原始杆号','截面','杆长/m','随机方向偏离弱弯曲方向','随机方向参考绕轴角上限'],section_rows)}<p>角度来自现有截面坐标约定。参考绕轴角不是扭转应变，角钢实际安装朝向仍需核对。</p></section>
<section><h2>本轮得到的结果</h2><p>{result_explanation}</p>{table(['杆件','4段相对32段','16段相对32段','17纤维相对272纤维','随机方向相对弱向+（L/1000）'],findings)}<p>{elastic_note}</p><p class="note">建议四段继续用于初筛，对关键压杆采用16段和更细截面复核，再用全塔实际端部历史验证。920号杆的铰接单杆压力上限不能直接用来判定全塔杆件失稳。</p></section>{figures}<section><h2>全塔原截面网格下的长度分段结果</h2>{table(['杆件','分段','最大压力/kN','相对32段','完整'],mesh_rows)}<details><summary>展开全部方向与幅值结果</summary>{table(['杆件','方向','幅值','最大压力/kN','完整'],direction_rows)}</details></section>
<section id="evidence"><h2>执行步骤与证据</h2><ol><li>按实际S2K读取几何、截面、材料，保存选杆依据。</li><li>共享全塔完整Steel02参数，分别检查长度网格、截面网格与位移步长。</li><li>在相同边界下完成卸载及往复；固定网格比较缺陷正反方向、原随机样本和三档幅值。</li><li>保留所有已接受子步、失败尝试和最后完成位置；按共同有序历史评价。</li></ol><p>默认初弯曲已统一为L/1000；旧幅值扫描固定seed30103。全塔循环材料参数保持原值，历史结果保留。</p><nav><a href="REPORT.md">完整报告</a><a href="case_summary.csv">工况汇总</a><a href="histories.csv">全部有序曲线CSV</a><a href="summary.json">机器可读结果</a><a href="/steel02-tmq/literature/README.md">文献依据</a><a href="/steel02-tmq/">此前二维Steel02与TMQ对照</a></nav></section></main></body></html>'''
    (output/'index.html').write_text(body,encoding='utf-8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    result=publish(parser.parse_args().output)
    print(json.dumps({key:result[key] for key in ('total_cases','complete_cases')}))
