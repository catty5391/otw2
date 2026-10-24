# 后续工程与研究实施计划：从可信参考到有限范围交付

编制始于 2026-10-22，补充于 2026-10-23（目录名沿用本轮创建名）。本文由本轮两个规划子 agent 中的工程规划角色编写；本轮只读检查并形成计划，没有运行有限元、修改生产代码、重测整套软件或重启 9999。

当前最短路径是：完成既有参考差异定位，同时补齐来源核验和非循环的阶段依赖；得到可信参考域后再决定哪些杆值得等效。当前不能把“全塔算完”当作材料验证，也不能把“某类杆不适合一维等效”当作分段路线永远不能继续的原因。

## 1. 执行起点与已有能力

工作区为 `/home/panqiheng/otw2`，分支 `redevelop`；HEAD 不能代表全部成果，已有未提交及未跟踪文件需要保留。解释器使用 `.venv/bin/python`。状态依据是 [RESULTS.md](../execution_20261022/RESULTS.md)、[TASKS.json](../TASKS.json) 与各执行报告。

截至上一批，25 项中 9 项完成、6 项被前置条件阻塞、2 项部分完成、8 项尚未实施。软件最后一次整套验证为 **264/264，16.440 s**。本轮没有重新运行，下一轮只有相关源代码改变、发现新失败或准备阶段门交付时才重测。

| 已有能力/证据 | 下一轮应复用的真实位置 | 不应再做的重复工作 |
|---|---|---|
| 完整 legacy 全塔参考，9/9、587 步 | `results/followup/execution_20261022/reference_legacy_v1/segmented_reference/`，路径前缀均为 `initial_imperfection_material/` | 不再以“补记录”为由重跑同配置 |
| 原卡点、fine、gradual 三组全塔数值回归 | 同批 `solver_legacy_v1/`、`solver_fine_v1/`、`solver_gradual_v1/` | 不再盲目堆算法/降步长；fine 仍越域，gradual 未改善 |
| 877 完整同四段第三次重放差 2.15446% | [MECHANICS.md](../execution_20261022/MECHANICS.md) 及其指向的原始档案 | 不重复已执行三组；不能当作 877 网格已收敛 |
| 825 全幅加密与密采样峰位、前六目标 Fiber/镜像对照 | 同批 `mechanics/` | 不把力指标通过外推成 Fiber 极值/全幅 G1 通过 |
| 配置、v2 缓存、状态、记录、比较、残差、外功、步长预算 | `initial_imperfection_material/config.py`、`calibration_cache.py`、`util/analysis/`、`util/processing/` | 不重建另一套基础框架 |
| 两组实际杆离线标定工具 | `initial_imperfection_material/calibrate_actual_members.py`，15 项合成测试 | 工具不会生成 FE 参考；真实标定当前 0 组 |
| 16 个预冻结循环设计与绑定契约 | `initial_imperfection_material/cyclic_protocol_contract.py`、`protocols/t10_pre_frozen_v1.json` | 当前数值幅值 0、FE 0；不是已经完成的循环验证 |
| 动力样本独立建域/初始化注入 | `fluctuate_wind_simulate/opensees_simulate/wind_refactor_common.py` | 不重写样本隔离；实际塔质量/模态/阻尼仍未验收 |
| 易损性保守准入和流转、9999 网页 | `util/analysis/sample_admission.py`、`fluctuate_wind_simulate/fragility_curve/main.py`、`py_view/results_dashboard/` | 不把历史 70 条未知结果重新标成正式样本 |

本文的任务 E01～E12 是剩余工作的执行切片，不替代原 T00～T24 的历史记录。T08 的具体力学定位与参考加密由本轮另一规划角色单独细化；这里规定其输出如何进入后续任务。

## 2. 依赖需要先区分的四件事

现有实现存在实际的逻辑阻塞：T09 的正式标定要求 G1、至少两种独立边界的可辨识性证据及完整零载单调参考；T10 的 `resolve_case()` 又同时要求 `G1=passed` 和 `T09=completed`；T11 原清单依赖 T09/T10。若某杆确实不可一维等效，不能伪造 T09 completed 来让 B/C 路线继续。

下一轮应通过显式版本化接口调整，而不是改旧 gate JSON：

1. **参考诊断/可辨识性试验**只研究分段参考，可以在候选骨架尚不存在时执行。用于建立 G1 的网格、步长、边界检查本来就不能依赖 G1 已通过；它们完成前的结果始终是未验收的诊断数据。
2. **限定作用域 G1 结论**必须列出构件、完整参数、缺陷、边界、协议、范围、参考离散与证据。前六目标力史通过，不能覆盖零载到 3% 的单调标定，更不能覆盖完整 ±1% 全塔或未来风振。
3. **T09 处理终态**可为 `calibrated_subset`、`unsupported_in_scope`、`incomplete_reference` 等；它表示这组处理有结果。只有真实通过组才有 `calibration_completed=true`，只有它们能进入候选循环验证。缺参考导致 blocked 不是“已证不可辨识”。
4. **T11 的负结果决策**可消费完整且可信的不可辨识证据、局部误差及成本评估，选 B/C；不能要求不可等效杆先生成成功候选。C 仍必须通过它实际研究范围的参考 G1/G4/G5。若 G1 尚未可信，仅能形成资源优先级/暂定路线记录，不能把正式 G2 或后续物理门标 passed。

