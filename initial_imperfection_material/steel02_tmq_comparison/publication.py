"""Plots and a UTF-8 evidence page; incomplete curves stay visibly incomplete."""
import csv
import html
import json
from pathlib import Path
from util.postprocess.scientific_figures import save_figure

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .experiment import initial_coordinates, write_csv

FIGURES = ('monotonic', 'hysteresis', 'mesh_and_step', 'imperfection',
           'mechanism', 'convergence', 'loading_and_geometry', 'forcebeam_hysteresis')
COLORS = {'steel02_4':'#0072B2','steel02_16':'#56B4E9','tmq':'#D55E00','straight_steel02':'#666666'}
LABELS = {'steel02_4':'Steel02 / 4 segments','steel02_16':'Steel02 / 16 segments',
          'tmq':'TMQ / current tower coefficients','straight_steel02':'Straight Steel02 truss (no buckling)'}


def publish(output, summary, histories):
    output=Path(output);cases=summary['cases'];specimens=summary['specimens']
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
    def save(fig,name):
        fig.tight_layout()
        save_figure(fig, output/f'{name}.png')
        plt.close(fig)
    def curve(ax,key,label,color=None,compression=False,**kwargs):
        rows=histories[key];sign=-1 if compression else 1
        ax.plot([sign*r['displacement_m']*1000 for r in rows],
                [sign*r['force_N']/1000 for r in rows],label=label,color=color,**kwargs)
        if not cases[key]['complete']:
            ax.plot(sign*rows[-1]['displacement_m']*1000,sign*rows[-1]['force_N']/1000,'x',color=color,ms=10)
    titles={k:f"L125x8 Q345 | L={m['length']:.3f} m" for k,m in specimens.items()}
    for loading,name in [('monotonic','monotonic'),('cyclic','hysteresis')]:
        fig,ax=plt.subplots(2,2,figsize=(13,9))
        for column,key in enumerate(specimens):
            for suffix in LABELS:
                curve(ax[0,column],f'{key}_{loading}_{suffix}',LABELS[suffix],COLORS[suffix],
                      compression=loading=='monotonic',lw=1.1,alpha=.85)
            ax[0,column].set_title(titles[key]);ax[0,column].legend(fontsize=7)
            if loading=='monotonic':
                for suffix in ('steel02_4','steel02_16','tmq'):
                    curve(ax[1,column],f'{key}_{loading}_{suffix}',LABELS[suffix],COLORS[suffix],compression=True,lw=1.2)
                ax[1,column].set_xlim(0,6 if key=='long_demo' else 4)
                ax[1,column].set_title('Initial compression peak: magnified')
            else:
                base=f'{key}_cyclic_steel02_16'; reference=histories[base]
                for suffix in ('steel02_4','steel02_16','tmq'):
                    r=histories[f'{key}_cyclic_{suffix}'];cum=np.cumsum([0]+[abs(b['displacement_m']-a['displacement_m'])*1000 for a,b in zip(r,r[1:])])
                    ax[1,column].plot(cum,[x['force_N']/1000 for x in r],color=COLORS[suffix],lw=.8,label=LABELS[suffix])
                ax[1,column].set(xlabel='Accumulated absolute displacement (mm)',ylabel='Axial force (kN)',title='Ordered history; curves are never sorted by displacement')
            for a in ax[:,column]:
                a.grid(alpha=.2)
                if a is ax[0,column] or loading=='monotonic':
                    a.set_xlabel('Shortening (mm)' if loading=='monotonic' else 'Axial displacement (mm), tension +')
                    a.set_ylabel('Compression (kN)' if loading=='monotonic' else 'Axial force (kN), tension +')
        save(fig,name)
    mesh_rows=[]
    fig,ax=plt.subplots(2,2,figsize=(13,9))
    for j,key in enumerate(specimens):
        baseline=cases[f'{key}_monotonic_steel02_32']['peak_compression_kN']
        for n in (4,8,16,32):
            name=f'{key}_monotonic_steel02_{n}';c=cases[name]
            curve(ax[0,j],name,f'dispBeamColumn / {n}',compression=True,lw=1.)
            mesh_rows.append(dict(member=key,divisions=n,peak_compression_kN=c['peak_compression_kN'],
                peak_difference_to_32_percent=100*(c['peak_compression_kN']/baseline-1),complete=c['complete']))
        for n in (4,16):curve(ax[0,j],f'{key}_forcebeam_{n}',f'forceBeamColumn / {n}',compression=True,ls='--',lw=1)
        for n in (4,8,16,32):
            c=cases[f'{key}_monotonic_steel02_{n}']
            ax[1,j].plot(n,100*(c['peak_compression_kN']/baseline-1),'o',color='#226d93')
        ax[1,j].axhline(1,color='gray',ls='--',lw=.7);ax[1,j].axhline(-1,color='gray',ls='--',lw=.7)
        ax[0,j].set(xlabel='Shortening (mm)',ylabel='Compression (kN)',title=titles[key]);ax[0,j].legend(fontsize=7)
        ax[1,j].set(xlabel='Number of segments',ylabel='Peak difference to 32 segments (%)',title='Mesh evidence; 32 segments is a comparison, not an exact solution')
        for a in ax[:,j]:a.grid(alpha=.2)
    save(fig,'mesh_and_step');write_csv(output/'mesh_summary.csv',mesh_rows)
    fig,ax=plt.subplots(2,2,figsize=(13,8.5))
    for j,key in enumerate(specimens):
        for suffix,label in [('imperfection_l2000','e0/L = 1/2000'),('monotonic_steel02_16','e0/L = 1/1000'),('imperfection_l500','e0/L = 1/500')]:
            curve(ax[0,j],f'{key}_{suffix}',label,compression=True,lw=1.2)
        for suffix,label in [('monotonic_steel02_4','Half sine'),('shape_triangle','Triangle'),('shape_legacy_midpoint_only','Legacy: middle node only')]:
            curve(ax[1,j],f'{key}_{suffix}',label,compression=True,lw=1.2)
        ax[0,j].set_title(titles[key]+' / 16 segments');ax[1,j].set_title('Same amplitude, different initial shapes / 4 segments')
        for a in ax[:,j]:a.set(xlabel='Shortening (mm)',ylabel='Compression (kN)');a.grid(alpha=.2);a.legend(fontsize=8)
    save(fig,'imperfection')
    fig,ax=plt.subplots(2,2,figsize=(13,8.5))
    for j,key in enumerate(specimens):
        for n in (4,16):
            r=histories[f'{key}_monotonic_steel02_{n}'];fy=specimens[key]['yield_strength']
            ax[0,j].plot([-x['displacement_m']*1000 for x in r],[x['midspan_lateral_total_m']*1000 for x in r],label=f'{n} segments')
            ax[1,j].plot([-x['displacement_m']*1000 for x in r],[x['max_abs_fiber_stress_Pa']/fy for x in r],label=f'{n} segments')
        ax[0,j].set(xlabel='Shortening (mm)',ylabel='Midspan bow (mm)',title=titles[key])
        ax[1,j].set(xlabel='Shortening (mm)',ylabel='Maximum sampled |fiber stress| / fy',title='Fiber constitutive response; fy is a diagnostic threshold')
        ax[1,j].axhline(1,color='gray',ls='--',lw=.8)
        for a in ax[:,j]:a.grid(alpha=.2);a.legend()
    save(fig,'mechanism')
    fig,ax=plt.subplots(2,2,figsize=(13,8))
    stats=[]
    for j,key in enumerate(specimens):
        names=('steel02_4','steel02_16','tmq','straight_steel02')
        for i,suffix in enumerate(names):
            c=cases[f'{key}_cyclic_{suffix}'];stats.append(dict(member=key,scheme=suffix,
                complete=c['complete'],completed_steps=c['completed_steps'],requested_steps=c['requested_steps'],
                accepted_substeps=c['accepted_substeps'],failed_attempts=c['failed_attempts'],
                mean_iterations=c['accepted_iterations_mean'],max_iterations=c['accepted_iterations_max'],runtime_seconds=c['runtime_seconds']))
            ax[0,j].bar(i,c['accepted_iterations_mean'],color=COLORS[suffix])
            ax[0,j].text(i,c['accepted_iterations_mean']+.08,f"max {c['accepted_iterations_max']}",ha='center',va='bottom',fontsize=8)
            ax[1,j].bar(i,c['runtime_seconds'],color=COLORS[suffix])
        for a in ax[:,j]:a.set_xticks(range(4),['Steel02 4','Steel02 16','TMQ','Straight S02']);a.grid(axis='y',alpha=.2)
        ax[0,j].set(ylabel='Mean accepted iterations',title=titles[key]);ax[0,j].margins(y=.22);ax[0,j].grid(False)
        ax[1,j].set(ylabel='Recorded wall time (s)',title='Includes fiber queries and Python bridge; not a tower speedup')
    save(fig,'convergence');write_csv(output/'convergence_summary.csv',stats)
    fig,ax=plt.subplots(1,2,figsize=(12,4.5))
    for key in specimens:
        r=histories[f'{key}_cyclic_steel02_4'];ax[0].plot([x['target_index'] for x in r],[x['strain'] for x in r],label=titles[key])
    for shape,label in [('half_sine','Half sine'),('triangle','Triangle'),('legacy_midpoint_only','Legacy middle only')]:
        xy=initial_coordinates(1.,4,.001,shape);ax[1].plot(xy[:,1],xy[:,0]/.001,'o-',label=label)
    ax[0].set(xlabel='Requested step',ylabel='Member axial strain',title='Prescribed synthetic cyclic history');ax[0].legend(fontsize=8)
    ax[1].set(xlabel='Station / L',ylabel='Initial offset / e0',title='Four-segment initial shape');ax[1].legend()
    for a in ax:a.grid(alpha=.2)
    save(fig,'loading_and_geometry')
    fig,ax=plt.subplots(1,2,figsize=(13,5))
    for j,key in enumerate(specimens):
        for n in (4,16):curve(ax[j],f'{key}_cyclic_forcebeam_{n}',f'Steel02 / forceBeamColumn {n}',lw=1.1)
        curve(ax[j],f'{key}_cyclic_tmq','TMQ / same current tower mapping',COLORS['tmq'],lw=1.)
        ax[j].set(xlabel='Axial displacement (mm)',ylabel='Axial force (kN)',title=titles[key]);ax[j].legend(fontsize=8);ax[j].grid(alpha=.2)
    save(fig,'forcebeam_hysteresis')
    write_report(output,summary,mesh_rows)
    write_html(output,summary)


