from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

import openseespy.opensees as ops

from model.tower_model import OpenSeesModel, TagManager
from util.postprocess.plot_model import PlotModel


@dataclass
class CombinedModelView:
    """Minimal object accepted by PlotModel for visualizing several models."""

    node_map: dict[int, dict[str, Any]]
    element_map: dict[int, dict[str, Any]]
    fix_map: dict[int, dict[str, Any]]
    mass_map: dict[int, dict[str, Any]]
    output_dir: Path


def make_tag_manager() -> TagManager:
    return TagManager(
        start_tag={
            "node": 1,
            "material": 1,
            "section": 1,
            "transf": 1,
            "integration": 1,
            "element": 1,
            "source_element": 1,
        }
    )


def merge_models(models: list[OpenSeesModel], output_dir: Path) -> CombinedModelView:
    node_map: dict[int, dict[str, Any]] = {}
    element_map: dict[int, dict[str, Any]] = {}
    fix_map: dict[int, dict[str, Any]] = {}
    mass_map: dict[int, dict[str, Any]] = {}

    for model in models:
        node_map.update(model.node_map)
        element_map.update(model.element_map)
        fix_map.update(model.fix_map)
        mass_map.update(model.mass_map)

    return CombinedModelView(
        node_map=node_map,
        element_map=element_map,
        fix_map=fix_map,
        mass_map=mass_map,
        output_dir=output_dir,
    )


def build_multi_tower_plot_test(auto_open: bool = True) -> Path:
    """Build two towers in one OpenSees domain and display an interactive HTML plot."""

    ops.wipe()
    output_dir = PROJECT_ROOT / "model" / ".output" / "multi_tower_plot_test"
    source_path = PROJECT_ROOT / "Source" / "Z30103A6.s2k"
    tag_manager = make_tag_manager()

    towers = [
        OpenSeesModel(
            source_path,
            tower_id="tower_1",
            origin=(0.0, 0.0, 0.0),
            tag_manager=tag_manager,
            output_dir=output_dir / "tower_1",
        ),
        OpenSeesModel(
            source_path,
            tower_id="tower_2",
            origin=(0, 300, 0.0),
            tag_manager=tag_manager,
            output_dir=output_dir / "tower_2",
        ),
    ]

    for tower in towers:
        tower.model_tower()

    combined_model = merge_models(towers, output_dir)
    html_path = output_dir / "multi_tower_model.html"
    PlotModel(combined_model).write_html(
        html_path,
        title="Multi Tower Model - Shared TagManager",
        show_nodes=True,
        show_elements=True,
        element_hover="midpoint",
        node_size=2,
        element_width=2,
        width=1200,
        height=850,
        auto_open=auto_open,
    )

    local_node = min(towers[0].node_local_to_global_tag)
    print("multi tower model built")
    print(f"tower_1 local node {local_node} -> global {towers[0].resolve_node_tag(local_node)}")
    print(f"tower_2 local node {local_node} -> global {towers[1].resolve_node_tag(local_node)}")
    print(f"nodes: {len(combined_model.node_map)}")
    print(f"elements: {len(combined_model.element_map)}")
    print(f"plot html: {html_path}")
    print(f"plot url: {html_path.resolve().as_uri()}")
    if auto_open:
        print("plot opened in the default browser")
    return html_path


if __name__ == "__main__":
    build_multi_tower_plot_test()