建议依赖图如下，其中“参考可信”均带作用域；不同作用域不能直接继承：

```text
E01 来源/状态核对 ─┬─ E02 参考诊断与候选验证接口分离（0 FE）
                  └─ E03 动力输入/质量来源清单（0 FE）
已有档案 → T08 定位/必要的参考验证 → scoped G1
                                         ├─ E04 零载单调与边界可辨识性
                                         │       ├─ supported → E05 两组离线标定
                                         │       │                 └─ E06 循环参考绑定/训练与诊断
                                         │       └─ unsupported → E07 B/C 负证据选路
                                         └───────────────────────────────┘
E06 训练/诊断机制证据 → E07 选路（不读 holdout 评分来选模型）
  A → E08 状态原型/引擎 → E09 构件独立留出 → E10 塔段/全塔/成本
  B → E08 混合政策/构建 → E09 等效子集与分段保留域 → E10
  C → 已验收分段参考 → E10 参考自身全塔验证（不冒充候选对照）
E10/G4 → E11 动力初始化及小批风振/G5 → E12 可选易损性/G6与研究交付
```

图中的 E04 零载/边界参考有自己的收敛验收；不能仅因既有往复 G1 已通过就免做。E04 中建立新参考域的诊断计算不依赖已完成 E05/E06；只有宣告其可信和用于标定时需要实际 G1 证据。这样消除“先有候选才有参考”的闭环。

## 3. 可以与 T08 同步完成的低成本工作

### E01 — 来源、计数和当前计划入口核验

- 对应：T24 交接维护；owner 为工程 agent。
- 输入：当前 TASKS、RESULTS、`execution_summary.json`、T09/T10 报告、原 S2K、旧 metadata、冻结阈值。
- 操作：核对 source-file 字节哈希、模型配置指纹、设计规范化哈希、运行清单哈希的字段含义；建立带路径/文件类型/算法的来源表；修订当前入口的过时描述，历史执行结果加勘误说明而不静默重写。
- 本轮已只读核实：`Source/Z30103A6.s2k` 的 SHA256 为 `4ba541e896e203d896b9288b9c0dba27b8926fd351cc788054441eb7e8430d16`；`fine_sparse/member_metadata.json` 为 `f274ce6b1fa4f51d6891cd537caa4950257a4bea874757bc47fbac83dc22fbbb`。T10 JSON 的 `historical_member_metadata` 指向正确，T10 报告第 1 节把后者简称“源 SHA256”会混淆；不能拿后者填写 `source_sha256`。
- 产物：`provenance_audit.json`、`PLAN_ERRATA.md`、更新后的当前交接入口；保持旧批次原始 run/manifest 不变。
- 验收：每个身份字段能定位到实际文件；9/6/2/8 的原状态和 264 测试记录不被新计划冒充新结果；所有新增链接有效。
- 测试：文档/JSON 只做解析、链接、字段一致性检查；不为文字更正新增单元测试。
- 预算：0 FE，预计 30～60 分钟人工检查；无整套重测。
- 失败出口：缺失/不匹配记录具体路径和实际哈希，禁止通过重新基线化抹除差异。

### E02 — 将“参考诊断”和“候选验证”从接口上分开

- 对应：T09/T10/T11 的工程增量；owner 为工程 agent。
- 输入：`calibrate_actual_members.py`、`cyclic_protocol_contract.py`、16 用例设计包、[T09 报告](../execution_20261022/T09_ACTUAL_CALIBRATION.md)、[T10 报告](../execution_20261022/CYCLIC_PROTOCOL_PREPARATION.md)。
- 操作步骤：
  1. 保留现有 v1 `resolve_case()` 的约束和旧绑定文件；规划新版本/独立参考入口，不偷偷删除 `T09 completed` 检查。
  2. 加入参考试验 purpose 与范围：`reference_diagnostic` 可在 T09 前消费原始观测，但返回 `candidate_ready=false`；正式候选验收仍要求该组标定成功及真实 scoped G1。
  3. 参考锚点区分“为了建立收敛性而运行的 provisional”与“已经通过精度确认可用于候选协议”；不能用 provisional 幅值发布可用候选。
  4. 加入 `T09_processing_outcome` 和逐组 `calibration_completed`；T11 接受有证据的 unsupported 终态，不接受 missing/failed 冒充不可辨识。
  5. 对 evidence 注册项实际读文件核对字节 SHA256、存在性、成员/边界/范围和原始 run 状态。当前契约只检查声明与格式，不能继续把“哈希长得对”当作真实已核对。
  6. 实现候选准备/负证据选路两个入口的 DAG 检查；同一项不依赖自身通过，A/B/C 的必需门清晰且不互相阻死。
