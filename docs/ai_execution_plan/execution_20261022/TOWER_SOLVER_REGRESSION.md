# 新入口全塔数值回归：三组实际结果

任务T15。三组均为同一Z30103A6等效塔、同一旧标定库显式只读、控制350/DOF2、L/1000、种子30103及原九目标。
算法固定Newton→KrylovNewton→NewtonLineSearch(0.8)，NormDispIncr=1e-6、60次；不放宽容差、不改材料、不把877/878替换成弹性。

## 1. 实际步骤

1. 暴露完整实际生效数值设置，记录每次attempt的算法参数、迭代数、范数、前后进度、返回码及提交/试算标记。
2. 先用legacy最大/最小步复现旧停止，再只降低最小步重现旧fine完整结果。
3. 第三组只改成功后的步长恢复策略为gradual，每2次成功乘1.5，最高5mm；运行前设2000成功步/5000次尝试/900秒上限。
4. 全过程保存关键6杆与静力残差。比较时按原阶段和方向对齐，以共同覆盖区间积分，不外推缺失目标。
5. 相同CSV格式新增薄适配器，显式传入实际协议位移，保留重力终态和每段起点；3项专属测试通过。

## 2. 最后结果

| 配置 | 最大/最小步 mm | 恢复策略 | 完成目标 | 成功步/attempts | 停止位置 mm | 最终基底剪力 kN |
|---|---|---|---:|---:|---:|---:|
| solver_legacy_v1 | 5 / 0.3125 | legacy | 6/9 | 272/298 | -117.775 | -526.855 |
| solver_fine_v1 | 5 / 0.001220703125 | legacy | 9/9 | 590/646 | 0（回零） | 约0 |
| solver_gradual_v1 | 5 / 0.001220703125 | gradual | 6/9 | 277/320 | -117.627 | -526.196 |

gradual是因达到最小步长而停，不是因预算停止。完整协议原目标未变。

- legacy与旧停止记录一致；fine与旧fine的591行相对位移/基底剪力逐行最大差均为0。
- fine的最小实际成功步为0.0390625 mm，并没有用到配置下限0.0012207 mm。
- fine在原卡点附近先成功0.078125、0.0390625 mm，然后用KrylovNewton、27次迭代接受2.5 mm增量，再恢复5mm。
- gradual避免立即恢复5mm，但没有因此解决卡点，反而停在相近位置。因此不能宣称新恢复策略改善了本塔的完整收敛。
- fine对legacy原步长的共同协议覆盖68.5864%，共同区间RMSE=0。
- fine对gradual共同覆盖68.5892%，共同区间基底剪力RMSE=2.10e-5 N；这不包含gradual未走到的后续路径。
- 完整空间参考对fine的9阶段共同覆盖100%，全局剪力NRMSE=0.15945%。该全局指标不能掩盖局部杆力大误差。
- 三次计时分别约461.1、422.6、252.0秒；覆盖、attempt和并行资源不同，**不构成加速比**。

该对照直接证明结果对恢复策略敏感；尚未证明局部连续平衡分支、稳定性或哪种跳转更物理。
失败步检查只有引擎返回码与已提交进度一致性，不能等同逐一证明所有内部状态回滚。

![新四案例整体对照：标出未完成终点及验证范围](../../../initial_imperfection_material/results/followup/execution_20261022/tower_four_case_plot_v1/base_shear_displacement.png)

总图由现有 `load_saved_result` / `create_comparison_outputs` 只读四组新CSV生成，未重新求解、未排序往复位移；
大部分整体曲线重叠并不代表局部杆件响应相同，应结合下一节局部表及FULL_REFERENCE中的逐杆曲线阅读。

## 3. 共同-0.6%目标的局部失配依然存在

以下为新运行中同一阶段终点、完整全局端力在各自原杆轴方向的投影，压缩列取正。
它不是大变形后排除剪力的局部基本轴力，精确原始端力和基本变形均另存。

| 原杆 | 空间四段参考 kN | 等效fine kN | 压力相对参考偏差 |
|---|---:|---:|---:|
| 877 | 31.557 | 6.788 | 约-78.49% |
| 878 | 32.327 | 6.788 | 约-79.00% |
| 825 | 23.604 | 7.266 | 约-69.22% |
| 828 | 23.377 | 7.266 | 约-68.92% |

877的弦应变：参考-0.000653，等效-0.022123。前者来自真实空间杆变形，后者是等效构件响应；均不能直接当作钢材纤维应变。
这些是实际新记录的复核，不是把历史近似值重新当新计算。参考全幅网格尚未通过，数值精度问题见MECHANICS.md；
在已通过网格的前六目标限定域中，该差异仍远大于10%关键杆门槛。

## 4. 质量告警与结论

fine虽完成9/9，但第499步、target8首次出现877等效应变-0.03033354，超过其实际缓存下界-0.03。
清单准确保存 `out_of_range`、`out_of_calibration_range` 和 `eligible_for_fragility=false`。
旧库依赖身份无法核验，另保留 `legacy_unknown`，不会伪造成v2有效缓存。

结论：T15的旧配置回归、fine回归和恢复策略全塔对照已执行；gradual不是通过物理门槛的新推荐配置。
后续必须先解释参考/局部重放的强非线性路径和标定边界/截面耦合，不能仅以590步完成宣布材料适用于风振。

## 5. 复现入口与证据

三组命令公共项：

```sh
.venv/bin/python -m initial_imperfection_material.full_tower_cyclic \
  --model equivalent --output <新的结果目录> \
  --calibration-cache initial_imperfection_material/results/full_tower_cyclic/calibration_library.json \
  --allow-legacy-calibration-cache --local-members 825 828 877 878 917 920 --equilibrium-every 20
```

fine另加 `--minimum-increment 0.000001220703125`；gradual在fine上另加
`--recovery-policy gradual --maximum-accepted-steps 2000 --maximum-total-attempts 5000 --timeout-seconds 900`。
命令已经运行，不要为了交接再重复计算。

同格式CSV比较示例：

```sh
.venv/bin/python -m initial_imperfection_material.compare_runs \
  --reference initial_imperfection_material/results/followup/execution_20261022/solver_fine_v1/equivalent/cyclic_history.csv \
  --candidate initial_imperfection_material/results/followup/execution_20261022/solver_gradual_v1/equivalent/cyclic_history.csv \
  --tower-cyclic-targets 0.0364 -0.0364 0.1092 -0.1092 0.2184 -0.2184 0.364 -0.364 0 \
  --output <新的对比JSON文件>
```

- [三组对比目录](../../../initial_imperfection_material/results/followup/execution_20261022/solver_comparisons_v1)
- [fine清单](../../../initial_imperfection_material/results/followup/execution_20261022/solver_fine_v1/equivalent/run_manifest.json)
- [gradual清单](../../../initial_imperfection_material/results/followup/execution_20261022/solver_gradual_v1/equivalent/run_manifest.json)
- [legacy清单](../../../initial_imperfection_material/results/followup/execution_20261022/solver_legacy_v1/equivalent/run_manifest.json)

每个模型目录的 `attempts.jsonl` 保存全部尝试，`member_states.jsonl`只保存已提交历程；两者不能混用。
