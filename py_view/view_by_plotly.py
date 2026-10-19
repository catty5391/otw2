from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from model.tower_line_system_model import TowerLineSystemModel
from py_view.tower_line_dashboard import TowerLineDashboard


def build_tower_line_view(
    *,
    config_path: str | Path | None = None,
    output_path: str | Path | None = None,
    show_nodes: bool = False,
    auto_open: bool = False,
) -> Path:
    """Build the configured tower-line model and write its HTML dashboard."""

    model_output = PROJECT_ROOT / "model" / ".output" / "py_view_tower_line"
    model = TowerLineSystemModel(config_path=config_path, output_dir=model_output, wipe=True)
    model.build()
    html_path = (
        Path(output_path)
        if output_path is not None
        else PROJECT_ROOT / "py_view" / ".output" / "tower_line_dashboard.html"
    )
    return TowerLineDashboard(model).write_html(
        html_path,
        show_nodes=show_nodes,
        auto_open=auto_open,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成输电塔—线体系交互式 HTML 可视化。")
    parser.add_argument("--config", type=Path, help="塔线体系 JSON 配置文件。")
    parser.add_argument("--output", type=Path, help="输出 HTML 路径。")
    parser.add_argument("--show-nodes", action="store_true", help="默认显示全部节点。")
    parser.add_argument("--open", action="store_true", dest="auto_open", help="生成后在浏览器打开。")
    args = parser.parse_args()
    html_path = build_tower_line_view(
        config_path=args.config,
        output_path=args.output,
        show_nodes=args.show_nodes,
        auto_open=args.auto_open,
    )
    print(f"可视化已生成: {html_path.resolve()}")


if __name__ == "__main__":
    main()
