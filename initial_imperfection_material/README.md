# 等效初始缺陷材料：单杆试验模块

本目录是一个与全塔模型隔离的实验区，用 `L125x8Q345` 角钢验证“等效杆件屈曲本构”能否重构收敛后的分段几何初弯曲模型。

默认材料载体为可逆的 `ElasticMultiLinear`，用于正确恢复屈服前的几何弹性变形；旧 `HystereticSM` 载体仅在卸载验收中作为反例保留。默认参考模型为 16 段 `dispBeamColumn + Legendre-6`，并与全塔统一采用 `E=210 GPa、Steel02 b=0.03`。

运行默认试验：

```bash
uv run python -m initial_imperfection_material.run_experiment
```

改变杆长、初弯曲和结果目录：

```bash
uv run python -m initial_imperfection_material.run_experiment \
  --length 3.0 \
  --imperfection-ratio 0.001 \
  --steps 800 \
  --reference-divisions 16 \
  --output /tmp/imperfection-result
```

输出包括推覆曲线、屈服前压缩—卸载、分段/步长收敛、实际塔杆验证、材料骨架和缺陷敏感性图，以及全部 CSV 与汇总 JSON。理论、实现方法、修订结果及使用边界见 [REPORT.md](REPORT.md)。

运行 Z30103A6 全塔准静力往复对照：

```bash
uv run python -m initial_imperfection_material.full_tower_cyclic
```

全塔接入方法、加载协议、内力数据库和正式结果见
[FULL_TOWER_CYCLIC_REPORT.md](FULL_TOWER_CYCLIC_REPORT.md)。

−117.775 mm 停止点的定位、缩步后完整循环及局部误差见
[CONVERGENCE_DIAGNOSIS.md](CONVERGENCE_DIAGNOSIS.md)：877、878 号杆的下降段回程触发
局部分支跳转；数值可跑通，但局部轴力与参考明显不同，且 ±1% 协议中已超出部分骨架标定范围。

下一阶段的详细实施顺序、参考验证、材料/混合模型路线、测试与交付要求见
[后续 AI 执行任务包](../docs/ai_execution_plan/README.md)。建议先完成T00～T04基础审计与记录，
再开展真实边界重放；任务包中的新模块均为拟建内容。

注意：一个等效材料实例只对应一根具有确定 `L、K、A、I、fy` 的原始物理杆件。应用该材料时不得再次给同一杆件施加几何初弯曲，也不得把原杆分段后按每段长度重复计算材料。
