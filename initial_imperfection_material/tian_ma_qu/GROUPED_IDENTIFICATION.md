# 真实有序历史后的分阶段识别

本模块是严格物理识别入口；此前 `parameter_identification.py` 保留用于显式合成数据检验和标量特征识别。**当前 Jain 公共数据只完成候选资料审计，尚未通过本入口准入；不得把测试中的人工数据视为实测结果。**

## 1. 整理完整历史

每件试件单独一份 JSON，基础格式使用 `otw2.tmq_ordered_history.v1`，由 `parameter_identification.ordered_data()` 校验：

- `data_kind: experiment`，真实文献/仪器来源 `source`、唯一 `specimen_id`。
- `ordered: true`、`ordering_evidence`；`samples[].sequence` 严格递增。数组保持原始顺序，位移允许反复。
- `elastic_modulus_Pa`、`yield_stress_Pa` 固定实测；`area_m2`、`length_m` 固定并注明量测/原文依据。不得把仪器、连接滑移或弯曲造成的构件柔度拟合进材料 E。
- `geometry_basis`、`material_property_basis` 和明确 `units`。位移支持 m/mm，力支持 N/kN/kip，拉力为正。
- 当前初态仅支持已确认的 `virgin_zero_load`，起始位移为 0，初始力在明确测量容差内。**未知预加载不能通过补零点或放大容差解决**。若做过有证据的仪器零点校正，另保留原文件、校正公式/原因、量值和不确定性。
- `force_resolution_N` 为正，来自仪器/数字化分辨率。不是用来让拟合通过的可调参数。
- 每个样本除 sequence、displacement、force 外，增加 `phase`。取 `first_compression`、`unload_reload`、`subsequent_compression`；其余完整历史可用 `validation_only`。`segment` 用于原有支路等权重，不能按点密度偷偷改变权重。

阶段应由加载记录或对照原报告后的循环编号界定。首压阶段从未加载状态进入压缩，必须覆盖内部峰值和至少两个下降点。当前实现一次选一段连续的首压、一次连续的后续压屈支；不把多次压屈曲线拼接成单调支。其它后续循环保留在完整预测中。

## 2. 明确证据审核字段

新增 `verification` 对象，必须包含 E、fy、geometry、boundary、displacement、initial_state、order、phases、group 九项，每项含：

```json
{"status": "verified", "source_reference": "报告名、页码/表号/原始文件及说明"}
```

额外要求：

- E、fy 项的 `basis` 为 `measured_coupon`。假定 200 GPa、规范名义 fy、仅数据库标签尚未核查的数值都不满足。
- order 的 `basis` 只能是 `instrument_sequence`、`author_sequence` 或 `curator_sequence_crosschecked`。没有时序的扫描图点集不满足。
- `group_key` 指向已复核的截面、杆长、连接/约束及试验配置组。当前组拟合还强制 E/fy/A/L 一致，不支持默默跨长细比共用 φ。
- `verified` 是人工依据真实证据作出的判断；代码只能审查声明的完整性，不能替代对原文/仪器记录的科学核验。

## 3. 先冻结方案，再拟合

计划 JSON 内容：

- `training`、`holdout`：各自非空的试件 JSON 相对路径列表。同一个 specimen_id 不能两边出现。
- `template`：完整 `TMQParameters` 参数表，E/fy 与实测输入一致；未识别参数要在 provenance 说明来源及假设。
- `stages` 按以下顺序排列，每项包含 `name` 和 `bounds`。每个 bounds 条目含 name、lower、upper，可含 scale=linear/log。
- `optimizer` 可含 seeds、population、generations、timeout_seconds。默认 3 个种子，真实编码 GA；另标记最小二乘细化。时间限制针对每个 GA；最小二乘受 100 次函数评价限制，不属于该 GA 时间限额。

| 顺序/name | 允许优化的系数 | 固定与适用条件 |
|---|---|---|
| 1 / first_compression | φ、α、β、γ | E/fy/A/L 永不优化；只有峰值不能识别两段下降斜率；γ 只在转折清楚时加入 |
| 2 / unload_reload | τ、μ、ν、ζ、ρ | 冻结首压系数；ρ 需要观察到拉伸塑性段；矩形边界保持 ν>μ |
| 3 / subsequent_compression | η、θ、κ | 冻结前两阶段；需要前次卸载/再加载和新的压屈下降支 |

不必把允许的所有参数都放入 bounds；无足够覆盖者保留明确先验。新增/删减参数与调整边界都属于变更计划，不能反复用留出曲线调参后再称独立验证。

每次目标函数均重放**整条原始历史**。mask 仅选择误差统计位置，不切断材料状态。训练试件等权，支路权重归一化，力误差按各试件完整观测的绝对峰值归一化。留出观测不参与目标函数。

## 4. 运行与验收

```sh
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.grouped_identification reviewed_plan.json --output /tmp/tmq-reviewed-group-01
```

运行前审查输入，保留冻结计划与全部 manifest 哈希。输出目录不得覆盖；优化失败记录 `failure.json`。输出包括各阶段 GA 轨迹、细化状态、模板和固定物理量、完整预测 CSV、训练/留出全曲线 NRMSE、局部 Jacobian 秩。

局部灵敏度秩不足时，返回 `nonidentifiable_stage` 并停止后续阶段；不将任意优化器数字发布为已确定最终参数。只有弹性段、没有分辨出的峰后支、缺少实测 E/fy、未知初态等会在拟合前拒绝。

`candidate_evaluated_not_automatically_validated` 仅表示候选拟合及留出评价执行完成。还需人工检查首/次压峰、卸载刚度、残余位移、完整回线、分支误差与力学机制；不能靠一个 NRMSE 将物理状态自动置为通过。当前没有断裂模型，完整末端断裂曲线若失配应如实呈现。

## 5. 本轮交付和下一项依赖

真实数据已取得 7 条、9560 点，网页保留完整记录及逐行查看。由于 Jain 原文券样表、初态和循环对应尚未核对，本轮未执行真实参数拟合；所有生产系数保留现状。

下一步先补齐原文证据或导入用户已有的可靠仪器历史，再指定训练/留出试件。若连接和杆长不匹配本塔，该组拟合成功仍不能直接迁移到 Z30103A6。

## 条件几何入口及实际批次

严格入口现在明确要求 geometry.basis=measured_specimen；若仅有原报告名义尺寸，可显式选择 evidence_policy=conditional_nominal_geometry，并提供 geometry.basis=reported_nominal 和 conditions。E/fy仍必须实测，顺序与初态检查仍保留。条件模式始终独立标记 strict_geometry_admitted=false。

[Carden实际批次](followup_results/carden_conditional_20261026/REPORT.md)已经使用这一入口。阶段目标只重放到最后一个评分点，完整此前历史全部保留；未来点不影响因果目标，完整历史另行评价。允许不超过明确绘图分辨率的位移反向量，不排序或平滑数据。
