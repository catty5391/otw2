# Tian–Ma–Qu 单杆与独立全塔实验

本模块保留原单杆实验，并新增独立全塔入口，不替换原有塔模型及结果。它实现文献分段机制，并通过实验性 OpenSees 适配进行计算；**不是原作者 VUMAT 的完整复刻，也未完成原试验或本塔角钢的定量标定**。

2026-10-24发布范围：本次同步代码、方法和结论，原始计算数据、图表与预生成结果页保留本地。
下文的结果文件链接用于原工作区追溯，新克隆需重算或另行取得数据后使用；当前9999网页继续读取本地数据。

## 当前塔线模型的物理适用范围（2026-10-24）

当前为单塔、两路单根导线、前后各300 m共四跨、两组V串、固定远端的简化模型。
导线的垂度约8.055 m、索力约20.71～20.83 kN、最低频率约0.195077 Hz，量级相容。
实际挂线图、分裂数、地线、EA/初张力、邻塔柔度和角钢材料标定尚未统一验证。

对既有保存节点位移按 `N=EA*(L_current/L_initial-1)` 重建当前 `Elastic + corotTruss` 绝缘子轴力，
没有重跑全塔。四肢重力初态均约5.90 kN拉力；0°工况第18步、45°位移控制工况第32步首次保存到超过1 N的压力，
换算风速分别46.03、65.36 m/s；45°峰值第88步最小肢杆力约−10.96 kN，对应108.40 m/s。
90°已保存全过程保持受拉。离散首次记录不等于精确临界点，换算风速不等于工程设计或倒塌风速。

当前绝缘子保持拉压对称弹性刚度，没有松弛或压屈。应先按实际绝缘子类型与抗压能力决定模型，
不能未经依据直接采用无限弹性抗压，也不能将所有复合绝缘子一概视作完全不能受压。
V串两上挂点相距17.35 m、垂向落差4 m，每肢实际9.55 m、夹角约130.5°，需要核对真实几何。
因此强风峰值只能作为旧假设下的数值结果保留；物理核查与修正后的0°/45°对照优先于模态扩阶。

