"""Publish reviewed feature identification and explicitly synthetic checks."""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import math
from pathlib import Path

from .parameter_identification import DEFAULT_OUTPUT, write_json, write_csv, ordered_data, response
from .material import TMQParameters


def publish(output=DEFAULT_OUTPUT):
    output=Path(output)
    if (output/'summary.json').exists():raise FileExistsError(output/'summary.json')
    peaks=json.loads((output/'experimental_peak_features/summary.json').read_text())
    fit=json.loads((output/'algorithm_check/summary.json').read_text())
    plan=json.loads((output/'algorithm_check/frozen_plan.json').read_text())
    rows=[{k:r[k] for k in ('specimen_id','area_m2','compression_peak_N','yield_stress_Pa','identified_phi','geometry_basis','yield_basis')}
          for r in peaks['cases']]
    result={'schema':'otw2.tmq_parameter_identification_study.v1','date':'2026-10-26',
        'physical_validation':'conditional_first_buckling_feature_identification_only',
        'full_hysteresis_validation':False,'single_angle_full_cyclic_parameters_determined':False,
        'production_parameters_changed':False,'new_full_tower_runs':0,
        'peak_identification':{'source':'Black, Wenger & Popov (1980), Tables 1/2',
            'cases':rows,'identified_parameter':'phi','conditional_on':'declared nominal area and original-table fy',
            'transfer_to_tower_single_angle':False,'complete_cyclic_parameter_fit':False},
        'algorithm_check':{'data_kind':fit['data_kind'],'fitted_parameters':fit['fitted_parameters'],
            'template_provenance':fit['template_provenance'],
            'best_parameters':fit['best_parameters'],'training_weighted_force_nrmse':math.sqrt(fit['best_objective']),
            'heldout_weighted_force_nrmse':fit['heldout_protocol']['weighted_force_nrmse'],
            'local_identifiability':fit['local_identifiability'],'seeds':[r['ga']['seed'] for r in fit['runs']],
            'all_ga_runs_completed':all(not r['ga']['timed_out'] for r in fit['runs']),
            'physical_evidence':False},
        'data_contract':'otw2.tmq_ordered_history.v1; explicit units, sequence, virgin initial state, geometry and E/fy provenance',
        'artifacts':{'report':'REPORT.md','index':'index.html','peak_plot':'experimental_peak_features/peak_identification.png',
            'synthetic_full_cycles':'algorithm_check/synthetic_recovery.png','integration':'INTEGRATION.md',
            'single_angle_features':'single_angle_features/summary.json','tower_parameter_audit':'tower_audit/summary.json'},
        'evidence_sha256':{str(path.relative_to(output)):hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in [output/'algorithm_check/frozen_plan.json',output/'algorithm_check/training.json',
                           output/'algorithm_check/holdout.json',output/'experimental_peak_features/features.json']}}
    single_path=output/'single_angle_features/summary.json'
    if single_path.exists():
        single=json.loads(single_path.read_text())
        result['single_angle_features']={k:single[k] for k in ('schema','source','selected_compression_first',
            'excluded_tension_first','conditional_phi_range','single_angle_complete_parameter_set_determined','force_product_only')}
        result['single_angle_features']['feature_limitation']='maximum buckling capacity of compression-first specimens used as initial-peak proxy; initial-cycle peak not individually digitized'
        result['single_angle_features']['index']='single_angle_features/index.html'
    for name in ['training','holdout']:
        data=ordered_data(json.loads((output/f'algorithm_check/{name}.json').read_text()))
        force=response(TMQParameters(**fit['best_parameters']),data['strain'])*data['area_m2']
        write_csv(output/f'algorithm_check/{name}_ordered_predictions.csv',[
            {'sequence':int(i),'displacement_m':float(u),'synthetic_target_force_N':float(o),'fitted_force_N':float(f)}
            for i,u,o,f in zip(data['sequence'],data['displacement_m'],data['force_N'],force)])
    write_json(output/'algorithm_check/example_fit_settings.json',{
        'fixed_and_initial_parameters':plan['truth'],'bounds':plan['bounds'],
        'note':'API demonstration with synthetic same-model data; not physical calibration'})
    write_json(output/'summary.json',result)
    peak_table='\n'.join(f"| {r['specimen_id'].replace('Black_1980_','')} | {r['area_m2']*1e6:.3f} | {r['yield_stress_Pa']/1e6:.3f} | {r['compression_peak_N']/1000:.3f} | {r['identified_phi']:.6f} |" for r in rows)
    ga_table='\n'.join(f"| {r['ga']['seed']} | {math.sqrt(r['ga']['objective']):.6g} | {math.sqrt(r['local_refinement']['objective']):.6g} | {r['ga']['evaluations']} | {'完整' if not r['ga']['timed_out'] else '超时'} |" for r in fit['runs'])
    parameter_table='\n'.join(f"| {k} | {plan['truth'][k]:.8g} | {fit['best_parameters'][k]:.10g} | {fit['truth_parameter_relative_errors'][k]:.3g} |" for k in fit['fitted_parameters'])
    report=f'''# Tian–Ma–Qu 参数识别：真实首峰特征与独立算法检验

日期：2026-10-26。新增识别工作与生产材料、全塔模型隔离；本模块未修改生产默认值，未开展新的全塔有限元分析。

## 1. 先说明本次得到什么

从 Black、Wenger、Popov 1980 原始试验表中提取了 5 个试件的首次屈曲承载力，在明确面积和屈服强度口径的条件下确定 φ。首峰只能识别这一项系数，不能决定整条滞回曲线。两个双角钢和三个管材试件不等于本塔的单角钢试件。

已经实现真正的实数编码遗传算法、有序试验数据接口、参数边界、三种固定随机种子、单独标记的最小二乘细化、加载协议留出检验和局部灵敏度诊断。已给出完整往复曲线，但这些曲线来自明确标注的合成数据，作用是检验算法。它们不能证明真实角钢模型已经标定完成。

同期找到的 Carden 2006 单角钢试验由主任务独立处理，见 [单角钢识别页面](single_angle_features/index.html) 和 [文献及全塔参数整合说明](INTEGRATION.md)。选用 10 件首次先压试件，排除 7 件先拉试件，条件 φ 为 0.34945～0.76613。分母直接使用原表券样屈服力，不虚构独立的 A、fy；表 4 最大压屈容量暂作为先压组首峰的代理，尚未逐条数字化证明其确为第一循环峰值。该结果与下列 Black 对照相互独立，不假定两类试验系数可以互换。

## 2. 文献与参数机制审计

2022 JBE 论文官方摘要说明优化了 9 项系数：α、β、τ、μ、ν、η、θ、φ、κ。本文的算法是自建的可复算实现，不能称为复现了作者未公开的优化器设置。[出版社论文入口](https://doi.org/10.1016/j.jobe.2021.103798)

| 参数 | 当前实现中的作用 | 需要的识别信息 |
|---|---|---|
| E、fy | 初始弹性刚度和屈服尺度 | 实测券样、截面及端部位移定义；构件滑移不能当作材料 E |
| φ | 首次压屈峰值，Pcr=φ A fy | 处于初始状态的首压峰值；先拉后压的首峰可能已有历史影响 |
| α、β、γ | 首压屈曲后两段下降斜率与分界强度 | 连续首压下降支，覆盖两段转折 |
| ρ | 拉伸屈服后斜率 ρE | 足够大的拉伸塑性段 |
| τ、μ、ν、ζ | 受压后的卸载、捏拢及重新拉伸段 | 有序反向加载路径，尤其低力区和拉伸恢复段 |
| η、θ、κ | 后续压屈峰值和两段下降斜率 | 第二次及以后完整受压支 |
| residual_compression_ratio | 当前原型额外设置的尾部常值下限 | 属于实现附加假设，不是本次文献标定成果 |

现有管材示例中 E、ρ、γ、ζ 的取值有假设成分；仅把文献 9 项数字填入当前原型，不会消除这些假设。当前原型还采用了未由原始 VUMAT 验证的小反转闭合规则，因此即使优化误差小，也需要区分“参数误差”和“本构闭合规则误差”。

## 3. 真实 Black 首峰条件识别

来源：[Black 等 1980 原报告](https://nehrpsearch.nist.gov/static/files/NSF/PB81154312.pdf)，表 1 位于印刷页 45／PDF 第 59 页，表 2 位于印刷页 47／PDF 第 61 页。PP 为两端铰接；PF 为一端固接、一端铰接。

| 试件 | 名义面积 mm² | 原表 fy 换算 MPa | 首次屈曲力 kN | 条件 φ |
|---|---:|---:|---:|---:|
{peak_table}

计算为 φ=Pcr/(A fy)。这里的单参数 GA 用于核验识别接口，直接比值才是此问题最清楚的解法；不能将峰值几乎零误差解释为模型获得了独立循环验证。

- 8、20 号为 2-L6×3½×⅜ in 双角钢，短肢向外、有间隔。面积按两根尖角 L 形截面的毛面积计算，未计轧制圆角，也不是重新测量所得面积。表 2 注 b 的 fy 为券样平均屈服强度。
- 14、15 号为 Pipe 4 Std.，采用名义外径 114.3 mm、壁厚 6.02 mm；24 号为 Pipe 3½ Std.，采用 101.6 mm、5.74 mm。表 2 注 c 的 fy 来自构件试验的首次屈服，不是独立券样结果。
- 全部采用 1 kip=4448.2216152605 N、1 ksi=6894757.293168 Pa，未混用原表脚注的 4.45 kN 和 6.89 MPa 近似换算。
- 原表没有提供本次所需的测量误差或名义面积误差，因此这里不制造统计置信区间。φ 对 A、fy 的相对误差均为反比例关系：小误差下 dφ/φ≈dP/P−dA/A−dfy/fy。
- 不能把 Black 14、15 分别强制对应到当前 `p102_row_a/b`；也不能把双角钢这两个直接比值当成 2022 年全曲线 GA 的替代结果。GA 同时拟合全曲线时的最优 φ 可以与恰好匹配一个峰值的 φ 不同。

![真实首峰与条件参数](experimental_peak_features/peak_identification.png)

未把 2014 Q345 单角钢论文表 5 的全试验最大受压力 Pc 直接当作首压屈曲值：它并未在当前提取中被证明属于初始状态首峰。数据接口明确区分 `first_buckling_peak` 和 `whole_test_compression_maximum`，后者会被拒绝。

## 4. 有序试验数据接口

输入 schema 为 `otw2.tmq_ordered_history.v1`，完整范例见 [training.json](algorithm_check/training.json)。真实试验接入时必须替换合成数据及其全部来源标识，而不是只把 `data_kind` 改名。

必须声明：`data_kind`（experiment、numerical_reference 或 synthetic_same_model）、试件编号、来源、`ordered=true`、加载顺序依据、初始状态、杆长、面积、几何定义、E/fy 及其来源、位移/力单位、拉力为正的符号约定。每行必须包含严格递增的 sequence、位移、力；可包含单调加载段 segment 和严格递增的 time。

当前接口只支持独立初始化的零位移、零荷载状态。初始力容许值默认为 0.001 N，可在明确仪器零点误差依据时显式修改。存在预载、已经屈曲或未知历史的截断记录不能直接接入。必须区分杆端相对位移、试验机横梁位移和含连接滑移的位移。

接口不会按位移或力对点排序。扫描滞回图中的散点不含可靠加载顺序，不能直接用于逐点时程 NRMSE。必须先人工确认各支路的先后顺序、方向、起点与循环编号，保留数字化误差；否则只能拟合能独立辨认的特征。

## 5. 优化目标、边界和算法

目标 J=Σwᵢ(Fmodelᵢ−Fobsᵢ)²/Fscale²。Fscale 为固定的观测绝对峰值（下限 1 N），每个 segment 的总权重相同，再整体归一化；本合成协议的初始零点为独立 segment 0。NRMSE=√J，不混用不同时长的曲线面积。

每个候选参数均新建材料，从初始状态按完整加载顺序逐点求解。先冻结边界和协议：φ∈[0.55,0.90]、α∈[0.25,0.70]、β∈[0.008,0.035]（对数编码）、γ∈[0.30,0.65]、η∈[0.35,0.65]。这些边界服务于算法测试，不是文献证明的通用物理区间。其余参数固定并明确保存在 JSON 中。

GA 为实数编码：种群 28、35 代、三元锦标赛选择、混合交叉、概率 0.25 的高斯变异、2 个精英保留、基因截断到 [0,1]。每次运行分别使用 seed 17、29、43；单次 GA 上限 100 秒。不是差分进化。之后使用 `scipy.optimize.least_squares`，最多 100 次函数求值，单独记录其结果。

候选材料必须满足原型参数约束；搜索矩形还要求整个范围满足 ν>μ、残余强度比例<γ，避免局部差分越过耦合约束。无有效候选会明确失败。命令行失败保留 failure.json 和输入快照；已经存在的输出目录拒绝覆盖。超时 GA 保存已取得的结果及 timed_out 状态，不能当作正常完整运行。

## 6. 合成恢复与留出协议：仅检验算法

训练及留出协议在优化前写入 frozen_plan.json。五项真值刻意与示例原值不同，其他系数固定。留出的是另一套加载路径，训练和留出都由同一个材料实现生成，因此属于同实现自检，不能检验该实现是否符合试验。

| seed | GA 单独 NRMSE | GA 后局部细化 NRMSE | GA 候选求值数 | 状态 |
|---|---:|---:|---:|---|
{ga_table}

| 参数 | 合成真值 | 最佳恢复值 | 相对误差 |
|---|---:|---:|---:|
{parameter_table}

最佳训练 NRMSE={math.sqrt(fit['best_objective']):.6g}；留出加载协议 NRMSE={fit['heldout_protocol']['weighted_force_nrmse']:.6g}。误差极小的原因是同模型无噪声数据，不应拿这个数值作为真实构件拟合精度。

局部归一化基因 Jacobian 秩为 {fit['local_identifiability']['rank']}/5，条件数约 {fit['local_identifiability']['condition_number']:.2f}；只说明该特定无噪声协议附近五个自由参数产生可区分的响应，不证明全局唯一，也不是参数的统计置信区间。三次起点局部细化后的参数范围保存在 summary.json。未研究实验噪声、实际几何误差和闭合规则误差下的稳健性。

![合成数据完整往复曲线及GA收敛](algorithm_check/synthetic_recovery.png)

另有两个有针对性的不可识别性测试：首峰相同但 α、η 不同会出现不同下降/再压响应；完全未达到屈曲与屈服的微幅循环对下降支及再压参数没有识别能力。这也是不能从当前近似直线的塔推覆曲线反推出全部 TMQ 系数的原因。

## 7. 复算与接入步骤

项目根目录使用 `.venv/bin/python`，建议 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`。以下输出路径必须尚不存在：

```bash
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.parameter_identification black-peaks --output /tmp/tmq-black-recheck
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.parameter_identification synthetic-check --output /tmp/tmq-synthetic-recheck
.venv/bin/python -m unittest tests.test_tmq_parameter_identification -v
```

一般有序数据拟合命令：

```bash
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.parameter_identification fit-history --manifest ordered_history.json --settings fit_settings.json --output /tmp/tmq-ordered-fit
```

`fit_settings.json` 的 `fixed_and_initial_parameters` 必须提供完整材料字段，`bounds` 列出拟合字段与冻结边界。语法示例见 [example_fit_settings.json](algorithm_check/example_fit_settings.json)，它针对合成数据，仅用于接口示范。一般拟合输出保留完整有序预测 CSV、全滞回图、力随序号曲线、GA 每代历史和三次运行参数。代码将 GA 与局部细化结果分开记录。

新增测试覆盖单位转换、加载顺序、初始状态、非有限数、来源字段、E/fy 一致性、耦合边界、GA 固定种子、精英单调改进、无效种群、峰值类型与量纲、不可识别性及输出保护。测试日志见 [verification.log](verification.log)，结构化验收见 [verification.json](verification.json)。

## 8. 下一步真正的物理标定

1. 优先使用有截面、杆长、端部连接与加载协议的单角钢试验，区分偏心连接、螺栓滑移和材料本身。
2. 从原始采集文件或可追溯数字化路径获得完整有序 u–F；每个循环标注方向、级别和反转点。若只有首峰，仍只识别 φ。
3. 先固定独立实测 E、fy、几何和端部条件，再按首压下降、拉伸恢复、再次压屈分组开放参数；不要一次要求所有系数唯一。
4. 冻结拟合试件、留出试件和评价阈值，再做多种子 GA、局部细化与灵敏度；留出数据不能用于调边界后再报独立验证。
5. 若不同参数组误差接近但预测不同，报告多解范围；通过补充卸载/再加载试验消除不可识别性，而不是选一组数字写成确定材料。
6. 只有完整循环的刚度、首峰、后续峰、残余变形、回线面积通过真实试验评价后，才考虑按截面/杆长/连接分组映射全塔。构件等效应变仍不能直接当作钢材纤维塑性应变。

本次没有把合成真值写回生产参数。与全塔的参数来源、Perry φ 映射和后续应用决策，见 [INTEGRATION.md](INTEGRATION.md) 与 [tower_audit/summary.json](tower_audit/summary.json)。
'''
    (output/'REPORT.md').write_text(report)
    table=''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in [r['specimen_id'].replace('Black_1980_',''),f"{r['compression_peak_N']/1000:.3f}",f"{r['identified_phi']:.6f}"] )+'</tr>' for r in rows)
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TMQ 参数识别｜2026-10-26</title>
<style>body{{margin:0;background:#f2f5f8;color:#183040;font:16px/1.75 system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:32px 22px}}h1{{font-size:30px}}h2{{font-size:23px;margin-top:8px}}section{{background:white;border:1px solid #dce4eb;border-radius:14px;padding:24px;margin:22px 0}}.notice{{border-left:5px solid #bf8b36;background:#fff9ec;padding:14px 20px}}a{{color:#116b91}}img{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;border-bottom:1px solid #dce4eb;text-align:left}}.links{{display:flex;gap:20px;flex-wrap:wrap}}.badge{{padding:3px 9px;border-radius:6px;background:#e7f1f6;font-size:14px}}p{{margin:12px 0}}</style><main>
<h1>Tian–Ma–Qu 参数识别</h1><p>2026-10-26 · 文献试验特征、可复算遗传算法与有序数据接口</p>
<div class="notice"><strong>本页已确定的是明确试件条件下的首峰 φ。</strong>完整循环参数尚未获得真实试验验证。未修改生产默认参数，未新增全塔计算。</div>
<p class="links"><a href="REPORT.md">完整中文方法与步骤</a><a href="INTEGRATION.md">文献与全塔应用说明</a><a href="summary.json">结构化汇总</a><a href="verification.log">测试日志</a></p>
<section><h2>真实单角钢试验：10 件先压试件</h2><p>Carden 2006 原表给出的条件 φ 为 <strong>0.34945～0.76613</strong>。已排除 7 件先拉试件；直接使用券样屈服力作为分母。当前把先压组最大压屈容量作为首峰代理，尚未逐条核实第一循环峰值。连接和杆件条件仍需核对。</p><p class="links"><a href="single_angle_features/index.html">打开单角钢识别页面与图表</a><a href="single_angle_features/summary.json">单角钢结构化结果</a><a href="INTEGRATION.md">适用范围与参数采用说明</a></p></section>
<section><span class="badge">真实试验表 · 单一特征</span><h2>Black 1980：5 件试件的条件 φ</h2><p>使用原表首次屈曲力及 fy，面积为明确声明的名义面积。φ=Pcr/(A fy)。首峰拟合不约束卸载、捏拢和后续压屈；双角钢及管材不能直接替代本塔单角钢。</p>
<table><thead><tr><th>原始试件</th><th>首次屈曲力 kN</th><th>条件 φ</th></tr></thead><tbody>{table}</tbody></table>
<img src="experimental_peak_features/peak_identification.png" alt="Black真实首峰及条件phi"><p>8、20 号为双角钢，fy 来自平均券样；14、15、24 号为管材，fy 是构件试验首次屈服值。名义面积和原表测量误差未形成统计置信区间。</p>
<p class="links"><a href="experimental_peak_features/identified_peak_parameters.csv">参数CSV</a><a href="experimental_peak_features/summary.json">全部来源及GA历史</a><a href="experimental_peak_features/peak_identification.svg">SVG图</a><a href="experimental_peak_features/peak_identification.pdf">PDF图</a><a href="https://nehrpsearch.nist.gov/static/files/NSF/PB81154312.pdf">原始报告</a></p></section>
<section><span class="badge">合成数据 · 仅算法检查</span><h2>完整循环恢复与未参与拟合的加载协议</h2><p>3 组种子运行真正的 GA，之后单独进行最小二乘细化。五项参数由同一材料实现生成并恢复。留出 NRMSE={fit['heldout_protocol']['weighted_force_nrmse']:.3g}，这个极小误差不代表真实角钢拟合精度。</p>
<img src="algorithm_check/synthetic_recovery.png" alt="合成训练及留出协议完整滞回与GA历史"><p>左为合成训练全循环，中为另一加载协议的全循环，右为仅 GA 的收敛历史。局部 Jacobian 秩 {fit['local_identifiability']['rank']}/5，不能据此断言实验数据可唯一识别。</p>
<p class="links"><a href="algorithm_check/summary.json">算法完整记录</a><a href="algorithm_check/ga_history.csv">GA逐代历史</a><a href="algorithm_check/training_ordered_predictions.csv">训练全循环CSV</a><a href="algorithm_check/holdout_ordered_predictions.csv">留出全循环CSV</a><a href="algorithm_check/synthetic_recovery.svg">SVG图</a><a href="algorithm_check/synthetic_recovery.pdf">PDF图</a></p></section>
<section><h2>下一步：取得真实有序历史后分组识别</h2><p>先固定实测 E、fy 与几何，识别首压峰和下降支，再利用卸载—再加载、后续压屈分别约束相应系数。扫描图的无序点不会被当成时程。仅有弹性段的曲线无法辨识屈曲后参数。</p><p class="links"><a href="algorithm_check/training.json">数据接口示例（合成）</a><a href="algorithm_check/example_fit_settings.json">设置示例（合成）</a><a href="tower_audit/summary.json">全塔当前参数来源审计</a></p></section>
</main></html>'''
    (output/'index.html').write_text(page)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args();publish(args.output);print(args.output)
