# 求解、协议比较、残差与外功：执行步骤和结果

批次：`execution_20261022`；执行角色：第 4 个执行 agent，`execution_solver_records`。
任务范围：T04 的通用协议比较、T05 的平衡/外功工具与小模型验收、T15 的 stepper 基础能力。
本角色没有修改全塔入口、单杆实验入口或记录器，也没有启动全塔计算。全塔采集和接入由主 agent 负责。

## 1. 本执行线的最终状态

| 子项 | 实际完成 | 仍需下游证据 |
|---|---|---|
| T04 协议比较工具 | 阶段/方向/进度对齐、跳点排除、早停覆盖、零共同区间、旧诊断 CSV 显式适配、CLI | 全塔/局部状态综合报告、事件识别器、矩阵谱能力探测不属于本角色代码 |
| T05 平衡与外功 | 静力真实自由 DOF 残差、显式动态惯性/阻尼账、真实共轭分布加载外功、小模型验证 | 全塔静力接入结果由主 agent 出具；不能据此直接宣称全塔动力通过 |
| T15 stepper | attempts 的迭代/范数/参数、停止上限、可选步长恢复、异常记录、提交后回调异常停止 | 新代码对全塔 legacy/fine 的路径复现、恢复策略的全塔路径敏感性尚未由本角色执行 |

新增 **34 项测试实际通过 34/34**，相关既有回归 **29/29**。这 63 项定向测试不等于整个仓库最终测试总数；全仓集成由主 agent 汇总。
数值工具通过不表示材料循环物理验收、G3 或 G4 已通过。

## 2. 实际执行步骤

1. 阅读 `PLAN.md` 第 0～5 节和 T04/T05/T15，核对现有 stepper、单调曲线比较、公共模块测试和新全塔记录字段。
2. 与主 agent 明确文件独占：本角色只修改本报告第 3 节列出的代码/测试；保留主 agent 的全塔和记录器所有权。
3. 先建立协议比较数据契约，保留原输入次序，按 `stage_id + direction` 分组；阶段内只允许归一化进度递增。
4. 用分段线性误差的解析积分计算 RMSE，避免自适应采样密度改变评分；只比较实际共同区间。
5. 加入跳点与空覆盖处理：重复进度保留前/后两侧值；显式 `jump_before` 或超出给定采样间隔的区间不插值；无共同阶段返回可解释的空结果。
6. 构建静力残差工具：逐个单元读取全局 `eleForce`，按端节点 DOF 汇总，并从完整当前外载台账中相减；约束 DOF 不作为自由残差。
7. 用真实 OpenSees 弹簧链、具有平动/转动 DOF 的梁、负刚度串联弹簧及刚体平移验证残差。故意篡改外载台账，证明“analyze 已成功、位移增量很小”仍不能掩盖不平衡。
8. 构建全部指定加载 DOF 的 `sum integral(F_i du_i)` 外功工具，分别验证分布荷载、重力、力矩/转角、移动支座功和闭合弹性路径。
9. 向主 agent 提供静力 API 与已通过小模型证据，供新的全塔采集使用。每个已提交状态若检查失败，保存并终止；没有自动伪回滚。
10. 保持 stepper 默认 `legacy` 行为，新增 attempts 的实际 `testIter/testNorms`、算法参数和有效测试设置；加入局部/总 attempt、成功步数和时间上限。
11. 新增 `last_success`、`gradual` 两种显式可选恢复策略，用受控求解器测试减少重复大步失败；未据此改变全塔默认策略。
12. 处理异常边界：analyze 异常默认终止；只有显式、经过应用方验证的恢复回调才可重试；记录器在提交之后抛异常时正确保留提交计数并终止。
13. 主 agent 追加动态验收要求后，新增显式 `P - I - D - R_static` 接口；缺动态账、未知质量模型或缺来源一律拒绝。
14. 用真实恒力振子分别验证无阻尼、已知黏性系数 `C=4 N s/m` 两种 Newmark 分析，逐成功步检查惯性/阻尼平衡，并核对解析位移。
15. 只读旧 baseline/fine_sparse 历史，输出新的协议比较和图；不重算、不覆盖历史，不把共同区间外的结果外推进误差。
16. 整理机器可读验证结果、输入指纹、测试命令、已完成范围和未完成验收，供主 agent 登记总任务状态。

