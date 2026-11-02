"""Scientific plots and self-contained Chinese publication for the prototype."""
import csv
from dataclasses import replace
from html import escape
import json
from pathlib import Path

import numpy as np

from .material import AnglePHMParameters,compression_response


def publish(output,summary,rows,old_rows,literal_rows,post,reloading):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output=Path(output);fit=summary['fit'];geom=fit['geometry'];length=geom['length_m'];area=geom['area_m2']
    def save(fig,name):
        fig.tight_layout()
        for ext in ('png','svg','pdf'):fig.savefig(output/f'{name}.{ext}',dpi=170,bbox_inches='tight')
        plt.close(fig)
    def xy(data):return np.array([x['strain'] for x in data])*length*1000,np.array([x['stress_Pa'] for x in data])*area/1000
    x,y=xy(rows);xo,yo=xy(old_rows);xl,yl=xy(literal_rows)
    fig,ax=plt.subplots(2,2,figsize=(13,9))
    ax[0,0].plot(xo,yo,color='#acb3be',lw=.8,label='Polygonal conditional baseline')
    ax[0,0].plot(x,y,color='#cf532f',lw=.9,label='Analytical curved candidate')
    ax[0,0].set(xlabel='Axial displacement (mm)',ylabel='Axial force (kN)',title='Complete artificial protocol | same imposed history');ax[0,0].legend(fontsize=8)
    ax[0,1].plot([r['step'] for r in rows],x,color='#245f87',lw=.8)
    ax[0,1].set(xlabel='Calculation sequence (not time)',ylabel='Axial displacement (mm)',title=f"All {len(rows)-1} increments retained")
    ax[1,0].plot(xl,yl,color='#8e9ba6',lw=.8,label='Printed unloading exponent = 3')
    ax[1,0].plot(x,y,color='#cf532f',lw=.8,label=f"Conditional fitted exponent = {fit['unloading']['fitted_exponent']:.3f}")
    ax[1,0].set(xlabel='Axial displacement (mm)',ylabel='Axial force (kN)',title='Unloading rule materially changes the loops');ax[1,0].legend(fontsize=8)
    events=json.loads((output/'events.json').read_text());buckles=[e for e in events if e['event']=='buckling']
    ax[1,1].plot(range(1,len(buckles)+1),[-e['stress']*area/1000 for e in buckles],'o-',color='#245f87')
    ax[1,1].set(xlabel='Compression-limit event number',ylabel='Compression limit magnitude (kN)',title='History-dependent limits; coefficients not fitted here')
    for a in ax.flat:a.grid(alpha=.2)
    save(fig,'full_hysteresis')

    fig,ax=plt.subplots(2,2,figsize=(13,9))
    u=np.array([r['displacement_m'] for r in post])*1000
    obs=np.array([r['observed_force_N'] for r in post])/1000
    for key,label,color in [('observed_force_N','Observed ordered P branch','black'),('curved_force_N','Curved fit: 3 free coefficients','#cf532f'),('polygon_force_N','Polygon fit: 3 free coefficients','#246d97')]:
        ax[0,0].plot(u,[r[key]/1000 for r in post],lw=1.2,label=label,color=color)
    ax[0,0].set(xlabel='Actuator displacement (mm)',ylabel='Axial force (kN)',title='Same observed peak anchor; descending branch only');ax[0,0].legend(fontsize=8)
    q=abs(fit['peak_stress_Pa'])*area
    for key,label,color in [('curved_force_N','Curved','#cf532f'),('polygon_force_N','Polygon','#246d97')]:
        ax[0,1].plot(u,[(r[key]-r['observed_force_N'])/q*100 for r in post],label=label,color=color)
    ax[0,1].axhline(0,color='gray',lw=.6);ax[0,1].legend(fontsize=8)
    ax[0,1].set(xlabel='Actuator displacement (mm)',ylabel='Residual / first peak (%)',title=f"NRMSE: curved {100*fit['nonlinear']['nrmse']:.2f}%, polygon {100*fit['polygon']['nrmse']:.2f}%")
    for key,label,color in [('observed_force_N','Observed P reversal branch','black'),('curved_force_N','Conditional GH/HI candidate','#cf532f')]:
        ax[1,0].plot([r['displacement_m']*1000 for r in reloading],[r[key]/1000 for r in reloading],label=label,color=color)
    ax[1,0].set(xlabel='Actuator displacement (mm)',ylabel='Axial force (kN)',title='Recovery fit is rank-deficient: not accepted');ax[1,0].legend(fontsize=8)
    un=fit['unloading'];names=['Observed zero','Fitted unloading','Printed exponent 3']
    ax[1,1].barh(names,[un['observed_zero_strain']*length*1000,un['fitted_zero_strain']*length*1000,un['paper_zero_strain']*length*1000],color=['#444','#cf532f','#8e9ba6'])
    ax[1,1].axvline(0,color='gray',lw=.7);ax[1,1].set(xlabel='Zero-force actuator displacement (mm)',title='Anchored at observed first compression reversal')
    for a in ax.flat:a.grid(alpha=.2)
    save(fig,'branch_fits')

    fig,ax=plt.subplots(1,2,figsize=(12,4.5))
    for slenderness in (60,80,100,120):
        p=AnglePHMParameters.from_regression(elastic_modulus=210e9,yield_stress=367.7e6,slenderness=slenderness,
            hardening_ratio=.005,unloading_exponent=3.,reload_stress_fraction=.8,
            reload_span_yield_strains=2.,reload_linear_ratio=.5,max_abs_strain=.03)
        sc=p.first_buckling_stress;ec=sc/p.elastic_modulus
        eps=np.linspace(ec,-.015,300);data=np.array([compression_response(p,e,ec,sc) for e in eps])
        ax[0].plot(-eps/p.yield_strain,-data[:,0]/p.yield_stress,label=f'lambda = {slenderness}')
        ax[1].plot(-eps/p.yield_strain,data[:,1]/p.elastic_modulus,label=f'lambda = {slenderness}')
    ax[0].set(xlabel='Compression strain / yield strain',ylabel='Compression stress / fy',title='Literature regression: signed softening interpretation')
    ax[1].set(xlabel='Compression strain / yield strain',ylabel='Analytical tangent / E',title='Changing tangent enters the actual constitutive law')
    for a in ax:a.legend(fontsize=8);a.grid(alpha=.2)
    save(fig,'literature_envelopes')

    from .experiment import EVIDENCE
    fig,ax=plt.subplots(1,2,figsize=(13,4.8))
    for a,name,item in zip(ax,('P','Q'),summary['observed_replay']):
        original=list(csv.DictReader((EVIDENCE/f'{name}_predictions.csv').open()))
        predicted=list(csv.DictReader((output/f'{name}_diagnostic_prefix.csv').open()))
        a.plot([float(r['displacement_m'])*1000 for r in original],[float(r['observed_force_N'])/1000 for r in original],color='black',lw=.6,label='Complete original ordered experimental trace')
        a.plot([float(r['displacement_m'])*1000 for r in predicted],[float(r['candidate_force_N'])/1000 for r in predicted],color='#cf532f',lw=.9,label='Curved diagnostic prediction until domain guard')
        a.set(xlabel='Actuator displacement (mm)',ylabel='Axial force (kN)',title=f"{name}: predicted {item['predicted_points']}/{item['observed_points']} points; not validated")
        a.legend(fontsize=7);a.grid(alpha=.2)
    save(fig,'observed_diagnostics')
    write_report(output,summary)
    publish_html(output,summary)


