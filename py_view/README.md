# 塔—线体系可视化

该模块把已经建立的 OpenSees 塔—线模型输出为一个交互式 HTML 页面：

- 输电塔、绝缘子和导线分色显示；
- 鼠标悬停查看节点坐标、节点质量及单元信息；
- 汇总模型节点、单元、模型高度和导线总质量；
- 展示每条导线的型号、分裂数、线质量、自重、总质量、找形初拉力和平衡弧垂。

从项目根目录运行：

```bash
.venv/bin/python -m py_view.view_by_plotly
```

默认输出到 `py_view/.output/tower_line_dashboard.html`。如果要生成后直接打开并默认显示节点：

```bash
.venv/bin/python -m py_view.view_by_plotly --show-nodes --open
```

也可以在代码中复用：

```python
from py_view import TowerLineDashboard

viewer = TowerLineDashboard(built_model)
viewer.write_html("tower_line.html")
```

## Z30103A6 成果驾驶舱

`results_dashboard` 将当前已经生成的研究结果整合成一个本地网页：

- 单杆推覆、收敛、峰前卸载和实际杆长验证；
- 等效材料全塔与四分段全塔的往复响应对比；
- 从 SQLite 内力库查询任意记录时刻或任意时间段的全塔内力分布；
- 点击杆件查看该构件的完整内力历程；
- 集中下载材料报告、全塔报告、参数依据和本地文献。

从项目根目录启动：

```bash
.venv/bin/python -m py_view.results_dashboard --host 0.0.0.0 --port 9999
```

浏览器访问 `http://127.0.0.1:9999`。网页只读取现有 JSON、CSV 和 SQLite
结果，不会重新运行 OpenSees，也不会复制两套大体积内力数据库。
