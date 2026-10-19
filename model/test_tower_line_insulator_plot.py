from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from model.tower_line_system_model import TowerLineSystemModel


def build_tower_line_insulator_plot(auto_open: bool = True) -> Path:
    config_path = PROJECT_ROOT / "model" / ".config" / "tower_line_with_insulators.json"
    output_dir = PROJECT_ROOT / "model" / ".output" / "tower_line_with_insulators"
    system_model = TowerLineSystemModel(config_path, output_dir=output_dir, wipe=True)
    system_model.build()
    html_path = system_model.write_plot_html(auto_open=auto_open)

    print("tower-line-insulator system built")
    print(f"towers: {len(system_model.towers)}")
    print(f"insulators: {len(system_model.insulator_map)}")
    print(f"transmission lines: {len(system_model.transmission_line_map)}")
    print(f"nodes: {len(system_model.node_map)}")
    print(f"elements: {len(system_model.element_map)}")
    print(f"plot html: {html_path}")
    print(f"plot url: {html_path.resolve().as_uri()}")
    if auto_open:
        print("plot opened in the default browser")
    return html_path


if __name__ == "__main__":
    build_tower_line_insulator_plot()
