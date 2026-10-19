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
