# 雨谱与塔线雨荷载研究模块

本模块将雨滴粒径谱、雨滴速度、冲量和节点荷载分开，服务于后续雨影响研究。它不自动改变现有风荷载入口。

- [完整结果与复现报告](results/REPORT.md)
- [文献公式调查](../literature/rain_loading_investigation_20261102/README.md)
- [风雨通用节点加载接口与调用示例](../util/processing/NODAL_LOADS.md)
- [加载接口实际验证结果](results/loading_interface_verification.json)
- 网页：[雨谱与风雨荷载](http://localhost:9999/rain-loading/)

`physics.py` 实现原始/雨强闭合 M–P 谱、Atlas 终速、平板动量通量、杆线投影收集器、守恒节点映射、合成风速与泊松冲量检查。`tower_check.py` 在独立进程中对现有四分段 Steel02 塔施加重力、干风与雨滴冲击。`study.py` 汇总真实计算结果并生成网页图表。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m unittest tests.test_rain_loading -v
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m rain_loading.study
```

全塔结果已保存在 `results/runs/angle_0`、`angle_45`、`angle_90`。重新求解须选择新输出目录，已有算例不会被静默覆盖；具体命令见报告。

当前完成数值检查和全塔静力接入，尚未完成实测气象标定、湿态气动试验标定及塔线风雨耦合时程。导线是独立荷载映射，塔身角钢采用未校准的腿宽代理；原始杆两端集中力尚不能用于声称局部雨载弯矩准确。
