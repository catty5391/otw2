# 全塔参考边界采集：步骤与结果

本报告对应 T07 的 legacy 四分段完整协议。它是新的实算证据，不是旧 CSV 的复制，也不是新的材料已通过验证。

## 执行步骤

1. 保留 `results/full_tower_cyclic` 和 `results/convergence_diagnosis`，新结果另存 `results/followup/execution_20261022/reference_legacy_v1`。
2. 不改变物理参数：Z30103A6、控制节点 350/DOF2、L/1000、种子30103、四段、原九个漂移目标、原算法序列及容差。
3. 从未加载状态开始，记录初始、10个重力提交步、每段起点及所有成功循环步；记录825/828/877/878/917/920两端6DOF、分点坐标、端力、积分点和纤维极值。
4. 每20个成功步及每个目标终点，按完整重力/风荷载账本组装自由DOF静力残差；失败后保存已提交状态并停止，不声称能撤销已提交状态。
5. 完成后比较新旧完整整体历程，再用 `summarize_member_states` 输出逐杆表、名义阈值事件及图。

```sh
.venv/bin/python -m initial_imperfection_material.full_tower_cyclic \
  --model segmented_reference \
  --output initial_imperfection_material/results/followup/execution_20261022/reference_legacy_v1 \
  --local-members 825 828 877 878 917 920 --equilibrium-every 20

.venv/bin/python -m initial_imperfection_material.summarize_member_states \
  --history initial_imperfection_material/results/followup/execution_20261022/reference_legacy_v1/segmented_reference/member_states.jsonl \
  --output initial_imperfection_material/results/followup/execution_20261022/reference_full_truth_v1
```

结果目录非空时入口拒绝覆盖。重跑应另用新目录。

## 整体结果与记录影响

- 清单 `status=completed`，9/9目标、587循环成功步；包含阶段起点和重力的局部记录为607条。
- 正/负基底剪力极值：+1624.773/-1616.492 kN；最终回到原端距后基底剪力+3.897 kN。
- 新旧整体 CSV 均588行。逐行对比相对控制位移、基底剪力、风荷载因子，最大绝对差均为0；本轮记录没有改变原整体响应。
- 591次分析尝试中4次失败，算法回退后完成；不能把日志中的单次失败当作最终不收敛。
- 39次残差检查全部通过。最大平动残差0.002269 N、转动残差0.000758 N·m；最大相对平动残差1.333e-9、转动1.224e-11。检查不是每一步，未检查步骤不能声称有独立残差认证。
- 求解计时3323.97秒，包括本轮记录开销且存在并行任务；不用于论文加速比。

## 关键杆完整历程

| 杆号 | 原始轴投影最大压力 kN | 最大绝对纤维应变 | 最大弦线侧弯 mm | 最大应力/fy |
|---|---:|---:|---:|---:|
| 877 | 50.597 | 0.058370 | 116.602 | 2.5554 |
| 878 | 52.391 | 0.057433 | 112.421 | 2.5302 |
| 825 | 30.645 | 0.002975 | 29.006 | 1.0691 |
| 828 | 31.594 | 0.003024 | 28.737 | 1.0704 |
| 917 | 21.858 | 0.000769 | 3.623 | 0.6860 |
| 920 | 22.024 | 0.000702 | 3.388 | 0.6268 |

这些是原四段模型在完整空间端部约束中的响应，不是铰接压杆的轴向推覆结果。力列为全局端力在原始杆轴的投影，
并非将大变形后的剪力贡献排除后的局部基本轴力；原始完整端力/基本变形另存，后续分析应按用途选择。
不同应力/应变极值可能来自不同纤维/时刻，不能将两列直接配对为某一纤维本构。

- 前六个目标（±0.1%、±0.3%、±0.6%）六根杆均未跨越名义fy标记；这不等于Steel02平滑过渡过程严格可逆。
- 877/878在第7目标（+1%）首次达到名义应力fy，源循环步分别354/357。
- 825/828在第8目标（-1%）才首次达到fy，源循环步498/502。
- 917/920在本完整协议中未达到该名义标记。
- 名义应变fy/E的首次跨越可能早于名义应力fy；这是两种观测标记，不应混称唯一的Steel02塑性屈服点。
- 后半段877/878的侧弯及纤维应变明显放大。四段的这些大变形数值仍需完整T08网格/纤维检查；不能把大应变自动认作已经验证的断裂或倒塌。

## 功与质量状态

完整加载DOF的循环外功为4291.921 J；这里只包括完成重力后的循环段，重力预加载功未计入。
基底剪力—塔顶位移图面积为3835.174 J；它不是同一个共轭功，二者均不能直接称为滞回耗能。
最终外力/位移及内部状态没有证明闭合。

运行完成状态与力学验证分别保存：本次清单仍为 `validation_status=unvalidated`、`domain_status=unknown`、`eligible_for_fragility=false`。
T07的legacy采集与原结果复现已完成；aligned配置的另一次全塔参考尚未执行，完整参考精度须接T08，不能提前把G1/G4标为通过。

## 结果位置与读取

- [运行清单](../../../initial_imperfection_material/results/followup/execution_20261022/reference_legacy_v1/segmented_reference/run_manifest.json)
- [逐杆真值表](../../../initial_imperfection_material/results/followup/execution_20261022/reference_full_truth_v1/local_response_truth_table.csv)
- [事件表](../../../initial_imperfection_material/results/followup/execution_20261022/reference_full_truth_v1/reference_events.csv)
- [局部曲线图](../../../initial_imperfection_material/results/followup/execution_20261022/reference_full_truth_v1/local_reference_response.png)

仓库根目录读取示例（只读、逐条，不把全历程展开进内存）：

```python
from pathlib import Path
from util.processing.member_state_recorder import iter_member_states

history = Path("initial_imperfection_material/results/followup/execution_20261022/reference_legacy_v1/segmented_reference/member_states.jsonl")
for state in iter_member_states(history):
    member = next(m for m in state["members"] if m["original_member_id"] == 877)
    print(state["stage_id"], state["source_step"], member["chord_strain"])
```

`source_step`是原全塔循环步编号；`accepted_step`是本地记录序号，包含重力和阶段起点；准静力domain time不是物理秒。
