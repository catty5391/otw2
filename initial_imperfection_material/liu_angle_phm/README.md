# 刘俊才角钢 PHM 形式的解析曲线实验模块

这个独立模块实现压屈后指数曲线、反向拉伸的有理恢复曲线、解析切线与历史相关压峰，并通过已有 C++ 桥接执行 OpenSees 单杆平衡。原有折线 TMQ 和全塔参数没有替换。

主参考为用户提供的 Liu et al., *Thin-Walled Structures* 183 (2023) 110335，式(3)–(15)。[出版社入口](https://www.sciencedirect.com/science/article/abs/pii/S0263823122008874)。本模块包含压缩符号解释、H/I闭合和小反转等项目补充规则，**不能称原作者 VUMAT 的完整复现或已经验证的工程材料**。

- [改写、公式、拟合与结果报告](results/REPORT.md)
- [9999 完整展示](http://localhost:9999/liu-phm/results/index.html)
- `material.py`：真实应力、解析切线、trial/commit/revert/copy；没有通过平滑画图替代本构。
- `experiment.py`：Carden P 真实有序分支拟合、完整人工协议、实际 OpenSees 对照、真实历史范围检查。
- `publication.py`：完整曲线、拟合残差、论文回归曲线和有限预测范围的图表。

当前结果：1980步人工协议全部完成；压后同段同峰、同为3参数时，曲线 NRMSE=1.62%、折线=1.47%。曲线渐近应力触界，恢复段秩不足；P/Q完整实测路径的预测会触发范围限制。数值接口通过与实验验证未通过分别报告，参数未接入全塔。

重算须使用新目录，保留既有证据：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.liu_angle_phm.experiment --output /tmp/liu_phm_new_run
.venv/bin/python -m unittest tests.test_liu_angle_phm -v
```

绘图结果和原始数值文件保留本地；后续版本管理优先脚本、测试、方法和结论，避免整体提交结果目录。
