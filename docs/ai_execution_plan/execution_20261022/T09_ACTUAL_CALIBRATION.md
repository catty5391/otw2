# T09 两组实际杆的门控标定工具：步骤和最终结果

批次：`execution_20261022`；执行角色：第 4 执行 agent 的后续任务。

## 1. 最终结论

完成了独立的离线标定工具及 **15/15 项合成契约测试**，没有启动任何新的有限元分析。
真实源文件的 CLI 预检查实际输出：877 与 825 都是 `blocked / G1_not_passed`，保持分段表示。
**本轮真实标定组数为 0，真实 v2 库发布数为 0，真实杆对比图生成数为 0；T09 未完成。**

预检查时 G1 尚在计算，因此保存的是 pending 门控快照。随后主执行线通知：877 的第三组定向数值对照虽全部完成，同四段端力差仍约 **2.15%**，未通过完整幅值的参考复现门槛，G1 全幅明确未通过。
该 2.15% 是主执行线提供的最新结论，本角色没有重新计算，物理证据应以 [力学执行报告](MECHANICS.md) 和对应原始结果为准。
不能把 pending 文件中的状态手改成 passed 来启动正式标定；后续应建立新的、经过核对的限定范围证据文件。

## 2. 实际执行步骤

1. 阅读 T09、`config.py`、`calibration_cache.py`、现有材料骨架、实际杆目录与三维局部参考接口，确认当前合法 v2 库的字段及指纹规则。
2. 将首批目标固定为 877 对应的 `0.85 m L40×3Q235`、825 对应的 `1.95 m L40×3Q235`；没有启动 194 组标定。
3. 明确采用离线输入：只消费已经产生的三维、零载起点、单调压缩参考，不在工具中自动求解新 FE。
4. 定义 G1 门控输入，先检查源文件 SHA256、同网格重放、分段/步长/纤维收敛的证据文件及哈希；G1 不通过时在读取参考曲线或构建模型目录前退出。
5. 补充逐组作用域绑定：杆号、完整钢材、真实几何/profile、边界类型/描述/坐标系、参考配置和文件 SHA256、源运行清单 SHA256、已验证范围。
6. 对单轴可辨识性要求有来源的定量声明，不能仅凭 `scalar_axial_identifiable=true`。缺来源、边界未验证或作用域不覆盖时，输出可补证据的 unsupported，保留分段。
7. 检查参考曲线所有提交点、请求/完成步数、实际/请求终点和覆盖率；部分参考保留 CSV、实际覆盖和原因，不生成全范围骨架。
8. 拒绝二维参考冒充三维、重力预应力起点冒充零载、往复曲线排序成单调曲线、缺材料/引擎/约定的参考和失败试算数据。
9. 用现有七点取样方法重构单调骨架，计算共同区间误差、峰邻点区间及取点造成的峰值重合；把结果明确归为训练重构。
10. 单独记录 `independent_validation=not_performed`；旧库仅只读比较，不能由新旧曲线相近推导独立验证通过。
11. 只有通过全部前置检查和训练重构门槛的组才进入合法 v2 子库；组指纹、配置指纹、依赖源码 SHA256 和引用文件 SHA256 均保存并重新读验。
12. 保留参考/新骨架/旧缓存的绘图能力，曲线面积明确为标量轴向曲线面积，不叫全三维外功或滞回耗能。本轮没有用假物理数据发布实际杆图。
13. 用合成夹具完成 15 项快速测试；合法 v2 写读、部分覆盖、失败、门控、unsupported 和旧库比较都经过测试，夹具输出由临时目录自动清理。
14. 核对真实 `Source/Z30103A6.s2k` SHA256，运行 G1 pending 的真实 CLI 预检查，保存两组 blocked 结果、测试日志和本报告后冻结代码。

本任务只新增 `initial_imperfection_material/calibrate_actual_members.py`、`tests/test_actual_member_calibration.py` 和本任务报告/结果文件。
没有改共享 stepper、现有单杆实验、全塔入口或原缓存，也没有额外开启 agent。

## 3. 作用域和拒绝策略