def write_report(output,s):
    f=s['fit'];p=f['parameters'];u=f['unloading'];g=f['geometry'];n=f['nonlinear'];o=f['polygon'];r=f['reloading'];native=s['opensees']
    lines=["# 刘俊才角钢 PHM 形式：解析曲线本构与真实分支拟合", "", "日期：2026-10-28。新增独立模块 `initial_imperfection_material/liu_angle_phm/`。现有 TMQ、塔模型和生产参数未替换。", "",
    "**已开发真正参与应力、切线与 OpenSees 平衡迭代的曲线本构。当前是有明确补充规则的条件原型，尚非原作者 VUMAT 的完整复现，未通过角钢完整历史验证。曲线更平滑并不自动意味着拟合更准确。**", "",
    "## 1. 与原 TMQ 的区别", "",
    "原 TMQ 的压后主支是两段直线，切线为 −αE、−βE；新模块使用随应变连续变化的指数压后支、积分得到的有理恢复曲线和历史最大塑性变形控制的后续峰。初始弹性、卸载和部分强化段仍为直线，分支交接也可能存在切线突变，这符合分阶段模型的定义。没有用样条平滑图线来冒充材料开发。", "",
    "力学公式用 Python 实现，复用已有 C++ 单轴材料桥接注册到 OpenSees；桥接的历史 ClassType 名称仍包含 TianMaQu，但实际应力与切线来自 `LiuAnglePHM` 对象。桥接限制仍是 Linux/CPython/OpenSees3.8.0、单进程，不支持 MPI/数据库序列化。", "",
    "## 2. 论文与实际采用的方程", "",
    "主依据：Liu, Tian, Ma & Meng, *Phenomenological hysteretic model for fixed-end steel equal-leg angle: Development and application*, TWS183:110335 (2023)，用户提供的完整PDF第7–10页，式(3)–(15)。[出版社入口](https://www.sciencedirect.com/science/article/abs/pii/S0263823122008874)。这是2023角钢模型，与2022折线TMQ分开。", "",
    "### 压屈后曲线及切线", "", "拉为正、压为负，d=εcr−ε≥0：", "", "```text",
    "σ = σa + (σcr−σa) exp[−(η1+η2√d)d]",
    "Et = (σcr−σa) exp[−(η1+η2√d)d] (η1+1.5η2√d)",
    "σcr,1 = −φfy;  εcr 初次 = σcr,1/E",
    "```", "",
    "这是原文式(4)积分核的解析结果，但按压负约定选择恢复承载力幅值下降的符号。原文写出的 `σcr+(σcr−σa)∫...` 若直接配压负σcr，会让压应力幅值增长，必须明确这项符号解释，不能称逐字无歧义复现。原文式(7b)输出按MPa解释，并取打印的负值作为压缩渐近应力；图15画正幅值，仍需作者确认。", "",
    "```text", "λn = (λ/π)√(fy/E); a = 1.028 + 0.196λn + λn²",
    "φ = 2 / [a + √(a²−4λn²)]",
    "σa / MPa = 0.805 − 37.902 exp(−0.887λn)",
    "η1 = −180.877 + 532.191 exp(−0.240λn)",
    "η2 = 63.913 − 683.403 exp(−0.455λn)", "```", "",
    "上述回归式可以在 `from_regression` 中按长细比生成曲线；论文已拟合的回归系数不是本次重新拟合得到的。真实Carden分支拟合另列，η1/η2可以离开原文经验回归范围，只能解释为条件拟合。", "",
    "### 反向恢复曲线", "", "```text",
    "ξ2 = 1/σH − ξ1/(εH−εG)",
    "σ = σH − (εH−ε)/[ξ1+ξ2(εH−ε)]",
    "Et = ξ1/[ξ1+ξ2(εH−ε)]²",
    "ξ1 = 1/(1.1E)                      λn≤0.6",
    "ξ1 = 1/[(1.718λn+0.075)E]          0.6<λn≤1.7",
    "ξ1 = 1/(3E)                        λn>1.7", "```", "",
    "这是式(11)、(13)的解析积分，可严格满足G点零应力和H点指定应力。1.7处区间归属显式采用中段，未假装两侧完全连续。H应力比例、G–H跨度和H–I线段斜率仍需数据确定；本轮拟合暴露不可辨识，未接受为完整标定。", "",
    "### 卸载、历史退化与补充闭合", "", "```text",
    "σFt = −fy + κE(εF−εy)", "Ku = E(σF/σFt)^p; εG = εF−σF/Ku",
    "θ = (1+69.896λn εp,max)^(-1.566); σcr,后续 = θ σcr,1", "```", "",
    "论文卸载指数p=3。本轮另由真实首卸载段求一个p候选，并同时保留p=3的完整循环对照，不悄悄更改原式。κ是拉伸强化比，不是旧TMQ的kappa。εp,max当前定义为拉伸强化支上max(ε−σ/E,0)的历史最大值，属于等效构件变量；历史最大值不增长时，不因重复迭代或循环计数额外退化。", "",
    "项目补充规则：小反转沿原分支回到起点再恢复父支；I点不早于既有最大拉伸塑性伸长对应的屈服位置。这些闭合约束尚需实验审查，不能据此声称已解决旧模型左偏。每次trial从commit复制，失败回滚不污染历史。未猜测断裂阈值；超过声明应变或渐近应力与退化峰不相容时停止并报告。", "",
    "## 3. 本次真实拟合使用什么数据", "",
    "仅采用已有Carden P作者有序矢量路径，实测券样E=218 GPa、fy=338 MPa，名义A=219.2536 mm²、L=645.16 mm；位移为作动器口径，非确认杆端标距。没有使用Q优化。P/Q已在前轮检查过，Q不能再称完全未见的验证集。", "",
    f"首压主支0–112号，35号是观察首峰。压后拟合只取35–112号共78个点，保持原顺序。两种模型都固定同一个**实测峰位置**，都拟合3个自由参数，均做3组起点的有界最小二乘。这个比较只评价下降支重构，不能用来掩盖初始线性E导致的首峰位移失配。", "",
    "|拟合项目|曲线候选|折线候选/来源|", "|---|---:|---:|",
    f"|同一压后段 NRMSE / 首峰|{100*n['nrmse']:.3f}%|{100*o['nrmse']:.3f}%|",
    f"|η1、η2|{p['eta1']:.6g}、{p['eta2']:.6g}|3个自由系数之一为渐近应力|",
    f"|σa|{p['sigma_a']/1e6:.3f} MPa|残余幅值比例触碰0.4上界|",
    f"|卸载Ku/E|{u['ratio_to_E']:.6f}|固定观察反转点后线性最小二乘|",
    f"|卸载指数p|{u['fitted_exponent']:.6f}|论文为3|",
    f"|恢复段正向支NRMSE / fy|{100*r['nrmse']:.3f}%|Jacobian秩{r['local_rank']}/3，未接受|", "",
    "**曲线候选本轮没有优于重新拟合的三参数折线。** 渐近应力触界、恢复H比例触界和恢复段秩不足，表明数据范围或当前闭合形式不能支持稳定完整识别。不能把优化器success当作材料通过。拟合参数仅用于下方诊断演示，未替换全塔。", "",
    f"K=.5为固定端工程假定，由名义尺寸算得λ={g['slenderness']:.4f}、λn={g['lambda_n']:.6f}；实际连接等效长度未验证。历史退化系数69.896/1.566仍取论文，未在本轮识别。拉伸κ={p['hardening_ratio']:.8f}取既有P条件拟合，非券样强化。", "",
    "## 4. 完整循环、实际OpenSees与诊断历史", "",
    f"自定义增幅协议完整完成{s['completed_steps']}/{s['requested_steps']}步，所有点按加载顺序展示；幅值为1、2、3、4、6、8倍屈服应变。它是新生成的数值协议，不是作者试验回放。", "",
    f"步数加倍后目标应力最大差{s['doubled_resolution_max_target_stress_difference_Pa']:.6g} Pa，外功积分相对差{s['doubled_resolution_relative_work_difference']:.6g}。应力和切线直接解析求值，Gauss积分只用于外功记账，不用于平滑应力曲线。未闭合回线的∫σdε不直接命名纯耗能。", "",
    (f"实际OpenSees单杆完成{native['completed_steps']}/{native['requested_steps']}步；最大应力差{native['max_stress_difference_Pa']:.6g} Pa，反力平衡误差{native['max_reaction_error_N']:.6g} N，荷载因子平衡误差{native['max_load_error_N']:.6g} N，接口检查通过={native['passed']}。" if native else "本次未执行原生OpenSees检查。"), "",
    "已将P/Q真实完整观察路径保留在诊断图中；本构预测遇范围限制即停，不把末点水平外推。只列有预测前缀上的误差，不宣称完整回线通过：", "",
    "|记录|预测点 / 原观察点|覆盖前缀NRMSE|停止原因|", "|---|---:|---:|---|"]
    for d in s['observed_replay']:
        lines.append(f"|{d['specimen']}|{d['predicted_points']}/{d['observed_points']}|{100*d['covered_prefix_nrmse']:.2f}%|{d['stop']['reason'] if d['stop'] else '完成'}|")
    lines += ["", "## 5. 当前缺口和下一步", "",
    "1. 当前能开发并运行曲线材料，但尚未复现刘俊才原始12根固定端角钢的有序循环。需要将论文图18可辨认的试验路径与边界、标距逐一核实，再固定训练/留出试件。",
    "2. 首峰位置仍需处理：实测峰约−1.869 mm，固定实测E后的线性杆峰约−0.721 mm。不能修改坐标符号或悄悄降低钢材E来掩盖连接/几何柔度。",
    "3. 用更长的下降支约束渐近应力；目前σa触界意味着不可认为残余承载力已识别。必要时固定有来源的σa再拟合少量曲率参数，并检验不同固定值。",
    "4. H/I生成规则、ξ1与当前端部条件的适用性、卸载指数p及恢复段需重新约束。拟合到一个首卸载段，不等于所有后续循环都适用。",
    "5. 历史塑性、同幅循环、小反转与断裂必须分别验证。先对构件和小塔段验证，再讨论替换全塔；本轮没有更换全塔。", "",
    "## 6. 文件与复现", "", "`material.py`：解析本构与历史状态；`experiment.py`：分组拟合、完整协议、OpenSees单杆和范围审查；`publication.py`：图表与网页。`fit.json`保留目标、边界触碰、秩和输入文件哈希。", "",
    "```bash", "OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.liu_angle_phm.experiment --output <新的结果目录>",
    ".venv/bin/python -m unittest tests.test_liu_angle_phm -v", "```", "",
    "原始PDF与大体积数值数据保留本地。成果网页只发布固定名单的报告和结果。旧Carden符号与偏移另有独立审计，不通过翻号或平移数据来美化拟合。"]
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def publish_html(output,s):
    f=s['fit'];n=f['nonlinear'];o=f['polygon'];adapter=s['opensees']
    p=f['parameters'];tr=''.join(f'<tr><td>{escape(k)}</td><td>{v:.7g}</td></tr>' for k,v in p.items() if isinstance(v,(int,float)))
    images=[('full_hysteresis','完整往复：折线与解析曲线','所有1980个加载增量均保留。主曲线为条件候选，协议为人工数值协议；并非原论文试验复现。'),
        ('branch_fits','真实有序分支拟合','同一观察首峰、同一78点压后段，各拟合3参数。曲线渐近应力触界；恢复段秩不足，不能接受为完整参数标定。'),
        ('literature_envelopes','按论文长细比回归生成的曲线','指数曲线与解析切线进入本构计算；图中回归关系沿用文献，不是本轮新采集试验。'),
        ('observed_diagnostics','原始P/Q完整历史与有限预测范围','黑线保留全部原始观察点；橙线遇本构范围限制即停止。没有将末点外推到未算区间。')]
    sections=''.join(f'<section><h2>{title}</h2><p>{note}</p><a href="{key}.pdf"><img src="{key}.svg" alt="{title}"></a></section>' for key,title,note in images)
    html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>刘俊才角钢曲线本构实验</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#eff3f5;color:#19374b;font:16px/1.8 system-ui}}main{{max-width:1200px;margin:auto;padding:28px}}section{{background:white;padding:24px;border-radius:14px;margin:22px 0}}h1{{line-height:1.35}}a{{color:#126c8b}}img{{display:block;width:100%;height:auto}}.note{{background:#fff3df;border-left:4px solid #ad7222;padding:16px}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.metrics div{{background:#e3eff3;padding:18px;border-radius:10px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #cfdce4;padding:8px;text-align:left;overflow-wrap:anywhere}}code,p{{overflow-wrap:anywhere}}nav{{display:flex;gap:18px;flex-wrap:wrap}}@media(max-width:650px){{main{{padding:12px}}section{{padding:14px}}.metrics{{grid-template-columns:1fr}}h1{{font-size:25px}}}}</style></head><body><main>