开发中修正过两处测试夹具问题，保留其说明：负刚度弹簧测试最初继续推进到严格零切线平台后发生矩阵奇异，最终验证止于 49 mm，已包含真实峰后软化；这不是全塔材料参数修复。另一个测试最初在 step 返回后查询引擎迭代计数，但恢复基线 test 会清零引擎计数；最终改为在 attempt 回调内同时采样真实引擎值并核对，运行代码没有因此改变。

## 3. 文件与实际接口

| 文件 | 功能 |
|---|---|
| `initial_imperfection_material/compare_runs.py` | `compare_protocol_histories`、旧诊断适配器、只写新输出的 CLI |
| `util/analysis/equilibrium_checks.py` | `static_equilibrium`、`dynamic_equilibrium`、`require_equilibrium`、`CommittedStateRejected` |
| `util/postprocess/energy.py` | `conjugate_external_work`，真实加载 DOF 的路径有符号外功 |
| `util/analysis/stepping.py` | 扩展的 `AdaptiveStepper`，保留原构造接口与默认恢复策略 |
| `tests/test_protocol_comparison.py` | 10 项协议比较与旧数据适配测试 |
| `tests/test_equilibrium_checks.py` | 15 项真实小模型、动态与外功测试 |
| `tests/test_stepper_diagnostics.py` | 9 项诊断、异常、停止上限与策略测试 |

### 3.1 往复比较

```python
from initial_imperfection_material.compare_runs import compare_protocol_histories

result = compare_protocol_histories(
    reference_rows, candidate_rows,
    value_fields=("base_shear", "member_axial_force"),
    protocol_stages=(("stage_1", 1), ("stage_2", -1)),
)
```

每行包含 `stage_id, direction, stage_progress` 和所比较数值字段；`accepted=false`、`committed=false` 或 `state=trial` 行被排除。
阶段起点应显式存在，`protocol_stages` 应来自冻结的请求协议；否则覆盖率只按观测到的阶段计算，并在 `coverage_basis` 明确声明。
阶段名需在整个协议中唯一；同一阶段/方向再次非连续出现会拒绝，避免重复循环被合并。

`jump_before=true` 表示前一记录到本记录的整个区间不允许插值；相同进度的两个点保存跳跃前/后响应。
输出含两模型各自跳跃位置、前/后值和幅值。未标记跳跃不会被工具凭空识别；结果始终给出该限制。
无正长度共同区间时，`status=no_common_coverage`、RMSE 为 `null`；零幅阶段可另给 `point_only` 的同进度点误差。
不会对位移全局排序，也不会把不同加载支路的同位移点合并。

### 3.2 静力残差

```python
from util.analysis.equilibrium_checks import static_equilibrium, require_equilibrium

report = static_equilibrium(
    ops, {(node_tag, dof): current_load},
    constrained_dofs=fixed_node_dofs,
    rotational_dofs=rotation_node_dofs,
    force_scale=reference_force_N, moment_scale=reference_moment_Nm,
)
save_report(report)
require_equilibrium(report)
```

计算的是自由 DOF 上 `P - sum(element global resisting forces)`；平动以 N、转动以 N m 分开归一化。
调用者必须提供所有当前荷载模式及当前系数形成的完整节点外载台账和独立 SP 约束集合。
单元分布载要与 `eleForce` 的固定端力约定相容，不能重复加入等效节点载。
一般 MP 约束需要专门力转换适配器，当前可检测时显式拒绝；单元返回力向量不满足节点 DOF 布局时也拒绝，不能悄悄截断。

`require_equilibrium` 抛出的 `CommittedStateRejected` 携带原报告。成功 analyze 后一般已经提交，异常不得直接当作可重试的未提交失败；只能停止或执行另行验证的重建/重放。

### 3.3 动力残差

```python
from util.analysis.equilibrium_checks import dynamic_equilibrium

report = dynamic_equilibrium(
    ops, applied_loads,
    inertial_nodal_forces=known_Ma,
    damping_nodal_forces=known_Cv,
    mass_model="nodal_diagonal_only",
    force_provenance={"inertia": "known nodal masses times committed acceleration",
                      "damping": "known C times committed velocity"},
    constrained_dofs=fixed_node_dofs,
)
```

