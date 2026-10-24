# T20 动力入口工程准备：步骤、结果与剩余门槛

批次：`execution_20261022`；执行角色：第 4 执行 agent 的后续任务。
本次只完成独立建域、初始化接口、控制参数和记录能力适配，以及真实小模型验证。
没有启动全塔风振或 70 样本扫描，没有修改普通塔模型的默认材料、质量、重力或阻尼参数。
T20 的全塔物理验收仍须依赖 T18/G4 与本报告第 6 节的证据，不能把工程适配完成登记成 G5 已通过。

## 1. 实际改动与执行步骤

1. 完整阅读 T20 和现有 `wind_refactor_common.py`，核对风输入预检查、运行清单、漂移记录器、内力数据库、ForceControl 和已有 workflow 测试。
2. 确认旧批处理只建一次普通塔，并在各样本前执行 `ops.reset()`，无法证明材料、重力、荷载和初态完全独立；同时确认节点 370/DOF2 与固定 Fiber 探针被写死。
3. 将 `run_sample_batch` 改为逐样本调用 factory，每次清域后重建；保留默认普通 `OpenSeesModel` 的物理参数。
4. 在 `run_one_sample` 增加 `model_factory` 和 `initialize_model` 注入接口；禁止同时传现成 model 与 factory。
5. 把初始化职责明确交给回调：重力、`loadConst`、阻尼、质量声明和来源均可返回元数据。没有证据的字段显式 `unknown`。
6. 取消无条件 `ops.reset()` 和 `setTime(0)`。现成外部模型保留其已提交状态，并显式标记 `external_legacy_model / caller_managed_unknown`，不能自动宣称样本隔离。
7. 对非零初始域时间，把 Path 风时程起点移到当前时间，推进目标为 `t_start + elapsed`；同时记录实际模型时间和真实瞬态历时的对应关系。新增相位测试还发现默认 Path 最后点索引可能归零的问题，显式 `-useLast` 保持最后记录值；分析终点仍严格为输入终点，不延长时域。
8. 参数化控制节点、控制 DOF 和风加载 DOF，验证存在性；Node 位移/速度/加速度记录器使用实际控制参数。
9. 采用按节点实际 NDF 创建的风节点力向量，保留原来“楼层总力均分到节点”的规则；重力已有 pattern 不移除。
10. 使用独立风荷载 tag 段，并允许初始化回调声明保留的时间序列/荷载起始 tag。加载创建途中若异常，撤销本次已创建的 wind pattern/timeSeries，保留原 pattern。
11. 删除默认固定 `fiber(-0.05,1)` 查询，改为按引擎能力记录 section 1 的广义力/广义变形。不支持 section 的单元明确标 `unsupported`，内力数据库仍按原接口工作。
12. Aggregator 的变形语义明确写为整构件等效广义变形，不能作为钢材 Fiber 应变。旧普通 Fiber 探针只有显式开关才启用，并记录未验证探针警告；Aggregator 会拒绝该选项。
13. 增加进程内域互斥保护，同进程多线程共享 OpenSees 域时立即拒绝。原 ProcessPool 的进程隔离方式保持。
14. 新样本输出目录若已有 `run_manifest.json` 则拒绝覆盖；通过新 `output_root` 创建独立实验批次。
15. 新增真实非线性弹簧、Aggregator 梁、预加载和时间偏移测试；测试输入与输出均在独立临时目录，不读取或改写已有全塔风振成果。

本角色独占修改：`fluctuate_wind_simulate/opensees_simulate/wind_refactor_common.py`、新增 `tests/test_wind_model_isolation.py`。
没有修改 `test_analysis_workflows.py`，避免与其他执行角色的易损性准入回归冲突。

## 2. 可用接口

```python
from fluctuate_wind_simulate.opensees_simulate.wind_refactor_common import run_one_sample, run_sample_batch

def model_factory():
    # 上层已 wipe；这里创建完整、独立的域并返回带 element_map 的模型。
    return build_frozen_model()

def initialize(model):
    apply_and_complete_gravity(model)
    freeze_gravity_for_transient(model)
    apply_documented_damping(model)
    return {
        "initialization": "frozen_init_v1",
        "gravity": {"status": "completed", "source": "specified gravity configuration"},
        "damping": {"type": "specified", "source": "documented coefficients"},
        "mass": {"type": "specified", "source": "frozen mass ledger"},
    }

result = run_one_sample(
    sample_id, speed_name, sample_name, sample_dir, floor_to_nodes,
    model_factory=model_factory,
    initialize_model=initialize,
    model_declaration={"model_family": "segmented_reference"},
    control_node=actual_node_tag,
    control_dof=2,
    wind_load_dof=2,
    output_root=new_output_root,
    drift_node_config=actual_drift_floor_config,
)
```