- 拟建接口：建议 `reference_protocol_contract.py` 与 `route_decision_contract.py`，或在现模块内增加独立 schema；**当前没有这些模块/CLI，先实现并测试，不能直接运行**。
- 产物：版本化契约说明、真实证据注册表模板、分组决策表、最小测试。旧包规范化哈希 `cef191cf7111125dcfd2ec461c8bbc206a3050089ac068bae24d724b5d647e7a` 保留；结构改变必须新版本。
- 有意义的测试：篡改证据字节、交换 S2K/metadata 哈希、错误作用域、失败参考、同数据不同 ID 泄漏、unsupported 允许 C 决策但禁止候选、G1 未过禁止 C 的正式全塔准入、DAG 无环。
- 验收：既有 15/16 项相关测试仍通过，新边界测试通过；所有新“recipe_ready”仍不等于执行或物理通过。
- 预算：0 FE，1～3 小时实现/评审预算；专属测试通常秒级，超 5 分钟先定位资源或异常，不能当成 FE 运行。
- 失败出口：先交付参考诊断与负证据报告，保留旧 v1 门控；未完成接口前不手改 T09/T10 passed。

### E03 — 提前形成动力来源与风输入清单

- 对应：T20/T21 前置工程；owner 为工程 agent，可在 G1 阻塞期间做。
- 输入：`model/tower_model.py:mass()`、已保存 `model_data/masses.csv`、导线质量模块、S2K `ASSEMBLED JOINT MASSES`、`wind_refactor_common.py`、风输入与楼层节点配置。
- 操作：只读汇总各平动方向质量和楼层分布；查重节点质量/单元质量/导线参与方式；列重力映射、端约束、转动自由度处理、现有风力单位和平均/脉动分量；记录未声明字段为 unknown。节点表导出的总量不是已经完成的动力有效质量核验。
- 已有可用 CLI：

```bash
.venv/bin/python -m util.analysis check-wind \
  fluctuate_wind_simulate/static/wind_press_generate \
  --node-config fluctuate_wind_simulate/.config/node_to_add_wind_press.json \
  --output initial_imperfection_material/results/followup/next_batch_v1/wind_input_preflight.json
```

- 实施前确认输出新路径不存在；`next_batch_v1` 仅示意下一批目录名，当前未创建。
- 产物：`dynamic_source_ledger.json`、`mass_source_audit.csv`、`wind_input_preflight.json`、待证项清单。不得在 G4 前写“实际塔动力验收通过”。
- 测试：若新写质量汇总器，测试节点重复、三个方向质量、空值、单位及总量守恒；不改既有隔离入口就不重复其 8 个真实测试。
- 预算：0 FE，30～90 分钟只读核查；文件统计在 10 分钟预算内。大输入先统计大小/数量，再决定是否全量谱检查。
- 失败出口：单位或导线参与不明时继续做独立来源整理；不能补一个猜测的质量/阻尼系数填空。

## 4. 参考可信后执行的单杆任务

### E04 — 零载单调导出与独立边界可辨识性

- 对应：T08 范围扩展、T09 前置、T10 参考锚点；owner 为力学 agent。
- 输入：T08 的 scoped G1/未通过说明、真实 `MechanicalCatalog`、两根实际杆 877（0.85 m）/825（1.95 m）、完整 Steel02、确切缺陷向量、统一 Fiber/积分/坐标和零载初态。
- 当前实际 API：`member_reference_3d.run_axial_boundary_case(member, axial_extensions, boundary=..., divisions=..., imperfection_vector=..., rotational_stiffnesses=..., elastic_steel=...)` 支持三维铰接、固接、四个端转动弹簧；正 axial extension 为拉伸。当前 CLI 只做既有两端历程重放，**没有完整 T09 单调导出 CLI**。
- 接口差异必须先处理：现函数固定 Newton、`NormDispIncr 1e-10/80`；不能给 T09 随便附一份不一致的 `ReferenceSolverConfig`。下一实现仅增加可声明且实际生效的 solver 配置/预算、完整输出，不复制一套截面和建模器。
- 操作步骤：
  1. 为零载单调压缩编写小型导出器，所有成功提交点写出；实测请求/完成终点、状态和来源，使用现 `reference_identity()` 生成身份。
  2. 先 877 一组、一个边界得到时间/存储样本；按既有 G1 方法验证它的新单调域，不能用既有塔端往复的精度自动覆盖。
  3. 按相同轴向路径比较第二种有来源的端约束。铰接/固接可以做边界包络诊断，但不能把任选的固接认为就是塔中实际边界；弹簧刚度须有独立来源，不靠调 K 抵消失配。
  4. 在相同轴向历史/端距缩短处，记录端转角、弯矩、轴力、形状；形成条件轴力差表与参考误差带，不能把不同历史只按单个 strain 拼在一起。
  5. 对 825 按同样方法实施；若参考不完整，保存 partial，不自动 Perry；若可辨识性不支持，记录 unsupported 进入 E07。
  6. 如需要 C0/C1 幅值，另做 Elastic 小幅和 Steel02 明确低应力裕度的锚点；拉伸锚点需单独参考，不能由压缩幅值直接取负代替。
- 产物：`reference_877.json`、`reference_825.json`（`otw2.actual_member_monotonic_reference.v1`）、完整原始状态档案、各自 run 清单、`identifiability.csv`、新 scope gate 与证据哈希、峰值邻域采样表。
- 验收：零载/零缩短起点、三维、真实完整材料及边界、覆盖请求范围 100%、网格/步长/Fiber 受控。单轴预筛当前工具要求至少两边界且条件轴力差 ≤5%，这是工程预筛，不是材料唯一性定理；循环历史可辨识性仍由后续判断。
- 预算：首阶段最多 2 杆×2 边界共 4 个单调主例，逐个运行；首例测时后更新下一例预算。每例初始管理上限建议 900 s/输出 2 GiB，达到即保存未完成；这些是止损上限而非预测。必要网格/步长对照按失败指标追加，不批量展开所有组合。额外 Elastic/拉伸锚点另列清单后执行。
- 失败出口：参考尚不可信回 T08；已可信但不可轴向等效转 E07；覆盖不足仅降低未来声明范围并形成新 scope，不能截掉已有失败段后宣称原范围通过。

