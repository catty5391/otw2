from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


class PlotModel:
    """Interactive 3D visualization for OpenSeesModel and subclasses.

    The visualizer reads ``node_map`` and ``element_map`` from the model. If the
    maps are empty, it falls back to ``nodes.csv`` and ``elements.csv`` under the
    model's ``output_dir``. Hover text is attached to both nodes and elements.
    """

    def __init__(
        self,
        model: Any,
        *,
        build_if_empty: bool = False,
        strict: bool = False,
    ) -> None:
        self.model = model
        self.build_if_empty = build_if_empty
        self.strict = strict
        self.skipped_elements: list[int] = []
        self.node_records = self._load_nodes()
        self.element_records = self._load_elements()

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))

    @staticmethod
    def _fmt(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    @staticmethod
    def _coord(record: dict[str, Any]) -> tuple[float, float, float]:
        return float(record["x"]), float(record["y"]), float(record["z"])

    @staticmethod
    def _load_plotly_go() -> Any:
        try:
            import plotly.graph_objects as go
        except ImportError as exc:  # pragma: no cover
            raise ImportError("PlotModel.figure()/show() 依赖 plotly；也可以直接用 write_html()。") from exc
        return go

    def _output_dir(self) -> Path | None:
        output_dir = getattr(self.model, "output_dir", None)
        if output_dir is None:
            return None
        return Path(output_dir)

    def _maybe_build_model(self) -> None:
        if not self.build_if_empty:
            return
        if getattr(self.model, "node_map", None) and getattr(self.model, "element_map", None):
            return
        build = getattr(self.model, "model_tower", None)
        if not callable(build):
            raise ValueError("model 没有 model_tower()，无法自动建模。")
        build()

    def _load_nodes(self) -> dict[int, dict[str, Any]]:
        self._maybe_build_model()
        node_map = getattr(self.model, "node_map", None) or {}
        if node_map:
            result: dict[int, dict[str, Any]] = {}
            for tag, raw_record in node_map.items():
                record = dict(raw_record)
                node_tag = int(record.get("node_tag", tag))
                result[node_tag] = {
                    **record,
                    "node_tag": node_tag,
                    "x": float(record["x"]),
                    "y": float(record["y"]),
                    "z": float(record["z"]),
                }
            return result

        output_dir = self._output_dir()
        rows = self._read_csv(output_dir / "nodes.csv") if output_dir else []
        if not rows:
            raise ValueError("未找到节点数据，请先调用 model.node()/model_tower() 或提供 nodes.csv。")
        return {
            int(row["node_tag"]): {
                **row,
                "node_tag": int(row["node_tag"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "z": float(row["z"]),
            }
            for row in rows
        }

    def _load_elements(self) -> dict[int, dict[str, Any]]:
        element_map = getattr(self.model, "element_map", None) or {}
        if element_map:
            result: dict[int, dict[str, Any]] = {}
            for tag, raw_record in element_map.items():
                record = dict(raw_record)
                element_tag = int(record.get("element_tag", tag))
                result[element_tag] = {
                    **record,
                    "element_tag": element_tag,
                    "node_i": int(record["node_i"]),
                    "node_j": int(record["node_j"]),
                }
            return result

        output_dir = self._output_dir()
        rows = self._read_csv(output_dir / "elements.csv") if output_dir else []
        if not rows:
            raise ValueError("未找到单元数据，请先调用 model.element()/model_tower() 或提供 elements.csv。")

        result: dict[int, dict[str, Any]] = {}
        int_fields = {
            "element_tag",
            "node_i",
            "node_j",
            "original_element_tag",
            "segment_index",
            "parent_node_i",
            "parent_node_j",
            "num_intgr_pts",
            "section_tag",
            "mat_tag",
            "transf_tag",
            "integration_tag",
        }
        for row in rows:
            record: dict[str, Any] = {**row}
            for key in int_fields:
                if key in record and record[key] not in ("", None):
                    record[key] = int(float(record[key]))
            result[int(record["element_tag"])] = record
        return result

    def _node_hover_text(self, record: dict[str, Any]) -> str:
        lines = [
            f"Node: {record['node_tag']}",
            f"x: {self._fmt(float(record['x']))}",
            f"y: {self._fmt(float(record['y']))}",
            f"z: {self._fmt(float(record['z']))}",
        ]
        for key in ("original_element_tag", "station_index", "station_ratio"):
            if key in record and record[key] not in ("", None):
                lines.append(f"{key}: {self._fmt(record[key])}")

        fix_map = getattr(self.model, "fix_map", {}) or {}
        fix = fix_map.get(record["node_tag"])
        if fix:
            fixity = [fix.get(key) for key in ("ux", "uy", "uz", "rx", "ry", "rz")]
            lines.append(f"fix: {fixity}")

        mass_map = getattr(self.model, "mass_map", {}) or {}
        mass = mass_map.get(record["node_tag"])
        if mass:
            masses = [mass.get(key) for key in ("mx", "my", "mz", "mrx", "mry", "mrz")]
            lines.append(f"mass: {masses}")
        return "<br>".join(lines)

    def _element_hover_text(self, record: dict[str, Any], length: float) -> str:
        keys = [
            "original_element_tag",
            "segment_index",
            "node_i",
            "node_j",
            "parent_node_i",
            "parent_node_j",
            "section_name",
            "section_tag",
            "material_name",
            "mat_tag",
            "transf_tag",
            "integration_tag",
            "integration_type",
            "num_intgr_pts",
        ]
        lines = [f"Element: {record['element_tag']}", f"length: {length:.6g}"]
        for key in keys:
            if key in record and record[key] not in ("", None):
                lines.append(f"{key}: {self._fmt(record[key])}")
        return "<br>".join(lines)

    def _valid_element_geometry(
        self,
        record: dict[str, Any],
    ) -> tuple[tuple[float, float, float], tuple[float, float, float], float] | None:
        node_i_tag = int(record["node_i"])
        node_j_tag = int(record["node_j"])
        node_i = self.node_records.get(node_i_tag)
        node_j = self.node_records.get(node_j_tag)
        if node_i is None or node_j is None:
            self.skipped_elements.append(int(record["element_tag"]))
            if self.strict:
                missing = node_i_tag if node_i is None else node_j_tag
                raise KeyError(f"单元 {record['element_tag']} 引用了不存在的节点 {missing}")
            return None
        coord_i = self._coord(node_i)
        coord_j = self._coord(node_j)
        return coord_i, coord_j, math.dist(coord_i, coord_j)

    def figure_dict(
        self,
        *,
        title: str = "OpenSees Model",
        show_nodes: bool = True,
        show_elements: bool = True,
        element_hover: str = "midpoint",
        node_size: int = 3,
        element_width: int = 3,
        width: int = 1000,
        height: int = 800,
    ) -> dict[str, Any]:
        """Return a Plotly-compatible figure dictionary.

        ``element_hover="midpoint"`` batches all element lines into one trace
        and uses midpoint markers for hover, which is much faster for large
        models. Use ``element_hover="line"`` only when direct line hover is
        more important than browser performance.
        """
        if element_hover not in {"line", "midpoint"}:
            raise ValueError('element_hover 只能是 "line" 或 "midpoint"。')

        self.skipped_elements = []
        data: list[dict[str, Any]] = []
        if show_elements:
            if element_hover == "line":
                self._add_element_line_dicts(data, element_width)
            else:
                self._add_batched_element_dicts(data, element_width)
        if show_nodes:
            self._add_node_dict(data, node_size)

        return {
            "data": data,
            "layout": {
                "title": title,
                "width": width,
                "height": height,
                "hovermode": "closest",
                "scene": {
                    "xaxis_title": "X",
                    "yaxis_title": "Y",
                    "zaxis_title": "Z",
                    "aspectmode": "data",
                },
                "legend": {"itemsizing": "constant"},
                "margin": {"l": 0, "r": 0, "b": 0, "t": 40},
            },
        }

    def figure(self, **figure_kwargs: Any) -> Any:
        """Return a Plotly Figure. Requires the Python ``plotly`` package."""
        payload = self.figure_dict(**figure_kwargs)
        go = self._load_plotly_go()
        return go.Figure(data=payload["data"], layout=payload["layout"])

    def _add_node_dict(self, data: list[dict[str, Any]], node_size: int) -> None:
        records = [self.node_records[tag] for tag in sorted(self.node_records)]
        data.append(
            {
                "type": "scatter3d",
                "x": [record["x"] for record in records],
                "y": [record["y"] for record in records],
                "z": [record["z"] for record in records],
                "mode": "markers",
                "marker": {
                    "size": node_size,
                    "color": [record["z"] for record in records],
                    "colorscale": "Viridis",
                    "opacity": 0.85,
                },
                "text": [self._node_hover_text(record) for record in records],
                "hovertemplate": "%{text}<extra></extra>",
                "name": "Nodes",
            }
        )

    def _add_element_line_dicts(self, data: list[dict[str, Any]], element_width: int) -> None:
        first = True
        for element_tag in sorted(self.element_records):
            record = self.element_records[element_tag]
            geometry = self._valid_element_geometry(record)
            if geometry is None:
                continue
            coord_i, coord_j, length = geometry
            hover_text = self._element_hover_text(record, length)
            data.append(
                {
                    "type": "scatter3d",
                    "x": [coord_i[0], coord_j[0]],
                    "y": [coord_i[1], coord_j[1]],
                    "z": [coord_i[2], coord_j[2]],
                    "mode": "lines",
                    "line": {"color": "#666666", "width": element_width},
                    "text": [hover_text, hover_text],
                    "hovertemplate": "%{text}<extra></extra>",
                    "name": "Elements",
                    "legendgroup": "Elements",
                    "showlegend": first,
                }
            )
            first = False

    def _add_batched_element_dicts(self, data: list[dict[str, Any]], element_width: int) -> None:
        x_lines: list[float | None] = []
        y_lines: list[float | None] = []
        z_lines: list[float | None] = []
        mid_x: list[float] = []
        mid_y: list[float] = []
        mid_z: list[float] = []
        hover_texts: list[str] = []

        for element_tag in sorted(self.element_records):
            record = self.element_records[element_tag]
            geometry = self._valid_element_geometry(record)
            if geometry is None:
                continue
            coord_i, coord_j, length = geometry
            x_lines.extend([coord_i[0], coord_j[0], None])
            y_lines.extend([coord_i[1], coord_j[1], None])
            z_lines.extend([coord_i[2], coord_j[2], None])
            mid_x.append((coord_i[0] + coord_j[0]) * 0.5)
            mid_y.append((coord_i[1] + coord_j[1]) * 0.5)
            mid_z.append((coord_i[2] + coord_j[2]) * 0.5)
            hover_texts.append(self._element_hover_text(record, length))

        data.append(
            {
                "type": "scatter3d",
                "x": x_lines,
                "y": y_lines,
                "z": z_lines,
                "mode": "lines",
                "line": {"color": "#666666", "width": element_width},
                "hoverinfo": "skip",
                "name": "Elements",
            }
        )
        data.append(
            {
                "type": "scatter3d",
                "x": mid_x,
                "y": mid_y,
                "z": mid_z,
                "mode": "markers",
                "marker": {"size": max(2, element_width + 1), "color": "#d95f02", "opacity": 0.01},
                "text": hover_texts,
                "hovertemplate": "%{text}<extra></extra>",
                "name": "Element hover",
                "showlegend": False,
            }
        )

    def show(self, **figure_kwargs: Any) -> Any:
        """Show the same figure content as ``write_html()`` via Plotly."""
        fig = self.figure(**figure_kwargs)
        fig.show()
        return fig

    def to_html(
        self,
        *,
        include_plotlyjs: str | bool = "cdn",
        div_id: str = "opensees-model-viewer",
        **figure_kwargs: Any,
    ) -> str:
        payload = self.figure_dict(**figure_kwargs)
        plotly_script = ""
        if include_plotlyjs is True or include_plotlyjs == "cdn":
            plotly_script = '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'
        elif isinstance(include_plotlyjs, str) and include_plotlyjs:
            plotly_script = f'<script src="{include_plotlyjs}"></script>'
        config = {"responsive": True, "displaylogo": False}
        return "\n".join(
            [
                "<!doctype html>",
                '<html lang="zh-CN">',
                "<head>",
                '<meta charset="utf-8">',
                "<title>OpenSees Model</title>",
                plotly_script,
                "</head>",
                "<body>",
                f'<div id="{div_id}" style="width:100%;height:100vh;"></div>',
                "<script>",
                f"const figure = {json.dumps(payload, ensure_ascii=False)};",
                f"const config = {json.dumps(config, ensure_ascii=False)};",
                f"Plotly.newPlot({json.dumps(div_id)}, figure.data, figure.layout, config);",
                "</script>",
                "</body>",
                "</html>",
            ]
        )

    def write_html(
        self,
        path: str | Path,
        *,
        include_plotlyjs: str | bool = "cdn",
        auto_open: bool = False,
        **figure_kwargs: Any,
    ) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            self.to_html(include_plotlyjs=include_plotlyjs, **figure_kwargs),
            encoding="utf-8",
        )
        if auto_open:
            import shutil
            import subprocess
            import webbrowser

            uri = output_path.resolve().as_uri()
            opened = webbrowser.open_new_tab(uri)
            if not opened:
                for command in (("xdg-open", uri), ("gio", "open", uri), ("open", uri)):
                    if shutil.which(command[0]) is None:
                        continue
                    try:
                        subprocess.Popen(
                            command,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        opened = True
                        break
                    except OSError:
                        continue
        return output_path


plot_model = PlotModel


if __name__ == "__main__":
    from pathlib import Path
    import sys
    import os
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.append(str(PROJECT_ROOT))
    from model import OpenSeesModelWithBuckling
    model_with_buckling = OpenSeesModelWithBuckling("Source/Z30103A6.s2k")
    model_with_buckling.model_tower()
    PlotModel(model_with_buckling).show()