示例中的建模、重力和阻尼函数是调用方提供的工作流，并非本次新增的通用全塔物理配置。
`run_sample_batch(samples, model_factory=..., initialize_model=..., node_config=..., **options)` 同样支持这些参数。
老代码不传 factory 时，仍使用普通塔，逐样本重新建立；传 `model=` 的旧接口保留，但其独立性由调用者负责。

可选项：`drift_enabled=False` 可用于无楼层含义的小模型；普通塔默认仍保留原漂移计算。
控制节点参数化没有改写原漂移算法：启用时，漂移仍按原全局 Y 平动 DOF2、绕 X 转动 DOF4 和实际楼层配置计算，并在清单记录。
对其他方向的物理漂移定义应另建经过核对的适配，不能只换 control_dof 就假定漂移方向一起改变。

## 3. 记录语义与能力边界

- `model_adapter` 进入 run manifest 和返回结果：包含模型族、实际类、域来源、factory、初始化/重力/阻尼/质量声明、实际控制信息、风加载 tags 和截面响应能力计数。
- `section_responses.jsonl` 保存初始已提交状态及所有成功自适应子步；记录 `time`、`elapsed_time_s`、广义力、广义变形和不支持的单元列表。
- section 记录当前只取积分点 1，不代表所有积分点/纤维包络；内力库仍覆盖其原支持的全部选定塔单元。
- `equivalent_component_generalized_deformation_not_steel_fiber_strain` 明确禁止把等效轴向缩短直接当钢材 Fiber 应变。
- Node 原文件和内力数据库使用域时间；真实瞬态历时为 `domain_time - transient_start_time`。初始化阶段的域时间可能是静力伪时间，不能连同预加载一起解释为真实秒。
- 本次没有擅自施加默认重力、Rayleigh 阻尼或新的质量；未声明字段保持 `unknown`，`physical_validation` 保持 `unvalidated`。
- OpenSees 没有当前可用的全部 timeSeries tag 查询接口；默认 wind 从高 tag 段开始，并由调用者在复杂初始化时用 `wind_time_series_start / wind_pattern_start` 明确避开自定义保留范围。碰撞会报错，不会覆盖旧时间序列。
- 时程端点行为有显式修正：Path 使用 `-useLast`，输入最后记录值不因恰好落在末索引或浮点偏差变成零。历史默认实现可能在最后一步给零荷载，因此旧输出的末点不一定与修正后逐点相同；该变化不涉及材料、质量或阻尼参数，且已进入元数据。

## 4. 真实测试与结果口径

新增测试覆盖以下 8 项；最终运行状态和原始输出见本批次测试日志：

| 验证项 | 实际测试方式与验收 |
|---|---|
| A→B 与单独 B、B→A 与单独 A | 真实 Steel01 非线性弹簧，A 足以越过其 0.5 mm 屈服位移；6 次 factory 创建，逐时刻位移比较到 12 位小数 |
| 初始化回调保留预加载 | 真实弹性弹簧预载 0.4 N，位移 0.4 mm；域时间保留 1，后续 0.03 s 零风保持该状态，原 pattern7 保留 |
| 外部 legacy model | 已预加载的模型传入后初始位移保留，独立性和未声明重力来源明确 unknown |
| 非零起始时间的风序列相位 | 同一零状态/同一风历程分别从 0 与 2 开始，响应相同而记录时间差 2 s |
| Aggregator 梁记录能力 | 真实空间 Aggregator 梁；所有 eleResponse 调用没有 Fiber 查询；广义力/变形确有数值，语义不是钢材应变 |
| 自适应成功子步 | 3 个名义时间步，每步显式分半；初始+6 成功子步共 7 点，实际时间为 0、0.005、…、0.03 s，section 与内力库一致 |
| 不支持输入/并发/固定 Fiber | 无效控制节点、共享域线程进入、Aggregator 固定 Fiber 选项分别拒绝；锁正确释放 |
| 荷载创建失败清理 | 实际创建 Path/pattern 后注入 load 异常，本次资源被删除，原 pattern7 保留，被移除 timeSeries tag 可重新使用 |

最初使用 zeroLength 弹簧夹具时发现，其 `localForce` 是 1 分量，不能满足既有塔内力库的 12 分量契约；因此最终测试改为有完整端力的真实 `twoNodeLink` 弹簧，没有修改内力库或制造虚构的其余分量。

