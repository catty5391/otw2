# N03 实际执行记录

本批只读取已有有限元状态；没有创建OpenSees域，没有调用特征值求解器，没有更新质量/材料/重力状态。

1. 读取计划N03、METHODS和建议验收值，检查已有CSV、float64振型、自由方程映射、K/M与纯风荷载函数。
2. 新建 `initial_imperfection_material/tian_ma_qu/wind_projection.py`。输出目录内先写`config.json`冻结风向、阶数/频带、2%相对或1 μm绝对误差门槛，再处理数据。
3. 运行第一版10项代数/荷载单元测试，通过。
4. 运行实际离线分析：

   ```bash
   OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.wind_projection \
     --output initial_imperfection_material/tian_ma_qu/followup_results/B1_20261024/wind_projection
   ```

   四个保存的K各做一次LU，求33组方向/荷载分量静态参考；六份历史同网格载荷重构一致。
5. 检查结果后增加主沿风/横风独立摘要、精确挂点误差表和绝对误差图；修正不同图中相同工况的颜色对应。代数、冻结门槛与载荷未改变。旧输出完整保存在`iterations/first_pass/`。
6. 以更新后的同一后处理入口重新执行离线矩阵分析并发布，最终源码指纹写入`source_fingerprints.json`。两次后处理合计8次K的LU；最终结果对应四个已有有限元状态，仍为0次新FE/特征值分析。
7. 新增保存证据检查，最终运行：

   ```bash
   OPENBLAS_NUM_THREADS=1 .venv/bin/python -m unittest tests.test_tmq_wind_projection -v
   ```

   **14项通过，0跳过**。日志为`validation/tests.log`，机器可读核验为`verification.json`。测试包括奇异质量/受力转动DOF、固定载荷排除、模态符号和次序不变性、近零绝对误差、各自网格重建、分布到节点力矩守恒、历史载荷交叉校验、固定/自由载荷总账、静态响应叠加和发表数值追溯。
8. 目视检查静态截断图和主向/横向响应图，保留SVG/PNG/PDF。后续网页集成由主agent完成。

## 重跑

该入口拒绝覆盖非空结果目录。重跑时提供一个新的输出目录；源`modal_results/runs`仍使用四个`*_checked`工况。输入指纹变化后应明确其影响，不覆盖旧证据。

## 结果与限制

40→80段的315条观察记录均满足冻结误差门槛；这些记录包含不同风向、荷载分量和坐标投影，**不是315个独立自由度**。
80段160阶对挂点沿风0°/45°的误差约14.17%/14.31%，尚不够；350节点对应误差约2.36%/0.876%。因此不能只看塔顶或有效质量比来接受模态截断。
最大3.67945m是参考荷载因子为1时的重力切线线性外推，不能解释为真实20m/s风下的非线性导线位移。
反力、塔杆内力和导线张力缺少独立恢复算子；本轮不据位移收敛声称这些量已收敛。所有动力/阻尼/物理验证仍未完成。
