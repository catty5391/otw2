# Steel02 分段初弯曲与 TMQ 对比

独立单杆实验；不修改全塔模型或已发布参数。文献整理于
[`literature/opensees_segmented_steel02_20261028/`](../../literature/opensees_segmented_steel02_20261028/README.md)。

实际Z30103A6杆349：L125×8Q345、L=1.602379m；另有3m长杆演示。
统一E=210GPa、fy=345MPa、b=0.03、A=1936mm²，两端铰接、弱轴平面。
Steel02采用纤维梁、Corotational与半正弦初弯曲；TMQ采用当前塔参数映射，未拟合本次参考曲线。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.steel02_tmq_comparison.experiment
.venv/bin/python -m unittest tests.test_steel02_tmq_comparison -v
```

46个工况：单调/循环/弹性回零、4/8/16/32段、缺陷幅值与形状、forceBeamColumn补充、16段单调步长减半。
`results/REPORT.md`包含具体步骤和结果；`results/runs/`记录每个成功子步及所有求解尝试。
HTTP入口：`http://localhost:9999/steel02-tmq/`。

所有误差按有序共同历史比较，提前停止不能算作完整验证。
几何非线性平面纤维模型不包含角钢局部屈曲、弯扭屈曲、连接滑移或断裂。
运行时间含响应查询，不能直接当作全塔加速比。