首次完整 8 项运行实际为 **7 通过、1 失败**：新增非零起始时间测试发现，相同输入仅把域起点从 0 改为 2，最后位移出现 `2.4391e-5 m` 差值。
差值约等于该小模型平均加速度 Newmark 的 `1/(4m/dt^2+k)=1/41000 m/N`，支持“最后一步外载相差约 1 N”的定位；按这个明确假设增加 `-useLast`，而非调整模型参数或降低测试精度。
该失败证据单独保留，修正后的焦点测试与最终全套结果分别记录，不能把修正前 7/8 改写成全部通过。
- [8 项运行的失败终态证据](../../../initial_imperfection_material/results/followup/execution_20261022/wind_adapter/new_tests_before_endpoint_fix.log)

修正 `-useLast` 后，仅针对该机制重跑焦点用例，实际 **1/1 通过**，保留相同 12 位小数精度要求；最终代码的完整 8 项及全仓集成留给主 agent 统一串行，不为凑完整通过数字重复竞争资源。
- [端点修正后焦点测试原始输出](../../../initial_imperfection_material/results/followup/execution_20261022/wind_adapter/endpoint_focus_after_fix.log)
- [机器可读能力、数值检查与未完成门槛](../../../initial_imperfection_material/results/followup/execution_20261022/wind_adapter/verification.json)

已有 `test_analysis_workflows.py` 的 5 项回归用于确认普通入口、小弹簧瞬态、风分析失败清单及数据库关闭行为仍正常。
本任务不修改易损性回归的准入逻辑，该部分由另一执行角色负责。

## 5. 复现命令

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_wind_model_isolation.py' -v

.venv/bin/python -m unittest discover -s tests -p 'test_analysis_workflows.py' -v

.venv/bin/python -m unittest discover -s tests -p 'test_wind_model_isolation.py' -k nonzero_start -v
# 端点修正后的焦点复算：1 test, OK
```

测试创建并清理自己的临时目录；不会批量运行现有风样本。
首次 6 项隔离测试与当时的既有 5 项 workflow 回归已经通过；随后补充非零时间相位与荷载失败资源清理两项，再做最终隔离测试，最终状态以附加日志为准。
末轮重复 workflow 回归因共享环境资源竞争，由主 agent 统一调度：只读核对本角色进程 PID3020365 后发送 SIGINT 中断，保留独有新测试继续执行。该运行以 130 退出：静力反复、恒力振子、风入口三项显示通过，最后风失败处理测试在写清单时被中断。
此外开头的易损性提取测试已显示 ERROR，但尚未输出该项 traceback 就被中断；这一项不能归因于本次 SIGINT，也不能宣称末轮 5/5。已通知主 agent 在其他角色的准入修改冻结后重点核对，最终串行全仓测试作为集成结论。
- [重复 workflow 回归的终态片段与调度原因](../../../initial_imperfection_material/results/followup/execution_20261022/wind_adapter/workflow_recheck_interrupted.log)

## 6. T20 仍未完成的物理门槛

1. 等待 T18/G4 通过后，冻结实际用于动力的参考/混合模型政策；本入口本身不会把普通模型变成已验证的新材料塔。
2. 核对全塔总质量、楼层分布、单元与节点质量是否重复、转动自由度处理及导线参与方式。
3. 核对实际重力初始化、几何/材料已提交状态及重力荷载冻结方式；对生产初始化做可重复状态检查。
4. 完成实际塔的模态配对、目标频率误差和 MAC，不能用小弹簧的顺序独立替代。
5. 冻结阻尼来源、系数、采用初始/当前/已提交刚度的具体方式，并检查软化负切线附近阻尼的物理影响。
6. 把 T05 真实动力残差工具接入完整且有来源的实际塔 `M a / C v` 台账；未知的单元一致质量和阻尼不能猜测。
7. 在实际塔上做小幅瞬态/线性响应对照、时间步减半与关键杆状态检查，达到计划中的 G5 门槛。
8. 核对实际风荷载单位、方向、平均/脉动分量、空间相干和时间基准，然后按 T21 先单例、再受控小批；没有自动授权据此直接全扫 70 样本。
9. 如需推广到全局 X/其他方向，单独验证漂移指标和坐标变换；当前原漂移器的 Y/X 转角约定保持不变。

因此，本报告支持将 T20 登记为“工程适配与小模型验证已完成、全塔物理验收未完成”，不支持标记整项或 G5 完成。
