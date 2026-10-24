# T04与全塔集成：步骤和结果

本工作线由主agent负责，避免与力学、缓存、质量、求解和网页五个角色同时修改全塔入口。

## 已执行步骤

1. 保留原12分量内力SQLite及查询接口，新增旁挂`member_states.jsonl`与静态metadata。旧数据库读者改用SQLite只读模式。
2. 新记录器按原物理杆聚合分段，明确原节点、分段节点、全局6DOF、初始/当前弦长、各段局部与全局端力、基本变形。
3. 对所选杆每个积分点查询全部离散纤维，保存应力/应变极值及所在纤维坐标、探测数量与缺失状态；Aggregator不冒充Fiber。
4. 在全塔入口接入初始无荷载状态、全部10个重力成功步、每阶段起点和每个成功子步；失败试算单独进入attempts日志。
5. 记录stage_id、cycle_id、direction、stage_progress和source_step/accepted_step。准静力domain_time只作协议状态，不宣称真实秒。
6. 修复无共同完成目标、无共同物理杆时后处理索引空表的问题。
7. 第4agent提供按阶段/方向/进度的通用比较，原硬编码诊断脚本继续保留历史用途，见SOLVER_RECORDS.md。
8. 新增事件/阶段可选的刚度探针。真实PythonSparse小体系检验了探针前后物理状态与下一成功步完全一致；能力缺失与探针错误分别报告。
9. 接入真实自由DOF平衡检查，完整台账包含当前因子的重力与分布风荷载；平动N、转动N·m分开。检查失败先保存已提交状态并终止，不能假装回滚重试。
10. 逐加载自由度保存F/u并计算有符号外功；明确其范围从重力完成开始，包含循环中的重力功，不包含此前重力预加载过程的功。旧Vbase–utop面积保留兼容键并明确命名。
11. 全塔新CLI暴露最小步长、容差/迭代数、算法组合、步长恢复策略和资源上限。清单同时保存实际stepper设置和缓存/源码依赖。
12. 默认新运行拒绝非空输出目录；旧v1骨架仅显式授权只读。等效模型逐杆按实际组上下界检查范围，数值完成和验证状态分开。

## 实际验证

- `test_member_state_recorder.py`最初7项通过：真实3D纤维梁应力、6DOF、读操作不改状态及下一步、trial隔离、缺历史、输出保护、空共同目标、严格回退异常恢复。
- 新增全塔循环控制器的步长恢复回归：受限步长弹簧中，legacy/last_success/gradual均到同一目标，后两者减少重复失败；实际结果以末次集成日志为准。
- `test_diagnostic_probe.py`3/3通过：实际稀疏刚度最小特征值38.196601125、开启探针不改变下一步、能力缺失明确、选择不写死旧杆号/步号。
- 原内力数据库读写/窗口/包络测试继续回归。
- 全塔记录冒烟完成±1e-5漂移并回零：3/3目标、3成功步；6根关键杆共17条局部提交记录（含initial、10步重力和阶段起点）。
- 两根真实塔杆同网格边界重放、小幅10/20子步及共同平移处理的结果见MECHANICS.md。
- 新增局部状态汇总器，已对完成的冒烟运行生成6杆真值表、标称fy阈值事件和局部曲线。该小幅运行没有标称fy事件，不能据此推断±1%响应。

第一轮全仓库集成116/116通过；第二轮172/172通过、75.924秒。仍有后续改动，最终统计以最终日志为准。

## 已存在的入口

```bash
.venv/bin/python -m initial_imperfection_material.full_tower_cyclic --help

.venv/bin/python -m initial_imperfection_material.full_tower_cyclic \
  --model segmented_reference --output <新目录> \
  --local-members 825 828 877 878 917 920 --equilibrium-every 20

.venv/bin/python -m initial_imperfection_material.summarize_member_states \
  --history <完成运行>/member_states.jsonl --output <新汇总目录>

.venv/bin/python -m initial_imperfection_material.compare_runs --help
```

已经完成的`recorder_smoke_v1`不能覆盖；复算必须换新目录。完整参考`reference_legacy_v1`由主agent运行，最终状态见其run_manifest，不用本报告中的进度替代最终结果。

## 完整前缀的定义

为避免等待高幅阶段时局部工作空转，可在某个目标完全提交后导出包含initial、完整gravity和全部前序目标的独立前缀。
`export_protocol_prefix`核对每阶段从0到1、完整重力、原始行和输入指纹，派生清单只声明所选目标数量，父运行状态与9目标覆盖保持原样。
这是原始已提交历史的导出，不在非线性中间状态重新建模；后续试件仍从初始态重放。结论只适用于该前缀，不能冒充完整±1%通过。

## 适用范围与待核对项

详细纤维默认只对关键杆开启；整塔所有分量内力仍由原SQLite提供。记录器不推断未测局部塑性、不由应变越界自动判倒塌。
刚度探针需当前引擎实际支持PythonSparse；要求的探针失败会保存报告并停止该运行。
静力真实残差的前提是完整节点荷载账和明确约束；动态需显式惯性/阻尼账，不能拿静力方法直接用于风振。
新步长恢复策略的物理路径敏感性仍须同模型完整协议比较；软件回归不替代这项验收。
