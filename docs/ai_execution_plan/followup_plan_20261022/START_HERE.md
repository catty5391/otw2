# 下一批执行入口

下面的提示对应用户后续要求“按新计划执行”时的建议首批。本次已完成的是规划，尚未启动这些实现或有限元试验。

> 在 `/home/panqiheng/otw2` 继续Z30103A6任务。先读本目录README、NEXT_TASKS和两个详细分计划，再读上一批RESULTS与MECHANICS的相关证据。
> 本批完成F00～F03：证据身份与预算、877已有档案只读差异定位、全塔近直线/六杆屈服事件联合图、同物理点纤维精度、来源字节核验及负结果选路契约。
> 如沿用两个agent，力学负责差异/纤维，工程负责证据/门控；主agent负责共享文件及集成，不继续扩agent。没有并行授权时单agent做同样工作。
>
> 工作区含未提交源码和未跟踪结果，不能reset或仅凭HEAD重建。保护旧结果及上一批execution_20261022；新产物放独立的新批次目录，输出非空则拒绝覆盖。
> 原TASKS的9 done/6 blocked/2 in_progress/8 planned保持事实；本批只更新有真实验收的对应内容。不要从T00重新跑53项基线，不要把历史264项当本轮测试。
>
> 首先回查877父accepted_step524、529→530与父source_step506、511→512的映射。局部archive的source_step指父accepted_step；父JSONL的source_step才是原塔循环步。
> 检查所有历史阶段，不把窗口截取当作非线性初态恢复。已有记录没有完整Steel02历史变量，紧凑子步缺某些截面量；缺失量标unknown，不反推伪造。
> 不再跑877已有三组全幅方案，不重算587步参考。先给差异定位表、可观测/不可观测清单与下一试验的可区分假设。F04/F05须有证据触发后才继续。
>
> 同时回应曲线问题：完整参考/fine停止于预定±1%再回零，并非末点不收敛；原步长等效才6/9失败。参考整体偏离初始直线最多约峰值的0.576%，但监测六杆中的四根已跨名义fy。不要称全塔都弹性，也不要声称已得到整塔峰后。
> 将独立单调推覆保留为F13任务，从初态+重力出发；不把往复结果排序拼接、不任意增大加载去追求图像形状。
>
> 工程侧规划/实现参考诊断与候选标定的分离契约。T09不适用可形成T11排除A的证据，不能要求先标定成功；但新诊断模式不能绕过物理G1向候选/正式结果发放通过状态。旧绑定接口测试继续通过。
> source S2K的SHA256为4ba541…；f274ce…是历史member_metadata文件，规范化设计hash与文件字节hash也分开。复制待绑定模板不代表获得真实证据。
>
> 首批结束交付步骤、结果、测试、限定结论和F04是否必要的决定。若有新代码跑对应单测与最后集成回归；若仅只读后处理，只检查指标/来源/不覆盖行为，不重跑FE。保留9999服务。

## 可用的只读命令

从仓库根运行。以下是现有接口，均不启动FE求解；计划中的新比较/导出接口尚不存在，不提供可执行的虚构命令。

```sh
git status --short
git branch --show-current
git rev-parse HEAD
sha256sum Source/Z30103A6.s2k
sha256sum initial_imperfection_material/results/convergence_diagnosis/fine_sparse/member_metadata.json
.venv/bin/python -m initial_imperfection_material.cyclic_protocol_contract
.venv/bin/python -m initial_imperfection_material.member_reference_3d --help
.venv/bin/python -m initial_imperfection_material.full_tower_cyclic --help
```

设计契约CLI返回16个设计用例，不表示16个算例已运行或已绑定；目前绑定模板拒绝是预期行为。

旧保护目录的只读核验可使用已有命令，但该命令只核查旧97项和当时归档，不自动涵盖上一批所有新followup证据：

```sh
.venv/bin/python -m util.analysis.baseline_snapshot \
  --root /home/panqiheng/otw2 \
  --verify docs/ai_execution_plan/execution_20261022/baseline/baseline_inventory.json
```

新批次须增量登记所消费的followup清单/源文件指纹；不回写旧基线。对于SQLite，主体及WAL严格核查，SHM读锁变化按既有规则单独报告。

## 新输出应具备的内容

- `batch_manifest.json`：实际运行UUID、源码/输入/父证据指纹、单位、坐标和预算。
- `record_index_map.csv`、`first_divergence.csv`：真实映射和首差异，不按固定偏移猜步号。
- `global_local_diagnostics.png`：全局图、偏离初始线、局部事件以及记录覆盖声明。
- `fiber_same_point_review.json`：可同点比较的量、缺失的材料历史、判据与误差。
- `next_case_decision.json`：下一试验唯一假设/配置、触发依据、预算或不开展理由。
- `REPORT.md`、测试日志与任务状态：明确实际执行结果，不把拟建文件列为已产生。

上述文件名为建议交付契约，**当前并不存在这些下一批结果**。实施者可按既有模块风格调整，须在清单登记真实路径。