两份动态台账必须覆盖全部节点 DOF，包括质量为零或固定自由度上的显式零值。
`nodal_diagonal_only` 表示已确认没有未计入的单元质量；若已有独立完整的已知质量/阻尼组装力，可显式用 `externally_assembled_nodal_forces`。
工具不会从 `nodeUnbalance` 或默认 Rayleigh 参数猜测惯性/阻尼，也不能自行验证调用者的完整质量模型声明。
未知单元一致质量、未知阻尼、缺台账或缺来源会拒绝，不输出假“通过”。

### 3.4 真实外功

```python
from util.postprocess.energy import conjugate_external_work

work = conjugate_external_work(
    [{"displacements": {"node2y": u2, "node3y": u3},
      "external_forces": {"node2y": f2, "node3y": f3}}, ...],
    all_applied_dofs_included=True,
    constraint_work_included=False,
)
```

所有提交点必须有同一组力/位移共轭通道；缺通道、非有限数或失败状态会拒绝。
重力和移动约束需由实际建模方加入对应通道；`all_applied_dofs_included` 是调用方完整性声明，不能从数据中自动推断。
结果叫有符号外功。端点力/位移闭合只给闭合标记，不自动宣称材料内部状态闭合或滞回耗能。

## 4. 量化结果

### 4.1 小模型

| 实验 | 实际结果 |
|---|---|
| 两弹簧线性串联，节点 2/3 分别 10/20 N | `u2=0.03 m, u3=0.05 m`；最大自由残差 `3.553e-15 N` |
| 同模型读取 nodeUnbalance | 节点 3 为 `20 N`，但真实残差约零，直接证明该量不能冒充组装残差 |
| 外载台账故意把 20 N 改成 19 N | 检出 `1 N` 残差；原提交状态保持，未自动重试 |
| 具有 N/V/M 的真实二维梁 | 平动力/转动力矩残差均为 0；N 与 N m 分组输出 |
| 两弹簧串联，第二根峰后负刚度 | 49/49 步；峰值 20 N、终点约 11 N；终点自由残差 `1.776e-15 N` |
| 两端相同规定平移 10 m 的真实弹性弹簧链 | 自由中点同移 10 m、内力约零、残差通过 |
| 分布节点加载的真实外功 | `0.65 J`；`0.5 Vbase utop=0.75 J`，二者不同 |
| 力矩/转角 + 重力 + 移动支座功 | `0.2 + 2.0 + 0.6 = 2.8 J` |
| 闭合弹性路径 | 外功 0，仍不伪造内部状态闭合证明 |

### 4.2 动力小模型

`m=2 kg, k=200 N/m, P=1 N, dt=0.001 s, t_end=0.1 s`，平均加速度 Newmark。

| 阻尼 C | 成功步 | 最大真实动力残差 N | 数值末位移 m | 解析末位移 m | 绝对误差 m |
|---|---:|---:|---:|---:|---:|
| 0 N s/m | 100/100 | 5.551e-17 | 0.002298453410 | 0.002298488471 | 3.506e-8 |
| 4 N s/m | 100/100 | 5.551e-17 | 0.002155105294 | 0.002155140545 | 3.525e-8 |

故意把惯性设为零时，成功 analyze 后仍检出大于 0.9 N 的残差。缺账与未知质量模型的拒绝路径也有测试。
这些结果验证接口、小模型和读操作不改变状态；尚未证明实际塔动力入口的质量、阻尼台账已经完整接入。

### 4.3 可选步长恢复策略

以下只是在可成功增量上限 0.025 的受控假求解器上，从 0 推进到 0.2，最大请求步为 0.1：

| 策略 | 成功步 | 失败 attempts | 总 attempts |
|---|---:|---:|---:|
| `legacy` | 9 | 45 | 54 |
| `last_success` | 8 | 6 | 14 |
| `gradual` | 11 | 12 | 23 |

它只说明恢复控制流可减少重复大步失败，不能当作全塔加速比例或路径一致性证据。
`timeout_seconds` 在 attempt 边界检查，不能强行打断一次仍在引擎内部执行的 analyze。

### 4.4 只读历史协议比较

显式采用 9 个目标位移：`[.0364,-.0364,.1092,-.1092,.2184,-.2184,.364,-.364,0] m`。