### E05 — 实际两组离线重构，保留成功与负结果

- 对应：T09；owner 为力学 agent，工程 agent 核查缓存/身份。
- 输入：E04 实际导出的参考、真实 scoped G1、可辨识性/边界证据、旧缓存只读对照。
- 现成 CLI 模板如下；占位文件必须由 E04 真实产生，当前 pending_gate 不能替换为 passed 文本后运行：

```bash
.venv/bin/python -m initial_imperfection_material.calibrate_actual_members \
  --source Source/Z30103A6.s2k \
  --gate-evidence initial_imperfection_material/results/followup/next_batch_v1/actual_members/gate_verified.json \
  --reference-877 initial_imperfection_material/results/followup/next_batch_v1/actual_members/reference_877.json \
  --reference-825 initial_imperfection_material/results/followup/next_batch_v1/actual_members/reference_825.json \
  --old-cache initial_imperfection_material/results/full_tower_cyclic/calibration_library.json \
  --output initial_imperfection_material/results/followup/next_batch_v1/calibration_v1 \
  --maximum-strain 0.03 --tolerance 1e-8
```

- 上例的范围/容差只是接口展示，执行值必须与参考 solver/有效域一致；CLI 目前只暴露 tolerance，不足以表达更复杂实际 solver 时应调用 `calibrate_batch(..., solver=actual_config)` 或先补真实配置输入，不能伪填 metadata。若只通过一组，可以用 API 处理限定子集；不为“凑两组成功”填假另一组。
- 操作：核验文件哈希→检查完整覆盖→共同区间重构→与旧库只读比较→发布合法 v2 子库→重新读验缓存指纹→逐组记录 terminal outcome。
- 产物：工具已有 config/summary/reference CSV/plot/library；另加训练重构 vs 独立验证明确标签及逐组保留表示政策。
- 验收：训练峰力 ≤3%、NRMSE ≤5%、100% 覆盖；峰值被采样点直接保留应解释为重构性质；库仍 `unvalidated`，最多两组，绝非 194 组 drop-in。
- 测试：只在导出器/门控接口发生改变时运行 `test_actual_member_calibration.py` 及新增来源回归；不重跑 FE 证明缓存有效。
- 预算：0 新 FE，通常秒至分钟；每批 10 分钟上限包含绘图。默认不扩 5%，不自动重标定 194 组。
- 失败出口：partial/unsupported 原样保留，转 E07；exit code 0 不代表校准成功，读取 summary 的实际分组状态。

### E06 — 实际循环幅值绑定、参考训练/诊断与预留独立验收

- 对应：T10；owner 为力学 agent，工程 agent 核对 E02 来源/泄漏契约。
- 输入：`t10_pre_frozen_v1.json` 或经过说明的新版本、E04 实测 Fiber/峰值/拉伸锚点、E05 成功子集、未加载+重力+两端 6DOF 的档案及未来预注册路径。
- 现 CLI：

```bash
.venv/bin/python -m initial_imperfection_material.cyclic_protocol_contract
.venv/bin/python -m initial_imperfection_material.cyclic_protocol_contract \
  --case q235_l40_0850_c1_train \
  --bindings initial_imperfection_material/results/followup/next_batch_v1/cyclic/reference_bindings_verified.json
```

- 上述 CLI 只解析，不运行 FE。真实循环 runner 为**待建小入口**，应复用 E04 和现有 3D/重放 API；不能把 `recipe_ready=true` 当曲线已经出现。
- 操作顺序：C0 Elastic 两组→C1 两组→C5 seen 可信范围诊断→C2/C3/C4 训练；每阶段通过前停止扩展。纯 Elastic C0 检查严格可恢复；Steel02 C1 比较其自身真实残余，低于 fy 不自动等于严格弹性。
- 原设计是 16 个逻辑用例（8 训练、4 诊断、4 留出），不是只需要 16 个底层求解；参考精度对照、候选对照另外计数。C5 已见全塔路径永远是 diagnostic；未来 C5 和 C6 保持 holdout，不用其评分作 E07 选路或调参。
- 同杆铰接的幅值锚点不能直接绑定空间塔端历史；C5 必须是真实 12 个端自由度和所有前序阶段。新完整全塔历史若有必要，要由主 agent 另立唯一案例/预算，从初始与重力开始。
- 产物：真实 bindings、每例 source/response 哈希、usage 账本、已执行数量/范围、轴力—缩短/卸载刚度/恢复力/残余/轴向部分功、参考 Fiber/弯矩功。区分零力残余位移与强制原端距时恢复力。
- 验收：所有锚点在可信范围内、来源实际可验、无 training/holdout 泄漏；C0 恢复力 ≤max(1 N,峰力×0.1%)、伪外功 ≤0.5% 参考可恢复尺度；其他循环按冻结阈值比较参考实际响应。不可用 Vbase–utop 面积充当此处耗能。
- 预算：第一批只 2 杆 C0/C1，最多 4 个逻辑用例，每个底层参考运行按 E04 实测预算；余下训练/诊断另列预算。holdout 留到 E09 候选冻结后只揭示一次；失败后若拿它调参，标记 seen 并新建独立 holdout。
- 失败出口：纯 Elastic 不恢复先查几何/边界/求解；Steel02 无法表达的耦合形成负证据进 E07；缺峰后或拉伸可信锚点保持该协议 unresolved，不造数值幅值。