| 情况 | 机器结果 | 下游动作 |
|---|---|---|
| G1 pending/failed | `blocked / G1_not_passed` | 暂不标定，两组保留分段 |
| G1 自称通过但缺某项证据 | `blocked / G1_missing_*_evidence` | 先补证据 |
| 边界/材料/源 run/参考文件/范围未绑定 | `unsupported` 和具体原因 | 保留分段；允许补证据后用新输出目录重试 |
| 无参考输入文件 | `unsupported / reference_input_not_available` | 等待有效参考导出，不永久排除该杆 |
| 部分参考 | `partial_reference`、实际终点、步数、覆盖率、参考 CSV | 不生成该组全范围骨架 |
| 2D、预应力起点或缺坐标/符号约定 | `unsupported` | 回到适当的空间/有状态参考 |
| 参考配置/证据哈希改变，或代码/输入异常 | `failure.json` 并抛异常 | 保留错误，不回退 Perry |
| 训练重构误差超限 | `unsupported`、保存重构误差 | 改取点或保留分段，不降门槛 |
| 一组通过、另一组无证据 | 只发布通过组的 v2 子库，整批仍是 `partial_or_unsupported` | 不能当作全塔完整库 |

unsupported 是针对“当前数据与当前作用域”的决定，不是永久禁用该构件。
默认范围为端距缩短比 `0～3%`；它不是钢材 Fiber 应变。超过 3% 需显式 `--allow-range-extension`、研究理由、同范围参考完成和作用域证据，不会自动扩成 5%。
主算法与重试算法必须使用同一容差，`ReferenceSolverConfig.legacy()` 的隐式放宽方式会被拒绝。

单轴可辨识性中的“至少两种独立边界、条件轴力差不超过 5%”只是本工具透明记录的保守工程预筛，已经进入配置。
它没有改写冻结的全项目 acceptance_profile，也不能替代 T08/T10/T11 的真实物理判别。工具检查的是作用域、来源、数据完整性与指纹一致性，不能凭一份 JSON 中的布尔值或数字证明机械结论。

## 4. 输入契约

### 4.1 G1 证据

顶层字段：`schema=otw2.actual_member_calibration_gate.v1`、`gate=G1`、`status`、`source_sha256`、`mechanical_profile`、`checks`、`groups`。

`checks` 必须包含 `same_mesh_replay, mesh_convergence, step_convergence, fiber_convergence`，每项给 `passed=true` 和非空证据列表。
每个证据是 `{path, sha256}`；相对路径相对于 gate 文件，而非运行 cwd。

`groups["877"]` / `groups["825"]` 必须包含：

- `scope.member_id`、`steel_fingerprint`、`boundary_fingerprint`、`reference_configuration_fingerprint`、`reference_sha256`、`source_run_sha256`。
- `scope.loading=zero_load_monotonic_compression`、`maximum_compression_strain`，以及包含空间参考、网格/步长/纤维和单轴可辨识性验证的 `validation_kinds`。
- `source_run={path,sha256}`，该源清单的 status 必须为 completed。
- 非空的 `evidence` 列表，指向实际可复核的边界/机制证据，而非只有一条支持声明。
- `identifiability.status`、`independent_boundary_cases`、`maximum_conditional_force_spread_relative`。

不能把失败全幅参考的材料越界段、截取出来的有利分支或不明初态的参考作为这些证据。

### 4.2 零载单调三维参考

输入 schema 为 `otw2.actual_member_monotonic_reference.v1`，每组一个独立 JSON，至少包含：

| 字段 | 要求 |
|---|---|
| `member_id / source_sha256 / dimension` | 实际杆号、同一源文件、维数为 3 |
| `boundary` | 显式空间铰接/固接/转动弹簧/规定 6DOF 之一；有描述及 global 或原杆局部坐标约定 |
| `origin_convention` | `zero_load_zero_end_shortening` |
| `force_convention` | `original_member_chord_compression_positive` |
| `shortening_convention` | `end_chord_shortening_positive` |
| `steel / mechanical_profile / engine_version` | 完整塔钢材参数、G1 同 profile、已知真实引擎版本 |
| `imperfection_vector` | 三个有限全局分量，与物理杆弦正交 |
| `solver` | 完整 `ReferenceSolverConfig.to_dict()`，与请求一致 |
| `configuration_fingerprint` | 下述 helper 计算，绑定完整 member、源、边界、缺陷、求解及范围 |
| `requested_steps / completed_steps / execution_status` | 真实请求/完成数量与状态 |
| `all_committed_states_included` | 必须为 true，曲线点数等于完成步数+初始点 |
| `requested_end_shortening_m / actual_end_shortening_m` | 与范围及实际曲线尾点一致 |
| `curve` | 初始零点及所有成功提交点：`{shortening_m, compression_force_N, committed:true}`，严格单调缩短 |

配置指纹 helper：