<nav><a href="/#tianmaqu">← 成果主页</a><a href="REPORT.md">详细公式与改写报告</a><a href="summary.json">完整数值摘要</a></nav>
<h1>从折线主支走向解析曲线本构</h1><p>刘俊才2023角钢 PHM 形式 · 独立实验模块 · 2026-10-28</p>
<p class="note">已经实现曲线应力、解析切线、历史更新和实际OpenSees单杆往复。当前包含符号解释与补充闭合，<strong>尚非原作者完整复现，完整试验验证未通过，未替换全塔。</strong></p>
<div class="metrics"><div>真实压后段曲线 NRMSE<br><strong>{100*n['nrmse']:.2f}%</strong><br>折线同段 {100*o['nrmse']:.2f}%</div><div>完整人工协议<br><strong>{s['completed_steps']} / {s['requested_steps']} 步</strong><br>OpenSees接口检查：{'通过' if adapter and adapter['passed'] else '未通过/未执行'}</div><div>参数识别状态<br><strong>仍有触界与秩不足</strong><br>曲线更平滑不等于更准确</div></div>
{sections}<section><h2>实际改写了什么</h2><p>压屈后：σ = σa + (σcr−σa) exp[−(η1+η2√d)d]；恢复段：σ = σH − (εH−ε)/[ξ1+ξ2(εH−ε)]；后续峰按历史最大等效塑性变形更新。弹性和部分卸载/强化段仍为直线，未强行把整个回线画圆。</p><p>Python计算本构，C++桥接送入OpenSees。当前首峰位置、恢复支和参数适用性仍需实测约束，详见报告。</p></section>
<section><h2>本轮候选参数（含未识别项）</h2><p>K=0.5、名义几何、论文退化系数及补充历史规则均需复核。卸载p已用首卸载段条件拟合；不能推广为全部角钢的材料常数。</p><table><thead><tr><th>字段</th><th>数值 / SI制</th></tr></thead><tbody>{tr}</tbody></table></section>
<section><h2>完整数据与下一步</h2><nav><a href="curved_history.csv">全部曲线本构步</a><a href="polygon_history.csv">折线对照</a><a href="opensees_history.csv">实际OpenSees结果</a><a href="postbuckling_fit.csv">原始压后段与拟合</a><a href="reloading_fit.csv">原始恢复段与拟合</a><a href="fit.json">参数/边界/秩/来源</a></nav><p>下一步先确定原论文H/I及压缩符号口径，取得匹配边界的角钢有序历史，验证卸载、小反转和后续退化，再接塔段。原Carden偏左问题另有独立审计。</p></section></main></body></html>'''
    (output/'index.html').write_text(html,encoding='utf-8')