## 5. 选路及结构层任务

### E07 — 形成有终点的 A/B/C 路线决策

- 对应：T11/G2；owner 主 agent，两个执行 agent 提交证据。
- 输入：scoped G1、E04 可辨识性、E05 真实处理终态、E06 训练/诊断机制及成本；禁止使用独立 holdout 评分选模型。
- 操作：按杆族/边界/历史范围列 supported、unsupported、unknown；将全塔已知局部偏差、I23 耦合审计与参考自身误差分开；比较有限范围精度收益和实现成本，选一个主路线。
- A 条件：一维状态对目标杆族的目标历史足够；同轴向史不同端转角/弯矩的差异在阈值内；所需循环机制能由可观测量辨识。
- B 条件：存在非空的已验证/可验收等效子集，且其余杆能由事先规则保留分段；规则依据几何、边界和有效域，不只写死 877/878。若一个可接受等效组都没有，B 的“全分段”退化应明确等同于 C，而不是虚称新混合效果。
- C 条件：等效机制或收益不足，选择分段主线可作为务实终态；仍需该模型/研究范围可信的 G1、全塔 G4，做风振再过 G5。G1 未过可先定“优先研究参考”的管理决定，物理准入继续阻塞。
- 产物：`MODEL_ROUTE_DECISION.md`、machine route/scopes、未选任务状态、`T09_processing_outcome`；调整 TASKS 依赖经主 agent 检查，无环，历史 blocked/failed 证据不删。
- 验收：unsupported 能进入 B/C 负证据决策但不能发布候选库；missing_reference 不能假定不可辨识；未选 T12/T13/T14 记 `not_selected` 并引用决定。
- 预算：0 FE，半天内基于已获证据决策；只有明确能改变结论且不重复旧实验的最小追加对照才另立案例。
- 失败出口：若仍缺可信参考，交付受限结论/下一参考问题，不强行选 A/B；禁止用路线 C 绕开参考数值精度。

### E08 — 只实现所选候选分支

- 对应：A 的 T12/T13，或 B 的 T14；owner 按路线指定唯一源代码负责人。
- A 步骤：最少状态 Python 原型→trial/commit/revert/start/copy→有限差分切线/折点左右切线→现有引擎载体能力试验→必要时才原生扩展→材料、truss、3D 梁逐层一致性。未知规则不先加任意退化参数。
- B 步骤：每根原杆冻结 `representation_policy` 和理由→复用既有两个构建器→标签/连接/原杆映射→质量/重力/风面积一致→缺陷仅计一次→全等效/全分段两个极端小模型回归。运行中不动态换表示。
- 输入：E07 决策、E05 库、E06 训练/诊断、完整参数和有效域；不是旧 194 组库默认全可用。
- 拟建入口：A 的 `cyclic_material.py`/必要原生模块；B 的 `model/tower_model_hybrid_imperfection.py`。当前未存在，不能写成可执行命令。
- 产物：实现、配置、状态/接口说明、可重建版本信息、失败试算状态独立性测试；原生扩展要能从源码重建，不只交本机二进制。
- 验收：A 被拒 trial 不污染已提交状态，克隆独立，P 通道面积只乘一次；B 原杆全覆盖/标签无冲突/政策前置/分段与等效不重复缺陷。尚不宣告 G3。
- 预算：先 1 个工作日做小原型和可行性说明；没有明确收益/训练改善时回 E07，不同时做完整 A+B，也不直接启动 C++ 全实现。
- 失败出口：保留训练反例，选择更小适用域或 B/C；不能取消软化、永久弹性化关键杆或调钢材参数掩盖错误。

### E09 — 构件独立留出与作用域发布

- 对应：T16/G3，A/B 才必需；owner 力学 agent。
- 输入：冻结候选版本、未经拟合/选模使用的 C5 future 与 C6，训练/诊断参考，scope 与阈值。
- 操作：先两组已支持对象，在相同边界/完整初态下比较；再选择已有实际 Q345（例如审计中 349）/Q420（例如 1）是否需要扩展。必须重新核对实际参数，未执行的钢级不得纳入有效域。保留分段杆也需其实际参考域已可信。
- 产物：`member_validation.csv`、`valid_domain.json`、每例曲线与状态证据、拒绝/保留分段规则；有效域包括长度、材料、缺陷、边界、幅值、方向、循环次数。
- 验收：独立循环峰力/卸载刚度误差 ≤5%、曲线 NRMSE ≤10%、残余和循环功按冻结 10%/绝对量级规则；无隐式越域。只通过单调重构不能算 G3。
- 预算：首批两组×两个预留逻辑用例，最多 4 个 holdout；底层参考/候选独立计数、串行，参考不重算已有合格结果。新增钢级每次一组。
- 失败出口：失败 holdout 保留；若用其改善模型，它失去留出资格，重新预注册一例；不能循环重调同例直到“独立验证通过”。

