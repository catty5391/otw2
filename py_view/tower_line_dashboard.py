from __future__ import annotations

import html
import json
import math
import webbrowser
from pathlib import Path
from typing import Any


class TowerLineDashboard:
    """Create a lightweight Plotly dashboard from a built tower-line model.

    The model only needs ``node_map`` and ``element_map``. When available,
    ``transmission_line_map`` and ``mass_map`` are used for the summary cards,
    conductor table, and node hover information.
    """

    GROUP_STYLES = {
        "tower": {"label": "输电塔", "color": "#94a3b8", "width": 2},
        "insulator": {"label": "绝缘子", "color": "#f59e0b", "width": 5},
        "conductor": {"label": "输电线", "color": "#38bdf8", "width": 4},
    }

    def __init__(self, model: Any) -> None:
        self.model = model
        self.nodes = self._normalized_nodes(getattr(model, "node_map", {}))
        self.elements = self._normalized_elements(getattr(model, "element_map", {}))
        self.lines = getattr(model, "transmission_line_map", {}) or {}
        self.masses = getattr(model, "mass_map", {}) or {}
        if not self.nodes:
            raise ValueError("模型没有节点数据，请先调用 build() 或 model_tower()。")
        if not self.elements:
            raise ValueError("模型没有单元数据，请先调用 build() 或 model_tower()。")

    @staticmethod
    def _normalized_nodes(raw_nodes: Any) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for key, raw in (raw_nodes or {}).items():
            record = dict(raw)
            tag = int(record.get("node_tag", key))
            result[tag] = {
                **record,
                "node_tag": tag,
                "x": float(record["x"]),
                "y": float(record["y"]),
                "z": float(record["z"]),
            }
        return result

    @staticmethod
    def _normalized_elements(raw_elements: Any) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for key, raw in (raw_elements or {}).items():
            record = dict(raw)
            tag = int(record.get("element_tag", key))
            result[tag] = {
                **record,
                "element_tag": tag,
                "node_i": int(record["node_i"]),
                "node_j": int(record["node_j"]),
            }
        return result

    @staticmethod
    def _element_group(record: dict[str, Any]) -> str:
        component = str(record.get("component", "")).lower()
        if component == "insulator":
            return "insulator"
        if component in {"transmission_line", "conductor", "line"}:
            return "conductor"
        return "tower"

    def summary(self) -> dict[str, float | int]:
        z_values = [record["z"] for record in self.nodes.values()]
        total_conductor_mass = sum(
            float(record.get("total_conductor_mass", 0.0)) for record in self.lines.values()
        )
        return {
            "nodes": len(self.nodes),
            "elements": len(self.elements),
            "lines": len(self.lines),
            "height": max(z_values) - min(z_values),
            "total_conductor_mass": total_conductor_mass,
        }

    def _element_hover(self, record: dict[str, Any], length: float) -> str:
        group = self._element_group(record)
        style = self.GROUP_STYLES[group]
        lines = [
            f"{style['label']}单元: {record['element_tag']}",
            f"节点: {record['node_i']} → {record['node_j']}",
            f"长度: {length:.4f} m",
        ]
        for key, label in (
            ("tower_id", "塔编号"),
            ("line_id", "导线编号"),
            ("insulator_id", "绝缘子编号"),
            ("section_name", "截面"),
            ("section_tag", "截面 tag"),
        ):
            value = record.get(key)
            if value not in (None, ""):
                lines.append(f"{label}: {value}")
        return "<br>".join(lines)

    def _node_hover(self, record: dict[str, Any]) -> str:
        tag = int(record["node_tag"])
        lines = [
            f"节点: {tag}",
            f"坐标: ({record['x']:.4f}, {record['y']:.4f}, {record['z']:.4f}) m",
        ]
        mass = self.masses.get(tag)
        if mass:
            lines.append(f"平动质量: {float(mass.get('mx', 0.0)):.4f} kg")
        component = record.get("component")
        if component:
            lines.append(f"类型: {component}")
        return "<br>".join(lines)

    def _group_traces(self, group: str) -> list[dict[str, Any]]:
        style = self.GROUP_STYLES[group]
        x: list[float | None] = []
        y: list[float | None] = []
        z: list[float | None] = []
        mid_x: list[float] = []
        mid_y: list[float] = []
        mid_z: list[float] = []
        hover: list[str] = []

        for tag in sorted(self.elements):
            record = self.elements[tag]
            if self._element_group(record) != group:
                continue
            node_i = self.nodes.get(record["node_i"])
            node_j = self.nodes.get(record["node_j"])
            if node_i is None or node_j is None:
                continue
            coord_i = (node_i["x"], node_i["y"], node_i["z"])
            coord_j = (node_j["x"], node_j["y"], node_j["z"])
            length = math.dist(coord_i, coord_j)
            x.extend([coord_i[0], coord_j[0], None])
            y.extend([coord_i[1], coord_j[1], None])
            z.extend([coord_i[2], coord_j[2], None])
            mid_x.append(0.5 * (coord_i[0] + coord_j[0]))
            mid_y.append(0.5 * (coord_i[1] + coord_j[1]))
            mid_z.append(0.5 * (coord_i[2] + coord_j[2]))
            hover.append(self._element_hover(record, length))

        if not hover:
            return []
        return [
            {
                "type": "scatter3d",
                "mode": "lines",
                "x": x,
                "y": y,
                "z": z,
                "line": {"color": style["color"], "width": style["width"]},
                "hoverinfo": "skip",
                "name": style["label"],
                "legendgroup": group,
            },
            {
                "type": "scatter3d",
                "mode": "markers",
                "x": mid_x,
                "y": mid_y,
                "z": mid_z,
                "marker": {"size": 5, "color": style["color"], "opacity": 0.01},
                "text": hover,
                "hovertemplate": "%{text}<extra></extra>",
                "name": f"{style['label']}信息",
                "legendgroup": group,
                "showlegend": False,
            },
        ]

    def figure_dict(self, *, show_nodes: bool = False) -> dict[str, Any]:
        traces: list[dict[str, Any]] = []
        for group in ("tower", "insulator", "conductor"):
            traces.extend(self._group_traces(group))

        node_records = [self.nodes[tag] for tag in sorted(self.nodes)]
        traces.append(
            {
                "type": "scatter3d",
                "mode": "markers",
                "x": [record["x"] for record in node_records],
                "y": [record["y"] for record in node_records],
                "z": [record["z"] for record in node_records],
                "marker": {"size": 2.5, "color": "#e2e8f0", "opacity": 0.65},
                "text": [self._node_hover(record) for record in node_records],
                "hovertemplate": "%{text}<extra></extra>",
                "name": "节点",
                "visible": True if show_nodes else "legendonly",
            }
        )

        return {
            "data": traces,
            "layout": {
                "paper_bgcolor": "#0f172a",
                "plot_bgcolor": "#0f172a",
                "font": {"color": "#e2e8f0", "family": "Inter, system-ui, sans-serif"},
                "margin": {"l": 0, "r": 0, "t": 10, "b": 0},
                "hovermode": "closest",
                "legend": {"orientation": "h", "x": 0.01, "y": 0.99, "bgcolor": "rgba(15,23,42,.7)"},
                "scene": {
                    "aspectmode": "data",
                    "bgcolor": "#0f172a",
                    "xaxis": {"title": "X / m", "gridcolor": "#334155", "zerolinecolor": "#475569"},
                    "yaxis": {"title": "Y / m", "gridcolor": "#334155", "zerolinecolor": "#475569"},
                    "zaxis": {"title": "Z / m", "gridcolor": "#334155", "zerolinecolor": "#475569"},
                    "camera": {"eye": {"x": 1.35, "y": 1.35, "z": 0.9}},
                },
            },
        }

    def _line_table_rows(self) -> str:
        rows = []
        for line_id, record in self.lines.items():
            conductor = record.get("conductor", {}) or {}
            formfinding = record.get("formfinding", {}) or {}
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(line_id))}</td>"
                f"<td>{html.escape(str(conductor.get('model') or '自定义'))}</td>"
                f"<td>{int(conductor.get('bundle_count', 1))}</td>"
                f"<td>{float(record.get('conductor_length', 0.0)):.3f}</td>"
                f"<td>{float(record.get('mass_per_length', 0.0)):.4f}</td>"
                f"<td>{float(record.get('q_g', 0.0)):.4f}</td>"
                f"<td>{float(record.get('total_conductor_mass', 0.0)):.3f}</td>"
                f"<td>{float(formfinding.get('initial_force', record.get('material', {}).get('initial_force', 0.0))) / 1000.0:.3f}</td>"
                f"<td>{float(formfinding.get('achieved_sag', record.get('initial_sag', 0.0))):.4f}</td>"
                "</tr>"
            )
        if not rows:
            return '<tr><td colspan="9" class="empty">当前模型没有导线汇总数据</td></tr>'
        return "".join(rows)

    def to_html(self, *, show_nodes: bool = False, title: str = "输电塔—线体系可视化") -> str:
        figure_json = json.dumps(self.figure_dict(show_nodes=show_nodes), ensure_ascii=False).replace(
            "</", "<\\/"
        )
        summary = self.summary()
        safe_title = html.escape(title)
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #020617; color: #e2e8f0; font-family: Inter, system-ui, sans-serif; }}
    main {{ width: min(1500px, 100%); margin: auto; padding: 24px; }}
    header {{ display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 18px; }}
    h1 {{ margin: 0; font-size: clamp(22px, 3vw, 34px); }}
    .hint {{ color: #94a3b8; font-size: 13px; }}
    .cards {{ display: grid; grid-template-columns: repeat(5, minmax(130px, 1fr)); gap: 12px; margin-bottom: 14px; }}
    .card, .panel {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; box-shadow: 0 12px 34px rgba(0,0,0,.16); }}
    .card {{ padding: 14px 16px; }}
    .card span {{ color: #94a3b8; display: block; font-size: 12px; margin-bottom: 6px; }}
    .card strong {{ color: #f8fafc; font-size: 22px; }}
    #viewer {{ width: 100%; height: min(72vh, 820px); min-height: 520px; }}
    .table-panel {{ margin-top: 14px; padding: 18px; overflow-x: auto; }}
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #1e293b; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
    th {{ color: #94a3b8; font-weight: 600; }}
    .empty {{ color: #64748b; text-align: center !important; }}
    @media (max-width: 800px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} main {{ padding: 14px; }} header {{ align-items: start; flex-direction: column; }} }}
  </style>
</head>
<body>
<main>
  <header><div><h1>{safe_title}</h1><div class="hint">拖动旋转，滚轮缩放；点击图例可隐藏或显示构件</div></div><div class="hint">Z30103A6 · OpenSees</div></header>
  <section class="cards">
    <div class="card"><span>节点</span><strong>{summary['nodes']}</strong></div>
    <div class="card"><span>单元</span><strong>{summary['elements']}</strong></div>
    <div class="card"><span>导线数量</span><strong>{summary['lines']}</strong></div>
    <div class="card"><span>模型高度</span><strong>{summary['height']:.2f} m</strong></div>
    <div class="card"><span>导线总质量</span><strong>{summary['total_conductor_mass']:.2f} kg</strong></div>
  </section>
  <section class="panel"><div id="viewer"></div></section>
  <section class="panel table-panel">
    <h2>导线质量参数</h2>
    <table><thead><tr><th>导线</th><th>型号</th><th>分裂数</th><th>长度 / m</th><th>线质量 / kg·m⁻¹</th><th>线自重 / N·m⁻¹</th><th>总质量 / kg</th><th>找形初拉力 / kN</th><th>平衡弧垂 / m</th></tr></thead>
    <tbody>{self._line_table_rows()}</tbody></table>
  </section>
</main>
<script>
  const figure = {figure_json};
  Plotly.newPlot('viewer', figure.data, figure.layout, {{responsive: true, displaylogo: false}});
</script>
</body>
</html>"""

    def write_html(
        self,
        path: str | Path,
        *,
        show_nodes: bool = False,
        title: str = "输电塔—线体系可视化",
        auto_open: bool = False,
    ) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            self.to_html(show_nodes=show_nodes, title=title),
            encoding="utf-8",
        )
        if auto_open:
            webbrowser.open_new_tab(output_path.resolve().as_uri())
        return output_path
