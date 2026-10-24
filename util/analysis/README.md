# 通用分析模块与提前建设清单

本轮将五类已有重复逻辑或后续批量分析必需的功能做成公共模块，使用标准库；解析示例使用项目已有的 OpenSeesPy、Matplotlib。导入 `util.analysis` 不会创建或清除 OpenSees 模型。

## 1. 已完成的模块

| 模块 | 解决的问题 | 已接入位置 |
|---|---|---|
| `protocols.py` | 生成多幅值、重复循环、正负换向及最终回零协议；生成有符号且不越过目标的步长 | `full_tower_cyclic.default_protocol()` |
| `stepping.py` | 多算法回退、失败步减半、最小步长、完整目标区间推进、成功子步回调和统计 | 全塔往复、批量风振 |
| `time_series.py` | 核对全部时间点、均匀步长、各层荷载长度、非有限值、重复节点及可选节点存在性 | 风振入口、独立命令行检查 |
| `response_metrics.py`（在 `util/postprocess` 下） | 共同覆盖区间、禁止外推、与采样密度无关的 RMSE、覆盖率、保留换向顺序的路径外功 | 单杆比较、全塔路径外功 |
| `run_manifest.py` | 参数、输入 SHA256、随机种子、Git/运行环境、完成状态、异常和输出文件索引 | 全塔往复、批量风振；易损性提取识别状态 |

## 2. 加载协议

```python
from util.analysis import cyclic_targets, bounded_increments

targets = cyclic_targets([0.001, 0.003, 0.006], repeats=2)
# 每级 (+a, -a) 重复两次，最后追加 0；0.001 表示 0.1% 漂移。
displacements = [ratio * 36.4 for ratio in targets]  # m
increments = list(bounded_increments(0.1, -0.12, 0.05))
```

幅值不允许为空、非正、NaN 或 Inf；末步会使用剩余量，防止越过目标。

## 3. 自适应求解

调用前先建立模型、荷载、约束、方程求解器及分析类型。位移控制示例：

```python
from util.analysis import AdaptiveStepper

solver = AdaptiveStepper(
    ops,
    progress=lambda: ops.nodeDisp(control_node, 2),
    configure_increment=lambda du: ops.integrator(
        "DisplacementControl", control_node, 2, du
    ),
    minimum_increment=0.0003125,
    convergence_test=("NormDispIncr", 1e-6, 60, 0),
)
result = solver.advance_to(target_displacement, maximum_increment=0.005)
if not result.converged:
    print("未完成目标，实际到达", result.achieved)
print(solver.diagnostics())
```

瞬态分析使用 `transient=True, progress=ops.getTime`，调用 `advance_to(target_time, maximum_increment=dt)`。每个成功子步都会调用可选的 `on_step`，因此可以逐子步记录内力、位移角与峰值。默认依次尝试 Newton、KrylovNewton、NewtonLineSearch，再减半步长；所有尝试使用同一收敛验收条件，完成后恢复首选算法。

`step(increment)` 只接受一次成功增量，可能比请求小；`advance_to` 会继续覆盖剩余区间。终点剩余量小于最小步长时仍会尝试该剩余量。失败步必须保持提交状态不变；返回码与实际位移/时间不符时立即抛出异常，防止重试导致重复推进。

缩步能够处理部分数值困难，但不能据此认定结构没有失效；求解失败也不能自动作为倒塌事件。当前材料全塔在 1% 目标的已知边界仍需单独验证。

## 4. 风荷载预检查

检查单个样本或整个根目录，无需建立 OpenSees 模型：

```bash
.venv/bin/python -m util.analysis check-wind \
  fluctuate_wind_simulate/static/wind_press_generate \
  --node-config fluctuate_wind_simulate/.config/node_to_add_wind_press.json \
  --output /tmp/wind_preflight.json
```

约定 `t.csv` 和 `floorN_wind_press.csv` 均为无表头单列数值；支持 UTF-8 BOM 和空白行。时间从 0 开始，严格递增且等间隔；荷载值数与时间点数完全一致。存在无效样本时报告保留错误原因，退出码为 1。