### E10 — 塔段、全塔、配置冻结与公平成本

- 对应：T17/T18/G4、必要 T19；owner 力学 agent，主 agent 统筹长任务。
- A/B 输入：G3 候选+可信参考；C 输入：选定分段模型的可信参考域，无需构造虚假等效候选。
- A/B 顺序：含 877/878 及真实邻接传力的完整横担区域→边界扩大一圈敏感性→小幅/原协议/预注册留出→全塔原节点 350/DOF2、L/1000、原 seed 和 9 目标→一个正交方向与一个缺陷变体。每层通过再扩。
- C 顺序：相同分段模型的局部/必要全塔加密、步长和事件一致性，先通过其声明幅值；legacy/aligned 的材料/几何差异单列归因，不能混成收敛误差。
- 必须另设 **单调全塔极限推覆** 子任务，与原 9 目标循环验收分开。当前参考与 fine 的 9/9 是达到预先给定 ±1% 并回零后结束；只有原步长/gradual 等效案例是在 6/9 数值停止。不能因为图近似直线就把所有结束都解释成不收敛，或因为少数局部杆已过名义 fy 就认定全塔已达峰值。
- 单调任务从全新初态与重力开始，使用一致的风力空间分布与明确控制节点/方向。先以已有可信幅值为阶段目标，完成后按预冻结的增幅上限、单步上限、成功步/尝试/时间/磁盘预算逐段推进；需要更大幅值参考域时先补对应 G1/材料范围证据，不能直接外推等效 3% 骨架。分段模型也要检查应变、局部几何与材料物理适用范围，不能把分段当作无限有效。
- 在运行前冻结“已观测峰值/已覆盖峰后”的识别规则、步长复核及端部状态记录。只有曲线确有峰值、峰后段且其数值/材料域可信，才能讨论该工况的承载峰值；未见峰后就报告“本次范围内最大已观测荷载”和结束原因。停在最小步或预算是数值/资源终点，不能自动写极限承载力/倒塌；软化后分支敏感性另列诊断，不通过随意放宽容差继续画线。
- 单调产物单列 `monotonic_pushover/`：P–u、相对初始斜率、切线/割线刚度、关键杆事件与空间分布、峰值附近完整提交点、覆盖与停止原因。首批只一个方向/一个冻结缺陷场，不将更大位移盲扫等同于求极限。此任务需要可信参考后独立案例立项，**本轮不运行**。
- 现全塔 CLI 已支持 `--minimum-increment`、`--reference-divisions`、`--tolerance`、`--iterations`、`--algorithms`、`--recovery-policy`、成功步/试算/超时预算、关键杆与目标漂移。需要新参考时必须显式 `--model segmented_reference`；省略 `--model` 会依次运行参考和等效，可能意外触发不需要的校准。
- 当前 CLI 没有任意方向/完整 aligned profile/混合政策开关。相关新试验要用已核对的 Python API或最小增量入口，不臆造命令参数。
- 产物：塔段几何/边界图、全塔目标点与逐杆误差 CSV、空间图、事件顺序/区域、覆盖率、参考不确定范围、残差与外功；候选未通过的局部误差不能被整体 0.16% NRMSE 掩盖。
- 验收：塔段初始刚度 ≤3%、整体反力 ≤5%、关键杆 ≤10%；全塔整体 ≤5%、关键杆 ≤10%、显著受力其余杆 P95≤10%/最大≤20%，异常有记录。C 使用参考收敛/残差/事件门，不伪造候选相对参考误差。
- 预算：先 1 个塔段再 1 个全塔主例；上一批完整参考约 3324 s 是含详细记录/资源竞争的观察值，不能作性能基准。下一例先定记录量/存储空间，预留 2 小时管理上限并用实际进度修订；一次只能有一个长 FE。
- T19：只在同终点/协议/精度/记录量通过后，单机串行至少 3 次热缓存计时；冷标定、建模、重力、求解、I/O、后处理、内存分列。C 无等效候选时不做伪加速比，可仅报告资源需求。
- 失败出口：全塔局部超限回 G3/政策范围，参考失配回 G1；新候选不通过不影响既有诊断证据的保存。

## 6. 风振、可选易损性和交付终点

### E11 — 实际塔动力验证和 3 种子小批