```python
from initial_imperfection_material.calibrate_actual_members import reference_identity

reference["configuration_fingerprint"] = reference_identity(
    actual_member_record,
    source_sha256=source_hash,
    boundary=reference["boundary"],
    imperfection_vector=reference["imperfection_vector"],
    solver=actual_solver_settings,
    maximum_strain=requested_end_shortening_ratio,
)
```

actual_member_record 应来自同一 `MechanicalCatalog` 与 G1 profile；CLI 自行读取真实 S2K。
函数中的 `member_records` 注入仅用于快速合成测试/明确的导出目录数据；CLI 不提供伪造实际构件参数的输入开关。
工具没有把重力+往复的 `member_states.jsonl` 自动转成唯一单轴骨架，因为那样会掩盖预应力、弯矩与端转角耦合。

## 5. 产物含义

通过条件后可能产生 `reference_877.csv`、`reference_825.csv`、`config.json`、`summary.json`、`calibration_library.json`、`calibration_comparison.png`。
部分参考仅有其真实覆盖，不会补齐数据或外推曲线。

v2 cache 使用现有不可覆盖、原子发布及指纹验证接口，`validation_status` 仍为 unvalidated。
它是最多两组的独立子库，不是 194 组全塔 drop-in；也不会自动把同截面其他杆、对称杆、不同边界或不同循环历史纳入验证范围。
训练峰值被直接插入七点骨架，所以峰值误差零要解释为重构规则；独立验证明确另列 `not_performed`。
旧库比较标记 legacy_unknown / comparison_only，旧 Perry 下降段不会因此变成经过验证的规律。

## 6. 实际命令和结果

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_actual_member_calibration.py' -v
# 最终冻结版：15 tests, 0.114 s, OK；全部为合成契约测试，无FE

sha256sum Source/Z30103A6.s2k
# 4ba541e896e203d896b9288b9c0dba27b8926fd351cc788054441eb7e8430d16

.venv/bin/python -m initial_imperfection_material.calibrate_actual_members \
  --source Source/Z30103A6.s2k \
  --gate-evidence initial_imperfection_material/results/followup/execution_20261022/actual_member_calibration/pending_gate.json \
  --reference-877 initial_imperfection_material/results/followup/execution_20261022/actual_member_calibration/not_yet_exported_reference_877.json \
  --reference-825 initial_imperfection_material/results/followup/execution_20261022/actual_member_calibration/not_yet_exported_reference_825.json \
  --output initial_imperfection_material/results/followup/execution_20261022/actual_member_calibration/preflight_v1
# {"status":"blocked","groups":{"877":"blocked","825":"blocked"}, ...}
```

该 CLI 进程正常退出仅表示预检查完成，不能用 exit code 0 代替 summary 中的标定/物理状态。
两个 not_yet_exported 路径确实没有参考数据；因为 G1 未通过，工具没有打开它们，也没有建立 catalog 或任何 FE 域。
输出目录已存在，重复命令应换新 preflight_v2，不能覆盖证据。

15 项测试覆盖：合法 v2 写读；G1 pending；缺纤维证据；仅布尔声明；源 run/材料绑定；不可辨识；部分覆盖；2D/预应力拒绝；缺参考；证据哈希变化；统一容差/范围扩展；缺材料/提交点；旧 v1 只读；不覆盖输出；失败试算拒绝。
测试中合法库和旧库都是合成临时夹具；没有把测试生成物当作真实杆标定成果发布。

## 7. 证据与后续执行条件

- [15 项实际测试原始输出](../../../initial_imperfection_material/results/followup/execution_20261022/actual_member_calibration/tests.log)
- [真实源文件 CLI 的 blocked 结果](../../../initial_imperfection_material/results/followup/execution_20261022/actual_member_calibration/preflight_v1/summary.json)
- [预检查时的 pending gate 快照](../../../initial_imperfection_material/results/followup/execution_20261022/actual_member_calibration/pending_gate.json)
- [本轮机器可读交付状态](../../../initial_imperfection_material/results/followup/execution_20261022/actual_member_calibration/verification.json)

当前应收尾保留 blocked 证据，不再启动这两组正式标定。
只有限定作用域的 G1 后续确实通过，且实际空间边界可辨识、零载单调参考完整覆盖所请求范围，才可建立新的 gate/evidence 文件并用新目录执行。
执行时可以用 `--old-cache` 指向旧库做只读差异对照，显式设 `--tolerance`；应先完成一组，再评估另一组的参考可靠性，不扩展为 194 组扫描。
如果仍不可辨识，继续保留分段或按 T11 走参考保底路线；本工具不会强行拟合以绕过该决定。