def write_report(output,s,mesh):
    c=s['cases'];lines=['# Steel02 分段初弯曲与 Tian–Ma–Qu 单杆对比','',
        '日期：2026-10-28。以下均为本项目新计算，不是文献试验数据。现有全塔模型与生产参数未修改。','',
        '## 研究依据与边界','',
        '文献单独存放于 `literature/opensees_segmented_steel02_20261028/`，见该目录 README 与下载清单。',
        'Jeddi等2022论文§2.1.2采用四分段、弱轴方向、Euler形状初弯曲，幅值范围L/2000至L/1000；其钢材是Steel01。本试验仅借鉴其几何建模方法，并按用户要求使用Steel02，不能称为全文复现。[出版社全文](https://onlinelibrary.wiley.com/doi/full/10.1002/eqe.3735)。',
        '文中四段充分性的判断针对其被检查的塔杆；本项目需要自己的网格检查。Darestani等2020为其追溯来源，直接全文本次未取得。[原论文入口](https://www.tandfonline.com/doi/full/10.1080/15732479.2019.1673783)。',
        'Uriz与Mahin的PEER2008/08印刷页81图4.11直接给出Steel02、纤维截面和Corotational的OpenSees脚本；页77–83比较2/4/10/30段，采用二次初弯曲。它提供直接实现依据，但不能把其管截面参数未经标定视为角钢参数。[原始PDF](https://peer.berkeley.edu/sites/default/files/web_peer808_uriz_patxi_uriz_stephen_a._mahin.pdf)。','',
        '## 建模与参数','',
        '- 两端铰接，二维弱轴平面；端部转角自由，沿杆轴位移控制。半正弦初弯曲 x=e0 sin(πs/L)，e0/L=1/1000。',
        '- Steel02纤维截面由两个不重叠矩形构成，约174个纤维；Corotational几何变换。主比较为dispBeamColumn＋6点Legendre，与当前塔采用的单元类型一致；补充forceBeamColumn＋5点Lobatto。',
        '- E=210 GPa、fy=345 MPa、b=0.03、A=1936 mm²，统一使用项目塔模型参数。Steel02的R0=20、cR1=0.925、cR2=0.15；a1=a3=0、a2=a4=1，无附加各向同性强化。b来自项目配置，不是本轮试验识别。',
        '- TMQ使用现有塔映射：同E/fy/ρ=b，φ为K=1、e0/L=1/1000的Perry首次纤维屈服估计，其余沿用P102-row-A。没有用本次Steel02曲线重新标定，且φ不等于实测极限承载力。',
        '- TMQ使用直线轴向truss，不再施加几何初弯曲；Steel02直线truss另作对照，说明Steel02本身不包含整根构件的压屈机制。',
        '- 本次不是完整空间角钢：未计弯扭屈曲、板件局部屈曲、螺栓滑移、残余应力与断裂。平面分段模型也不等于无误差的实验真值。','',
        f"实际塔杆：原始杆件{s['source_selection']['selected_original_frame']}，L={s['source_selection']['selected_length_m']:.9f} m，已用S2K原节点坐标独立核对；112根同截面杆长范围1.440–2.414 m。另一个3 m试件仅作长细杆演示。",'',
        '## 执行步骤与求解记录','',
        '1. 固定原始几何及钢材参数；冻结plan.json；所有模型从零应力、相同端距开始。',
        '2. 单调压缩至等效应变−1.5%，600步；16段另用1200步检查。',
        '3. 小幅压缩卸载0→−0.0003→0；记录最大纤维应力和返回零位移时的轴力。',
        '4. 往复历史以εy=fy/E定义，幅值0.5、1、2、4、6εy，每级两次压拉过程；仅为统一合成协议。',
        '5. 4/8/16/32段单调网格；4/16段往复；缺陷幅值L/2000、L/1000、L/500；半正弦、三角形、旧中点偏移分别比较。',
        '6. Newton＋NormUnbalance，容差1e−5，最多60次；失败后NewtonLineSearch最多120次，容差不放宽；再失败则二分，最多8级。每次尝试、迭代数、残差和最后已收敛状态均保存。',
        '残差范数对梁模型包含N与N·m数值分量；另记录整体轴力反力平衡。运行时间含截面应力查询与Python桥接，不作为全塔加速比。不同自由度模型的迭代数也不是同等难度下的算法排名。','',
        f"完成 {s['complete_cases']}/{s['total_cases']} 个算例；失败或预算停止均保留在summary.json中，不等同于物理倒塌。",'',
        '## 单调承载力与往复差异','',
        '| 杆件 | 模型 | 单调最大压力 kN | 峰值缩短 mm | 往复完成/请求步数 | 往复相对16段NRMSE / Afy |',
        '|---|---|---:|---:|---:|---:|']
    for key,m in s['specimens'].items():
        for suffix,label in LABELS.items():
            mono=c[f'{key}_monotonic_{suffix}'];cyc=c[f'{key}_cyclic_{suffix}'];metric=s['comparisons'].get(f'{key}_cyclic_{suffix}')
            err=f"{metric['nrmse']*100:.2f}%" if metric and metric['nrmse'] is not None else '基准'
            lines.append(f"| {m['length']:.3f} m | {label} | {mono['peak_compression_kN']:.3f} | {-mono['peak_compression_displacement_mm']:.3f} | {cyc['completed_steps']}/{cyc['requested_steps']} | {err} |")
    lines += ['', 'NRMSE只比较同一加载顺序的共同已完成采样点，以Afy归一化。若有提前停止，只能解释共同前缀；所有原始滞回线按时间顺序保留，未按位移排序、平移或改符号。直线Steel02的最大压力是加载终点响应，不是压屈峰值。','',
              'TMQ表中峰值来自同一步长采样，折线尖点可能落在两步之间；解析首压值φAfy见下表。不得将采样误差解释成物理退化。','',
              '| 杆件 | TMQ解析首压 φAfy / kN |','|---|---:|']
    for key,m in s['specimens'].items():
        p=c[f'{key}_monotonic_tmq']['metadata']['tmq_parameters']
        lines.append(f"| {key} | {p['phi']*p['yield_stress']*m['area']/1000:.6f} |")
    lines += ['',
              '## forceBeamColumn 往复补充','',
              '文献使用力法梁，因此另外计算了4段及16段forceBeamColumn、5点Lobatto的同一完整往复协议。','',
              '| 杆件 | 分段 | 完成/请求 | 相对dispBeamColumn16段的NRMSE/Afy |','|---|---:|---:|---:|']
    for key in s['specimens']:
        for n in (4,16):
            name=f'{key}_cyclic_forcebeam_{n}';r=c[name];d=s['comparisons'][name]
            lines.append(f"| {key} | {n} | {r['completed_steps']}/{r['requested_steps']} | {d['nrmse']*100:.3f}% |")
    lines += ['',
              '## 网格与步长','', '| 杆件 | 分段数 | 峰值 kN | 相对32段 | 完成 |','|---|---:|---:|---:|---|']
    for r in mesh:lines.append(f"| {r['member']} | {r['divisions']} | {r['peak_compression_kN']:.3f} | {r['peak_difference_to_32_percent']:+.3f}% | {r['complete']} |")
    for key in s['specimens']:
        d=s['comparisons'][f'{key}_step_refinement']
        lines += ['',f"{key}：16段步长减半、共同点力响应NRMSE={d['nrmse']*100:.5f}%；峰值是否收敛需结合网格表、整条曲线与目标误差判断。"]
    lines += ['', '## 本轮得到的判断','',
              '1. 本轮所有完成记录应按summary中的complete字段解释；单杆能收敛不能证明全塔能越过整体极限点。',
              '2. 四分段是可追溯的工程离散选择，不是普适充分条件。以32段为比较，1.602m杆四段峰值偏高约1.85%，3m杆约4.79%；16段对应约0.064%和0.227%。',
              '3. 本组参数下，当前TMQ首峰相对接近，完整往复相对16段纤维梁仍相差24.34%与31.52%（NRMSE/Afy）。恢复到较高拉力的时机与后续压屈承载力均需单独识别。',
              '4. 三种缺陷形状的对照说明，旧“仅中点偏移”和半正弦是不同模型；改分段数时必须保持同一连续缺陷函数。',
              '5. 本项目下一步宜以经过网格与步长检查的Steel02分段杆作为数值比较对象，固定钢材与几何，分组识别TMQ峰后及恢复参数。它仍需角钢试验或空间模型复核，不能把拟合数值模型当作完成物理验证。']
    lines += ['', '## 弹性小循环与力学解释','', '| 杆件 | 模型 | 返回原端距轴力 kN | 最大纤维应力/fy |','|---|---|---:|---:|']
    for key in s['specimens']:
        for suffix in ('steel02_4','steel02_16','tmq'):
            r=c[f'{key}_elastic_{suffix}'];value=f"{r['max_fiber_stress_over_fy']:.4f}" if suffix!='tmq' else '不适用：构件等效应变'
            lines.append(f"| {key} | {suffix} | {r['final_force_kN']:.8f} | {value} |")
    lines += ['', 'Steel02分段杆通过初弯曲放大、截面弯曲和纤维塑性自然产生构件软化与残余变形；TMQ直接规定轴力—端缩滞回，缺陷只通过首压估计影响φ，后续恢复、下降与退化由转移系数控制。单调首峰接近不能替代循环验证。',
              '钢材屈服判断看纤维，而非N/A是否达到fy；初弯曲杆可以在平均轴应力低于fy时因弯曲使外缘纤维进入非线性。Steel02屈服过渡平滑，|σfiber|≥fy只是报告诊断阈值。', '',
              '## 复现与文件','', '```bash', 'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.steel02_tmq_comparison.experiment', '```','',
              '每个runs子目录包含history.csv（每个成功子步）、attempts.csv（所有求解尝试）和summary.json。根目录提供冻结配置、汇总、图形SVG/PNG/PDF及网页。完整协议比较和独立试验验证是不同工作，本轮仅完成前者在所列数值边界内的检查。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def write_html(output,s):
    captions={
        'monotonic':('单调受压：构件压屈与钢材屈服','上排为完整曲线，下排放大首次压屈。直线Steel02不包含杆件弯曲失稳。'),
        'hysteresis':('完整往复滞回','相同有序位移协议。下排按累计位移展开，便于看出各次恢复与压屈差异。'),
        'mesh_and_step':('四段是否足够','分段数只改变离散精度，保留同一半正弦缺陷；forceBeamColumn是额外单元形式检查。'),
        'imperfection':('缺陷幅值与形状','同样跨中幅值，旧版只偏移中点与半正弦也可能给出不同响应。'),
        'mechanism':('杆内发生了什么','观察跨中弯曲放大和外缘纤维应力，避免只用平均应力判断是否屈服。'),
        'convergence':('实际求解情况','迭代数和耗时均来自实际OpenSees调用；截面查询成本与自由度不同，不宣称全塔加速比。'),
        'loading_and_geometry':('加载与初始形状','从零应力开始；TMQ没有重复叠加几何初弯曲。')}
    captions['forcebeam_hysteresis']=('文献力法梁的完整往复对照','另用forceBeamColumn＋5点Lobatto复核；材料仍按本轮要求采用Steel02。')
    cards=''.join(f'<section><h2>{html.escape(captions[n][0])}</h2><p>{html.escape(captions[n][1])}</p><img src="{n}.svg" alt="{n}"><p><a href="{n}.pdf">PDF</a> · <a href="{n}.png">PNG</a></p></section>' for n in FIGURES)
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Steel02 四分段初弯曲与 Tian–Ma–Qu 对比</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f4;color:#243b46;font:16px/1.7 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:26px}}h1{{line-height:1.3;font-size:clamp(26px,4vw,40px)}}section,.note{{background:white;border:1px solid #d7e1df;border-radius:12px;padding:22px;margin:22px 0}}img{{width:100%;height:auto}}a{{color:#176388;overflow-wrap:anywhere}}.badge{{color:#a24b22}}h2{{font-size:23px}}@media(max-width:600px){{main{{padding:12px}}section,.note{{padding:12px}}}}</style>
<main><a href="/">← 返回成果首页</a><p class="badge">文献依据 · 同参数单杆试验 · 2026-10-28</p><h1>Steel02 四分段＋初始缺陷<br>与 Tian–Ma–Qu 的实际差别</h1>
<p>实际塔杆 1.602 m ＋ 长杆演示 3 m；E=210 GPa，fy=345 MPa，b=0.03。完成 {s['complete_cases']}/{s['total_cases']} 个算例。</p>
<div class="note"><strong>研究范围</strong>：二维弱轴铰接单杆，使用原有TMQ塔参数映射，未重新拟合。Steel02显式计算弯曲与纤维塑性；TMQ直接给出构件等效滞回。本页不宣称完整空间角钢或全塔已验证。<br>
<a href="REPORT.md">详细步骤与结果报告</a> · <a href="summary.json">结果汇总</a> · <a href="plan.json">冻结配置</a> · <a href="mesh_summary.csv">网格数据</a> · <a href="convergence_summary.csv">收敛统计</a><br>
<a href="../literature/README.md">文献核对说明</a> · <a href="../literature/uriz_mahin_2008_peer.pdf">PEER 原始报告 / Steel02示例</a> · <a href="../literature/jeddi_2020_kns.pdf">输电塔四分段会议论文</a><br>
<a href="https://onlinelibrary.wiley.com/doi/full/10.1002/eqe.3735">四分段输电塔研究：Jeddi等2022 §2.1.2</a> · <a href="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Steel02.html">Steel02官方文档</a></div>{cards}</main></html>'''
    (output/'index.html').write_text(page,encoding='utf-8')