- 对应：T20/T21/G5；owner 工程 agent 负责初始化/动力接口，力学 agent 负责物理判别。
- 输入：G4 冻结模型与 E03 来源账本、完整质量/约束/重力、阻尼依据、风输入。`run_one_sample(..., model_factory=..., initialize_model=..., model_declaration=..., control_node=..., control_dof=..., wind_load_dof=..., output_root=...)` 与 `run_sample_batch()` 已存在，直接复用。
- 步骤：实际塔质量总量与分布/单元节点去重→独立重力和冻结→模态配对/MAC→阻尼来源与具体刚度类型→小幅线性瞬态和真实 M a/C v 残差→代表例 dt/2→一个固定风样本小强度→同样本有效域内非线性→再加两个预固定种子。
- 模态/MAC、实际初始化配置和完整动力账本是本轮未实现部分，需小模块和接口；目前没有已经完备的全塔 G5 命令。不能以已有解析振子或样本顺序独立代替实际塔模态。
- 漂移器仍按全局 Y/DOF2 与绕 X/DOF4；换 `control_dof` 不自动改变漂移定义。其他方向先实现并验算坐标变换/风映射。
- 产物：`dynamic_model_config.json`、`mass_ledger.csv`、模态/MAC/阻尼报告、输入谱/相干/单位核验、实际时程、关键杆局部状态、时间步敏感性、完整质量状态。
- 验收：目标频率误差 ≤3%、MAC≥0.95（近重根用子空间）、小幅峰/RMS≤5%、非线性主要峰/RMS及关键杆≤10%；真实残差来源完整；所有越域/失败有处置。没有质量/阻尼来源就保持 unknown，不猜 M/C。
- 预算：A/B 第一轮最多 3 种子×2 强度×2 模型＝12 主运行；C 为 6 主运行，加一个代表 dt/2 对照。先一例短窗测资源，短窗不是正式完整样本；每个样本预算按实测时长×安全系数冻结后扩批，禁止直接 70 组扫描。
- 失败出口：返回初始化/步长/适用域，保留 failure/timeout/out_of_range 的区别。G5 不通过仍可交静力研究；不因此把响应失败当倒塌。

### E12 — 可选易损性与最终研究交付

- 对应：T22/G6（仅 scope 含 fragility）、T24；owner 主 agent。
- 研究范围在 G4 时明确：static 验证截止于 G4；wind 还需 G5；fragility 还需 G6。当前用户没有提供学校正式硬性要求，不能以软件任务完成承诺毕业；范围选择应依据课题主线和实际证据。
- 若做易损性：先冻结服务性/杆件屈服/压屈/体系退化各极限状态及出处，验证等效量与钢材 Fiber 判据映射；再冻结 cohort、风速、样本/seed、停止规则和未知失败处理。数值失败、越界与物理失效分开，缺失样本保留分母。
- 现正式准入入口为 `fluctuate_wind_simulate.fragility_curve.main`，支持 `--output-root`、`--output-dir`、`--eligibility-mode formal`、`--criteria-id`、`--cohort-json`；它只导出正式准入与事件表，不会自动拟合正式概率曲线。`--manual-thresholds` 和 `--auto-thresholds` 只适用于明确历史探索。
- 拟建正式统计部分必须消费物理事件/已冻结判据而非重新从分位数定阈值；处理 unknown/删失要依据实际观测机制，报告置信区间和敏感性。现有探索拟合不能改标签即变正式。
- 产物：若含 fragility，`limit_states.json`、全样本流转/分母、参数及不确定性、适用范围；所有路线都生成 `VALIDATION_REPORT.md`、`MODEL_LIMITATIONS.md`、`REPRODUCE.md`、每图 CSV/命令/配置哈希和适用域。
- 验收：选择的研究范围各门有实际证据；未选路线记 not_selected，可选范围不做记 deferred；正式统计无阈值/质量/分母缺口。至少保留旧虚假残余、局部失配、fine 越域这些反例。
- 预算：静力/风振交付整理各半天预留；易损性样本数不在缺少先导方差与失效比例时拍定，先由 pilot 的区间宽度估算。没有冻结的统计方案就不扩样。
- 失败出口：G6 尚不满足时交付已验证的静力或风响应对照，保持正式拟合未执行，不用探索曲线填补。

## 7. 下一轮两个执行 agent 的分工

用户本轮明确要求的是两个**规划**子 agent；本文是后续执行分工建议，不自动启动 FE 或第三个子 agent。用户下一轮授权实施时可按下面分工执行。

| 角色 | 首批独占任务/文件 | 物理解锁后的职责 | 不应同时写的共享位置 |
|---|---|---|---|
| agent M：参考与力学 | 另一规划报告指定的 T08 定位、独立参考分析与该批 mechanics 证据 | E04/E06/E09，E08 选定力学候选，E10 物理判别 | `member_reference_3d.py` 为 M；若工程要其参数接口，先书面 schema，M 单点合入 |
| agent E：接口与证据 | E01/E02/E03、新 provenance/route 契约及相应独立测试 | E05 数据核验、E11 初始化/模态/风入口、网页证据增量 | `cyclic_protocol_contract.py`/`calibrate_actual_members.py` 为 E；M 提供物理字段，不同时编辑 |
| 主 agent | 批次目录、预算、阶段门、TASKS/PLAN/HANDOFF、总报告 | E07 决策、唯一长 FE 调度、集成测试/全塔和服务 | `TASKS.json`、共享 `full_tower_cyclic.py`、`stepping.py`、`run_manifest.py`、网页共享接口由主 agent 协调单 owner |

先汇合 E01/E02 的 schema，再动依赖它的生成器；不能两边各写一套 source hash/作用域定义。工程任务结束后可只读复核力学档案或整理图表，不为了让 agent 忙而启动第二个长 FE。

调度规则：