节点可在相邻楼层间共享，同一楼层内不允许重复。`available_nodes` 可选参数用于检查实际模型节点。预检查只验证数据格式、长度与映射，不判断风谱、相干函数或荷载物理取值是否合理。

## 5. 曲线比较与路径外功

```python
from util.postprocess.response_metrics import ResponseCurve, compare_curves, path_work

reference = ResponseCurve.from_pairs([(0, 0), (1, 2), (2, 4)])
candidate = ResponseCurve.from_pairs([(0.5, 1), (1.5, 3)])
metrics = compare_curves(reference, candidate)
# 实际比较 [0.5, 1.5]，参考覆盖率 50%，候选覆盖率 100%。
work = path_work([(0, 0), (1, 2), (0, 0)], require_closed=True)  # 0
```

`ResponseCurve` 要求横坐标严格递增。以两曲线共同范围内的全部折点构造分段线性误差，准确积分误差平方，再除以区间长度得到 RMSE，避免密集采样区人为占据更大权重。归一化采用共同区间参考响应最大绝对值；参考尺度为 0 时返回 `None`。

单杆原有的采样点 NRMSE 字段保留，新增 `domain_weighted_nrmse_percent` 及双方覆盖率。两种 NRMSE 的权重定义不同，比较研究结果时应写清使用哪个字段。

往复曲线使用 `path_work` 按原始顺序计算 `∫F du`，不按位移排序。开放路径的积分是外功；闭合力—位移回线的面积才能用于相应的滞回耗能评价。`require_closed=True` 同时检查首末位移和力。

## 6. 运行记录与结果状态

```python
from pathlib import Path
from util.analysis import RunManifest

with RunManifest(
    Path("case_output"),
    parameters={"wind_speed_mps": 30, "model": "segmented"},
    input_files=["Source/Z30103A6.s2k"],
    seed=30103,
    expected_steps=100,
) as run:
    # 此处执行任务；定期更新真实已完成步数。
    run.update(completed_steps=100, peak_displacement_m=0.012)
    # 也可登记已有输出：run.add_artifact("history", "case_output/history.csv")
```

生成 `run_manifest.json`，状态含义为：

| 状态 | 含义 |
|---|---|
| `running` | 正在计算，完成步数是最近一次保存的进度 |
| `completed` | 正常结束且已覆盖指定目标步数 |
| `nonconverged` | 明确报告未收敛，或实际完成步数少于预期 |
| `failed` | 输入、建模、求解或导出发生异常，记录异常类型及内容 |
| `interrupted` | 收到 Python 的 KeyboardInterrupt/SystemExit |

元数据以临时文件原子替换，避免写到一半出现无效 JSON。同一结果目录使用 `.run.lock` 防止同时写入。若进程被强制杀死或机器断电，可能留下 `running` 和锁文件；应先确认对应进程已经结束，再人工处理该锁，工具不会自动续算或清除锁。

种子仅记录调用者提供的值，不改变全局随机状态。Git 记录提交及工作区是否有改动，关键输入另存 SHA256；这不是完整代码快照。清单也不保存 OpenSees 的材料内部状态，不能作为非线性分析断点恢复文件。

批量查看：

```bash
.venv/bin/python -m util.analysis list-runs \
  fluctuate_wind_simulate/static/.opensees.output
```

风振清单的 `completed_steps` 对应原始时间网格；`metrics.solver.accepted_steps` 是缩步后的实际成功步数。`drift.csv` 保留历史格式，行号 `step` 从 0 开始，对应内力库中的 `step+1`。实际物理时间以 SQLite 的 `time` 列及 OpenSees 自带记录器的时间列为准。全塔准静力库的 `time` 是记录步序号，不是物理秒。