证据：[逐步轴力](followup_results/insulator_audit_20261024/leg_forces.csv)、
[汇总与源文件SHA-256](followup_results/insulator_audit_20261024/summary.json)、
[重建脚本](insulator_audit.py)。该脚本仅适用于当前无初应变/初应力的弹性绝缘子，不能直接用于以后修改的材料。
公式与[OpenSees CorotTruss源码](https://github.com/OpenSees/OpenSees/blob/master/SRC/element/truss/CorotTruss.cpp)中的工程应变定义一致。

仓库成果索引、发布范围与当前测试见[项目首页](../../readme.md#当前成果总览2026-10-24redevelop)。

- [完整曲线与逐步回放](results/index.html)（下载/本地用浏览器打开）
- [完整滞回图 PNG](results/full_hysteresis.png) / [矢量 PDF](results/full_hysteresis.pdf)
- [改写与验证报告](REPORT.md)
- [来源、数学式和缺项](../../literature/transmission_tower_wind/tian_ma_qu_sources.md)
- [原始汇总及参数](results/summary.json)
- [新材料全塔：实施步骤、完整曲线、停止点和逐步回放](tower_results/index.html)
- [全塔运行及弹性对照汇总](tower_results/publication.json)
- [参照罗贤超的薄弱位置筛查：位置查询、节间沿高曲线和方法报告](weakness_results/index.html)
- [单塔与一塔四档导线：多风角加载、小幅循环与验收报告](directional_results_v2/index.html)
- [等效风速探索：单调增风、首次压屈、数值停止与步长复核](wind_speed_results/index.html)
- [塔线初步模态分析：频率、振型动画、参与质量和导线网格对照](modal_results/index.html)

## 加导线后的初步模态分析

`modal_analysis.py`独立重建单塔或一塔四档体系，先完成自重与既有导线初力的平衡，再求无风、无阻尼切线模态。它使用与风速探索相同的质量、杆件和导线模型，但不加载风，也不继承推覆后的材料历史。原全塔摘要中的`initial_frequencies_Hz`仍是加导线前的单塔初始值，本模块另行保存耦合频率，避免混淆。

本批单塔取20阶，导线按20、40、80段/档分别取160阶。原生ARPACK的40段尝试因未完整收敛被校核拒绝，保留在未发布目录；正式结果使用OpenSees官方PythonSparse接口与SciPy移位反演，保存K、M、方程振型及节点6自由度振型。校核包括重力平衡、特征方程残差、质量正交性、节点/方程映射和与原生`modalProperties`的参与质量一致性。单塔及20段模型还与默认ARPACK频率交叉比较。

80段/档结果中，最低频率约0.19508Hz，周期5.126s，主要是导线横向摆动。塔身扭转、X侧摆、Y侧摆的代表模态分别位于全体系81、90、99阶，频率约2.104214、2.269358、2.505670Hz。按原塔节点质量加权MAC匹配形状，并保留附近的耦合候选，不能直接将两个模型的同一阶号相比。塔身频率变化小，不代表横向参与质量分配已网格收敛；20→40→80段对照仍显示该分配敏感。

有效质量比的分母是各方向自由质量，指标对应均匀支座惯性激励，不能直接当作风荷载广义力参与系数。80段模型前160阶X/Y/Z累计占比约48.24%/61.38%/7.49%；本次是低频与塔身首三振型筛查，不宣称动力响应截断充分。动画显示的位移已归一化，塔身局部视窗单独放大；近重频导线振型的相位组合不是唯一。

```bash
CXX=/usr/bin/g++-13 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.modal_analysis \
  --output /tmp/modal_80_NEW --segments 80 --modes 160 --solver scipy
# --segments 0 用于单塔；其他非零值用于每档导线分段。
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m unittest tests.test_tmq_modal -v
```

`modal_results/runs/*_checked`为正式结果，其他目录保存最初求解检查。输出目录禁止覆盖。汇总图、动画及说明由`publish_modal.py`从四个正式结果生成。远端固定、两根导线、既有弧垂与初张力等边界不变；尚无多塔、完整相束、地线、气动阻尼或实测标定。方法参见OpenSees官方[eigen/PythonSparse](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/eigen.html)及[modalProperties](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/modalProperties.html)。

## 等效风速探索

`wind_speed_exploration.py` 对单塔和一塔四档体系分别计算0°、30°、45°、90°。每例先完成独立重力平衡，冻结重力后用LoadControl增大同一个风荷载系数；20m/s参考场保持形状、密度和系数，按 **U=20√λ** 换算等效均匀静态风速。全塔内力、节点六自由度、支座反力和导线轴力逐接受步保存。

先从10推至140m/s；已完成的方向独立重算并扩展至240m/s或3%水平漂移计算保护线。各模型最早遇到数值停止的方向再将最大荷载增量从0.5减为0.25，并用位移控制独立追踪同方向路径。最小荷载增量0.0001，力不平衡收敛容差0.01，Newton/KrylovNewton/NewtonLineSearch回退；每例600秒求解预算。实际是否跑到目标、停止原因和末点均由记录报告，不将非收敛当作倒塌。

本批共13次主计算（8个初始工况、1次扩展、2次半步长复核、2次位移控制）。45°荷载控制末点为单塔111.299m/s、塔线108.887m/s，最大荷载步长减半后基本一致。位移控制成功跨过转折并记录下降段，采样峰值分别为 **110.977m/s、108.399m/s**。位移控制采用最大2.5mm、最小0.01mm的控制节点增量：单塔完成1%控制漂移，32根曾压屈、5根曾进入拉向强化；塔线在0.8580%控制漂移缩步至下限后停止，14根曾压屈、2根曾进入拉向强化。控制漂移为X方向位移/36.4m，不是45°沿风漂移。峰后曲线是真实接受步，不补齐未收敛区间。

```bash
CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.wind_speed_exploration \
  --output /tmp/wind_speed_NEW --workers 2
.venv/bin/python -m unittest tests.test_wind_speed_exploration tests.test_wind_speed_evidence -v
```

`full_tower`也可直接接收`--wind-speed-targets 10 20 30`，必须同时提供有量纲的`--wind-config`。不设置新参数时，保留旧位移控制协议。输出目录不允许覆盖；两种控制方式的失败尝试与已收敛状态分开记录，报告按真实覆盖范围绘图。

这是当前未标定气动力和TMQ角钢参数下的静力探索，**不是10m基本风速、脉动风倒塌风速或工程设计极限值**。3%保护线和图中用于识别明显回落的2%相对降幅均不是倒塌判据。已完成范围、首次压屈、采样路径峰值、数值停止是四种不同结果。方法参见OpenSees官方[LoadControl](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/integrator/LoadControl.html)及[DisplacementControl](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/integrator/DisplacementControl.html)。

## 多风角加载：单塔与单塔—导线体系

新接口 `wind_angle_deg` 明确定义 **0°为全局+X横线、90°为+Y顺线，度制，风流去向**。旧 `get_area(theta)` 仍保留弧度制、0=+Y的历史含义；不静默改变旧结果。新加载器同时施加X/Y分量，由同一时程系数驱动，保留其他自由度，不把斜风强制为单向位移。

实现步骤：

1. `util/processing/tower_directional_wind.py` 接受两个方向的逐杆挡风面积，按局部高度切分跨带杆件，按片段位置向原端点分配荷载，保存合力/合矩残差。可给定不同区域的系数，横担不抹平为整层均布。验证算例明确启用未标定的全杆件角钢边宽投影代理，不是IEC单面挡风面积，也不包含遮挡。
2. `conductor_directional_wind.py` 提供显式导线法向阻力和挂点等效两种模式；使用外径、实际线段长度及明确的Cd/密度，禁止同一物理档重复加载。水平直线符合cos²风角关系，弧垂线在沿线风下可以存在局部法向力，不强行归零。
3. `directional_wind.py` 负责六分量合力/合矩和OpenSees加载。Path从当前域时间开始，可显式设start_time；默认历史结束回零，hold_last=True保持末值。Linear要求域时间为0，调用方必须先冻结重力，工具不偷偷重置分析状态。
4. `directional_loading.py` 接入TMQ，塔线算例只有一座塔、两个已有V形绝缘子、四档300m导线及固定远端，不构建相邻塔。临时导线自重模式被移除，全体系统一按节点质量仅施加一次重力。初始弧垂8m、初力20kN继承既有示例，实际重力平衡值另由求解决定，未声称完成目标弧垂找形。
5. 各角度采用独立进程及重力初态，验证0/30/45/90°，每例控制自由度±0.01%后回零。输出沿风位移/剪力、X/Y响应、各支座六分量反力、导线轴力、塔杆材料状态与12分量内力。控制漂移不是沿风漂移，负荷载系数只代表固定模式机械反向。

```bash
CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.wind_angle_verification \
  --output /tmp/wind_angle_NEW --workers 2
.venv/bin/python -m unittest tests.test_directional_wind tests.test_tower_directional_wind \
  tests.test_conductor_directional_wind tests.test_directional_integration -v
```

也可将明确的配置JSON传给 `full_tower --wind-config FILE --control-dof 1/2`；风向与控制DOF正交时拒绝执行。不传配置仍使用原Y向等效归一化模式。每个输出目录禁止覆盖；目录内保留输入配置、代码/源数据哈希、逐杆荷载、力矩坐标基准与误差。组合合矩同时保存初始坐标及重力后坐标，不能跨坐标状态直接比较分项。

本批最终八个工况均完成3/3目标、各5个接受步，无杆件进入压屈或拉向强化；这是微幅验证，不是大幅滞回。最大自由节点力残差0.00244N、最大整体水平合力残差0.000167N。90项力学/材料/集成测试、36项网页回归和5项浏览器检查通过；旧Y向弹性小循环复跑与原始history.csv逐字节一致。[完整验收记录](directional_results_v2/verification.json)。初轮结果保留在directional_results，最终增加完整溯源和支座记录的版本为directional_results_v2，网页仅发布后者。

**适用边界：当前验证使用20m/s均匀参考场、Cx=Cy=1、角度修正0.2、导线Cd=1等显式试算选择，不是已确定的工程参数。微幅循环不用于比较容量、确定最不利风角或判定倒塌。** 不含束导线遮挡、气动阻尼、绝缘子风阻、地线和完整相数。导线阻力方向冻结于重力平衡后几何。TMQ未标定角钢、轴弯不耦合、无损伤删除等原有边界不变。

公式参考：[Cai等2021，式27–31](https://vibcon.tongji.edu.cn/Upload/file/20220216/202202162058006832578.pdf)；角钢塔斜风系数的适用限制：[Tang等2022](https://scholarsmine.mst.edu/civarc_enveng_facwork/2277/)。本实现没有把未取得正文的规范条文当作已核验的系数来源。

## 参照罗贤超的薄弱位置分析

对应论文式2.2（PDF26／印刷19）、表2.3（PDF37／印刷30）和图2.18（PDF38／印刷31），分别筛查**首压屈位置**与**旋转修正节间位移角最大位置**。不把二者强制合并成危险评分，不把409个准静力步当作409条独立风记录，也不迁移论文的2%倒塌阈值。

新跑的 `weakness_runs/bounded_with_nodes_01` 保存621个节点的全部六自由度、410个状态（含重力平衡step0），与旧有界协议逐步控制位移、剪力和压屈数量完全一致。旧结果不修改。以12个塔身四角截面定义11个节间（0–36.4m）；横担节点不混入截面均值，所有1528根杆件仍纳入材料位置筛查。

实算结论：33m塔身水平杆825/828在step104首次记录进入软化，917/920在step159进入；同高横担远端877/878在部分扩展工况中压力比约0.999920，但未记录进入软化。平均节点转角法最大ISDR-Y在9–13.2m，约0.103040%；竖向位移平面拟合法最大在24–27m，约0.127786%。**转角提取方法会改变节间排序，因此本次不认定唯一倒塌控制节间。**

```bash
CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.full_tower \
  --record-nodes --output /tmp/tmq_nodes_NEW \
  --targets 0.0001 -0.0001 0 0.001 -0.001 0 0.003 -0.003 0 0.004 -0.004 0 0.005 -0.005 0
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.weakness_analysis \
  --run /tmp/tmq_nodes_NEW \
  --extended initial_imperfection_material/tian_ma_qu/tower_results/tmq_cyclic_02 \
  --baseline initial_imperfection_material/tian_ma_qu/tower_results/tmq_bounded_03 \
  --output /tmp/tmq_weakness_NEW
.venv/bin/python -m unittest tests.test_tmq_weakness -v
```

新增程序不启用损伤/断裂/删除，不改变本构。节点转角均值与几何拟合均为本项目公开的实现，论文未给出其转角提取细节；报告保留原始位移角、两种修正量、正负极值、绝对值包络、拟合残差和首次事件区间。资料目录 `weakness_results` 内含HTML报告、SVG/PNG/PDF位置图、分级ISDR图、全杆件统计CSV、逐步节间CSV、截面节点表和来源哈希。

验证记录：[weakness_results/verification.json](weakness_results/verification.json)。50项力学/材料/全塔相关测试和32项网页测试通过；Chromium最终通过13项检查。两个子agent分别独立复核论文方法及全量数据，确认新旧全部杆件状态一致；转角敏感性导致不同的最大变形节间，已明确保留，不把某一种排序包装成已验证的唯一薄弱区。

## 独立全塔入口

`model/tower_model_with_tian_ma_qu.py` 读取 Z30103A6 的 1,528 根物理杆件，保留六自由度空间梁网络。每根杆件使用一个 Corotational `dispBeamColumn`：轴向为 TMQ（应力乘以面积后进入 Aggregator P 通道），My/Mz/T 为弹性。**轴弯不耦合、梁刚度未计 I23、不再叠加几何初弯曲**；不是原四段纤维模型的已验证替代。

E、fy、A、L 来自 S2K，ρ 使用塔模型既有强化比 0.03；φ 用实际杆件弱轴、K=1、e0/L=1/1000 的 Perry 首次纤维屈服估计，不能称为标定后的极限承载力。其余循环系数暂借用 P102 row A，γ=0.5、ζ=0.1 为假设。逐杆参数及来源保存在 `model_data/tmq_member_parameters.csv`。

```bash
# 完整有界往复：依次 ±0.01%、±0.1%、±0.3%、±0.4%、±0.5%，各级回零。
CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.full_tower \
  --output /tmp/tmq_tower_bounded_NEW \
  --targets 0.0001 -0.0001 0 0.001 -0.001 0 0.003 -0.003 0 0.004 -0.004 0 0.005 -0.005 0

# 较大幅值探索：默认协议含 ±0.6%、±1%；不能保证完成，部分结果返回退出码 2。
CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.full_tower \
  --output /tmp/tmq_tower_extended_NEW

# 相同拓扑的弹性对照，仅用于初始接口/刚度检查，不是四段参考。
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.full_tower \
  --output /tmp/tmq_tower_elastic_NEW --axial-mode elastic --targets 0.0001 -0.0001 0

TMQ_TEST_NATIVE=1 CXX=/usr/bin/g++-13 .venv/bin/python -m unittest tests.test_tmq_full_tower -v
```

控制节点 350、Y 向自由度 2、控制高度 36.4 m；漂移以重力平衡后位置为原点。输出目录禁止覆盖：`history.csv` 保存所有接受步，`attempts.jsonl` 保存所有求解尝试，`equilibrium.jsonl` 保存独立节点平衡核查，`member_states.csv.gz` 保存全部杆件材料分支，`internal_forces.sqlite` 保存全塔 12 分量梁端内力。每根梁的 3 个轴向材料副本互相独立，记录时检查三个积分点的轴向状态一致。拉向屈服状态按实际进入 `tension_hardening` 分支记录，而非把等效应变当成纤维塑性应变。

```python
from util.processing.internal_force_recorder import TowerInternalForceHistory
db = TowerInternalForceHistory("initial_imperfection_material/tian_ma_qu/tower_results/tmq_bounded_03/internal_forces.sqlite")
# time 在此为拟静力接受步号，不是秒；任意已保存步区间均可读取全塔内力。
rows = list(db.iter_history(start_time=100, end_time=110, element_tags=[825, 828]))
```

9999 网页的 Tian–Ma–Qu 栏上方新增全塔图和报告入口，旧版内力浏览器仍展示旧模型，不混用。原 `results/summary.json` 中“未改动全塔”的字段是此前单杆批次的历史记录，不回写旧证据。单进程桥接原型不支持并行 OpenSees/MPI 或保存恢复；不同算例应运行在独立进程中。

本次实际结果：有界协议完成 15/15 个目标、409 步，4 根杆件（825、828、917、920）进入过压屈软化，未进入拉向强化；较大幅值协议完成 10/15 个目标、264 步，在 -0.571399% 漂移、-929.254 kN 剪力处停止（减至最小步长仍未收敛）。首次记录压屈为第 104 步，825/828 杆，漂移 -0.221978%。数值终点不等于倒塌点。有界协议最大剪力幅值 816.018 kN 是本次加载范围内的记录值，不称极限承载力。

验证：36 项材料/全塔相关测试（启用真实原生桥）及 30 项网页回归测试通过；Chromium 完成 12 项检查，包括新全塔图、回放、旧版内力界面及手机布局。见 [验证记录](tower_results/verification.json)。初始刚度相对弹性对照误差约 2.67e-13，前三阶频率一致；这些只证明接入和初始响应一致，不证明管试件参数适用于本塔角钢。

## 重现

在仓库根目录运行，所有单位为 N、m、Pa；拉伸为正。

```bash
# 纯 Python 材料：无需编译器，也不会改动 OpenSees domain。
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.run_experiment \
  --output /tmp/tmq_python_new_run

# 真实 OpenSees 单 truss 往复：当前工作环境已验证。
CXX=/usr/bin/g++-13 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.run_experiment \
  --with-opensees --output /tmp/tmq_opensees_new_run

# 单元、图表、协议及真实 OpenSees 隔离进程测试。
TMQ_TEST_NATIVE=1 CXX=/usr/bin/g++-13 .venv/bin/python -m unittest \
  tests.test_tian_ma_qu_material tests.test_tian_ma_qu_experiment -v
```

输出目录非空时默认拒绝覆盖。要重算本模块已有成果，需显式 `--overwrite`；请勿将输出指向旧塔模型结果目录。`--steps-per-leg 100` 是当前展示值；程序同时运行 200 步/段的材料细化核查。未设置 `TMQ_TEST_NATIVE=1` 时跳过两项原生适配测试，其余正常执行。

原生桥限 **Linux + CPython + OpenSees 引擎 3.8.0**。本机 `openseespy` 包版本与实际引擎版本不同，程序检查的是 `ops.version()`。首次构建从 OpenSees 官方仓库下载固定提交的头文件及版权声明，使用本机 C++17 编译器；缓存位于已忽略的 `_native_cache/`，不修改安装包。当前默认 `g++` 是旧版本，故示例显式指定 `g++-13`。需要联网下载头文件；已有哈希匹配的缓存可离线复用。

## 使用接口

```python
from initial_imperfection_material.tian_ma_qu.cases import literature_cases
from initial_imperfection_material.tian_ma_qu import TianMaQuPrototype

case = literature_cases()[0]
material = TianMaQuPrototype(case.parameters)
material.set_trial_strain(-0.003)
stress = material.get_stress()
tangent = material.get_tangent()
material.commit_state()       # 仅收敛状态提交；失败时 revert_to_last_commit()
```

在新的、隔离的 OpenSees domain 内使用 `opensees_adapter.register_material(tag, parameters)` 后，可将该 tag 交给 `truss`。它不是安装包内置的 `ops.uniaxialMaterial("TianMaQu", ...)` 命令。用完调用 `ops.wipe()`，不要在正在运行的全塔进程里调用本实验入口。

## 适用边界

构件等效 `σ=N/A, ε=Δ/L`，不等于钢材纤维本构。E、ρ、γ、ζ 及不完整反转的回溯规则均有明确假设；PP/PF 影响来自文献试件参数，不是单 truss 再现了其端部弯曲。尚不支持损伤断裂、单元删除、MPI、数据库保存恢复、敏感性分析或可直接使用的 OpenSees 能量响应；后者返回 NaN，而不是伪造零耗能。CSV 的外功为 `∫N dΔ`，不自动等于耗散能。

不要把独立探索性全塔入口直接用于已验证的全塔抗倒塌/易损性结果，也不要叠加同一杆件的四分段初弯曲。后续仍需补足原试验同协议验证、角钢专属标定和轴弯耦合影响评估。