- baseline 对 fine_sparse：前 6 阶段共同覆盖 100%，第 7 阶段共同进度 **17.277644%**，第 8/9 阶段无 baseline 数据。
- 对完整 9 阶段协议，共同进度覆盖率为 **68.586405%**；共同采样区间基底剪力 RMSE 为 **0 N**。
- fine_sparse 自比：9/9 阶段、共同覆盖率 100%、RMSE 为 0。
- 旧 CSV 没有关键杆的局部跳跃事件标志，所以这部分仅为整体采样曲线比较，不能解释为跨局部跳跃的物理验证。工具的显式跳跃排除能力由独立测试覆盖。
- 旧 baseline 后续无数据，没有参与误差计算，更没有用最后一个反力值外推。

## 5. 实际运行命令

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_protocol_comparison.py' -v
# 10 tests, OK

.venv/bin/python -m unittest discover -s tests -p 'test_equilibrium_checks.py' -v
# 15 tests, OK

.venv/bin/python -m unittest discover -s tests -p 'test_stepper_diagnostics.py' -v
# 9 tests, OK

.venv/bin/python -m unittest discover -s tests -p 'test_analysis_common.py' -v
# 24 tests, OK

.venv/bin/python -m unittest discover -s tests -p 'test_analysis_workflows.py' -v
# 5 tests, OK

.venv/bin/python -m initial_imperfection_material.compare_runs \
  --reference initial_imperfection_material/results/convergence_diagnosis/baseline/history.csv \
  --candidate initial_imperfection_material/results/convergence_diagnosis/fine_sparse/history.csv \
  --legacy-diagnostic-targets .0364 -.0364 .1092 -.1092 .2184 -.2184 .364 -.364 0 \
  --output initial_imperfection_material/results/followup/execution_20261022/solver/protocol_comparison_v1/baseline_vs_fine_sparse.json

.venv/bin/python -m initial_imperfection_material.compare_runs \
  --reference initial_imperfection_material/results/convergence_diagnosis/fine_sparse/history.csv \
  --candidate initial_imperfection_material/results/convergence_diagnosis/fine_sparse/history.csv \
  --legacy-diagnostic-targets .0364 -.0364 .1092 -.1092 .2184 -.2184 .364 -.364 0 \
  --output initial_imperfection_material/results/followup/execution_20261022/solver/protocol_comparison_v1/fine_sparse_self.json
```

比较输出已存在，CLI 会拒绝覆盖；复算应换 `protocol_comparison_v2` 等新目录。
测试可重新运行。静力/动力量化核对来自同一批测试夹具的额外实际执行，机器可读数值保存在下面的验证 JSON。

## 6. 产物与后续衔接

- [数值验证 JSON、63 项定向检查计数和旧输入 SHA256](../../../initial_imperfection_material/results/followup/execution_20261022/solver/verification_v1.json)
- [baseline 对 fine_sparse 的完整协议结果](../../../initial_imperfection_material/results/followup/execution_20261022/solver/protocol_comparison_v1/baseline_vs_fine_sparse.json)
- [fine_sparse 自比结果](../../../initial_imperfection_material/results/followup/execution_20261022/solver/protocol_comparison_v1/fine_sparse_self.json)
- [历史整体曲线与共同覆盖图](../../../initial_imperfection_material/results/followup/execution_20261022/solver/protocol_comparison_v1/historical_protocol_comparison.png)
- [残差/外功 15 项测试原始输出](../../../initial_imperfection_material/results/followup/execution_20261022/solver/test_equilibrium_checks.log)
- [协议比较 10 项测试原始输出](../../../initial_imperfection_material/results/followup/execution_20261022/solver/test_protocol_comparison.log)
- [stepper 9 项测试原始输出](../../../initial_imperfection_material/results/followup/execution_20261022/solver/test_stepper_diagnostics.log)

后续主 agent 应把实际全塔 `equilibrium_checks`、加载 DOF 外功台账和阶段/局部状态输出连到总报告。
T15 还应在同一模型/协议上实际对照 legacy/fine 以及恢复策略，报告路径、关键杆、跳点区间和终点，不仅比较运行时间。
动态工具不能替代 T20/T21 对真实塔质量、阻尼、重力初态、样本隔离和时间步收敛的验证。