易损性提取现在默认 `formal`：必须有完整运行、独立验证、已核对适用域、绑定的物理极限状态判据及对应证据。
无清单历史数据为 `legacy_unknown`，不再默认进入正式统计；旧数据探索须显式选择 `exploratory_legacy`，输出始终标为非正式。
所有样本（包括未完成、越界和未知）保留在准入审计表，不能静默删除或把数值失败自动判为倒塌。
具体入口、兼容变化和70条历史响应的审核见
[样本准入说明](../../docs/ai_execution_plan/execution_20261022/SAMPLE_ADMISSION.md)。

## 7. 测试与可复现实例

最初模块测试见 [`TEST_REPORT.md`](TEST_REPORT.md)；后续整合批次的实际测试、步骤和结果见
[执行记录](../../docs/ai_execution_plan/execution_20261022/execution_log.md)，旧测试数量不代表最新回归结果。

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m util.analysis.demo
```

示例默认输出至 `util/analysis/.output/demo/`，包含静力往复弹簧、恒力作用下无阻尼振子的 CSV、解析对比图、误差汇总和任务清单。该示例只操作独立小模型。

测试包括：协议换向与尾步、非均匀时间/缺失荷载/NaN 拒绝、求解回退与最小步长、部分进度保存、闭合回线外功、不同采样密度曲线比较、清单锁与异常状态；另有真实 OpenSees 静力/瞬态解析核对、风振入口逐子步内力记录，以及失败样本被易损性提取排除的集成检查。

## 8. 后续已补齐的通用模块

| 模块 | 约束与用途 | 说明 |
|---|---|---|
| `baseline_snapshot.py` | 可恢复源码归档、旧证据哈希；WAL严格检查，SHM读锁另列 | [执行基线](../../docs/ai_execution_plan/execution_20261022/execution_log.md) |
| `result_quality.py` | 执行/验证/适用域/物理状态独立；只观察已提交状态 | [质量契约](../../docs/ai_execution_plan/execution_20261022/QUALITY.md) |
| `sample_admission.py` | 正式/探索样本流转、分档缺失及失败计数 | [准入说明](../../docs/ai_execution_plan/execution_20261022/SAMPLE_ADMISSION.md) |
| `equilibrium_checks.py` | 完整荷载账本的静力残差、显式惯性/阻尼项的动力残差 | [残差与求解](../../docs/ai_execution_plan/execution_20261022/SOLVER_RECORDS.md) |
| `util/postprocess/energy.py` | 所有加载自由度的共轭外功；不自动称耗能 | [口径说明](../../docs/ai_execution_plan/execution_20261022/SOLVER_RECORDS.md) |
| `util/processing/member_state_recorder.py` | 原杆到分段、两端6DOF、纤维极值和完整重力/循环历程 | [记录器说明](../../docs/ai_execution_plan/execution_20261022/RECORDING.md) |
| `initial_imperfection_material/compare_runs.py` | 按阶段/方向/进度比较；禁止全局位移排序与外推 | [比较方法](../../docs/ai_execution_plan/execution_20261022/SOLVER_RECORDS.md) |

`AdaptiveStepper`另增迭代数/范数/算法参数attempt日志、停止预算及显式 `legacy/last_success/gradual` 恢复策略。
默认仍为legacy；改变策略的全塔路径敏感性必须另外验证，不能只用单弹簧测试宣称全塔通过。

## 9. 仍待物理验证的模块

| 候选模块 | 已有基础 | 继续实施前需要明确 |
|---|---|---|
| 建模预检查 | 节点、单元、质量和截面映射 | 如何区分允许的重合节点/释放与错误连接 |
| 模态与阻尼校核 | 已有模态图及质量模型 | 目标振型、阻尼比及采用初始/当前/提交刚度 |
| 统一响应统计与损伤状态 | 层间位移角、内力库及峰值提取 | 钢材纤维应变与构件等效应变不能共用阈值 |
| 参数工况与批量调度 | 当前串并行风振入口 | 统一风速、风向、缺陷幅值、种子和结果命名规则 |
| IDA 与易损性评价 | 现有曲线拟合和样本提取 | 物理极限状态、失效与数值失败的区分、删失样本处理 |

以上几项适合作为下一阶段基础设施，但其中的物理判据应结合课题目标明确后再接入正式计算。