1. 同时最多一个长 OpenSees FE 进程；不同域即使可放不同进程，本批也先串行，排除资源竞争和证据混乱。短契约测试可以与其并行，但真实 OpenSees 测试也应排队。
2. 每个运行独立且不可覆盖目录、独立清单与实际 PID/session；共享缓存只有一个写者。记录 Python/OpenSees 版本、代码及输入指纹、开始/结束/停止原因。
3. 主 agent 在首例前列案例数、预计自由度/记录字段/磁盘、成功步/尝试/时间预算。每 60 秒内给进度或当前证据更新，不能仅报告“还在跑”。
4. 不从 JSONL 假恢复非线性材料状态。需要重算时从初始/重力重放，除非另有经过验证的完整引擎 checkpoint。
5. 冻结阈值沿用 `execution_20261022/acceptance_profile.json`；新指标阈值在观察候选评分前注明来源和范围。预算到达、参考部分覆盖、数值失败分别保存，不能改成 collapse。
6. 性能计时全部串行、同记录量。网页既有 9999 继续运行；只有网站源代码改变且完成测试后才按已有部署授权更新，不误杀未知监听进程。

## 8. 最小复核命令与测试调度

以下命令实际存在，均从仓库根执行。只读命令可用于开工；不能因为计划列了命令就重跑全部。

```bash
git status --short
git branch --show-current
git rev-parse HEAD
sha256sum Source/Z30103A6.s2k initial_imperfection_material/results/convergence_diagnosis/fine_sparse/member_metadata.json
.venv/bin/python -m initial_imperfection_material.cyclic_protocol_contract
.venv/bin/python -m initial_imperfection_material.calibrate_actual_members --help
.venv/bin/python -m initial_imperfection_material.full_tower_cyclic --help
.venv/bin/python -m util.analysis.baseline_snapshot \
  --root /home/panqiheng/otw2 \
  --verify docs/ai_execution_plan/execution_20261022/baseline/baseline_inventory.json
```

| 实际改动 | 应跑的最小现有测试 | 何时才加大验证 |
|---|---|---|
| 只改计划/来源勘误 | JSON/链接/指纹检查 | 不重跑 264 |
| E02 契约/离线标定 | `test_cyclic_protocol_contract.py`、`test_actual_member_calibration.py`，新 provenance/route 边界测试 | 更改共享状态/缓存时追加对应测试 |
| E04 3D 单杆 API | `test_member_reference_3d.py`、相关 archive/fallback/convergence 测试，新增实际配置/零载/partial 导出测试 | 小型真实 FE 先行，长局部算例独立清单 |
| E08 材料/混合 | 新状态生命周期/单元解析/映射测试 | 构件→塔段→全塔逐级，不放进默认 unittest |
| E11 动力接口 | `test_wind_model_isolation.py`、`test_analysis_workflows.py`、真实残差相关测试 | 实际模态/风振另立长实验，不靠单测统计通过 |
| E12 准入/统计 | `test_sample_admission.py`、`test_fragility_admission.py`，新正式统计边界测试 | 先合成可核对概率/失败机制，再真实 cohort |
| 网页数据字段变化 | `test_dashboard_quality.py`、`test_results_dashboard.py`，必要真实浏览器 | 文档链接变动不必重复全部浏览器矩阵 |

最后合并共享代码、交付一个阶段门时统一运行一次 `.venv/bin/python -m unittest discover -s tests -v`，记录该次真实数量/耗时/日志；不能引用上一批 264 作为新代码测试结论。此前不要多个 agent 各跑同一整套。

## 9. 当前共享计划的过时点，供主 agent 更新

本角色没有修改下面共享文档，避免与主 agent 冲突：

1. `PLAN.md` 第 1 节仍写 53 项、部分已证事实“尚未证明”，第 2 节仍把配置/记录/网页等已完成能力当缺口；保留历史基线应显著标历史，并以本批结果为当前。
2. `PLAN.md` 第 8 节写全塔 CLI 没有 minimum-increment，现已支持；第 11 节/TASKS 的 `execution_default_batch` 仍从 T00～T04 开始。下一批不能照旧首批重做。
3. `HANDOFF.md` 顶部“当前下一步不是重写计划”属于上一批当时建议；用户本轮已明确要求后续规划，应新增当前规划入口，并保留旧段为历史。
4. T07 全任务仍含 aligned 全塔未做，但 T08 已有 legacy 子成果可用。后续依赖应引用 `T07.legacy_complete` 能力，不因 aligned 未跑阻断 legacy 差异定位；若主路线选 legacy，不为了清任务状态做无目的 aligned 长算例。aligned 是否必要须单列研究问题/理由。
5. T09/T10/T11 目前简单 done 依赖不能处理可信的不可辨识负结果；按 E02/E07 增加分组处理终态和条件依赖，不能仅把 blocked 改 done。
6. T10 报告 f274… 为 metadata 哈希，原 S2K 为 4ba541…；JSON provenance 本身正确，勘误不需要改冻结设计包哈希。
7. T20 的专属最终小模型测试在总回归已经收敛到 8/8；角色报告保留失败过程是合理的，当前摘要应链接最终集成结果，不能继续把历史中断当现状。
8. `fragility_curve/main.py` 的实际路径是 `fluctuate_wind_simulate/fragility_curve/main.py`。正式入口当前只导出准入，不自动正式概率拟合，应在后续 T22 计划中明确尚缺统计部分。

本轮计划交付的完成标准是后续 AI 能找到真实输入、分辨已有/拟建接口、按有限预算得到能推进或明确停止的证据；它不改变当前 G1 未过、A/B/C 未选或本轮 0 FE 的事实。
