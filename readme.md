# 易损性分析流程

## 科研图表统一重绘（2026-11-06）

使用 nature-figure 技能整合公共科研绘图出口，完成材料滞回、全塔推覆、单塔/塔线静风及雨荷载7组37幅图。
提供300 dpi PNG与PDF/SVG，保留曲线顺序、停止点和科学限定。37幅渲染审计通过，45项独立测试通过；原始数据与大图留在本地。

[9999图册](http://localhost:9999/scientific-figures/) · [方法、范围与复现说明](util/postprocess/SCIENTIFIC_FIGURES.md) · [检查汇总](validation/figure_refactor_20261106/summary.json)

## 阶段同步与最新入口（2026-11-02）

后续在完成并验证一个阶段后提交、推送到 `redevelop`。同步代码、测试、方法、结论报告、文献索引和必要的小型参数文件；
大型静态资源、论文全文、逐步计算数据和重复代码快照保留本地。提交前检查暂存清单和文件大小，避免直接 `git add .`。
已有 Git 历史中的资源不重写、不删除；本地重算产生的历史已跟踪数据变化也不随本轮上传。

- [Steel01 / Steel02 四分段与 TMQ 全塔推覆：实际曲线及停止原因](initial_imperfection_material/tower_material_pushover/README.md)
- [单角钢曲线型材料原型](initial_imperfection_material/liu_angle_phm/README.md)与[四分段初始缺陷核查](initial_imperfection_material/segmented_member_validation/README.md)
- [雨谱、塔线雨荷载及静力验证](rain_loading/results/REPORT.md)
- [风雨通用节点荷载接口：单位、时程、叠加及移除](util/processing/NODAL_LOADS.md)
- [新材料、输电塔风荷载和风雨荷载文献索引](literature/material_wind_rain_20261102/README.md)

当前工作区的 9999 网页继续使用本地完整结果。新克隆包含网页代码及文字结论，图表、时程和部分证据复核测试需要按各模块说明重算或另行取得数据。
文献表中的本地 PDF 链接只对原工作区有效；GitHub 阅读时使用同表的 DOI 或出版入口。

本轮发布前另对去除已保存结果的源码副本进行检查：53项测试通过；3项历史证据测试和1个雨荷载证据测试类因本地结果未附而跳过，无失败。
这不替代原工作区已完成的66项相关回归，也不代表全部研究模块已重新计算。[发布检查记录](validation/git_publish_20261102/summary.json)。

## 四分段初始缺陷验证（2026-10-29）

三根真实塔杆完成63个空间单杆数值工况，分别检查长度分段、截面纤维、完整往复和缺陷方向/幅值。四段相对32段最大压力偏高约0.56%～5.08%；此结论限于所测独立铰接单杆。全塔与新试验已共用完整Steel02参数，默认初弯曲改为L/1000，历史结果保留。

[步骤、结果和复现方法](initial_imperfection_material/segmented_member_validation/README.md) · [9999独立结果页](http://localhost:9999/segmented-validation/)。

## TMQ参数识别进展（2026-10-26）

已核实遗传算法参数来源，整理两组双角钢与三组管件候选；实际完成10件先压单角钢的条件容量比、
5件Black试件首峰比识别。GA与局部精修的完整滞回恢复属于合成算法检验，本塔完整循环参数尚未标定，生产默认值未改。
当前按用户要求优先推进材料参数，塔线动力任务保留在原计划中。

[文献文件夹](literature/tmq_parameter_identification_20261026/README.md) ·
[参数采用结论与全部步骤](initial_imperfection_material/tian_ma_qu/followup_results/parameter_identification_20261026/INTEGRATION.md) ·
[9999结果页](http://localhost:9999/tmq/followup_results/parameter_identification_20261026/index.html) ·
[统一任务进度](docs/ai_execution_plan/CURRENT_STATUS.md)。新增参数及证据测试24项通过，35项HTTP检查及桌面/移动端显示通过。

## 当前成果总览（2026-10-24，redevelop）

本次整理上传从等效初始缺陷材料到 Tian–Ma–Qu（TMQ）单杆、全塔和单塔四跨导线模型的代码、
方法说明、结论报告、任务计划与测试记录。原始计算数据、压缩归档及预生成图表/网页保留在本地。
**完成计算、通过软件测试、通过物理验证是不同状态。**
目前为研究原型，尚不能把求解终点或静态荷载换算风速作为实际线路的倒塌风速。

| 成果 | 当前结果与限制 | 详细入口 |
| --- | --- | --- |
| 等效初始缺陷单杆 | 修正峰前可逆卸载；含网格收敛、实际杆长验证与骨架重构；适用范围仍受标定约束 | [单杆报告](initial_imperfection_material/REPORT.md) |
| 旧等效材料全塔往复与查因 | 保存完整/部分完成算例、关键杆状态与收敛诊断；局部适用域验证不能被整体曲线吻合替代 | [全塔报告](initial_imperfection_material/FULL_TOWER_CYCLIC_REPORT.md)、[收敛诊断](initial_imperfection_material/CONVERGENCE_DIAGNOSIS.md) |
| TMQ 新材料 | 三组单杆完整滞回及原生 OpenSees 桥接；实现文献机制，未完成原作者试验及本塔角钢的定量标定 | [材料说明](initial_imperfection_material/tian_ma_qu/README.md)、[改写报告](initial_imperfection_material/tian_ma_qu/REPORT.md) |
| TMQ 全塔与薄弱位置 | 有界循环完成15/15目标、409步，4根杆进入压屈；扩展循环10/15目标后在最小步长处停止 | [全塔方法](initial_imperfection_material/tian_ma_qu/README.md#独立全塔入口)、[薄弱位置方法](initial_imperfection_material/tian_ma_qu/README.md#参照罗贤超的薄弱位置分析) |
| 风攻角与风速探索 | 单塔和单塔四跨导线分开；45°推覆峰值换算风速约110.98/108.40 m/s，仅代表当前假设下的静态曲线 | [风向加载](initial_imperfection_material/tian_ma_qu/README.md#多风角加载单塔与单塔导线体系)、[风速结论](initial_imperfection_material/tian_ma_qu/README.md#等效风速探索) |
| 塔线模态与B1诊断 | 40→80段指定静位移最大非近零差0.1824%；80段160阶对部分挂点位移重构仍有约14%误差；实际阻尼/瞬态尚未验证 | [B1报告](initial_imperfection_material/tian_ma_qu/followup_results/B1_20261024/REPORT.md)、[模态方法](initial_imperfection_material/tian_ma_qu/README.md#加导线后的初步模态分析) |
| 绝缘子受压复核（新增） | 已有0°/45°保存状态中，约46.03/65.36 m/s首次记录到V串一肢受压；45°峰值处约−10.96 kN，现有模型未模拟松弛或压屈 | [复核方法](initial_imperfection_material/tian_ma_qu/insulator_audit.py)、[小型结论汇总](initial_imperfection_material/tian_ma_qu/followup_results/insulator_audit_20261024/summary.json) |
| V串松弛敏感性（后续完成） | 三种轴向假设×0°/45°共6组均完成至100 m/s；仅受拉使控制点位移增加约3.12%/0.58%，挂点沿风位移幅值却由0.147/0.096 m增至0.966/0.562 m | [步骤、结果与复现](initial_imperfection_material/tian_ma_qu/README.md#v串受压与松弛敏感性2026-10-24)、[完整报告](initial_imperfection_material/tian_ma_qu/followup_results/insulator_sensitivity_20261024/REPORT.md) |
| B2网格与N06频响（最新） | 仅受拉40→80段41项静态输出逐点通过；旧弹性V串300阶挂点静柔度误差降至1.57%/1.20%；实际动力阻尼未验证 | [本批结果](initial_imperfection_material/tian_ma_qu/followup_results/B2_20261024/REPORT.md)、[24项最新进度](docs/ai_execution_plan/CURRENT_STATUS.md) |

**已完成受压假设和仅受拉模型40/80段静态网格对照；下一步推进N07瞬态小模型与N09风场核验，同时补实际挂线资料。** 当前V串每肢长约9.55 m，
配置中4 m是垂向落差；当前仅两路单根导线、共四跨、远端固定。实际相线/分裂数/地线、邻塔柔度、
垂度与张力条件仍需核实。模态扩阶可改善截断误差，但不能解决上述物理假设问题。
此前B1的诊断结果保留，当前物理核查范围见[TMQ说明](initial_imperfection_material/tian_ma_qu/README.md#当前塔线模型的物理适用范围2026-10-24)。
N06已由B2完成有范围的数值检查，尚不放行实际阻尼或全塔非线性风振。B2另发现0°约92.64～93.18 m/s首次超过导线目录123.04 kN计算拉断力，
当前模型无导线断裂机制，不能把100 m/s仍收敛解释成实际线路完好。

### 发布范围与运行

**本次Git提交不附原始数据。** SQLite内力库、逐步CSV/JSONL、模态矩阵/振型、压缩包、论文PDF、
截图及预生成结果页面均留在原工作区。本次也不更新已跟踪的历史原始数据/图像；结论以报告中的日期和工况为准。
历史报告保留本地证据路径用于追溯，这些路径不保证在新克隆中存在。
9999网页在当前工作区仍可读取完整本地结果；新克隆需要重算或另行取得对应数据后才能完整浏览。

```bash
# 安装项目依赖且具备本地结果后启动网页；本机既有服务使用9999端口。
.venv/bin/python -m py_view.results_dashboard --host 127.0.0.1 --port 9999

# 完整测试含本地数据复核，需具备相应数据；原生桥要求详见材料说明。
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 TMQ_TEST_NATIVE=1 CXX=/usr/bin/g++-13 \
  .venv/bin/python -m unittest discover -s tests -v

# 不依赖已保存全塔结果的材料、协议、质量逻辑和轴力重建测试。
.venv/bin/python -m unittest tests.test_tian_ma_qu_material \
  tests.test_cyclic_protocol_contract tests.test_result_quality tests.test_tmq_insulator_audit -v

# 仅从已有节点位移重建绝缘子轴力，不进行新的有限元分析；输出目录必须不存在。
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.insulator_audit \
  --output /tmp/otw2_insulator_audit_new
```

上一轮发布时本地完整回归468项通过、0跳过；另有7项定向检查，其中6项重复，合计469项独立测试通过。
见[测试汇总](validation/git_publish_20261024/tests.json)、[去重清单](validation/git_publish_20261024/tests_aggregate.json)
及[完整日志](validation/git_publish_20261024/tests.log)。这些结果不表示缺少本地数据的新克隆可直接运行全部证据复核测试。
原生编译缓存和Python字节码不提交，原生桥源码、构建逻辑及固定来源校验保留。
历史报告中的绝对路径记录原计算环境，跨机器运行使用仓库相对路径命令。
前一批V串扩展另完成74项相关测试（0失败、0跳过），并核对六组算例全部786个保存状态的平衡和3144条肢杆轴力；
不将上一轮全量测试视作本轮重新执行。新结果入口为9999网页“V形绝缘子受压与松弛对照”。
最新B2整合回归115项通过、0跳过，见[B2验证记录](initial_imperfection_material/tian_ma_qu/followup_results/B2_20261024/verification.json)。

通用分析基础模块及使用说明见
[`util/analysis/README.md`](util/analysis/README.md)，包含循环协议、自适应求解、风荷载预检查、
共同区间响应比较与任务状态记录。可运行 `.venv/bin/python -m util.analysis.demo` 验证独立小算例。

后续研究与开发的详细任务书见
[`docs/ai_execution_plan/README.md`](docs/ai_execution_plan/README.md)：包含25项任务、依赖与验收门槛、
机器可读任务清单及可直接交给后续AI的开工提示。计划已开始实施，当前进展与逐角色步骤/结果见
[`执行记录`](docs/ai_execution_plan/execution_20261022/execution_log.md)，具体完成状态以TASKS.json及证据为准，不能将整份计划视为全部已实现。

## 此分支进行易损性分析


### 1.考虑屈曲的输电塔建模

将杆件一分为4，并在中点处添加初始位移，建模如下

<img src="static/2026_05_27/image.png" width=500>

<img src="static/2026_05_27/PixPin_2026-05-27_14-57-07.png" width=500>

### 2.不同初始缺陷下的推覆分析

初始缺陷取 1/1000杆长 的倍数 1/1000 * L , 2/1000*L, ...

结果如下

#### （1）顶点位移
<img src="static/2026_05_27/70d94026-5c1c-41d7-88b4-5114d519db5f.png">

####  (2) ISDR
<img src="static/2026_05_27/plot_reaction_drift.png">

### 3.等效初始缺陷材料单杆试验

在保留原分段模型作为对照的前提下，新增了
[`initial_imperfection_material`](initial_imperfection_material/README.md) 实验模块。
该模块以 Z30103A6 的 `L125x8Q345` 为试件，对比收敛后的分段几何缺陷杆、
单单元可逆等效材料和无缺陷 `Steel02` 直杆，并输出推覆曲线、卸载验收、
网格收敛、实际杆长验证、材料骨架、缺陷敏感性和误差指标。详细方法及修订结果见
[`initial_imperfection_material/REPORT.md`](initial_imperfection_material/REPORT.md)。

### 4.等效材料全塔往复试验

等效轴向本构已通过保留弹性弯曲、扭转通道的聚合梁截面接入 Z30103A6 全塔，
并与4段几何初缺陷全塔进行了正负0.1%、0.3%、0.6%和1.0%漂移循环对照。
共同完成的正负0.6%范围内，目标点基底剪力最大误差为0.321%，1528根物理杆
轴力包络相关系数为0.999964；但等效模型未能通过后续+1.0%目标，尚不能直接用于
任意强度的循环风振分析。完整方法和结果见
[`FULL_TOWER_CYCLIC_REPORT.md`](initial_imperfection_material/FULL_TOWER_CYCLIC_REPORT.md)。


### 5.输电线建模

下面是早期独立导线找形示例。当前TMQ单塔四跨入口使用初始抛物线垂度与预张力，再进行整体重力平衡，
没有在该入口重新迭代拟合目标垂度；不能用此历史示例宣称当前四跨初态已经按实际线路找形标定。

使用聚合截面命令定义输电线截面，赋予其较大轴向刚度

```python
ops.uniaxialMaterial("Elastic", 1, EA)
ops.uniaxialMaterial("Elastic", 2,nonaxial_stiffness)
ops.uniaxialMaterial("Elastic", 3, nonaxial_stiffness)
ops.uniaxialMaterial("Elastic", 5, nonaxial_stiffness)
ops.uniaxialMaterial("InitStressMaterial", 4, 1, init_force)
ops.section("Aggregator", 1, 4, "P", 2, "Mz", 3, "My", 5, "T")

```

使用有限元找形法，确定输电线重力作用下的位形

1.首先需要确定找形目标，一般来说以输电线最低点弧垂或者最低点轴向应力为找形目标，我这里以弧垂为例进行找形，假定最终弧垂为8m

<img src="static/2026_05_27/ecdd1f85-f0d3-47dc-9893-68480eb16608.png">

2.每次开始迭代的初始位形相同，改变的是初始应力的大小，经过7次迭代，最终最低点弧垂收敛到7.9995，结束迭代。

<img src="static/2026_05_27/ae829b7d-85a1-4158-8ed9-5169b0aad105.png">

3.输电线模态分析
<img src="static/2026_05_27/modes_3x2.png">

2026-10-29全塔位移控制推覆已形成独立模块：[方法、复现与本轮结论](initial_imperfection_material/tower_material_pushover/README.md)。完成Steel01/Steel02四分段及TMQ整杆等效、四风角共12次尝试，首次Newton失败即停止留证；网页入口为 [全塔推覆结果](http://localhost:9999/tower-pushover/)。0°钢材方案已观察到屈服及峰后下降，TMQ的截断前缀尚不能作为极限容量；本轮未指定易损性等级。
