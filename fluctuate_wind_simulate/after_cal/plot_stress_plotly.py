# -*- coding: utf-8 -*-
"""
OpenSees tower post-processing (Plotly)
- nodes file:    node <tag> <x> <y> <z>
- elements file: element dispBeamColumn <eleTag> <iNode> <jNode> ...
- stress file:
    A) time table: [time, s(ele1), s(ele2), ... s(eleN)]  (columns ordered by eleTag ascending)
    B) snapshot:   N rows x 1 col (one stress per element) OR 1 row x N cols

Output:
  - Interactive HTML (recommended): tower_stress.html
  - Optional static PNG via kaleido
"""

from __future__ import annotations
import re
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale


@dataclass(frozen=True)
class ElementLine:
    ele_tag: int
    i_node: int
    j_node: int


# -----------------------------
# Parsers
# -----------------------------
def read_nodes(node_file: str) -> Dict[int, np.ndarray]:
    nodes: Dict[int, np.ndarray] = {}
    with open(node_file, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = re.split(r"[#;]", line, maxsplit=1)[0].strip()
            if not line:
                continue
            toks = line.split()
            if len(toks) >= 5 and toks[0] == "node":
                tag = int(toks[1])
                x, y, z = float(toks[2]), float(toks[3]), float(toks[4])
                nodes[tag] = np.array([x, y, z], dtype=float)
    return nodes


def read_elements_disp_beamcolumn(ele_file: str) -> List[ElementLine]:
    elems: List[ElementLine] = []
    with open(ele_file, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = re.split(r"[#;]", line, maxsplit=1)[0].strip()
            if not line:
                continue
            toks = line.split()
            if len(toks) >= 5 and toks[0] == "element" and toks[1] == "dispBeamColumn":
                ele_tag = int(toks[2])
                i_node = int(toks[3])
                j_node = int(toks[4])
                elems.append(ElementLine(ele_tag, i_node, j_node))

    elems.sort(key=lambda e: e.ele_tag)
    return elems


def _read_numeric_rows(path: str) -> List[List[float]]:
    rows: List[List[float]] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = re.split(r"[#;]", line, maxsplit=1)[0].strip()
            if not line:
                continue
            toks = re.split(r"[\s,]+", line)
            nums = []
            ok = True
            for t in toks:
                if not t:
                    continue
                try:
                    nums.append(float(t))
                except ValueError:
                    ok = False
                    break
            if ok and nums:
                rows.append(nums)
    return rows


def read_stress(
    stress_file: str,
    n_elems: int,
    *,
    has_time: Optional[bool] = None,
    time_col: int = 0,
    data_col_start: int = 1,
) -> Tuple[Optional[np.ndarray], np.ndarray]:
    """
    Returns:
      times: (n_steps,) or None
      table: (n_steps, n_elems) or (1, n_elems)
    """
    rows = _read_numeric_rows(stress_file)
    if not rows:
        raise ValueError(f"Stress file empty or non-numeric: {stress_file}")

    if has_time is None:
        # heuristic: if every row has exactly n_elems+1 columns, treat as time table
        has_time = all(len(r) == n_elems + 1 for r in rows)

    if has_time:
        times, data = [], []
        need_cols = data_col_start + n_elems
        for r in rows:
            if len(r) < need_cols:
                raise ValueError(f"Row has {len(r)} cols, need >= {need_cols}. Check data_col_start.")
            times.append(r[time_col])
            data.append(r[data_col_start: data_col_start + n_elems])
        return np.asarray(times, float), np.asarray(data, float)

    # snapshot modes
    if len(rows) == n_elems and all(len(r) >= 1 for r in rows):
        s = np.array([r[0] for r in rows], dtype=float).reshape(1, n_elems)
        return None, s

    if len(rows) == 1 and len(rows[0]) >= n_elems:
        s = np.asarray(rows[0][:n_elems], dtype=float).reshape(1, n_elems)
        return None, s

    raise ValueError(
        f"Cannot infer stress format. rows={len(rows)}, cols(first)={len(rows[0])}, n_elems={n_elems}. "
        f"Set has_time=True/False explicitly."
    )


def pick_step(
    times: Optional[np.ndarray],
    table: np.ndarray,
    *,
    step_index: int = -1,
    target_time: Optional[float] = None,
) -> Tuple[int, Optional[float], np.ndarray]:
    if times is not None and target_time is not None:
        idx = int(np.argmin(np.abs(times - target_time)))
        return idx, float(times[idx]), table[idx, :].copy()

    idx = step_index
    if idx < 0:
        idx = table.shape[0] + idx
    idx = max(0, min(idx, table.shape[0] - 1))
    t = float(times[idx]) if times is not None else None
    return idx, t, table[idx, :].copy()


def build_segments(elems: List[ElementLine], nodes: Dict[int, np.ndarray]) -> Tuple[np.ndarray, List[int]]:
    segs, tags = [], []
    for e in elems:
        if e.i_node not in nodes or e.j_node not in nodes:
            continue
        segs.append([nodes[e.i_node], nodes[e.j_node]])
        tags.append(e.ele_tag)
    if not segs:
        raise ValueError("No valid segments found. Check node IDs / element connectivity.")
    return np.asarray(segs, float), tags


# -----------------------------
# Plotting (Plotly)
# -----------------------------
def plot_stress_cloud_plotly(
    segments: np.ndarray,   # (n,2,3)
    stresses: np.ndarray,   # (n,)
    *,
    title: str,
    colorscale: str = "YlOrRd",   # ✅ 红黄系：黄→橙→红
    use_abs: bool = False,
    nbins: int = 80,              # 分箱数量：越大越连续
    line_width: float = 4.0,
) -> go.Figure:
    s = np.abs(stresses) if use_abs else stresses
    vmin = float(np.nanmin(s))
    vmax = float(np.nanmax(s))
    if math.isclose(vmin, vmax):
        vmax = vmin + 1e-12

    # 分箱：每个 bin 一个 trace（同色），实现“近似连续”的云图
    edges = np.linspace(vmin, vmax, nbins + 1)
    bin_ids = np.clip(np.digitize(s, edges) - 1, 0, nbins - 1)

    fig = go.Figure()

    for b in range(nbins):
        idx = np.where(bin_ids == b)[0]
        if idx.size == 0:
            continue

        xs, ys, zs = [], [], []
        for i in idx:
            p0, p1 = segments[i, 0], segments[i, 1]
            xs += [p0[0], p1[0], None]
            ys += [p0[1], p1[1], None]
            zs += [p0[2], p1[2], None]

        t = (b + 0.5) / nbins
        color = sample_colorscale(colorscale, [t])[0]

        fig.add_trace(
            go.Scatter3d(
                x=xs, y=ys, z=zs,
                mode="lines",
                line=dict(color=color, width=line_width),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # 用透明点来“挂载”连续 colorbar（颜色条与线条同色带）
    fig.add_trace(
        go.Scatter3d(
            x=np.zeros_like(s),
            y=np.zeros_like(s),
            z=np.zeros_like(s),
            mode="markers",
            marker=dict(
                size=1,
                opacity=0.0,
                color=s,
                colorscale=colorscale,
                cmin=vmin,
                cmax=vmax,
                colorbar=dict(title="Stress"),
            ),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    fig.update_layout(
        title=title,
        scene=dict(
            xaxis_title="X",
            yaxis_title="Y",
            zaxis_title="Z",
            aspectmode="data",   # ✅ 按原始比例显示
        ),
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return fig


# -----------------------------
# Main workflow (interfaces)
# -----------------------------
def main(
    node_file: str,
    ele_file: str,
    stress_file: str,
    *,
    # stress file format interface:
    has_time: Optional[bool] = None,  # True: [time, s1..sN], False: snapshot
    time_col: int = 0,
    data_col_start: int = 1,
    # choose time step:
    target_time: Optional[float] = None,  # e.g. 0.25 (choose nearest)
    step_index: int = -1,                 # default last step if target_time None
    # plot options:
    colorscale: str = "YlOrRd",
    use_abs: bool = False,
    nbins: int = 80,
    line_width: float = 4.0,
    # outputs:
    out_html: str = "tower_stress.html",
    out_png: Optional[str] = None,        # requires kaleido
) -> None:
    nodes = read_nodes(node_file)
    elems = read_elements_disp_beamcolumn(ele_file)

    times, table = read_stress(
        stress_file,
        n_elems=len(elems),
        has_time=has_time,
        time_col=time_col,
        data_col_start=data_col_start,
    )
    idx, t, stress_vec = pick_step(times, table, step_index=step_index, target_time=target_time)

    segments, seg_ele_tags = build_segments(elems, nodes)

    # stress_vec is assumed ordered by eleTag ascending (same as elems sorted)
    ele_tags_sorted = [e.ele_tag for e in elems]
    tag_to_index = {tag: i for i, tag in enumerate(ele_tags_sorted)}
    seg_stress = np.array([stress_vec[tag_to_index[tag]] for tag in seg_ele_tags], dtype=float)

    title = "Tower member stress contour"
    if t is not None:
        title += f" (t={t:g}, step={idx})"
    else:
        title += f" (step={idx})"

    fig = plot_stress_cloud_plotly(
        segments,
        seg_stress,
        title=title,
        colorscale=colorscale,
        use_abs=use_abs,
        nbins=nbins,
        line_width=line_width,
    )

    fig.write_html(out_html, include_plotlyjs="cdn")
    print(f"[OK] Saved HTML: {out_html}")

    if out_png:
        try:
            fig.write_image(out_png, scale=2)
            print(f"[OK] Saved PNG: {out_png}")
        except Exception as e:
            print("[WARN] PNG export failed. Install kaleido: pip install kaleido")
            print("       Error:", e)

    fig.show()


if __name__ == "__main__":
    # ====== 在这里填你的文件路径（接口）======
    NODE_FILE = "Src/Node.tcl"
    ELE_FILE = "Src/Element.tcl"
    STRESS_FILE = "fluctuate_wind_simulate/.output/opensees_simulate/Element_all_section_1.out"

    main(
        NODE_FILE,
        ELE_FILE,
        STRESS_FILE,
        has_time=True,          # 若 stress.txt 第一列是 time，则 True；如果是快照向量则 False
        time_col=0,
        data_col_start=1,
        target_time=None,       # 指定某一时刻：如 0.25；不指定则用 step_index
        step_index=-1,          # 默认最后一步
        colorscale="Hot",    # ✅ 红黄系（可换 "Hot" / "OrRd" / "Reds"）
        use_abs=False,          # True: |stress|
        nbins=80,
        line_width=4.0,
        out_html="tower_stress.html",
        out_png=None,           # 想导出png：out_png="tower_stress.png" (需 kaleido)
    )
